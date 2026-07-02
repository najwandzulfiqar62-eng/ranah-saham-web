# =========================
# CHART: IHSG ADVANCED
# =========================
# Migrasi generate_ihsg_advanced_chart dari main.py lama. Chart 4-panel:
# price (candlestick + MA + Bollinger + Fibonacci + SMC overlay), RSI,
# MACD, volume.
#
# CATATAN: kode lama meng-import "from scipy import stats" tapi TIDAK
# PERNAH memakainya di manapun dalam fungsi ini (sudah dikonfirmasi via
# pyflakes static analysis di awal proses refactor). Import itu dihapus
# di modul ini -- tidak ada perubahan perilaku, cuma menghilangkan
# dependency yang tidak terpakai.
#
# FITUR BARU: overlay SMC (BOS, CHoCH, Order Block, FVG) di panel price.
# CATATAN JUJUR PENTING: ini ditambahkan sebagai KONTEKS VISUAL TAMBAHAN,
# BUKAN klaim bahwa SMC meningkatkan akurasi prediksi arah IHSG. Setelah
# riset (Juni 2026): tidak ada satupun jurnal akademik yang mengukur
# akurasi SMC secara kuantitatif -- ini metodologi price-action
# diskresioner (StrategyQuant, Alchemy Markets, ICT, ratusan sumber
# edukasi/marketing trading, BUKAN penelitian terukur). Prediksi arah
# IHSG di /ihsg (analyze_ihsg_with_backtest) TETAP berbasis indikator
# teknikal yang sudah divalidasi via backtest historis SENDIRI (lihat
# core/ihsg/ihsg_analysis.py) -- SMC di chart ini PURE VISUAL, tidak
# masuk ke perhitungan prediction/confidence/backtest_result sama sekali.

import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, FancyBboxPatch
import matplotlib.patches as mpatches
from matplotlib.gridspec import GridSpec

from core.indicators import calculate_rsi, calculate_macd, calculate_bollinger_bands
from core.charts.chart_symbols import to_chart_safe
from core.charts.watermark import apply_centered_watermark_to_file
from core.smc import detect_bos_choch, detect_order_blocks, detect_fvg


def _overlay_smc(ax1, ihsg: pd.DataFrame, x_range) -> list:
    """Overlay elemen SMC (BOS/CHoCH terbaru, 1 Order Block, 1 FVG
    terbaru) ke panel price chart. Dibatasi jumlahnya supaya chart
    tidak terlalu ramai -- prioritas keterbacaan di atas kelengkapan.

    Returns list of legend handle SMC (kosong kalau tidak ada elemen
    yang digambar) -- TIDAK memanggil ax1.legend() sendiri, supaya
    caller bisa menggabungkan dengan legend yang sudah ada (MA20/MA50/
    Fibonacci) jadi SATU legend, bukan saling menimpa."""
    smc_legend_handles = []
    try:
        events = detect_bos_choch(ihsg, left_bars=5, right_bars=5)
        obs = detect_order_blocks(ihsg, left_bars=5, right_bars=5, max_blocks=1)
        fvgs = detect_fvg(ihsg, max_gaps=1, only_unfilled=True)

        n = len(ihsg)

        # BOS/CHoCH: maksimal 2 event paling baru (1 BOS + 1 CHoCH kalau ada)
        bos_events = [e for e in events if e["type"] == "BOS"][-1:]
        choch_events = [e for e in events if e["type"] == "CHOCH"][-1:]

        for ev in bos_events:
            idx = ev["index"]
            if 0 <= idx < n:
                color = "#00ff88" if ev["direction"] == "bullish" else "#ff4d4d"
                ax1.axhline(y=ev["broken_level"], color=color, linestyle="--",
                            linewidth=1.0, alpha=0.6,
                            xmin=max(0, (idx-8)/n), xmax=min(1, (idx+3)/n))
                ax1.annotate(f"BOS {'↑' if ev['direction']=='bullish' else '↓'}",
                             xy=(idx, ev["broken_level"]), color=color, fontsize=7,
                             fontweight="bold",
                             bbox=dict(boxstyle="round,pad=0.15", facecolor="#1a1a2e",
                                       edgecolor=color, alpha=0.85))

        for ev in choch_events:
            idx = ev["index"]
            if 0 <= idx < n:
                color = "#00ff88" if ev["direction"] == "bullish" else "#ff4d4d"
                ax1.axhline(y=ev["broken_level"], color=color, linestyle="-.",
                            linewidth=1.4, alpha=0.75,
                            xmin=max(0, (idx-8)/n), xmax=min(1, (idx+3)/n))
                ax1.annotate(f"CHoCH {'↑' if ev['direction']=='bullish' else '↓'}",
                             xy=(idx, ev["broken_level"]), color=color, fontsize=7,
                             fontweight="bold",
                             bbox=dict(boxstyle="round,pad=0.15", facecolor="#1a1a2e",
                                       edgecolor=color, linewidth=1.2, alpha=0.9))

        # Order Block: 1 zona terbaru
        for ob in obs:
            color = "#00ff88" if ob["type"] == "BULLISH" else "#ff4d4d"
            ob_idx = max(0, ob["ob_index"])
            alpha = 0.18 if ob["is_fresh"] else 0.08
            rect = FancyBboxPatch(
                (ob_idx, ob["zone_low"]), n - ob_idx, ob["zone_high"] - ob["zone_low"],
                boxstyle="square,pad=0", facecolor=color, edgecolor=color,
                linewidth=0.8, alpha=alpha,
            )
            ax1.add_patch(rect)

        # FVG: 1 zona terbaru yang belum terisi
        for gap in fvgs:
            color = "#00ff88" if gap["type"] == "BULLISH" else "#ff4d4d"
            gap_idx = max(0, gap["index"])
            rect = FancyBboxPatch(
                (gap_idx, gap["zone_low"]), n - gap_idx, gap["zone_high"] - gap["zone_low"],
                boxstyle="square,pad=0", facecolor=color, edgecolor=color,
                linewidth=0.8, alpha=0.20, linestyle="--",
            )
            ax1.add_patch(rect)

        # Cuma tambahkan legend SMC kalau memang ada elemen yang digambar
        if bos_events or choch_events or obs or fvgs:
            smc_legend_handles = [
                mpatches.Patch(color="#00ff88", alpha=0.5, label="SMC Bullish (BOS/CHoCH/OB/FVG)"),
                mpatches.Patch(color="#ff4d4d", alpha=0.5, label="SMC Bearish (BOS/CHoCH/OB/FVG)"),
            ]
    except Exception as e:
        print(f"⚠️ Gagal overlay SMC di chart IHSG (chart tetap dibuat tanpa SMC): {e}")

    return smc_legend_handles


