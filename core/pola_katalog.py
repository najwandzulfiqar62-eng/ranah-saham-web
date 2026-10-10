"""Katalog pola chart klasik + satu jawaban: emiten ini sedang fase apa.

SUMBERNYA. Bab pola chart di "Technical Analysis for Mega Profit"
(Edianto Ong) mengadaptasi Edwards & Magee lewat Murphy, dan membaginya
jadi dua keluarga:

  PEMBALIKAN (reversal) -- muncul di UJUNG tren, menandai arah berbalik
    Head & Shoulders (atas)          turun
    Inverse Head & Shoulders         naik
    Double Top / Double Bottom       turun / naik
    Triple Top / Triple Bottom       turun / naik
    Rounding Top / Rounding Bottom   turun / naik

  PENERUSAN (continuation) -- muncul di TENGAH tren, menandai jeda
    Rising Wedge                     turun   <- naik tapi BEARISH
    Falling Wedge                    naik    <- turun tapi BULLISH
    Bull Flag / Bear Flag            naik / turun
    Segitiga Menaik / Menurun        naik / turun
    Segitiga Simetris                penerusan (ikut tren sebelumnya)
    Rectangle                        penerusan
    Cup with Handle                  naik

Dua yang paling sering salah dibaca sengaja ditandai di atas: Rising
Wedge garisnya NAIK tapi artinya turun, dan Falling Wedge sebaliknya.
Penulis sendiri pernah salah membaca Inverse H&S sebagai sinyal jual.

CARA POLA BERLAWANAN ARAH DIBUAT. Tidak ditulis dua kali. Harga
DICERMINKAN (dinegatifkan, tinggi<->rendah ditukar) lalu pencari arah
"naik" dijalankan di atasnya. Alasannya bukan hemat baris: dua
implementasi yang seharusnya cermin SELALU berakhir menyimpang -- satu
diperbaiki, satunya terlupa, dan tidak ada yang sadar karena keduanya
"jalan". Pencerminannya eksak sampai ke arah tembusnya; lihat
_cermin() dan tesnya.

APA YANG DILAPORKAN. Bukan "beli" atau "jual", melainkan FASE:

  TERBENTUK  bentuknya lengkap, tapi BELUM menembus level kuncinya
  TEMBUS     sudah menutup melewati level kuncinya, ke arah polanya

Pembedaan ini bukan hiasan. Pola yang belum tembus itu belum pola --
Edwards & Magee menuntut konfirmasi, dan sebagian besar bentuk yang
terlihat seperti pola tidak pernah dikonfirmasi. Menampilkan keduanya
dengan kata yang sama akan membuat separuh daftar ini bohong.

TIDAK ADA YANG MENGINTIP MASA DEPAN. Semua pivot baru sah sesudah
JEDA_KANAN bar berikutnya terbukti berbalik -- pelajaran NR7 (separuh
sinyalnya artefak bar sesi berjalan) dan divergence. Konsekuensinya
polanya baru terbaca beberapa hari sesudah terbentuk, dan itu harga
kejujurannya.

ANGKA KEUNGGULAN TIAP POLA ADA DI core/pola_ukur.py, bukan di sini --
modul ini cuma mendeteksi bentuk. Yang belum diukur TIDAK boleh
ditampilkan dengan angka.
"""
from dataclasses import dataclass, field

from core.divergence import JEDA_KANAN, JEDA_KIRI, pivot_low
from core.pola_chart import (MAKS_UMUR_BAR, _garis, _neckline_pada,
                             cari_bull_flag, cari_falling_wedge, cari_ihs,
                             pivot_high)

# ---------------------------------------------------------------------------
# HASIL SERAGAM
# ---------------------------------------------------------------------------
# Satu bentuk hasil untuk SEMUA pola. Tanpa ini, tiap pola punya dataclass
# sendiri dengan nama medan yang beda-beda, dan baik pengukur maupun layar
# harus tahu dua belas bentuk -- itu dua belas tempat yang bisa tidak
# sinkron.


@dataclass(frozen=True)
class Pola:
    kode: str
    nama: str                 # "Rising Wedge", "Inverse Head & Shoulders", ...
    keluarga: str             # "pembalikan" | "penerusan"
    arah: str                 # "naik" | "turun"
    fase: str                 # "TERBENTUK" | "TEMBUS"
    setup_id: str             # TETAP selama polanya sama (lihat catatan)
    tanggal_mulai: str
    tanggal_kunci: str        # pivot terakhir yang membentuknya
    level_kunci: float        # neckline / garis tren yang harus ditembus
    harga_kini: float
    umur_bar: int
    potensi_pct: float | None  # target klasik, None kalau polanya tak punya

    # --- bahan GAMBAR -----------------------------------------------------
    # Koordinat, bukan sekadar level. Alasannya: menggambar neckline H&S
    # sebagai garis MENDATAR di nilai terakhirnya akan keliru setiap kali
    # neckline-nya miring -- dan miring itu lumrah, bukan kasus khusus.
    # Gambar yang keliru lebih buruk daripada tidak menggambar: pembaca
    # memverifikasi analisisnya LEWAT gambar itu.
    #
    # titik: [{"t": "2026-01-02", "p": 123.0, "label": "KEPALA"}, ...]
    # garis: [{"nama": "Neckline", "titik": [{"t":..,"p":..}, ...]}, ...]
    titik: list = field(default_factory=list)
    garis: list = field(default_factory=list)

    @property
    def tembus(self) -> bool:
        return self.fase == "TEMBUS"


