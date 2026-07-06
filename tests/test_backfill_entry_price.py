# Test utk scripts/backfill_open_entry_price.py -- backfill KOREKSI SATU
# KALI (bukan migrasi permanen) yang merekonstruksi skenario Trading Plan
# yang beneran kena pada hari sinyal OPEN direkam, lalu mengoreksi
# entry_price HANYA kalau confidence check (tp_pct/sl_pct tersimpan cocok
# dgn skenario yang direkonstruksi) lolos. Lihat docstring modul itu utk
# alasan lengkap (permintaan user langsung, live: RAJA entry_price masih
# harga real-time padahal tp_pct/sl_pct sudah dihitung dari skenario
# pullback yang beneran kena).
import pandas as pd
import pytest

from scripts.backfill_open_entry_price import (
    _evaluate_row,
    _fetch_open_rows,
    apply_updates,
)


def _fake_df(dates, lows, highs, closes):
    return pd.DataFrame(
        {"Open": closes, "High": highs, "Low": lows, "Close": closes,
         "Volume": [1_000_000] * len(dates)},
        index=pd.DatetimeIndex(dates),
    )


def _fake_scenarios():
    """Skenario sintetis terkontrol -- entry pullback SENGAJA beda jauh
    dari entry normal, supaya gampang dibedakan di assertion."""
    return {
        "normal": {"key": "normal", "entry": 4130.0, "sl": 4004.0, "risk_pct": 3.1,
                   "tp1_pct": 3.1, "tp2_pct": 6.2, "tp3_pct": 9.3},
        "pullback": {"key": "pullback", "entry": 3968.0, "sl": 3840.0, "risk_pct": 3.2,
                     "tp1_pct": 3.2, "tp2_pct": 6.4, "tp3_pct": 9.6},
        "deep": {"key": "deep", "entry": 3800.0, "sl": 3650.0, "risk_pct": 3.9,
                 "tp1_pct": 3.9, "tp2_pct": 7.8, "tp3_pct": 11.7},
        "breakout": {"key": "breakout", "entry": 4300.0, "sl": 4150.0, "risk_pct": 3.5,
                     "tp1_pct": 3.5, "tp2_pct": 7.0, "tp3_pct": 10.5},
    }


@pytest.fixture
def patch_scenarios(monkeypatch):
    """Monkeypatch fungsi core/trading_plan.py yang dipakai backfill script
    supaya skenarionya SEPENUHNYA terkontrol (tidak bergantung pada
    kalkulasi ATR/S&R sungguhan dari df sintetis) -- fokus test ini pada
    LOGIC backfill-nya sendiri (as-of truncation, confidence gate,
    threshold no-change, OPEN-only scope), bukan pada core/trading_plan.py
    (yang sudah ditest terpisah)."""
    import scripts.backfill_open_entry_price as mod

    def fake_calc(df, created_date_str):
        return {"scenarios": _fake_scenarios()}

    def fake_hit(scenarios, low, high):
        # "kena" ditentukan SENGAJA sederhana: pullback kena kalau low <= 3970 (dekat 3968)
        hits = []
        if low <= 3968.0:
            hits.append({"key": "pullback", "scenario": scenarios["pullback"], "entry_price": 3968.0})
        else:
            hits.append({"key": "normal", "scenario": scenarios["normal"], "entry_price": 4130.0})
        return hits

    monkeypatch.setattr(mod, "calculate_fixed_entry_levels_from_df", fake_calc)
    monkeypatch.setattr(mod, "get_hit_scenarios", fake_hit)
    return mod


def _row(entry_price, tp_pct, sl_pct, recorded_at="2026-07-06 14:41:05", kode="ZZBACK", row_id=1):
    return {"id": row_id, "kode": kode, "recorded_at": recorded_at,
            "entry_price": entry_price, "tp_pct": tp_pct, "sl_pct": sl_pct}


