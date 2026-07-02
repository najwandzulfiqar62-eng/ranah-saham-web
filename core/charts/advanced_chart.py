# =========================
# CHART: ADVANCED (STOCHASTIC RSI + VOLUME SIGNAL DETECTION)
# =========================
# Migrasi generate_advanced_chart dari main.py lama. Chart ini punya
# ALGORITMA DETEKSI SINYAL (bukan cuma plotting statis): mendeteksi
# titik buy/sell berdasarkan crossover StochRSI %K/%D di zona oversold/
# overbought, dikonfirmasi volume spike. Karena ini logic yang menentukan
# sinyal yang dilihat user, dipisah jadi fungsi tersendiri yang bisa
# ditest independen dari plotting.

import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from matplotlib.gridspec import GridSpec

from core.indicators import calculate_stochrsi
from core.charts.chart_symbols import to_chart_safe
from core.charts.watermark import apply_centered_watermark_to_file


def detect_buy_sell_signals(df: pd.DataFrame, stoch_k: pd.Series, stoch_d: pd.Series,
                              volume: pd.Series, vol_ma20: pd.Series) -> tuple[list, list]:
    """Deteksi sinyal BUY dan SELL berdasarkan:
    - BUY: StochRSI %K dan %D di bawah 20 (oversold) + %K baru saja cross
      ke atas %D + volume > 1.5x MA20.
    - SELL: StochRSI %K dan %D di atas 80 (overbought) + %K baru saja
      cross ke bawah %D + volume > 1.3x MA20.

    Returns: (buy_signals, sell_signals), masing-masing list of (index, price).
    """
    buy_signals = []
    sell_signals = []

    for i in range(20, len(df) - 1):
        if (stoch_k.iloc[i] < 20 and stoch_d.iloc[i] < 20 and
                stoch_k.iloc[i - 1] <= stoch_d.iloc[i - 1] and stoch_k.iloc[i] > stoch_d.iloc[i] and
                volume.iloc[i] > vol_ma20.iloc[i] * 1.5):
            buy_signals.append((i, df['Low'].iloc[i]))

        if (stoch_k.iloc[i] > 80 and stoch_d.iloc[i] > 80 and
                stoch_k.iloc[i - 1] >= stoch_d.iloc[i - 1] and stoch_k.iloc[i] < stoch_d.iloc[i] and
                volume.iloc[i] > vol_ma20.iloc[i] * 1.3):
            sell_signals.append((i, df['High'].iloc[i]))

    return buy_signals, sell_signals