def _t(tanggal, p, label=""):
    """Satu titik gambar."""
    return {"t": str(tanggal), "p": round(float(p), 2), "label": label}


def _g(nama, *titik):
    """Satu garis gambar."""
    return {"nama": nama, "titik": list(titik)}


def _id(kode: str, slug: str, *bagian) -> str:
    """Penanda setup yang TETAP selama polanya sama.

    JEBAKAN YANG SUDAH TIGA KALI MENGGIGIT proyek ini: memasukkan tanggal
    PEMINDAIAN ke dalam penanda. Satu pola yang bertahan dua minggu lalu
    terhitung sepuluh kejadian, dan pengukurannya melaporkan 3.808 wedge
    per tahun dari 178 saham -- dua puluh satu per saham per tahun,
    mustahil untuk pola chart. Terulang tiga kali karena penandanya
    ditulis ulang dari nol tiap pola; sekarang semuanya lewat sini.
    """
    return ":".join([(kode or "").upper(), slug, *[str(b) for b in bagian]])


# ---------------------------------------------------------------------------
# PENCERMINAN
# ---------------------------------------------------------------------------


def _cermin(tinggi: list, rendah: list, tutup: list):
    """Cerminkan harga sehingga pola arah-turun terbaca sebagai arah-naik.

    PAKAI KEBALIKAN (x' = K/x), BUKAN NEGATIF. Versi pertama memakai
    x' = -x dan hasilnya NOL pola bearish dari 200 emiten -- tiap
    pencari punya penjaga `harga <= 0 -> tolak` yang masuk akal untuk
    harga sungguhan, dan penjaga itu menolak seluruh harga cermin di
    baris pertama. Gejalanya diam: tidak ada error, cuma daftar yang
    selamanya kosong di satu sisi.

    Kebalikan dipilih, bukan sekadar menggeser (K - x), karena SEMUA
    ambang di modul ini bersifat PERSENTASE, dan cuma kebalikan yang
    mencerminkannya dengan eksak:

        x' = K/x   ->   log x' = log K - log x

    yaitu pencerminan sempurna di ruang logaritma, tempat "naik 4%" dan
    "turun 4%" memang berjarak sama. Dengan pergeseran (K - x), kenaikan
    4% di harga Rp500 akan menjadi penurunan yang bukan 4% di cerminnya,
    sehingga pola bullish dan bearish akan dinilai dengan ketatnya yang
    BERBEDA -- dan tidak akan ada yang menyadarinya, karena keduanya
    tetap menghasilkan daftar yang masuk akal.

    Bukti satu syarat (kepala H&S harus d lebih ekstrem dari bahu):
        kepala' < bahu' x (1-d)
        K/Kepala < (K/Bahu)(1-d)
        Bahu < Kepala x (1-d)      ->  Kepala > Bahu / (1-d)
    yaitu "kepala harus d lebih TINGGI dari bahu" -- syarat H&S Top yang
    benar, dengan ketat yang sama persis.

    K dipilih max(tinggi) x min(rendah) supaya hasilnya tetap berada di
    kisaran harga aslinya; nilai K tidak memengaruhi satu pun syarat
    (semuanya ratio), cuma enak dibaca saat menelusuri.
    """
    hi = [float(x) for x in tinggi]
    lo = [float(x) for x in rendah]
    cl = [float(x) for x in tutup]
    if not hi or min(lo) <= 0 or min(hi) <= 0 or min(cl) <= 0:
        return None
    K = max(hi) * min(lo)
    # tinggi<->rendah DITUKAR: kebalikan membalik urutan, jadi tertinggi
    # asli menjadi terendah cermin.
    return ([K / x for x in lo], [K / x for x in hi], [K / x for x in cl]), K


def _balik_harga(x: float | None, K: float) -> float | None:
    """Harga cermin -> harga asli."""
    return None if x in (None, 0) else K / x


# ---------------------------------------------------------------------------
# AMBANG
# ---------------------------------------------------------------------------
# Tiap ambang di bawah ini punya alasan, dan alasannya ditulis. Ambang
# tanpa alasan adalah ambang yang dipas-paskan ke data sesudah melihat
# hasilnya, dan itu cara tercepat menghasilkan pola yang "bekerja" di
# masa lalu saja.

# Dua dasar yang dianggap "sejajar": selisihnya maksimal sekian dari
# tinggi polanya. Dipakai bersama double & triple -- longgar sedikit saja
# dan dua lembah sembarang jadi "double bottom".
TOLERANSI_DASAR = 0.25

# Puncak di antara dua dasar harus setinggi ini (relatif dasar), kalau
# tidak polanya cuma riak.
MIN_TINGGI_POLA = 0.04

MIN_JARAK_DASAR = 8      # dua dasar yang terlalu rapat itu satu dasar
MAKS_JARAK_DASAR = 90

