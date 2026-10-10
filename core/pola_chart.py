"""Pola chart klasik, dideteksi dengan aturan yang bisa diperiksa.

DIMULAI DARI SATU POLA, BUKAN SEPULUH. Divergence RSI -- pola yang jauh
lebih sederhana daripada Head & Shoulders -- ternyata punya keunggulan
NEGATIF sampai disaring kedalaman jatuhnya (diukur 10 Okt 2026). Kalau
pola sesederhana itu saja tidak bekerja apa adanya, memasang sepuluh pola
sekaligus tanpa mengukur satu pun berarti memasang sepuluh janji yang
tidak diketahui benar atau tidak.

INVERSE HEAD & SHOULDERS dipilih lebih dulu karena ia punya aturan
konfirmasi yang JELAS -- tembus neckline -- sehingga bisa diukur tanpa
penilaian subjektif. Pola seperti wedge dan triangle butuh garis tren
yang digambar tangan, dan "akurat" untuk pola semacam itu sangat
bergantung pada siapa yang menggambar.

ATURANNYA, dari Edwards & Magee lewat Murphy (sumber yang sama yang
diadaptasi Edianto Ong di buku rujukan penulis):

  - tiga lembah: bahu kiri, KEPALA (terendah), bahu kanan
  - kedua bahu kira-kira sejajar
  - neckline = garis lewat dua puncak di antara ketiga lembah
  - KONFIRMASI = harga menutup di ATAS neckline
  - volume sebaiknya meningkat saat menembus

TIDAK ADA YANG MENGINTIP MASA DEPAN. Lembah dan puncak baru sah sesudah
JEDA_KANAN bar berikutnya terbukti berbalik -- pelajaran yang sama dengan
NR7 dan divergence. Polanya memang baru terbaca beberapa hari setelah
bahu kanannya terbentuk, dan itu harga kejujurannya.
"""
from dataclasses import dataclass

from core.divergence import JEDA_KANAN, JEDA_KIRI, pivot_low

# Selisih tinggi kedua bahu, relatif terhadap dalamnya kepala. Bahu yang
# terlalu timpang bukan lagi H&S -- ia cuma tiga lembah sembarang, dan
# pola yang definisinya terlalu longgar akan "ditemukan" di mana-mana.
TOLERANSI_BAHU = 0.35

# Kepala harus LEBIH DALAM dari bahu sebesar ini (relatif harga kepala).
# Tanpa ambang, tiga lembah yang nyaris sama tinggi lolos sebagai H&S.
MIN_KEPALA_LEBIH_DALAM = 0.02

# Rentang jarak antar-lembah yang masuk akal.
MIN_JARAK_BAHU = 5
MAKS_JARAK_BAHU = 60

# Sesudah sekian bar dari bahu kanan tanpa tembus, polanya dianggap gagal.
# Pola yang menunggu terlalu lama bukan lagi pola yang sama -- keadaan
# yang melahirkannya sudah berganti.
MAKS_UMUR_BAR = 30


def pivot_high(nilai: list, kiri: int = JEDA_KIRI, kanan: int = JEDA_KANAN) -> list:
    """Puncak lokal. Cerminan pivot_low, termasuk penjaga daerah datar --
    tanpa itu, harga yang mendatar melahirkan puncak palsu di tiap bar."""
    n = len(nilai)
    keluar = []
    for i in range(kiri, n - kanan):
        if nilai[i] != max(nilai[i - kiri:i + kanan + 1]):
            continue
        if nilai[i] > nilai[i - kiri] and nilai[i] > nilai[i + kanan]:
            keluar.append(i)
    return keluar