def generate_ihsg_advanced_chart(ihsg: pd.DataFrame, output_path: str = None) -> str | None:
    """Generate chart IHSG 4-panel: price+Fibonacci+SMC, RSI, MACD, volume.

    ihsg: DataFrame OHLCV ^JKSE yang sudah didownload & dibersihkan oleh caller.
    Returns: path file PNG, atau None kalau data tidak cukup (< 50 baris).
    """
    try:
        if len(ihsg) < 50:
            return None

        fig = plt.figure(figsize=(16, 12), facecolor='#1a1a2e')
        fig.patch.set_facecolor('#1a1a2e')
        gs = GridSpec(4, 1, height_ratios=[3, 1, 1, 1], hspace=0.08)

        ma20 = ihsg["Close"].rolling(20).mean()
        ma50 = ihsg["Close"].rolling(50).mean()

        _, upper_bb, lower_bb = calculate_bollinger_bands(ihsg["Close"])
        rsi = calculate_rsi(ihsg["Close"])
        macd_line, signal_line, histogram = calculate_macd(ihsg["Close"])

        # ===== MAIN CHART with Fibonacci =====
        ax1 = plt.subplot(gs[0])
        ax1.set_facecolor('#16213e')

        x = range(len(ihsg))

        width = 0.6
        for i in range(len(ihsg)):
            color = '#00d2ff' if ihsg['Close'].iloc[i] >= ihsg['Open'].iloc[i] else '#ff6b6b'

            ax1.plot([i, i], [ihsg['Low'].iloc[i], ihsg['High'].iloc[i]], color=color, linewidth=0.8, alpha=0.7)

            body_bottom = min(ihsg['Open'].iloc[i], ihsg['Close'].iloc[i])
            body_height = abs(ihsg['Close'].iloc[i] - ihsg['Open'].iloc[i])
            if body_height > 0:
                rect = Rectangle((i - width / 2, body_bottom), width, body_height,
                                  facecolor=color, alpha=0.7, edgecolor=color, linewidth=0.5)
                ax1.add_patch(rect)

        ax1.plot(x, ma20, color='#ffd93d', linewidth=1.5, label='MA20', alpha=0.9)
        ax1.plot(x, ma50, color='#6bcb77', linewidth=1.5, label='MA50', alpha=0.9)
        ax1.fill_between(x, lower_bb, upper_bb, color='#4d4d4d', alpha=0.2)

        high_50 = ihsg['High'].tail(50).max()
        low_50 = ihsg['Low'].tail(50).min()
        fib_range = high_50 - low_50
        fib_382 = low_50 + fib_range * 0.382
        fib_500 = low_50 + fib_range * 0.5
        fib_618 = low_50 + fib_range * 0.618

        ax1.axhline(y=fib_618, color='#ff6b6b', linestyle='--', alpha=0.5, label='Fib 61.8%')
        ax1.axhline(y=fib_500, color='#ffd93d', linestyle='--', alpha=0.5, label='Fib 50%')
        ax1.axhline(y=fib_382, color='#00d2ff', linestyle='--', alpha=0.5, label='Fib 38.2%')

        # Overlay SMC (BOS/CHoCH/OB/FVG) -- PURE VISUAL, lihat catatan
        # lengkap di awal file soal kenapa ini tidak masuk ke perhitungan
        # prediksi arah IHSG sama sekali.
        smc_legend_handles = _overlay_smc(ax1, ihsg, x)

        current_price = ihsg['Close'].iloc[-1]
        prev_close = ihsg['Close'].iloc[-2]
        change = ((current_price / prev_close) - 1) * 100

        title = f'IHSG - {ihsg.index[-1].strftime("%d %b %Y")}  |  {current_price:,.0f}  ({change:+.2f}%)'
        ax1.set_title(to_chart_safe(title), color='white', fontsize=12)
        ax1.set_ylabel('Harga', color='white')
        ax1.tick_params(colors='white')
        ax1.grid(True, alpha=0.2)
        # Gabungkan legend asli (MA20/MA50/Fibonacci) DENGAN legend SMC
        # jadi SATU legend -- supaya tidak saling menimpa
        existing_handles, existing_labels = ax1.get_legend_handles_labels()
        ax1.legend(handles=existing_handles + smc_legend_handles,
                   loc='upper left', facecolor='#1a1a2e', labelcolor='white', fontsize=8)

        # ===== RSI =====
        ax2 = plt.subplot(gs[1], sharex=ax1)
        ax2.set_facecolor('#16213e')
        ax2.plot(x, rsi, color='#9b59b6', linewidth=1.5)
        ax2.axhline(y=70, color='#ff6b6b', linestyle='--', alpha=0.7, label='Overbought')
        ax2.axhline(y=30, color='#00d2ff', linestyle='--', alpha=0.7, label='Oversold')
        ax2.fill_between(x, 30, 70, color='#4d4d4d', alpha=0.2)
        ax2.set_ylabel('RSI (14)', color='white')
        ax2.set_ylim(0, 100)
        ax2.tick_params(colors='white')
        ax2.grid(True, alpha=0.2)
        ax2.legend(loc='upper left', facecolor='#1a1a2e', labelcolor='white')

        # ===== MACD =====
        ax3 = plt.subplot(gs[2], sharex=ax1)
        ax3.set_facecolor('#16213e')
        ax3.plot(x, macd_line, color='#00d2ff', linewidth=1.5, label='MACD')
        ax3.plot(x, signal_line, color='#ffd93d', linewidth=1.5, label='Signal')
        ax3.bar(x, histogram, color=['#00ff88' if h >= 0 else '#ff4444' for h in histogram], alpha=0.5, width=0.8)
        ax3.axhline(y=0, color='white', linestyle='-', alpha=0.3)
        ax3.set_ylabel('MACD', color='white')
        ax3.tick_params(colors='white')
        ax3.grid(True, alpha=0.2)
        ax3.legend(loc='upper left', facecolor='#1a1a2e', labelcolor='white')

        # ===== VOLUME =====
        ax4 = plt.subplot(gs[3], sharex=ax1)
        ax4.set_facecolor('#16213e')

        colors_vol = ['#00d2ff' if ihsg['Close'].iloc[i] >= ihsg['Open'].iloc[i] else '#ff6b6b'
                      for i in range(len(ihsg))]
        ax4.bar(x, ihsg['Volume'], color=colors_vol, alpha=0.7, width=0.8)

        vol_ma20 = ihsg['Volume'].rolling(20).mean()
        ax4.plot(x, vol_ma20, color='#ffd93d', linewidth=1.5, label='Volume MA20')

        ax4.set_ylabel('Volume', color='white')
        ax4.set_xlabel('Tanggal', color='white')
        ax4.tick_params(colors='white')
        ax4.grid(True, alpha=0.2)
        ax4.legend(loc='upper left', facecolor='#1a1a2e', labelcolor='white')

        date_positions = range(0, len(ihsg), max(1, len(ihsg) // 10))
        date_labels = [ihsg.index[i].strftime('%d/%m') for i in date_positions]
        ax4.set_xticks(date_positions)
        ax4.set_xticklabels(date_labels, rotation=45, ha='right', color='white')

        plt.tight_layout()

        file_path = output_path or "ihsg_advanced_analysis.png"
        plt.savefig(file_path, facecolor='#1a1a2e', dpi=150, bbox_inches='tight')
        plt.close(fig)
        apply_centered_watermark_to_file(file_path)

        return file_path

    except Exception as e:
        print(f"Error generating advanced IHSG chart: {e}")
        plt.close('all')
        return None
