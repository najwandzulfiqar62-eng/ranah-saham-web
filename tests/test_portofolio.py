"""Portofolio anggota: bot tahu "kamu lagi bagaimana", bukan cuma "pasar".

Permintaan penulis 21 Sep 2026, beserta syaratnya: "ide bagus buat kan dong
eh tapi itu sekalian kasih tau kita entry dimana kan?" -- portofolio tanpa
jawaban "lalu harus apa, di harga berapa" cuma jadi kalkulator untung-rugi,
dan itu sudah ada di aplikasi sekuritas mana pun.
"""
import pytest

# Fixture bot WhatsApp dipakai ulang dari test_wa_bot.py -- uji privasi di
# bawah harus melewati jalur perintah yang SUNGGUHAN, bukan tiruan.
from tests.test_wa_bot import wa_bersih  # noqa: F401


@pytest.fixture
def porto():
    from core.database import get_db

    import core.portofolio as pf
    pf.ensure_porto_tables()
    with get_db() as conn:
        conn.execute("DELETE FROM porto_transaksi")
    yield pf
    with get_db() as conn:
        conn.execute("DELETE FROM porto_transaksi")


# ---------------------------------------------------------------------------
# Hitungan posisi
# ---------------------------------------------------------------------------

def test_beli_dua_kali_merata_ratakan_harganya(porto):
    porto.catat(1, "BBCA", "BELI", 5, 8000)
    p = porto.catat(1, "bbca", "BELI", 5, 7000)
    assert p["lot"] == 10
    assert p["harga_avg"] == 7500


def test_jual_mengurangi_lot_tanpa_mengubah_rata_rata(porto):
    """Rata-rata BERGERAK, seperti aplikasi sekuritas di Indonesia. Angka
    yang berbeda dari broker akan dianggap salah oleh penggunanya, seberapa
    pun benarnya secara akuntansi."""
    porto.catat(1, "BBCA", "BELI", 10, 7500)
    p = porto.catat(1, "BBCA", "JUAL", 4, 9000)
    assert p["lot"] == 6
    assert p["harga_avg"] == 7500, "menjual untung tidak boleh menggeser rata-rata"


def test_menjual_lebih_banyak_dari_yang_dipegang_ditolak(porto):
    """Hampir selalu salah ketik. Ditolak di sini, bukan dibiarkan jadi
    posisi negatif yang baru ketahuan aneh berhari-hari kemudian."""
    porto.catat(1, "BBCA", "BELI", 2, 8000)
    with pytest.raises(ValueError, match="memegang"):
        porto.catat(1, "BBCA", "JUAL", 5, 8000)


def test_posisi_habis_tidak_muncul_lagi(porto):
    porto.catat(1, "BBCA", "BELI", 3, 8000)
    porto.catat(1, "BBCA", "JUAL", 3, 8500)
    assert porto.posisi_user(1) == []


def test_posisi_milik_orang_lain_tidak_tercampur(porto):
    """Satu tabel, banyak anggota. Kalau penyaringan per user_id pernah
    luput, seseorang melihat posisi orang lain -- kebocoran yang paling
    tidak bisa dimaafkan di fitur ini."""
    porto.catat(1, "BBCA", "BELI", 5, 8000)
    porto.catat(2, "TLKM", "BELI", 5, 3000)
    assert [p["kode"] for p in porto.posisi_user(1)] == ["BBCA"]
    assert [p["kode"] for p in porto.posisi_user(2)] == ["TLKM"]


def test_hapus_membatalkan_catatan_bukan_mencatat_penjualan(porto):
    """Dua hal yang berbeda: salah ketik dibatalkan, penjualan sungguhan
    dicatat. Mencampurnya membuat riwayat berbohong."""
    porto.catat(1, "BBCA", "BELI", 5, 8000)
    assert porto.hapus_kode(1, "BBCA") == 1
    assert porto.posisi_user(1) == []
    assert porto.riwayat_kode(1, "BBCA") == []