@dataclass(frozen=True)
class IHS:
    kode: str
    tanggal_bahu_kiri: str
    tanggal_kepala: str
    tanggal_bahu_kanan: str
    harga_bahu_kiri: float
    harga_kepala: float
    harga_bahu_kanan: float
    neckline: float           # pada bar terakhir (garisnya boleh miring)
    # Dua jangkar neckline, untuk MENGGAMBAR garisnya. `neckline` di atas
    # cuma nilainya pada bar terakhir: cukup untuk menilai tembus, tidak
    # cukup untuk menggambar. Garis mendatar di nilai itu akan keliru
    # setiap kali neckline-nya miring -- dan miring itu lumrah.
    tanggal_neck1: str
    harga_neck1: float
    tanggal_neck2: str
    harga_neck2: float
    harga_kini: float
    umur_bar: int             # sejak bahu kanan
    tembus: bool              # sudah menutup di atas neckline?
    potensi_pct: float        # tinggi pola, diproyeksikan dari neckline

    @property
    def setup_id(self) -> str:
        """Tetap selama polanya sama -- supaya satu pola tidak terhitung
        berkali-kali saat dipindai tiap hari. Pelajaran dari divergence,
        di mana 10 setup sempat terhitung 80 kejadian."""
        return (f"{self.kode}:ihs:{self.tanggal_bahu_kiri}:"
                f"{self.tanggal_kepala}:{self.tanggal_bahu_kanan}")


def _neckline_pada(i1: int, h1: float, i2: int, h2: float, i: int) -> float:
    """Tinggi neckline pada bar i. Garisnya boleh miring -- neckline datar
    itu kasus khusus, bukan syarat."""
    if i2 == i1:
        return max(h1, h2)
    kemiringan = (h2 - h1) / (i2 - i1)
    return h1 + kemiringan * (i - i1)


def cari_ihs(kode: str, tanggal: list, tinggi: list, rendah: list,
             tutup: list) -> IHS | None:
    """Inverse H&S yang sedang berlaku pada bar terakhir, atau None."""
    n = len(tutup)
    if n < 60 or not (len(tanggal) == len(tinggi) == len(rendah) == n):
        return None
    akhir = n - 1

    lembah = [p for p in pivot_low(rendah) if p + JEDA_KANAN <= akhir]
    if len(lembah) < 3:
        return None
    kiri, kepala, kanan = lembah[-3], lembah[-2], lembah[-1]

    umur = akhir - kanan
    if umur > MAKS_UMUR_BAR:
        return None
    for a, b in ((kiri, kepala), (kepala, kanan)):
        if not (MIN_JARAK_BAHU <= b - a <= MAKS_JARAK_BAHU):
            return None

    hk, hh, hn = float(rendah[kiri]), float(rendah[kepala]), float(rendah[kanan])
    if hh <= 0:
        return None
    # Kepala harus benar-benar lebih dalam dari KEDUA bahu.
    if not (hh < hk * (1 - MIN_KEPALA_LEBIH_DALAM)
            and hh < hn * (1 - MIN_KEPALA_LEBIH_DALAM)):
        return None
    # Bahu kira-kira sejajar, diukur relatif terhadap dalamnya kepala --
    # bukan terhadap harga, supaya ambangnya sepadan untuk saham mahal
    # maupun murah.
    dalam = ((hk + hn) / 2) - hh
    if dalam <= 0 or abs(hk - hn) / dalam > TOLERANSI_BAHU:
        return None

    # Neckline: puncak tertinggi di antara bahu kiri-kepala, dan di antara
    # kepala-bahu kanan.
    p1 = [p for p in pivot_high(tinggi) if kiri < p < kepala]
    p2 = [p for p in pivot_high(tinggi) if kepala < p < kanan]
    if not p1 or not p2:
        return None
    i1 = max(p1, key=lambda p: tinggi[p])
    i2 = max(p2, key=lambda p: tinggi[p])
    garis = _neckline_pada(i1, float(tinggi[i1]), i2, float(tinggi[i2]), akhir)
    # Neckline yang jatuh di BAWAH kepala itu mustahil untuk H&S terbalik:
    # polanya didefinisikan sebagai lembah-lembah DI BAWAH neckline, dan
    # proyeksi targetnya jadi negatif. Terjadi saat garisnya menukik tajam
    # lalu diperpanjang jauh ke kanan. Ditemukan pada 1 dari 48 pola saat
    # memeriksa BENTUK hasil deteksi -- bukan hasilnya.
    if garis <= 0 or garis <= hh:
        return None

    kini = float(tutup[akhir])
    # Tinggi pola diproyeksikan dari neckline -- target klasiknya.
    tinggi_pola = garis - hh
    return IHS(
        kode=(kode or "").upper(),
        tanggal_bahu_kiri=str(tanggal[kiri]), tanggal_kepala=str(tanggal[kepala]),
        tanggal_bahu_kanan=str(tanggal[kanan]),
        harga_bahu_kiri=hk, harga_kepala=hh, harga_bahu_kanan=hn,
        neckline=round(garis, 2),
        tanggal_neck1=str(tanggal[i1]), harga_neck1=float(tinggi[i1]),
        tanggal_neck2=str(tanggal[i2]), harga_neck2=float(tinggi[i2]),
        harga_kini=kini, umur_bar=umur,
        tembus=kini > garis,
        potensi_pct=round(tinggi_pola / garis * 100, 2),
    )


