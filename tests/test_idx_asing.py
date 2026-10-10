"""Aliran dana asing per saham dari data resmi IDX.

Panel "asing" di aplikasi ini selama ini menebak dari volume, dan kodenya
sendiri mengakuinya: "BUKAN data transaksi bandar/asing sungguhan". Modul
ini yang membuat label itu jadi benar.

NILAI SEBENARNYA BUKAN MENAMBAH ANGKA, TAPI MEMISAHKAN. Diuji pada hasil 6
Okt 2026, lima saham yang ditandai "Siluman (quiet buy)" oleh tebakan
volume ternyata terbelah dua:

    PTBA  +Rp26,8 M  (9,98% transaksi hari itu)  <- akumulasi sungguhan
    BULL  -Rp6,9 M   (3,65%)                     <- asing justru MELEPAS

Tebakan volume tidak bisa membedakan keduanya. Itulah yang dibeli fitur ini,
dan itu pula sebabnya ujinya berfokus pada hal-hal yang membuat angkanya
bisa salah baca: satuan, tanggal, dan nol yang bukan nol.
"""
from datetime import date, datetime, timedelta

import pytest

from core.idx_asing import WIB, hari_bursa_terakhir, net_asing, urai


def _baris(**ubah):
    dasar = {"StockCode": "BBCA", "Close": 9000.0, "Value": 1_000_000_000.0,
             "ForeignBuy": 200_000.0, "ForeignSell": 50_000.0}
    dasar.update(ubah)
    return dasar


# ---------------------------------------------------------------------------
# Satuan -- lembar vs rupiah
# ---------------------------------------------------------------------------

def test_lembar_dikali_harga_jadi_rupiah():
    """ForeignBuy/Sell dihitung dalam LEMBAR. Menyandingkannya langsung
    dengan nilai transaksi (rupiah) membandingkan dua satuan berbeda dan
    menghasilkan angka yang terlihat masuk akal tapi tidak berarti apa-apa."""
    r = net_asing(_baris())
    assert r["net_lembar"] == 150_000
    assert r["net_rp"] == 150_000 * 9000


def test_porsi_mengukur_terhadap_transaksi_saham_ITU():
    """Net Rp1 miliar di saham yang hari itu ditransaksikan Rp2 miliar jauh
    lebih berarti daripada Rp1 miliar di saham yang ditransaksikan Rp500
    miliar. Tanpa rasio ini keduanya terbaca sama besar."""
    kecil = net_asing(_baris(Value=2_000_000_000.0))
    besar = net_asing(_baris(Value=500_000_000_000.0))
    assert kecil["porsi_pct"] > besar["porsi_pct"]
    assert kecil["porsi_pct"] == round(150_000 * 9000 / 2e9 * 100, 2)


def test_nilai_transaksi_nol_tidak_membagi_dengan_nol():
    assert net_asing(_baris(Value=0))["porsi_pct"] is None


def test_net_jual_bernilai_negatif():
    """Arah harus terbaca dari tandanya, bukan dari field terpisah yang bisa
    lupa dibaca pemakainya."""
    r = net_asing(_baris(ForeignBuy=10_000.0, ForeignSell=90_000.0))
    assert r["net_lembar"] == -80_000
    assert r["net_rp"] < 0


# ---------------------------------------------------------------------------
# Nol yang bukan nol
# ---------------------------------------------------------------------------

def test_tanpa_transaksi_asing_dibuang_bukan_dicatat_nol():
    """Saham yang asing tidak menyentuhnya sama sekali dan saham yang asing
    beli-jual sama banyak adalah dua keadaan berbeda. Mencatat keduanya
    sebagai "net 0" menghapus perbedaan itu, dan 241 dari 963 emiten ada di
    keadaan pertama -- cukup banyak untuk mencemari peringkat."""
    assert net_asing(_baris(ForeignBuy=0, ForeignSell=0)) is None
    assert net_asing(_baris(ForeignBuy=None, ForeignSell=None)) is None


def test_beli_sama_dengan_jual_TETAP_dicatat():
    """Ini keadaan yang berbeda: asing aktif, tapi berimbang."""
    r = net_asing(_baris(ForeignBuy=50_000.0, ForeignSell=50_000.0))
    assert r is not None and r["net_lembar"] == 0


def test_baris_tanpa_kode_dibuang():
    assert net_asing(_baris(StockCode="")) is None
    assert net_asing(_baris(StockCode=None)) is None


