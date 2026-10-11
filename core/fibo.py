"""Fibonacci retracement & extension dari ayunan BERARAH.

SUMBERNYA memang dari buku rujukan penulis. Bab Fibonacci di "Technical
Analysis for Mega Profit" (Edianto Ong) memakai deret baku:

    retracement   23,6%  38,2%  50%  61,8%  78,6%
    extension     127,2%  161,8%

50% bukan bilangan Fibonacci; ia masuk karena konvensi Dow ("harga
sering mengoreksi separuh gerakan sebelumnya"), dan buku itu
memuatnya bersama yang lain. Disebut di sini supaya tidak ada yang
mengira ia hasil perhitungan rasio emas.

CACAT YANG DIPERBAIKI DARI VERSI LAMA. core/indicators.py mengambil
`High.max()` dan `Low.min()` dari 90 bar terakhir -- tanpa memedulikan
MANA YANG LEBIH DULU. Padahal retracement didefinisikan pada ayunan
BERARAH: kalau puncaknya terjadi sebelum lembahnya, level "61,8% dari
low ke high" mengukur gerakan yang tidak pernah terjadi ke arah itu,
dan garisnya jatuh di tempat yang tidak punya arti apa-apa.

Di sini arahnya ditentukan dari URUTAN WAKTU pivotnya:

    lembah lalu puncak  -> ayunan NAIK, retracement di BAWAH harga
                           (calon support saat harga mundur)
    puncak lalu lembah  -> ayunan TURUN, retracement di ATAS harga
                           (calon resistance saat harga memantul)

AYUNANNYA HARUS BERARTI. Level Fibonacci dari ayunan 2% adalah lima
garis yang berjarak beberapa rupiah -- bukan analisis, cuma derau yang
diberi nama. Ambang minimumnya mengikuti ATR saham itu sendiri, bukan
persentase tetap.

TIDAK MENGINTIP MASA DEPAN: pivot baru sah sesudah JEDA_KANAN bar
berikutnya terbukti berbalik, sama dengan seluruh modul pola.
"""
from dataclasses import dataclass

from core.divergence import JEDA_KANAN, JEDA_KIRI, pivot_low
from core.pola_chart import pivot_high

# Deret baku. 78,6% = akar dari 61,8%; 127,2% = akar dari 161,8%.
RETRACEMENT = (0.236, 0.382, 0.5, 0.618, 0.786)
EXTENSION = (1.272, 1.618)

JENDELA = 180

