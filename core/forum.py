# =========================
# FORUM KOMUNITAS (Tanya Jawab)
# =========================
# Permintaan user: "fitur chat buat komunitas ... lebih ke forum sih" --
# thread tanya-jawab async (BUKAN live chat), tempat user bisa tanya dan
# admin/user lain jawab. Aplikasi ini TIDAK PUNYA sistem akun/login sama
# sekali (dihapus sesi sebelumnya sbg dead code -- lihat catatan di
# core/database.py), jadi "siapa yang posting" di sini HANYA nama bebas
# yang diketik user sendiri tiap kali (bukan identitas terverifikasi) --
# `is_admin` per baris SATU-SATUNYA hal yang server verifikasi sungguhan
# (lihat _forum_is_admin di web/app.py, bukan modul ini -- modul ini murni
# layer data, tidak tahu apa pun soal kode rahasia/HTTP).
#
# Lingkup SENGAJA disederhanakan utk kebutuhan riil skripsi ini: flat
# (SATU list thread, balasan flat per-thread, TIDAK nested reply-ke-reply;
# kategori v2 cuma 5 slug TETAP -- lihat FORUM_KATEGORI di web/app.py --
# BUKAN tabel kategori dinamis), thread default terurut created_at DESC
# (gaya Q&A, BUKAN "bump ke atas kalau ada balasan baru" ala forum diskusi
# -- bisa diubah via param `sort`/`status` di list_threads()), hard DELETE
# utk moderasi admin (bukan soft-delete -- ini konten forum user-generated,
# beda dgn prinsip "jangan hapus sinyal trading resolved" yang soal
# integritas track record finansial, lihat core/signal_history.py).
#
# SQLite di proyek ini TIDAK mengaktifkan PRAGMA foreign_keys (lihat
# core/database.py::_get_connection) -- REFERENCES di bawah SEKADAR
# dokumentasi, BUKAN constraint yang di-enforce. delete_thread() karena
# itu HARUS menghapus forum_reply-nya secara manual (cascade manual),
# tidak ada mekanisme otomatis yang melakukannya.

from core.database import get_db

_ensured = False


def _ensure_table():
    global _ensured
    if _ensured:
        return
    with get_db() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS forum_thread (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                nama       TEXT NOT NULL,
                judul      TEXT NOT NULL,
                isi        TEXT NOT NULL,
                is_admin   INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS forum_reply (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id  INTEGER NOT NULL REFERENCES forum_thread(id),
                nama       TEXT NOT NULL,
                isi        TEXT NOT NULL,
                is_admin   INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            )
        ''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_forum_reply_thread ON forum_reply(thread_id)')

        # Migrasi v2 (kategori/upvote/jawaban-terbaik/lapor) -- ADDITIVE ONLY.
        # PRAGMA table_info + ALTER TABLE ADD COLUMN kalau kolom belum ada,
        # TIDAK PERNAH DROP/rewrite baris lama -- pola sama persis dgn
        # core/signal_history.py::_ensure_table() (lihat komentar "Migration
        # 10/12 RETRAKSI" di modul itu: DELETE dgn kondisi longgar pernah
        # menghapus riwayat sungguhan, pelajarannya migrasi tabel yang sudah
        # ada datanya harus additive-only).
        cols_t = {r["name"] for r in conn.execute("PRAGMA table_info(forum_thread)").fetchall()}
        if "kategori" not in cols_t:
            conn.execute("ALTER TABLE forum_thread ADD COLUMN kategori TEXT NOT NULL DEFAULT 'umum'")
        if "report_count" not in cols_t:
            conn.execute("ALTER TABLE forum_thread ADD COLUMN report_count INTEGER NOT NULL DEFAULT 0")

        cols_r = {r["name"] for r in conn.execute("PRAGMA table_info(forum_reply)").fetchall()}
        if "upvotes" not in cols_r:
            conn.execute("ALTER TABLE forum_reply ADD COLUMN upvotes INTEGER NOT NULL DEFAULT 0")
        if "is_best_answer" not in cols_r:
            conn.execute("ALTER TABLE forum_reply ADD COLUMN is_best_answer INTEGER NOT NULL DEFAULT 0")
        if "report_count" not in cols_r:
            conn.execute("ALTER TABLE forum_reply ADD COLUMN report_count INTEGER NOT NULL DEFAULT 0")
    _ensured = True


def create_thread(nama: str, judul: str, isi: str, is_admin: bool, kategori: str = "umum") -> dict:
    """Simpan thread baru, return baris yang baru dibuat (id, nama, judul,
    isi, is_admin, kategori, created_at) -- caller (web/app.py) sudah
    memvalidasi panjang/kekosongan field, kode admin, DAN kategori (thd
    FORUM_KATEGORI) SEBELUM memanggil ini, modul ini tidak mengulang
    validasi itu (satu tempat kebenaran validasi)."""
    _ensure_table()
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO forum_thread (nama, judul, isi, is_admin, kategori) VALUES (?, ?, ?, ?, ?)",
            (nama, judul, isi, int(is_admin), kategori),
        )
        new_id = cur.lastrowid
        row = conn.execute("SELECT * FROM forum_thread WHERE id = ?", (new_id,)).fetchone()
    return dict(row)


