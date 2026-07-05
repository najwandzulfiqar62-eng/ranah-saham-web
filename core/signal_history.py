# =========================
# SIGNAL HISTORY + AUTO AUDIT
# =========================
# FITUR BARU. Permintaan eksplisit user: "fitur paling bernilai untuk
# kredibilitas" -- setiap sinyal Top Pick yang pernah ditampilkan ke user
# DICATAT, lalu diaudit otomatis terhadap harga riil untuk lihat apakah
# target (TP) atau stop loss (SL) tercapai. Tanpa ini, klaim "AI Score
# bagus" tidak pernah bisa dibuktikan/dibantah dengan data -- cuma janji.
#
# PRINSIP JUJUR yang WAJIB dipegang (ditegaskan berulang oleh user):
# - JANGAN PERNAH mengarang win rate/return kalau belum ada sinyal yang
#   benar-benar selesai diaudit (status TP_HIT/SL_HIT/EXPIRED). Kalau
#   kosong, bilang jujur "belum cukup data", BUKAN tampilkan 0% atau
#   angka acak yang kelihatan meyakinkan.
# - Sinyal DICATAT OTOMATIS dari hasil /api/confidence (Top Pick) yang
#   SUDAH ditampilkan ke user -- BUKAN dipilih manual/cherry-picked
#   sesudah tahu hasilnya. Ini penting: track record cuma kredibel kalau
#   sinyalnya dicatat SEBELUM tahu benar/salahnya.
# - TP/SL dipakai di sini SAMA PERSIS dengan yang sudah dihitung buat
#   badge Ringkasan Cepat (potensi_naik_pct/risiko_turun_pct dari
#   calculate_snr_levels) -- bukan angka baru yang beda dari yang dilihat
#   user saat sinyal itu pertama ditampilkan.
#
# REVISI (Juli 2026): audit SEKARANG juga jalan otomatis via background
# task periodik di web/app.py (_signal_auto_loop), TIDAK LAGI cuma
# on-demand saat /api/signals dipanggil -- permintaan eksplisit user
# supaya status sinyal & notifikasi Telegram ter-update walau tidak ada
# yang sedang membuka halaman. record_top_picks() & audit_open_signals()
# sekarang mengembalikan LIST sinyal yang baru dicatat/diselesaikan
# (bukan cuma jumlah/None) supaya caller bisa mengirim notifikasi berisi
# detail sinyalnya -- fungsi ini SENDIRI tetap tidak melakukan I/O
# jaringan (kirim notifikasi jadi tanggung jawab caller di web/app.py),
# supaya tetap mudah ditest tanpa mock network/Telegram.
#
# REVISI KEDUA (Juli 2026): ditambah kolom 'source' -- signal_history
# sekarang punya DUA sumber entry point independen: 'TOP_PICK' (skor
# gabungan harian, seperti sebelumnya) dan 'MACD_CROSS' (permintaan
# eksplisit user: histogram MACD yang baru saja berbalik positif dipakai
# SENDIRI sebagai teori entry point, TANPA disaring skor gabungan lain --
# supaya validitas teori itu bisa diuji apa adanya lewat data real, bukan
# tercampur/ketutupan Top Pick). Kedua sumber diaudit dengan cara yang
# SAMA PERSIS (audit_open_signals tidak peduli source), dan get_signal_
# report() menghitung win rate/return TERPISAH per source (stats_by_source)
# selain angka gabungan -- supaya user bisa benar-benar bandingkan mana
# yang lebih valid, bukan cuma klaim.

from datetime import datetime, timedelta

from core.database import get_db

# Sinyal yang tidak tercapai TP maupun SL dalam MAX_HOLD_DAYS dianggap
# "kadaluarsa" (EXPIRED) -- horison realistis untuk sinyal teknikal
# swing/menengah (bukan scalping harian, bukan juga investasi tahunan).
MAX_HOLD_DAYS = 20