# ===========================================================================
# HASIL PENGUKURAN -- dan ia membenarkan perbaikan arahnya
# ===========================================================================
# Diukur 20 hari ke depan, jalan maju, per kejadian, 786 emiten,
# dasar setanggal +3.35%. "Menyentuh" = dalam 2.0% dari levelnya.
#
#     Fibo 38,2% ayunan NAIK      +0.67%  (n=1,927)
#     Fibo 38,2% ayunan TURUN     -1.24%  (n=1,578)
#     Fibo 38,2% GABUNGAN ARAH    +0.04%  (n=2,940)   <- NOL
#
# DUA ARAHNYA BERLAWANAN, jadi menggabungkannya saling meniadakan. Dan
# "gabungan arah" itu persis yang dihasilkan calculate_fibonacci_levels()
# yang lama -- ia mengambil High.max() dan Low.min() tanpa memedulikan
# mana yang lebih dulu.
#
# Artinya memperbaiki arahnya BUKAN kosmetik: ia selisih antara sinyal
# (selisih 1,91 poin antara dua arah) dan derau (nol). Ini salah satu
# selisih terbesar yang terukur di proyek ini.
#
# Rasio yang sampelnya di bawah 500 TIDAK dimasukkan -- 50% pada ayunan
# turun cuma 109 kejadian, dan angka dari sampel sekecil itu tidak bisa
# dibedakan dari kebetulan.
# Kuncinya RASIO PECAHAN (0.382), sama dengan yang dipakai daftar
# level di bawah. Sempat tersimpan sbg 38.2 -- pencariannya tidak
# pernah cocok, dan layar diam-diam menulis "belum diukur" untuk
# level yang sebenarnya SUDAH diukur.
# ===========================================================================
# HASIL PENGUKURAN -- dan ia TIDAK mendukung Fibonacci sbg sinyal
# ===========================================================================
# Diukur 20 hari ke depan, jalan maju, per kejadian, 786 emiten,
# dasar setanggal +3.35%. "Menyentuh" = dalam 2.0% dari levelnya.
#
#     23,6% naik   +0.61%   38,2% naik  -1.06%
#     50%   naik   -0.60%   61,8% naik  -0.19%
#     78,6% naik   +0.90%
#     23,6% turun  -2.12%   38,2% turun -0.64%
#     50%   turun  +1.59%
#
# TIDAK ADA POLA. Tandanya berganti-ganti antar-rasio tanpa urutan yang
# masuk akal (23,6 positif, 38,2 negatif, 50 negatif, 61,8 negatif, 78,6
# positif pada sisi naik). Itu sebaran acak, bukan struktur.
#
# DAN INI MEMBATALKAN TEMUAN SEBELUMNYA. Pengukuran pertama -- waktu
# ayunannya masih diambil dari pivot TERAKHIR -- memberi 38,2% naik
# +0,67% dan turun -1,24%, dan selisih 1,91 poin itu sempat disebut
# salah satu yang terbesar di proyek ini. Sesudah penjangkarannya
# diperbaiki ke ayunan DOMINAN (perbaikan yang benar, karena itu yang
# ditarik manusia), selisihnya LENYAP. Jadi selisih itu artefak
# penjangkaran, bukan sifat pasar. Klaim lamanya batal, dan dicatat di
# sini supaya tidak dipungut lagi dari riwayat commit.
#
# AKIBATNYA untuk layar: garis Fibonacci tetap digambar sebagai ACUAN --
# orang memang memakainya, dan ia menandai tempat yang bisa diperiksa
# sendiri -- tapi TIDAK BOLEH disajikan sebagai sesuatu yang terukur
# menguntungkan. Angkanya ditempel apa adanya, termasuk yang negatif.
#
# Rasio bersampel < 500 tidak dimasukkan. "78,6% turun +3,58%" cuma 135
# kejadian; dari lima belas sel yang diuji sekaligus, satu yang terlihat
# luar biasa itu yang diharapkan muncul karena kebetulan.
UNGGUL_FIBO: dict[tuple[float, str], dict] = {
    (0.236, "naik"): {"unggul_pct": 0.61, "n": 1459, "pct_positif": 42.5},
    (0.236, "turun"): {"unggul_pct": -2.12, "n": 1684, "pct_positif": 38.4},
    (0.382, "naik"): {"unggul_pct": -1.06, "n": 1828, "pct_positif": 41.0},
    (0.382, "turun"): {"unggul_pct": -0.64, "n": 988, "pct_positif": 40.4},
    (0.500, "naik"): {"unggul_pct": -0.6, "n": 1517, "pct_positif": 43.0},
    (0.500, "turun"): {"unggul_pct": 1.59, "n": 517, "pct_positif": 41.4},
    (0.618, "naik"): {"unggul_pct": -0.19, "n": 1273, "pct_positif": 42.5},
    (0.786, "naik"): {"unggul_pct": 0.9, "n": 534, "pct_positif": 48.5},
}
MIN_N_FIBO = 500
TANGGAL_UKUR_FIBO = "2026-10-12"


def unggul(rasio: float, arah: str) -> dict | None:
    """Angka terukur satu level, atau None kalau belum cukup sampel."""
    return UNGGUL_FIBO.get((rasio, arah))

