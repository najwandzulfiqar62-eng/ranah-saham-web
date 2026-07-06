# Test utk scripts/backfill_open_sl_tp.py -- backfill KOREKSI SATU KALI
# (bukan migrasi permanen) yang memperlebar SL/TP sinyal OPEN kalau
# support asli (S1..S4, setelah core/trading_plan.py::_calc_entry_levels
# diperbaiki utk turun ke support lebih dalam kalau S1 kedeketan) ternyata
# lebih lebar dari floor MIN_SL_PCT yang tersimpan. Lihat docstring modul
# itu utk alasan lengkap (permintaan user langsung: "sl nya kedeketan,
# kalo bisa sl nya di support").
import pandas as pd
import pytest

from scripts.backfill_open_sl_tp import _evaluate_row, _fetch_open_rows, apply_updates


def _fake_df(dates, lows, highs, closes):
    return pd.DataFrame(
        {"Open": closes, "High": highs, "Low": lows, "Close": closes,
         "Volume": [1_000_000] * len(dates)},
        index=pd.DatetimeIndex(dates),
    )


def _fake_scenarios():
    """chosen["entry"] utk 'normal' SENGAJA dibuat sama dgn entry_price yg
    dipakai baris test di bawah (1885.0), supaya confidence check (cocokkan
    entry, bukan persentase lama) lolos."""
    return {
        "normal": {"key": "normal", "entry": 1885.0, "sl": 1785.0, "risk_pct": 5.3,
                   "tp1_pct": 5.3, "tp2_pct": 10.6, "tp3_pct": 15.9},
        "pullback": {"key": "pullback", "entry": 1800.0, "sl": 1700.0, "risk_pct": 5.6,
                     "tp1_pct": 5.6, "tp2_pct": 11.2, "tp3_pct": 16.8},
        "deep": {"key": "deep", "entry": 1750.0, "sl": 1650.0, "risk_pct": 5.7,
                 "tp1_pct": 5.7, "tp2_pct": 11.4, "tp3_pct": 17.1},
        "breakout": {"key": "breakout", "entry": 1950.0, "sl": 1850.0, "risk_pct": 5.1,
                     "tp1_pct": 5.1, "tp2_pct": 10.2, "tp3_pct": 15.3},
    }


@pytest.fixture
def patch_scenarios(monkeypatch):
    """Monkeypatch fungsi core/trading_plan.py yang dipakai script backfill
    supaya skenarionya SEPENUHNYA terkontrol -- fokus test ini pada LOGIC
    backfill-nya sendiri, bukan pada kalkulasi ATR/S&R sungguhan."""
    import scripts.backfill_open_sl_tp as mod

    def fake_calc(df, created_date_str):
        return {"scenarios": _fake_scenarios()}

    def fake_hit(scenarios, low, high):
        return [{"key": "normal", "scenario": scenarios["normal"], "entry_price": 1885.0}]

    monkeypatch.setattr(mod, "calculate_fixed_entry_levels_from_df", fake_calc)
    import scripts.backfill_open_entry_price as entry_mod
    monkeypatch.setattr(entry_mod, "get_hit_scenarios", fake_hit)
    return mod


def _row(entry_price, tp_pct, sl_pct, recorded_at="2026-07-06 14:41:05", kode="ZZSLBACK", row_id=1):
    return {"id": row_id, "kode": kode, "recorded_at": recorded_at,
            "entry_price": entry_price, "tp_pct": tp_pct, "sl_pct": sl_pct,
            "tp2_pct": tp_pct * 2, "tp3_pct": tp_pct * 3}


def _df_60d():
    return _fake_df(
        pd.bdate_range(end="2026-07-06", periods=60),
        lows=[1800] * 60, highs=[1950] * 60, closes=[1885] * 60,
    )


def test_evaluate_row_widens_sl_when_real_support_is_wider(patch_scenarios):
    """Regresi UTAMA (permintaan user: 'sl nya kedeketan, kalo bisa sl nya
    di support'): entry_price tersimpan COCOK dgn skenario 'normal' yang
    direkonstruksi, dan risk_pct barunya (5.3%, dari support asli) lebih
    lebar dari yang tersimpan (3.1%) -- HARUS diperlebar."""
    row = _row(entry_price=1885.0, tp_pct=3.1, sl_pct=3.1)
    result = _evaluate_row(row, _df_60d())

    assert result["action"] == "update"
    assert result["new_sl_pct"] == 5.3
    assert result["new_tp_pct"] == 5.3
    assert result["new_tp2_pct"] == 10.6
    assert result["new_tp3_pct"] == 15.9


def test_evaluate_row_no_change_needed_when_not_wider(patch_scenarios):
    """Kontrol: kalau risk_pct hasil rekonstruksi TIDAK lebih lebar dari
    yang tersimpan (mis. sudah sama-sama lebar/lebih lebar), JANGAN
    diubah -- backfill ini HANYA memperlebar, tidak pernah mempersempit."""
    row = _row(entry_price=1885.0, tp_pct=6.0, sl_pct=6.0)  # sudah lebih lebar dari 5.3% skenario
    result = _evaluate_row(row, _df_60d())

    assert result["action"] == "no_change_needed"


def test_evaluate_row_skip_low_confidence_when_entry_does_not_match_any_scenario(patch_scenarios):
    """Regresi: verifikasi skenario di sini mencocokkan ENTRY (bukan
    persentase lama, krn itu yang mau dikoreksi) -- kalau entry_price
    tersimpan tidak cocok skenario manapun (kemungkinan direkam dgn logic
    yg beda sama sekali), JANGAN ditebak, lewati sbg low-confidence."""
    row = _row(entry_price=2500.0, tp_pct=3.1, sl_pct=3.1)  # jauh dari entry skenario manapun (1750-1950)
    result = _evaluate_row(row, _df_60d())

    assert result["action"] == "skip_low_confidence"


