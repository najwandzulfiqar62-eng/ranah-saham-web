"""Harga beli yang aman -- dan ongkos dari menunggunya.

PERTANYAAN YANG DIJAWAB di sini bukan "berapa harga bagusnya" (itu tidak
bisa dijawab), melainkan: kalau menaruh order di bawah harga sekarang,
seberapa sering ia kena, dan apa yang terjadi sesudahnya.

DIUKUR 11 Okt 2026, 178 emiten likuid, 2 tahun. Order limit di bawah harga
penutupan, ditunggu 10 hari bursa, lalu ditahan 20 hari:

    diskon   terisi   jika kena    naik    HARAPAN
      0%      96,2%     +1,37%    44,4%    +1,32%
      1%      81,9%     +1,44%    48,8%    +1,18%
      2%      70,1%     +1,53%    49,8%    +1,07%
      3%      59,6%     +1,62%    50,2%    +0,97%
      5%      43,4%     +1,94%    52,0%    +0,84%
      8%      27,1%     +2,84%    54,7%    +0,77%

"AMAN" DAN "MENGUNTUNGKAN" BUKAN HAL YANG SAMA, dan itu seluruh isi tabel
di atas. Menunggu diskon memang membuat tiap transaksi lebih aman -- win
rate naik dari 44,4% ke 54,7%, dan hasil per transaksinya dua kali lipat.
Tapi HARAPANNYA turun terus, karena order yang tidak pernah kena berarti
peluang yang hilang sepenuhnya, dan itu dihitung nol.

Diskon 8% menghasilkan +2,84% tiap kali kena -- tapi cuma kena 27% dari
waktu, jadi harapannya +0,77%: lebih buruk daripada beli di pasar yang
cuma +1,37% tapi hampir selalu dapat.

KARENA ITU MODUL INI TIDAK MEMBERI "SATU HARGA AMAN". Ia menyajikan
tangganya beserta kedua angkanya, supaya yang memilih tahu persis apa
yang ditukar: ketenangan dengan harapan.
"""
from dataclasses import dataclass

# DUA TANGGA, dan selisihnya sendiri yang bermakna.
#
# Diukur pada DUA universe berbeda, dan bentuknya identik di keduanya:
# makin dalam diskonnya, makin tinggi win rate-nya dan makin rendah
# harapannya. Yang berbeda cuma besarannya.
#
# Saham tidak likuid menunjukkan hasil JAUH lebih besar (+3,49% vs +1,37%
# untuk beli pasar). Itu bukan peluang yang lebih baik -- itu sebagian
# besar selip harga yang tidak terukur: harga penutupan di saham sepi
# tidak mencerminkan harga yang benar-benar bisa didapat. Karena itu
# saham likuid dinilai dengan tangganya sendiri, yang lebih rendah dan
# lebih bisa dipercaya.
#
# Urutan: (diskon %, terisi %, hasil jika kena %, naik %, harapan %).

# 178 emiten likuid -- dipakai untuk saham yang memang likuid.
TANGGA_LIKUID = (
    (0.0, 96.2, 1.37, 44.4, 1.32),
    (1.0, 81.9, 1.44, 48.8, 1.18),
    (2.0, 70.1, 1.53, 49.8, 1.07),
    (3.0, 59.6, 1.62, 50.2, 0.97),
    (5.0, 43.4, 1.94, 52.0, 0.84),
    (8.0, 27.1, 2.84, 54.7, 0.77),
)

# SELURUH 793 emiten IDX.
TANGGA_SEMUA = (
    (0.0, 97.2, 3.49, 46.3, 3.39),
    (1.0, 85.9, 3.25, 50.3, 2.79),
    (2.0, 76.3, 3.45, 51.3, 2.63),
    (3.0, 67.2, 3.62, 51.9, 2.43),
    (5.0, 51.4, 3.86, 52.5, 1.98),
    (8.0, 34.7, 4.32, 53.6, 1.50),
)

# Bawaan: yang likuid, karena angkanya yang paling mungkin bisa ditepati.
TANGGA = TANGGA_LIKUID

# Nilai transaksi harian di atas ini dianggap likuid.
AMBANG_LIKUID = 1e9

DIUKUR = "2026-10-11"
TUNGGU_HARI = 10
TAHAN_HARI = 20

# Pembagian cicilan bawaan. Bukan kompromi asal-asalan: bagian pertama
# mengunci peluang (terisi 96%), bagian kedua menurunkan harga rata-rata
# kalau pasar memberi kesempatan. Yang dihindari adalah menaruh SELURUH
# posisi di diskon -- di situlah harapannya paling banyak hilang.
PORSI_PASAR = 0.5


