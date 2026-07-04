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
# ARSITEKTUR: TIDAK ada scheduler/cron (aplikasi ini stateless request-
# response, tidak ada proses background). Audit dijalankan ON-DEMAND --
# setiap kali /api/signals dipanggil (mis. user buka halaman "Audit
# Sinyal"), semua sinyal yang masih OPEN dicek ulang terhadap harga
# terakhir. Trade-off yang diterima sadar: status baru ter-update saat
# ada yang benar-benar membuka halaman ini, bukan real-time strict --
# untuk fitur audit historis (horison hari/minggu), ini cukup.

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
                recorded_at      TEXT NOT NULL DEFAULT (datetime('now')),
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
    _ensured = True


def record_top_picks(items: list[dict]) -> int:
    """Catat sinyal baru dari hasil /api/confidence (items sudah diurut
    confidence_score menurun). Hanya MAX_RECORDED_PER_DAY teratas yang skornya
    >= MIN_SCORE_TO_RECORD, dan SATU kode SAHAM cuma dicatat SEKALI per hari
    (dedup via tanggal) -- mencegah duplikasi kalau /api/confidence dipanggil
    berkali-kali di hari yang sama (cache 300 detik bisa expire & recompute
    beberapa kali sehari).

    Melewati saham tanpa potensi_naik_pct/risiko_turun_pct valid (mis. GOTO
    yang sedang flat di harga floor -- lihat catatan di core/charts/
    snr_chart.py) karena TP/SL tidak bisa didefinisikan dengan wajar.

    Returns jumlah sinyal baru yang benar-benar disimpan."""
    _ensure_table()
    candidates = [
        it for it in items
        if it.get("confidence_score", 0) >= MIN_SCORE_TO_RECORD
        and it.get("potensi_naik_pct") is not None
        and it.get("risiko_turun_pct") is not None
        and it.get("risiko_turun_pct") > 0
        and it.get("harga")
    ][:MAX_RECORDED_PER_DAY]

    if not candidates:
        return 0

    saved = 0
    with get_db() as conn:
        for it in candidates:
            already = conn.execute('''
                SELECT 1 FROM signal_history
                WHERE kode = ? AND date(recorded_at) = date('now')
                LIMIT 1
            ''', (it["kode"],)).fetchone()
            if already:
                continue
            conn.execute('''
                INSERT INTO signal_history
                    (kode, entry_price, tp_pct, sl_pct, confidence_score, ai_score, recommendation)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                it["kode"], it["harga"], it["potensi_naik_pct"], it["risiko_turun_pct"],
                it.get("confidence_score"), it.get("ai_score"), it.get("ai_rating"),
            ))
            saved += 1
    return saved


async def audit_open_signals(price_lookup) -> None:
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
    """
    _ensure_table()
    with get_db() as conn:
        open_rows = conn.execute(
            "SELECT id, kode, recorded_at, entry_price, tp_pct, sl_pct FROM signal_history WHERE status = 'OPEN'"
        ).fetchall()

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
                SET status = ?, resolved_at = datetime('now'), resolved_price = ?,
                    return_pct = ?, days_to_resolve = ?
                WHERE id = ?
            ''', (status, price, return_pct, age_days, row["id"]))


def get_signal_report() -> dict:
    """Ringkasan lengkap: daftar sinyal (terbaru dulu) + statistik agregat
    yang HANYA dihitung dari sinyal yang SUDAH SELESAI (TP_HIT/SL_HIT/
    EXPIRED) -- sinyal OPEN sengaja tidak ikut dihitung ke win rate karena
    belum ada hasil sungguhan (menganggapnya menang/kalah sekarang = angka
    bohong).

    Returns dict dengan 'signals' (list) dan 'stats' (bisa None kalau
    belum ada satupun sinyal yang selesai -- caller/frontend WAJIB
    menampilkan ini sebagai "belum cukup data", BUKAN 0%)."""
    _ensure_table()
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM signal_history ORDER BY recorded_at DESC LIMIT 200"
        ).fetchall()

    signals = [dict(r) for r in rows]

    closed = [s for s in signals if s["status"] in ("TP_HIT", "SL_HIT", "EXPIRED")]
    if not closed:
        stats = None
    else:
        wins = [s for s in closed if s["status"] == "TP_HIT"]
        losses = [s for s in closed if s["status"] == "SL_HIT"]
        decided = wins + losses  # EXPIRED sengaja di luar win-rate (bukan menang atau kalah jelas)
        win_rate = round(len(wins) / len(decided) * 100, 1) if decided else None
        avg_return = round(sum(s["return_pct"] for s in closed) / len(closed), 2)
        avg_days = round(sum(s["days_to_resolve"] for s in closed) / len(closed), 1)
        stats = {
            "n_closed": len(closed),
            "n_tp_hit": len(wins),
            "n_sl_hit": len(losses),
            "n_expired": len(closed) - len(wins) - len(losses),
            "win_rate": win_rate,
            "avg_return_pct": avg_return,
            "avg_days_to_resolve": avg_days,
        }

    n_open = sum(1 for s in signals if s["status"] == "OPEN")
    return {"signals": signals, "stats": stats, "n_open": n_open, "n_total": len(signals)}