def test_evaluate_row_skip_no_data_when_history_missing(patch_scenarios):
    row = _row(entry_price=1885.0, tp_pct=3.1, sl_pct=3.1)
    result = _evaluate_row(row, df=None)
    assert result["action"] == "skip_no_data"


def test_fetch_open_rows_only_returns_open_top_pick_smart_money_buy(clean_signal_db):
    """Regresi SCOPE-SAFETY (sama seperti backfill entry_price): HANYA
    status='OPEN' AND source IN ('TOP_PICK','SMART_MONEY') AND
    direction='BUY' -- baris resolved/SELL/source lain tidak boleh
    tersentuh backfill ini."""
    from core.database import get_db

    with get_db() as conn:
        conn.execute("INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, status, source, direction) "
                     "VALUES ('ZZSLOPEN', 1000, 3.0, 3.0, 'OPEN', 'TOP_PICK', 'BUY')")
        conn.execute("INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, status, source, direction, "
                     "resolved_at, resolved_price, return_pct, days_to_resolve) "
                     "VALUES ('ZZSLCLOSED', 1000, 3.0, 3.0, 'SL_HIT', 'TOP_PICK', 'BUY', datetime('now'), 970, -3.0, 2)")

    rows = _fetch_open_rows()
    kodes = {r["kode"] for r in rows}

    assert "ZZSLOPEN" in kodes
    assert "ZZSLCLOSED" not in kodes, "baris resolved TIDAK BOLEH pernah masuk -- sl_pct-nya sudah final"


def test_apply_updates_only_touches_sl_tp_columns_of_update_rows(clean_signal_db):
    """Regresi: apply_updates() HANYA menulis sl_pct/tp_pct/tp2_pct/
    tp3_pct, dan HANYA utk baris ber-action 'update' -- entry_price/status
    TIDAK PERNAH ikut berubah."""
    from core.database import get_db

    with get_db() as conn:
        cur1 = conn.execute("INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, status, source, direction) "
                            "VALUES ('ZZSLUPD', 1885, 3.1, 3.1, 'OPEN', 'TOP_PICK', 'BUY')")
        id_upd = cur1.lastrowid
        cur2 = conn.execute("INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, status, source, direction) "
                            "VALUES ('ZZSLSKIP', 2500, 3.1, 3.1, 'OPEN', 'TOP_PICK', 'BUY')")
        id_skip = cur2.lastrowid

    results = [
        {"id": id_upd, "kode": "ZZSLUPD", "action": "update", "new_sl_pct": 5.3,
         "new_tp_pct": 5.3, "new_tp2_pct": 10.6, "new_tp3_pct": 15.9,
         "entry_price": 1885.0, "sl_pct": 3.1, "tp_pct": 3.1, "recorded_at": "2026-07-06 00:00:00", "detail": ""},
        {"id": id_skip, "kode": "ZZSLSKIP", "action": "skip_low_confidence", "new_sl_pct": 5.3,
         "entry_price": 2500.0, "sl_pct": 3.1, "tp_pct": 3.1, "recorded_at": "2026-07-06 00:00:00", "detail": ""},
    ]

    n = apply_updates(results)
    assert n == 1

    with get_db() as conn:
        upd_row = conn.execute("SELECT entry_price, sl_pct, tp_pct, tp2_pct, tp3_pct FROM signal_history WHERE id = ?", (id_upd,)).fetchone()
        skip_row = conn.execute("SELECT sl_pct FROM signal_history WHERE id = ?", (id_skip,)).fetchone()

    assert upd_row["entry_price"] == 1885.0, "entry_price TIDAK BOLEH berubah"
    assert upd_row["sl_pct"] == 5.3 and upd_row["tp_pct"] == 5.3
    assert upd_row["tp2_pct"] == 10.6 and upd_row["tp3_pct"] == 15.9
    assert skip_row["sl_pct"] == 3.1, "baris skip_low_confidence TIDAK BOLEH ter-UPDATE"


def test_run_dry_run_makes_no_db_writes(clean_signal_db, patch_scenarios, monkeypatch):
    """Regresi: mode dry-run (default) TIDAK BOLEH menulis apa pun ke
    database, bahkan kalau ada baris yang seharusnya diperlebar."""
    import asyncio

    import scripts.backfill_open_sl_tp as mod
    from core.database import get_db

    with get_db() as conn:
        cur = conn.execute("INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, status, source, direction, recorded_at) "
                           "VALUES ('ZZSLDRYRUN', 1885, 3.1, 3.1, 'OPEN', 'TOP_PICK', 'BUY', '2026-07-06 14:41:05')")
        row_id = cur.lastrowid

    async def fake_fetch_history(kodes):
        return {"ZZSLDRYRUN": _df_60d()}

    monkeypatch.setattr(mod, "_fetch_history", fake_fetch_history)

    results = asyncio.run(mod.run(apply=False))
    assert any(r["action"] == "update" for r in results), "test ini butuh setidaknya 1 baris yang SEHARUSNYA diperlebar"

    with get_db() as conn:
        row = conn.execute("SELECT sl_pct FROM signal_history WHERE id = ?", (row_id,)).fetchone()
    assert row["sl_pct"] == 3.1, "dry-run TIDAK BOLEH menulis apa pun ke database"
