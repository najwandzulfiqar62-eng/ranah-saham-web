# Test utk scripts/backfill_pending_entry.py -- backfill KOREKSI SATU KALI
# (bukan migrasi permanen) yang mengoreksi entry_price/tp_pct/tp2_pct/
# tp3_pct/sl_pct sinyal PENDING_ENTRY yang SUDAH kadung tercatat pakai
# formula pullback LAMA (S1 pivot -> MA20 -> 1x ATR) ke formula BARU
# (diskon kecil, lihat core/trading_plan.py::PULLBACK_DISCOUNT_PCT).
# Permintaan user langsung setelah lihat data nyata (BRMS entry Rp478
# padahal harga sudah lari ke Rp505, TP1 cuma Rp500 -- sudah kelewatan
# sebelum entry sempat kena): "koreksi ke harga pada hari itu dengan
# logika entry skrg biar keliatan profitnya pada hari ini".
import pandas as pd
import pytest

from scripts.backfill_pending_entry import (
    _evaluate_row,
    _fetch_pending_entry_rows,
    apply_updates,
)


def _fake_df(dates, lows, highs, closes):
    return pd.DataFrame(
        {"Open": closes, "High": highs, "Low": lows, "Close": closes,
         "Volume": [1_000_000] * len(dates)},
        index=pd.DatetimeIndex(dates),
    )


def _fake_scenarios(recommended="pullback"):
    """Skenario sintetis terkontrol -- SAMA pola dgn test_backfill_
    entry_price.py, tapi tambah 'recommended' supaya bisa mensimulasikan
    kasus recommended_scenario='breakout' (mis. ELSA/PGEO live)."""
    return {
        "scenarios": {
            "normal": {"key": "normal", "entry": 4130.0, "sl": 4004.0, "risk_pct": 3.1,
                       "tp1_pct": 3.1, "tp2_pct": 6.2, "tp3_pct": 9.3},
            "pullback": {"key": "pullback", "entry": 4109.0, "sl": 3980.0, "risk_pct": 3.6,
                         "tp1_pct": 3.6, "tp2_pct": 7.2, "tp3_pct": 10.8},
            "deep": {"key": "deep", "entry": 3800.0, "sl": 3650.0, "risk_pct": 3.9,
                     "tp1_pct": 3.9, "tp2_pct": 7.8, "tp3_pct": 11.7},
            "breakout": {"key": "breakout", "entry": 4300.0, "sl": 4150.0, "risk_pct": 3.5,
                         "tp1_pct": 3.5, "tp2_pct": 7.0, "tp3_pct": 10.5},
        },
        "recommended_scenario": recommended,
    }


@pytest.fixture
def patch_scenarios(monkeypatch):
    """Monkeypatch calculate_fixed_entry_levels_from_df supaya skenarionya
    SEPENUHNYA terkontrol (tidak bergantung ATR/S&R sungguhan dari df
    sintetis) -- fokus test ini pada LOGIC backfill (as-of truncation,
    threshold no-change, PENDING_ENTRY-only scope, pilih recommended_
    scenario), bukan core/trading_plan.py (ditest terpisah)."""
    import scripts.backfill_pending_entry as mod

    def fake_calc(df, created_date_str):
        # recommended='breakout' HANYA kalau bar terakhir df closes > 4200
        # (dipakai test khusus di bawah utk simulasi ELSA/PGEO-style).
        last_close = float(df["Close"].iloc[-1])
        recommended = "breakout" if last_close > 4200 else "pullback"
        return _fake_scenarios(recommended)

    monkeypatch.setattr(mod, "calculate_fixed_entry_levels_from_df", fake_calc)
    return mod


def _row(entry_price, tp_pct=3.2, tp2_pct=6.4, tp3_pct=9.6, sl_pct=3.2,
         recorded_at="2026-07-09 11:05:43", kode="ZZBACK", row_id=1):
    return {"id": row_id, "kode": kode, "recorded_at": recorded_at,
            "entry_price": entry_price, "tp_pct": tp_pct, "tp2_pct": tp2_pct,
            "tp3_pct": tp3_pct, "sl_pct": sl_pct}


def test_evaluate_row_updates_to_recommended_pullback_entry(patch_scenarios):
    """Regresi UTAMA (BRMS-style live): entry_price lama (formula ATR/MA20
    lama, jauh dari harga) dikoreksi ke entry pullback BARU (formula
    diskon kecil) -- SEMUA field (entry/tp/tp2/tp3/sl) ikut diperbarui
    bersamaan, bukan cuma entry_price sendirian."""
    df = _fake_df(pd.bdate_range(end="2026-07-09", periods=60),
                   lows=[4000] * 60, highs=[4100] * 60, closes=[4050] * 60)
    row = _row(entry_price=3900.0)  # formula lama, jauh dari pullback baru (4109)

    result = _evaluate_row(row, df)

    assert result["action"] == "update"
    assert result["new_entry"] == 4109.0
    assert result["new_tp_pct"] == 3.6 and result["new_tp2_pct"] == 7.2 and result["new_tp3_pct"] == 10.8
    assert result["new_sl_pct"] == 3.6


