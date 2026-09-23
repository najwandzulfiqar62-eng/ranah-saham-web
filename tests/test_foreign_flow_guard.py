"""Pemindaian Smart Money tidak boleh menjatuhkan seluruh aplikasi.

LAPORAN NYATA 23 Sep 2026: "ini web nya kenapa kok ngelag/failed trus
ngescannya".

/api/foreign-flow mengunduh 250 emiten (scope bawaan di layar) atau 793
(scope 'all') LANGSUNG di dalam request, dan tidak punya satu pun penjagaan
yang sudah lama dipakai endpoint berat lain:

  - tanpa single-flight  -> tiap muat-ulang memulai pemindaian BARU
  - tanpa serve-stale    -> satu penolakan Yahoo = panel kosong
  - tanpa to_thread      -> loop pandas-nya menahan event loop

Yang membuatnya luput bukan kelalaian biasa: komentar di _warm_shared_caches
sudah MENYEBUT scope='all' "tetap on-demand (dgn single-flight +
serve-stale)". Kalimat itu tidak salah ketik, ia salah fakta -- penjagaannya
tidak pernah dipasang. Siapa pun yang membaca komentar itu akan mengira
bagian ini sudah beres dan berhenti memeriksa.

Berkas ini ada supaya klaim itu TIDAK bisa lagi cuma berupa kalimat.
"""
import asyncio
import inspect

import pytest
from fastapi import HTTPException

import web.app as app_module


@pytest.fixture
def tanpa_cache(monkeypatch):
    """Paksa jalur dingin: cache selalu meleset."""
    monkeypatch.setattr(app_module, "_cache_get", lambda k: None)
    monkeypatch.setattr(app_module, "_cache_set_durable", lambda k, v, ttl=None: None)


# ---------------------------------------------------------------------------
# 1. Single-flight
# ---------------------------------------------------------------------------

def test_permintaan_bersamaan_hanya_memindai_SEKALI(tanpa_cache, monkeypatch):
    """Inti keluhannya: halaman lambat -> orang memuat ulang -> jadi lebih
    lambat. Tanpa single-flight, bebannya tidak menumpuk melainkan BERLIPAT
    oleh ketidaksabaran, dan tiap salinan menahan thread unduhan sampai
    selesai. Lima permintaan bersamaan harus menghasilkan SATU pemindaian."""
    jumlah = {"n": 0}

    async def palsu(scope, cache_key):
        jumlah["n"] += 1
        await asyncio.sleep(0.05)      # meniru unduhan yang lama
        return {"akumulasi": [], "distribusi": [], "scope": scope}

    monkeypatch.setattr(app_module, "_build_foreign_flow", palsu)

    async def jalan():
        return await asyncio.gather(*[
            app_module.api_foreign_flow(scope="medium") for _ in range(5)
        ])

    hasil = asyncio.run(jalan())
    assert jumlah["n"] == 1, "tiap muat-ulang memulai pemindaian baru"
    assert all(h is hasil[0] for h in hasil), "semua harus dapat hasil yang SAMA"


def test_scope_berbeda_tidak_saling_menunggu(tanpa_cache, monkeypatch):
    """Single-flight dikunci per scope. Kalau tidak, orang yang membuka
    ~45 saham ikut menunggu pemindaian 793 saham milik orang lain selesai --
    memperbaiki satu antrean dengan membuat antrean baru."""
    dipakai = []

    async def palsu(scope, cache_key):
        dipakai.append(scope)
        return {"scope": scope}

    monkeypatch.setattr(app_module, "_build_foreign_flow", palsu)

    async def jalan():
        return await asyncio.gather(app_module.api_foreign_flow(scope="core"),
                                    app_module.api_foreign_flow(scope="all"))

    hasil = asyncio.run(jalan())
    assert sorted(dipakai) == ["all", "core"]
    assert {h["scope"] for h in hasil} == {"all", "core"}


# ---------------------------------------------------------------------------
# 2. Serve-stale
# ---------------------------------------------------------------------------

