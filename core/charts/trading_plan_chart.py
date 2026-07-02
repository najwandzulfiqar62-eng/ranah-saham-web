# =========================
# CHART: TRADING PLAN
# =========================
# Migrasi generate_trading_plan_chart dari main.py lama. Logic plotting
# DIPERTAHANKAN IDENTIK -- semua warna, style, layout sama persis, cuma
# dipisah dari download data (parameter df sekarang diterima dari luar,
# bukan didownload di dalam fungsi ini) supaya bisa dipanggil dari
# handler async tanpa perlu nested blocking call.

import matplotlib
matplotlib.use("Agg")  # backend non-interaktif, wajib untuk server tanpa display
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

from core.charts.chart_symbols import to_chart_safe
from core.charts.watermark import apply_centered_watermark_to_file


def generate_trading_plan_chart(df, ticker_symbol: str, sr: dict, current_price: float,
                                  atr: float, entry_levels: dict = None,
                                  tp_levels: dict = None, sl_levels: dict = None,
                                  output_path: str = None) -> str | None:
    """Generate chart trading plan 4-panel: candlestick+S/R+entry (kiri atas),
    info panel (kanan atas), volume (kiri bawah), tabel entry/SL/TP (kanan bawah).

    df: DataFrame OHLCV yang SUDAH didownload & dibersihkan oleh caller.
    output_path: path file output. Kalau None, dibuat otomatis di direktori kerja.

    Returns: path file PNG yang dihasilkan, atau None kalau data tidak cukup.
    """
    try:
        if len(df) < 50:
            return None

        fig = plt.figure(figsize=(18, 12), facecolor='#0d1117')
        fig.patch.set_facecolor('#0d1117')

        gs = fig.add_gridspec(2, 2, height_ratios=[3, 1.2], width_ratios=[3, 1],
                               hspace=0.1, wspace=0.05)

        # ===== MAIN PRICE CHART (kiri atas) =====
        ax1 = fig.add_subplot(gs[0, 0])
        ax1.set_facecolor('#161b22')
        ax1.grid(True, alpha=0.15, color='gray', linestyle='-', linewidth=0.5)

        width = 0.6
        for i in range(len(df)):
            open_p = df['Open'].iloc[i]
            close_p = df['Close'].iloc[i]
            high_p = df['High'].iloc[i]
            low_p = df['Low'].iloc[i]

            if close_p >= open_p:
                color = '#00ff88'
                body_color = '#00ff88'
                alpha = 0.7
            else:
                color = '#ff4444'
                body_color = '#ff4444'
                alpha = 0.7

            ax1.plot([i, i], [low_p, high_p], color=color, linewidth=1, alpha=0.5)

            body_bottom = min(open_p, close_p)
            body_height = abs(close_p - open_p)
            if body_height > 0:
                rect = Rectangle((i - width / 2, body_bottom), width, body_height,
                                  facecolor=body_color, alpha=alpha, edgecolor=color, linewidth=0.5)
                ax1.add_patch(rect)

        x = range(len(df))
        ma20 = df['Close'].rolling(20).mean()
        ma50 = df['Close'].rolling(50).mean()
        ax1.plot(x, ma20, color='#ffd93d', linewidth=1.5, label='MA20', alpha=0.9)
        ax1.plot(x, ma50, color='#6bcb77', linewidth=1.5, label='MA50', alpha=0.9)

        current_idx = len(df) - 1

        ax1.axhline(y=sr['R1'], color='#ff6b6b', linestyle='--', alpha=0.8, linewidth=1.5)
        ax1.axhline(y=sr['R2'], color='#ff6b6b', linestyle='--', alpha=0.5, linewidth=1)
        ax1.axhline(y=sr['S1'], color='#00d2ff', linestyle='--', alpha=0.8, linewidth=1.5)
        ax1.axhline(y=sr['S2'], color='#00d2ff', linestyle='--', alpha=0.5, linewidth=1)
        ax1.axhline(y=current_price, color='#ffffff', linestyle='-', alpha=0.6, linewidth=1)

        entry_styles = {
            'normal': {'color': '#00ff88', 'linestyle': '-', 'linewidth': 2, 'alpha': 0.9, 'label': to_chart_safe('📊 NORMAL')},
            'pullback': {'color': '#ffa500', 'linestyle': '-', 'linewidth': 2, 'alpha': 0.9, 'label': to_chart_safe('📉 PULLBACK')},
            'deep': {'color': '#ff4444', 'linestyle': '-', 'linewidth': 2, 'alpha': 0.9, 'label': to_chart_safe('🔻 DEEP')},
            'breakout': {'color': '#ff00ff', 'linestyle': '-', 'linewidth': 2, 'alpha': 0.9, 'label': to_chart_safe('🚀 BREAKOUT')},
        }

        if entry_levels:
            for key, entry_price in entry_levels.items():
                if entry_price and key in entry_styles:
                    style = entry_styles[key]
                    ax1.axhline(y=entry_price, color=style['color'], linestyle=style['linestyle'],
                                linewidth=style['linewidth'], alpha=style['alpha'])

        if sl_levels:
            for key, sl_price in sl_levels.items():
                if sl_price and key in entry_styles:
                    ax1.axhline(y=sl_price, color=entry_styles[key]['color'],
                                linestyle=':', alpha=0.7, linewidth=1.5)
                    ax1.text(current_idx + 2, sl_price, f"SL: Rp{sl_price:,.0f}",
                             color=entry_styles[key]['color'], fontsize=7,
                             bbox=dict(boxstyle='round,pad=0.2', facecolor='#1a1a2e', alpha=0.7))

        ax1.fill_between(x, sr['S2'], sr['S1'], color='#00d2ff', alpha=0.08)
        ax1.fill_between(x, sr['R1'], sr['R2'], color='#ff6b6b', alpha=0.08)

        ax1.text(current_idx + 2, sr['R1'], f'R1: {sr["R1"]:,.0f}', color='#ff6b6b', fontsize=9,
                  fontweight='bold', bbox=dict(boxstyle='round,pad=0.3', facecolor='#1a1a2e', alpha=0.8))
        ax1.text(current_idx + 2, sr['R2'], f'R2: {sr["R2"]:,.0f}', color='#ff6b6b', fontsize=8, alpha=0.7)
        ax1.text(current_idx + 2, sr['S1'], f'S1: {sr["S1"]:,.0f}', color='#00d2ff', fontsize=9,
                  fontweight='bold', bbox=dict(boxstyle='round,pad=0.3', facecolor='#1a1a2e', alpha=0.8))
        ax1.text(current_idx + 2, sr['S2'], f'S2: {sr["S2"]:,.0f}', color='#00d2ff', fontsize=8, alpha=0.7)
        ax1.text(current_idx + 2, current_price, f'Current: {current_price:,.0f}', color='white', fontsize=9,
                  fontweight='bold', bbox=dict(boxstyle='round,pad=0.3', facecolor='#1a1a2e', alpha=0.8))

        if entry_levels:
            for key, entry_price in entry_levels.items():
                if entry_price and key in entry_styles:
                    ax1.text(current_idx + 2, entry_price, f"{entry_styles[key]['label']}: Rp{entry_price:,.0f}",
                              color=entry_styles[key]['color'], fontsize=8,
                              bbox=dict(boxstyle='round,pad=0.2', facecolor='#1a1a2e', alpha=0.7))

        ax1.set_ylabel('Harga (Rp)', color='white', fontsize=11, fontweight='bold')
        ax1.tick_params(colors='white', labelsize=9)
        ax1.legend(loc='upper left', facecolor='#1a1a2e', labelcolor='white', framealpha=0.9, fontsize=9)
        ax1.set_xlim(-2, len(df) + 15)

        # ===== INFO PANEL (kanan atas) =====
        ax2 = fig.add_subplot(gs[0, 1])
        ax2.set_facecolor('#161b22')
        ax2.axis('off')

        info_text = f"""
╔══════════════════════════════╗
║     📊 TRADING PLAN INFO     ║
╠══════════════════════════════╣
║ 💰 Current: Rp{current_price:,.0f}
║ 📈 ATR(14):  Rp{atr:,.0f}
╠══════════════════════════════╣
║ 🎯 BEST RISK:REWARD:
"""
        if tp_levels:
            best_rr = 0
            best_key = 'normal'
            for key, tp in tp_levels.items():
                rr = tp.get('rr3', 0)
                if rr > best_rr:
                    best_rr = rr
                    best_key = key

            entry_map = {'normal': 'NORMAL', 'pullback': 'PULLBACK', 'deep': 'DEEP', 'breakout': 'BREAKOUT'}
            info_text += f"║   {entry_map.get(best_key, best_key)} → 1:{best_rr}\n"

        info_text += f"""
╠══════════════════════════════╣
║ 📐 SUPPORT & RESISTANCE:      ║
║   R1: Rp{sr['R1']:,.0f}
║   R2: Rp{sr['R2']:,.0f}
║   S1: Rp{sr['S1']:,.0f}
║   S2: Rp{sr['S2']:,.0f}
╠══════════════════════════════╣
║ 💡 ZONA ENTRY:                ║
║   🟢 S1-S2 = Akumulasi
║   🟡 Current = Normal
║   🔴 R1+ = Breakout
╚══════════════════════════════╝
"""
        ax2.text(0.05, 0.95, to_chart_safe(info_text), transform=ax2.transAxes, fontsize=9,
                  verticalalignment='top', color='white', fontfamily='monospace')

        # ===== VOLUME CHART (bawah kiri) =====
        ax3 = fig.add_subplot(gs[1, 0])
        ax3.set_facecolor('#161b22')
        ax3.grid(True, alpha=0.15, color='gray', linestyle='-', linewidth=0.5)

        colors_vol = ['#00ff88' if df['Close'].iloc[i] >= df['Open'].iloc[i] else '#ff4444'
                      for i in range(len(df))]
        ax3.bar(x, df['Volume'], color=colors_vol, alpha=0.6, width=0.8)

        vol_ma20 = df['Volume'].rolling(20).mean()
        ax3.plot(x, vol_ma20, color='#ffd93d', linewidth=1.5, label='Volume MA20', alpha=0.9)

        avg_vol = vol_ma20.iloc[-1]
        for i in range(len(df)):
            if df['Volume'].iloc[i] > avg_vol * 1.5:
                ax3.bar(i, df['Volume'].iloc[i], color='#ffd93d', alpha=0.9, width=0.8)

        ax3.set_ylabel('Volume', color='white', fontsize=11, fontweight='bold')
        ax3.tick_params(colors='white', labelsize=9)
        ax3.legend(loc='upper left', facecolor='#1a1a2e', labelcolor='white', fontsize=9)

        # ===== ENTRY TABLE (bawah kanan) =====
        ax4 = fig.add_subplot(gs[1, 1])
        ax4.set_facecolor('#161b22')
        ax4.axis('off')

        if entry_levels and tp_levels and sl_levels:
            table_data = []
            headers = ['Skenario', 'Entry', 'SL', 'TP1', 'TP2', 'TP3', 'R:R']

            entry_names = {'normal': 'NORMAL', 'pullback': 'PULLBACK', 'deep': 'DEEP', 'breakout': 'BREAKOUT'}

            for key, entry in entry_levels.items():
                if key in tp_levels and key in sl_levels and entry:
                    tp = tp_levels[key]
                    sl = sl_levels[key]
                    row = [
                        entry_names.get(key, key), f"{entry:,.0f}", f"{sl:,.0f}",
                        f"{tp.get('tp1', 0):,.0f}", f"{tp.get('tp2', 0):,.0f}", f"{tp.get('tp3', 0):,.0f}",
                        f"1:{tp.get('rr3', 0)}",
                    ]
                    table_data.append(row)

            table = ax4.table(cellText=table_data, colLabels=headers, loc='center', cellLoc='center',
                               colWidths=[0.14, 0.14, 0.14, 0.14, 0.14, 0.14, 0.16])
            table.auto_set_font_size(False)
            table.set_fontsize(7)
            table.scale(1, 1.5)

            for (i, j), cell in table.get_celld().items():
                if i == 0:
                    cell.set_facecolor('#0d1117')
                    cell.set_text_props(weight='bold', color='#ffd93d')
                else:
                    cell.set_facecolor('#161b22')
                    cell.set_text_props(color='white')
                cell.set_edgecolor('#30363d')
                cell.set_linewidth(0.5)

        dates = df.index
        date_positions = range(0, len(df), max(1, len(df) // 12))
        date_labels = [dates[i].strftime('%d/%m') for i in date_positions]

        for ax in [ax1, ax3]:
            ax.set_xticks(date_positions)
            ax.set_xticklabels(date_labels, rotation=45, ha='right', color='white', fontsize=8)

        ticker_name = ticker_symbol.replace('.JK', '')
        fig.suptitle(f'{ticker_name} - COMPLETE TRADING PLAN', color='white', fontsize=16,
                      fontweight='bold', y=0.98)

        plt.tight_layout()

        file_path = output_path or f"{ticker_name}_trading_plan.png"
        plt.savefig(file_path, facecolor='#0d1117', dpi=150, bbox_inches='tight')
        plt.close(fig)
        apply_centered_watermark_to_file(file_path)

        return file_path

    except Exception as e:
        print(f"Error generating trading plan chart: {e}")
        plt.close('all')  # pastikan figure tidak menumpuk di memori kalau error di tengah jalan
        return None