# Ambang minimum confidence_score supaya masuk daftar yang diaudit --
# JANGAN catat SEMUA 45 saham tiap hari (terlalu bising, dan sinyal yang
# skornya biasa-biasa saja bukan "yang ditampilkan sebagai Top Pick").
MIN_SCORE_TO_RECORD = 55.0
# Maksimum berapa saham teratas per hari yang dicatat -- konsisten dengan
# semangat "Top Pick" (peringkat TERATAS), bukan seluruh universe.
MAX_RECORDED_PER_DAY = 10

# Maksimum berapa entry point MACD Histogram Cross per hari yang dicatat --
# alasan sama dengan MAX_RECORDED_PER_DAY (jangan bising), TAPI angka ini
# TIDAK terkait skor gabungan sama sekali (lihat record_macd_cross_signals).
MACD_CROSS_MAX_PER_DAY = 10


def _is_bursa_weekend() -> bool:
    """True kalau HARI INI Sabtu/Minggu -- BEI tidak buka, jadi closing
    price yfinance yang dipakai utk hitung confidence_score/entry masih
    PERSIS closing hari bursa terakhir (Jumat), bukan data baru.

    BUG NYATA ditemukan lewat inspeksi data produksi: siklus auto-audit
    (jalan tiap 600 detik, 24/7, tidak peduli akhir pekan) tetap mencatat
    "sinyal Top Pick baru" di hari Sabtu & Minggu dengan entry_price/tp_pct/
    sl_pct yang IDENTIK dengan sinyal Jumat -- karena memang belum ada
    pergerakan harga sungguhan. Akibatnya satu pergerakan pasar bisa
    tercatat sebagai 2-3 sinyal terpisah (Jumat, Sabtu, Minggu semua dgn
    angka sama), yang MENGGANDAKAN statistik win-rate secara palsu kalau
    nanti sinyal itu kena TP/SL -- justru bertentangan dengan prinsip
    kredibilitas "jangan mengarang win rate" yang jadi alasan fitur ini
    dibuat.

    KETERBATASAN YANG JUJUR DICATAT: ini cuma cek akhir pekan, BELUM
    menutup hari libur nasional Indonesia yang jatuh di hari kerja (mis.
    Idul Fitri, Natal) -- itu butuh kalender libur bursa eksternal yang di
    luar cakupan perbaikan ini. Tetap perbaikan nyata utk kasus dominan
    (2 dari 7 hari), bukan solusi lengkap."""
    return datetime.now().weekday() >= 5  # 5=Sabtu, 6=Minggu


# CATATAN TIMEZONE PENTING: semua SQL di modul ini yang butuh "tanggal hari
# ini" HARUS pakai `datetime('now', 'localtime')`/`date('now', 'localtime')`,
# BUKAN `datetime('now')`/`date('now')` polos. SQLite's `datetime('now')`
# SELALU UTC, sedangkan BEI beroperasi WIB (UTC+7) dan _is_bursa_weekend()
# di atas pakai Python `datetime.now()` (local/WIB). BUG NYATA ditemukan
# lewat inspeksi live: jam 00:00-06:59 WIB, tanggal UTC MASIH "kemarin" --
# tanpa 'localtime', satu hari bursa WIB yang sama bisa terbagi jadi 2
# "tanggal UTC" berbeda, membuat dedup check (`date(recorded_at) =
# date('now')`) gagal mendeteksi duplikat yang sebenarnya sama hari bursa
# -- kelas bug yang SAMA dengan race condition/weekend duplication di atas,
# lewat celah timezone yang berbeda.
_ensured = False


