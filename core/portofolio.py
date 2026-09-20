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
        conn.execute("""
            CREATE TABLE IF NOT EXISTS porto_pantau (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                kode TEXT NOT NULL,
                harga REAL NOT NULL,
                arah TEXT NOT NULL CHECK(arah IN ('atas', 'bawah')),
                dibuat_at TEXT NOT NULL DEFAULT (datetime('now')),
                tercapai_at TEXT
            )
        """)
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_pantau_unik "
                     "ON porto_pantau(user_id, kode, arah)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS porto_modal (
                user_id INTEGER PRIMARY KEY,
                rupiah REAL NOT NULL,
                diubah_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
    _tabel_siap = True


def set_modal(user_id: int, rupiah: float) -> float:
    """Simpan modal yang siap dipakai anggota ini."""
    if not (rupiah and rupiah > 0):
        raise ValueError("Modal harus lebih dari 0.")
    ensure_porto_tables()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO porto_modal (user_id, rupiah) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET rupiah = excluded.rupiah, "
            "diubah_at = datetime('now')",
            (int(user_id), float(rupiah)))
    return float(rupiah)


def get_modal(user_id: int) -> float:
    ensure_porto_tables()
    with get_db() as conn:
        r = conn.execute("SELECT rupiah FROM porto_modal WHERE user_id = ?",
                         (int(user_id),)).fetchone()
    return float(r["rupiah"]) if r else 0.0


def ringkas_modal(user_id: int) -> dict:
    """Modal total, yang sudah terpakai, dan sisanya.

    "Terpakai" dihitung dari HARGA BELI, bukan harga sekarang: yang
    ditanyakan "sisa uang saya berapa", dan untung-rugi mengambang tidak
    menambah atau mengurangi uang yang bisa dibelanjakan.
    """
    modal = get_modal(user_id)
    posisi = posisi_user(user_id)
    terpakai = sum(p["modal"] for p in posisi)
    return {"modal": modal, "terpakai": terpakai,
            "sisa": max(0.0, modal - terpakai),
            "n_posisi": len(posisi),
            "kode": [p["kode"] for p in posisi]}


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


# ===========================================================================
# PANTAUAN HARGA -- untuk saham yang BELUM dipegang
# ===========================================================================
# Peringatan posisi cuma melayani saham yang sudah dibeli. Padahal keputusan
# yang paling sering diambil orang justru soal yang BELUM dibeli: "kalau
# ELSA sampai 695, saya masuk". Tanpa ini, satu-satunya cara menunggu level
# adalah membuka aplikasi berkali-kali.
#
# Nyambung langsung dengan `racik`: bot menyarankan entry di 695, orangnya
# menjawab `pantau ELSA 695`, dan ia dikabari saat harganya sampai.

def pantau_tambah(user_id: int, kode: str, harga: float,
                  arah: str = "") -> dict:
    """Pasang satu pantauan harga.

    `arah` boleh kosong -- akan ditentukan dari posisi target terhadap harga
    sekarang oleh pemanggil (lihat web/app.py). Menebaknya di sini tidak
    mungkin: modul ini sengaja tidak tahu harga pasar.
    """
    kode = (kode or "").upper().strip()
    arah = (arah or "").lower().strip()
    if not kode:
        raise ValueError("Kode emiten kosong.")
    if not (harga and harga > 0):
        raise ValueError("Harga pantauan harus lebih dari 0.")
    if arah not in ("atas", "bawah"):
        raise ValueError("Arah harus 'atas' atau 'bawah'.")
    ensure_porto_tables()
    with get_db() as conn:
        # Satu emiten + satu arah = satu pantauan. Memasang ulang MENIMPA,
        # bukan menumpuk: orang yang mengoreksi angkanya bermaksud
        # mengganti, bukan menambah pantauan kedua.
        conn.execute(
            "INSERT INTO porto_pantau (user_id, kode, harga, arah) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(user_id, kode, arah) DO UPDATE SET "
            "harga = excluded.harga, dibuat_at = datetime('now'), "
            "tercapai_at = NULL",
            (int(user_id), kode, float(harga), arah))
    return {"kode": kode, "harga": float(harga), "arah": arah}


def pantau_daftar(user_id: int, termasuk_tercapai: bool = False) -> list[dict]:
    ensure_porto_tables()
    q = "SELECT * FROM porto_pantau WHERE user_id = ?"
    if not termasuk_tercapai:
        q += " AND tercapai_at IS NULL"
    q += " ORDER BY kode, arah"
    with get_db() as conn:
        return [dict(r) for r in conn.execute(q, (int(user_id),)).fetchall()]


def pantau_semua_aktif() -> list[dict]:
    """Pantauan SELURUH anggota yang belum tercapai -- dipakai loop peringatan."""
    ensure_porto_tables()
    with get_db() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM porto_pantau WHERE tercapai_at IS NULL").fetchall()]


def pantau_tandai_tercapai(pantau_id: int) -> None:
    """Sekali kena, berhenti. Pantauan harga yang terus berbunyi tiap kali
    harganya bergoyang di sekitar target bukan pengingat, itu gangguan."""
    ensure_porto_tables()
    with get_db() as conn:
        conn.execute("UPDATE porto_pantau SET tercapai_at = datetime('now') "
                     "WHERE id = ?", (int(pantau_id),))


def pantau_hapus(user_id: int, kode: str) -> int:
    ensure_porto_tables()
    with get_db() as conn:
        cur = conn.execute(
            "DELETE FROM porto_pantau WHERE user_id = ? AND kode = ?",
            (int(user_id), (kode or "").upper().strip()))
        return cur.rowcount or 0