# ---------------------------------------------------------------------------
# FALLING WEDGE (baji turun)
# ---------------------------------------------------------------------------
# Dipilih sebagai pola kedua yang diuji BUKAN karena ia populer, tapi
# karena sifatnya PALING BERBEDA dari Inverse H&S yang sudah gagal: IHS
# soal bentuk tiga lembah, wedge soal MEREDANYA tekanan jual -- jarak
# antara puncak dan lembah yang makin menyempit. Itu sejenis dengan panel
# Pemulihan yang terbukti bekerja (+4,11%), jadi kalau ia pun negatif,
# kesimpulannya jauh lebih kuat daripada menguji sembilan pola bentuk lain.
#
# DEFINISINYA, dan tiap syarat ada alasannya:
#   - garis atas (lewat puncak-puncak) dan garis bawah (lewat lembah-lembah)
#     sama-sama MENURUN  -> ini pola di dalam tren turun, bukan konsolidasi
#   - garis atas menurun LEBIH CURAM  -> itu arti "menyempit"; tanpa syarat
#     ini, saluran turun sejajar ikut lolos dan ia pola yang berbeda
#   - lebarnya menyusut cukup banyak -> penyempitan yang cuma beberapa
#     persen tidak bisa dibedakan dari derau
#   - garisnya belum berpotongan -> sesudah berpotongan, polanya bukan
#     wedge lagi melainkan sudah selesai

MIN_PIVOT_WEDGE = 2          # minimum puncak DAN lembah di dalam jendela
JENDELA_WEDGE = 60           # bar ke belakang yang dipertimbangkan
MIN_PENYEMPITAN = 0.30       # lebar akhir maksimal 70% dari lebar awal
MAKS_UMUR_WEDGE = 15         # sesudah ini, tembusnya bukan tembus wedge lagi


def _garis(titik: list) -> tuple[float, float] | None:
    """(kemiringan, intersep) lewat titik-titik (indeks, harga).

    Kuadrat terkecil, bukan cuma dua titik pertama-terakhir: dua titik
    membuat garisnya sangat bergantung pada pilihan pivot, dan pilihan
    pivot adalah bagian yang paling subjektif dari analisis wedge.
    """
    n = len(titik)
    if n < 2:
        return None
    sx = sum(p[0] for p in titik)
    sy = sum(p[1] for p in titik)
    sxx = sum(p[0] * p[0] for p in titik)
    sxy = sum(p[0] * p[1] for p in titik)
    pembagi = n * sxx - sx * sx
    if pembagi == 0:
        return None
    m = (n * sxy - sx * sy) / pembagi
    return m, (sy - m * sx) / n


