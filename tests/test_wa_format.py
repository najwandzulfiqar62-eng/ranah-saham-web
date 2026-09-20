"""Gaya penulisan pesan WhatsApp (core/wa_format.py).

Permintaan penulis 20 Sep 2026: "penulisan bot wa bisa lebih rapih ga biar
orang bacanya ga bingung kebanyakan teks gitu dimana pun ya".

"Di mana pun" itu yang menentukan bentuknya: aturannya dipasang di SATU titik
keluar, bukan dititipkan ke dua belas penyusun pesan. Aturan gaya yang harus
diingat orang di banyak tempat adalah aturan yang cepat atau lambat
berbeda-beda.
"""
import pytest

from core.wa_format import (BATAS_PESAN, bagian, batasi, padat, potong,
                            rapikan, siap_kirim)


# ---------------------------------------------------------------------------
# rapikan: jarak & bagian kosong
# ---------------------------------------------------------------------------

def test_baris_kosong_berlebih_dipadatkan():
    """Tiga baris kosong berturut-turut itu ruang yang tidak memberi tahu
    apa pun, dan di layar HP ia mendorong isi berikutnya keluar layar."""
    assert rapikan("a\n\n\n\n\nb") == "a\n\nb"


def test_tidak_ada_baris_kosong_tepat_di_bawah_judul():
    """Judul dan isinya satu kesatuan; dipisah baris kosong, keduanya
    terbaca seperti dua hal yang tidak berhubungan."""
    assert rapikan("*Judul*\n\n• isi") == "*Judul*\n• isi"


def test_judul_tanpa_isi_dibuang():
    """INI yang paling sering terjadi: datanya kebetulan kosong, tapi
    judulnya tetap tercetak -- baris yang memakan tempat tanpa memberi tahu
    apa pun, dan muncul berkali-kali dalam satu pesan."""
    hasil = rapikan("*Ada isinya*\n• satu\n\n*Kosong*\n\n*Juga kosong*")
    assert hasil == "*Ada isinya*\n• satu"


def test_judul_terakhir_yang_menggantung_ikut_dibuang():
    """Judul di ujung pesan paling sering menggantung, karena bagian
    terakhirlah yang datanya paling mungkin belum ada."""
    assert rapikan("• isi\n\n*Menggantung*") == "• isi"


def test_baris_kosong_di_awal_dan_akhir_dibuang():
    assert rapikan("\n\n  \nisi\n\n  \n") == "isi"


def test_rapikan_tidak_pernah_membuang_isi():
    """Perapian yang diam-diam menghapus kalimat membuat kesalahan jauh
    lebih sulit dilacak daripada sekadar pesan yang kurang rapi."""
    asli = "*Judul*\n• satu\n• dua\n\n*Lain*\n_catatan penting_"
    hasil = rapikan(asli)
    for potongan in ("satu", "dua", "catatan penting", "*Judul*", "*Lain*"):
        assert potongan in hasil


@pytest.mark.parametrize("masukan", ["", None])
def test_kosong_tidak_meledak(masukan):
    assert rapikan(masukan) == ""


# ---------------------------------------------------------------------------
# bagian & padat: menyusun yang sudah pendek sejak awal
# ---------------------------------------------------------------------------

def test_bagian_kosong_tidak_menghasilkan_judul():
    assert bagian("Indikator", []) == []
    assert bagian("Indikator", ["", "   ", None]) == []


def test_bagian_membatasi_butir_dan_menyebut_sisanya():
    """Sepuluh butir berturut-turut berhenti terbaca sebagai daftar; ia jadi
    dinding. Yang dipotong tetap DISEBUT jumlahnya -- memotong diam-diam
    membuat orang tidak tahu ada yang hilang."""
    hasil = bagian("Daftar", [f"butir {i}" for i in range(10)], maks=3)
    assert hasil[0] == "*Daftar*"
    assert len([b for b in hasil if b.startswith("• ")]) == 3
    assert "7 lainnya" in hasil[-1]


def test_padat_menggabungkan_nilai_pendek_jadi_satu_baris():
    """Enam baris "• RSI: 62" menghabiskan enam baris layar untuk enam kata."""
    assert padat([("RSI", 62), ("MACD", "bullish"), ("Vol", "1,4×")]) == \
        "RSI 62 · MACD bullish · Vol 1,4×"


def test_padat_membuang_yang_kosong():
    assert padat([("RSI", None), ("MACD", "bullish"), ("Vol", "")]) == "MACD bullish"


def test_potong_memenggal_di_batas_kata():
    hasil = potong("satu dua tiga empat lima enam tujuh delapan", batas=20)
    assert hasil.endswith("…")
    assert "delapa" not in hasil, "terpenggal di tengah kata"
    assert len(hasil) <= 21


def test_potong_membiarkan_yang_sudah_pendek():
    assert potong("pendek saja", batas=50) == "pendek saja"


# ---------------------------------------------------------------------------
# batasi: jaring pengaman, bukan alat utama
# ---------------------------------------------------------------------------

def test_kalau_sampai_memotong_potongnya_di_batas_bagian():
    """Jaring pengaman ini hampir tidak pernah bekerja (lihat uji batas
    bawaan di bawah). Kalau sampai bekerja, potongannya harus di batas
    bagian -- dipotong di tengah kalimat membuat pesannya terbaca seperti
    rusak."""
    teks = "\n\n".join(f"*Bagian {i}*\n• isi yang cukup panjang sekali" for i in range(80))
    hasil = batasi(teks, batas=300)
    assert len(hasil) < 500
    assert "terlalu panjang" in hasil
    assert not hasil.split("\n\n_Pesan")[0].rstrip().endswith("isi yang cuku")