@pytest.mark.parametrize("lot,harga", [(0, 8000), (-1, 8000), (5, 0), (5, -3)])
def test_angka_tidak_masuk_akal_ditolak(porto, lot, harga):
    with pytest.raises(ValueError):
        porto.catat(1, "BBCA", "BELI", lot, harga)


def test_modal_dihitung_per_lembar_bukan_per_lot(porto):
    """Satu lot = 100 lembar di BEI. Salah di sini membuat seluruh nominal
    rupiah meleset 100 kali lipat."""
    p = porto.catat(1, "BBCA", "BELI", 5, 8000)
    assert p["modal"] == 5 * 8000 * porto.LEMBAR_PER_LOT == 4_000_000


# ---------------------------------------------------------------------------
# Tampilan: perintah DAN levelnya
# ---------------------------------------------------------------------------

def _baris(kode="BBCA", lot=5, avg=8000, harga=8450, level=None, rek=None):
    untung_pct = (harga / avg - 1) * 100 if harga and avg else None
    return {"kode": kode, "lot": lot, "harga_avg": avg,
            "modal": lot * avg * 100, "harga": harga,
            "untung_pct": untung_pct,
            "untung_rp": (harga - avg) * lot * 100 if harga else None,
            "rekomendasi": rek, "wajar": None, "level": level or []}


def test_posisi_rugi_diberi_level_menambah():
    """INI syarat yang diminta penulis: "sekalian kasih tau kita entry
    dimana kan?" Tanpa baris ini, portofolio cuma kalkulator untung-rugi."""
    import web.app as app_module

    b = _baris(kode="ERAA", avg=720, harga=625,
               level=[{"label": "Support S1", "price": 600, "new_avg_price": 660},
                      {"label": "Batas bawah wajar", "price": 560}])
    teks = app_module._wa_fmt_porto([b], None)
    assert "Kalau mau menambah" in teks
    assert "Support S1 Rp600" in teks
    assert "rata-rata Rp660" in teks
    assert "TIDAK wajib" in teks, "menambah posisi tidak boleh terbaca sebagai anjuran"


def test_posisi_untung_tidak_disodori_level_menambah():
    """Menambah di posisi yang sudah untung itu keputusan yang sama sekali
    berbeda -- menambah risiko pada untung yang belum direalisasikan.
    Menyodorkannya di sini akan terbaca seperti anjuran padahal bukan."""
    import web.app as app_module

    b = _baris(level=[{"label": "Support S1", "price": 7000}])
    teks = app_module._wa_fmt_porto([b], None)
    assert "Kalau mau menambah" not in teks


def test_ihsg_lemah_disebut_saat_menyarankan_level():
    """Menambah posisi saat indeksnya sendiri rontok itu keputusan yang
    berbeda. Menyebut levelnya tanpa menyebut ini akan menyesatkan."""
    import web.app as app_module

    b = _baris(kode="ERAA", avg=720, harga=625,
               level=[{"label": "Support S1", "price": 600}])
    teks = app_module._wa_fmt_porto(
        [b], {"prediction": "BEARISH", "daily_change": -1.4,
              "bearish_score": 7, "bullish_score": 2})
    assert "IHSG sedang lemah" in teks


def test_portofolio_kosong_mengajari_cara_memakainya():
    import web.app as app_module

    teks = app_module._wa_fmt_porto([], None)
    assert "beli BBCA 8000 5" in teks
    assert "pribadi" in teks


def test_untung_dan_rugi_dipisah_serta_ada_totalnya():
    import web.app as app_module

    teks = app_module._wa_fmt_porto(
        [_baris(), _baris(kode="ERAA", avg=720, harga=625)], None)
    assert "*Untung* (1)" in teks and "*Rugi* (1)" in teks
    assert "Mengambang" in teks


