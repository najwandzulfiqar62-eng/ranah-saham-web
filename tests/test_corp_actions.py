# Test utk core/corp_actions.py -- peringatan aksi korporasi (split/dividen)
# di Audit Sinyal (permintaan user 2026-07-22: tandai emiten yang ada corp
# action supaya sinyal tidak salah dibaca sbg trap; kasus nyata RAJA split &
# ERAA dividend trap).
import pandas as pd

from core.corp_actions import extract_recent_actions, build_warning


def _df_with_actions(rows):
    """rows: list of (tanggal_str, dividend, split). Bangun OHLC df minimal +
    kolom Dividends / Stock Splits seperti hasil yf.download(actions=True)."""
    idx = pd.DatetimeIndex([pd.Timestamp(d) for d, _, _ in rows])
    return pd.DataFrame({
        "Open": [100.0] * len(rows), "High": [101.0] * len(rows),
        "Low": [99.0] * len(rows), "Close": [100.0] * len(rows),
        "Volume": [1_000_000.0] * len(rows),
        "Dividends": [dv for _, dv, _ in rows],
        "Stock Splits": [sp for _, _, sp in rows],
    }, index=idx)


NOW = "2026-07-20"


def test_extract_dividend_within_window():
    # ERAA-like: ex-dividen 2026-07-08 Rp25
    df = _df_with_actions([("2026-07-06", 0.0, 0.0), ("2026-07-08", 25.0, 0.0), ("2026-07-10", 0.0, 0.0)])
    acts = extract_recent_actions(df, window_days=30, now=NOW)
    assert acts == [{"type": "dividen", "date": "2026-07-08", "value": 25.0}]


def test_extract_split_within_window():
    # RAJA-like: split 1:5 2026-07-16
    df = _df_with_actions([("2026-07-14", 0.0, 0.0), ("2026-07-16", 0.0, 5.0)])
    acts = extract_recent_actions(df, window_days=30, now=NOW)
    assert acts == [{"type": "split", "date": "2026-07-16", "value": 5.0}]


def test_extract_both_sorted_newest_first():
    df = _df_with_actions([("2026-07-02", 8.0, 0.0), ("2026-07-16", 0.0, 5.0)])
    acts = extract_recent_actions(df, window_days=30, now=NOW)
    assert [a["date"] for a in acts] == ["2026-07-16", "2026-07-02"]  # terbaru dulu


def test_extract_ignores_old_actions_outside_window():
    df = _df_with_actions([("2026-01-01", 30.0, 0.0), ("2026-07-16", 0.0, 5.0)])
    acts = extract_recent_actions(df, window_days=30, now=NOW)
    assert [a["type"] for a in acts] == ["split"]  # dividen Januari di luar window 30 hari


def test_extract_ignores_nan_and_zero_and_unit_split():
    # NaN (jalur batch), 0, dan split=1.0 (=tanpa split) semua HARUS diabaikan
    df = _df_with_actions([
        ("2026-07-10", float("nan"), float("nan")),
        ("2026-07-12", 0.0, 1.0),
        ("2026-07-14", 0.0, 0.0),
    ])
    assert extract_recent_actions(df, window_days=30, now=NOW) == []


def test_extract_empty_and_missing_columns():
    assert extract_recent_actions(None) == []
    assert extract_recent_actions(pd.DataFrame()) == []
    # df tanpa kolom aksi (mis. OHLC biasa) -> aman, kosong
    plain = pd.DataFrame({"Close": [1.0]}, index=[pd.Timestamp("2026-07-16")])
    assert extract_recent_actions(plain, now=NOW) == []


def test_build_warning_dividend():
    w = build_warning([{"type": "dividen", "date": "2026-07-08", "value": 25.0}])
    assert w["has_dividen"] is True and w["has_split"] is False
    assert "ex-dividen 2026-07-08" in w["summary"]
    assert "dividen" in w["note"].lower()


def test_build_warning_split_takes_priority_note():
    w = build_warning([
        {"type": "split", "date": "2026-07-16", "value": 5.0},
        {"type": "dividen", "date": "2026-07-02", "value": 8.0},
    ])
    assert w["has_split"] is True and w["has_dividen"] is True
    assert "split" in w["note"].lower()  # note split diprioritaskan (penurunan lebih besar)
    assert "stock split 2026-07-16" in w["summary"]


def test_build_warning_none_when_empty():
    assert build_warning([]) is None
    assert build_warning(None) is None