# ---------------------------------------------------------------------------
# Penguraian
# ---------------------------------------------------------------------------

def test_urai_memetakan_per_kode_dan_tahan_baris_cacat():
    """963 baris diproses sekaligus; satu baris aneh tidak boleh
    mengosongkan seluruh peta."""
    hasil = urai({"data": [
        _baris(StockCode="BBCA"),
        "bukan dict",
        None,
        _baris(StockCode="TLKM", ForeignBuy=0, ForeignSell=0),   # dibuang
        _baris(StockCode="ptba"),                                 # huruf kecil
    ]})
    assert set(hasil) == {"BBCA", "PTBA"}


@pytest.mark.parametrize("rusak", [None, {}, {"data": None}, {"data": []}])
def test_payload_rusak_memulangkan_peta_kosong(rusak):
    assert urai(rusak) == {}


# ---------------------------------------------------------------------------
# Tanggal -- "kemarin" yang disajikan sebagai "hari ini"
# ---------------------------------------------------------------------------

def test_sebelum_bursa_tutup_meminta_hari_SEBELUMNYA():
    """Ringkasan harian baru terbit sesudah penutupan. Meminta data hari ini
    pada pukul 10 pagi memulangkan daftar kosong, dan kosong itu tidak bisa
    dibedakan dari "hari ini memang sepi"."""
    pagi = datetime(2026, 10, 7, 10, 0, tzinfo=WIB)      # Rabu pagi
    assert hari_bursa_terakhir(pagi) == date(2026, 10, 6)


def test_sesudah_bursa_tutup_memakai_hari_itu_sendiri():
    sore = datetime(2026, 10, 7, 17, 0, tzinfo=WIB)
    assert hari_bursa_terakhir(sore) == date(2026, 10, 7)


@pytest.mark.parametrize("jam", [10, 17])
def test_akhir_pekan_mundur_ke_jumat(jam):
    minggu = datetime(2026, 10, 11, jam, 0, tzinfo=WIB)
    assert minggu.weekday() == 6, "prasyarat ujinya sendiri"
    assert hari_bursa_terakhir(minggu) == date(2026, 10, 9)


def test_senin_pagi_mundur_ke_jumat_bukan_ke_minggu():
    """Jebakan yang mudah terlewat: Senin pagi mundur sehari jadi Minggu,
    dan Minggu tidak punya data. Harus terus mundur sampai hari bursa."""
    senin = datetime(2026, 10, 12, 8, 0, tzinfo=WIB)
    assert senin.weekday() == 0, "prasyarat ujinya sendiri"
    assert hari_bursa_terakhir(senin) == date(2026, 10, 9)


# ---------------------------------------------------------------------------
# Penyajian -- dua lapis bukti yang berbeda kekuatannya
# ---------------------------------------------------------------------------

def test_syarat_berubah_saat_data_asing_ADA():
    """Kalimat "bukan aliran dana asing -- siapa yang membeli tidak ada di
    data ini" BENAR selama panel cuma menebak dari volume. Begitu angka
    asing resmi ikut ditempel, kalimat itu berubah jadi keterangan KELIRU.

    Keterangan keliru yang diwarisi dari versi sebelumnya adalah jenis
    kesalahan yang paling lama bertahan, justru karena ia dulu benar."""
    from web.app import _syarat_smartmoney

    dengan = " ".join(_syarat_smartmoney({"asing_tanggal": "2026-10-06"}))
    assert "catatan resmi IDX per 2026-10-06" in dengan
    assert "siapa yang membeli tidak ada" not in dengan.lower()


def test_syarat_kembali_jujur_saat_data_asing_TIDAK_ADA():
    """IDX tak terjangkau = kembali ke tebakan, dan harus mengaku begitu."""
    from web.app import _syarat_smartmoney

    tanpa = " ".join(_syarat_smartmoney({}))
    assert "tidak ada di data ini" in tanpa
    assert "catatan resmi IDX" not in tanpa


def test_syarat_selalu_membedakan_tebakan_dari_catatan():
    """Dua lapis bukti dalam satu pesan, dan bedanya harus terbaca: rasio
    volume itu tebakan, net asing itu catatan bursa."""
    from web.app import _syarat_smartmoney

    teks = " ".join(_syarat_smartmoney({"asing_tanggal": "2026-10-06"}))
    assert "TEBAKAN" in teks and "BUKAN tebakan" in teks
    assert "asing bukan bandar" in teks


