# =========================
# CHART: SUPPORT & RESISTANCE (SNR)
# =========================
# Migrasi generate_snr dari main.py lama. Berbeda dari calculate_support_
# resistance_deep di core/indicators.py (yang murni pivot point), chart
# ini memakai metode TAMBAHAN: cluster swing high/low dari histori harga
# untuk memperkuat level S/R -- jadi sengaja dipisah sebagai fungsi
# tersendiri, bukan duplikasi yang perlu disatukan.
#
# Logic kalkulasi S/R dipisah dari plotting supaya bisa ditest tanpa
# perlu matplotlib.

import pandas as pd
import numpy as np

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from matplotlib.gridspec import GridSpec

from core.indicators import calculate_rsi
from core.charts.chart_symbols import to_chart_safe
from core.charts.watermark import apply_centered_watermark_to_file


def _cluster_levels(levels: list, tolerance: float = 0.02) -> list:
    """Gabungkan level-level harga yang berdekatan (dalam toleransi %)
    jadi satu level rata-rata. Dipakai untuk menyatukan pivot point
    dengan swing high/low yang nilainya mirip."""
    if not levels:
        return []
    levels = sorted(levels)
    clusters = []
    current_cluster = [levels[0]]

    for l in levels[1:]:
        if l / current_cluster[-1] - 1 < tolerance:
            current_cluster.append(l)
        else:
            clusters.append(np.mean(current_cluster))
            current_cluster = [l]
    clusters.append(np.mean(current_cluster))
    return clusters


def calculate_snr_levels(df: pd.DataFrame) -> dict:
    """Hitung 3 level support (S1-S3) dan resistance (R1-R3) dengan
    metode pivot point classic, diperkuat dengan cluster swing high/low
    dari histori harga (10 swing terakhir).

    Returns dict dengan key: s1, s2, s3, r1, r2, r3 (S1>S2>S3, R1<R2<R3).
    """
    last_high = float(df["High"].iloc[-1])
    last_low = float(df["Low"].iloc[-1])
    last_close = float(df["Close"].iloc[-1])

    pivot = (last_high + last_low + last_close) / 3
    range_hl = last_high - last_low

    r1 = pivot + range_hl * 0.382
    r2 = pivot + range_hl * 0.618
    r3 = pivot + range_hl

    s1 = pivot - range_hl * 0.382
    s2 = pivot - range_hl * 0.618
    s3 = pivot - range_hl

    swing_highs = []
    swing_lows = []
    for i in range(5, len(df) - 5):
        if df["High"].iloc[i] == df["High"].iloc[i - 5:i + 6].max():
            swing_highs.append(df["High"].iloc[i])
        if df["Low"].iloc[i] == df["Low"].iloc[i - 5:i + 6].min():
            swing_lows.append(df["Low"].iloc[i])

    support_levels = [s1, s2, s3] + swing_lows[-10:]
    resistance_levels = [r1, r2, r3] + swing_highs[-10:]

    clustered_supports = _cluster_levels(support_levels)[:3]
    clustered_resistances = _cluster_levels(resistance_levels)[:3]

    while len(clustered_supports) < 3:
        base = clustered_supports[-1] if clustered_supports else s3
        clustered_supports.append(base * 0.96)
    while len(clustered_resistances) < 3:
        base = clustered_resistances[-1] if clustered_resistances else r3
        clustered_resistances.append(base * 1.04)

    clustered_supports = sorted(clustered_supports, reverse=True)
    clustered_resistances = sorted(clustered_resistances)

    return {
        "s1": clustered_supports[0], "s2": clustered_supports[1], "s3": clustered_supports[2],
        "r1": clustered_resistances[0], "r2": clustered_resistances[1], "r3": clustered_resistances[2],
    }