def create_reply(thread_id: int, nama: str, isi: str, is_admin: bool) -> dict | None:
    """Simpan balasan baru. Returns None kalau thread_id tidak ada --
    caller mengangkat 404. Cek keberadaan thread DAN insert dalam SATU
    `with get_db()` block (satu commit) supaya tidak ada celah antara
    'thread ada' dan 'balasan disimpan'."""
    _ensure_table()
    with get_db() as conn:
        exists = conn.execute("SELECT 1 FROM forum_thread WHERE id = ?", (thread_id,)).fetchone()
        if exists is None:
            return None
        cur = conn.execute(
            "INSERT INTO forum_reply (thread_id, nama, isi, is_admin) VALUES (?, ?, ?, ?)",
            (thread_id, nama, isi, int(is_admin)),
        )
        new_id = cur.lastrowid
        row = conn.execute("SELECT * FROM forum_reply WHERE id = ?", (new_id,)).fetchone()
    return dict(row)


_SORT_SQL = {
    "terbaru": "t.created_at DESC, t.id DESC",
    "populer": "total_upvotes DESC, reply_count DESC, t.created_at DESC, t.id DESC",
}


def list_threads(
    limit: int = 200,
    q: str | None = None,
    kategori: str | None = None,
    sort: str = "terbaru",
    status: str | None = None,
) -> list[dict]:
    """Daftar thread (default terbaru dulu), plus reply_count & total_upvotes
    per thread -- batas `limit` sbg jaring pengaman thd pertumbuhan tak
    terbatas (BUKAN pagination sungguhan, dianggap cukup utk skala proyek
    skripsi ini).

    ORDER BY created_at SAJA tidak cukup -- datetime('now','localtime')
    SQLite presisi DETIK (bukan milidetik), jadi dua thread yang dibuat
    dalam detik yang sama akan seri (ditemukan lewat tes: 2 POST beruntun
    tanpa jeda jaringan sungguhan gampang kena kasus ini) dan urutannya
    jadi tidak terdefinisi. `id DESC` sbg tie-breaker -- id auto-increment
    SELALU mencerminkan urutan insert sungguhan, bahkan saat timestamp seri.

    `sort` HANYA dipakai sbg key lookup ke `_SORT_SQL` (fallback ke
    'terbaru' kalau key tak dikenal) -- TIDAK PERNAH di-string-format
    mentah ke SQL (caller/app.py juga sudah validasi, tapi modul ini
    defensif sendiri krn ORDER BY tidak bisa diparameterisasi via `?`).
    `q` dicari di judul MAUPUN isi via LIKE parameterized (caller sudah
    escape literal `%`/`_` sebelum sampai sini)."""
    _ensure_table()
    where = []
    params: list = []
    if q:
        where.append("(t.judul LIKE ? ESCAPE '\\' OR t.isi LIKE ? ESCAPE '\\')")
        params.extend([f"%{q}%", f"%{q}%"])
    if kategori:
        where.append("t.kategori = ?")
        params.append(kategori)
    if status == "belum_dijawab":
        where.append("(SELECT COUNT(*) FROM forum_reply r WHERE r.thread_id = t.id) = 0")
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    order_sql = _SORT_SQL.get(sort, _SORT_SQL["terbaru"])
    with get_db() as conn:
        rows = conn.execute(f'''
            SELECT t.*,
                (SELECT COUNT(*) FROM forum_reply r WHERE r.thread_id = t.id) AS reply_count,
                (SELECT COALESCE(SUM(upvotes), 0) FROM forum_reply r WHERE r.thread_id = t.id) AS total_upvotes
            FROM forum_thread t
            {where_sql}
            ORDER BY {order_sql}
            LIMIT ?
        ''', (*params, limit)).fetchall()
    return [dict(r) for r in rows]


def get_thread(thread_id: int) -> dict | None:
    _ensure_table()
    with get_db() as conn:
        row = conn.execute("SELECT * FROM forum_thread WHERE id = ?", (thread_id,)).fetchone()
    return dict(row) if row else None


