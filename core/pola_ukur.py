"""Arti tiap pola chart, dan angka keunggulannya yang TERUKUR.

Dipisah dari core/pola_katalog.py dengan sengaja: yang di sana soal
BENTUK (apakah polanya ada), yang di sini soal NILAI (apakah polanya
berarti). Menyatukannya akan menggoda untuk memakai hasil pengukuran
sebagai syarat deteksi, dan begitu itu terjadi, pengukurannya tidak lagi
mengukur apa pun -- ia cuma mengulang keputusan yang sudah diambil.

UNGGUL_POLA diisi dari pengukuran jalan-maju di seluruh universe IDX,
dua tahun. Rinciannya ada di komentar masing-masing. Pola yang TIDAK ada
di tabel ini belum diukur, dan layar menuliskannya "belum diukur" --
bukan nol. Nol adalah klaim; "tidak tahu" bukan.
"""

# ---------------------------------------------------------------------------
# ARTI POLA (dari bab pola chart Edianto Ong, yang mengadaptasi Edwards &
# Magee lewat Murphy)
# ---------------------------------------------------------------------------
# Ditulis untuk pembaca yang belum tahu, bukan untuk pengingat. Tiap
# keterangan menyebut TIGA hal: bentuknya apa, artinya apa, dan kapan ia
# dianggap terkonfirmasi -- karena pola tanpa konfirmasi adalah bagian
# yang paling sering dipakai salah.

_ARTI = {
    "Inverse Head & Shoulders":
        "Tiga lembah di ujung tren turun; yang tengah paling dalam. "
        "Artinya penjual kehabisan tenaga. Dianggap sah hanya kalau harga "
        "menutup DI ATAS neckline (garis lewat dua puncak di antaranya) -- "
        "sebelum itu ia cuma tiga lembah biasa. Pola ini NAIK, bukan turun.",
    "Head & Shoulders":
        "Kebalikan dari Inverse: tiga puncak di ujung tren naik, yang "
        "tengah tertinggi. Artinya pembeli kehabisan tenaga. Sah kalau "
        "harga menutup DI BAWAH neckline.",
    "Double Bottom":
        "Dua lembah di harga yang kira-kira sama, berbentuk huruf W. "
        "Harga dua kali gagal menembus ke bawah di level yang sama, "
        "tanda penjual tidak lagi sanggup mendorong lebih rendah. Sah "
        "kalau menutup di atas puncak di antara kedua lembah.",
    "Double Top":
        "Dua puncak di harga yang kira-kira sama, berbentuk huruf M. "
        "Harga dua kali gagal menembus ke atas di level yang sama. Sah "
        "kalau menutup di bawah lembah di antara kedua puncak.",
    "Triple Bottom":
        "Seperti Double Bottom tapi tiga kali. Lebih jarang, dan "
        "level yang bertahan tiga kali biasanya lebih berarti daripada "
        "yang bertahan dua kali.",
    "Triple Top":
        "Seperti Double Top tapi tiga kali gagal menembus ke atas.",
    "Rounding Bottom":
        "Harga berbalik PERLAHAN membentuk mangkuk, bukan menukik seperti "
        "huruf V. Perlahannya itu yang penting: ia menandakan pergantian "
        "pemilik yang bertahap dari penjual ke pembeli, bukan satu "
        "kepanikan. Sah kalau menutup di atas bibir mangkuknya.",
    "Rounding Top":
        "Kebalikan Rounding Bottom: puncak yang membulat perlahan, tanda "
        "tenaga beli meredup bertahap.",
    "Cup with Handle":
        "Rounding Bottom yang diikuti satu tarikan napas pendek dan "
        "DANGKAL di bibir kanannya (gagangnya). Gagang yang dalam "
        "membatalkan pola -- itu berarti cangkir kedua sedang terbentuk, "
        "bukan gagang.",
    "Falling Wedge":
        "Dua garis sama-sama TURUN tapi menyempit: tiap penurunan makin "
        "kecil. Artinya tekanan jual mereda. Membingungkan karena "
        "bentuknya turun sementara artinya NAIK.",
    "Rising Wedge":
        "Dua garis sama-sama NAIK tapi menyempit: tiap kenaikan makin "
        "kecil. Artinya tenaga beli menipis. Ini kebalikan dari dugaan "
        "kebanyakan orang -- bentuknya naik, artinya TURUN.",
    "Bull Flag":
        "Kenaikan tajam (tiang), lalu istirahat pendek dan dangkal "
        "(bendera). Koreksi yang dangkal menandakan yang membeli belum "
        "mau melepas. Sah kalau menutup di atas puncak benderanya.",
    "Bear Flag":
        "Penurunan tajam, lalu pantulan pendek dan lemah. Pantulan yang "
        "lemah menandakan yang menjual belum selesai.",
    "Segitiga Menaik":
        "Atap MENDATAR, lantai NAIK. Harga berkali-kali menguji atap yang "
        "sama sementara dasarnya makin tinggi -- pembeli makin tidak "
        "sabar. Condong naik.",
    "Segitiga Menurun":
        "Lantai MENDATAR, atap TURUN. Penjual makin tidak sabar. Condong "
        "turun.",
    "Segitiga Simetris":
        "Atap turun, lantai naik, bertemu di tengah. TIDAK punya arah "
        "sendiri -- ia mengikuti ke mana pun ia tembus. Menebak arahnya "
        "sebelum tembus adalah cara pola ini paling sering dipakai salah.",
    "Rectangle":
        "Harga mondar-mandir di antara dua batas MENDATAR. Seperti "
        "segitiga simetris, arahnya ditentukan oleh tembusnya, bukan oleh "
        "bentuknya.",
}


