# Test utk scripts/replay_pending_entry_progress.py -- backfill KOREKSI
# SATU KALI (bukan migrasi permanen) yang mereplay STATUS sebenarnya utk
# baris PENDING_ENTRY yang entry_price-nya baru saja dikoreksi (lihat
# scripts/backfill_pending_entry.py) tapi statusnya belum ikut disesuaikan.
# Permintaan user langsung, live: "itu kan sinyal tanggal 9 harusnya udah
# kena tp dong nah nyesuain nya ama yg kmrn bukan hari ini soalnya itu
# sinyal tanggal 9" (BRMS masih 'Menunggu Entry' padahal replay histori
# harga sungguhan menunjukkan entry-nya sudah kena tanggal 9 dan tp1
# tercapai tanggal 10).
from datetime import date, datetime, timedelta

import pandas as pd

from scripts.replay_pending_entry_progress import (
    _replay_row,
    _fetch_pending_entry_rows,
    apply_updates,
)


def _fake_df(dates, lows, highs, closes):
    return pd.DataFrame(
        {"Open": closes, "High": highs, "Low": lows, "Close": closes},
        index=pd.DatetimeIndex(dates),
    )


def _row(entry_price=490.0, tp_pct=4.4, tp2_pct=8.8, tp3_pct=13.2, sl_pct=4.4,
         recorded_at="2026-07-09 11:05:43", kode="ZZREPLAY", row_id=1):
    return {"id": row_id, "kode": kode, "recorded_at": recorded_at,
            "entry_price": entry_price, "tp_pct": tp_pct, "tp2_pct": tp2_pct,
            "tp3_pct": tp3_pct, "sl_pct": sl_pct}


def test_replay_row_fills_same_day_and_still_open_next_day():
    """Regresi UTAMA (BRMS live persis): entry di bawah Low HARI DICATAT
    sendiri -> kena hari itu juga (entry_filled_at = recorded_date),
    lanjut TP1 tercapai hari berikutnya (High >= tp1) tapi belum TP3 --
    hasil akhir 'fill_and_open' (status OPEN, tp_level_hit=1), BUKAN tetap
    PENDING_ENTRY."""
    dates = pd.bdate_range(start="2026-07-09", periods=2)
    df = _fake_df(dates, lows=[472.0, 494.0], highs=[505.0, 520.0], closes=[492.0, 505.0])
    row = _row()

    result = _replay_row(row, df, today=date(2026, 7, 10))

    assert result["action"] == "fill_and_open"
    assert result["fill_date"] == date(2026, 7, 9)
    assert result["tp_level_hit"] == 1


def test_replay_row_resolves_sl_hit_same_day_as_fill_on_gap_down():
    """Regresi (ELSA/PGEO live): kalau hari fill JUGA turun sampai
    menembus SL (gap-through-stop, bukan cuma menyentuh entry) -- HARUS
    langsung resolve SL_HIT hari itu juga, bukan dianggap masih OPEN."""
    dates = pd.bdate_range(start="2026-07-10", periods=1)
    # entry=667 (dari row override), Low hari itu 615 turun jauh di bawah SL juga.
    df = _fake_df(dates, lows=[615.0], highs=[660.0], closes=[655.0])
    row = _row(entry_price=667.0, tp_pct=7.1, tp2_pct=14.2, tp3_pct=21.2, sl_pct=7.1,
               recorded_at="2026-07-10 02:43:33")

    result = _replay_row(row, df, today=date(2026, 7, 10))

    assert result["action"] == "fill_and_resolve"
    assert result["new_status"] == "SL_HIT"
    assert result["fill_date"] == date(2026, 7, 10)
    assert result["resolve_date"] == date(2026, 7, 10)


def test_replay_row_resolves_tp_hit_when_final_level_reached():
    """Kontrol: kalau High suatu hari mencapai TP3 (level konfigurasi
    tertinggi), resolve TP_HIT -- bukan tp_progress terus-menerus."""
    dates = pd.bdate_range(start="2026-07-09", periods=3)
    df = _fake_df(dates,
                   lows=[472.0, 494.0, 500.0],
                   highs=[505.0, 520.0, 560.0],  # hari ke-3 tembus tp3 (555)
                   closes=[492.0, 505.0, 555.0])
    row = _row()

    result = _replay_row(row, df, today=date(2026, 7, 13))

    assert result["action"] == "fill_and_resolve"
    assert result["new_status"] == "TP_HIT"
    assert result["tp_level_hit"] == 3
    assert result["return_pct"] == 13.2  # tp3_pct