def list_replies(thread_id: int) -> list[dict]:
    """Balasan urut: jawaban terbaik (is_best_answer) SELALU naik ke atas
    dulu, sisanya kronologis (created_at ASC) -- alur baca alami dari
    pertanyaan ke jawaban-jawaban berikutnya. `id ASC` sbg tie-breaker
    SAMA alasannya dgn list_threads() -- created_at presisi detik saja."""
    _ensure_table()
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM forum_reply WHERE thread_id = ? "
            "ORDER BY is_best_answer DESC, created_at ASC, id ASC", (thread_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def reply_counts_for_threads(thread_ids: list[int]) -> dict[int, dict]:
    """Untuk tiap thread_id yang diminta, kembalikan {thread_id: {count,
    latest_reply_id}} -- dipakai lonceng notifikasi forum: klien kirim
    daftar id thread yang dia ikuti (miliknya sendiri atau yang dibalas),
    server balas jumlah balasan & id balasan terakhir supaya klien bisa
    deteksi ADA BALASAN BARU dgn membandingkan latest_reply_id thd yang
    tersimpan. Thread yang tidak punya balasan tetap muncul dgn count=0
    (bukan hilang dari hasil) supaya klien tidak salah kira thread-nya
    terhapus. Batas jumlah id di-cap di caller (web/app.py) supaya query
    IN (...) tidak membengkak."""
    _ensure_table()
    if not thread_ids:
        return {}
    placeholders = ",".join("?" for _ in thread_ids)
    with get_db() as conn:
        rows = conn.execute(
            f"SELECT thread_id, COUNT(*) AS c, MAX(id) AS latest "
            f"FROM forum_reply WHERE thread_id IN ({placeholders}) GROUP BY thread_id",
            tuple(thread_ids),
        ).fetchall()
    by_thread = {r["thread_id"]: {"count": r["c"], "latest_reply_id": r["latest"]} for r in rows}
    # Isi thread tanpa balasan dgn count 0 (tidak dilewati) supaya klien
    # punya entri utk SEMUA thread yang dia tanya.
    return {tid: by_thread.get(tid, {"count": 0, "latest_reply_id": 0}) for tid in thread_ids}


def delete_thread(thread_id: int) -> bool:
    """Hapus thread BESERTA semua balasannya (cascade MANUAL -- lihat
    catatan modul di atas soal foreign_keys tidak di-enforce), dalam SATU
    `with get_db()` block supaya atomic (thread & balasannya terhapus
    bersamaan, atau tidak sama sekali kalau ada error). Returns True kalau
    thread-nya benar-benar ada & terhapus (caller mengangkat 404 kalau False)."""
    _ensure_table()
    with get_db() as conn:
        conn.execute("DELETE FROM forum_reply WHERE thread_id = ?", (thread_id,))
        cur = conn.execute("DELETE FROM forum_thread WHERE id = ?", (thread_id,))
    return cur.rowcount > 0


def delete_reply(reply_id: int) -> bool:
    _ensure_table()
    with get_db() as conn:
        cur = conn.execute("DELETE FROM forum_reply WHERE id = ?", (reply_id,))
    return cur.rowcount > 0


def upvote_reply(reply_id: int) -> dict | None:
    """Tambah 1 upvote. TIDAK ADA dedup di sisi server (keputusan desain
    disetujui user -- taruhannya cuma urutan tampilan, bukan uang/keamanan;
    dedup "1 orang 1 vote" murni localStorage di frontend, best-effort).
    Returns None kalau reply tidak ada (caller mengangkat 404)."""
    _ensure_table()
    with get_db() as conn:
        cur = conn.execute("UPDATE forum_reply SET upvotes = upvotes + 1 WHERE id = ?", (reply_id,))
        if cur.rowcount == 0:
            return None
        row = conn.execute("SELECT * FROM forum_reply WHERE id = ?", (reply_id,)).fetchone()
    return dict(row)


def set_best_answer(reply_id: int) -> dict | None:
    """Toggle status jawaban terbaik utk `reply_id`. Kalau reply ini SUDAH
    jadi jawaban terbaik, lepas (toggle-off). Kalau belum, lepas jawaban
    terbaik LAIN di thread yang sama dulu baru tandai reply ini -- supaya
    MAKSIMAL SATU jawaban terbaik per thread, dalam SATU `get_db()` block
    (atomic, tidak ada celah antara unset & set). Returns None kalau reply
    tidak ada (caller mengangkat 404)."""
    _ensure_table()
    with get_db() as conn:
        row = conn.execute(
            "SELECT thread_id, is_best_answer FROM forum_reply WHERE id = ?", (reply_id,)
        ).fetchone()
        if row is None:
            return None
        if row["is_best_answer"]:
            conn.execute("UPDATE forum_reply SET is_best_answer = 0 WHERE id = ?", (reply_id,))
        else:
            conn.execute(
                "UPDATE forum_reply SET is_best_answer = 0 WHERE thread_id = ?", (row["thread_id"],)
            )
            conn.execute("UPDATE forum_reply SET is_best_answer = 1 WHERE id = ?", (reply_id,))
        updated = conn.execute("SELECT * FROM forum_reply WHERE id = ?", (reply_id,)).fetchone()
    return dict(updated)


def report_thread(thread_id: int) -> bool:
    _ensure_table()
    with get_db() as conn:
        cur = conn.execute(
            "UPDATE forum_thread SET report_count = report_count + 1 WHERE id = ?", (thread_id,)
        )
    return cur.rowcount > 0


def report_reply(reply_id: int) -> bool:
    _ensure_table()
    with get_db() as conn:
        cur = conn.execute(
            "UPDATE forum_reply SET report_count = report_count + 1 WHERE id = ?", (reply_id,)
        )
    return cur.rowcount > 0
