"""Deteksi pemulihan setelah jatuh -- divergence RSI yang sudah diukur.

NAMANYA SENGAJA BUKAN "BULLISH DIVERGENCE", dan itu kesimpulan dari
pengukuran, bukan pilihan gaya bahasa. Diukur 10 Okt 2026 pada 178 emiten
likuid, 2 tahun, 256 setup unik, horizon 20 hari bursa:

    semua divergence           n=256   naik 48,8%   unggul -0,72%
    + selisih RSI 3-6          n= 82   naik 48,8%   unggul -0,35%
    + harga sudah jatuh 5-15%  n= 52   naik 65,4%   unggul +4,05%

DIVERGENCE MURNI PUNYA KEUNGGULAN NEGATIF. Yang dijual aplikasi lain
sebagai "Bullish Divergence" -- RSI membuat dasar lebih tinggi sementara
harga membuat dasar lebih rendah -- sendirian TIDAK bekerja di IDX.

Dan yang menolong ternyata bukan RSI-nya. Selisih RSI 3-6 memberi -0,35%,
praktis nol. Yang memisahkan menang dari kalah adalah SEBERAPA DALAM harga
sudah jatuh di antara kedua dasar itu. Karena itu penyaring utamanya jatuh
harga, dan RSI cuma syarat lolos/tidak.

DUA JEBAKAN YANG DITUTUP DI SINI, keduanya pernah membuat angka saya salah:

1. MENGINTIP MASA DEPAN. Sebuah dasar baru bisa disebut dasar setelah
   beberapa bar berikutnya terbukti lebih tinggi. Mendeteksinya pada hari
   kejadian berarti memakai informasi yang belum ada. Karena itu pivot
   hanya sah sesudah JEDA_KANAN bar -- sinyalnya memang terlambat tiga
   hari, dan keterlambatan itu harga kejujurannya.

2. SATU SETUP DIHITUNG BERKALI-KALI. Sepasang pivot bertahan sebagai "dua
   pivot terakhir" selama belasan bar. Menghitung tiap bar sebagai kejadian
   baru menggandakan n sampai 8x DAN membuat hasilnya saling tumpang
   tindih. Pengukuran pertama saya melaporkan 86,2% naik karena jebakan
   ini; angka sebenarnya 80% dari 10 setup, bukan 86% dari 80. Karena itu
   tiap setup punya `setup_id` yang tetap.
"""
from dataclasses import dataclass

# Bar di kiri & kanan yang harus lebih tinggi agar sebuah titik disebut dasar.
JEDA_KIRI = 3
JEDA_KANAN = 3

# Jarak antar-dasar yang masuk akal. Terlalu dekat = derau yang sama;
# terlalu jauh = dua kejadian yang tidak lagi berhubungan.
MIN_JARAK = 5
MAKS_JARAK = 60

# Selisih RSI minimum. Sengaja RENDAH (bukan 3-6 seperti dugaan awal):
# diukur, pengetatan RSI tidak menambah keunggulan sama sekali dan hanya
# memotong jumlah temuan. Ia syarat lolos, bukan penyaring mutu.
MIN_GAP_RSI = 1.0

# PENYARING UTAMA, dan satu-satunya yang terbukti berpengaruh.
# Jatuh < 5%  : belum cukup jauh, keunggulannya hilang (+0,06%)
# Jatuh > 15% : pisau jatuh, keunggulannya berbalik negatif (-5,35%)
MIN_JATUH_PCT = 5.0
MAKS_JATUH_PCT = 15.0

# Setup yang terlalu tua tidak lagi bisa ditindaklanjuti -- harga sudah
# jauh dari dasarnya. Umur dihitung sejak pivot kedua, bukan sejak sinyal
# terdeteksi.
MAKS_UMUR_BAR = 25


@dataclass(frozen=True)
class Setup:
    kode: str
    tanggal_dasar1: str
    tanggal_dasar2: str
    harga_dasar1: float
    harga_dasar2: float
    rsi_dasar1: float
    rsi_dasar2: float
    jatuh_pct: float        # negatif: dasar kedua lebih rendah
    gap_rsi: float          # positif: RSI dasar kedua lebih tinggi
    jarak_bar: int          # antar kedua dasar
    umur_bar: int           # sejak dasar kedua sampai bar terakhir
    harga_kini: float
    kuat: bool              # lolos penyaring jatuh harga yang terukur

    @property
    def setup_id(self) -> str:
        """Penanda yang TETAP selama setup-nya sama.

        Dipakai supaya satu setup tidak diberitakan berulang kali tiap
        pemindaian. Tanggal kedua dasarnya yang dipakai, bukan tanggal
        deteksi -- tanggal deteksi berubah tiap hari, dan itu persis yang
        membuat satu setup terhitung delapan kali.
        """
        return f"{self.kode}:{self.tanggal_dasar1}:{self.tanggal_dasar2}"


