"""Panduan analisa di tab Edukasi.

KENAPA DIUJI. Panduan ini memuat angka hasil pengukuran, dan angka yang
dipajang ke pembaca pemula punya tanggung jawab yang berbeda dari angka di
komentar kode: pembacanya tidak punya cara memeriksanya sendiri.

Yang dijaga berkas ini: angka di panduan SAMA dengan angka yang dipakai
aplikasinya. Kalau suatu hari ambang atau hasil ukurnya berubah dan
panduannya tidak ikut, uji ini yang menemukannya -- bukan pembaca yang
terlanjur bertindak atas angka basi.
"""
import pathlib
import re

import pytest

import web.app as app_module

JS = (pathlib.Path(__file__).resolve().parent.parent
      / "web" / "static" / "app.js").read_text(encoding="utf-8")
PANDUAN = JS[JS.index("const EDU_PANDUAN=["):JS.index("const EDU_TERMS=[")]


def test_panduan_terpasang_dan_dirender():
    """Panduan yang ada di data tapi tidak pernah dipanggil sama saja
    dengan tidak ada."""
    html = (pathlib.Path(__file__).resolve().parent.parent
            / "web" / "static" / "index.html").read_text(encoding="utf-8")
    assert 'id="eduPanduan"' in html
    assert "renderPanduan();" in JS


def test_semua_panduan_punya_langkah_dan_ringkasan():
    ids = re.findall(r"\{id:'([a-z]+)'", PANDUAN)
    assert len(ids) >= 7, f"cuma {len(ids)} panduan"
    assert len(set(ids)) == len(ids), "ada id panduan yang kembar"
    for kunci in ("judul:", "ringkas:", "langkah:", "menit:"):
        assert PANDUAN.count(kunci) >= len(ids), f"{kunci} tidak lengkap"


# ---------------------------------------------------------------------------
# Angka di panduan harus SAMA dengan angka yang dipakai aplikasinya
# ---------------------------------------------------------------------------

def _koma(x):
    """Angka bergaya Indonesia, bertanda, seperti yang ditulis panduan."""
    tanda = "+" if x >= 0 else "\u2212"
    return tanda + f"{abs(x):.2f}".replace(".", ",")


def test_angka_vonis_di_panduan_sama_dengan_yang_dipakai():
    """Panduan yang menyebut angka lain daripada yang dipakai mesinnya
    membuat pembaca menghitung peluang dari angka yang tidak berlaku.

    Dibaca dari KONSTANTA, bukan ditulis tangan. Angka-angka ini pernah
    ditulis tangan di sini; lalu pengukurannya diulang dengan dasar
    pembanding yang lebih ketat, dan tesnya jatuh bukan karena
    panduannya salah melainkan karena tes memegang salinan yang basi.
    """
    for v in ("BELI", "BELI KUAT"):
        assert _koma(app_module.UNGGUL_VONIS[v]) in PANDUAN, v


def test_angka_bertahan_dua_hari_sama():
    """Keranjang terkuat sekarang BELI yang bertahan, BUKAN BELI KUAT --
    vonis yang lebih ekstrem terukur lebih lemah. Panduannya harus
    menyebut yang terkuat menurut angka, bukan yang namanya terdengar
    paling meyakinkan."""
    terkuat = max(app_module.UNGGUL_BERTAHAN,
                  key=app_module.UNGGUL_BERTAHAN.get)
    assert terkuat == "BELI", terkuat
    assert _koma(app_module.UNGGUL_BERTAHAN[terkuat]) in PANDUAN


def test_ambang_pemulihan_di_panduan_sama_dengan_kodenya():
    """Panduan menyebut "jatuh 5-15%" sebagai syarat label KUAT. Kalau
    ambangnya digeser di core/divergence.py tanpa panduannya ikut, pembaca
    akan mencari sesuatu yang sudah tidak ada."""
    from core.divergence import MAKS_JATUH_PCT, MIN_JATUH_PCT

    assert (MIN_JATUH_PCT, MAKS_JATUH_PCT) == (5.0, 15.0)
    assert "5\u201315%" in PANDUAN or "5-15%" in PANDUAN


def test_angka_tangga_beli_sama_dengan_tabelnya():
    """Panduan menyebut 96%, 60%, 27% sebagai peluang order kena."""
    from core.entry_aman import TANGGA_LIKUID

    peta = {d: (t, n, h) for d, t, _, n, h in TANGGA_LIKUID}
    assert round(peta[0.0][0]) == 96 and "96%" in PANDUAN
    assert round(peta[3.0][0]) == 60 and "60%" in PANDUAN
    assert round(peta[8.0][0]) == 27 and "27%" in PANDUAN
    assert "+1,32%" in PANDUAN and "+0,77%" in PANDUAN


# ---------------------------------------------------------------------------
# Kejujuran isinya
# ---------------------------------------------------------------------------

def test_ada_panduan_yang_menyebut_apa_yang_BELUM_diukur():
    """Aplikasi saham umumnya menampilkan semua fiturnya dengan percaya
    diri yang sama. Pembaca pemula tidak punya cara membedakan fitur yang
    sudah diuji dari yang cuma kelihatan meyakinkan."""
    assert "belum diukur" in PANDUAN.lower()
    assert "Konsensus analis" in PANDUAN
    for gagal in ("Inverse Head", "Falling Wedge", "Bull Flag"):
        assert gagal in PANDUAN, f"{gagal} tidak disebut sebagai yang tidak bekerja"


def test_panduan_menyebut_keterlambatan_sinyal_pemulihan():
    """Tiga hari itu nyata dan mengubah harga entry. Menyembunyikannya
    membuat pembaca mengira ia melihat kejadian hari ini."""
    assert "terlambat tiga hari" in PANDUAN


def test_panduan_mengakui_RSI_berbeda_dari_buku_teks():
    """Pembaca akan menemukan panduan lain yang mengajarkan sebaliknya.
    Lebih baik ia tahu kenapa dari sini daripada mengira aplikasinya
    rusak."""
    assert "jenuh beli" in PANDUAN and "+14,10%" in PANDUAN


def test_panduan_memperingatkan_ilusi_saham_tidak_likuid():
    assert "sepi" in PANDUAN and "ilusi" in PANDUAN


def test_panduan_tidak_menjanjikan_masa_depan():
    """Semua angkanya diukur pada data masa lalu."""
    assert "data masa lalu" in PANDUAN
    assert "tidak dikarang" in PANDUAN