def _ensure_table():
    global _ensured
    if _ensured:
        return
    with get_db() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS signal_history (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                kode             TEXT NOT NULL,
                recorded_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                entry_price      REAL NOT NULL,
                tp_pct           REAL NOT NULL,
                sl_pct           REAL NOT NULL,
                confidence_score REAL,
                ai_score         REAL,
                recommendation   TEXT,
                status           TEXT NOT NULL DEFAULT 'OPEN',
                resolved_at      TEXT,
                resolved_price   REAL,
                return_pct       REAL,
                days_to_resolve  INTEGER
            )
        ''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_signal_status ON signal_history(status)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_signal_kode_date ON signal_history(kode, recorded_at)')
        # Migrasi ringan: kolom 'pattern' (nama pola chart rule-based dari
        # detect_patterns(), mis. "DOUBLE BOTTOM") ditambahkan belakangan --
        # ALTER TABLE ADD COLUMN aman di SQLite utk row yang sudah ada
        # (otomatis NULL), tidak perlu drop/recreate tabel produksi.
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(signal_history)").fetchall()}
        if "pattern" not in cols:
            conn.execute("ALTER TABLE signal_history ADD COLUMN pattern TEXT")
        # Migrasi ringan kedua: kolom 'source' membedakan entry point dari
        # Top Pick (skor gabungan) vs MACD Cross (momentum, teori berdiri
        # sendiri) -- default 'TOP_PICK' utk baris lama (semuanya memang
        # dari Top Pick sebelum fitur MACD Cross ada), aman tanpa migrasi data manual.
        if "source" not in cols:
            conn.execute("ALTER TABLE signal_history ADD COLUMN source TEXT NOT NULL DEFAULT 'TOP_PICK'")
        # Migrasi ketiga: BUG NYATA ditemukan lewat inspeksi data produksi --
        # record_top_picks()/record_macd_cross_signals() dulu cek duplikat
        # via SELECT lalu INSERT terpisah (bukan atomic), dengan sebuah
        # `await price_lookup(...)` (network call) di ANTARA keduanya. Kalau
        # dua panggilan confidence() tumpang tindih (mis. siklus auto-audit
        # 600 detik vs request /api/confidence manual yang bersamaan), event
        # loop bisa berpindah task tepat di celah itu -- kedua task lolos
        # SELECT "belum ada" sebelum salah satu sempat INSERT, hasilnya
        # baris duplikat persis (kode+tanggal+source sama, selisih detik).
        # Dibuktikan nyata: /api/signals produksi berisi ~12 kode tercatat
        # 2x dengan recorded_at berselisih ~1 detik.
        #
        # Bersihkan duplikat lama SEBELUM index unique dibuat (kalau
        # tidak, CREATE UNIQUE INDEX gagal karena data existing sudah
        # melanggar constraint-nya) -- baris ber-id TERKECIL per grup
        # dipertahankan (yang pertama tercatat).
        conn.execute('''
            DELETE FROM signal_history
            WHERE id NOT IN (
                SELECT MIN(id) FROM signal_history
                GROUP BY kode, date(recorded_at), source
            )
        ''')
        conn.execute('''
            CREATE UNIQUE INDEX IF NOT EXISTS idx_signal_unique_daily
            ON signal_history(kode, date(recorded_at), source)
        ''')
        # Migrasi keempat: kelas duplikasi TERPISAH dari race condition di
        # atas -- sebelum _is_bursa_weekend() ada, siklus auto-audit tetap
        # mencatat "sinyal baru" di hari Sabtu/Minggu dengan entry_price/
        # tp_pct/sl_pct IDENTIK dengan sinyal hari sebelumnya (BEI tutup,
        # closing price belum berubah) -- baris-baris ini LOLOS index unique
        # di atas karena tanggalnya beda (Sabtu vs Jumat), padahal secara
        # substansi itu sinyal yang SAMA persis, cuma dicatat ulang tanpa
        # informasi baru. Kalau dibiarkan, satu pergerakan pasar bisa
        # dihitung sebagai 2+ kemenangan/kekalahan terpisah begitu kena TP/
        # SL. Hapus baris yang PERSIS sama (kode+source+entry_price+tp_pct+
        # sl_pct) selain yang PALING AWAL tercatat (id terkecil) -- dijalankan
        # tiap startup, idempotent, aman diulang (kalau sudah bersih tidak
        # menghapus apa-apa). _is_bursa_weekend() sudah mencegah kasus BARU,
        # ini cuma membersihkan sisa data historis dari sebelum fix itu ada.
        conn.execute('''
            DELETE FROM signal_history
            WHERE id NOT IN (
                SELECT MIN(id) FROM signal_history
                GROUP BY kode, source, entry_price, tp_pct, sl_pct
            )
        ''')
    _ensured = True