def test_yahoo_menolak_maka_data_lama_disajikan(tanpa_cache, monkeypatch):
    """Data beberapa menit lalu jauh lebih berguna daripada pesan error.
    Anomali volume tidak berubah dari menit ke menit; panel kosong berubah
    dari berguna jadi tidak berguna seketika."""
    async def gagal(scope, cache_key):
        raise RuntimeError("YFRateLimitError")

    monkeypatch.setattr(app_module, "_build_foreign_flow", gagal)
    monkeypatch.setattr(app_module, "_cache_get_stale",
                        lambda k: {"akumulasi": [{"kode": "BBCA"}], "scope": "medium"})

    hasil = asyncio.run(app_module.api_foreign_flow(scope="medium"))
    assert hasil["akumulasi"] == [{"kode": "BBCA"}]


def test_data_lama_DITANDAI_bukan_disamarkan(tanpa_cache, monkeypatch):
    """Menyajikan data lama diam-diam sebagai data hari ini adalah cara lain
    untuk berbohong -- orang mengambil keputusan uang dari angka ini."""
    async def gagal(scope, cache_key):
        raise RuntimeError("Yahoo menolak")

    monkeypatch.setattr(app_module, "_build_foreign_flow", gagal)
    monkeypatch.setattr(app_module, "_cache_get_stale", lambda k: {"akumulasi": []})

    hasil = asyncio.run(app_module.api_foreign_flow(scope="medium"))
    assert hasil["basi"] is True


def test_gagal_DAN_tidak_ada_data_lama_tetap_melapor_error(tanpa_cache, monkeypatch):
    """Serve-stale tidak boleh berubah jadi alat menyembunyikan kerusakan.
    Kalau memang tidak ada apa pun untuk disajikan, katakan gagal."""
    async def gagal(scope, cache_key):
        raise RuntimeError("Yahoo menolak")

    monkeypatch.setattr(app_module, "_build_foreign_flow", gagal)
    monkeypatch.setattr(app_module, "_cache_get_stale", lambda k: None)

    with pytest.raises(HTTPException) as e:
        asyncio.run(app_module.api_foreign_flow(scope="medium"))
    assert e.value.status_code == 502


# ---------------------------------------------------------------------------
# 3. Scope liar
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("liar", ["ALL", "semua", "", "../etc", "medium "])
def test_scope_tak_dikenal_jatuh_ke_yang_paling_ringan(tanpa_cache, monkeypatch, liar):
    """Scope yang tidak dikenal harus jadi 'core' (~45 saham), BUKAN 'all'
    (793). Salah arah di sini berarti nilai sembarangan dari luar bisa
    memicu pemindaian terberat yang ada."""
    dipakai = []

    async def palsu(scope, cache_key):
        dipakai.append(scope)
        return {"scope": scope}

    monkeypatch.setattr(app_module, "_build_foreign_flow", palsu)
    asyncio.run(app_module.api_foreign_flow(scope=liar))
    assert dipakai == ["core"]


# ---------------------------------------------------------------------------
# 4. Loop pandas-nya sinkron & tahan data cacat
# ---------------------------------------------------------------------------

def test_compute_sm_items_sinkron_supaya_bisa_masuk_worker_thread():
    """Harus fungsi biasa, bukan coroutine -- asyncio.to_thread hanya bisa
    memindahkan yang sinkron. Kalau suatu hari ia diubah jadi `async def`,
    to_thread-nya diam-diam berhenti berguna dan event loop kembali tertahan
    tanpa ada yang gagal."""
    assert not inspect.iscoroutinefunction(app_module._compute_sm_items)


def test_satu_emiten_rusak_tidak_menjatuhkan_sisanya():
    """793 emiten diproses sekaligus; selalu ada yang datanya aneh. Satu
    baris cacat tidak boleh mengosongkan seluruh panel."""
    hasil = app_module._compute_sm_items(
        ["RUSAK.JK", "KOSONG.JK"],
        {"RUSAK.JK": "ini bukan DataFrame"},   # KOSONG.JK sengaja tak ada
    )
    assert hasil == []
