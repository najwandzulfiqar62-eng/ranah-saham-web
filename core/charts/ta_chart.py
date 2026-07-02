# =========================
# CHART: TECHNICAL ANALYSIS (TA)
# =========================
# FITUR BARU. Menggantikan "ML Chart" (core/charts/ml_chart.py, yang
# namanya menyiratkan machine learning padahal cuma regresi linear
# sederhana -- lihat catatan jujur di file itu). /ta dirancang meniru
# referensi visual yang diberikan user: candlestick + MA5/MA20/MA50/
# MA200 + Fibonacci + S/R + panel info kotak (trend, Stoch, ADX, Fib,
# Skor, Rekomendasi) + MACD + Volume, dengan watermark logo BESAR di
# TENGAH chart (bukan kecil di pojok seperti chart lain) + teks brand
# "RANAH INVEST" di bawah.
#
# METODOLOGI SKOR & REKOMENDASI: REUSE dari calculate_ai_score_from_df()
# (core/ai_score.py) -- SAMA seperti /compare, supaya /ta KONSISTEN
# dengan /aiscore (skor yang sama persis kalau user cek command yang
# berbeda untuk saham yang sama). TIDAK menulis metodologi skor baru
# lagi -- itu cuma akan menambah kebingungan kalau setiap command
# punya angka "skor" yang beda metodologi & beda hasil untuk saham yang
# sama persis.

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
from matplotlib.patches import Rectangle

from core.indicators import (
    calculate_macd, calculate_stochastic, calculate_adx,
    calculate_fibonacci_levels, calculate_support_resistance_deep,
)
from core.ai_score import calculate_ai_score_from_df
from core.charts.chart_symbols import to_chart_safe
from core.charts.watermark import apply_centered_watermark_to_file

_MA_COLORS = {
    "MA5": "#ff9f43",    # oranye -- konsisten dengan gambar referensi user
    "MA20": "#feca57",   # kuning
    "MA50": "#48dbfb",   # cyan
    "MA200": "#ee5a6f",  # magenta/pink
}


