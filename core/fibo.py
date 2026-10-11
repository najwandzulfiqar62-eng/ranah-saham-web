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
# HASIL PENGUKURAN -- DUA PERIODE, dan ia TIDAK mendukung Fibonacci
# sebagai sinyal
# ===========================================================================
# Jalan maju, per kejadian, jeda antar-sampel sepanjang horizon, dasar
# pembanding per TANGGAL. "Menyentuh" = dalam 2,0% dari levelnya, lalu
# diukur 20 hari bursa ke depan.
#
#   2 tahun : 786 emiten, 220 bar terakhir, dasar pasar +3,35%
#   5 tahun : 634 emiten, 900 bar terakhir, dasar pasar +1,61%
#
#   RASIO  ARAH     2 THN      n      5 THN      n    STATUS
#   23,6%  naik     +0,61   1.459     +0,16   4.652   stabil
#   23,6%  turun    -2,12   1.684     -0,85   6.019   stabil
#   38,2%  naik     -1,06   1.828     -0,64   5.245   stabil
#   38,2%  turun    -0,64     988     -0,51   4.051   stabil
#   50%    naik     -0,60   1.517     -0,61   4.060   stabil
#   50%    turun    +1,59     517     +0,53   2.292   stabil
#   61,8%  naik     -0,19   1.273     +0,04   3.512   GOYAH
#   61,8%  turun        -     360     -0,48   1.726   sepihak
#   78,6%  naik     +0,90     534     +0,35   1.489   stabil
#   78,6%  turun        -     135     +1,21     681   sepihak
#
# KESIMPULANNYA BERTAHAN, dan sekarang lebih kuat daripada waktu cuma ada
# satu periode: menyentuh level Fibonacci TIDAK memberi keunggulan.
#
# Dari tujuh sel yang tandanya bertahan di kedua periode, EMPAT negatif
# dan TIGA positif -- tanda yang campur aduk, bukan arah. Rata-ratanya
# -0,19% (2 thn) dan -0,22% (5 thn); ditimbang jumlah sampel, -0,57%.
# Jadi bukan "umumnya merugikan", melainkan "tidak membedakan apa pun,
# dengan kecenderungan tipis ke bawah".
#
# Satu sel memang buruk dan bukan kecil: 23,6% dalam ayunan turun,
# -2,12% (2 thn) dan -0,85% (5 thn).
#
# SATU HAL YANG MEMANG BERTAHAN, dan ia layak disebut apa adanya: 78,6%
# satu-satunya rasio yang POSITIF di kedua arah pada kedua periode (naik
# +0,90/+0,35, turun +3,58/+1,21 -- empat sel, satu tanda). 78,6% adalah
# retracement TERDALAM, nyaris seluruh ayunan dikembalikan; secara teori
# itu memang tempat orang yang masih percaya arah ayunannya menunggu.
#
# TAPI BESARNYA MENGECIL SEPARUH dari 2 ke 5 tahun di keempat selnya, dan
# satu selnya (78,6% turun, 2 thn) cuma 135 kejadian. Jadi yang bertahan
# ARAHNYA, bukan ukurannya -- dan "arah yang bertahan" bukan angka yang
# bisa dipakai menyusun rencana. Ia tidak dipajang sebagai keunggulan.
#
# 61,8% NAIK GOYAH: -0,19% jadi +0,04%. Keduanya praktis nol, dan itu
# justru bacaan yang benar -- bukan "kadang untung kadang rugi",
# melainkan tidak bisa dibedakan dari pasar.
#
# TEMUAN YANG BATAL, dicatat supaya tidak dipungut lagi dari riwayat
# commit: pengukuran PERTAMA -- waktu ayunannya masih diambil dari pivot
# TERAKHIR, bukan ayunan dominan -- memberi 38,2% naik +0,67% dan turun
# -1,24%, dan selisih 1,91 poin itu sempat disebut salah satu yang
# terbesar di proyek ini. Sesudah penjangkarannya dibetulkan (perbaikan
# yang BENAR: ayunan dominan itu yang ditarik manusia), selisihnya
# LENYAP -- kedua arah jadi negatif. Satu perbaikan metode menghapus
# seluruh temuan. Selisih itu artefak penjangkaran, bukan sifat pasar.
#
# DUA BATAS YANG HARUS IKUT DIBACA:
#
#   1. 5 tahun MEMUAT 2 tahun. Jadi ini bukan dua sampel yang saling
#      bebas, dan "tandanya sama" berarti "tambahan tiga tahun tidak
#      membalikkannya" -- lebih lemah daripada dua periode terpisah,
#      tapi cukup untuk menyingkirkan temuan yang hidup hanya karena
#      satu rentang pendek tertentu. Pola chart dan SMC diukur dengan
#      tumpang tindih yang sama, jadi ketiganya setara cara bacanya.
#
#   2. 5 tahun cuma memakai 634 dari 786 emiten, karena memindai 900 bar
#      menuntut riwayat ~4 tahun. Yang tersisih emiten yang BARU
#      tercatat -- jadi periode panjangnya sedikit berpihak pada
#      perusahaan yang sudah lama bertahan. Arah temuannya tidak berubah
#      karenanya (semua tanda yang stabil sudah stabil di 2 tahun, yang
#      memakai 786 emiten), tapi besarnya di kolom 5 tahun tidak boleh
#      dibaca sebagai angka seluruh bursa.
#
# AKIBATNYA untuk layar: garis Fibonacci tetap digambar sebagai ACUAN --
# orang memang memakainya, dan ia menandai tempat yang bisa diperiksa
# sendiri -- tapi TIDAK disajikan sebagai sesuatu yang terukur
# menguntungkan. Angkanya ditempel apa adanya, termasuk yang negatif,
# dan yang GOYAH diberi tanda "⚠" di judul garisnya.
#
# Kuncinya RASIO PECAHAN (0.382), sama dengan yang dipakai daftar level
# di bawah. Sempat tersimpan sbg 38.2 -- pencariannya tidak pernah
# cocok, dan layar diam-diam menulis "belum diukur" untuk level yang
# sebenarnya SUDAH diukur.
UNGGUL_FIBO: dict[tuple[float, str], dict] = {
    (0.236, "naik"): {"unggul_pct": 0.61, "n": 1459, "pct_positif": 42.5, "status": "stabil", "unggul_5y": 0.16, "n_5y": 4652},
    (0.236, "turun"): {"unggul_pct": -2.12, "n": 1684, "pct_positif": 38.4, "status": "stabil", "unggul_5y": -0.85, "n_5y": 6019},
    (0.382, "naik"): {"unggul_pct": -1.06, "n": 1828, "pct_positif": 41.0, "status": "stabil", "unggul_5y": -0.64, "n_5y": 5245},
    (0.382, "turun"): {"unggul_pct": -0.64, "n": 988, "pct_positif": 40.4, "status": "stabil", "unggul_5y": -0.51, "n_5y": 4051},
    (0.5, "naik"): {"unggul_pct": -0.6, "n": 1517, "pct_positif": 43.0, "status": "stabil", "unggul_5y": -0.61, "n_5y": 4060},
    (0.5, "turun"): {"unggul_pct": 1.59, "n": 517, "pct_positif": 41.4, "status": "stabil", "unggul_5y": 0.53, "n_5y": 2292},
    (0.618, "naik"): {"unggul_pct": -0.19, "n": 1273, "pct_positif": 42.5, "status": "goyah", "unggul_5y": 0.04, "n_5y": 3512},
    (0.618, "turun"): {"unggul_pct": -0.48, "n": 1726, "pct_positif": 40.8, "status": "sepihak", "unggul_5y": -0.48, "n_5y": 1726},
    (0.786, "naik"): {"unggul_pct": 0.9, "n": 534, "pct_positif": 48.5, "status": "stabil", "unggul_5y": 0.35, "n_5y": 1489},
    (0.786, "turun"): {"unggul_pct": 1.21, "n": 681, "pct_positif": 43.2, "status": "sepihak", "unggul_5y": 1.21, "n_5y": 681},
}
# Sampel di bawah ini tidak diberi angka. Lima rasio x dua arah diuji
# sekaligus; dari sebanyak itu, satu sel yang terlihat luar biasa memang
# DIHARAPKAN muncul karena kebetulan.
MIN_N_FIBO = 500
TANGGAL_UKUR_FIBO = "2026-10-11"
# Uji kestabilan: 2y (786 emiten, 220 bar)
# vs 5y (634 emiten, 900 bar).
# Dasar pasar 20 hari: +3.35% (2 thn),
# +1.61% (5 thn).
#
# `status` tiap baris: "stabil" tandanya sama di kedua periode (satu-satunya
# yang layak dibaca sebagai angka), "goyah" tandanya BERBALIK, "sepihak"
# cuma cukup sampel di satu periode. 5 tahun MEMUAT 2 tahun, jadi "sama"
# di sini berarti "tambahan tiga tahun tidak membalikkannya" -- bukan dua
# sampel yang saling bebas.


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
                      "n_ukur": (u or {}).get("n"),
                      # "stabil" | "goyah" | "sepihak". Ikut dikirim karena
                      # angka yang tandanya BERBALIK antar-periode tidak
                      # boleh terbaca sama dengan angka yang bertahan --
                      # dan di layar keduanya cuma selisih beberapa persen,
                      # tidak ada yang membedakannya kalau tidak disebut.
                      "status": (u or {}).get("status")})
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
