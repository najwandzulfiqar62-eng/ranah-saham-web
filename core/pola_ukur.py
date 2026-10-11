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
#     dihitung SEKALI.
#   - JEDA ANTAR-SAMPEL sepanjang horizon.
#   - DASAR SETANGGAL, bukan rata-rata seluruh periode.
#   - DUA PERIODE sebagai UJI KESTABILAN (lihat `status` di tiap baris).
#
# STATUS tiap baris:
#     "stabil"  tandanya SAMA di 2 tahun (790 emiten) dan 5 tahun
#               (790 emiten). Hanya ini yang layak dibaca sbg angka.
#     "goyah"   tandanya BERBALIK antar-periode. Dipajang dengan
#               peringatan, bukan disembunyikan -- pembaca berhak tahu
#               bahwa aplikasinya sendiri belum yakin.
#     "sepihak"   cuma cukup sampel di satu periode.
#     "arah_saja" sampelnya di bawah ambang angka, TAPI tandanya sama
#                 di dua periode. unggul_pct sengaja None -- yang
#                 disampaikan cuma ARAHNYA, bukan besarnya. Wedge ada
#                 di golongan ini: bahkan 5 tahun cuma memberi n=80.
#
# Angka utamanya dari periode 2 TAHUN (lebih mencerminkan pasar
# sekarang); angka 5 tahun ikut disimpan sbg pembanding.
#
# Pola yang tandanya berbalik TIDAK layak dipercaya, berapa pun besar
# angkanya di salah satu periode. Justru angka besar dari satu periode
# yang paling berbahaya: ia paling meyakinkan dan paling mudah
# kebetulan.
UNGGUL_POLA: dict[tuple[str, str], dict] = {
    ("Bear Flag", "TEMBUS"): {"unggul_pct": -0.92, "n": 2343, "pct_positif": 47.8, "status": "stabil", "unggul_5y": -0.69, "n_5y": 6940},
    ("Bear Flag", "TERBENTUK"): {"unggul_pct": -0.75, "n": 4355, "pct_positif": 47.7, "status": "stabil", "unggul_5y": -0.17, "n_5y": 12727},
    ("Bull Flag", "TEMBUS"): {"unggul_pct": 4.93, "n": 2063, "pct_positif": 47.1, "status": "stabil", "unggul_5y": 3.26, "n_5y": 5297},
    ("Bull Flag", "TERBENTUK"): {"unggul_pct": 0.93, "n": 3704, "pct_positif": 45.9, "status": "stabil", "unggul_5y": 0.45, "n_5y": 9551},
    ("Cup with Handle", "TERBENTUK"): {"unggul_pct": -2.05, "n": 100, "pct_positif": 47.0, "status": "stabil", "unggul_5y": -1.78, "n_5y": 406},
    ("Double Bottom", "TEMBUS"): {"unggul_pct": 1.06, "n": 745, "pct_positif": 41.7, "status": "stabil", "unggul_5y": 0.47, "n_5y": 1887},
    ("Double Bottom", "TERBENTUK"): {"unggul_pct": -0.75, "n": 3265, "pct_positif": 50.5, "status": "stabil", "unggul_5y": -0.48, "n_5y": 9419},
    ("Double Top", "TEMBUS"): {"unggul_pct": -1.2, "n": 587, "pct_positif": 50.6, "status": "stabil", "unggul_5y": -0.99, "n_5y": 1682},
    ("Double Top", "TERBENTUK"): {"unggul_pct": -0.19, "n": 2650, "pct_positif": 46.3, "status": "stabil", "unggul_5y": -0.21, "n_5y": 7740},
    # Falling Wedge / TEMBUS: sampel kurang di kedua periode -- sengaja tanpa angka
    # Falling Wedge / TERBENTUK: sampel kurang di kedua periode -- sengaja tanpa angka
    ("Head & Shoulders", "TEMBUS"): {"unggul_pct": -3.36, "n": 290, "pct_positif": 52.8, "status": "stabil", "unggul_5y": -1.08, "n_5y": 764},
    ("Head & Shoulders", "TERBENTUK"): {"unggul_pct": -2.87, "n": 457, "pct_positif": 45.3, "status": "stabil", "unggul_5y": -0.9, "n_5y": 1310},
    ("Inverse Head & Shoulders", "TEMBUS"): {"unggul_pct": -1.12, "n": 199, "pct_positif": 40.2, "status": "goyah", "unggul_5y": 1.51, "n_5y": 474},
    ("Inverse Head & Shoulders", "TERBENTUK"): {"unggul_pct": -1.63, "n": 347, "pct_positif": 51.3, "status": "stabil", "unggul_5y": -0.98, "n_5y": 971},
    ("Rectangle", "TEMBUS"): {"unggul_pct": -0.8, "n": 524, "pct_positif": 47.3, "status": "stabil", "unggul_5y": -0.29, "n_5y": 1882},
    ("Rectangle", "TERBENTUK"): {"unggul_pct": -1.7, "n": 801, "pct_positif": 46.8, "status": "stabil", "unggul_5y": -0.47, "n_5y": 2880},
    ("Rising Wedge", "TEMBUS"): {"unggul_pct": None, "n": 47, "pct_positif": 38.3, "status": "arah_saja", "arah_terukur": "turun", "unggul_5y": -5.15, "n_5y": 86},
    # Rising Wedge / TERBENTUK: sampel kurang di kedua periode -- sengaja tanpa angka
    ("Rounding Bottom", "TERBENTUK"): {"unggul_pct": 0.62, "n": 315, "pct_positif": 52.1, "status": "goyah", "unggul_5y": -0.03, "n_5y": 1139},
    ("Rounding Top", "TERBENTUK"): {"unggul_pct": -1.42, "n": 289, "pct_positif": 44.3, "status": "stabil", "unggul_5y": -1.57, "n_5y": 1073},
    ("Segitiga Menaik", "TEMBUS"): {"unggul_pct": 3.24, "n": 464, "pct_positif": 44.6, "status": "stabil", "unggul_5y": 1.52, "n_5y": 1429},
    ("Segitiga Menaik", "TERBENTUK"): {"unggul_pct": -0.6, "n": 1164, "pct_positif": 49.2, "status": "stabil", "unggul_5y": -0.46, "n_5y": 3628},
    ("Segitiga Menurun", "TEMBUS"): {"unggul_pct": -1.82, "n": 637, "pct_positif": 46.0, "status": "stabil", "unggul_5y": -1.25, "n_5y": 2135},
    ("Segitiga Menurun", "TERBENTUK"): {"unggul_pct": -1.3, "n": 1385, "pct_positif": 48.0, "status": "stabil", "unggul_5y": -0.78, "n_5y": 4277},
    ("Segitiga Simetris", "TEMBUS"): {"unggul_pct": -0.18, "n": 1303, "pct_positif": 47.1, "status": "goyah", "unggul_5y": 0.08, "n_5y": 3019},
    ("Segitiga Simetris", "TERBENTUK"): {"unggul_pct": -1.58, "n": 817, "pct_positif": 43.3, "status": "stabil", "unggul_5y": -0.77, "n_5y": 1819},
    ("Triple Bottom", "TEMBUS"): {"unggul_pct": -0.35, "n": 232, "pct_positif": 40.9, "status": "sepihak", "unggul_5y": -0.35, "n_5y": 232},
    ("Triple Bottom", "TERBENTUK"): {"unggul_pct": -1.0, "n": 737, "pct_positif": 48.6, "status": "stabil", "unggul_5y": -0.42, "n_5y": 2086},
    ("Triple Top", "TEMBUS"): {"unggul_pct": 0.16, "n": 162, "pct_positif": 52.5, "status": "sepihak", "unggul_5y": 0.16, "n_5y": 162},
    ("Triple Top", "TERBENTUK"): {"unggul_pct": -0.51, "n": 487, "pct_positif": 45.0, "status": "stabil", "unggul_5y": -0.07, "n_5y": 1330},
}

DASAR_PCT: float | None = 3.38
DASAR_5Y_PCT: float | None = 1.72
HORIZON_HARI = 20
N_EMITEN_UKUR: int | None = 790
TANGGAL_UKUR: str | None = "2026-10-12"
