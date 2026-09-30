"""Perintah `smartmoney` di bot WhatsApp.

Fitur ini punya satu risiko yang lebih besar daripada bug teknis: NAMANYA
MENJANJIKAN LEBIH BANYAK DARIPADA YANG DIUKUR DATANYA. Yang dihitung adalah
volume yang tidak biasa dibandingkan rata-rata 20 harinya. Siapa yang membeli
-- asing, institusi, atau satu orang kaya yang sedang iseng -- tidak ada di
satu pun sumber data yang dipakai aplikasi ini.

Orang bertaruh uang atas pesan bot ini, dan pesannya tiba di WhatsApp tanpa
konteks layar, tanpa legenda, tanpa tooltip. Karena itu syarat dan
keterbatasannya diuji di sini sama ketatnya dengan angkanya.
"""
import pytest

# Fixture `wa_bersih` (DB akses kosong + secret bot + jeda per-nomor direset)
# tinggal di test_wa_bot.py, bukan conftest. Diimpor supaya pytest melihatnya
# di modul ini juga -- menyalinnya akan membuat dua penyiapan yang bisa
# berbeda diam-diam.
from tests.test_wa_bot import wa_bersih  # noqa: F401

SECRET = "rahasia-wa-bot-khusus-pytest"


def _contoh(**ubah) -> dict:
    dasar = {
        "total_scan": 250, "net_score": 1,
        "akumulasi": [{"kode": "UNTR", "pola": "Akumulasi", "harga": 26500,
                       "chg1": 4.27, "chg5": 6.1, "vol_ratio": 3.2, "rsi": 61.2,
                       "likuiditas": "Sangat Likuid", "grup": "Astra",
                       "hari_lalu": 0, "vol_ratio_percentile": 100.0}],
        "distribusi": [{"kode": "CARE", "pola": "Distribusi", "harga": 129,
                        "chg1": -3.06, "chg5": -8.2, "vol_ratio": 8.67,
                        "rsi": 31.0, "likuiditas": "Likuid",
                        "grup": "Independen", "hari_lalu": 4,
                        "vol_ratio_percentile": 100.0}],
    }
    dasar.update(ubah)
    return dasar


# ---------------------------------------------------------------------------
# Kejujuran isi pesannya
# ---------------------------------------------------------------------------

def test_pesan_menyangkal_klaim_yang_ada_di_namanya():
    """"Smart Money" terdengar seperti bot tahu siapa yang membeli. Ia tidak
    tahu, dan pesannya harus mengatakan itu -- di WhatsApp tidak ada legenda
    atau tooltip yang bisa meluruskannya belakangan."""
    from web.app import _wa_fmt_smartmoney

    teks = _wa_fmt_smartmoney(_contoh())
    assert "bukan aliran dana asing" in teks
    assert "siapa yang membeli tidak ada di data ini" in teks


def test_arah_disebut_sebagai_kesimpulan_bukan_pengetahuan():
    """Volume besar sendiri tidak berarah. Yang membedakan "terkumpul" dari
    "dilepas" cuma gerak harganya -- itu kesimpulan, dan harus terbaca
    sebagai kesimpulan."""
    from web.app import _wa_fmt_smartmoney

    teks = _wa_fmt_smartmoney(_contoh())
    assert "bisa juga berarti dilepas" in teks
    assert "bukan diketahui" in teks


# ---------------------------------------------------------------------------
# Umur anomali -- yang basi tidak boleh terbaca seperti yang baru
# ---------------------------------------------------------------------------

def test_anomali_lama_diberi_tanda_umur():
    """Anomali empat hari lalu dan anomali hari ini menuntut tindakan yang
    berbeda, tapi keduanya muncul di daftar yang sama. Tanpa penanda umur,
    yang basi terbaca seperti yang baru."""
    from web.app import _wa_fmt_smartmoney

    teks = _wa_fmt_smartmoney(_contoh())
    assert "4 hari lalu, bukan hari ini" in teks


def test_anomali_hari_ini_TIDAK_diberi_tanda_umur():
    """"0 hari lalu" di tiap baris cuma menambah teks tanpa menambah arti,
    dan justru membuat penanda yang sungguhan jadi kurang menonjol."""
    from web.app import _wa_fmt_smartmoney

    teks = _wa_fmt_smartmoney(_contoh())
    assert "0 hari lalu" not in teks


# ---------------------------------------------------------------------------
# Satu angka, satu kata -- bot dan layar tidak boleh bercerita beda
# ---------------------------------------------------------------------------