async def record_top_picks(items: list[dict], price_lookup=None) -> list[dict]:
    """Catat sinyal baru dari hasil /api/confidence (items sudah diurut
    confidence_score menurun). Hanya MAX_RECORDED_PER_DAY teratas yang skornya
    >= MIN_SCORE_TO_RECORD, dan SATU kode SAHAM cuma dicatat SEKALI per hari
    (dedup via tanggal) -- mencegah duplikasi kalau /api/confidence dipanggil
    berkali-kali di hari yang sama (cache 300 detik bisa expire & recompute
    beberapa kali sehari).

    Melewati saham tanpa potensi_naik_pct/risiko_turun_pct valid (mis. GOTO
    yang sedang flat di harga floor -- lihat catatan di core/charts/
    snr_chart.py) karena TP/SL tidak bisa didefinisikan dengan wajar.

    price_lookup (opsional): async callable(kode) -> float | None utk ambil
    harga REAL-TIME (reuse _realtime_price yang sudah ada di web/app.py)
    sebagai entry_price, BUKAN it['harga'] (closing harian yang bisa basi
    sampai 1 hari bursa -- entry yang dicatat dari harga penutupan yang SAMA
    dipakai buat menghitung sinyalnya sendiri secara teknis tidak pernah
    benar-benar bisa dieksekusi user, ini bentuk lookahead bias kecil).
    Kalau price_lookup None atau gagal/return None utk suatu kode, fallback
    jujur ke it['harga'] (closing harian) -- tetap lebih baik daripada
    tidak mencatat entry sama sekali.

    'pattern' (opsional, dari core/screening_pro.py::detect_patterns) ikut
    disimpan kalau ada di item -- konteks tambahan "kenapa sinyal ini
    muncul", ditampilkan di Audit Sinyal/kartu Signal Confirmed.

    Returns LIST sinyal yang baru disimpan (bukan cuma jumlah) -- caller
    (web/app.py) pakai ini utk kirim notifikasi Telegram berisi detail
    entry/TP/SL, bukan sekadar angka."""
    _ensure_table()
    if _is_bursa_weekend():
        return []  # lihat _is_bursa_weekend() -- jangan catat sinyal "baru" dgn harga basi
    candidates = [
        it for it in items
        if it.get("confidence_score", 0) >= MIN_SCORE_TO_RECORD
        and it.get("potensi_naik_pct") is not None
        and it.get("risiko_turun_pct") is not None
        and it.get("risiko_turun_pct") > 0
        and it.get("harga")
    ][:MAX_RECORDED_PER_DAY]

    if not candidates:
        return []

    saved = []
    for it in candidates:
        with get_db() as conn:
            already = conn.execute('''
                SELECT 1 FROM signal_history
                WHERE kode = ? AND date(recorded_at) = date('now', 'localtime') AND source = 'TOP_PICK'
                LIMIT 1
            ''', (it["kode"],)).fetchone()
        if already:
            continue

        entry_price = it["harga"]
        if price_lookup is not None:
            try:
                live_price = await price_lookup(it["kode"])
                if live_price:
                    entry_price = live_price
            except Exception:
                pass  # fail-open: tetap pakai closing harian, jangan gagalkan pencatatan

        tp_pct, sl_pct = it["potensi_naik_pct"], it["risiko_turun_pct"]
        pattern = it.get("pattern")
        with get_db() as conn:
            cur = conn.execute('''
                INSERT OR IGNORE INTO signal_history
                    (kode, entry_price, tp_pct, sl_pct, confidence_score, ai_score, recommendation, pattern, source, recorded_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'TOP_PICK', datetime('now', 'localtime'))
            ''', (
                it["kode"], entry_price, tp_pct, sl_pct,
                it.get("confidence_score"), it.get("ai_score"), it.get("ai_rating"), pattern,
            ))
            # OR IGNORE: kalau baris ini SEBENARNYA sudah tercatat proses/
            # task lain di celah antara SELECT di atas dan INSERT ini
            # (race, lihat catatan idx_signal_unique_daily di _ensure_table),
            # constraint UNIQUE membuat SQLite diam-diam skip insert ini --
            # rowcount jadi 0, bukan exception. Jangan masukkan ke `saved`
            # (bukan baris baru, caller tidak perlu kirim notifikasi lagi).
            if cur.rowcount == 0:
                continue
            new_id = cur.lastrowid
        saved.append({
            "id": new_id, "kode": it["kode"], "entry_price": entry_price,
            "tp_pct": tp_pct, "sl_pct": sl_pct,
            "tp_price": round(entry_price * (1 + tp_pct / 100), 2),
            "sl_price": round(entry_price * (1 - sl_pct / 100), 2),
            "confidence_score": it.get("confidence_score"), "pattern": pattern,
            "source": "TOP_PICK",
        })
    return saved