def test_evaluate_row_picks_breakout_when_recommended(patch_scenarios):
    """Regresi (ELSA/PGEO-style live, ditemukan nyata: 2 dari 17 baris
    ternyata direkomendasikan breakout bukan pullback) -- backfill HARUS
    ikut recommended_scenario yang direkonstruksi (bisa 'breakout'), BUKAN
    selalu memaksa 'pullback' apa adanya."""
    df = _fake_df(pd.bdate_range(end="2026-07-09", periods=60),
                   lows=[4250] * 60, highs=[4350] * 60, closes=[4300] * 60)  # close>4200 -> breakout
    row = _row(entry_price=3900.0)

    result = _evaluate_row(row, df)

    assert result["action"] == "update"
    assert result["new_entry"] == 4300.0  # entry skenario breakout, bukan pullback


def test_evaluate_row_no_change_needed_when_entry_already_close(patch_scenarios):
    """Kontrol: kalau entry_price tersimpan SUDAH dekat hasil rekonstruksi
    (selisih < MIN_CHANGE_PCT), jangan di-UPDATE -- idempotent kalau
    dijalankan ulang (mis. PTRO live: selisih cuma 0.08%)."""
    df = _fake_df(pd.bdate_range(end="2026-07-09", periods=60),
                   lows=[4000] * 60, highs=[4100] * 60, closes=[4050] * 60)
    row = _row(entry_price=4109.0)  # sudah persis = pullback baru

    result = _evaluate_row(row, df)

    assert result["action"] == "no_change_needed"


def test_evaluate_row_never_uses_data_after_recorded_date(patch_scenarios):
    """Regresi anti-lookahead INTI (sama disiplin dgn backfill_open_entry_
    price.py): data SETELAH recorded_date TIDAK BOLEH memengaruhi hasil."""
    dates = pd.bdate_range(end="2026-07-13", periods=63)  # sampai beberapa hari SETELAH recorded_date
    recorded_date = pd.Timestamp("2026-07-09").date()
    n_before = sum(1 for d in dates if d.date() <= recorded_date)  # bar sampai/pada recorded_date
    n_after = len(dates) - n_before  # bar SETELAH recorded_date
    # Bar sampai recorded_date close=4050 (-> pullback); bar SETELAH
    # recorded_date close=4300 (-> breakout kalau anti-lookahead bocor).
    closes = [4050] * n_before + [4300] * n_after
    lows = [4000] * n_before + [4250] * n_after
    highs = [4100] * n_before + [4350] * n_after
    df = _fake_df(dates, lows, highs, closes)
    row = _row(entry_price=3900.0, recorded_at="2026-07-09 11:05:43")

    result = _evaluate_row(row, df)

    assert result["new_entry"] == 4109.0, "harus tetap skenario pullback -- data breakout SETELAH recorded_date wajib diabaikan"


def test_evaluate_row_skip_no_data_when_history_missing(patch_scenarios):
    row = _row(entry_price=3900.0)
    result = _evaluate_row(row, df=None)
    assert result["action"] == "skip_no_data"


def test_evaluate_row_skip_no_history_before_date_when_truncation_is_empty(patch_scenarios):
    df = _fake_df(pd.bdate_range(start="2026-07-15", periods=60),  # semua data SETELAH recorded_date
                   lows=[4000] * 60, highs=[4100] * 60, closes=[4050] * 60)
    row = _row(entry_price=3900.0, recorded_at="2026-07-09 11:05:43")

    result = _evaluate_row(row, df)

    assert result["action"] == "skip_no_history_before_date"


def test_fetch_pending_entry_rows_only_returns_pending_entry_top_pick_buy(clean_signal_db):
    """Regresi SCOPE-SAFETY: query HARUS HANYA mengambil status=
    'PENDING_ENTRY' AND source='TOP_PICK' AND direction='BUY' -- baris
    OPEN/resolved/source lain TIDAK BOLEH pernah masuk (memenuhi jaminan
    'tidak pernah menyentuh posisi yang sudah aktif/selesai')."""
    from core.database import get_db

    with get_db() as conn:
        conn.execute("INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, status, source, direction) "
                     "VALUES ('ZZPENDING', 1000, 3.0, 3.0, 'PENDING_ENTRY', 'TOP_PICK', 'BUY')")
        conn.execute("INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, status, source, direction) "
                     "VALUES ('ZZOPEN', 1000, 3.0, 3.0, 'OPEN', 'TOP_PICK', 'BUY')")
        conn.execute("INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, status, source, direction) "
                     "VALUES ('ZZSMARTMONEY', 1000, 3.0, 3.0, 'PENDING_ENTRY', 'SMART_MONEY', 'BUY')")

    rows = _fetch_pending_entry_rows()
    kodes = {r["kode"] for r in rows}

    assert "ZZPENDING" in kodes
    assert "ZZOPEN" not in kodes, "baris OPEN (posisi sudah aktif) TIDAK BOLEH tersentuh"
    assert "ZZSMARTMONEY" not in kodes, "SMART_MONEY tidak pernah PENDING_ENTRY -- di luar cakupan backfill ini"


