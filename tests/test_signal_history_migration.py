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


def test_ensure_table_does_not_revive_sl_hit_into_conflict_with_existing_active_row(clean_signal_db):
    """Bug produksi NYATA KEDUA, ditemukan SETELAH fix pertama di atas
    di-deploy tapi /api/signals & /api/portofolio masih 500 (kasus asli:
    BSSR) -- migrasi "hidupkan balik SL_HIT yang sl_pct-nya ternyata di
    bawah floor MIN_SL_PCT" (lihat komentar panjang di _ensure_table)
    men-UPDATE status jadi 'OPEN' TANPA cek apakah kode itu SUDAH punya
    baris aktif lain, sehingga UPDATE itu sendiri melempar IntegrityError,
    migrasi tak pernah tuntas, `_ensured` tak pernah True, dan /api/signals
    dkk gagal PERMANEN.

    Yang dijaga di sini: bentrokan SESAMA source-group. Dua baris aktif utk
    kode yang sama di grup 'main' melanggar idx_signal_unique_open_kode
    (aktif tepat di titik UPDATE ini) maupun idx_signal_active_main di
    migrasi ke-17, jadi baris SL_HIT itu TIDAK boleh dihidupkan balik.
    Kasus LINTAS-group (BSSR asli: TOP_PICK OPEN + NR7_52W SL_HIT) diuji
    terpisah di bawah -- sejak 2026-07-29 justru HARUS boleh."""
    sh._ensure_table()

    with get_db() as conn:
        # Baris AKTIF yang sudah ada, dan baris SL_HIT dari grup yang SAMA.
        conn.execute('''
            INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, status, source)
            VALUES ('BSSR', 4288, 5, 3, 'OPEN', 'TOP_PICK')
        ''')
        # sl_pct di bawah floor (1.0% < MIN_SL_PCT 3.0%) DAN resolved_price
        # masih di atas floor yang benar -- persis kriteria "revival".
        conn.execute('''
            INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, status, source,
                                        recommendation, resolved_price)
            VALUES ('BSSR', 4300, 5, 1.0, 'SL_HIT', 'SMART_MONEY', 'BELI KUAT', 4240)
        ''')

    sh._ensured = False

    sh._ensure_table()  # TIDAK BOLEH melempar IntegrityError

    with get_db() as conn:
        row = conn.execute(
            "SELECT status, sl_pct FROM signal_history WHERE kode='BSSR' AND source='SMART_MONEY'"
        ).fetchone()

    # Tidak dihidupkan (tetap SL_HIT) -- kode ini SUDAH punya posisi aktif
    # lain DI GRUP YANG SAMA, menghidupkannya bikin dua cerita aktif yang
    # saling tumpang tindih. Kejujuran data > memaksa koreksi yang bikin ganda.
    assert row["status"] == "SL_HIT"


def test_ensure_table_revives_sl_hit_when_only_other_active_row_is_different_theory(clean_signal_db):
    """Sisi lain dari test di atas, dan bagian dari perbaikan 2026-07-29:
    penjaga anti-IntegrityError itu awalnya menolak revival kalau kode punya
    baris aktif dari source APA PUN. Setelah index dipersempit per
    source-group (lihat migrasi keenam), syarat seketat itu mengulang
    kesalahan yang sama -- sinyal NR7 dgn SL keketatan tak akan pernah
    dikoreksi cuma karena kebetulan ada Top Pick aktif utk saham yang sama,
    padahal keduanya memang dirancang hidup berdampingan. Ini konfigurasi
    BSSR yang ASLI dari produksi (TOP_PICK OPEN id 251 + NR7_52W SL_HIT
    sl_pct=1.0 id 333): sekarang NR7-nya HARUS dihidupkan balik, dan
    migrasi tetap TIDAK BOLEH melempar IntegrityError."""
    sh._ensure_table()

    with get_db() as conn:
        conn.execute('''
            INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, status, source)
            VALUES ('BSSR', 4288, 5, 3, 'OPEN', 'TOP_PICK')
        ''')
        conn.execute('''
            INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, status, source, resolved_price)
            VALUES ('BSSR', 4300, 5, 1.0, 'SL_HIT', 'NR7_52W', 4240)
        ''')

    sh._ensured = False

    sh._ensure_table()  # tetap tidak boleh melempar apa pun

    with get_db() as conn:
        rows = conn.execute(
            "SELECT source, status, sl_pct FROM signal_history WHERE kode='BSSR' ORDER BY source"
        ).fetchall()
    by_src = {r["source"]: r for r in rows}

    from core.trading_plan import MIN_SL_PCT

    assert by_src["NR7_52W"]["status"] == "OPEN", (
        "SL_HIT dgn SL di bawah floor harus dikoreksi -- Top Pick dari teori "
        "LAIN tidak boleh menghalanginya"
    )
    assert by_src["NR7_52W"]["sl_pct"] == MIN_SL_PCT, "sl_pct dilebarkan ke floor"
    assert by_src["TOP_PICK"]["status"] == "OPEN", "baris Top Pick tidak ikut terganggu"