@dataclass(frozen=True)
class Tingkat:
    diskon_pct: float
    harga: int
    terisi_pct: float
    hasil_jika_kena_pct: float
    naik_pct: float
    harapan_pct: float


def tangga_beli(harga: float, atr_pct: float | None = None,
                nilai_harian: float | None = None) -> list[Tingkat]:
    """Tangga harga beli dengan angka terukurnya.

    `atr_pct` tidak mengubah angkanya -- ia cuma dipakai memangkas tingkat
    yang tidak masuk akal untuk saham itu. Diskon 1% pada saham yang
    bergerak 6% sehari bukan "menunggu", itu sama saja dengan beli pasar
    dengan langkah tambahan; dan menampilkannya sebagai pilihan yang
    berbeda itu menyesatkan.
    """
    try:
        h = float(harga)
    except (TypeError, ValueError):
        return []
    if h <= 0:
        return []

    batas_bawah = 0.0
    if atr_pct:
        try:
            # Di bawah separuh ATR harian, "diskonnya" tenggelam di derau.
            batas_bawah = max(0.0, float(atr_pct) * 0.5)
        except (TypeError, ValueError):
            batas_bawah = 0.0

    # Saham tidak likuid dinilai dengan tangganya sendiri. Memakai angka
    # saham likuid untuknya akan MENGECILKAN hasil yang tampak; memakai
    # angka seluruh universe untuk saham likuid akan MEMBESARKANNYA. Dua
    # kesalahan berlawanan, dan dua-duanya menyesatkan.
    tabel = TANGGA_LIKUID
    if nilai_harian is not None and nilai_harian < AMBANG_LIKUID:
        tabel = TANGGA_SEMUA

    keluar = []
    for diskon, terisi, hasil, naik, harapan in tabel:
        if diskon and diskon < batas_bawah:
            continue
        keluar.append(Tingkat(
            diskon_pct=diskon, harga=round(h * (1 - diskon / 100)),
            terisi_pct=terisi, hasil_jika_kena_pct=hasil,
            naik_pct=naik, harapan_pct=harapan,
        ))
    return keluar


def paling_aman(tangga: list) -> Tingkat | None:
    """Tingkat dengan peluang NAIK tertinggi -- yang paling 'aman'.

    Sengaja DIPISAH dari paling_untung(). Keduanya hampir selalu berbeda
    tingkat, dan menyatukannya jadi satu angka "harga rekomendasi" akan
    menyembunyikan pertukaran yang justru harus dilihat orang.
    """
    return max(tangga, key=lambda t: t.naik_pct) if tangga else None


def paling_untung(tangga: list) -> Tingkat | None:
    """Tingkat dengan HARAPAN tertinggi -- yang paling menguntungkan."""
    return max(tangga, key=lambda t: t.harapan_pct) if tangga else None


def saran_cicil(harga: float, atr_pct: float | None = None,
                porsi_pasar: float = PORSI_PASAR,
                nilai_harian: float | None = None) -> dict | None:
    """Saran membagi pembelian jadi dua bagian.

    KENAPA DICICIL, dan ini kesimpulan dari angkanya sendiri: menaruh
    seluruh posisi di pasar memberi harapan tertinggi tapi win rate
    terendah (44,4%); menaruh seluruhnya di diskon memberi win rate
    tertinggi tapi harapan terendah. Membaginya mengambil sebagian dari
    keduanya, dan -- yang lebih penting -- membuat hasilnya tidak
    bergantung pada tebakan apakah harga akan turun dulu.
    """
    tangga = tangga_beli(harga, atr_pct, nilai_harian)
    if not tangga:
        return None
    pasar = tangga[0]
    # Tingkat diskon untuk bagian kedua: yang win rate-nya nyata lebih
    # baik tapi peluang terisinya masih di atas separuh. Di bawah itu,
    # bagian keduanya lebih sering tidak terbeli daripada terbeli.
    calon = [t for t in tangga if t.diskon_pct > 0 and t.terisi_pct >= 50]
    kedua = max(calon, key=lambda t: t.naik_pct) if calon else None
    return {
        "harga_pasar": pasar.harga,
        "porsi_pasar_pct": round(porsi_pasar * 100),
        "harga_cicil": kedua.harga if kedua else None,
        "diskon_cicil_pct": kedua.diskon_pct if kedua else None,
        "peluang_cicil_terisi_pct": kedua.terisi_pct if kedua else None,
        "naik_pasar_pct": pasar.naik_pct,
        "naik_cicil_pct": kedua.naik_pct if kedua else None,
    }