def generate_advanced_chart(df: pd.DataFrame, ticker_symbol: str, output_path: str = None) -> str | None:
    """Generate chart 4-panel: price+candlestick+BB+S/R+signal markers,
    volume, StochRSI, dan signal summary timeline.

    df: DataFrame OHLCV yang sudah didownload & dibersihkan oleh caller.
    Returns: path file PNG, atau None kalau data tidak cukup (< 50 baris).
    """
    try:
        if len(df) < 50:
            return None

        fig = plt.figure(figsize=(16, 12), facecolor='#1a1a2e')
        fig.patch.set_facecolor('#1a1a2e')
        gs = GridSpec(4, 1, height_ratios=[3, 1, 1, 1], hspace=0.08)

        stoch_k, stoch_d = calculate_stochrsi(df['Close'])
        volume = df['Volume']
        vol_ma20 = volume.rolling(20).mean()
        ma20 = df['Close'].rolling(20).mean()
        ma50 = df['Close'].rolling(50).mean()

        # ===== 1. MAIN PRICE CHART =====
        ax1 = plt.subplot(gs[0])
        ax1.set_facecolor('#16213e')

        width = 0.6
        for i in range(len(df)):
            if df['Close'].iloc[i] >= df['Open'].iloc[i]:
                color = '#00d2ff'
            else:
                color = '#ff6b6b'

            ax1.plot([i, i], [df['Low'].iloc[i], df['High'].iloc[i]], color=color, linewidth=0.8, alpha=0.7)

            body_bottom = min(df['Open'].iloc[i], df['Close'].iloc[i])
            body_height = abs(df['Close'].iloc[i] - df['Open'].iloc[i])
            if body_height > 0:
                rect = Rectangle((i - width / 2, body_bottom), width, body_height,
                                  facecolor=color, alpha=0.7, edgecolor=color, linewidth=0.5)
                ax1.add_patch(rect)

        ax1.plot(range(len(ma20)), ma20, color='#ffd93d', linewidth=1.5, label='MA20', alpha=0.9)
        ax1.plot(range(len(ma50)), ma50, color='#6bcb77', linewidth=1.5, label='MA50', alpha=0.9)

        sma = df['Close'].rolling(20).mean()
        std = df['Close'].rolling(20).std()
        upper_bb = sma + (std * 2)
        lower_bb = sma - (std * 2)
        ax1.fill_between(range(len(df)), lower_bb, upper_bb, color='#4d4d4d', alpha=0.2)

        high_20 = df['High'].rolling(20).max()
        low_20 = df['Low'].rolling(20).min()
        s1 = low_20.iloc[-1]
        r1 = high_20.iloc[-1]
        ax1.axhline(y=r1, color='#ff6b6b', linestyle='--', alpha=0.7, label=f'R1: {r1:.0f}')
        ax1.axhline(y=s1, color='#00d2ff', linestyle='--', alpha=0.7, label=f'S1: {s1:.0f}')

        buy_signals, sell_signals = detect_buy_sell_signals(df, stoch_k, stoch_d, volume, vol_ma20)

        for idx, price in buy_signals[-6:]:
            ax1.scatter(idx, price, color='#00ff00', s=200, marker='^', zorder=5, edgecolors='white', linewidth=2)
        for idx, price in sell_signals[-6:]:
            ax1.scatter(idx, price, color='#ff0000', s=200, marker='v', zorder=5, edgecolors='white', linewidth=2)

        ax1.set_ylabel('Price (Rp)', color='white')
        ax1.tick_params(colors='white')
        ax1.grid(True, alpha=0.2)
        ax1.legend(loc='upper left', facecolor='#1a1a2e', labelcolor='white')

        # ===== 2. VOLUME SUBPLOT =====
        ax2 = plt.subplot(gs[1], sharex=ax1)
        ax2.set_facecolor('#16213e')

        colors_vol = ['#00d2ff' if df['Close'].iloc[i] >= df['Open'].iloc[i] else '#ff6b6b'
                      for i in range(len(df))]
        ax2.bar(range(len(df)), df['Volume'], color=colors_vol, alpha=0.7, width=0.8)

        for i in range(len(df)):
            if df['Volume'].iloc[i] > vol_ma20.iloc[i] * 1.5:
                ax2.bar(i, df['Volume'].iloc[i], color='#ffd93d', alpha=0.9, width=0.8)

        ax2.plot(range(len(vol_ma20)), vol_ma20, color='#ffd93d', linewidth=1.5, label='Volume MA20')
        ax2.set_ylabel('Volume', color='white')
        ax2.tick_params(colors='white')
        ax2.grid(True, alpha=0.2)

        # ===== 3. STOCHASTIC RSI SUBPLOT =====
        ax3 = plt.subplot(gs[2], sharex=ax1)
        ax3.set_facecolor('#16213e')

        ax3.plot(range(len(stoch_k)), stoch_k, color='#00d2ff', linewidth=1.5, label='%K')
        ax3.plot(range(len(stoch_d)), stoch_d, color='#ffd93d', linewidth=1.5, label='%D')
        ax3.axhline(y=80, color='#ff6b6b', linestyle='--', alpha=0.7, label='Overbought (80)')
        ax3.axhline(y=20, color='#00d2ff', linestyle='--', alpha=0.7, label='Oversold (20)')
        ax3.fill_between(range(len(stoch_k)), 20, 80, color='#4d4d4d', alpha=0.2)
        ax3.set_ylabel('Stoch RSI', color='white')
        ax3.set_ylim(0, 100)
        ax3.tick_params(colors='white')
        ax3.grid(True, alpha=0.2)
        ax3.legend(loc='upper left', facecolor='#1a1a2e', labelcolor='white')

        # ===== 4. SIGNAL SUMMARY =====
        ax4 = plt.subplot(gs[3], sharex=ax1)
        ax4.set_facecolor('#16213e')

        signal_line = [0] * len(df)
        for idx, _ in buy_signals:
            signal_line[idx] = 1
        for idx, _ in sell_signals:
            signal_line[idx] = -1

        for i in range(len(df)):
            if signal_line[i] == 1:
                ax4.axvspan(i - 0.5, i + 0.5, alpha=0.5, color='#00ff00')
                ax4.text(i, 0.5, 'BUY', ha='center', va='center', color='white', fontsize=8)
            elif signal_line[i] == -1:
                ax4.axvspan(i - 0.5, i + 0.5, alpha=0.5, color='#ff0000')
                ax4.text(i, -0.5, 'SELL', ha='center', va='center', color='white', fontsize=8)

        ax4.set_ylim(-1.5, 1.5)
        ax4.set_ylabel('Signals', color='white')
        ax4.set_yticks([-1, 0, 1])
        ax4.set_yticklabels(['SELL', 'NEUTRAL', 'BUY'], color='white')
        ax4.tick_params(colors='white')
        ax4.grid(True, alpha=0.2)

        dates = df.index
        date_positions = range(0, len(df), max(1, len(df) // 10))
        date_labels = [dates[i].strftime('%d-%b') for i in date_positions]
        ax4.set_xticks(date_positions)
        ax4.set_xticklabels(date_labels, rotation=45, ha='right', color='white')

        info_text = f"""
Current: {df['Close'].iloc[-1]:,.0f}
Change: {((df['Close'].iloc[-1]/df['Close'].iloc[-2])-1)*100:+.2f}%
Stoch K: {stoch_k.iloc[-1]:.1f}
Stoch D: {stoch_d.iloc[-1]:.1f}
Volume: {df['Volume'].iloc[-1]/vol_ma20.iloc[-1]:.1f}x MA20
"""
        ax1.text(0.98, 0.97, to_chart_safe(info_text), transform=ax1.transAxes, fontsize=9,
                  verticalalignment='top', horizontalalignment='right',
                  bbox=dict(boxstyle='round', facecolor='#1a1a2e', alpha=0.8), color='white')

        ticker_name = ticker_symbol.replace('.JK', '')
        plt.suptitle(to_chart_safe(f'{ticker_name} - Stochastic RSI + Volume Analysis'), color='white',
                      fontsize=14, fontweight='bold')

        plt.tight_layout()

        file_path = output_path or f"{ticker_name}_advanced_chart.png"
        plt.savefig(file_path, facecolor='#1a1a2e', dpi=150, bbox_inches='tight')
        plt.close(fig)
        apply_centered_watermark_to_file(file_path)

        return file_path

    except Exception as e:
        print(f"Error generating advanced chart: {e}")
        plt.close('all')
        return None