def test_harga_gagal_terambil_tidak_menghilangkan_posisinya():
    """Satu harga yang gagal diambil tidak boleh membuat posisinya lenyap
    dari daftar -- orang akan mengira catatannya hilang."""
    import web.app as app_module

    b = _baris(kode="XXXX", harga=None)
    b["untung_pct"] = b["untung_rp"] = None
    teks = app_module._wa_fmt_porto([b], None)
    assert "XXXX" in teks and "belum terambil" in teks


# ---------------------------------------------------------------------------
# PRIVASI -- yang paling tidak boleh salah
# ---------------------------------------------------------------------------

def test_perintah_portofolio_ditolak_di_grup(client, wa_bersih):
    """Isinya nominal uang orang, dan grupnya berisi banyak anggota.

    Ditolak, BUKAN disensor sebagian: menyamarkan rupiah tapi tetap menyebut
    kode dan jumlah lot sama saja membocorkan posisi seseorang ke seluruh
    grup."""
    from tests.test_wa_bot import SECRET, _daftarkan_approved

    _daftarkan_approved()
    r = client.post("/api/wa/command",
                    json={"from": "6281234567890@s.whatsapp.net", "text": "porto",
                          "chat": "628999-1@g.us", "grup": True},
                    headers={"Authorization": f"Bearer {SECRET}"})
    balas = r.json()["reply"] or ""
    assert "pribadi" in balas and "japri" in balas
    assert "Rp" not in balas, "nominal bocor di grup"


def test_sidecar_membalas_ke_asal_pesan_bukan_selalu_ke_grup():
    """Pengaman KEDUA, dan yang ini di berkas lain.

    Kalau sidecar tetap mengirim balasan ke GROUP_JID, jawaban `porto` yang
    diminta lewat japri justru TERKIRIM KE GRUP -- posisi dan nominal uang
    seseorang dibacakan ke semua orang. Penolakan di sisi Python tidak
    menolong kalau jalur pengirimannya sendiri salah alamat."""
    import io
    import os

    akar = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    js = io.open(os.path.join(akar, "wa-bot", "index.js"), encoding="utf-8").read()
    # Bagian penanganan pesan masuk (bukan endpoint siaran /send, yang
    # memang selalu ke grup).
    penanganan = js.split('sock.ev.on("messages.upsert"')[1].split("startSock()")[0]
    assert "kirimTeks(asal," in penanganan, "balasan teks masih dipaksa ke grup"
    assert "sendMessage(GROUP_JID" not in penanganan, "media masih dipaksa ke grup"


def test_sidecar_lama_yang_belum_kirim_asal_dianggap_grup(client, wa_bersih):
    """GAGAL-TERTUTUP. Sidecar dan app di-deploy terpisah, jadi akan ada
    jendela waktu ketika app sudah baru tapi sidecar masih lama dan belum
    mengirim asal percakapan.

    Menolak karena salah tebak cuma merepotkan; membocorkan posisi seseorang
    ke grup karena salah tebak tidak bisa ditarik kembali."""
    from tests.test_wa_bot import SECRET, _daftarkan_approved

    _daftarkan_approved()
    r = client.post("/api/wa/command",
                    json={"from": "6281234567890@s.whatsapp.net", "text": "porto"},
                    headers={"Authorization": f"Bearer {SECRET}"})
    balas = r.json()["reply"] or ""
    assert "japri" in balas, "tanpa keterangan asal, harus dianggap grup"


def test_japri_dilayani(client, wa_bersih):
    """Dan sebaliknya: kalau jelas japri, perintahnya harus jalan."""
    from tests.test_wa_bot import SECRET, _daftarkan_approved

    _daftarkan_approved()
    r = client.post("/api/wa/command",
                    json={"from": "6281234567890@s.whatsapp.net", "text": "porto",
                          "chat": "6281234567890@s.whatsapp.net", "grup": False},
                    headers={"Authorization": f"Bearer {SECRET}"})
    balas = r.json()["reply"] or ""
    assert "Portofolio kamu" in balas
    assert "japri" not in balas
