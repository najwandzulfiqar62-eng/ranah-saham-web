"""Arah tren menurut Dow, dan garis tren yang menyertainya.

SUMBERNYA, dan kali ini memang dari buku rujukan penulis. Bab Dow Theory
di "Technical Analysis for Mega Profit" (Edianto Ong) menurunkan arah
tren dari BENTUK puncak dan lembahnya, bukan dari indikator:

    tren NAIK  = puncak makin tinggi DAN lembah makin tinggi
    tren TURUN = puncak makin rendah DAN lembah makin rendah
    sisanya    = MENDATAR, dan "mendatar" itu jawaban yang sah

Syarat DAN-nya penting. Harga yang puncaknya naik tapi lembahnya turun
bukan tren naik yang lemah -- ia bukan tren sama sekali, dan memberinya
nama "naik" akan membuat orang membeli ke dalam sesuatu yang sedang
melebar ke dua arah.

AREA BELI & JUAL MENGIKUTI ARAHNYA, dan ini inti bab berikutnya di buku
yang sama (garis tren):

    di tren NAIK   beli saat harga turun MENYENTUH garis tren naik
                   (garis lewat lembah-lembahnya); jual saat garis itu
                   ditembus ke bawah -- bukan di atap pertama yang
                   ditemui, karena di tren naik atap memang untuk
                   ditembus
    di tren TURUN  jual saat harga naik MENYENTUH garis tren turun
                   (garis lewat puncak-puncaknya); jangan beli sampai
                   garis itu ditembus ke atas
    MENDATAR       tidak ada garis tren; pakai level mendatar yang
                   teruji (lihat core/level_sr.py)

PERBEDAANNYA DENGAN LEVEL MENDATAR. Level mendatar menjawab "di harga
berapa pasar pernah berbalik". Garis tren menjawab "di harga berapa
pasar akan berbalik BESOK, kalau trennya bertahan" -- dan angkanya
bergerak tiap hari. Keduanya dipakai bersama; yang satu tidak
menggantikan yang lain.

TIDAK ADA YANG MENGINTIP MASA DEPAN: pivot baru sah sesudah JEDA_KANAN
bar berikutnya terbukti berbalik, sama dengan seluruh modul pola.
"""
from dataclasses import dataclass

from core.divergence import JEDA_KANAN, JEDA_KIRI, pivot_low
from core.pola_chart import pivot_high

# Jendela yang dipertimbangkan. Tren yang lebih tua dari ini bukan lagi
# tren yang sama -- keadaan yang melahirkannya sudah berganti.
JENDELA = 160

# Dua pivot itu minimum MUTLAK untuk menarik garis; tiga membuatnya jauh
# lebih sulit kebetulan. Dipakai dua supaya tren yang baru berbalik tetap
# terbaca, tapi jumlahnya dilaporkan agar pembaca tahu seberapa tipis
# dasarnya.
MIN_PIVOT = 2

# Pivot yang dianggap "lebih tinggi"/"lebih rendah" harus berbeda lebih
# dari ini. Tanpa ambang, dua puncak yang selisihnya 0,1% sudah dihitung
# sbg "puncak makin tinggi" -- dan itu derau, bukan struktur.
MIN_BEDA_PCT = 0.5

# Sesudah sekian bar tanpa pivot baru, garis trennya tidak diperpanjang
# lagi. Garis yang diperpanjang terlalu jauh dari pivot terakhirnya
# menghasilkan angka yang terlihat pasti padahal cuma ekstrapolasi.
MAKS_UMUR_BAR = 30


@dataclass(frozen=True)
class Tren:
    arah: str                 # "naik" | "turun" | "mendatar"
    n_puncak: int
    n_lembah: int
    # Garis tren pada bar terakhir; None kalau trennya mendatar atau
    # pivotnya kurang.
    garis_kini: float | None
    garis_mulai: float | None       # nilai garis di pivot pertama
    tanggal_mulai: str | None
    tanggal_pivot_akhir: str | None
    umur_bar: int
    # Sudah ditembus? Di tren naik: harga menutup DI BAWAH garis.
    tembus: bool
    alasan: str

    def dict(self) -> dict:
        return {
            "arah": self.arah, "n_puncak": self.n_puncak,
            "n_lembah": self.n_lembah,
            "garis_kini": None if self.garis_kini is None else round(self.garis_kini, 2),
            "garis_mulai": None if self.garis_mulai is None else round(self.garis_mulai, 2),
            "tanggal_mulai": self.tanggal_mulai,
            "tanggal_pivot_akhir": self.tanggal_pivot_akhir,
            "umur_bar": self.umur_bar, "tembus": self.tembus,
            "alasan": self.alasan,
        }


