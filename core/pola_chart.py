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
        neckline=round(garis, 2), harga_kini=kini, umur_bar=umur,
        tembus=kini > garis,
        potensi_pct=round(tinggi_pola / garis * 100, 2),
    )