# JUMLAH LEVEL MENYESUAIKAN BESAR AYUNAN -- bukan ambang tunggal yang
# membuang sebagian besar saham.
#
# Syaratnya satu dan bisa dihitung: jarak antar-level harus MELEBIHI
# derau harian, kalau tidak garis-garisnya cuma menandai kisaran satu
# hari dan "harga menyentuh 61,8%" jadi pernyataan yang selalu benar.
#
#   lima level (23,6 / 38,2 / 50 / 61,8 / 78,6)
#       jarak tersempit 0,118 x ayunan  ->  butuh ayunan > 8,5 x ATR
#   dua level (38,2 / 61,8)
#       jarak 0,236 x ayunan            ->  butuh ayunan > 4,2 x ATR
#
# Diukur pada 120 emiten: median ayunan 3,3 x ATR, p75 4,9 x ATR. Jadi
# ambang tunggal 8,5 akan membuang 95% saham, sementara memaksakan lima
# level pada ayunan kecil akan menggambar lima garis yang lebih rapat
# daripada gerak sehari. Keduanya salah; yang benar menyesuaikan.
MIN_AYUNAN_ATR_PENUH = 8.5
MIN_AYUNAN_ATR_RINGKAS = 4.2
RETRACEMENT_RINGKAS = (0.382, 0.618)
MIN_AYUNAN_PCT = 4.0      # batas bawah mutlak, untuk saham sangat tenang

# Sesudah sekian bar dari pivot penutup ayunan, levelnya tidak relevan
# lagi -- pasar sudah membentuk ayunan baru yang belum sempat terbaca.
MAKS_UMUR_BAR = 60


@dataclass(frozen=True)
class Fibo:
    arah: str                 # "naik" | "turun"
    awal_tanggal: str
    awal_harga: float
    akhir_tanggal: str
    akhir_harga: float
    ayunan_pct: float
    ayunan_atr: float         # ayunan dalam kelipatan ATR -- penentu jumlah level
    umur_bar: int
    level: tuple              # ({"rasio","harga","jenis","nama"}, ...)
    harga_kini: float

    def dict(self) -> dict:
        return {"arah": self.arah,
                "awal_tanggal": self.awal_tanggal,
                "awal_harga": round(self.awal_harga, 2),
                "akhir_tanggal": self.akhir_tanggal,
                "akhir_harga": round(self.akhir_harga, 2),
                "ayunan_pct": round(self.ayunan_pct, 2),
                "ayunan_atr": round(self.ayunan_atr, 1),
                "penuh": len([x for x in self.level
                              if x["jenis"] == "retracement"]) > 2,
                "umur_bar": self.umur_bar,
                "harga_kini": round(self.harga_kini, 2),
                "level": list(self.level)}


def _atr_pct(tinggi, rendah, tutup, n=14) -> float:
    if len(tutup) < n + 1:
        return 2.0
    tr = []
    for i in range(len(tutup) - n, len(tutup)):
        h, l, pc = float(tinggi[i]), float(rendah[i]), float(tutup[i - 1])
        tr.append(max(h - l, abs(h - pc), abs(l - pc)))
    harga = float(tutup[-1]) or 1.0
    return max(0.1, sum(tr) / len(tr) / harga * 100)


