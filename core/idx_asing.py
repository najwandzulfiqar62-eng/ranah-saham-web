"""Aliran dana asing per saham, dari data RESMI IDX.

KENAPA ADA (7 Okt 2026). Aplikasi ini punya menu bernama "asing", dan
kodenya sendiri terpaksa mengaku di dalamnya:

    "proxy tren Chaikin A/D Line ... BUKAN data transaksi bandar/asing
     sungguhan"

Panel itu menebak dari volume. Tebakannya tidak buruk -- PTBA ditandainya
"akumulasi diam-diam" pada 6 Okt, dan ternyata asing memang net beli Rp26,8
miliar di saham itu. Tapi menebak dan mengetahui adalah dua hal berbeda,
dan selama ini yang ada baru tebakan.

SUMBERNYA. IDX menerbitkan ForeignBuy & ForeignSell PER SAHAM di endpoint
ringkasan perdagangan hariannya. Satu permintaan memulangkan seluruh pasar
(963 emiten pada 6 Okt 2026), dan 722 di antaranya punya angka asing.

    block.idx.id/primary/TradingSummary/GetStockSummary?date=YYYYMMDD

HOST-NYA YANG MENENTUKAN. www.idx.co.id ada di belakang Cloudflare dan
membalas 403 dari mana pun kecuali lewat peramban sungguhan (lihat
core/idx_cf.py, yang dibangun justru untuk menembusnya). block.idx.id
melayani endpoint yang SAMA tanpa Cloudflare sama sekali -- diuji dengan
curl polos dari laptop biasa: 200, 644 KB, 963 baris. Jadi fitur ini tidak
memerlukan Chrome, nodriver, atau Xvfb.

Cadangannya tetap www.idx.co.id lewat idx_cf: block.idx.id itu cermin, dan
cermin bisa ditutup tanpa pemberitahuan.

YANG TIDAK DIJAWAB DATA INI, dan harus dikatakan di layar: asing bukan
bandar. Saham yang digerakkan broker domestik tidak akan terlihat di sini
sama sekali. Broker summary per saham -- yang benar-benar menjawab "siapa"
-- adalah produk berbayar IDX, dan tidak ada versi gratisnya (diperiksa 7
Okt 2026: parameter `code` pada GetBrokerSummary diabaikan diam-diam,
balasannya sama persis byte per byte dengan atau tanpanya).
"""
from datetime import date, datetime, timedelta, timezone

WIB = timezone(timedelta(hours=7))

# Cermin tanpa Cloudflare. Didahulukan justru karena ia TIDAK memerlukan
# peramban -- jalur idx_cf mahal (menjalankan Chrome) dan rapuh.
HOST_UTAMA = "https://block.idx.id"
HOST_CADANGAN = "https://www.idx.co.id"

_JALUR = "/primary/TradingSummary/GetStockSummary"

# Mundur maksimal sekian hari kalender saat mencari hari bursa terakhir.
# Cukup untuk akhir pekan panjang + libur nasional beruntun (Lebaran bisa
# menutup bursa hampir seminggu penuh).
MAKS_MUNDUR_HARI = 10


def _tanggal_idx(d: date) -> str:
    return d.strftime("%Y%m%d")


def hari_bursa_terakhir(sekarang: datetime | None = None) -> date:
    """Tanggal yang paling mungkin punya data.

    Ringkasan harian baru terbit SESUDAH bursa tutup. Meminta data hari ini
    pada pukul 10 pagi memulangkan daftar kosong, dan kosong itu tidak bisa
    dibedakan dari "hari ini memang sepi" -- jadi sebelum penutupan yang
    diminta hari sebelumnya.

    KETERBATASAN YANG DICATAT JUJUR: libur nasional tidak dikenali di sini.
    Penanganannya ada di pemanggil -- ia mundur sehari lagi saat datanya
    kosong (lihat ambil_asing). Akibat terburuknya satu permintaan ekstra,
    bukan angka yang salah.
    """
    n = sekarang or datetime.now(WIB)
    d = n.date()
    # 16.00 WIB: bursa tutup 15.50, ringkasannya menyusul tak lama kemudian.
    if n.hour < 16:
        d -= timedelta(days=1)
    while d.weekday() >= 5:          # Sabtu/Minggu
        d -= timedelta(days=1)
    return d