def test_peringkat_memakai_kata_yang_sama_dengan_panel_web():
    """Panel web menulis "Top X% di kelas likuiditasnya". Menuliskannya beda
    di bot akan membuat satu angka yang sama terbaca seperti dua hal."""
    from web.app import _wa_fmt_smartmoney

    teks = _wa_fmt_smartmoney(_contoh())
    assert "Top 0% di kelas likuiditasnya" in teks


def test_semua_baris_ditampilkan_tidak_dipangkas():
    """Pernah jadi keluhan nyata: versi ringkas memangkas isi sampai yang
    dicari orang justru hilang. Yang tampil di web harus tampil juga di sini."""
    from web.app import _wa_fmt_smartmoney

    banyak = [{"kode": f"AA{i:02d}", "pola": "Akumulasi", "harga": 100 + i,
               "chg1": 1.0, "chg5": 2.0, "vol_ratio": 2.0, "rsi": 55.0,
               "likuiditas": "Likuid", "grup": "Independen", "hari_lalu": 0,
               "vol_ratio_percentile": 90.0} for i in range(20)]
    teks = _wa_fmt_smartmoney(_contoh(akumulasi=banyak, distribusi=[]))
    for i in range(20):
        assert f"AA{i:02d}" in teks


# ---------------------------------------------------------------------------
# Tahan data cacat -- pelajaran 24 Sep 2026
# ---------------------------------------------------------------------------

def test_tidak_ada_anomali_dijawab_jujur_bukan_error():
    """Hari sepi itu hasil yang sah, bukan kerusakan. Menjawabnya dengan
    error membuat orang mengira botnya rusak lalu mengulang terus."""
    from web.app import _wa_fmt_smartmoney

    teks = _wa_fmt_smartmoney({"total_scan": 250, "akumulasi": [], "distribusi": []})
    assert "Tidak ada anomali" in teks
    assert "wajar" in teks


@pytest.mark.parametrize("rusak", [None, [], "bukan dict", 0])
def test_payload_rusak_tidak_meledak(rusak):
    """Perintah bot tidak boleh melempar. Yang dilempar di sini berubah jadi
    diam di WhatsApp, dan diam adalah kegagalan yang paling membingungkan."""
    from web.app import _wa_fmt_smartmoney

    assert isinstance(_wa_fmt_smartmoney(rusak), str)


def test_field_yang_hilang_tidak_meledak():
    """Persis kelas bug yang menjatuhkan halaman Pemegang Saham 24 Sep 2026:
    satu field bernilai None, seluruh panel mati. Baris seadanya jauh lebih
    baik daripada perintah yang tidak menjawab."""
    from web.app import _wa_fmt_smartmoney

    teks = _wa_fmt_smartmoney({
        "total_scan": 250,
        "akumulasi": [{"kode": "BBCA", "pola": "Akumulasi", "harga": 9000,
                       "vol_ratio": 2.1}],   # chg1/chg5/rsi/likuiditas TIDAK ADA
        "distribusi": [],
    })
    assert "BBCA" in teks


# ---------------------------------------------------------------------------
# Ujung ke ujung lewat endpoint bot
# ---------------------------------------------------------------------------

def _kirim(client, teks, nomor="6281234567890"):
    return client.post("/api/wa/command",
                       json={"from": f"{nomor}@s.whatsapp.net", "text": teks},
                       headers={"Authorization": f"Bearer {SECRET}"})


@pytest.mark.parametrize("perintah", ["smartmoney", "sm", "bandar", "akumulasi"])
def test_semua_sebutan_menjawab(client, wa_bersih, monkeypatch, perintah):
    """`bandar` itu kata yang benar-benar dipakai orang untuk konsep ini.
    Perintah yang hampir benar dijawab dengan diam adalah bentuk kegagalan
    yang paling membingungkan -- orang tidak tahu botnya mati, pesannya tidak
    sampai, atau ketikannya salah, dan ketiganya menuntut tindakan berbeda."""
    import web.app as app_module
    from tests.test_wa_bot import _daftarkan_approved

    async def _palsu(scope="core"):
        assert scope == "medium", "scope sempit membuang jangkauan tanpa alasan"
        return _contoh()

    monkeypatch.setattr(app_module, "api_foreign_flow", _palsu)
    _daftarkan_approved()
    app_module._wa_last_reply.clear()

    balasan = _kirim(client, perintah).json()["reply"]
    assert "UNTR" in balasan and "CARE" in balasan


def test_tercantum_di_menu_bantuan():
    """Fitur yang tidak disebut di `bantuan` sama saja dengan tidak ada:
    tidak ada yang bisa menebak kata kuncinya."""
    from web.app import _WA_BANTUAN

    assert "smartmoney" in _WA_BANTUAN and "bandar" in _WA_BANTUAN