def test_replay_row_no_change_when_not_yet_filled_within_wait_window():
    """Kontrol: belum kena entry sama sekali TAPI umur < MAX_ENTRY_WAIT_DAYS
    -- tetap PENDING_ENTRY (no_change_needed), jangan dipaksa expire.

    CATATAN: umur dihitung _replay_row dari datetime.now() SUNGGUHAN (lihat
    komentar di fungsinya -- BUKAN dari param `today`), jadi recorded_at HARUS
    relatif ke sekarang. Kalau dipatok tanggal tetap, test ini basi & salah
    'expire' begitu > MAX_ENTRY_WAIT_DAYS hari kalender berlalu sejak ditulis."""
    now = datetime.now()
    recorded = now - timedelta(days=1)  # baru 1 hari -> jelas < MAX_ENTRY_WAIT_DAYS(5)
    recorded_date = recorded.date()
    df = _fake_df([pd.Timestamp(recorded_date)], lows=[700.0], highs=[720.0], closes=[710.0])  # Low tidak pernah <= entry(490)
    row = _row(recorded_at=recorded.strftime("%Y-%m-%d %H:%M:%S"))

    result = _replay_row(row, df, today=recorded_date)

    assert result["action"] == "no_change_needed"


def test_replay_row_expires_no_entry_after_max_wait_days():
    """Kontrol: belum kena entry DAN sudah lewat MAX_ENTRY_WAIT_DAYS sejak
    recorded_at -- harus expire_no_entry, bukan tetap menggantung."""
    dates = pd.bdate_range(start="2026-06-25", periods=10)
    df = _fake_df(dates, lows=[700.0] * 10, highs=[720.0] * 10, closes=[710.0] * 10)
    row = _row(recorded_at="2026-06-25 09:00:00")  # >5 hari bursa sebelum today

    result = _replay_row(row, df, today=date(2026, 7, 9))

    assert result["action"] == "expire_no_entry"


def test_replay_row_never_uses_data_before_recorded_date():
    """Regresi anti-lookahead sisi lain: data SEBELUM recorded_date (kalau
    kebetulan ikut ke-fetch krn period 1y) TIDAK BOLEH dipakai utk klaim
    fill lebih awal dari recorded_date sungguhan.

    recorded_at relatif ke datetime.now() (lihat catatan di test kontrol
    lain di atas) supaya tetap 'belum expire' kapan pun test dijalankan."""
    now = datetime.now()
    recorded = now - timedelta(days=1)  # < MAX_ENTRY_WAIT_DAYS(5) -> belum expire
    recorded_date = recorded.date()
    # 5 hari SEBELUM recorded_date + recorded_date sendiri sebagai bar TERAKHIR.
    dates = [pd.Timestamp(recorded_date) - pd.Timedelta(days=k) for k in range(5, -1, -1)]
    n_before, n_on_or_after = 5, 1
    # Hari-hari SEBELUM recorded_date turun jauh di bawah entry -- HARUS
    # diabaikan; cuma hari recorded_date (494, TIDAK menembus entry=490) yang relevan.
    lows = [400.0] * n_before + [494.0] * n_on_or_after
    highs = [420.0] * n_before + [500.0] * n_on_or_after
    closes = [410.0] * n_before + [498.0] * n_on_or_after
    df = _fake_df(dates, lows, highs, closes)
    row = _row(recorded_at=recorded.strftime("%Y-%m-%d %H:%M:%S"))

    result = _replay_row(row, df, today=recorded_date)

    assert result["action"] == "no_change_needed", "hari-hari SEBELUM recorded_date tidak boleh dianggap sbg fill"


def test_replay_row_skip_no_data_when_history_missing():
    row = _row()
    result = _replay_row(row, df=None, today=date(2026, 7, 10))
    assert result["action"] == "skip_no_data"


