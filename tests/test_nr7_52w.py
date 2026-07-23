# Test utk teori NR7 + 52W High (permintaan user 2026-07-22: uji head-to-head
# vs Top Pick di Audit Sinyal, ditandai HIGH RISK).
# - detect_nr7_52w (core/screening_pro.py): deteksi setup + level SL/TP teori.
# - record_nr7_52w_signals (core/signal_history.py): perekaman sbg source
#   independen 'NR7_52W' yang SENGAJA boleh koeksis dgn TOP_PICK/SMART_MONEY
#   utk saham yang sama (perbandingan teori adil) tapi tetap maks 1 NR7/kode.
import asyncio

import numpy as np
import pandas as pd

from core.screening_pro import detect_nr7_52w
from core.signal_history import record_nr7_52w_signals, _has_open_signal, _has_open_nr7
from core.database import get_db


# ---------------------------------------------------------------------------
# detect_nr7_52w
# ---------------------------------------------------------------------------
def _uptrend_df(n=260, last_range=3.5):
    """Uptrend menuju 52W high dgn bar TERAKHIR = NR7 (range sempit) di puncak."""
    base = np.linspace(100.0, 200.0, n)
    highs = base + 4.0          # range harian ~8 utk bar-bar sebelumnya
    lows = base - 4.0
    closes = base.copy()
    peak = float(highs[:-1].max())
    closes[-1] = peak * 0.99                 # dekat/di area 52W high
    highs[-1] = closes[-1] + last_range / 2  # range terakhir jauh lebih sempit dari 8
    lows[-1] = closes[-1] - last_range / 2
    return pd.DataFrame(
        {"Open": closes, "High": highs, "Low": lows, "Close": closes,
         "Volume": [1_000_000.0] * n},
        index=pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n),
    )


def test_detect_nr7_52w_valid_setup():
    r = detect_nr7_52w(_uptrend_df(last_range=3.5))
    assert r is not None
    assert r["is_nr7_52w"] is True
    # SL wajar (di bawah harga, di atas floor) & TP = R-multiples 2R/3R/4R
    assert r["nr7_sl_pct"] > 1.0
    assert abs(r["nr7_tp1_pct"] - r["nr7_sl_pct"] * 2) < 0.02
    assert abs(r["nr7_tp2_pct"] - r["nr7_sl_pct"] * 3) < 0.02
    assert abs(r["nr7_tp3_pct"] - r["nr7_sl_pct"] * 4) < 0.02


def test_detect_nr7_52w_floor_on_ultratight_range():
    # range terakhir SANGAT sempit -> sl% mentah <1% -> di-floor ke 1.0
    r = detect_nr7_52w(_uptrend_df(last_range=0.4))
    assert r is not None
    assert r["nr7_sl_pct"] == 1.0
    assert r["nr7_tp1_pct"] == 2.0  # 2R dari floor


def test_detect_nr7_52w_rejects_wide_last_bar():
    # bar terakhir range LEBAR (bukan tersempit dari 7) -> None
    df = _uptrend_df()
    df.iloc[-1, df.columns.get_loc("High")] = float(df["Close"].iloc[-1]) + 10
    df.iloc[-1, df.columns.get_loc("Low")] = float(df["Close"].iloc[-1]) - 10
    assert detect_nr7_52w(df) is None


def test_detect_nr7_52w_rejects_far_from_52w_high():
    # NR7 tapi harga jauh di bawah 52W high -> None
    df = _uptrend_df()
    idx = df.index[-1]
    df.loc[idx, ["Close", "Open"]] = 120.0
    df.loc[idx, "High"] = 120.4
    df.loc[idx, "Low"] = 119.6
    assert detect_nr7_52w(df) is None


def test_detect_nr7_52w_rejects_insufficient_history():
    assert detect_nr7_52w(_uptrend_df().tail(100)) is None


def test_detect_nr7_52w_works_with_one_idx_trading_year():
    """BUG NYATA (2026-07-23): ambang lama `len(df) < 252` memakai konvensi
    hari bursa AS, padahal BEI cuma ~244 hari bursa setahun. Pemanggil di
    produksi (_build_confidence_raw) mengambil period="1y" -> TEPAT 244 baris
    -> detect selalu None, sehingga sumber sinyal NR7 tidak pernah sekali pun
    tercatat. Dengan 244 baris (setahun BEI yang sah) deteksi HARUS jalan."""
    df = _uptrend_df(n=244, last_range=3.5)
    assert len(df) == 244
    r = detect_nr7_52w(df)
    assert r is not None and r["is_nr7_52w"] is True


def test_detect_nr7_52w_masih_tolak_data_kurang_dari_setahun():
    """Batas bawahnya tetap ada -- 200 bar (~10 bulan) belum sah disebut
    'tertinggi 52 minggu'."""
    assert detect_nr7_52w(_uptrend_df(n=200, last_range=3.5)) is None


def test_detect_nr7_52w_never_returns_nan_levels():
    """Bug nyata (2026-07-23): yfinance kerap mengembalikan bar TERAKHIR
    berisi NaN (hari berjalan/belum lengkap). Tanpa membuang NaN, setiap
    perbandingan (`today_range <= 0`, dst) lolos diam-diam karena `nan <op> x`
    selalu False -> fungsi keliru mengembalikan dict SL/TP NaN utk SEMUA
    saham (178/178 'cocok' di produksi). Invariant: hasilnya None ATAU dict
    yang SEMUA nilainya angka hingga (finite), TIDAK PERNAH NaN."""
    df = _uptrend_df()
    for col in ["Open", "High", "Low", "Close"]:
        df.iloc[-1, df.columns.get_loc(col)] = float("nan")
    r = detect_nr7_52w(df)
    if r is not None:
        for k, v in r.items():
            if isinstance(v, float):
                assert v == v, f"{k} bernilai NaN (bug NaN belum ketangkap)"