def test_apply_updates_writes_all_five_fields_only_for_update_rows(clean_signal_db):
    """Regresi: apply_updates() menulis entry_price + tp_pct + tp2_pct +
    tp3_pct + sl_pct BERSAMAAN (beda dari backfill_open_entry_price.py yang
    cuma entry_price sendirian) -- HANYA utk baris ber-action 'update'."""
    from core.database import get_db

    with get_db() as conn:
        cur1 = conn.execute("INSERT INTO signal_history (kode, entry_price, tp_pct, tp2_pct, tp3_pct, sl_pct, status, source, direction) "
                            "VALUES ('ZZUPD', 3900, 3.2, 6.4, 9.6, 3.2, 'PENDING_ENTRY', 'TOP_PICK', 'BUY')")
        id_upd = cur1.lastrowid
        cur2 = conn.execute("INSERT INTO signal_history (kode, entry_price, tp_pct, tp2_pct, tp3_pct, sl_pct, status, source, direction) "
                            "VALUES ('ZZNOCHANGE', 4109, 3.6, 7.2, 10.8, 3.6, 'PENDING_ENTRY', 'TOP_PICK', 'BUY')")
        id_nochange = cur2.lastrowid

    results = [
        {"id": id_upd, "action": "update", "new_entry": 4109.0,
         "new_tp_pct": 3.6, "new_tp2_pct": 7.2, "new_tp3_pct": 10.8, "new_sl_pct": 3.6},
        {"id": id_nochange, "action": "no_change_needed", "new_entry": 4109.0,
         "new_tp_pct": None, "new_tp2_pct": None, "new_tp3_pct": None, "new_sl_pct": None},
    ]

    n = apply_updates(results)
    assert n == 1

    with get_db() as conn:
        upd_row = conn.execute("SELECT entry_price, tp_pct, tp2_pct, tp3_pct, sl_pct FROM signal_history WHERE id = ?", (id_upd,)).fetchone()
        nochange_row = conn.execute("SELECT entry_price FROM signal_history WHERE id = ?", (id_nochange,)).fetchone()

    assert upd_row["entry_price"] == 4109.0
    assert upd_row["tp_pct"] == 3.6 and upd_row["tp2_pct"] == 7.2 and upd_row["tp3_pct"] == 10.8 and upd_row["sl_pct"] == 3.6
    assert nochange_row["entry_price"] == 4109.0, "baris no_change_needed TIDAK BOLEH ter-UPDATE"


def test_run_dry_run_makes_no_db_writes(clean_signal_db, patch_scenarios, monkeypatch):
    """Regresi: mode dry-run (default) TIDAK BOLEH menulis apa pun ke
    database, bahkan kalau ada baris yang seharusnya di-update."""
    import asyncio

    import scripts.backfill_pending_entry as mod
    from core.database import get_db

    with get_db() as conn:
        cur = conn.execute("INSERT INTO signal_history (kode, entry_price, tp_pct, tp2_pct, tp3_pct, sl_pct, status, source, direction, recorded_at) "
                           "VALUES ('ZZDRYRUN', 3900, 3.2, 6.4, 9.6, 3.2, 'PENDING_ENTRY', 'TOP_PICK', 'BUY', '2026-07-09 11:05:43')")
        row_id = cur.lastrowid

    df = _fake_df(pd.bdate_range(end="2026-07-09", periods=60),
                   lows=[4000] * 60, highs=[4100] * 60, closes=[4050] * 60)

    async def fake_fetch_history(kodes):
        return {"ZZDRYRUN": df}

    monkeypatch.setattr(mod, "_fetch_history", fake_fetch_history)

    results = asyncio.run(mod.run(apply=False))
    assert any(r["action"] == "update" for r in results), "test ini butuh setidaknya 1 baris yang SEHARUSNYA di-update"

    with get_db() as conn:
        row = conn.execute("SELECT entry_price FROM signal_history WHERE id = ?", (row_id,)).fetchone()
    assert row["entry_price"] == 3900.0, "dry-run TIDAK BOLEH menulis apa pun ke database"