# Segitiga & rectangle
JENDELA_SEGITIGA = 70
MIN_SENTUH = 2           # minimal 2 puncak DAN 2 lembah; 1 tidak membuat garis
MAKS_UMUR_SEGITIGA = 15
# Garis dianggap MENDATAR kalau kemiringannya di bawah sekian persen
# harga per bar. 0,05%/bar = sekitar 3,5% per 70 bar -- cukup ketat untuk
# membedakan sisi datar segitiga menaik dari sisi yang benar-benar miring.
AMBANG_DATAR_PCT = 0.05
MIN_PENYEMPITAN_SEGITIGA = 0.25
# Rectangle sebaliknya: KEDUA sisi datar, dan lebarnya TIDAK menyempit.
MAKS_PENYEMPITAN_RECT = 0.15
MIN_LEBAR_RECT_PCT = 4.0   # kotak yang terlalu tipis cuma derau mendatar

# Rounding bottom / cup
JENDELA_CUP = 120
MIN_DALAM_CUP = 0.12       # cekungan dangkal bukan cup
MAKS_DALAM_CUP = 0.60      # terlalu dalam: itu keruntuhan, bukan cup
MAKS_MIRING_BIBIR = 0.15   # kedua bibir cangkir harus kira-kira sejajar
MAKS_GAGANG_BAR = 25
MIN_GAGANG_BAR = 3
MAKS_DALAM_GAGANG = 0.50   # gagang maksimal setengah kedalaman cangkir

# Parabolanya harus BENAR-BENAR menjelaskan harganya.
#
# Tanpa ambang ini, Rounding Bottom terdeteksi di 59 dari 200 emiten
# (29,5%) -- dan cerminnya, Rounding Top, di 59 emiten yang sama. Pola
# yang muncul di sepertiga pasar bukan pola, itu derau yang diberi nama.
# Sebabnya: tiga syarat lama (cekung, titik balik di tengah, kedalaman
# wajar) semuanya tentang BENTUK parabolanya, dan tak satu pun menuntut
# harganya mengikuti parabola itu. Jalan acak yang kebetulan turun lalu
# naik lolos semuanya.
#
# R^2 mengukur persis yang hilang itu: berapa bagian gerak harga yang
# dijelaskan lengkungannya. 0,70 dipilih sebagai titik tempat sisa
# deteksinya masih berbentuk cangkir saat diperiksa satu per satu --
# bukan angka bulat yang enak dibaca.
MIN_R2_CUP = 0.70


# ---------------------------------------------------------------------------
# DOUBLE / TRIPLE BOTTOM
# ---------------------------------------------------------------------------


def _cari_dasar_ganda(kode: str, tanggal: list, tinggi: list, rendah: list,
                      tutup: list, n_dasar: int) -> Pola | None:
    """Double (n=2) atau Triple (n=3) Bottom pada bar terakhir.

    Satu implementasi untuk keduanya: triple bottom ITU double bottom
    dengan satu dasar tambahan, dan menulisnya terpisah berarti dua
    tempat yang harus diperbaiki tiap kali definisinya berubah.
    """
    n = len(tutup)
    if n < 60 or not (len(tanggal) == len(tinggi) == len(rendah) == n):
        return None
    akhir = n - 1

    lembah = [p for p in pivot_low(rendah) if p + JEDA_KANAN <= akhir]
    if len(lembah) < n_dasar:
        return None
    dasar = lembah[-n_dasar:]

    # Jarak antar-dasar masuk akal
    for a, b in zip(dasar, dasar[1:]):
        if not (MIN_JARAK_DASAR <= b - a <= MAKS_JARAK_DASAR):
            return None

    harga_dasar = [float(rendah[i]) for i in dasar]
    if min(harga_dasar) <= 0:
        return None

    # Puncak-puncak di ANTARA dasar; neckline = yang tertinggi.
    puncak_antara = []
    for a, b in zip(dasar, dasar[1:]):
        kandidat = [p for p in pivot_high(tinggi) if a < p < b]
        if not kandidat:
            return None
        puncak_antara.append(max(kandidat, key=lambda p: tinggi[p]))
    neckline = max(float(tinggi[p]) for p in puncak_antara)

    rata_dasar = sum(harga_dasar) / len(harga_dasar)
    tinggi_pola = neckline - rata_dasar
    if tinggi_pola <= 0:
        return None
    # Polanya harus punya tinggi yang berarti
    if tinggi_pola / rata_dasar < MIN_TINGGI_POLA:
        return None
    # Dasar-dasarnya harus kira-kira SEJAJAR -- itu yang membedakan
    # double bottom dari sekadar dua lembah menurun.
    if (max(harga_dasar) - min(harga_dasar)) / tinggi_pola > TOLERANSI_DASAR:
        return None

    umur = akhir - dasar[-1]
    if umur > MAKS_UMUR_BAR:
        return None

    kini = float(tutup[akhir])
    nama = "Double Bottom" if n_dasar == 2 else "Triple Bottom"
    label = (["DASAR 1", "DASAR 2", "DASAR 3"])[:n_dasar]
    titik = [_t(tanggal[i], rendah[i], lb) for i, lb in zip(dasar, label)]
    # Neckline dasar ganda MENDATAR menurut definisinya (puncak tertinggi
    # di antara dasar), jadi dua titik di ketinggian yang sama memang
    # gambar yang benar di sini -- berbeda dengan neckline H&S.
    garis = [_g("Neckline", _t(tanggal[dasar[0]], neckline),
                _t(tanggal[akhir], neckline))]
    return Pola(
        kode=(kode or "").upper(), nama=nama, keluarga="pembalikan",
        arah="naik", fase="TEMBUS" if kini > neckline else "TERBENTUK",
        setup_id=_id(kode, "dasar%d" % n_dasar,
                     *[str(tanggal[i]) for i in dasar]),
        tanggal_mulai=str(tanggal[dasar[0]]),
        tanggal_kunci=str(tanggal[dasar[-1]]),
        level_kunci=round(neckline, 2), harga_kini=kini, umur_bar=umur,
        potensi_pct=round(tinggi_pola / neckline * 100, 2),
        titik=titik, garis=garis,
    )


