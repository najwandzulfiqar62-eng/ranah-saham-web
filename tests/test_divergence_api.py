"""Penjaga endpoint & bot untuk panel Pemulihan.

Berkas ini mengunci kelas-kelas bug yang sudah pernah terjadi di proyek
ini, bukan sekadar "endpointnya jalan":

  - permintaan pengunjung memicu pemindaian dingin (scaling #1)
  - loop sinkron membekukan event loop
  - kunci cache tidak berversi -> kolom diam-diam kosong sesudah deploy
  - sumber gagal -> halaman kosong, padahal hasil lama masih ada
  - syarat di layar berbeda dengan syarat di bot
"""
import asyncio
import inspect

import pytest

import web.app as app_module

UKURAN = {"n": 59, "per_tahun": 30, "naik_pct": 62.7, "unggul_pct": 4.11,
          "horizon_hari": 20, "dasar_pct": 1.95, "diukur": "2026-10-10"}


def _item(kode="PTBA", kuat=True, **ubah):
    d = {"kode": kode, "setup_id": f"{kode}:2026-09-01:2026-09-15",
         "tanggal_dasar1": "2026-09-01", "tanggal_dasar2": "2026-09-15",
         "harga_dasar1": 3720, "harga_dasar2": 3378, "rsi_dasar1": 29.4,
         "rsi_dasar2": 35.1, "jatuh_pct": -9.2, "gap_rsi": 5.7,
         "jarak_bar": 10, "umur_bar": 6, "harga": 3380, "kuat": kuat}
    d.update(ubah)
    return d


def _payload(items=None):
    items = items if items is not None else [_item()]
    return {"items": items, "kuat": sum(1 for x in items if x["kuat"]),
            "total": len(items), "universe": 178, "ukuran": UKURAN}


# ---------------------------------------------------------------------------
# Permintaan pengunjung tidak boleh memicu pemindaian
# ---------------------------------------------------------------------------

def test_cache_dingin_dijawab_SEKETIKA_bukan_memindai(monkeypatch):
    """Scaling #1 di proyek ini: memindai 178 emiten atas permintaan satu
    pengunjung membuat SELURUH aplikasi tersendat, bukan cuma halaman itu.
    Yang menanggung pemindaian adalah pemanas cache."""
    dipanggil = []

    async def _jangan(*a, **k):
        dipanggil.append(1)
        return _payload()

    monkeypatch.setattr(app_module, "_cache_get", lambda k: None)
    monkeypatch.setattr(app_module, "_cache_get_stale", lambda k: None)
    monkeypatch.setattr(app_module, "_build_divergence", _jangan)

    hasil = asyncio.run(app_module.api_divergence())
    assert hasil["menyiapkan"] is True
    assert dipanggil == [], "permintaan pengunjung memicu pemindaian dingin"


def test_cache_hangat_disajikan_apa_adanya(monkeypatch):
    monkeypatch.setattr(app_module, "_cache_get",
                        lambda k: _payload() if k == app_module._DIVERGENCE_CACHE_KEY else None)
    assert asyncio.run(app_module.api_divergence())["total"] == 1


def test_sumber_gagal_menyajikan_hasil_lama_DENGAN_tanda(monkeypatch):
    """Hasil kemarin jauh lebih berguna daripada halaman kosong -- asal
    dikatakan bahwa ia hasil kemarin."""
    monkeypatch.setattr(app_module, "_cache_get", lambda k: None)
    monkeypatch.setattr(app_module, "_cache_get_stale", lambda k: _payload())
    hasil = asyncio.run(app_module.api_divergence())
    assert hasil["basi"] is True and hasil["total"] == 1


# ---------------------------------------------------------------------------
# Bentuk & pemakaian
# ---------------------------------------------------------------------------

def test_kunci_cache_berversi():
    """Mengubah bentuk payload tanpa menaikkan versi kunci = sesudah deploy
    pembaca mendapat bentuk LAMA dari cache dan kolomnya diam-diam kosong.
    Bukan error, cuma salah -- dan karena itu lama tidak ketahuan."""
    assert app_module._DIVERGENCE_CACHE_KEY.split(":")[-1].startswith("v")


def test_loop_pemindaian_sinkron_supaya_bisa_masuk_worker_thread():
    """asyncio.to_thread hanya bisa memindahkan yang sinkron. Kalau suatu
    hari ia diubah jadi `async def`, to_thread-nya diam-diam berhenti
    berguna dan event loop kembali tertahan tanpa ada yang gagal."""
    assert not inspect.iscoroutinefunction(app_module._pindai_divergence)


def test_pemindaian_tahan_data_cacat():
    """178 emiten diproses sekaligus; satu DataFrame aneh tidak boleh
    mengosongkan seluruh panel."""
    hasil = app_module._pindai_divergence(
        ["RUSAK.JK", "HILANG.JK"], {"RUSAK.JK": "bukan DataFrame"})
    assert hasil == []


# ---------------------------------------------------------------------------
# Bot
# ---------------------------------------------------------------------------

def test_bot_hanya_mendaftar_yang_KUAT():
    """Bukan pemangkasan demi ringkas. Diukur pada 283 setup unik: setup
    yang TIDAK berlabel kuat berkinerja -2,26% DI BAWAH rata-rata pasar.
    Mencantumkannya berarti mengirimi orang daftar yang lebih buruk
    daripada menebak."""
    teks = app_module._wa_fmt_pemulihan(
        _payload([_item("PTBA", True), _item("ASBI", False)]))
    assert "PTBA" in teks and "ASBI" not in teks


def test_bot_mengatakan_KENAPA_yang_lemah_tidak_didaftar():
    """Daftar yang menyusut tanpa penjelasan terbaca seperti fitur rusak."""
    teks = app_module._wa_fmt_pemulihan(_payload())
    assert "di BAWAH rata-rata pasar" in teks


def test_bot_menyebut_angka_yang_TERUKUR_bukan_janji():
    teks = app_module._wa_fmt_pemulihan(_payload())
    assert "62.7% naik" in teks and "59 kejadian" in teks


def test_bot_mengaku_sinyalnya_terlambat_tiga_hari():
    """Jeda konfirmasi itu harga kejujuran, dan penerimanya berhak tahu --
    bukan karena rendah hati, tapi karena 3 hari mengubah harga entry."""
    assert "terlambat 3 hari" in app_module._wa_fmt_pemulihan(_payload())


def test_bot_hari_tanpa_setup_kuat_dijawab_jujur():
    """Hari sepi itu hasil yang sah. Menjawabnya dengan error membuat orang
    mengira botnya rusak lalu mengulang terus."""
    teks = app_module._wa_fmt_pemulihan(_payload([_item("ASBI", False)]))
    assert "Tidak ada setup KUAT" in teks and "Wajar" in teks


def test_bot_cache_belum_siap_dijawab_jujur():
    teks = app_module._wa_fmt_pemulihan({"menyiapkan": True})
    assert "sedang disiapkan" in teks


@pytest.mark.parametrize("rusak", [None, [], "bukan dict", 0])
def test_bot_payload_rusak_tidak_meledak(rusak):
    """Yang dilempar di sini berubah jadi DIAM di WhatsApp, dan diam adalah
    kegagalan yang paling membingungkan."""
    assert isinstance(app_module._wa_fmt_pemulihan(rusak), str)


def test_tercantum_di_menu_bantuan():
    assert "pemulihan" in app_module._WA_BANTUAN
