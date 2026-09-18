"""Simpanan filing X-15 (POJK 4/2024) yang BERTAHAN, bukan sekadar cache.

KENAPA ADA -- ini menjawab "kok riwayat pemegang saham hilang, kemarin
banyak". Tidak ada yang menghapusnya. Riwayat itu memang tidak pernah
disimpan: seluruhnya hidup di cache Redis `x15raw:{n}` dengan umur 24 jam.
Selama idx.co.id bisa dihubungi tiap hari, cache itu terus terisi ulang dan
terlihat seperti arsip. Begitu sumbernya tidak terjangkau (Cloudflare 403),
tidak ada lagi yang mengisi ulang -- dan satu per satu kunci kedaluwarsa
sampai habis.

Cache menjawab "supaya tidak mengambil ulang". Ia tidak pernah menjawab
"supaya tidak hilang". Dua hal yang berbeda, dan yang kedua belum pernah
dikerjakan di sini.

Filing X-15 itu ARSIP: sekali terbit, isinya tidak berubah lagi. Data
seperti itu tidak punya alasan untuk disimpan di tempat yang kedaluwarsa.
Yang disimpan di sini adalah hasil yang SUDAH berhasil diambil dan diurai,
jadi ia menumpuk dari hari ke hari dan tetap bisa dibaca walaupun idx.co.id
sedang menolak.
"""
from core.database import get_db

# Kolom yang membentuk satu filing. Dipisah sebagai konstanta supaya penulis
# dan pembaca tidak bisa berbeda diam-diam.
KOLOM = ("tanggal", "kode", "nama", "perusahaan", "jabatan",
         "pct_sebelum", "pct_setelah", "perubahan", "jenis", "pengendali",
         "pdf_url")


def ensure_x15_tables() -> None:
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS x15_filing (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tanggal TEXT NOT NULL,
                kode TEXT NOT NULL,
                nama TEXT,
                perusahaan TEXT,
                jabatan TEXT,
                pct_sebelum REAL,
                pct_setelah REAL,
                perubahan REAL,
                jenis TEXT,
                pengendali INTEGER NOT NULL DEFAULT 0,
                pdf_url TEXT,
                disimpan_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        # Satu filing = satu PDF. URL-nya yang membuatnya unik, bukan isinya:
        # satu orang bisa melapor dua kali di hari yang sama dengan angka yang
        # kebetulan sama, dan itu dua filing, bukan satu yang terduplikasi.
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_x15_pdf "
                     "ON x15_filing(pdf_url)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_x15_kode_tgl "
                     "ON x15_filing(kode, tanggal)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_x15_tgl "
                     "ON x15_filing(tanggal)")


def _baris(it: dict) -> tuple:
    return (
        str(it.get("tanggal") or "")[:10],
        str(it.get("kode") or "").upper().strip(),
        it.get("nama"), it.get("perusahaan"), it.get("jabatan"),
        it.get("pct_sebelum"), it.get("pct_setelah"), it.get("perubahan"),
        it.get("jenis"), 1 if it.get("pengendali") else 0,
        it.get("pdf_url"),
    )


def simpan_filing(items) -> int:
    """Simpan filing yang BERHASIL diambil. Return berapa baris baru.

    Sengaja memaafkan: menyimpan itu tambahan, bukan syarat. Kalau gagal,
    fitur yang sedang berjalan tidak boleh ikut jatuh -- itu akan menukar
    satu masalah dengan yang lebih buruk.
    """
    baris = [_baris(it) for it in (items or [])
             if it.get("pdf_url") and it.get("kode")]
    if not baris:
        return 0
    try:
        # DI DALAM try, bukan di luarnya. Membuat tabel juga menyentuh basis
        # data, jadi ia bisa gagal dengan cara yang sama -- dan kalau
        # gagalnya lolos ke pemanggil, lapisan yang seharusnya menolong
        # justru menjatuhkan pengambilan data yang tadinya berhasil.
        ensure_x15_tables()
        with get_db() as conn:
            sebelum = conn.execute("SELECT COUNT(*) c FROM x15_filing").fetchone()["c"]
            conn.executemany(
                f"INSERT OR IGNORE INTO x15_filing ({', '.join(KOLOM)}) "
                f"VALUES ({', '.join('?' * len(KOLOM))})", baris)
            sesudah = conn.execute("SELECT COUNT(*) c FROM x15_filing").fetchone()["c"]
        return sesudah - sebelum
    except Exception as e:
        print(f"⚠️ x15_store: gagal menyimpan filing: {type(e).__name__}: {e}")
        return 0


def _sebagai_item(row) -> dict:
    it = {k: row[k] for k in KOLOM}
    it["pengendali"] = bool(it["pengendali"])
    return it


def ambil_untuk_kode(kode: str, sejak: str) -> list[dict]:
    """Filing tersimpan untuk satu emiten sejak tanggal (YYYY-MM-DD)."""
    ensure_x15_tables()
    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT * FROM x15_filing WHERE kode = ? AND tanggal >= ? "
                "ORDER BY tanggal DESC", (kode.upper().strip(), sejak)).fetchall()
        return [_sebagai_item(r) for r in rows]
    except Exception:
        return []


def ambil_untuk_tanggal(tanggal: str) -> list[dict]:
    """Filing tersimpan untuk SATU tanggal, semua emiten."""
    ensure_x15_tables()
    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT * FROM x15_filing WHERE tanggal = ?", (tanggal,)).fetchall()
        return [_sebagai_item(r) for r in rows]
    except Exception:
        return []


def ringkas() -> dict:
    """Berapa yang tersimpan, dan rentang tanggalnya -- untuk ditampilkan
    saat data tersaji dari simpanan, bukan dari idx.co.id secara langsung."""
    ensure_x15_tables()
    try:
        with get_db() as conn:
            r = conn.execute(
                "SELECT COUNT(*) n, MIN(tanggal) awal, MAX(tanggal) akhir, "
                "COUNT(DISTINCT kode) emiten FROM x15_filing").fetchone()
        return {"n": r["n"] or 0, "awal": r["awal"], "akhir": r["akhir"],
                "emiten": r["emiten"] or 0}
    except Exception:
        return {"n": 0, "awal": None, "akhir": None, "emiten": 0}