def hitung(tanggal: list, tinggi: list, rendah: list, tutup: list) -> Fibo | None:
    """Fibonacci dari ayunan berarah terakhir, atau None."""
    n = len(tutup)
    if n < 60 or not (len(tanggal) == len(tinggi) == len(rendah) == n):
        return None
    akhir = n - 1
    awal_j = max(0, akhir - JENDELA)

    puncak = [p for p in pivot_high(tinggi, JEDA_KIRI, JEDA_KANAN)
              if awal_j <= p <= akhir - JEDA_KANAN]
    lembah = [p for p in pivot_low(rendah, JEDA_KIRI, JEDA_KANAN)
              if awal_j <= p <= akhir - JEDA_KANAN]
    if not puncak or not lembah:
        return None

    # AYUNAN DOMINAN, BUKAN AYUNAN TERAKHIR.
    #
    # CACAT NYATA (dilaporkan penulis: "mana kok ga ada garis fibonya").
    # Versi pertama memakai pivot high dan pivot low TERAKHIR. Di masa
    # konsolidasi keduanya sering cuma ayunan mikro yang berdampingan,
    # dan ayunan mikro ditolak ambang ukuran -- sehingga Fibonacci
    # hilang justru di saham yang ayunan besarnya paling jelas:
    #
    #     PTRO  pivot terakhir  10,0% (1,9x ATR, ditolak)
    #           ayunan dominan 310,1% (60,3x ATR)
    #     ANTM  pivot terakhir   5,2% (1,6x ATR, ditolak)
    #           ayunan dominan 102,9% (31,6x ATR)
    #
    # Manusia menarik Fibonacci di ayunan yang MEMBENTUK struktur
    # sekarang, bukan di riak terakhir. Jadi: untuk tiap pivot sebagai
    # UJUNG ayunan, dicari pasangan lawan paling ekstrem SEBELUMNYA,
    # lalu dipilih yang terbesar di antara yang ujungnya masih baru.
    #
    # Ongkosnya tidak berarti: pivot dalam jendela 180 bar cuma puluhan,
    # dan seluruh modul ini berada di dalam cache overlay chart.
    kandidat = []
    for ip in puncak:                      # ayunan NAIK, berujung di puncak
        lo_sebelum = [l for l in lembah if l < ip]
        if not lo_sebelum:
            continue
        il = min(lo_sebelum, key=lambda x: rendah[x])
        kandidat.append(("naik", il, ip, float(rendah[il]), float(tinggi[ip])))
    for il in lembah:                      # ayunan TURUN, berujung di lembah
        hi_sebelum = [p for p in puncak if p < il]
        if not hi_sebelum:
            continue
        ip = max(hi_sebelum, key=lambda x: tinggi[x])
        kandidat.append(("turun", ip, il, float(tinggi[ip]), float(rendah[il])))

    # Ujungnya harus MASIH BARU -- ayunan yang berakhir tiga bulan lalu
    # sudah digantikan struktur yang lebih baru.
    kandidat = [k for k in kandidat
                if (akhir - k[2]) <= MAKS_UMUR_BAR
                and k[3] > 0 and k[4] > 0]
    if not kandidat:
        return None

    def _besar(k):
        return abs(k[4] - k[3]) / min(k[3], k[4])

    arah, i_awal, i_akhir, h_awal, h_akhir = max(kandidat, key=_besar)
    rentang = abs(h_akhir - h_awal)
    ayunan_pct = rentang / min(h_awal, h_akhir) * 100

    atr = _atr_pct(tinggi, rendah, tutup)
    rasio_atr = ayunan_pct / atr if atr else 0
    if ayunan_pct < MIN_AYUNAN_PCT or rasio_atr < MIN_AYUNAN_ATR_RINGKAS:
        # Ayunannya terlalu kecil bahkan untuk dua garis: keduanya akan
        # berjarak lebih rapat daripada gerak sehari.
        return None
    rasio_pakai = (RETRACEMENT if rasio_atr >= MIN_AYUNAN_ATR_PENUH
                   else RETRACEMENT_RINGKAS)

    umur = akhir - i_akhir   # sudah dijamin <= MAKS_UMUR_BAR oleh saringan

    level = []
    for r in rasio_pakai:
        # Retracement diukur MUNDUR dari ujung ayunan.
        harga = (h_akhir - rentang * r) if arah == "naik" \
            else (h_akhir + rentang * r)
        u = unggul(r, arah)
        level.append({"rasio": r, "harga": round(harga, 2),
                      "jenis": "retracement",
                      "nama": f"Fibo {r * 100:.1f}%".replace(".0%", "%"),
                      # None = belum cukup sampel, BUKAN nol.
                      "unggul_pct": (u or {}).get("unggul_pct"),
                      "n_ukur": (u or {}).get("n")})
    for r in EXTENSION:
        # Extension diukur MAJU dari ujung ayunan, searah ayunannya.
        harga = (h_akhir + rentang * (r - 1)) if arah == "naik" \
            else (h_akhir - rentang * (r - 1))
        level.append({"rasio": r, "harga": round(harga, 2),
                      "jenis": "extension",
                      "nama": f"Target {r * 100:.1f}%".replace(".0%", "%")})

    return Fibo(arah=arah,
                awal_tanggal=str(tanggal[i_awal]), awal_harga=h_awal,
                akhir_tanggal=str(tanggal[i_akhir]), akhir_harga=h_akhir,
                ayunan_pct=ayunan_pct, ayunan_atr=rasio_atr, umur_bar=umur,
                level=tuple(level), harga_kini=float(tutup[akhir]))