def test_tempel_asing_menyandingkan_tanpa_mengubah_yang_lain():
    from web.app import _tempel_asing

    items = [{"kode": "PTBA", "vol_ratio": 1.28}, {"kode": "ENTAH", "vol_ratio": 2.0}]
    _tempel_asing(items, {"PTBA": {"net_rp": 26_834_840_000.0, "porsi_pct": 9.98}})
    assert items[0]["asing_rp"] == 26_834_840_000
    assert items[0]["asing_porsi"] == 9.98
    assert "asing_rp" not in items[1], "saham tanpa data asing jangan dikarang nol"


def test_tempel_asing_tahan_baris_cacat():
    from web.app import _tempel_asing

    assert _tempel_asing([None, "x", {}, {"kode": None}], {}) is not None


@pytest.mark.parametrize("nilai,harap", [
    (26_834_840_000, "Rp26,8 M"),
    (-6_900_000_000, "-Rp6,9 M"),
    (1_500_000_000_000, "Rp1,5 T"),
    (250_000_000, "Rp250,0 jt"),
    (0, "Rp0"),
    (None, "Rp0"),
])
def test_rupiah_besar_ditulis_ringkas(nilai, harap):
    """Rp26.834.840.000 itu benar tapi tidak terbaca: di WhatsApp ia jadi
    deretan titik yang harus dihitung mundur untuk tahu miliar atau juta."""
    from web.app import _rp_ringkas

    assert _rp_ringkas(nilai) == harap


# ---------------------------------------------------------------------------
# Ukuran tiket -- keterangan, bukan sinyal
# ---------------------------------------------------------------------------

def test_transaksi_terlalu_sedikit_TIDAK_dinilai():
    """KEJADIAN NYATA 9 Okt 2026: CASS menunjukkan Rp49,6 juta per
    transaksi -- dari TUJUH transaksi. Itu satu perdagangan blok, bukan
    minat institusional, dan tanpa penjaga ini ia duduk di puncak daftar
    "institusi masuk"."""
    from core.idx_asing import ukuran_tiket

    assert ukuran_tiket({"Value": 347_241_500.0, "Frequency": 7.0}) is None


def test_tiket_dihitung_saat_frekuensinya_cukup():
    from core.idx_asing import ukuran_tiket

    r = ukuran_tiket({"Value": 1_000_000_000.0, "Frequency": 2000.0})
    assert r["tiket_rp"] == 500_000 and r["frekuensi"] == 2000


@pytest.mark.parametrize("nilai,freq,label", [
    (200_000_000.0, 1000.0, "Ramai ritel"),     # Rp200rb/transaksi
    (2_000_000_000.0, 1000.0, "Campuran"),      # Rp2 jt
    (9_000_000_000.0, 1000.0, "Tiket besar"),   # Rp9 jt
])
def test_label_sesuai_sebaran_bursa_sungguhan(nilai, freq, label):
    """Ambangnya dari sebaran 830 emiten pada 9 Okt 2026 (persentil 50 =
    Rp1,31 jt, persentil 90 = Rp7,71 jt) -- bukan angka bulat yang
    kedengaran enak."""
    from core.idx_asing import ukuran_tiket

    assert ukuran_tiket({"Value": nilai, "Frequency": freq})["tiket_label"] == label


def test_tiket_ikut_terbawa_di_peta_asing_tanpa_permintaan_tambahan():
    from core.idx_asing import urai

    peta = urai({"data": [{"StockCode": "BBCA", "Close": 9000.0,
                           "Value": 5_000_000_000.0, "Frequency": 1000.0,
                           "ForeignBuy": 200_000.0, "ForeignSell": 50_000.0}]})
    assert peta["BBCA"]["tiket_rp"] == 5_000_000
    assert peta["BBCA"]["net_rp"] == 150_000 * 9000     # kolom lama tetap utuh


def test_tiket_tak_terhitung_tidak_merusak_baris_asingnya():
    """Frekuensi rendah membuat tiketnya tak bisa dinilai -- itu tidak
    boleh ikut membuang data asing yang justru sah."""
    from core.idx_asing import urai

    peta = urai({"data": [{"StockCode": "CASS", "Close": 1000.0,
                           "Value": 347_241_500.0, "Frequency": 7.0,
                           "ForeignBuy": 100_000.0, "ForeignSell": 0.0}]})
    assert "CASS" in peta
    assert "tiket_rp" not in peta["CASS"]