# ---------------------------------------------------------------------------
# SEGITIGA & RECTANGLE
# ---------------------------------------------------------------------------


def _dua_garis(tinggi: list, rendah: list, akhir: int, jendela: int):
    """(garis atas, garis bawah, indeks pivot) dari jendela terakhir."""
    awal = max(0, akhir - jendela)
    puncak = [p for p in pivot_high(tinggi) if awal <= p <= akhir - JEDA_KANAN]
    lembah = [p for p in pivot_low(rendah) if awal <= p <= akhir - JEDA_KANAN]
    if len(puncak) < MIN_SENTUH or len(lembah) < MIN_SENTUH:
        return None
    atas = _garis([(p, float(tinggi[p])) for p in puncak])
    bawah = _garis([(p, float(rendah[p])) for p in lembah])
    if not atas or not bawah:
        return None
    return atas, bawah, puncak, lembah


def cari_segitiga(kode: str, tanggal: list, tinggi: list, rendah: list,
                  tutup: list) -> Pola | None:
    """Segitiga menaik / menurun / simetris pada bar terakhir.

    Ketiganya satu fungsi karena bedanya CUMA kemiringan dua garis yang
    sama. Memisahkannya jadi tiga fungsi berarti tiga salinan pencarian
    pivot dan pencocokan garis yang identik.
    """
    n = len(tutup)
    if n < 80 or not (len(tanggal) == len(tinggi) == len(rendah) == n):
        return None
    akhir = n - 1
    hasil = _dua_garis(tinggi, rendah, akhir, JENDELA_SEGITIGA)
    if not hasil:
        return None
    (ma, ca), (mb, cb), puncak, lembah = hasil

    atas_kini = ma * akhir + ca
    bawah_kini = mb * akhir + cb
    if atas_kini <= 0 or bawah_kini <= 0 or atas_kini <= bawah_kini:
        return None

    # Kemiringan dinyatakan sebagai PERSEN harga per bar supaya satu
    # ambang berlaku untuk saham Rp50 maupun Rp50.000.
    pa = ma / atas_kini * 100
    pb = mb / atas_kini * 100
    datar_atas = abs(pa) < AMBANG_DATAR_PCT
    datar_bawah = abs(pb) < AMBANG_DATAR_PCT

    mulai = min(puncak[0], lembah[0])
    lebar_awal = (ma * mulai + ca) - (mb * mulai + cb)
    lebar_kini = atas_kini - bawah_kini
    if lebar_awal <= 0:
        return None
    penyempitan = 1 - lebar_kini / lebar_awal

    if datar_atas and mb > 0:
        nama, arah, level = "Segitiga Menaik", "naik", atas_kini
    elif datar_bawah and ma < 0:
        nama, arah, level = "Segitiga Menurun", "turun", bawah_kini
    elif ma < 0 and mb > 0:
        nama, arah, level = "Segitiga Simetris", "penerusan", atas_kini
    else:
        return None

    if penyempitan < MIN_PENYEMPITAN_SEGITIGA:
        return None

    pivot_akhir = max(puncak[-1], lembah[-1])
    umur = akhir - pivot_akhir
    if umur > MAKS_UMUR_SEGITIGA:
        return None

    kini = float(tutup[akhir])
    # Simetris tidak punya arah sendiri: ia ikut ke mana pun ia tembus,
    # jadi "TEMBUS"-nya dinilai dua sisi. Menebak arahnya sebelum tembus
    # adalah persis bagian yang membuat pola ini sering dipakai salah.
    if arah == "penerusan":
        tembus = kini > atas_kini or kini < bawah_kini
    elif arah == "naik":
        tembus = kini > level
    else:
        tembus = kini < level

    return Pola(
        kode=(kode or "").upper(), nama=nama, keluarga="penerusan",
        arah=arah, fase="TEMBUS" if tembus else "TERBENTUK",
        # tanggal[mulai] TIDAK ikut penanda: ia pivot tertua di dalam
        # jendela bergulir, jadi ia bergeser tanpa polanya berubah.
        # Lihat catatan panjang di Wedge.setup_id.
        setup_id=_id(kode, nama.lower().replace(" ", "_"),
                     str(tanggal[pivot_akhir])),
        tanggal_mulai=str(tanggal[mulai]),
        tanggal_kunci=str(tanggal[pivot_akhir]),
        level_kunci=round(level, 2), harga_kini=kini, umur_bar=umur,
        potensi_pct=round(lebar_awal / atas_kini * 100, 2),
        titik=[_t(tanggal[p], tinggi[p], "") for p in puncak]
              + [_t(tanggal[p], rendah[p], "") for p in lembah],
        garis=[
            _g("Resistance", _t(tanggal[mulai], ma * mulai + ca),
               _t(tanggal[akhir], atas_kini)),
            _g("Support", _t(tanggal[mulai], mb * mulai + cb),
               _t(tanggal[akhir], bawah_kini)),
        ],
    )