def pivot_low(nilai: list, kiri: int = JEDA_KIRI, kanan: int = JEDA_KANAN) -> list:
    """Indeks dasar lokal: tidak ada yang lebih rendah dalam jendelanya.

    Mengembalikan indeks yang pivotnya SUDAH bisa dipastikan -- yaitu yang
    punya `kanan` bar sesudahnya di dalam data. Pemanggil masih harus
    memastikan bar-bar itu memang sudah lewat saat sinyalnya dipakai.
    """
    n = len(nilai)
    keluar = []
    for i in range(kiri, n - kanan):
        jendela = nilai[i - kiri:i + kanan + 1]
        if nilai[i] != min(jendela):
            continue
        # HARUS lebih rendah dari KEDUA TEPI jendelanya, bukan sekadar
        # terendah di dalamnya.
        #
        # Tanpa syarat ini, daerah harga DATAR melahirkan pivot palsu di
        # setiap bar: kalau semua nilainya sama, tiap bar adalah "minimum
        # jendelanya". Saham tidur di IDX sering menutup di harga yang
        # persis sama berhari-hari, dan pivot palsu itu akan menggeser
        # pasangan dasar yang dipakai -- divergence dihitung dari dua titik
        # yang bukan dasar sama sekali.
        #
        # Seri rata masih lolos selama tepinya lebih tinggi, jadi dasar
        # yang mendatar dua-tiga hari tetap terdeteksi.
        if nilai[i] < nilai[i - kiri] and nilai[i] < nilai[i + kanan]:
            keluar.append(i)
    return keluar


def cari_setup(kode: str, tanggal: list, harga: list, rsi: list) -> Setup | None:
    """Setup yang SEDANG aktif pada bar terakhir, atau None.

    Dipanggil dengan seluruh riwayat; yang dinilai keadaan pada bar
    terakhir. Hanya pivot yang jeda kanannya sudah lewat yang dipakai.
    """
    n = len(harga)
    if n < 40 or len(rsi) != n or len(tanggal) != n:
        return None

    akhir = n - 1
    # Pivot baru SAH dipakai setelah JEDA_KANAN bar berlalu. Tanpa syarat
    # ini, sinyalnya memakai informasi yang pada hari itu belum ada.
    sah = [p for p in pivot_low(harga) if p + JEDA_KANAN <= akhir]
    if len(sah) < 2:
        return None

    kedua, pertama = sah[-1], sah[-2]
    jarak = kedua - pertama
    if not (MIN_JARAK <= jarak <= MAKS_JARAK):
        return None

    umur = akhir - kedua
    if umur > MAKS_UMUR_BAR:
        return None

    h1, h2 = float(harga[pertama]), float(harga[kedua])
    r1, r2 = float(rsi[pertama]), float(rsi[kedua])
    if h1 <= 0:
        return None
    # Syarat divergence: harga membuat dasar lebih RENDAH, RSI lebih TINGGI.
    if not (h2 < h1 and r2 > r1 + MIN_GAP_RSI):
        return None

    jatuh = (h2 / h1 - 1) * 100       # negatif
    return Setup(
        kode=(kode or "").upper(),
        tanggal_dasar1=str(tanggal[pertama]), tanggal_dasar2=str(tanggal[kedua]),
        harga_dasar1=h1, harga_dasar2=h2, rsi_dasar1=round(r1, 1),
        rsi_dasar2=round(r2, 1), jatuh_pct=round(jatuh, 2),
        gap_rsi=round(r2 - r1, 1), jarak_bar=jarak, umur_bar=umur,
        harga_kini=float(harga[akhir]),
        kuat=(-MAKS_JATUH_PCT <= jatuh <= -MIN_JATUH_PCT),
    )


def urutkan(setups: list) -> list:
    """Yang KUAT lebih dulu, lalu yang paling baru.

    Bukan diurut berdasarkan selisih RSI, walau itu yang ditonjolkan
    aplikasi lain. Diukur, selisih RSI tidak memisahkan menang dari kalah
    (-0,35% keunggulan); kedalaman jatuh harga yang memisahkan (+4,05%).
    Mengurutkan dengan angka yang tidak berarti akan menaruh yang terbaik
    di tengah daftar.
    """
    return sorted(setups, key=lambda s: (not s.kuat, s.umur_bar))