def test_ensure_table_does_not_delete_nr7_row_coexisting_with_top_pick(clean_signal_db):
    """Bug produksi NYATA KETIGA & paling merusak (laporan user 2026-07-29,
    kasus GJTL & MLBI): sinyal NR7_52W muncul di notifikasi lalu LENYAP dari
    Audit Sinyal, menyisakan cuma baris Top Pick -- padahal dua teori itu
    memang SENGAJA boleh memegang saham yang sama (lihat _has_open_nr7 &
    index terpisah per source-group di migrasi ke-17).

    Akarnya (dilacak pakai sqlite3.set_trace_callback): migrasi KEENAM
    menghapus semua baris OPEN kecuali id terkecil PER KODE tanpa peduli
    source -- ditulis waktu source yang ada baru TOP_PICK & SMART_MONEY.
    Karena rantai migrasi jalan ULANG tiap proses start (`_ensured` cuma
    flag per-proses, bukan versi skema tersimpan), SETIAP restart server
    menghapus ulang baris NR7 yang baru tercatat. Terbukti di data: TIDAK
    ADA satu pun baris NR7_52W yang bertahan di DB selama seminggu fitur itu
    aktif, walau notifikasinya rutin muncul.

    Test ini menaruh persis konfigurasi itu (TOP_PICK id lebih KECIL supaya
    NR7-lah yang jadi korban DELETE lama) lalu menjalankan ulang seluruh
    rantai migrasi: KEDUA baris harus selamat."""
    sh._ensure_table()

    with get_db() as conn:
        # Top Pick lebih dulu (id lebih kecil) -- di migrasi keenam versi lama,
        # baris inilah yang "menang" dan NR7 di bawah yang dihapus.
        conn.execute('''
            INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, status, source,
                                        direction, recorded_at)
            VALUES ('GJTL', 1139, 3.0, 3.0, 'OPEN', 'TOP_PICK', 'BUY', datetime('now', '-1 days'))
        ''')
        # NR7 + 52W High utk kode SAMA, rencana BEDA (entry/tp/sl semuanya
        # beda -- sekaligus menghindari migrasi ke-8 yang men-dedup baris
        # ber-entry/TP/SL IDENTIK di tanggal yang sama, bukan constraint
        # yang sedang diuji di sini).
        conn.execute('''
            INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, status, source,
                                        direction, entry_mode, recorded_at)
            VALUES ('GJTL', 1195, 4.0, 2.0, 'OPEN', 'NR7_52W', 'BUY', 'AGRESIF', datetime('now'))
        ''')

    sh._ensured = False  # simulasikan RESTART server (rantai migrasi jalan lagi)

    sh._ensure_table()

    with get_db() as conn:
        rows = conn.execute(
            "SELECT source, entry_price, status FROM signal_history "
            "WHERE kode='GJTL' ORDER BY source"
        ).fetchall()

    sources = [r["source"] for r in rows]
    assert sources == ["NR7_52W", "TOP_PICK"], (
        f"KEDUA teori harus selamat melewati migrasi, dapatnya {sources} -- "
        "migrasi keenam menghapus NR7 lintas-source lagi"
    )
    by_src = {r["source"]: r for r in rows}
    assert by_src["NR7_52W"]["entry_price"] == 1195
    assert by_src["TOP_PICK"]["entry_price"] == 1139
    assert all(r["status"] == "OPEN" for r in rows), "keduanya tetap OPEN, bukan diam-diam di-resolve"


def test_ensure_table_still_dedups_two_active_rows_within_main_group(clean_signal_db):
    """Kontrol utk test di atas: mempersempit migrasi keenam ke grup 'main'
    TIDAK boleh mematikan tujuan aslinya. TOP_PICK vs SMART_MONEY utk kode
    yang sama tetap harus dirapatkan jadi satu (keputusan user lama: entry/
    TP/SL keduanya nyaris identik sehingga terlihat seperti 'double' yang
    membingungkan) -- yang berubah cuma NR7_52W tidak lagi ikut jadi korban."""
    sh._ensure_table()

    with get_db() as conn:
        # Index aktif memang MELARANG kondisi ini -- justru itu yang mau
        # disimulasikan (data lama yang terlanjur ada sebelum index dibuat),
        # jadi di-drop dulu supaya barisnya bisa masuk, persis pola test
        # duplikat di paling atas file ini.
        conn.execute("DROP INDEX IF EXISTS idx_signal_active_main")
        conn.execute("DROP INDEX IF EXISTS idx_signal_unique_open_kode")
        conn.execute('''
            INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, status, source,
                                        recommendation, direction, recorded_at)
            VALUES ('ADRO', 2000, 3.0, 3.0, 'OPEN', 'TOP_PICK', 'BAGUS', 'BUY', datetime('now', '-1 days'))
        ''')
        conn.execute('''
            INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, status, source,
                                        recommendation, direction, recorded_at)
            VALUES ('ADRO', 2050, 4.0, 3.5, 'OPEN', 'SMART_MONEY', 'BELI KUAT', 'BUY', datetime('now'))
        ''')

    sh._ensured = False

    sh._ensure_table()

    with get_db() as conn:
        rows = conn.execute(
            "SELECT source FROM signal_history WHERE kode='ADRO' AND status='OPEN'"
        ).fetchall()

    assert len(rows) == 1, "dua sinyal aktif sesama grup main tetap harus disatukan"
    assert rows[0]["source"] == "TOP_PICK", "yang bertahan tetap id terkecil (paling awal)"
