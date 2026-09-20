"""Posisi saham milik anggota -- supaya bot tahu "kamu lagi bagaimana".

KENAPA ADA. Seluruh perintah bot sebelumnya menjawab pertanyaan yang sama
dari sudut berbeda: "pasar lagi bagaimana". `sinyal`, `screener`, `harmonic`,
`ihsg`, `kepemilikan` -- semuanya tentang pasar. Tidak ada satu pun yang
menjawab "SAYA lagi bagaimana", padahal itu yang benar-benar ditanyakan orang
yang sedang memegang barang.

`nyangkut KODE HARGA` paling dekat, tapi harga belinya harus diketik ulang
tiap kali, dan ia cuma melayani satu posisi yang sedang rugi.

BENTUKNYA TRANSAKSI, BUKAN "POSISI SEKARANG
===========================================
Yang disimpan tiap pembelian dan penjualan, bukan satu baris "posisi saat
ini" yang ditimpa terus. Alasannya:

  - Harga rata-rata jadi HASIL HITUNGAN, bukan angka yang bisa salah
    diperbarui. Beli tiga kali lalu jual sebagian itu operasi yang gampang
    keliru kalau rata-ratanya disimpan langsung.
  - Salah catat bisa ditelusuri dan dibatalkan. Kalau yang tersimpan cuma
    keadaan akhir, satu salah ketik menghapus kebenarannya selamanya.

PRIVASI. Isinya nominal uang orang. Yang memanggil WAJIB memastikan
permintaannya datang dari percakapan pribadi, bukan grup -- lihat
web/app.py. Modul ini sendiri tidak tahu apa-apa soal itu, jadi ia tidak
bisa menjaganya.
"""
from core.database import get_db

# Satu lot = 100 lembar di BEI. Dipakai untuk menghitung modal.
LEMBAR_PER_LOT = 100


_tabel_siap = False


def ensure_porto_tables() -> None:
    """Sekali per proses, bukan tiap panggilan.

    CREATE TABLE IF NOT EXISTS memang murah, tapi ia tetap menyentuh basis
    data yang SAMA dipakai web -- dan fungsi ini dipanggil dari hampir
    setiap operasi di modul ini. Membayarnya sekali saja menghilangkan
    seluruh percakapan yang tidak perlu itu.
    """
    global _tabel_siap
    if _tabel_siap:
        return
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS porto_transaksi (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                kode TEXT NOT NULL,
                arah TEXT NOT NULL CHECK(arah IN ('BELI', 'JUAL')),
                lot REAL NOT NULL,
                harga REAL NOT NULL,
                dicatat_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_porto_user "
                     "ON porto_transaksi(user_id, kode)")
    _tabel_siap = True


def catat(user_id: int, kode: str, arah: str, lot: float, harga: float) -> dict:
    """Catat satu pembelian/penjualan. Return posisi terbaru untuk kode itu."""
    kode = (kode or "").upper().strip()
    arah = (arah or "").upper().strip()
    if arah not in ("BELI", "JUAL"):
        raise ValueError("Arah harus BELI atau JUAL.")
    if not kode:
        raise ValueError("Kode emiten kosong.")
    if not (lot and lot > 0):
        raise ValueError("Jumlah lot harus lebih dari 0.")
    if not (harga and harga > 0):
        raise ValueError("Harga harus lebih dari 0.")

    ensure_porto_tables()
    if arah == "JUAL":
        # Menjual lebih banyak daripada yang dipegang itu hampir selalu salah
        # ketik. Ditolak di sini, bukan dibiarkan jadi posisi negatif yang
        # baru ketahuan aneh berhari-hari kemudian.
        punya = (_agregat(user_id).get(kode) or {}).get("lot", 0)
        if lot > punya + 1e-9:
            raise ValueError(
                f"Kamu memegang {_lot(punya)} lot {kode}, tidak bisa menjual {_lot(lot)}.")

    with get_db() as conn:
        conn.execute(
            "INSERT INTO porto_transaksi (user_id, kode, arah, lot, harga) "
            "VALUES (?, ?, ?, ?, ?)",
            (int(user_id), kode, arah, float(lot), float(harga)))
    return (_agregat(user_id).get(kode)
            or {"kode": kode, "lot": 0.0, "harga_avg": 0.0, "modal": 0.0})


def _lot(x: float) -> str:
    return f"{x:g}"


def _agregat(user_id: int) -> dict:
    """{kode: {lot, harga_avg, modal}} dari seluruh transaksi.

    Rata-rata dihitung dengan METODE RATA-RATA BERGERAK: penjualan mengurangi
    lot TANPA mengubah harga rata-rata. Itu yang dipakai hampir semua sekuritas
    di Indonesia, jadi angkanya cocok dengan yang dilihat orang di aplikasi
    brokernya sendiri -- dan angka yang berbeda dari brokernya akan dianggap
    salah, seberapa pun benarnya secara akuntansi.
    """
    ensure_porto_tables()
    with get_db() as conn:
        rows = conn.execute(
            "SELECT kode, arah, lot, harga FROM porto_transaksi "
            "WHERE user_id = ? ORDER BY id", (int(user_id),)).fetchall()

    posisi: dict = {}
    for r in rows:
        p = posisi.setdefault(r["kode"], {"kode": r["kode"], "lot": 0.0,
                                          "harga_avg": 0.0})
        if r["arah"] == "BELI":
            total = p["lot"] * p["harga_avg"] + r["lot"] * r["harga"]
            p["lot"] += r["lot"]
            p["harga_avg"] = total / p["lot"] if p["lot"] else 0.0
        else:
            p["lot"] = max(0.0, p["lot"] - r["lot"])
            if p["lot"] <= 1e-9:
                p["harga_avg"] = 0.0
    for p in posisi.values():
        p["modal"] = p["lot"] * p["harga_avg"] * LEMBAR_PER_LOT
    return posisi


def posisi_user(user_id: int) -> list[dict]:
    """Posisi yang MASIH DIPEGANG, terbesar modalnya lebih dulu."""
    semua = [p for p in _agregat(user_id).values() if p["lot"] > 1e-9]
    return sorted(semua, key=lambda p: p["modal"], reverse=True)


def posisi_kode(user_id: int, kode: str) -> dict | None:
    p = _agregat(user_id).get((kode or "").upper().strip())
    return p if p and p["lot"] > 1e-9 else None


def hapus_kode(user_id: int, kode: str) -> int:
    """Hapus SELURUH catatan satu emiten. Return berapa baris terhapus.

    Dipakai untuk membatalkan salah catat -- berbeda dari mencatat penjualan,
    yang merupakan kejadian nyata dan memang harus tersimpan.
    """
    ensure_porto_tables()
    kode = (kode or "").upper().strip()
    with get_db() as conn:
        cur = conn.execute(
            "DELETE FROM porto_transaksi WHERE user_id = ? AND kode = ?",
            (int(user_id), kode))
        return cur.rowcount or 0


def riwayat_kode(user_id: int, kode: str, batas: int = 20) -> list[dict]:
    ensure_porto_tables()
    with get_db() as conn:
        rows = conn.execute(
            "SELECT arah, lot, harga, dicatat_at FROM porto_transaksi "
            "WHERE user_id = ? AND kode = ? ORDER BY id DESC LIMIT ?",
            (int(user_id), (kode or "").upper().strip(), int(batas))).fetchall()
    return [dict(r) for r in rows]