def test_detect_nr7_52w_valid_even_with_nan_last_bar_when_prev_is_nr7():
    """Kalau bar terakhir NaN dibuang, bar SEBELUMNYA (yang valid NR7) jadi
    acuan -- deteksi tetap jalan, tidak macet oleh baris kosong."""
    df = _uptrend_df(last_range=3.5)
    # tambах 1 baris NaN di ujung (simulasi bar hari berjalan yg belum lengkap)
    nan_row = pd.DataFrame(
        {"Open": [float("nan")], "High": [float("nan")], "Low": [float("nan")],
         "Close": [float("nan")], "Volume": [0.0]},
        index=[df.index[-1] + pd.Timedelta(days=1)],
    )
    df2 = pd.concat([df, nan_row])
    r = detect_nr7_52w(df2)
    assert r is not None and r["is_nr7_52w"] is True


def test_record_nr7_rejects_nan_levels(clean_signal_db):
    """Pertahanan berlapis: walau caller keliru mengirim level NaN
    (bool(nan)==True di Python bisa lolos filter naif), perekaman menolaknya."""
    bad = {"kode": "NANX", "harga": 200.0, "is_nr7_52w": True,
           "nr7_sl_pct": float("nan"), "nr7_tp1_pct": float("nan")}
    saved = asyncio.run(record_nr7_52w_signals([bad]))
    assert saved == []


# ---------------------------------------------------------------------------
# record_nr7_52w_signals
# ---------------------------------------------------------------------------
def _nr7_item(kode="AAAA", harga=200.0):
    return {
        "kode": kode, "harga": harga, "is_nr7_52w": True,
        "nr7_sl_pct": 2.0, "nr7_tp1_pct": 4.0, "nr7_tp2_pct": 6.0, "nr7_tp3_pct": 8.0,
        "ai_rating": "BAGUS", "confidence_score": 70, "ai_score": 60,
    }


def test_record_nr7_records_open_buy_with_theory_levels(clean_signal_db):
    saved = asyncio.run(record_nr7_52w_signals([_nr7_item("BBCA")]))
    assert len(saved) == 1
    s = saved[0]
    assert s["source"] == "NR7_52W"
    assert s["direction"] == "BUY"
    assert s["sl_pct"] == 2.0 and s["tp_pct"] == 4.0
    assert s["pattern"] == "NR7 + 52W High"
    # tersimpan LANGSUNG OPEN (entry market), entry_filled_at terisi
    with get_db() as conn:
        row = conn.execute(
            "SELECT status, entry_filled_at, entry_mode FROM signal_history WHERE kode='BBCA' AND source='NR7_52W'"
        ).fetchone()
    assert row["status"] == "OPEN"
    assert row["entry_filled_at"] is not None
    assert row["entry_mode"] == "AGRESIF"


def test_record_nr7_ignores_non_nr7_and_incomplete_items(clean_signal_db):
    items = [
        {"kode": "X1", "harga": 100.0},                                  # bukan NR7
        {"kode": "X2", "harga": 100.0, "is_nr7_52w": True},              # tanpa level
        {"kode": "X3", "harga": 100.0, "is_nr7_52w": True, "nr7_sl_pct": 2.0},  # tanpa tp1
    ]
    saved = asyncio.run(record_nr7_52w_signals(items))
    assert saved == []


def test_record_nr7_dedups_same_kode(clean_signal_db):
    first = asyncio.run(record_nr7_52w_signals([_nr7_item("CCCC")]))
    second = asyncio.run(record_nr7_52w_signals([_nr7_item("CCCC")]))
    assert len(first) == 1
    assert second == []  # sudah ada NR7 OPEN utk CCCC -> tidak dobel


def test_record_nr7_coexists_with_top_pick_same_kode(clean_signal_db):
    """KRUX fitur ini: NR7 HARUS bisa mencatat saham yang SUDAH punya sinyal
    TOP_PICK OPEN -- itu yang bikin perbandingan head-to-head adil."""
    with get_db() as conn:
        conn.execute(
            "INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, source, status, direction) "
            "VALUES ('DDDD', 200.0, 5.0, 3.0, 'TOP_PICK', 'OPEN', 'BUY')"
        )
    saved = asyncio.run(record_nr7_52w_signals([_nr7_item("DDDD")]))
    assert len(saved) == 1  # NR7 tetap tercatat walau TOP_PICK sudah OPEN
    with get_db() as conn:
        rows = conn.execute(
            "SELECT source FROM signal_history WHERE kode='DDDD' AND status='OPEN' ORDER BY source"
        ).fetchall()
    sources = sorted(r["source"] for r in rows)
    assert sources == ["NR7_52W", "TOP_PICK"]  # keduanya OPEN bersamaan


def test_nr7_open_does_not_block_main_group(clean_signal_db):
    """Sebaliknya: sinyal NR7 OPEN TIDAK boleh menghalangi TOP_PICK/SMART_MONEY
    merekam kode yang sama (_has_open_signal ter-scope ke grup main)."""
    asyncio.run(record_nr7_52w_signals([_nr7_item("EEEE")]))
    assert _has_open_nr7("EEEE") is True          # NR7 memang aktif
    assert _has_open_signal("EEEE") is False       # tapi grup main lihatnya kosong