@dataclass(frozen=True)
class Wedge:
    kode: str
    tanggal_mulai: str
    tanggal_akhir: str          # tanggal PEMINDAIAN, bukan penanda pola
    tanggal_pivot_akhir: str    # pivot terakhir yang membentuknya
    garis_atas: float          # nilai pada bar terakhir
    garis_bawah: float
    # Nilai kedua garis di bar MULAI. Dengan ini garisnya bisa digambar
    # sebagai dua ruas lurus tanpa pembacanya perlu menghitung ulang
    # kemiringan -- dan tanpa risiko ia menghitungnya dengan satuan yang
    # berbeda (kemiringan di bawah disimpan sbg PERSEN per bar).
    garis_atas_awal: float
    garis_bawah_awal: float
    kemiringan_atas: float     # % harga per bar
    kemiringan_bawah: float
    penyempitan_pct: float     # berapa persen lebarnya menyusut
    n_puncak: int
    n_lembah: int
    harga_kini: float
    tembus: bool               # menutup di atas garis atas?

    @property
    def setup_id(self) -> str:
        """Penanda yang TETAP selama polanya sama.

        Sempat memakai `tanggal_akhir` -- yaitu tanggal PEMINDAIAN, yang
        berubah tiap hari. Akibatnya satu wedge yang bertahan dua minggu
        terhitung sepuluh kejadian, dan pengukurannya melaporkan 3.808
        wedge per tahun dari 178 saham: dua puluh satu per saham per
        tahun, mustahil untuk pola chart.

        Ini jebakan yang SAMA yang sudah ditutup di core/divergence.py
        (10 setup sempat terhitung 80 kejadian). Ia terulang karena
        penandanya ditulis ulang dari nol, bukan dipakai bersama.
        """
        # `tanggal_mulai` SENGAJA TIDAK ikut, walau dulu ikut.
        #
        # Ia diambil dari pivot tertua DI DALAM JENDELA BERGULIR
        # (akhir - JENDELA_WEDGE). Begitu jendelanya maju satu hari,
        # pivot tertua bisa keluar dan tanggal_mulai berganti -- padahal
        # wedge-nya sama persis. Penandanya ikut berganti, dan satu
        # wedge terhitung sebagai beberapa kejadian.
        #
        # Ini jebakan penggelembungan n yang SAMA yang sudah ditutup di
        # core/divergence.py dan di BullFlag, muncul lagi dengan samaran
        # baru: dulu yang menyusup adalah tanggal PEMINDAIAN, sekarang
        # tepi jendela. Keduanya berubah tanpa polanya berubah.
        #
        # Pivot TERAKHIR aman: ia tidak pernah keluar jendela selama
        # polanya masih berlaku (MAKS_UMUR_WEDGE jauh lebih pendek dari
        # JENDELA_WEDGE), dan dua wedge berbeda di emiten yang sama
        # mustahil berbagi pivot terakhir.
        return f"{self.kode}:wedge:{self.tanggal_pivot_akhir}"


def cari_falling_wedge(kode: str, tanggal: list, tinggi: list, rendah: list,
                       tutup: list) -> Wedge | None:
    """Falling wedge yang sedang berlaku pada bar terakhir, atau None."""
    n = len(tutup)
    if n < 80 or not (len(tanggal) == len(tinggi) == len(rendah) == n):
        return None
    akhir = n - 1
    awal = max(0, akhir - JENDELA_WEDGE)

    puncak = [p for p in pivot_high(tinggi)
              if awal <= p <= akhir - JEDA_KANAN]
    lembah = [p for p in pivot_low(rendah)
              if awal <= p <= akhir - JEDA_KANAN]
    if len(puncak) < MIN_PIVOT_WEDGE or len(lembah) < MIN_PIVOT_WEDGE:
        return None

    atas = _garis([(p, float(tinggi[p])) for p in puncak])
    bawah = _garis([(p, float(rendah[p])) for p in lembah])
    if not atas or not bawah:
        return None
    ma, ca = atas
    mb, cb = bawah

    # Keduanya menurun. Tanpa ini, pola naik atau mendatar ikut lolos.
    if ma >= 0 or mb >= 0:
        return None
    # Menyempit: garis atas turun lebih curam. Sama curam = saluran turun
    # sejajar, pola yang berbeda dan tidak sedang diuji di sini.
    if ma >= mb:
        return None

    # PIVOTNYA HARUS BENAR-BENAR BERURUTAN MENURUN.
    #
    # CACAT NYATA, ditemukan penulis dengan MATA pada chart IHSG yang
    # dilabeli "Falling Wedge" padahal bentuknya reli lalu anjlok.
    # Pivot puncaknya: 6.454 -> 6.463 -> 6.552 -> 6.713 -> 6.216.
    # Naik, naik, naik, lalu jatuh.
    #
    # Syarat di atas cuma memeriksa TANDA KEMIRINGAN garis regresinya,
    # dan satu pivot terakhir yang ambruk sudah cukup menyeret garis
    # sebuah struktur NAIK menjadi negatif. Regresi menjawab
    # "rata-ratanya ke mana"; wedge menuntut "tiap langkahnya ke mana"
    # -- dua pertanyaan berbeda, dan yang kedua itu yang dilihat mata.
    #
    # Berlaku untuk rising wedge juga: ia dibuat dari pencerminan modul
    # ini, jadi satu perbaikan menutup keduanya.
    if not all(tinggi[b] < tinggi[a] for a, b in zip(puncak, puncak[1:])):
        return None
    if not all(rendah[b] < rendah[a] for a, b in zip(lembah, lembah[1:])):
        return None

    mulai = min(puncak[0], lembah[0])
    lebar_awal = (ma * mulai + ca) - (mb * mulai + cb)
    atas_kini = ma * akhir + ca
    bawah_kini = mb * akhir + cb
    lebar_kini = atas_kini - bawah_kini
    # Sudah berpotongan = polanya selesai, bukan sedang berlangsung.
    if lebar_awal <= 0 or lebar_kini <= 0:
        return None
    penyempitan = 1 - lebar_kini / lebar_awal
    if penyempitan < MIN_PENYEMPITAN:
        return None

    # Umur dihitung dari pivot TERAKHIR yang membentuknya.
    pivot_akhir = max(puncak[-1], lembah[-1])
    if akhir - pivot_akhir > MAKS_UMUR_WEDGE:
        return None

    kini = float(tutup[akhir])
    if atas_kini <= 0:
        return None
    return Wedge(
        kode=(kode or "").upper(),
        tanggal_mulai=str(tanggal[mulai]), tanggal_akhir=str(tanggal[akhir]),
        tanggal_pivot_akhir=str(tanggal[pivot_akhir]),
        garis_atas=round(atas_kini, 2), garis_bawah=round(bawah_kini, 2),
        garis_atas_awal=round(ma * mulai + ca, 2),
        garis_bawah_awal=round(mb * mulai + cb, 2),
        kemiringan_atas=round(ma / atas_kini * 100, 4),
        kemiringan_bawah=round(mb / atas_kini * 100, 4),
        penyempitan_pct=round(penyempitan * 100, 1),
        n_puncak=len(puncak), n_lembah=len(lembah),
        harga_kini=kini, tembus=kini > atas_kini,
    )