async def record_macd_cross_signals(items: list[dict], price_lookup=None) -> list[dict]:
    """Catat entry point dari TEORI MACD HISTOGRAM CROSS secara independen
    dari Top Pick (lihat record_top_picks) -- permintaan eksplisit user:
    histogram MACD (MACD line - Signal line) yang baru saja berbalik
    positif dipakai SENDIRI sebagai sinyal entry, TANPA disaring skor
    gabungan (confidence_score) sama sekali. Ini supaya validitas teori
    itu (dikutip riset QuantifiedStrategies di core/screening_pro.py) bisa
    diuji apa adanya lewat data real -- kalau disaring skor gabungan juga,
    yang teruji bukan lagi teori MACD-nya sendiri, tapi campuran.

    Kriteria PENAPISAN (bukan "seberapa bagus", tapi "apakah bisa
    dieksekusi secara wajar"): saham likuid (Sangat Likuid/Likuid) dan
    target TP/SL valid -- di luar itu, SEMUA saham dgn histogram baru
    cross bullish ikut dicatat, berapa pun confidence_score-nya.

    Boleh mencatat kode saham yang SAMA di hari yang sama dengan Top Pick
    (dedup di sini HANYA per source='MACD_CROSS') -- keduanya teori entry
    yang berbeda, sengaja diaudit terpisah, bukan saling menggantikan.

    price_lookup/pattern/return: lihat docstring record_top_picks(), pola
    yang sama persis dipakai di sini."""
    _ensure_table()
    if _is_bursa_weekend():
        return []  # lihat _is_bursa_weekend() -- jangan catat sinyal "baru" dgn harga basi
    candidates = [
        it for it in items
        if it.get("macd_bullish_cross")
        and it.get("likuiditas") in ("Sangat Likuid", "Likuid")
        and it.get("potensi_naik_pct") is not None
        and it.get("risiko_turun_pct") is not None
        and it.get("risiko_turun_pct") > 0
        and it.get("harga")
    ][:MACD_CROSS_MAX_PER_DAY]

    if not candidates:
        return []

    saved = []
    for it in candidates:
        with get_db() as conn:
            already = conn.execute('''
                SELECT 1 FROM signal_history
                WHERE kode = ? AND date(recorded_at) = date('now', 'localtime') AND source = 'MACD_CROSS'
                LIMIT 1
            ''', (it["kode"],)).fetchone()
        if already:
            continue

        entry_price = it["harga"]
        if price_lookup is not None:
            try:
                live_price = await price_lookup(it["kode"])
                if live_price:
                    entry_price = live_price
            except Exception:
                pass  # fail-open: tetap pakai closing harian, jangan gagalkan pencatatan

        tp_pct, sl_pct = it["potensi_naik_pct"], it["risiko_turun_pct"]
        with get_db() as conn:
            cur = conn.execute('''
                INSERT OR IGNORE INTO signal_history
                    (kode, entry_price, tp_pct, sl_pct, confidence_score, ai_score, recommendation, pattern, source, recorded_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'MACD HISTOGRAM BULLISH CROSS', 'MACD_CROSS', datetime('now', 'localtime'))
            ''', (
                it["kode"], entry_price, tp_pct, sl_pct,
                it.get("confidence_score"), it.get("ai_score"), it.get("ai_rating"),
            ))
            # Lihat catatan sama di record_top_picks(): OR IGNORE + index
            # unique adalah pengaman ATOMIC terakhir terhadap race antara
            # SELECT dedup di atas dan INSERT ini.
            if cur.rowcount == 0:
                continue
            new_id = cur.lastrowid
        saved.append({
            "id": new_id, "kode": it["kode"], "entry_price": entry_price,
            "tp_pct": tp_pct, "sl_pct": sl_pct,
            "tp_price": round(entry_price * (1 + tp_pct / 100), 2),
            "sl_price": round(entry_price * (1 - sl_pct / 100), 2),
            "confidence_score": it.get("confidence_score"), "pattern": "MACD HISTOGRAM BULLISH CROSS",
            "source": "MACD_CROSS",
        })
    return saved