def cari_rectangle(kode: str, tanggal: list, tinggi: list, rendah: list,
                   tutup: list) -> Pola | None:
    """Rectangle: dua sisi MENDATAR dan lebarnya TIDAK menyempit.

    Syarat "tidak menyempit" itu yang memisahkannya dari segitiga
    simetris. Tanpa syarat itu keduanya saling mengklaim bentuk yang
    sama, dan emiten akan dilabeli dua pola yang bertentangan.
    """
    n = len(tutup)
    if n < 80 or not (len(tanggal) == len(tinggi) == len(rendah) == n):
        return None
    akhir = n - 1
    hasil = _dua_garis(tinggi, rendah, akhir, JENDELA_SEGITIGA)
    if not hasil:
        return None
    (ma, ca), (mb, cb), puncak, lembah = hasil

    atas_kini = ma * akhir + ca
    bawah_kini = mb * akhir + cb
    if atas_kini <= 0 or bawah_kini <= 0 or atas_kini <= bawah_kini:
        return None
    if abs(ma / atas_kini * 100) >= AMBANG_DATAR_PCT:
        return None
    if abs(mb / atas_kini * 100) >= AMBANG_DATAR_PCT:
        return None

    lebar_pct = (atas_kini - bawah_kini) / atas_kini * 100
    if lebar_pct < MIN_LEBAR_RECT_PCT:
        return None

    mulai = min(puncak[0], lembah[0])
    lebar_awal = (ma * mulai + ca) - (mb * mulai + cb)
    if lebar_awal <= 0:
        return None
    if 1 - (atas_kini - bawah_kini) / lebar_awal > MAKS_PENYEMPITAN_RECT:
        return None

    pivot_akhir = max(puncak[-1], lembah[-1])
    umur = akhir - pivot_akhir
    if umur > MAKS_UMUR_SEGITIGA:
        return None

    kini = float(tutup[akhir])
    return Pola(
        kode=(kode or "").upper(), nama="Rectangle", keluarga="penerusan",
        arah="penerusan",
        fase="TEMBUS" if (kini > atas_kini or kini < bawah_kini) else "TERBENTUK",
        setup_id=_id(kode, "rectangle", str(tanggal[pivot_akhir])),
        tanggal_mulai=str(tanggal[mulai]),
        tanggal_kunci=str(tanggal[pivot_akhir]),
        level_kunci=round(atas_kini, 2), harga_kini=kini, umur_bar=umur,
        potensi_pct=round(lebar_pct, 2),
        titik=[_t(tanggal[p], tinggi[p], "") for p in puncak]
              + [_t(tanggal[p], rendah[p], "") for p in lembah],
        garis=[
            _g("Batas atas", _t(tanggal[mulai], ma * mulai + ca),
               _t(tanggal[akhir], atas_kini)),
            _g("Batas bawah", _t(tanggal[mulai], mb * mulai + cb),
               _t(tanggal[akhir], bawah_kini)),
        ],
    )


# ---------------------------------------------------------------------------
# ROUNDING BOTTOM & CUP WITH HANDLE
# ---------------------------------------------------------------------------


def _lengkung(y: list) -> tuple[float, float, float, float] | None:
    """Cocokkan parabola y = a*x^2 + b*x + c, kuadrat terkecil.

    Dipakai untuk rounding bottom: a > 0 berarti cekung ke atas. Parabola
    dipilih, bukan "harga turun lalu naik", karena yang kedua lolos juga
    untuk huruf V -- dan V-reversal itu pola yang BERBEDA (buku
    memisahkannya), dengan arti yang berbeda pula.
    """
    n = len(y)
    if n < 10:
        return None
    sx = sx2 = sx3 = sx4 = 0.0
    sy = sxy = sx2y = 0.0
    for i, v in enumerate(y):
        x = float(i)
        x2 = x * x
        sx += x
        sx2 += x2
        sx3 += x2 * x
        sx4 += x2 * x2
        sy += v
        sxy += x * v
        sx2y += x2 * v
    # Sistem 3x3 lewat eliminasi; determinan nol berarti titiknya segaris.
    A = [[sx4, sx3, sx2, sx2y], [sx3, sx2, sx, sxy], [sx2, sx, float(n), sy]]
    for k in range(3):
        pivot = max(range(k, 3), key=lambda r: abs(A[r][k]))
        if abs(A[pivot][k]) < 1e-12:
            return None
        A[k], A[pivot] = A[pivot], A[k]
        for r in range(k + 1, 3):
            f = A[r][k] / A[k][k]
            for c in range(k, 4):
                A[r][c] -= f * A[k][c]
    sol = [0.0, 0.0, 0.0]
    for k in (2, 1, 0):
        s = A[k][3] - sum(A[k][c] * sol[c] for c in range(k + 1, 3))
        sol[k] = s / A[k][k]
    a, b, c = sol
    # R^2 ikut dihitung di sini, bukan di pemanggil: yang punya residual
    # adalah pencocokannya, dan menghitungnya di tempat lain berarti
    # parabolanya bisa dipakai tanpa pernah diperiksa cocok atau tidak.
    rata = sy / n
    ss_tot = sum((v - rata) ** 2 for v in y)
    ss_res = sum((v - (a * i * i + b * i + c)) ** 2 for i, v in enumerate(y))
    r2 = 1.0 if ss_tot <= 0 else 1 - ss_res / ss_tot
    return a, b, c, r2