def test_pesan_pendek_tidak_disentuh():
    assert batasi("pendek", batas=100) == "pendek"


def test_batas_bawaan_tidak_boleh_memotong_pesan_yang_wajar():
    """INI pelajarannya, dan mahal.

    Versi pertama memasang 3000 karakter. Saat pasar kuat, perintah `sinyal`
    menghasilkan 71 emiten aktif dan 67 emiten berpuncak di atas +20% --
    pesannya terpotong sampai TIDAK ADA satu pun sinyal tersisa. Pembaca
    menerima ringkasan pencapaian tanpa satu pun hal yang bisa
    ditindaklanjuti: kebalikan persis dari guna perintah itu.

    Rapi bukan berarti dipotong. Yang membuat pesan enak dibaca adalah
    kalimat yang padat dan urutan yang benar. Batas ini harus cukup besar
    untuk menampung pesan terpanjang yang WAJAR, supaya ia cuma menahan
    keluaran yang benar-benar liar."""
    assert BATAS_PESAN >= 20000, (
        "batas terlalu kecil — pesan `sinyal` saat pasar kuat bisa 6.000+ "
        "karakter dan akan terpotong di tempat yang salah")


def test_siap_kirim_merapikan_lalu_membatasi():
    assert siap_kirim("*Kosong*\n\n\n*Isi*\n• a") == "*Isi*\n• a"


# ---------------------------------------------------------------------------
# Dipasang di titik keluar, bukan dititipkan ke penyusun pesan
# ---------------------------------------------------------------------------

def test_kedua_jalur_keluar_memakai_gaya_yang_sama():
    """Dua jalur: balasan perintah (/api/wa/command) dan siaran
    (send_wa_text). Kalau salah satunya luput, separuh pesan bot tetap
    berantakan -- dan yang luput itu tidak akan ketahuan sampai ada yang
    memandanginya di HP."""
    import io
    import os

    akar = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    app = io.open(os.path.join(akar, "web", "app.py"), encoding="utf-8").read()
    notify = io.open(os.path.join(akar, "core", "whatsapp_notify.py"),
                     encoding="utf-8").read()

    # Jendelanya dilebarkan seiring fungsi itu tumbuh (pengecekan asal
    # percakapan untuk perintah portofolio, 21 Sep 2026). Ini pemeriksaan
    # kasar yang gunanya memastikan pemanggilannya ADA, bukan di mana.
    perintah = app.split("async def api_wa_command")[1][:2500]
    assert "siap_kirim" in perintah, "balasan perintah tidak dirapikan"
    kirim = notify.split("async def send_wa_text")[1][:900]
    assert "siap_kirim" in kirim, "siaran tidak dirapikan"


# ---------------------------------------------------------------------------
# "Kok lama" harus bisa DIJAWAB, bukan ditebak
# ---------------------------------------------------------------------------

def test_perakitan_pesan_sinyal_tetap_murah():
    """Diukur 21 Sep 2026: 71 sinyal aktif -> 0,3 ms.

    Fungsi ini berjalan SINKRON di event loop, jadi kalau suatu saat ada
    yang menambahkan perhitungan berat ke dalamnya, bukan cuma bot yang
    melambat -- seluruh web ikut tertahan. Uji ini yang menangkapnya."""
    import time
    from datetime import datetime, timedelta

    import web.app as app_module

    kini = datetime.now()
    sinyal = [{"kode": f"EM{i:02d}", "status": "OPEN", "direction": "BUY",
               "entry_price": 100 + i, "sl_price": 90, "tp_price": 120,
               "tp2_price": 140, "tp3_price": 160, "tp_level_hit": 0,
               "mulai_dilacak": "2026-07-01", "sejak_sinyal_return_pct": 5.0,
               "confidence_score": 90 - i, "source": "TOP_PICK",
               "puncak_return_pct": 200 - i * 2.5 if i < 67 else 5.0,
               "puncak_date": "2026-09-10",
               "recorded_at": (kini - timedelta(days=20)).isoformat()}
              for i in range(71)]
    rep = {"n_total": 587, "stats": {"win_rate": 63.5}, "signals": sinyal}

    app_module._wa_fmt_sinyal(rep)                    # panaskan
    t0 = time.perf_counter()
    for _ in range(5):
        app_module._wa_fmt_sinyal(rep)
    lama = (time.perf_counter() - t0) / 5
    assert lama < 0.2, (
        f"perakitan pesan {lama*1000:.0f} ms — berjalan sinkron di event "
        f"loop, jadi web ikut tertahan selama itu")


def test_perintah_lambat_dicatat():
    """Tanpa angka, "kok lama" cuma bisa dijawab dengan tebakan. Yang
    mungkin lambat ada empat tempat berbeda -- basis data, cache, perakitan
    pesan, dan WhatsApp itu sendiri -- dan dari luar keempatnya identik."""
    import io
    import os

    akar = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    app = io.open(os.path.join(akar, "web", "app.py"), encoding="utf-8").read()
    potongan = app.split("async def api_wa_command")[1][:2500]
    assert "perf_counter" in potongan and "LAMBAT" in potongan

    js = io.open(os.path.join(akar, "wa-bot", "index.js"), encoding="utf-8").read()
    # Sidecar memisahkan waktu APP dari waktu KIRIM -- perbaikannya berbeda.
    assert "msApp" in js and "LAMBAT" in js