# Maksimum berapa anomali volume "Smart Money" per hari yang dicatat --
# alasan sama dengan MACD_CROSS_MAX_PER_DAY (jangan bising).
SMART_MONEY_MAX_PER_DAY = 10

# Kategori _sm_classify() (web/app.py) yang dipetakan ke arah BUY --
# audit_open_signals()/get_signal_report() baru mendukung matematika
# long-only (TP di atas entry, SL di bawah), jadi Distribusi/Distribusi
# Agresif SENGAJA TIDAK dipetakan dulu (butuh kolom `direction` + logic
# bidirectional baru utk direkam sbg sinyal SELL/short -- keputusan
# terbuka utk fase 2, lihat memory smart_money_scanner_audit_fix.md).
SMART_MONEY_BUY_POLA = {"Akumulasi", "Akumulasi Agresif", "Siluman (quiet buy)", "Breakout Volume"}


async def record_smart_money_signals(items: list[dict], price_lookup=None) -> list[dict]:
    """Catat entry point dari anomali volume Smart Money (_process_sm_df,
    web/app.py) sebagai source ketiga yang independen -- HANYA kategori
    akumulasi (lihat SMART_MONEY_BUY_POLA) karena signal_history/
    audit_open_signals belum mendukung arah SELL/short.

    Beda dari record_top_picks()/record_macd_cross_signals(): item di
    sini adalah hasil SCAN VOLUME (kode, pola, chg1/chg5/vol_ratio/rsi),
    BUKAN item confidence() -- caller (web/app.py) WAJIB sudah meng-
    enrich tiap item dgn potensi_naik_pct/risiko_turun_pct/likuiditas/
    confidence_score/ai_score dari hasil confidence() yang SAMA (join by
    kode), supaya TP/SL yang dicatat identik dgn yang sudah dihitung utk
    Top Pick -- BUKAN dihitung ulang terpisah.

    Kriteria PENAPISAN sama filosofinya dgn record_macd_cross_signals:
    saham likuid & TP/SL valid supaya sinyal bisa dieksekusi secara wajar.

    Dedup HANYA per source='SMART_MONEY' -- boleh mencatat kode yang sama
    di hari yang sama dgn TOP_PICK/MACD_CROSS, tiga teori entry berbeda
    yang sengaja diaudit terpisah.

    price_lookup/pattern/return: lihat docstring record_top_picks(), pola
    yang sama persis dipakai di sini."""
    _ensure_table()
    if _is_bursa_weekend():
        return []  # lihat _is_bursa_weekend() -- jangan catat sinyal "baru" dgn harga basi
    candidates = [
        it for it in items
        if it.get("pola") in SMART_MONEY_BUY_POLA
        and it.get("likuiditas") in ("Sangat Likuid", "Likuid")
        and it.get("potensi_naik_pct") is not None
        and it.get("risiko_turun_pct") is not None
        and it.get("risiko_turun_pct") > 0
        and it.get("harga")
    ][:SMART_MONEY_MAX_PER_DAY]

    if not candidates:
        return []

    saved = []
    for it in candidates:
        with get_db() as conn:
            already = conn.execute('''
                SELECT 1 FROM signal_history
                WHERE kode = ? AND date(recorded_at) = date('now', 'localtime') AND source = 'SMART_MONEY'
                LIMIT 1
            ''', (it["kode"],)).fetchone()
        if already:
            continue

        entry_price = it["harga"]
        if price_lookup is not None:
            try:
                live_price = await price_lookup(it["kode"])
                if live_price:
                    entry_price = live_price
            except Exception:
                pass  # fail-open: tetap pakai closing harian, jangan gagalkan pencatatan

        tp_pct, sl_pct = it["potensi_naik_pct"], it["risiko_turun_pct"]
        pattern = it.get("pola")
        with get_db() as conn:
            cur = conn.execute('''
                INSERT OR IGNORE INTO signal_history
                    (kode, entry_price, tp_pct, sl_pct, confidence_score, ai_score, recommendation, pattern, source, recorded_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'SMART_MONEY', datetime('now', 'localtime'))
            ''', (
                it["kode"], entry_price, tp_pct, sl_pct,
                it.get("confidence_score"), it.get("ai_score"), it.get("ai_rating"), pattern,
            ))
            # Lihat catatan sama di record_top_picks(): OR IGNORE + index
            # unique adalah pengaman ATOMIC terakhir terhadap race antara
            # SELECT dedup di atas dan INSERT ini.
            if cur.rowcount == 0:
                continue
            new_id = cur.lastrowid
        saved.append({
            "id": new_id, "kode": it["kode"], "entry_price": entry_price,
            "tp_pct": tp_pct, "sl_pct": sl_pct,
            "tp_price": round(entry_price * (1 + tp_pct / 100), 2),
            "sl_price": round(entry_price * (1 - sl_pct / 100), 2),
            "confidence_score": it.get("confidence_score"), "pattern": pattern,
            "source": "SMART_MONEY",
        })
    return saved