def net_asing(baris: dict) -> dict | None:
    """Satu baris ringkasan IDX -> angka aliran asing yang bisa dipakai.

    SATUAN ASLINYA LEMBAR, BUKAN RUPIAH. ForeignBuy/ForeignSell dihitung
    dalam lembar saham; menyandingkannya langsung dengan nilai transaksi
    (yang rupiah) akan membandingkan dua satuan berbeda dan menghasilkan
    angka yang terlihat masuk akal tapi tidak berarti apa-apa. Rupiahnya
    diperkirakan dengan harga penutupan -- perkiraan, karena transaksinya
    terjadi di sepanjang hari pada harga yang berbeda-beda.
    """
    kode = (baris.get("StockCode") or "").strip().upper()
    if not kode:
        return None
    beli = baris.get("ForeignBuy")
    jual = baris.get("ForeignSell")
    if beli is None and jual is None:
        return None
    beli = float(beli or 0)
    jual = float(jual or 0)
    if beli == 0 and jual == 0:
        return None                   # tidak ada transaksi asing sama sekali

    tutup = float(baris.get("Close") or 0)
    net_lembar = beli - jual
    nilai_total = float(baris.get("Value") or 0)
    net_rp = net_lembar * tutup

    return {
        "kode": kode,
        "beli_lembar": beli,
        "jual_lembar": jual,
        "net_lembar": net_lembar,
        # Perkiraan, bukan angka resmi -- lihat catatan di atas.
        "net_rp": net_rp,
        "harga": tutup,
        # Seberapa besar asing dibanding SELURUH transaksi saham itu hari
        # ini. Net Rp1 miliar di saham yang hari itu ditransaksikan Rp2
        # miliar jauh lebih berarti daripada Rp1 miliar di saham yang
        # ditransaksikan Rp500 miliar -- tanpa rasio ini, keduanya terbaca
        # sama besar.
        "porsi_pct": (round(abs(net_rp) / nilai_total * 100, 2)
                      if nilai_total > 0 else None),
        "nilai_total": nilai_total,
    }


def urai(payload: dict) -> dict:
    """Balasan GetStockSummary -> peta {kode: angka asing}."""
    data = (payload or {}).get("data") or []
    keluar = {}
    for baris in data:
        if not isinstance(baris, dict):
            continue
        hasil = net_asing(baris)
        if not hasil:
            continue
        # Ukuran tiket menumpang payload yang SAMA -- tidak ada permintaan
        # tambahan ke IDX untuknya.
        tiket = ukuran_tiket(baris)
        if tiket:
            hasil.update(tiket)
        keluar[hasil["kode"]] = hasil
    return keluar


def _url(host: str, tgl: date) -> str:
    return f"{host}{_JALUR}?date={_tanggal_idx(tgl)}&start=0&length=9999"


class AsingError(RuntimeError):
    """Tidak ada satu pun jalur yang bisa memberi data asing hari itu."""


async def _ambil_satu(tgl: date, timeout: int = 40) -> dict:
    """Satu tanggal, lewat cermin dulu baru jalur Cloudflare.

    URUTANNYA DISENGAJA. block.idx.id tidak memerlukan peramban sama sekali,
    sementara idx_cf menjalankan Chrome di balik layar -- mahal, lambat, dan
    satu lagi hal yang bisa rusak. Jalur mahal itu cadangan, bukan pilihan
    pertama.
    """
    import httpx

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as c:
            r = await c.get(_url(HOST_UTAMA, tgl), headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "Accept": "application/json, text/plain, */*",
                "X-Requested-With": "XMLHttpRequest",
            })
        if r.status_code == 200:
            return urai(r.json())
        sebab = f"{HOST_UTAMA} membalas HTTP {r.status_code}"
    except Exception as e:
        sebab = f"{HOST_UTAMA} gagal: {type(e).__name__}: {e}"

    # Cadangan: host resmi lewat pembobol Cloudflare yang sudah ada.
    try:
        from core.idx_cf import idx_get_json

        status, data, jalur = await idx_get_json(_url(HOST_CADANGAN, tgl),
                                                 timeout=timeout)
        if status == 200 and data:
            return urai(data)
        raise AsingError(f"{sebab}; cadangan {HOST_CADANGAN} "
                         f"HTTP {status} lewat {jalur}")
    except AsingError:
        raise
    except Exception as e:
        raise AsingError(f"{sebab}; cadangan gagal: {type(e).__name__}: {e}")