def _cari_cangkir(kode: str, tanggal: list, tinggi: list, rendah: list,
                  tutup: list, dengan_gagang: bool) -> Pola | None:
    """Rounding Bottom, dan Cup with Handle kalau ada gagangnya.

    Satu implementasi untuk keduanya: cup with handle ITU rounding bottom
    plus tarikan napas pendek di bibir kanan.
    """
    n = len(tutup)
    if n < JENDELA_CUP or not (len(tanggal) == len(tinggi) == len(rendah) == n):
        return None
    akhir = n - 1

    # Gagang memakan bar paling kanan; cangkirnya berakhir sebelum itu.
    if dengan_gagang:
        # Gagang = koreksi dangkal setelah bibir kanan. Bibir kanannya
        # dicari sebagai puncak tertinggi dalam MAKS_GAGANG_BAR terakhir.
        wil = range(max(0, akhir - MAKS_GAGANG_BAR), akhir + 1)
        bibir_kanan = max(wil, key=lambda i: tinggi[i])
        panjang_gagang = akhir - bibir_kanan
        if not (MIN_GAGANG_BAR <= panjang_gagang <= MAKS_GAGANG_BAR):
            return None
        ujung_cangkir = bibir_kanan
    else:
        ujung_cangkir = akhir
        panjang_gagang = 0

    awal = max(0, ujung_cangkir - JENDELA_CUP)
    if ujung_cangkir - awal < 30:
        return None
    potong = [float(x) for x in tutup[awal:ujung_cangkir + 1]]
    fit = _lengkung(potong)
    if not fit:
        return None
    a, b, _c, r2 = fit
    if a <= 0:
        return None                      # cembung = rounding TOP, bukan bottom
    if r2 < MIN_R2_CUP:
        return None                      # bentuknya cekung, tapi harganya tidak mengikutinya

    # Titik terendah parabola harus berada DI DALAM jendela, tidak di
    # ujungnya -- kalau di ujung, yang terjadi cuma tren searah.
    puncak_x = -b / (2 * a)
    m = len(potong)
    if not (m * 0.2 <= puncak_x <= m * 0.8):
        return None

    bibir_kiri_h = float(tinggi[awal])
    bibir_kanan_h = float(tinggi[ujung_cangkir])
    # Indeks dasar cangkir disimpan -- ia jangkar penanda setup-nya.
    i_dasar = min(range(awal, ujung_cangkir + 1), key=lambda i: rendah[i])
    dasar_h = float(rendah[i_dasar])
    bibir = min(bibir_kiri_h, bibir_kanan_h)
    if bibir <= 0 or dasar_h <= 0:
        return None

    dalam = (bibir - dasar_h) / bibir
    if not (MIN_DALAM_CUP <= dalam <= MAKS_DALAM_CUP):
        return None
    # Kedua bibir kira-kira sejajar; cangkir yang miring itu bukan cangkir.
    if abs(bibir_kiri_h - bibir_kanan_h) / bibir > MAKS_MIRING_BIBIR:
        return None

    if dengan_gagang:
        dasar_gagang = min(float(x) for x in rendah[ujung_cangkir:akhir + 1])
        turun_gagang = (bibir_kanan_h - dasar_gagang) / bibir_kanan_h
        # Gagang WAJIB dangkal. Koreksi sedalam cangkirnya berarti itu
        # bukan gagang, melainkan cangkir kedua yang sedang terbentuk.
        if turun_gagang > dalam * MAKS_DALAM_GAGANG:
            return None
        if turun_gagang <= 0:
            return None

    level = max(bibir_kiri_h, bibir_kanan_h)
    kini = float(tutup[akhir])
    nama = "Cup with Handle" if dengan_gagang else "Rounding Bottom"
    return Pola(
        kode=(kode or "").upper(), nama=nama, keluarga="pembalikan",
        arah="naik", fase="TEMBUS" if kini > level else "TERBENTUK",
        # DIJANGKARKAN KE DASAR CANGKIR, bukan ke tepi jendela.
        #
        # Versi pertama memakai tanggal[awal], dan untuk Rounding Bottom
        # (yang ujungnya = bar terakhir) awal = akhir - JENDELA_CUP --
        # artinya penandanya berganti SETIAP HARI. Satu cangkir yang
        # bertahan dua bulan akan terhitung empat puluh kejadian, dan
        # pengukurannya akan melaporkan keyakinan yang sama sekali tidak
        # pantas. Dasar cangkir tidak bergerak selama polanya sama.
        setup_id=_id(kode, "cup" if dengan_gagang else "round",
                     str(tanggal[i_dasar])),
        tanggal_mulai=str(tanggal[awal]),
        tanggal_kunci=str(tanggal[ujung_cangkir]),
        level_kunci=round(level, 2), harga_kini=kini,
        umur_bar=panjang_gagang,
        potensi_pct=round((level - dasar_h) / level * 100, 2),
        titik=[_t(tanggal[awal], bibir_kiri_h, "BIBIR KIRI"),
               _t(tanggal[i_dasar], dasar_h, "DASAR"),
               _t(tanggal[ujung_cangkir], bibir_kanan_h, "BIBIR KANAN")]
              + ([_t(tanggal[akhir], tutup[akhir], "GAGANG")]
                 if dengan_gagang else []),
        garis=[_g("Bibir", _t(tanggal[awal], level),
                  _t(tanggal[akhir], level))],
    )