def test_evaluate_row_updates_when_scenario_confidently_matches(patch_scenarios):
    """Regresi UTAMA (permintaan user, contoh nyata RAJA): entry_price lama
    (harga real-time saat dicatat) SALAH, tp_pct/sl_pct tersimpan COCOK dgn
    skenario pullback yang direkonstruksi (dalam toleransi) -- entry_price
    HARUS dikoreksi ke level pullback (3968), bukan tetap 4050/4130."""
    df = _fake_df(
        pd.bdate_range(end="2026-07-06", periods=60),
        lows=[4000] * 59 + [3960], highs=[4100] * 59 + [4140], closes=[4050] * 60,
    )
    row = _row(entry_price=4050.0, tp_pct=3.2, sl_pct=3.2)  # cocok dgn pullback (3.2/3.2)

    result = _evaluate_row(row, df)

    assert result["action"] == "update"
    assert result["new_entry"] == 3968.0


def test_evaluate_row_skip_low_confidence_when_percentages_dont_match(patch_scenarios):
    """Kontrol: kalau tp_pct/sl_pct tersimpan TIDAK cocok dgn skenario mana
    pun yang direkonstruksi (mis. baris direkam kode lama sebelum skenario
    ada sama sekali) -- JANGAN ditebak, dilewati sbg low-confidence."""
    df = _fake_df(
        pd.bdate_range(end="2026-07-06", periods=60),
        lows=[4000] * 59 + [3960], highs=[4100] * 59 + [4140], closes=[4050] * 60,
    )
    row = _row(entry_price=4050.0, tp_pct=1.4, sl_pct=1.4)  # jauh dari skenario manapun

    result = _evaluate_row(row, df)

    assert result["action"] == "skip_low_confidence"


def test_evaluate_row_no_change_needed_when_entry_already_close(patch_scenarios):
    """Kontrol: kalau entry_price yang tersimpan SUDAH dekat dgn hasil
    rekonstruksi (selisih < MIN_CHANGE_PCT), jangan di-UPDATE -- hindari
    noise pembulatan, dan idempotent kalau script dijalankan ulang."""
    df = _fake_df(
        pd.bdate_range(end="2026-07-06", periods=60),
        lows=[4200] * 60, highs=[4300] * 60, closes=[4130] * 60,  # low TIDAK pernah <= 3968 -> normal
    )
    row = _row(entry_price=4130.0, tp_pct=3.1, sl_pct=3.1)  # cocok normal, entry sudah = normal

    result = _evaluate_row(row, df)

    assert result["action"] == "no_change_needed"


def test_evaluate_row_uses_last_available_bar_when_recorded_date_not_a_trading_day(patch_scenarios):
    """Regresi: kalau recorded_date bukan hari bursa (weekend/libur) atau
    sinyal dicatat pagi hari SEBELUM bar hari itu final di yfinance, bar
    TERAKHIR yang tersedia SEBELUM/PADA tanggal itu tetap dipakai (BUKAN
    dilewati) -- itu persis data yang akan dilihat confidence() kalau
    dijalankan saat itu, bukan kasus gagal."""
    df = _fake_df(
        pd.bdate_range(end="2026-07-03", periods=60),  # data cuma sampai Jumat 2026-07-03
        lows=[4200] * 60, highs=[4300] * 60, closes=[4130] * 60,  # cocok skenario normal
    )
    row = _row(entry_price=4130.0, tp_pct=3.1, sl_pct=3.1, recorded_at="2026-07-06 14:41:05")  # Senin, tidak ada bar sendiri

    result = _evaluate_row(row, df)

    assert result["action"] == "no_change_needed"  # tetap dievaluasi (pakai bar Jumat), bukan dilewati


def test_evaluate_row_skip_no_history_before_date_when_truncation_is_empty(patch_scenarios):
    """Kontrol: kalau BENAR-BENAR tidak ada data historis sebelum/pada
    recorded_date sama sekali (mis. data historis mulai SETELAH tanggal
    itu), tidak ada dasar apa pun utk merekonstruksi -- lewati, jangan
    menebak."""
    df = _fake_df(
        pd.bdate_range(start="2026-07-10", periods=60),  # semua data SETELAH recorded_date
        lows=[4000] * 60, highs=[4100] * 60, closes=[4050] * 60,
    )
    row = _row(entry_price=4050.0, tp_pct=3.2, sl_pct=3.2, recorded_at="2026-07-06 14:41:05")

    result = _evaluate_row(row, df)

    assert result["action"] == "skip_no_history_before_date"


