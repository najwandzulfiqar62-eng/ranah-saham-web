# Test regresi utk bug produksi NYATA 2026-07-27: migrasi ketujuh belas
# (pemecahan index unik per-kode jadi idx_signal_active_main/idx_signal_
# active_nr7, lihat core/signal_history.py::_ensure_table) lupa membersihkan
# baris yang melanggar constraint BARU sebelum CREATE UNIQUE INDEX -- kalau
# ada data existing yang melanggar, CREATE INDEX melempar IntegrityError DI
# DALAM _ensure_table() sebelum flag `_ensured` sempat di-set True, sehingga
# SETIAP pemanggilan fungsi apa pun yang menyentuh signal_history (termasuk
# /api/signals & /api/portofolio) mengulang migrasi dari awal dan gagal lagi
# dgn error yang SAMA -- bukan cuma sekali, PERMANEN sampai proses direstart
# (dan bahkan restart TIDAK menyembuhkan, karena data pelanggarnya masih ada
# di file DB yang sama). Test ini mensimulasikan skenario itu persis: index
# di-drop, baris duplikat disisipkan langsung, lalu _ensure_table() dipanggil
# ulang -- HARUS berhasil membersihkan duplikat & membangun ulang index-nya,
# bukan melempar exception.
import core.signal_history as sh
from core.database import get_db


def test_ensure_table_self_heals_from_duplicate_active_rows(clean_signal_db):
    sh._ensure_table()  # pastikan skema dasar ada dulu

    with get_db() as conn:
        conn.execute("DROP INDEX IF EXISTS idx_signal_active_main")
        conn.execute("DROP INDEX IF EXISTS idx_signal_active_nr7")
        # Dua baris OPEN/PENDING_ENTRY utk kode SAMA, source SAMA grup
        # ('main': TOP_PICK+SMART_MONEY) -- persis pola yang melanggar
        # idx_signal_active_main. DUA jebakan nyata yang bikin draf-draf
        # AWAL tes ini keliru lolos walau bug-nya belum diperbaiki, jadi
        # sengaja dihindari eksplisit di sini:
        #  1. Kalau salah satu baris source='SMART_MONEY' tanpa
        #     'recommendation' yang valid, migrasi TERPISAH & tak terkait
        #     di _ensure_table() sudah menghapusnya duluan -- karena itu
        #     DUA-DUANYA di sini 'TOP_PICK'.
        #  2. Migrasi PALING AWAL (migrasi ketiga) sudah dedup "1 baris per
        #     (kode, date(recorded_at), source)" -- kalau kedua baris
        #     direkam pada TANGGAL YANG SAMA, migrasi itu SENDIRI yang
        #     membereskan salah satunya sebelum sempat menguji index yang
        #     sebenarnya mau diuji. Constraint yang mau diuji di sini justru
        #     TIDAK peduli tanggal (per desain: "1 cerita aktif per kode
        #     KAPAN PUN", bukan per hari) -- karena itu recorded_at kedua
        #     baris sengaja dibuat beda TANGGAL, meniru sinyal yang
        #     direkam hari terpisah utk kode yang sama.
        conn.execute('''
            INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, status, source, recorded_at)
            VALUES ('BBCA', 9000, 5, 3, 'OPEN', 'TOP_PICK', datetime('now', '-3 days'))
        ''')
        conn.execute('''
            INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, status, source, recorded_at)
            VALUES ('BBCA', 9100, 5, 3, 'PENDING_ENTRY', 'TOP_PICK', datetime('now'))
        ''')
        first_id = conn.execute(
            "SELECT MIN(id) AS m FROM signal_history WHERE kode='BBCA'"
        ).fetchone()["m"]

    sh._ensured = False  # simulasikan proses baru yg belum pernah sukses migrasi

    sh._ensure_table()  # TIDAK BOLEH melempar IntegrityError

    with get_db() as conn:
        rows = conn.execute(
            "SELECT id FROM signal_history WHERE kode='BBCA' "
            "AND status IN ('OPEN','PENDING_ENTRY') AND source IN ('TOP_PICK','SMART_MONEY')"
        ).fetchall()
        idx_exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_signal_active_main'"
        ).fetchone()

    assert len(rows) == 1, "duplikat aktif seharusnya dibersihkan, sisakan satu"
    assert rows[0]["id"] == first_id, "yang dipertahankan harus yang id TERKECIL (paling awal)"
    assert idx_exists is not None, "index unik harus berhasil dibangun ulang setelah dedup"