def keterangan(nama: str) -> str:
    return _ARTI.get(nama, "")


# ---------------------------------------------------------------------------
# ANGKA TERUKUR
# ---------------------------------------------------------------------------
# Diisi oleh pengukuran; lihat catatan di kepala berkas dan di
# scratchpad/ukur_pola.py untuk metodenya. Kunci: (nama, fase).
# METODENYA, dan tiap butir menutup satu jebakan yang sudah pernah
# menggigit proyek ini:
#
#   - JALAN MAJU. Deteksi pada bar t hanya melihat data sampai t;
#     hasilnya diukur dari t ke t+20 bar.
#   - PER POLA, BUKAN PER HARI. Satu pola yang bertahan dua minggu
#     dihitung SEKALI. Tanpa ini, n menggelembung dan hasilnya saling
#     berkorelasi -- sudah terjadi tiga kali di proyek ini (divergence
#     10 setup terhitung 80, falling wedge 3.808/tahun).
#   - JEDA ANTAR-SAMPEL. Penjagaan kedua di atas yang pertama: untuk
#     tiap (emiten, pola, fase), sampel berikutnya baru dihitung sesudah
#     20 bar berlalu, supaya jendelanya tidak bertindihan.
#   - DASAR SETANGGAL. Dibandingkan dengan rata-rata return 20 hari
#     SELURUH emiten yang mulai di tanggal yang sama -- bukan rata-rata
#     seluruh periode. Pola yang kebetulan banyak muncul di bulan bagus
#     tidak jadi terlihat hebat karenanya.
#
# n < 15 SENGAJA TIDAK dimasukkan. Keunggulan dari sepuluh kejadian
# tidak bisa dibedakan dari kebetulan, dan menampilkannya sebagai angka
# membuatnya terbaca sama meyakinkan dengan angka dari lima ratus.
UNGGUL_POLA: dict[tuple[str, str], dict] = {
    ("Bear Flag", "TEMBUS"): {"unggul_pct": -0.92, "n": 2343, "pct_positif": 47.8},
    ("Bear Flag", "TERBENTUK"): {"unggul_pct": -0.75, "n": 4355, "pct_positif": 47.7},
    ("Bull Flag", "TEMBUS"): {"unggul_pct": 4.93, "n": 2063, "pct_positif": 47.1},
    ("Bull Flag", "TERBENTUK"): {"unggul_pct": 0.93, "n": 3704, "pct_positif": 45.9},
    ("Cup with Handle", "TERBENTUK"): {"unggul_pct": -2.05, "n": 100, "pct_positif": 47.0},
    ("Double Bottom", "TEMBUS"): {"unggul_pct": 1.06, "n": 745, "pct_positif": 41.7},
    ("Double Bottom", "TERBENTUK"): {"unggul_pct": -0.75, "n": 3265, "pct_positif": 50.5},
    ("Double Top", "TEMBUS"): {"unggul_pct": -1.2, "n": 587, "pct_positif": 50.6},
    ("Double Top", "TERBENTUK"): {"unggul_pct": -0.19, "n": 2650, "pct_positif": 46.3},
    ("Falling Wedge", "TEMBUS"): {"unggul_pct": 0.07, "n": 2440, "pct_positif": 49.4},
    ("Falling Wedge", "TERBENTUK"): {"unggul_pct": -0.71, "n": 2609, "pct_positif": 50.0},
    ("Head & Shoulders", "TEMBUS"): {"unggul_pct": -3.36, "n": 290, "pct_positif": 52.8},
    ("Head & Shoulders", "TERBENTUK"): {"unggul_pct": -2.87, "n": 457, "pct_positif": 45.3},
    ("Inverse Head & Shoulders", "TEMBUS"): {"unggul_pct": -1.12, "n": 199, "pct_positif": 40.2},
    ("Inverse Head & Shoulders", "TERBENTUK"): {"unggul_pct": -1.63, "n": 347, "pct_positif": 51.3},
    ("Rectangle", "TEMBUS"): {"unggul_pct": -0.8, "n": 524, "pct_positif": 47.3},
    ("Rectangle", "TERBENTUK"): {"unggul_pct": -1.7, "n": 801, "pct_positif": 46.8},
    ("Rising Wedge", "TEMBUS"): {"unggul_pct": -0.12, "n": 2157, "pct_positif": 50.9},
    ("Rising Wedge", "TERBENTUK"): {"unggul_pct": 1.07, "n": 1995, "pct_positif": 48.2},
    ("Rounding Bottom", "TERBENTUK"): {"unggul_pct": 0.62, "n": 315, "pct_positif": 52.1},
    ("Rounding Top", "TERBENTUK"): {"unggul_pct": -1.42, "n": 289, "pct_positif": 44.3},
    ("Segitiga Menaik", "TEMBUS"): {"unggul_pct": 3.24, "n": 464, "pct_positif": 44.6},
    ("Segitiga Menaik", "TERBENTUK"): {"unggul_pct": -0.6, "n": 1164, "pct_positif": 49.2},
    ("Segitiga Menurun", "TEMBUS"): {"unggul_pct": -1.82, "n": 637, "pct_positif": 46.0},
    ("Segitiga Menurun", "TERBENTUK"): {"unggul_pct": -1.3, "n": 1385, "pct_positif": 48.0},
    ("Segitiga Simetris", "TEMBUS"): {"unggul_pct": -0.18, "n": 1303, "pct_positif": 47.1},
    ("Segitiga Simetris", "TERBENTUK"): {"unggul_pct": -1.58, "n": 817, "pct_positif": 43.3},
    ("Triple Bottom", "TEMBUS"): {"unggul_pct": 0.24, "n": 88, "pct_positif": 39.8},
    ("Triple Bottom", "TERBENTUK"): {"unggul_pct": -1.0, "n": 737, "pct_positif": 48.6},
    ("Triple Top", "TEMBUS"): {"unggul_pct": 1.12, "n": 70, "pct_positif": 60.0},
    ("Triple Top", "TERBENTUK"): {"unggul_pct": -0.51, "n": 487, "pct_positif": 45.0},
}

# Dasar pembanding: rata-rata return 20 hari bursa SELURUH emiten
# pada tanggal yang sama.
DASAR_PCT: float | None = 3.38
HORIZON_HARI = 20
N_EMITEN_UKUR: int | None = 790
TANGGAL_UKUR: str | None = "2026-10-11"
