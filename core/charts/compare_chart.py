# =========================
# CHART: COMPARE SAHAM
# =========================
# FITUR BARU. Visualisasi perbandingan 2 saham: panel atas garis harga
# TERNORMALISASI (% return dari hari pertama window, BUKAN harga
# absolut -- supaya 2 saham dengan skala harga sangat berbeda, mis.
# BBCA Rp5000-an vs GOTO Rp70-an, tetap bisa dibandingkan visual di
# chart yang sama secara adil), panel bawah bar chart AI Score
# side-by-side.

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
import numpy as np

from core.charts.watermark import apply_centered_watermark_to_file

_COLOR_1 = "#00d2ff"  # cyan -- konsisten dengan warna candle bullish di chart lain
_COLOR_2 = "#ffb84d"  # oranye -- kontras jelas dari warna 1, beda dari merah (yang berarti bearish di chart lain)


def generate_compare_chart(df1, df2, name1: str, name2: str,
                             s1: dict, s2: dict,
                             output_path: str = None) -> str | None:
    """Generate chart perbandingan 2 saham: garis return ternormalisasi
    (atas) + bar chart AI Score (bawah).

    df1, df2: DataFrame OHLCV yang sudah didownload & dibersihkan caller.
    s1, s2: hasil analyze_for_compare() (core/compare.py) -- dict berisi
            'score', 'rating', dll. Tidak boleh None (caller sudah cek).
    Returns path file PNG, atau None kalau gagal."""
    try:
        # Samakan panjang window ke yang lebih pendek dari keduanya,
        # supaya kedua garis mulai dari titik yang sebanding (hari ke-0
        # window = index -min(len(df1),len(df2)))
        window = min(len(df1), len(df2), 120)  # cap 120 hari supaya chart tidak terlalu padat
        d1 = df1.tail(window).reset_index(drop=True)
        d2 = df2.tail(window).reset_index(drop=True)

        # Normalisasi ke % return dari harga AWAL window (bukan harga
        # absolut) -- ini yang membuat 2 saham beda skala harga bisa
        # dibandingkan visual secara adil di sumbu Y yang sama
        norm1 = (d1["Close"] / float(d1["Close"].iloc[0]) - 1) * 100
        norm2 = (d2["Close"] / float(d2["Close"].iloc[0]) - 1) * 100

        fig = plt.figure(figsize=(12, 8), facecolor="#0d1117")
        gs = GridSpec(2, 1, height_ratios=[2.2, 1], hspace=0.35)

        # ===== PANEL ATAS: garis return ternormalisasi =====
        ax1 = plt.subplot(gs[0])
        ax1.set_facecolor("#161b22")
        ax1.plot(range(window), norm1, color=_COLOR_1, linewidth=2, label=name1)
        ax1.plot(range(window), norm2, color=_COLOR_2, linewidth=2, label=name2)
        ax1.axhline(y=0, color="#444444", linewidth=0.8, linestyle="--")
        ax1.fill_between(range(window), norm1, 0, color=_COLOR_1, alpha=0.08)
        ax1.fill_between(range(window), norm2, 0, color=_COLOR_2, alpha=0.08)

        ax1.set_title(f"{name1} vs {name2} — Return {window} Hari Terakhir",
                       color="#e6edf3", fontsize=13, fontweight="bold", pad=12)
        ax1.set_ylabel("Return (%)", color="#8b949e")
        ax1.tick_params(colors="#8b949e")
        for spine in ax1.spines.values():
            spine.set_edgecolor("#30363d")
        ax1.grid(axis="y", color="#30363d", linewidth=0.4, alpha=0.6)
        ax1.legend(loc="best", facecolor="#161b22", edgecolor="#30363d",
                    labelcolor="#e6edf3", fontsize=10, framealpha=0.85)

        # Label nilai akhir di ujung kanan masing-masing garis
        final1 = float(norm1.iloc[-1])
        final2 = float(norm2.iloc[-1])
        ax1.annotate(f"{final1:+.1f}%", xy=(window - 1, final1), color=_COLOR_1,
                      fontsize=10, fontweight="bold", xytext=(8, 0),
                      textcoords="offset points", va="center")
        ax1.annotate(f"{final2:+.1f}%", xy=(window - 1, final2), color=_COLOR_2,
                      fontsize=10, fontweight="bold", xytext=(8, 0),
                      textcoords="offset points", va="center")

        # ===== PANEL BAWAH: bar chart AI Score side-by-side =====
        ax2 = plt.subplot(gs[1])
        ax2.set_facecolor("#161b22")

        categories = ["AI Score", "RSI", "Volume Ratio"]
        vals1 = [s1["score"], s1["rsi"], s1["vol_ratio"] * 20]  # vol_ratio di-scale x20 supaya sebanding skalanya
        vals2 = [s2["score"], s2["rsi"], s2["vol_ratio"] * 20]

        x = np.arange(len(categories))
        width = 0.35
        bars1 = ax2.bar(x - width/2, vals1, width, color=_COLOR_1, label=name1, alpha=0.9)
        bars2 = ax2.bar(x + width/2, vals2, width, color=_COLOR_2, label=name2, alpha=0.9)

        for bars, vals, raw in [(bars1, vals1, [s1["score"], s1["rsi"], s1["vol_ratio"]]),
                                  (bars2, vals2, [s2["score"], s2["rsi"], s2["vol_ratio"]])]:
            for bar, val, r in zip(bars, vals, raw):
                label = f"{r:.1f}x" if bar is bars1[2] or bar is bars2[2] else f"{r:.0f}"
                ax2.annotate(label, xy=(bar.get_x() + bar.get_width()/2, val),
                              xytext=(0, 3), textcoords="offset points",
                              ha="center", fontsize=8, color="#e6edf3")

        ax2.set_xticks(x)
        ax2.set_xticklabels(categories, color="#8b949e")
        ax2.tick_params(colors="#8b949e")
        for spine in ax2.spines.values():
            spine.set_edgecolor("#30363d")
        ax2.grid(axis="y", color="#30363d", linewidth=0.4, alpha=0.6)
        ax2.legend(loc="upper right", facecolor="#161b22", edgecolor="#30363d",
                    labelcolor="#e6edf3", fontsize=9)
        ax2.set_title("Indikator Kunci (Volume Ratio diskalakan x20 untuk visualisasi)",
                       color="#8b949e", fontsize=9, style="italic")

        plt.tight_layout()
        file_path = output_path or f"{name1}_vs_{name2}_compare.png"
        plt.savefig(file_path, facecolor="#0d1117", dpi=150, bbox_inches="tight")
        plt.close(fig)
        apply_centered_watermark_to_file(file_path)

        return file_path

    except Exception as e:
        print(f"Error generating compare chart: {e}")
        plt.close("all")
        return None