def generate_snr(df: pd.DataFrame, ticker: str, output_path: str = None) -> str | None:
    """Generate chart SNR 3-panel: price (candlestick+MA+S/R), volume, RSI.

    df: DataFrame OHLCV yang sudah didownload & dibersihkan oleh caller.
    Returns: path file PNG, atau None kalau data tidak cukup (< 50 baris).
    """
    try:
        if len(df) < 50:
            return None

        df = df.copy()
        df["MA5"] = df["Close"].rolling(5).mean()
        df["MA20"] = df["Close"].rolling(20).mean()
        df["MA50"] = df["Close"].rolling(50).mean()
        df["MA200"] = df["Close"].rolling(200).mean()

        levels = calculate_snr_levels(df)
        s1_val, s2_val, s3_val = levels["s1"], levels["s2"], levels["s3"]
        r1_val, r2_val, r3_val = levels["r1"], levels["r2"], levels["r3"]

        rsi = calculate_rsi(df["Close"])
        last_rsi = float(rsi.iloc[-1])
        current_price = float(df["Close"].iloc[-1])

        fig = plt.figure(figsize=(16, 12), facecolor='#0d1117')
        fig.patch.set_facecolor('#0d1117')
        gs = GridSpec(3, 1, height_ratios=[3, 1, 1], hspace=0.08)

        # ===== MAIN PRICE CHART =====
        ax1 = fig.add_subplot(gs[0])
        ax1.set_facecolor('#161b22')
        ax1.grid(True, alpha=0.15, color='gray', linestyle='-', linewidth=0.5)

        x = range(len(df))
        width = 0.6
        for i in range(len(df)):
            open_p = df['Open'].iloc[i]
            close_p = df['Close'].iloc[i]
            high_p = df['High'].iloc[i]
            low_p = df['Low'].iloc[i]

            color = '#00ff88' if close_p >= open_p else '#ff4444'
            ax1.plot([i, i], [low_p, high_p], color=color, linewidth=1, alpha=0.5)
            body_bottom = min(open_p, close_p)
            body_height = abs(close_p - open_p)
            if body_height > 0:
                rect = Rectangle((i - width / 2, body_bottom), width, body_height,
                                  facecolor=color, alpha=0.8, edgecolor=color, linewidth=0.5)
                ax1.add_patch(rect)

        ax1.plot(x, df['MA5'], color='#ff8c00', linewidth=1.5, label='MA5', alpha=0.9)
        ax1.plot(x, df['MA20'], color='#ffd700', linewidth=1.5, label='MA20', alpha=0.9)
        ax1.plot(x, df['MA50'], color='#00ced1', linewidth=1.5, label='MA50', alpha=0.9)
        ax1.plot(x, df['MA200'], color='#ff69b4', linewidth=1.5, label='MA200', alpha=0.9)

        ax1.axhline(y=r1_val, color='#ff6b6b', linestyle='--', alpha=0.8, linewidth=1.5)
        ax1.axhline(y=r2_val, color='#ff6b6b', linestyle='--', alpha=0.6, linewidth=1)
        ax1.axhline(y=r3_val, color='#ff6b6b', linestyle='--', alpha=0.4, linewidth=1)
        ax1.axhline(y=s1_val, color='#00d2ff', linestyle='--', alpha=0.8, linewidth=1.5)
        ax1.axhline(y=s2_val, color='#00d2ff', linestyle='--', alpha=0.6, linewidth=1)
        ax1.axhline(y=s3_val, color='#00d2ff', linestyle='--', alpha=0.4, linewidth=1)
        ax1.axhline(y=current_price, color='#ffffff', linestyle='-', alpha=0.6, linewidth=1)

        ax1.fill_between(x, s2_val, s1_val, color='#00d2ff', alpha=0.08)
        ax1.fill_between(x, s3_val, s2_val, color='#00d2ff', alpha=0.04)
        ax1.fill_between(x, r1_val, r2_val, color='#ff6b6b', alpha=0.08)
        ax1.fill_between(x, r2_val, r3_val, color='#ff6b6b', alpha=0.04)

        current_idx = len(df) - 1

        ax1.text(current_idx + 3, r1_val, f'R1: {int(r1_val)}', color='#ff6b6b', fontsize=9,
                  fontweight='bold', bbox=dict(boxstyle='round,pad=0.3', facecolor='#1a1a2e', alpha=0.8))
        ax1.text(current_idx + 3, r2_val, f'R2: {int(r2_val)}', color='#ff6b6b', fontsize=8, alpha=0.8,
                  bbox=dict(boxstyle='round,pad=0.2', facecolor='#1a1a2e', alpha=0.6))
        ax1.text(current_idx + 3, r3_val, f'R3: {int(r3_val)}', color='#ff6b6b', fontsize=8, alpha=0.6,
                  bbox=dict(boxstyle='round,pad=0.2', facecolor='#1a1a2e', alpha=0.5))
        ax1.text(current_idx + 3, s1_val, f'S1: {int(s1_val)}', color='#00d2ff', fontsize=9,
                  fontweight='bold', bbox=dict(boxstyle='round,pad=0.3', facecolor='#1a1a2e', alpha=0.8))
        ax1.text(current_idx + 3, s2_val, f'S2: {int(s2_val)}', color='#00d2ff', fontsize=8, alpha=0.8,
                  bbox=dict(boxstyle='round,pad=0.2', facecolor='#1a1a2e', alpha=0.6))
        ax1.text(current_idx + 3, s3_val, f'S3: {int(s3_val)}', color='#00d2ff', fontsize=8, alpha=0.6,
                  bbox=dict(boxstyle='round,pad=0.2', facecolor='#1a1a2e', alpha=0.5))
        ax1.text(current_idx + 3, current_price, f'Price: {int(current_price)}', color='white', fontsize=9,
                  fontweight='bold', bbox=dict(boxstyle='round,pad=0.3', facecolor='#1a1a2e', alpha=0.8))

        info_text = f"""Last: {int(current_price)}
S1: {int(s1_val)}
S2: {int(s2_val)}
R1: {int(r1_val)}
R2: {int(r2_val)}
RSI: {last_rsi:.1f}"""
        ax1.text(0.98, 0.97, to_chart_safe(info_text), transform=ax1.transAxes, fontsize=9,
                  verticalalignment='top', horizontalalignment='right',
                  bbox=dict(boxstyle='round', facecolor='#1a1a2e', alpha=0.85),
                  color='white', fontfamily='monospace')

        ax1.set_ylabel('Harga (Rp)', color='white', fontsize=11, fontweight='bold')
        ax1.tick_params(colors='white', labelsize=9)
        ax1.legend(loc='upper left', facecolor='#1a1a2e', labelcolor='white', framealpha=0.9, fontsize=9)

        # ===== VOLUME SUBPLOT =====
        ax2 = fig.add_subplot(gs[1], sharex=ax1)
        ax2.set_facecolor('#161b22')
        ax2.grid(True, alpha=0.15, color='gray', linestyle='-', linewidth=0.5)

        colors_vol = ['#00ff88' if df['Close'].iloc[i] >= df['Open'].iloc[i] else '#ff4444'
                      for i in range(len(df))]
        ax2.bar(x, df['Volume'], color=colors_vol, alpha=0.6, width=0.8)

        vol_ma20 = df['Volume'].rolling(20).mean()
        ax2.plot(x, vol_ma20, color='#ffd700', linewidth=1.5, label='Volume MA20', alpha=0.9)

        avg_vol = vol_ma20.iloc[-1]
        for i in range(len(df)):
            if df['Volume'].iloc[i] > avg_vol * 1.1:
                ax2.bar(i, df['Volume'].iloc[i], color='#ffd700', alpha=0.8, width=0.8)

        ax2.set_ylabel('Volume', color='white', fontsize=11, fontweight='bold')
        ax2.tick_params(colors='white', labelsize=9)
        ax2.legend(loc='upper left', facecolor='#1a1a2e', labelcolor='white', fontsize=9)

        # ===== RSI SUBPLOT =====
        ax3 = fig.add_subplot(gs[2], sharex=ax1)
        ax3.set_facecolor('#161b22')
        ax3.grid(True, alpha=0.15, color='gray', linestyle='-', linewidth=0.5)

        ax3.plot(x, rsi, color='#9b59b6', linewidth=1.5, label='RSI(14)')
        ax3.axhline(y=70, color='#ff6b6b', linestyle='--', alpha=0.7, linewidth=1, label='Overbought (70)')
        ax3.axhline(y=30, color='#00d2ff', linestyle='--', alpha=0.7, linewidth=1, label='Oversold (30)')
        ax3.fill_between(x, 30, 70, color='#4d4d4d', alpha=0.2)

        ax3.text(len(df) - 1, last_rsi, f' {last_rsi:.1f}', color='#9b59b6', fontsize=9,
                  fontweight='bold', bbox=dict(boxstyle='round,pad=0.2', facecolor='#1a1a2e', alpha=0.7))

        ax3.set_ylabel('RSI', color='white', fontsize=11, fontweight='bold')
        ax3.set_ylim(0, 100)
        ax3.tick_params(colors='white', labelsize=9)
        ax3.legend(loc='upper left', facecolor='#1a1a2e', labelcolor='white', fontsize=9)

        dates = df.index
        date_positions = range(0, len(df), max(1, len(df) // 12))
        date_labels = [dates[i].strftime('%Y-%b-%d') for i in date_positions]

        for ax in [ax1, ax2, ax3]:
            ax.set_xticks(date_positions)
            ax.set_xticklabels(date_labels, rotation=45, ha='right', color='white', fontsize=8)

        ticker_name = ticker.replace('.JK', '')
        fig.suptitle(to_chart_safe(f'{ticker_name} - BULL - SNR (S/R + MA + RSI)'), color='white',
                      fontsize=14, fontweight='bold', y=0.98)

        plt.tight_layout()

        file_path = output_path or f"{ticker_name}_snr.png"
        plt.savefig(file_path, facecolor='#0d1117', dpi=150, bbox_inches='tight')
        plt.close(fig)
        apply_centered_watermark_to_file(file_path)

        return file_path

    except Exception as e:
        print(f"Error generating SNR chart: {e}")
        plt.close('all')
        return None
