# =========================
# COMPARE SAHAM
# =========================
# REDESIGN (Juni 2026) -- versi lama cuma scoring 0-4 sederhana (4
# kondisi: trend vs EMA20, RSI>50, MACD bullish, momentum 5 hari),
# tanpa visual sama sekali. Diganti total dengan:
# 1. Scoring REUSE dari calculate_ai_score_from_df() (core/ai_score.py)
#    -- SENGAJA tidak menulis ulang metodologi scoring baru, supaya
#    /compare KONSISTEN dengan /aiscore: kalau user compare 2 saham,
#    skornya akan SAMA PERSIS dengan kalau mereka cek /aiscore masing-
#    masing secara terpisah. Skor itu sendiri sudah berbasis riset
#    (MACD+RSI 73% win rate backtest, Minervini MA trend, dst -- lihat
#    catatan lengkap di core/ai_score.py).
# 2. Relative strength ANTAR DUA SAHAM itu sendiri (BARU) -- siapa
#    outperform siapa dalam periode tertentu, pakai formula yang sama
#    dengan calculate_beta() tapi dibandingkan satu sama lain langsung,
#    bukan vs IHSG.
# 3. Visual chart perbandingan (BARU) -- lihat core/charts/compare_chart.py

import pandas as pd

from core.ai_score import calculate_ai_score_from_df


def calculate_relative_performance(df1: pd.DataFrame, df2: pd.DataFrame,
                                      period_days: int = 20) -> dict | None:
    """Bandingkan performa dua saham langsung (BUKAN vs IHSG) dalam
    period_days terakhir. Returns None kalau data tidak cukup.

    Returns dict: return_1, return_2 (dalam %), winner (ticker mana
    yang outperform), gap_pct (selisih return dalam poin persentase)."""
    if len(df1) < period_days + 1 or len(df2) < period_days + 1:
        return None

    try:
        start_1 = float(df1["Close"].iloc[-(period_days + 1)])
        end_1 = float(df1["Close"].iloc[-1])
        return_1 = ((end_1 / start_1) - 1) * 100

        start_2 = float(df2["Close"].iloc[-(period_days + 1)])
        end_2 = float(df2["Close"].iloc[-1])
        return_2 = ((end_2 / start_2) - 1) * 100

        gap_pct = return_1 - return_2

        return {
            "return_1": round(return_1, 2),
            "return_2": round(return_2, 2),
            "gap_pct": round(gap_pct, 2),
            "period_days": period_days,
        }
    except Exception:
        return None


def analyze_for_compare(df: pd.DataFrame) -> dict | None:
    """Analisis satu saham untuk perbandingan, REUSE dari AI Score
    (core/ai_score.py) -- supaya konsisten dengan /aiscore. Returns
    None kalau data tidak cukup (caller harus handle ini, BUKAN dapat
    dict placeholder seperti versi lama yang bisa menyesatkan)."""
    return calculate_ai_score_from_df(df)