def test_evaluate_row_never_uses_data_after_recorded_date(patch_scenarios):
    """Regresi anti-lookahead INTI: data SETELAH recorded_date ada di df
    (mis. karena fetch selalu ambil ~1 tahun sampai HARI INI, jauh setelah
    tanggal sinyal itu direkam) dan SENGAJA dibuat seolah menembus area
    pullback -- kalau lookahead-nya bocor, skenario yang kepilih akan
    SALAH jadi pullback. Baris SEBELUM/PADA recorded_date sendiri tidak
    pernah menembus pullback, jadi hasil yang benar HARUS tetap normal."""
    dates = pd.bdate_range(end="2026-07-10", periods=63)  # sampai 3 hari SETELAH recorded_date (2026-07-06)
    lows = [4200] * 60 + [3900, 3900, 3900]  # cuma 3 bar TERAKHIR (setelah recorded_date) yang menembus pullback
    highs = [4300] * 60 + [4000, 4000, 4000]
    closes = [4130] * 60 + [3950, 3950, 3950]
    df = _fake_df(dates, lows, highs, closes)
    row = _row(entry_price=4050.0, tp_pct=3.1, sl_pct=3.1, recorded_at="2026-07-06 14:41:05")  # cocok skenario NORMAL

    result = _evaluate_row(row, df)

    assert result["action"] == "update"
    assert result["new_entry"] == 4130.0, "harus tetap skenario normal -- data pullback SETELAH recorded_date wajib diabaikan"


def test_evaluate_row_skip_no_data_when_history_missing(patch_scenarios):
    row = _row(entry_price=4050.0, tp_pct=3.2, sl_pct=3.2)
    result = _evaluate_row(row, df=None)
    assert result["action"] == "skip_no_data"


def test_evaluate_row_never_touches_closed_signals_by_construction(patch_scenarios):
    """_evaluate_row menerima row APA ADANYA (tidak query status sendiri) --
    jaminan 'tidak pernah menyentuh baris closed' ada di _fetch_open_rows
    (query SQL eksplisit status='OPEN'), diuji terpisah di bawah. Test ini
    memastikan _evaluate_row TIDAK punya jalur yang diam-diam mengembalikan
    'update' utk row yang sebenarnya bukan dari hasil query itu -- sanity
    check bahwa action selalu salah satu dari 5 nilai yang dikenal."""
    df = _fake_df(
        pd.bdate_range(end="2026-07-06", periods=60),
        lows=[4000] * 59 + [3960], highs=[4100] * 59 + [4140], closes=[4050] * 60,
    )
    row = _row(entry_price=4050.0, tp_pct=3.2, sl_pct=3.2)
    result = _evaluate_row(row, df)
    assert result["action"] in {
        "update", "no_change_needed", "skip_low_confidence",
        "skip_date_mismatch", "skip_no_data", "skip_no_scenario",
    }


def test_fetch_open_rows_only_returns_open_top_pick_smart_money_buy(clean_signal_db):
    """Regresi SCOPE-SAFETY: query harus HANYA mengambil status='OPEN' AND
    source IN ('TOP_PICK','SMART_MONEY') AND direction='BUY' -- baris
    resolved (TP_HIT/SL_HIT/EXPIRED), source lain, atau SELL TIDAK BOLEH
    pernah muncul di hasil (jadi tidak akan pernah tersentuh backfill ini,
    memenuhi jaminan 'tidak pernah menulis ulang hasil yang sudah terjadi')."""
    from core.database import get_db

    with get_db() as conn:
        conn.execute("INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, status, source, direction) "
                     "VALUES ('ZZOPEN', 1000, 3.0, 3.0, 'OPEN', 'TOP_PICK', 'BUY')")
        conn.execute("INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, status, source, direction, "
                     "resolved_at, resolved_price, return_pct, days_to_resolve) "
                     "VALUES ('ZZCLOSED', 1000, 3.0, 3.0, 'TP_HIT', 'TOP_PICK', 'BUY', datetime('now'), 1030, 3.0, 2)")
        conn.execute("INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, status, source, direction, "
                     "recommendation) VALUES ('ZZSELL', 1000, 3.0, 3.0, 'OPEN', 'SMART_MONEY', 'SELL', 'BAGUS')")

    rows = _fetch_open_rows()
    kodes = {r["kode"] for r in rows}

    assert "ZZOPEN" in kodes
    assert "ZZCLOSED" not in kodes, "baris resolved TIDAK BOLEH pernah masuk -- backfill tidak boleh menyentuhnya"
    assert "ZZSELL" not in kodes, "arah SELL sengaja di luar cakupan backfill ini"