# ---------------------------------------------------------------------------
# BULL FLAG (bendera naik) -- pola LANJUTAN, bukan pembalikan
# ---------------------------------------------------------------------------
# Dipilih sebagai pola ketiga karena ia satu-satunya jenis yang belum
# diuji sama sekali. Inverse H&S dan falling wedge dua-duanya pola
# PEMBALIKAN, dan dua-duanya gagal (-0,68% dan +1,24% dengan win rate di
# bawah pasar). Bull flag bertaruh pada hal yang berlawanan: tren yang
# sedang berjalan akan BERLANJUT.
#
# Ada petunjuk bahwa arah ini lebih menjanjikan. Diukur di sesi
# sebelumnya, "Pullback di tren naik + likuid" naik keesokan harinya
# 43,6% dari waktu melawan dasar 37,5% -- setup terbaik dari dua belas
# yang diuji untuk membeli di pembukaan besok. Bull flag adalah
# pullback-dalam-tren-naik yang diformalkan: tiang, lalu istirahat
# dangkal, lalu lanjut.
#
# BENTUKNYA:
#   TIANG   : kenaikan tajam dalam waktu pendek
#   BENDERA : istirahat yang DANGKAL dan menurun/mendatar -- kalau
#             turunnya dalam, itu bukan istirahat melainkan pembalikan
#   TEMBUS  : harga menutup di atas puncak benderanya

MIN_TIANG_PCT = 15.0       # kenaikan minimum yang layak disebut tiang
MAKS_TIANG_BAR = 25        # ... dan harus terjadi dalam rentang ini
MIN_BENDERA_BAR = 3
MAKS_BENDERA_BAR = 20
# Koreksi maksimum selama bendera, sebagai porsi tinggi tiangnya. Lebih
# dari separuh tiang termakan = itu bukan istirahat, itu pembalikan.
MAKS_KOREKSI_TIANG = 0.50


@dataclass(frozen=True)
class BullFlag:
    kode: str
    tanggal_tiang_mulai: str
    tanggal_tiang_puncak: str
    harga_tiang_mulai: float
    harga_tiang_puncak: float
    tiang_pct: float
    bendera_bar: int
    koreksi_pct: float          # dari puncak tiang, negatif
    koreksi_thd_tiang: float    # porsi tinggi tiang yang termakan
    puncak_bendera: float
    harga_kini: float
    tembus: bool

    @property
    def setup_id(self) -> str:
        """Penanda dari TANGGAL POLANYA, bukan tanggal pemindaian.

        Jebakan yang sama sudah dua kali menggelembungkan angka di proyek
        ini -- divergence (10 setup terhitung 80) dan falling wedge (3.808
        pola per tahun, mustahil). Keduanya terjadi karena penandanya
        ditulis ulang dari nol di tiap modul.
        """
        return (f"{self.kode}:flag:{self.tanggal_tiang_mulai}:"
                f"{self.tanggal_tiang_puncak}")