async def ambil_asing(tgl: date | None = None,
                      maks_mundur: int = MAKS_MUNDUR_HARI) -> tuple[dict, date]:
    """Aliran asing per saham untuk hari bursa terakhir yang ADA datanya.

    Return (peta {kode: angka}, tanggal yang benar-benar dipakai).

    Mundur sehari demi sehari saat datanya kosong. Kosong di sini berarti
    bursa libur -- dan libur nasional tidak bisa dikenali dari kalender
    karena aplikasi ini tidak punya daftarnya. Mundur sampai ketemu jauh
    lebih sederhana daripada memelihara daftar libur yang pasti basi,
    ongkosnya beberapa permintaan ekstra setahun sekali.

    Tanggal yang DIPAKAI ikut dikembalikan, bukan disembunyikan: angka
    kemarin yang disajikan sebagai angka hari ini adalah jenis kesalahan
    yang tidak terlihat seperti kesalahan.
    """
    d = tgl or hari_bursa_terakhir()
    galat_pertama = None
    for _ in range(max(1, maks_mundur)):
        try:
            peta = await _ambil_satu(d)
            if peta:
                return peta, d
        except AsingError:
            # Kegagalan jaringan TIDAK boleh membuatnya mundur terus sampai
            # sepuluh hari lalu: itu menukar "sumbernya sedang mati" menjadi
            # "datanya sepuluh hari basi", diam-diam.
            raise
        except Exception as e:
            if galat_pertama is None:
                galat_pertama = e
        d -= timedelta(days=1)
        while d.weekday() >= 5:
            d -= timedelta(days=1)
    raise AsingError(f"tidak ada data asing dalam {maks_mundur} hari terakhir"
                     + (f" ({galat_pertama})" if galat_pertama else ""))


# ---------------------------------------------------------------------------
# Ukuran tiket rata-rata (perilaku ritel vs institusi)
# ---------------------------------------------------------------------------
# Value / Frequency = berapa rupiah rata-rata per transaksi. Tiket kecil
# berarti banyak orang membeli sedikit-sedikit; tiket besar berarti sedikit
# pihak membeli banyak.
#
# INI KOLOM KETERANGAN, BUKAN SINYAL. Berbeda dari panel divergence atau
# jarak stop ATR, angka ini BELUM diukur meramalkan apa pun. Ia menjawab
# "siapa yang ramai di saham ini", bukan "saham ini akan naik". Menamainya
# "deteksi" akan menjanjikan lebih dari yang dimilikinya.
#
# PENJAGA FREKUENSI yang tidak bisa ditawar. Diukur 9 Okt 2026: CASS
# menunjukkan Rp49,6 juta per transaksi -- dari TUJUH transaksi. Itu satu
# perdagangan blok, bukan minat institusional, dan tanpa penjaga ini ia
# akan duduk di puncak daftar "institusi masuk". Saham dengan transaksi
# sedikit tidak punya "rata-rata" yang berarti.
MIN_FREKUENSI = 100

# Ambang dari sebaran SUNGGUHAN seluruh bursa, 9 Okt 2026 (830 emiten):
#   persentil 25: Rp0,70 jt   persentil 50: Rp1,31 jt
#   persentil 75: Rp3,14 jt   persentil 90: Rp7,71 jt
TIKET_RITEL = 1_000_000
TIKET_BESAR = 5_000_000


def ukuran_tiket(baris: dict) -> dict | None:
    """Rata-rata rupiah per transaksi, atau None kalau tidak bisa dinilai."""
    nilai = float(baris.get("Value") or 0)
    freq = float(baris.get("Frequency") or 0)
    if freq < MIN_FREKUENSI or nilai <= 0:
        return None
    tiket = nilai / freq
    if tiket < TIKET_RITEL:
        label = "Ramai ritel"
    elif tiket >= TIKET_BESAR:
        label = "Tiket besar"
    else:
        label = "Campuran"
    return {"tiket_rp": round(tiket), "tiket_label": label,
            "frekuensi": int(freq)}