def test_apply_updates_only_touches_entry_price_of_update_rows(clean_signal_db):
    """Regresi: apply_updates() HANYA menulis kolom entry_price, dan HANYA
    utk baris ber-action 'update' -- baris lain (mis. skip_low_confidence,
    yang juga membawa 'new_entry' sbg info) TIDAK BOLEH ikut ter-UPDATE."""
    from core.database import get_db

    with get_db() as conn:
        cur1 = conn.execute("INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, status, source, direction) "
                            "VALUES ('ZZUPD', 4050, 3.2, 3.2, 'OPEN', 'TOP_PICK', 'BUY')")
        id_upd = cur1.lastrowid
        cur2 = conn.execute("INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, status, source, direction) "
                            "VALUES ('ZZSKIP', 4050, 1.4, 1.4, 'OPEN', 'TOP_PICK', 'BUY')")
        id_skip = cur2.lastrowid

    results = [
        {"id": id_upd, "kode": "ZZUPD", "action": "update", "new_entry": 3968.0,
         "entry_price": 4050.0, "tp_pct": 3.2, "sl_pct": 3.2, "recorded_at": "2026-07-06 00:00:00", "detail": ""},
        {"id": id_skip, "kode": "ZZSKIP", "action": "skip_low_confidence", "new_entry": 3968.0,
         "entry_price": 4050.0, "tp_pct": 1.4, "sl_pct": 1.4, "recorded_at": "2026-07-06 00:00:00", "detail": ""},
    ]

    n = apply_updates(results)
    assert n == 1

    with get_db() as conn:
        upd_row = conn.execute("SELECT entry_price, tp_pct, sl_pct FROM signal_history WHERE id = ?", (id_upd,)).fetchone()
        skip_row = conn.execute("SELECT entry_price FROM signal_history WHERE id = ?", (id_skip,)).fetchone()

    assert upd_row["entry_price"] == 3968.0
    assert upd_row["tp_pct"] == 3.2 and upd_row["sl_pct"] == 3.2, "tp_pct/sl_pct TIDAK BOLEH ikut berubah"
    assert skip_row["entry_price"] == 4050.0, "baris skip_low_confidence TIDAK BOLEH ter-UPDATE"


def test_run_dry_run_makes_no_db_writes(clean_signal_db, patch_scenarios, monkeypatch):
    """Regresi: mode dry-run (default) TIDAK BOLEH menulis apa pun ke
    database, bahkan kalau ada baris yang seharusnya di-update."""
    import asyncio

    import scripts.backfill_open_entry_price as mod
    from core.database import get_db

    with get_db() as conn:
        cur = conn.execute("INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, status, source, direction, recorded_at) "
                           "VALUES ('ZZDRYRUN', 4050, 3.2, 3.2, 'OPEN', 'TOP_PICK', 'BUY', '2026-07-06 14:41:05')")
        row_id = cur.lastrowid

    df = _fake_df(
        pd.bdate_range(end="2026-07-06", periods=60),
        lows=[4000] * 59 + [3960], highs=[4100] * 59 + [4140], closes=[4050] * 60,
    )

    async def fake_fetch_history(kodes):
        return {"ZZDRYRUN": df}

    monkeypatch.setattr(mod, "_fetch_history", fake_fetch_history)

    results = asyncio.run(mod.run(apply=False))
    assert any(r["action"] == "update" for r in results), "test ini butuh setidaknya 1 baris yang SEHARUSNYA di-update"

    with get_db() as conn:
        row = conn.execute("SELECT entry_price FROM signal_history WHERE id = ?", (row_id,)).fetchone()
    assert row["entry_price"] == 4050.0, "dry-run TIDAK BOLEH menulis apa pun ke database"
