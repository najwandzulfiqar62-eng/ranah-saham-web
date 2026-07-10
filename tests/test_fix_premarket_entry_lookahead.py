# Test utk scripts/fix_premarket_entry_lookahead.py -- backfill KOREKSI
# SATU KALI (bukan migrasi permanen) yang memperbaiki bug lookahead nyata:
# scripts/backfill_pending_entry.py memotong histori harga pakai
# `date <= recorded_date` SAJA, tanpa peduli JAM -- utk sinyal yang
# direkam SEBELUM bursa buka (mis. 02:43 WIB), itu tetap MENYERTAKAN bar
# HARI ITU SENDIRI yang closing-nya baru terbentuk jam 16:00 WIB, JAM-JAM
# SETELAH sinyal direkam. Permintaan user langsung: "elsa ama pgeo aja
# kmrn harusnya hari ini udah profit bukan kena sl" -- ditemukan lewat
# investigasi PGEO memang seharusnya profit (skenario benar: pullback,
# bukan breakout), tapi ELSA JUJURNYA malah tidak pernah kena entry sama
# sekali (bukan profit, bukan rugi) setelah dihitung ulang tanpa lookahead.
from datetime import date, datetime

import pandas as pd

from scripts.fix_premarket_entry_lookahead import (
    _correct_as_of_cutoff,
    _fetch_affected_rows,
    _recompute_row,
    apply_updates,
    MARKET_OPEN_HOUR,
)


def _fake_df(dates, lows, highs, closes):
    return pd.DataFrame(
        {"Open": closes, "High": highs, "Low": lows, "Close": closes,
         "Volume": [1_000_000] * len(dates)},
        index=pd.DatetimeIndex(dates),
    )


def test_correct_as_of_cutoff_excludes_same_day_when_recorded_premarket():
    """Regresi UTAMA -- INTI bug: recorded_at JAM 02:43 (sebelum
    MARKET_OPEN_HOUR) pada tanggal D -- bar tanggal D SENDIRI belum ada
    sama sekali saat itu, cutoff HARUS mundur ke D-1."""
    dates = pd.bdate_range(end="2026-07-10", periods=3)  # 2026-07-08, 09, 10
    df = _fake_df(dates, lows=[100, 100, 999], highs=[110, 110, 999], closes=[105, 105, 999])
    recorded_at = datetime(2026, 7, 10, 2, 43, 33)
    assert recorded_at.hour < MARKET_OPEN_HOUR

    truncated = _correct_as_of_cutoff(df, recorded_at)

    assert truncated.index[-1].date() == date(2026, 7, 9), "bar 2026-07-10 (999) TIDAK BOLEH ikut -- belum ada saat direkam"
    assert 999 not in truncated["Close"].values


def test_correct_as_of_cutoff_includes_same_day_when_recorded_during_market_hours():
    """Kontrol: kalau recorded_at SUDAH dalam jam bursa (mis. 11:05), bar
    hari itu SUDAH mulai terbentuk -- boleh tetap dipakai (SAMA perilaku
    lama _as_of(), tidak berubah utk kasus ini)."""
    dates = pd.bdate_range(end="2026-07-09", periods=2)
    df = _fake_df(dates, lows=[100, 472], highs=[110, 505], closes=[105, 492])
    recorded_at = datetime(2026, 7, 9, 11, 5, 43)
    assert recorded_at.hour >= MARKET_OPEN_HOUR

    truncated = _correct_as_of_cutoff(df, recorded_at)

    assert truncated.index[-1].date() == date(2026, 7, 9)
    assert 492 in truncated["Close"].values


def test_recompute_row_picks_pullback_not_breakout_when_lookahead_removed():
    """Regresi (PGEO/ELSA live): tanpa data hari-D yang belum ada saat
    direkam, skenario yang benar adalah 'pullback' -- BUKAN 'breakout'
    yang SEBELUMNYA salah terpilih krn rally hari-D (yang belum terjadi
    saat sinyal direkam) membuatnya kelihatan seolah sudah breakout."""
    import core.trading_plan as tp_module

    dates = pd.bdate_range(end="2026-07-10", periods=60)
    # 59 bar tenang @1000, bar TERAKHIR (2026-07-10, BELUM ada saat
    # direkam 02:43) rally jauh -- kalau lookahead bocor, ini akan
    # membuat breakout kelihatan sudah terjadi.
    closes = [1000.0] * 59 + [1100.0]
    highs = [1010.0] * 59 + [1150.0]
    lows = [990.0] * 59 + [1080.0]
    df = _fake_df(dates, lows, highs, closes)
    row = {"id": 1, "kode": "ZZLOOKAHEAD", "recorded_at": "2026-07-10 02:43:33",
           "entry_price": 1073.0, "tp_pct": 5, "tp2_pct": 10, "tp3_pct": 15, "sl_pct": 5, "status": "OPEN"}

    result = _recompute_row(row, df)

    assert result["action"] == "recompute"
    assert result["corrected_row"]["entry_price"] < 1000.0, "pullback dari data tenang (sebelum rally) HARUS di bawah 1000, bukan breakout di atas rally"