def generate_ta_chart(df, ticker: str, output_path: str = None) -> str | None:
    """Generate chart Technical Analysis lengkap: candlestick + 4 MA +
    Fibonacci + S/R, panel info kotak, MACD, Volume. Watermark logo
    BESAR di tengah + teks brand di bawah (BEDA dari chart lain yang
    pakai watermark kecil di pojok -- lihat core/charts/watermark.py).

    df: DataFrame OHLCV yang sudah didownload & dibersihkan caller.
    Returns: path file PNG, atau None kalau data tidak cukup (<60 baris,
    minimal untuk MA50 + sedikit buffer; MA200 akan NaN di awal kalau
    data <200 baris, tapi itu DITERIMA -- chart tetap dibuat, garis
    MA200 cuma muncul dari titik dia mulai valid).
    """
    try:
        if len(df) < 60:
            return None

        df = df.copy()
        df["MA5"] = df["Close"].rolling(5).mean()
        df["MA20"] = df["Close"].rolling(20).mean()
        df["MA50"] = df["Close"].rolling(50).mean()
        df["MA200"] = df["Close"].rolling(200).mean()  # NaN di awal kalau data <200, itu OK

        macd_line, signal_line, histogram = calculate_macd(df["Close"])
        stoch_k, stoch_d = calculate_stochastic(df)
        adx, plus_di, minus_di = calculate_adx(df)
        fib = calculate_fibonacci_levels(df, lookback=min(90, len(df)))
        sr = calculate_support_resistance_deep(df)
        ai = calculate_ai_score_from_df(df)

        # Trend label sederhana: ADX < 20 = SIDEWAYS (tren lemah,
        # konsisten dengan threshold Wilder yang dikonfirmasi riset),
        # >= 20 dengan +DI>-DI = UPTREND, >=20 dengan -DI>+DI = DOWNTREND
        last_adx = float(adx.iloc[-1]) if not adx.empty and not _isnan(adx.iloc[-1]) else 0
        last_plus_di = float(plus_di.iloc[-1]) if not plus_di.empty and not _isnan(plus_di.iloc[-1]) else 0
        last_minus_di = float(minus_di.iloc[-1]) if not minus_di.empty and not _isnan(minus_di.iloc[-1]) else 0

        if last_adx < 20:
            trend_label = "SIDEWAYS"
        elif last_plus_di > last_minus_di:
            trend_label = "UPTREND"
        else:
            trend_label = "DOWNTREND"

        last_stoch_k = float(stoch_k.iloc[-1]) if not stoch_k.empty and not _isnan(stoch_k.iloc[-1]) else 50
        last_stoch_d = float(stoch_d.iloc[-1]) if not stoch_d.empty and not _isnan(stoch_d.iloc[-1]) else 50

        # ===== FIGURE SETUP =====
        fig = plt.figure(figsize=(13, 10), facecolor="#0a0e17")
        gs = GridSpec(3, 1, height_ratios=[3, 1, 1], hspace=0.25)

        n = len(df)
        x = range(n)

        # ===== PANEL 1: PRICE + CANDLESTICK + MA + FIB + S/R =====
        ax1 = plt.subplot(gs[0])
        ax1.set_facecolor("#0a0e17")

        for i in range(n):
            o, h, l, c = (float(df["Open"].iloc[i]), float(df["High"].iloc[i]),
                          float(df["Low"].iloc[i]), float(df["Close"].iloc[i]))
            color = "#26de81" if c >= o else "#fc5c65"
            ax1.plot([i, i], [l, h], color=color, linewidth=0.6, alpha=0.85)
            body_lo, body_hi = min(o, c), max(o, c)
            body_h = max(body_hi - body_lo, c * 0.001)
            ax1.add_patch(Rectangle((i - 0.3, body_lo), 0.6, body_h,
                                      facecolor=color, edgecolor=color, linewidth=0.3))

        for ma_name, color in _MA_COLORS.items():
            series = df[ma_name]
            ax1.plot(x, series, color=color, linewidth=1.3, label=ma_name, alpha=0.95)

        # Fibonacci levels (garis putus-putus tipis)
        ax1.axhline(y=fib["fib_382"], color="#a29bfe", linestyle=":", linewidth=0.8, alpha=0.6)
        ax1.axhline(y=fib["fib_618"], color="#a29bfe", linestyle=":", linewidth=0.8, alpha=0.6)

        # Support & Resistance (garis putus-putus, label di kanan).
        # CATATAN: kalau dua level berdekatan secara harga (bisa terjadi
        # tergantung volatilitas saham -- formula pivot point tidak selalu
        # menghasilkan jarak antar level yang lega), label teks bisa
        # saling bertumpuk dan jadi tidak terbaca. Geser label SEDIKIT
        # secara vertikal kalau jaraknya (dalam unit harga) kurang dari
        # ~3% dari range harga chart, supaya tetap terbaca.
        r1, r2 = sr["R1"], sr["R2"]
        s1, s2 = sr["S1"], sr["S2"]
        price_range = float(df["High"].max() - df["Low"].min())
        min_gap = price_range * 0.035

        levels_to_draw = [(r1, f"R {r1:,.0f}", "#fc5c65"),
                            (r2, f"R {r2:,.0f}", "#fc5c65"),
                            (s1, f"S {s1:,.0f}", "#26de81"),
                            (s2, f"S {s2:,.0f}", "#26de81")]
        levels_to_draw.sort(key=lambda t: t[0], reverse=True)  # urut dari harga tertinggi

        label_y_positions = []
        for level, label, color in levels_to_draw:
            ax1.axhline(y=level, color=color, linestyle="--", linewidth=1.0, alpha=0.7)
            label_y = level
            # Kalau posisi label ini terlalu dekat dengan label SEBELUMNYA
            # yang sudah ditempatkan, geser ke bawah supaya tidak bertumpuk
            for prev_y in label_y_positions:
                if abs(label_y - prev_y) < min_gap:
                    label_y = prev_y - min_gap
            label_y_positions.append(label_y)
            ax1.annotate(label, xy=(n - 1, level), xytext=(8, (label_y - level) / price_range * 400),
                          textcoords="offset points", color=color, fontsize=9,
                          fontweight="bold", va="center")

        ax1.set_title(to_chart_safe(f"{ticker} — Technical Analysis"),
                       color="white", fontsize=15, fontweight="bold", pad=14)
        ax1.set_ylabel("Harga", color="#8b949e")
        ax1.tick_params(colors="#8b949e")
        for spine in ax1.spines.values():
            spine.set_edgecolor("#30363d")
        ax1.grid(True, color="#1f2937", linewidth=0.4, alpha=0.5)
        ax1.legend(loc="upper left", facecolor="#161b22", edgecolor="#30363d",
                    labelcolor="white", fontsize=9, ncol=4)
        ax1.set_xlim(-1, n + max(8, int(n * 0.08)))  # ruang ekstra kanan untuk label R/S

        # ===== Panel info kotak (mirip kotak hijau di gambar referensi) =====
        if ai:
            rekom_text = ai["recommendation"]
            skor_text = f"{ai['score']:.0f}"
        else:
            rekom_text = "N/A"
            skor_text = "N/A"

        info_lines = [
            f"Trend: {trend_label}",
            f"Stoch: K {last_stoch_k:.0f} D {last_stoch_d:.0f}",
            f"ADX: {last_adx:.0f}",
            f"Fib 0.382: {fib['fib_382']:,.0f}",
            f"Fib 0.618: {fib['fib_618']:,.0f}",
            f"Skor: {skor_text}",
            f"Rekom: {rekom_text}",
        ]
        info_text = "\n".join(info_lines)
        ax1.text(0.98, 0.97, info_text, transform=ax1.transAxes,
                  fontsize=10, color="white", va="top", ha="right",
                  linespacing=1.7,
                  bbox=dict(boxstyle="round,pad=0.6", facecolor="#0a0e17",
                            edgecolor="#26de81", linewidth=1.5, alpha=0.92))

        # ===== PANEL 2: VOLUME =====
        ax2 = plt.subplot(gs[1])
        ax2.set_facecolor("#0a0e17")
        vol_colors = ["#26de81" if float(df["Close"].iloc[i]) >= float(df["Open"].iloc[i])
                      else "#fc5c65" for i in range(n)]
        ax2.bar(x, df["Volume"], color=vol_colors, alpha=0.75, width=0.8)
        ax2.set_ylabel("Volume", color="#8b949e", fontsize=9)
        ax2.tick_params(colors="#8b949e")
        for spine in ax2.spines.values():
            spine.set_edgecolor("#30363d")
        ax2.grid(True, color="#1f2937", linewidth=0.4, alpha=0.5)
        ax2.set_xlim(-1, n + max(8, int(n * 0.08)))

        # ===== PANEL 3: MACD =====
        ax3 = plt.subplot(gs[2])
        ax3.set_facecolor("#0a0e17")
        hist_colors = ["#26de81" if v >= 0 else "#fc5c65" for v in histogram]
        ax3.bar(x, histogram, color=hist_colors, alpha=0.6, width=0.8)
        ax3.plot(x, macd_line, color="#48dbfb", linewidth=1.2, label="MACD")
        ax3.plot(x, signal_line, color="#feca57", linewidth=1.2, label="Signal")
        ax3.axhline(y=0, color="#444444", linewidth=0.6)
        ax3.set_ylabel("MACD", color="#8b949e", fontsize=9)
        ax3.tick_params(colors="#8b949e")
        for spine in ax3.spines.values():
            spine.set_edgecolor("#30363d")
        ax3.grid(True, color="#1f2937", linewidth=0.4, alpha=0.5)
        ax3.legend(loc="upper left", facecolor="#161b22", edgecolor="#30363d",
                    labelcolor="white", fontsize=8)
        ax3.set_xlim(-1, n + max(8, int(n * 0.08)))

        # Sumbu X tanggal hanya di panel paling bawah
        tick_step = max(1, n // 8)
        tick_positions = list(range(0, n, tick_step))
        tick_labels = [df.index[i].strftime("%Y-%m-%d") if hasattr(df.index[i], "strftime")
                       else str(df.index[i]) for i in tick_positions]
        ax3.set_xticks(tick_positions)
        ax3.set_xticklabels(tick_labels, rotation=30, ha="right", fontsize=8)

        plt.tight_layout()
        file_path = output_path or f"{ticker}_ta.png"
        plt.savefig(file_path, facecolor="#0a0e17", dpi=150, bbox_inches="tight")
        plt.close(fig)

        # Watermark BESAR di tengah (BEDA dari chart lain yang pakai
        # watermark kecil di pojok) + teks brand "RANAH INVEST" di bawah
        apply_centered_watermark_to_file(file_path)

        return file_path

    except Exception as e:
        print(f"Error generating TA chart: {e}")
        plt.close("all")
        return None


def _isnan(val) -> bool:
    """Helper kecil cek NaN tanpa perlu import math/numpy berulang di
    banyak titik -- val bisa float biasa atau NaN dari pandas."""
    return val != val  # trik klasik: NaN tidak pernah sama dengan dirinya sendiri