async def audit_open_signals(price_lookup) -> list[dict]:
    """Cek ulang semua sinyal berstatus OPEN terhadap harga TERKINI.

    price_lookup: async callable(kode: str) -> float | None -- caller (web/
    app.py) yang menyediakan cara ambil harga (REUSE _clean/harga close
    terakhir yang sudah ada, supaya modul ini TIDAK melakukan I/O jaringan
    sendiri dan tetap mudah ditest tanpa mock network).

    Status akhir:
    - TP_HIT: harga >= entry x (1 + tp_pct/100)
    - SL_HIT: harga <= entry x (1 - sl_pct/100)
    - EXPIRED: belum kena TP/SL tapi sudah lewat MAX_HOLD_DAYS sejak dicatat
    - OPEN: belum satupun kondisi di atas terpenuhi, tetap dibiarkan terbuka

    Returns LIST sinyal yang BARU SAJA berpindah status di pemanggilan ini
    (bukan sinyal yang sudah lama closed) -- caller pakai ini utk kirim
    notifikasi Telegram cuma sekali per sinyal, persis saat statusnya
    berubah, bukan berulang setiap audit berikutnya."""
    _ensure_table()
    with get_db() as conn:
        open_rows = conn.execute(
            "SELECT id, kode, recorded_at, entry_price, tp_pct, sl_pct, source, pattern "
            "FROM signal_history WHERE status = 'OPEN'"
        ).fetchall()

    just_resolved = []
    for row in open_rows:
        price = await price_lookup(row["kode"])
        if price is None or price <= 0:
            continue

        entry = row["entry_price"]
        tp_price = entry * (1 + row["tp_pct"] / 100)
        sl_price = entry * (1 - row["sl_pct"] / 100)
        recorded_at = datetime.fromisoformat(row["recorded_at"])
        age_days = (datetime.now() - recorded_at).days

        status, return_pct = None, None
        if price >= tp_price:
            status, return_pct = "TP_HIT", row["tp_pct"]
        elif price <= sl_price:
            status, return_pct = "SL_HIT", -row["sl_pct"]
        elif age_days >= MAX_HOLD_DAYS:
            status, return_pct = "EXPIRED", round((price / entry - 1) * 100, 2)

        if status is None:
            continue  # tetap OPEN, tidak ada perubahan

        with get_db() as conn:
            conn.execute('''
                UPDATE signal_history
                SET status = ?, resolved_at = datetime('now', 'localtime'), resolved_price = ?,
                    return_pct = ?, days_to_resolve = ?
                WHERE id = ?
            ''', (status, price, return_pct, age_days, row["id"]))

        just_resolved.append({
            "id": row["id"], "kode": row["kode"], "entry_price": entry,
            "status": status, "resolved_price": price, "return_pct": return_pct,
            "days_to_resolve": age_days, "recorded_at": row["recorded_at"],
            "source": row["source"], "pattern": row["pattern"],
        })

    return just_resolved