def cari_bull_flag(kode: str, tanggal: list, tinggi: list, rendah: list,
                   tutup: list) -> BullFlag | None:
    """Bull flag yang sedang berlaku pada bar terakhir, atau None."""
    n = len(tutup)
    if n < 60 or not (len(tanggal) == len(tinggi) == len(rendah) == n):
        return None
    akhir = n - 1

    # Puncak tiang = tinggi TERTINGGI dalam jendela di mana benderanya
    # mungkin berada. Dicari dengan argmax, BUKAN dengan mencoba tiap
    # panjang bendera lalu berhenti di yang pertama cocok.
    #
    # DUA CACAT yang ditutup di sini, keduanya rancangan saya sendiri dan
    # keduanya ketahuan dari angka yang mustahil saat mengukur:
    #
    # 1. Versi pertama mensyaratkan puncak tiang tetap yang TERTINGGI
    #    sampai bar terakhir. Akibatnya begitu harga menembusnya, polanya
    #    berhenti terdeteksi -- dan "sudah tembus" melaporkan NOL kejadian
    #    dari 5.664 pola. Breakout, yang justru inti pola lanjutan,
    #    tersingkir oleh syarat deteksinya sendiri.
    #
    # 2. Versi pertama mencoba panjang bendera dari yang terpendek lalu
    #    BERHENTI di yang pertama cocok. Akibatnya "bendera panjang"
    #    melaporkan SATU kejadian dari 5.664 -- bukan karena bendera
    #    panjang itu langka, tapi karena ia tidak pernah sempat dilihat.
    jendela_awal = max(0, akhir - MAKS_BENDERA_BAR)
    jendela_akhir = akhir - MIN_BENDERA_BAR
    if jendela_akhir <= jendela_awal:
        return None
    i_puncak = max(range(jendela_awal, jendela_akhir + 1),
                   key=lambda j: float(tinggi[j]))
    lama_bendera = akhir - i_puncak

    # Dasar tiang: titik terendah dalam MAKS_TIANG_BAR bar sebelum puncak.
    tiang_awal = max(0, i_puncak - MAKS_TIANG_BAR)
    if i_puncak - tiang_awal < 2:
        return None
    i_dasar = min(range(tiang_awal, i_puncak), key=lambda j: float(rendah[j]))
    h_dasar, h_puncak = float(rendah[i_dasar]), float(tinggi[i_puncak])
    if h_dasar <= 0:
        return None
    tiang = (h_puncak / h_dasar - 1) * 100
    if tiang < MIN_TIANG_PCT:
        return None

    bendera_rendah = min(float(x) for x in rendah[i_puncak + 1:akhir + 1])
    koreksi = (bendera_rendah / h_puncak - 1) * 100       # negatif
    tinggi_tiang = h_puncak - h_dasar
    if tinggi_tiang <= 0:
        return None
    porsi = (h_puncak - bendera_rendah) / tinggi_tiang
    # Istirahat yang dangkal. Lebih dari separuh tiang termakan = itu
    # pembalikan, bukan bendera -- dan pola yang definisinya memuat
    # keduanya tidak memberi tahu apa pun.
    if porsi > MAKS_KOREKSI_TIANG:
        return None

    kini = float(tutup[akhir])
    return BullFlag(
        kode=(kode or "").upper(),
        tanggal_tiang_mulai=str(tanggal[i_dasar]),
        tanggal_tiang_puncak=str(tanggal[i_puncak]),
        harga_tiang_mulai=h_dasar, harga_tiang_puncak=h_puncak,
        tiang_pct=round(tiang, 2), bendera_bar=lama_bendera,
        koreksi_pct=round(koreksi, 2), koreksi_thd_tiang=round(porsi, 3),
        puncak_bendera=round(h_puncak, 2), harga_kini=kini,
        tembus=kini > h_puncak,
    )