def _naik(a: float, b: float) -> bool:
    """b lebih tinggi dari a, lebih dari sekadar derau."""
    return a > 0 and (b - a) / a * 100 > MIN_BEDA_PCT


def _turun(a: float, b: float) -> bool:
    return a > 0 and (a - b) / a * 100 > MIN_BEDA_PCT


def _garis_dua_titik(i1, h1, i2, h2, i):
    if i2 == i1:
        return None
    return h1 + (h2 - h1) / (i2 - i1) * (i - i1)


def arah_tren(tanggal: list, tinggi: list, rendah: list, tutup: list) -> Tren:
    """Arah tren menurut Dow + garis trennya."""
    kosong = Tren("mendatar", 0, 0, None, None, None, None, 0, False,
                  "data tidak cukup")
    n = len(tutup)
    if n < 60 or not (len(tanggal) == len(tinggi) == len(rendah) == n):
        return kosong
    akhir = n - 1
    awal = max(0, akhir - JENDELA)

    puncak = [p for p in pivot_high(tinggi, JEDA_KIRI, JEDA_KANAN)
              if awal <= p <= akhir - JEDA_KANAN]
    lembah = [p for p in pivot_low(rendah, JEDA_KIRI, JEDA_KANAN)
              if awal <= p <= akhir - JEDA_KANAN]
    if len(puncak) < MIN_PIVOT or len(lembah) < MIN_PIVOT:
        return Tren("mendatar", len(puncak), len(lembah), None, None, None,
                    None, 0, False, "pivot belum cukup untuk menilai tren")

    p1, p2 = puncak[-2], puncak[-1]
    l1, l2 = lembah[-2], lembah[-1]
    hp1, hp2 = float(tinggi[p1]), float(tinggi[p2])
    hl1, hl2 = float(rendah[l1]), float(rendah[l2])

    puncak_naik, lembah_naik = _naik(hp1, hp2), _naik(hl1, hl2)
    puncak_turun, lembah_turun = _turun(hp1, hp2), _turun(hl1, hl2)
    kini = float(tutup[akhir])

    if puncak_naik and lembah_naik:
        # Garis tren naik ditarik lewat LEMBAH-lembahnya -- di situlah
        # harga disangga, dan di situlah pembeli menunggu.
        i1, i2, h1, h2 = l1, l2, hl1, hl2
        arah, pakai = "naik", "lembah"
    elif puncak_turun and lembah_turun:
        # Garis tren turun lewat PUNCAK-puncaknya.
        i1, i2, h1, h2 = p1, p2, hp1, hp2
        arah, pakai = "turun", "puncak"
    else:
        # MENDATAR, dan ini jawaban yang sah. Syarat DAN-nya sengaja
        # keras: puncak naik tapi lembah turun berarti harga MELEBAR ke
        # dua arah, dan menyebutnya "tren naik yang lemah" akan membuat
        # orang membeli ke dalamnya.
        sebab = []
        if puncak_naik != lembah_naik:
            sebab.append("puncak dan lembah tidak searah")
        if not (puncak_naik or puncak_turun):
            sebab.append("puncaknya mendatar")
        if not (lembah_naik or lembah_turun):
            sebab.append("lembahnya mendatar")
        return Tren("mendatar", len(puncak), len(lembah), None, None,
                    str(tanggal[min(p1, l1)]), str(tanggal[max(p2, l2)]),
                    akhir - max(p2, l2), False,
                    "; ".join(sebab) or "tidak membentuk tren")

    umur = akhir - i2
    if umur > MAKS_UMUR_BAR:
        # Garis yang diperpanjang terlalu jauh dari pivot terakhirnya
        # menghasilkan angka yang terlihat pasti padahal ekstrapolasi.
        return Tren("mendatar", len(puncak), len(lembah), None, None,
                    str(tanggal[i1]), str(tanggal[i2]), umur, False,
                    f"pivot {pakai} terakhir sudah {umur} bar lalu")

    g = _garis_dua_titik(i1, h1, i2, h2, akhir)
    if g is None or g <= 0:
        return kosong
    tembus = (kini < g) if arah == "naik" else (kini > g)
    return Tren(
        arah=arah, n_puncak=len(puncak), n_lembah=len(lembah),
        garis_kini=g, garis_mulai=h1,
        tanggal_mulai=str(tanggal[i1]), tanggal_pivot_akhir=str(tanggal[i2]),
        umur_bar=umur, tembus=tembus,
        alasan=(f"{len(puncak)} puncak & {len(lembah)} lembah, "
                f"dua terakhir sama-sama {'menaik' if arah == 'naik' else 'menurun'}"),
    )