def test_fetch_pending_entry_rows_only_returns_pending_entry_top_pick_buy(clean_signal_db):
    from core.database import get_db

    with get_db() as conn:
        conn.execute("INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, status, source, direction) "
                     "VALUES ('ZZPENDING', 1000, 3.0, 3.0, 'PENDING_ENTRY', 'TOP_PICK', 'BUY')")
        conn.execute("INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, status, source, direction) "
                     "VALUES ('ZZOPEN', 1000, 3.0, 3.0, 'OPEN', 'TOP_PICK', 'BUY')")

    rows = _fetch_pending_entry_rows()
    kodes = {r["kode"] for r in rows}

    assert "ZZPENDING" in kodes
    assert "ZZOPEN" not in kodes


def test_apply_updates_fill_and_open_sets_status_and_entry_filled_at(clean_signal_db):
    from core.database import get_db

    with get_db() as conn:
        cur = conn.execute("INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, status, source, direction) "
                           "VALUES ('ZZFO', 490, 4.4, 4.4, 'PENDING_ENTRY', 'TOP_PICK', 'BUY')")
        row_id = cur.lastrowid

    results = [{"id": row_id, "action": "fill_and_open", "fill_date": date(2026, 7, 9), "tp_level_hit": 1}]
    n = apply_updates(results)
    assert n == 1

    with get_db() as conn:
        row = conn.execute("SELECT status, entry_filled_at, tp_level_hit FROM signal_history WHERE id = ?", (row_id,)).fetchone()
    assert row["status"] == "OPEN"
    assert row["entry_filled_at"] == "2026-07-09 16:00:00"
    assert row["tp_level_hit"] == 1


def test_apply_updates_fill_and_resolve_sets_all_resolution_fields(clean_signal_db):
    from core.database import get_db

    with get_db() as conn:
        cur = conn.execute("INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, status, source, direction) "
                           "VALUES ('ZZFR', 667, 7.1, 7.1, 'PENDING_ENTRY', 'TOP_PICK', 'BUY')")
        row_id = cur.lastrowid

    results = [{"id": row_id, "action": "fill_and_resolve", "fill_date": date(2026, 7, 10),
                "resolve_date": date(2026, 7, 10), "new_status": "SL_HIT", "return_pct": -7.1,
                "resolved_price": 619.6, "days_to_resolve": 0, "tp_level_hit": 0}]
    n = apply_updates(results)
    assert n == 1

    with get_db() as conn:
        row = conn.execute(
            "SELECT status, entry_filled_at, resolved_at, resolved_price, return_pct, days_to_resolve "
            "FROM signal_history WHERE id = ?", (row_id,)
        ).fetchone()
    assert row["status"] == "SL_HIT"
    assert row["entry_filled_at"] == "2026-07-10 16:00:00"
    assert row["resolved_at"] == "2026-07-10 16:00:00"
    assert row["resolved_price"] == 619.6
    assert row["return_pct"] == -7.1


def test_apply_updates_expire_no_entry_sets_status_and_resolved_at_only(clean_signal_db):
    from core.database import get_db

    with get_db() as conn:
        cur = conn.execute("INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, status, source, direction) "
                           "VALUES ('ZZEXP', 1000, 3.0, 3.0, 'PENDING_ENTRY', 'TOP_PICK', 'BUY')")
        row_id = cur.lastrowid

    results = [{"id": row_id, "action": "expire_no_entry", "expire_date": date(2026, 7, 9)}]
    n = apply_updates(results)
    assert n == 1

    with get_db() as conn:
        row = conn.execute(
            "SELECT status, resolved_at, resolved_price, return_pct FROM signal_history WHERE id = ?", (row_id,)
        ).fetchone()
    assert row["status"] == "EXPIRED_NO_ENTRY"
    assert row["resolved_at"] == "2026-07-09 16:00:00"
    assert row["resolved_price"] is None
    assert row["return_pct"] is None


def test_apply_updates_skips_no_change_needed_rows(clean_signal_db):
    from core.database import get_db

    with get_db() as conn:
        cur = conn.execute("INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, status, source, direction) "
                           "VALUES ('ZZNC', 1000, 3.0, 3.0, 'PENDING_ENTRY', 'TOP_PICK', 'BUY')")
        row_id = cur.lastrowid

    results = [{"id": row_id, "action": "no_change_needed"}]
    n = apply_updates(results)
    assert n == 0

    with get_db() as conn:
        row = conn.execute("SELECT status FROM signal_history WHERE id = ?", (row_id,)).fetchone()
    assert row["status"] == "PENDING_ENTRY"