def test_fetch_affected_rows_excludes_genuinely_resolved_history(clean_signal_db):
    """Regresi KESELAMATAN UTAMA (near-miss ditemukan lewat dry-run
    sendiri sebelum apply, kasus ARTO nyata): baris yang SUDAH resolved
    lewat jalur audit_open_signals() SUNGGUHAN (entry_filled_at NULL,
    resolved_at BUKAN stempel '16:00:00' skrip ini) TIDAK BOLEH pernah
    ikut ke-fetch, meski recorded_at-nya kebetulan pre-market juga --
    kalau ini gagal, skrip akan menulis ulang track record asli."""
    from core.database import get_db

    with get_db() as conn:
        # Baris ASLI, resolved organik jam bursa sungguhan -- HARUS DIABAIKAN.
        conn.execute('''
            INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, status, source, direction,
                recorded_at, resolved_at, resolved_price, return_pct)
            VALUES ('ZZORGANIC', 907, 5, 5, 'TP_HIT', 'TOP_PICK', 'BUY',
                '2026-07-08 00:01:02', '2026-07-08 13:49:26', 1020, 9.4)
        ''')
        # Baris tercemar skrip backfill/replay HARI INI -- HARUS ikut.
        conn.execute('''
            INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, status, source, direction,
                recorded_at, entry_filled_at)
            VALUES ('ZZTAINTED', 490, 4, 4, 'OPEN', 'TOP_PICK', 'BUY',
                '2026-07-09 11:05:43', '2026-07-09 16:00:00')
        ''')
        # Baris masih PENDING_ENTRY murni, direkam pre-market baru2 ini -- HARUS ikut.
        conn.execute('''
            INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, status, source, direction, recorded_at)
            VALUES ('ZZSTILLPENDING', 1000, 4, 4, 'PENDING_ENTRY', 'TOP_PICK', 'BUY', '2026-07-10 02:43:33')
        ''')

    rows = _fetch_affected_rows()
    kodes = {r["kode"] for r in rows}

    assert "ZZORGANIC" not in kodes, "baris resolved SUNGGUHAN tidak boleh pernah tersentuh -- melindungi track record asli"
    assert "ZZTAINTED" in kodes
    assert "ZZSTILLPENDING" in kodes


def test_apply_updates_resets_before_reapplying_replay_result(clean_signal_db):
    """Regresi: apply_updates() HARUS reset penuh (entry/tp/sl BARU,
    status/entry_filled_at/resolved_at/dst dikosongkan) SEBELUM menerapkan
    hasil replay -- bukan menumpuk di atas state lama yang sudah salah."""
    from core.database import get_db

    with get_db() as conn:
        cur = conn.execute('''
            INSERT INTO signal_history (kode, entry_price, tp_pct, tp2_pct, tp3_pct, sl_pct, status,
                source, direction, recorded_at, entry_filled_at, resolved_at, resolved_price, return_pct, tp_level_hit)
            VALUES ('ZZRESET', 1027, 7.3, 14.5, 21.8, 7.3, 'SL_HIT', 'TOP_PICK', 'BUY',
                '2026-07-10 02:43:33', '2026-07-10 16:00:00', '2026-07-10 16:00:00', 952.0, -7.3, 0)
        ''')
        row_id = cur.lastrowid

    recomputed = [{"id": row_id, "kode": "ZZRESET", "action": "recompute",
                   "corrected_row": {"entry_price": 945.0, "tp_pct": 3.5, "tp2_pct": 7.0, "tp3_pct": 10.5, "sl_pct": 3.5}}]
    replayed = [{"id": row_id, "kode": "ZZRESET", "action": "fill_and_open",
                 "fill_date": date(2026, 7, 10), "tp_level_hit": 2}]

    n = apply_updates(recomputed, replayed)
    assert n == 1

    with get_db() as conn:
        row = conn.execute(
            "SELECT entry_price, tp_pct, sl_pct, status, entry_filled_at, resolved_at, resolved_price, return_pct, tp_level_hit "
            "FROM signal_history WHERE id = ?", (row_id,)
        ).fetchone()

    assert row["entry_price"] == 945.0
    assert row["status"] == "OPEN"
    assert row["entry_filled_at"] == "2026-07-10 16:00:00"
    assert row["resolved_at"] is None, "SL_HIT lama harus benar2 dikosongkan, bukan tetap nempel"
    assert row["resolved_price"] is None
    assert row["return_pct"] is None
    assert row["tp_level_hit"] == 2