# ---------------------------------------------------------------------------
# PEMBUNGKUS: pola lama dari core.pola_chart -> bentuk seragam
# ---------------------------------------------------------------------------


def _dari_ihs(p, kode: str, tgl_akhir: str) -> Pola | None:
    if p is None:
        return None
    return Pola(
        kode=kode.upper(), nama="Inverse Head & Shoulders",
        keluarga="pembalikan", arah="naik",
        fase="TEMBUS" if p.tembus else "TERBENTUK",
        setup_id=p.setup_id, tanggal_mulai=p.tanggal_bahu_kiri,
        tanggal_kunci=p.tanggal_bahu_kanan, level_kunci=p.neckline,
        harga_kini=p.harga_kini, umur_bar=p.umur_bar,
        potensi_pct=p.potensi_pct,
        titik=[_t(p.tanggal_bahu_kiri, p.harga_bahu_kiri, "BAHU KIRI"),
               _t(p.tanggal_kepala, p.harga_kepala, "KEPALA"),
               _t(p.tanggal_bahu_kanan, p.harga_bahu_kanan, "BAHU KANAN")],
        # Necklinenya MIRING: digambar dari dua jangkar aslinya lalu
        # diperpanjang ke bar terakhir memakai nilai yang sudah dihitung
        # pencarinya -- bukan diekstrapolasi ulang di sini, supaya garis
        # yang dilihat pengguna sama persis dengan garis yang dipakai
        # menilai tembus.
        garis=[_g("Neckline",
                  _t(p.tanggal_neck1, p.harga_neck1),
                  _t(p.tanggal_neck2, p.harga_neck2),
                  _t(tgl_akhir, p.neckline))])


def _dari_wedge(p, kode: str, tgl_akhir: str) -> Pola | None:
    if p is None:
        return None
    return Pola(
        kode=kode.upper(), nama="Falling Wedge", keluarga="penerusan",
        arah="naik", fase="TEMBUS" if p.tembus else "TERBENTUK",
        setup_id=p.setup_id, tanggal_mulai=p.tanggal_mulai,
        tanggal_kunci=p.tanggal_pivot_akhir, level_kunci=p.garis_atas,
        harga_kini=p.harga_kini,
        umur_bar=0, potensi_pct=None,
        garis=[_g("Resistance", _t(p.tanggal_mulai, p.garis_atas_awal),
                  _t(tgl_akhir, p.garis_atas)),
               _g("Support", _t(p.tanggal_mulai, p.garis_bawah_awal),
                  _t(tgl_akhir, p.garis_bawah))])


def _dari_flag(p, kode: str, tgl_akhir: str) -> Pola | None:
    if p is None:
        return None
    return Pola(
        kode=kode.upper(), nama="Bull Flag", keluarga="penerusan",
        arah="naik", fase="TEMBUS" if p.tembus else "TERBENTUK",
        setup_id=p.setup_id, tanggal_mulai=p.tanggal_tiang_mulai,
        tanggal_kunci=p.tanggal_tiang_puncak,
        # Level kuncinya PUNCAK BENDERA, bukan puncak tiang -- itu yang
        # dipakai cari_bull_flag untuk menentukan tembus, dan memakai
        # angka lain di layar akan membuat kata "tembus" tidak cocok
        # dengan garis yang ditunjukkan.
        level_kunci=p.puncak_bendera,
        harga_kini=p.harga_kini, umur_bar=p.bendera_bar,
        # Target klasiknya = tinggi tiang diproyeksikan dari breakout.
        potensi_pct=p.tiang_pct,
        titik=[_t(p.tanggal_tiang_mulai, p.harga_tiang_mulai, "KAKI TIANG"),
               _t(p.tanggal_tiang_puncak, p.harga_tiang_puncak, "PUNCAK TIANG")],
        garis=[_g("Tiang", _t(p.tanggal_tiang_mulai, p.harga_tiang_mulai),
                  _t(p.tanggal_tiang_puncak, p.harga_tiang_puncak)),
               _g("Atap bendera", _t(p.tanggal_tiang_puncak, p.puncak_bendera),
                  _t(tgl_akhir, p.puncak_bendera))])


# ---------------------------------------------------------------------------
# SATU PINTU
# ---------------------------------------------------------------------------
# Tiap entri: (nama arah-turun hasil cerminan, pencari, pembungkus).
# Pencari arah-naik dijalankan DUA KALI: sekali apa adanya, sekali di
# atas harga yang dicerminkan. Yang kedua menghasilkan pola arah-turun.

_CERMIN_NAMA = {
    "Inverse Head & Shoulders": "Head & Shoulders",
    "Falling Wedge": "Rising Wedge",
    "Bull Flag": "Bear Flag",
    "Double Bottom": "Double Top",
    "Triple Bottom": "Triple Top",
    "Rounding Bottom": "Rounding Top",
    "Cup with Handle": None,   # tidak punya cermin yang diakui buku
}