def _compute_stats(closed: list[dict]) -> dict | None:
    """Statistik agregat dari sinyal yang SUDAH SELESAI (TP_HIT/SL_HIT/
    EXPIRED). Returns None kalau daftar kosong -- caller/frontend WAJIB
    menampilkan ini sebagai "belum cukup data", BUKAN 0% (dipakai baik
    untuk statistik gabungan maupun per-source di get_signal_report)."""
    if not closed:
        return None
    wins = [s for s in closed if s["status"] == "TP_HIT"]
    losses = [s for s in closed if s["status"] == "SL_HIT"]
    decided = wins + losses  # EXPIRED sengaja di luar win-rate (bukan menang atau kalah jelas)
    win_rate = round(len(wins) / len(decided) * 100, 1) if decided else None
    avg_return = round(sum(s["return_pct"] for s in closed) / len(closed), 2)
    avg_days = round(sum(s["days_to_resolve"] for s in closed) / len(closed), 1)
    return {
        "n_closed": len(closed),
        "n_tp_hit": len(wins),
        "n_sl_hit": len(losses),
        "n_expired": len(closed) - len(wins) - len(losses),
        "win_rate": win_rate,
        "avg_return_pct": avg_return,
        "avg_days_to_resolve": avg_days,
    }


def get_signal_report() -> dict:
    """Ringkasan lengkap: daftar sinyal (terbaru dulu) + statistik agregat
    yang HANYA dihitung dari sinyal yang SUDAH SELESAI (TP_HIT/SL_HIT/
    EXPIRED) -- sinyal OPEN sengaja tidak ikut dihitung ke win rate karena
    belum ada hasil sungguhan (menganggapnya menang/kalah sekarang = angka
    bohong).

    Returns dict dengan 'signals' (list), 'stats' (gabungan semua source,
    bisa None kalau belum ada satupun sinyal yang selesai), dan
    'stats_by_source' (dict {source: stats-shape yang sama}, HANYA berisi
    source yang sudah punya minimal 1 sinyal selesai) -- supaya user bisa
    bandingkan validitas Top Pick vs MACD Cross sebagai teori entry
    terpisah, bukan tercampur jadi satu angka."""
    _ensure_table()
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM signal_history ORDER BY recorded_at DESC LIMIT 200"
        ).fetchall()

    signals = [dict(r) for r in rows]
    # Harga TP/SL eksplisit (Rupiah) -- dihitung dari entry_price x tp_pct/
    # sl_pct yang SAMA PERSIS dipakai audit_open_signals(), bukan angka
    # baru. Ditambahkan di sini (bukan disimpan di kolom terpisah) supaya
    # SATU sumber kebenaran: kalau formulanya berubah, tidak ada risiko
    # nilai tersimpan jadi basi/tidak sinkron dengan logic audit.
    for s in signals:
        s["tp_price"] = round(s["entry_price"] * (1 + s["tp_pct"] / 100), 2)
        s["sl_price"] = round(s["entry_price"] * (1 - s["sl_pct"] / 100), 2)

    closed = [s for s in signals if s["status"] in ("TP_HIT", "SL_HIT", "EXPIRED")]
    stats = _compute_stats(closed)
    stats_by_source = {}
    for source in sorted({s["source"] for s in closed}):
        source_stats = _compute_stats([s for s in closed if s["source"] == source])
        if source_stats is not None:
            stats_by_source[source] = source_stats

    n_open = sum(1 for s in signals if s["status"] == "OPEN")
    return {
        "signals": signals, "stats": stats, "stats_by_source": stats_by_source,
        "n_open": n_open, "n_total": len(signals),
    }