def _pencari_naik():
    """Pencari yang menghasilkan Pola arah "naik" dari harga apa adanya."""
    return [
        lambda k, t, h, l, c: _dari_ihs(cari_ihs(k, t, h, l, c), k, str(t[-1])),
        lambda k, t, h, l, c: _dari_wedge(cari_falling_wedge(k, t, h, l, c),
                                          k, str(t[-1])),
        lambda k, t, h, l, c: _dari_flag(cari_bull_flag(k, t, h, l, c),
                                         k, str(t[-1])),
        lambda k, t, h, l, c: _cari_dasar_ganda(k, t, h, l, c, 2),
        lambda k, t, h, l, c: _cari_dasar_ganda(k, t, h, l, c, 3),
        lambda k, t, h, l, c: _cari_cangkir(k, t, h, l, c, False),
        lambda k, t, h, l, c: _cari_cangkir(k, t, h, l, c, True),
    ]


# Label ikut dicerminkan: "DASAR 1" pada pola cermin sebenarnya PUNCAK
# di harga asli, dan membiarkannya tertulis "DASAR" akan membuat gambar
# bertentangan dengan apa yang dilihat mata pengguna di chart.
_LABEL_CERMIN = {
    "BAHU KIRI": "BAHU KIRI", "KEPALA": "KEPALA", "BAHU KANAN": "BAHU KANAN",
    "DASAR 1": "PUNCAK 1", "DASAR 2": "PUNCAK 2", "DASAR 3": "PUNCAK 3",
    "DASAR": "PUNCAK", "BIBIR KIRI": "BIBIR KIRI", "BIBIR KANAN": "BIBIR KANAN",
    "KAKI TIANG": "KAKI TIANG", "PUNCAK TIANG": "DASAR TIANG",
    "Atap bendera": "Lantai bendera", "Resistance": "Support",
    "Support": "Resistance", "Batas atas": "Batas bawah",
    "Batas bawah": "Batas atas",
}


def _balik(p: Pola, K: float) -> Pola | None:
    """Pola yang ditemukan di harga cerminan -> pola arah-turun asli."""
    nama = _CERMIN_NAMA.get(p.nama)
    if not nama:
        return None
    return Pola(
        kode=p.kode, nama=nama, keluarga=p.keluarga, arah="turun",
        fase=p.fase,
        # Slug penanda ikut ditandai 'c' supaya pola cermin tidak pernah
        # bertabrakan penanda dengan pasangan aslinya.
        setup_id=p.setup_id.replace(":", ":c", 1),
        tanggal_mulai=p.tanggal_mulai, tanggal_kunci=p.tanggal_kunci,
        level_kunci=round(_balik_harga(p.level_kunci, K), 2),
        harga_kini=round(_balik_harga(p.harga_kini, K), 2),
        umur_bar=p.umur_bar,
        # potensi_pct ikut apa adanya: ia rasio, dan rasio mencerminkan
        # dirinya sendiri (itu alasan memakai kebalikan, lihat _cermin).
        potensi_pct=p.potensi_pct,
        # KOORDINAT GAMBAR WAJIB IKUT DIKONVERSI. Kalau terlewat, pola
        # bearish akan tergambar di harga cermin -- angka yang tidak ada
        # hubungannya dengan sumbu harga di layar, sehingga garisnya
        # melayang jauh di luar chart atau, lebih buruk, kebetulan masuk
        # dan terlihat masuk akal.
        titik=[{"t": q["t"], "p": round(_balik_harga(q["p"], K), 2),
                "label": _LABEL_CERMIN.get(q["label"], q["label"])}
               for q in p.titik],
        garis=[{"nama": _LABEL_CERMIN.get(g["nama"], g["nama"]),
                "titik": [{"t": q["t"], "p": round(_balik_harga(q["p"], K), 2)}
                          for q in g["titik"]]}
               for g in p.garis])


def deteksi(kode: str, tanggal: list, tinggi: list, rendah: list,
            tutup: list) -> list[Pola]:
    """SEMUA pola yang sedang berlaku pada bar terakhir.

    Mengembalikan daftar, bukan satu pola, dan itu disengaja: emiten
    memang bisa berada di dua pola sekaligus (rectangle yang juga bagian
    dari cup, misalnya). Memaksa satu jawaban berarti memilih diam-diam,
    dan pilihan diam-diam itu yang akan disalahkan pengguna ketika pola
    yang ia lihat sendiri di chart tidak muncul.
    """
    keluar: list[Pola] = []
    for f in _pencari_naik():
        try:
            p = f(kode, tanggal, tinggi, rendah, tutup)
        except Exception:
            p = None
        if p is not None:
            keluar.append(p)

    cermin = _cermin(tinggi, rendah, tutup)
    if cermin is not None:
        (th, tl, tc), K = cermin
        for f in _pencari_naik():
            try:
                p = f(kode, tanggal, th, tl, tc)
            except Exception:
                p = None
            if p is not None:
                b = _balik(p, K)
                if b is not None:
                    keluar.append(b)

    # Segitiga & rectangle sudah mencakup kedua arah dari satu bentuk,
    # jadi TIDAK dijalankan di harga cerminan -- kalau dijalankan, satu
    # segitiga menaik akan ikut terbaca sebagai segitiga menurun cermin.
    for f in (cari_segitiga, cari_rectangle):
        try:
            p = f(kode, tanggal, tinggi, rendah, tutup)
        except Exception:
            p = None
        if p is not None:
            keluar.append(p)

    # TEMBUS lebih dulu: pola yang sudah terkonfirmasi lebih berarti
    # daripada bentuk yang masih menunggu.
    return sorted(keluar, key=lambda p: (p.fase != "TEMBUS", p.nama))
