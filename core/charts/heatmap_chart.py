# =========================
# CHART: SECTOR HEATMAP
# =========================
# FITUR BARU. /heatmap -- heatmap performa 11 sektor resmi IDX-IC
# (memakai get_sector_performance() dari core/sector_rotation.py).
# Mengikuti pola dark-theme yang sudah dipakai chart lain di project
# ini (lihat core/charts/ai_gauge_chart.py).

import math
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from core.charts.watermark import apply_centered_watermark_to_file


def generate_heatmap_chart(sector_results: list[dict], output_path: str = None) -> str | None:
    """Generate heatmap grid untuk performa sektor. Warna hijau =
    positif (makin terang = makin kuat), merah = negatif (makin gelap
    = makin lemah), berdasarkan return_pct.

    sector_results: list of dict dari get_sector_performance()
    (core/sector_rotation.py) -- masing-masing punya 'nama_sektor' dan
    'return_pct'. Returns path file PNG, atau None kalau gagal/kosong.
    """
    if not sector_results:
        return None

    try:
        n = len(sector_results)
        n_cols = 3
        n_rows = math.ceil(n / n_cols)

        fig, ax = plt.subplots(figsize=(9, 2.5 * n_rows), facecolor='#0d1117')
        fig.patch.set_facecolor('#0d1117')
        ax.set_facecolor('#0d1117')

        # Skala warna: clamp return_pct ke [-5, +5] untuk normalisasi
        # intensitas (return di luar rentang ini dianggap "paling
        # ekstrem" secara warna, supaya satu outlier tidak membuat
        # warna sektor lain jadi nyaris putih semua)
        max_abs = 5.0

        for i, sector in enumerate(sector_results):
            row = i // n_cols
            col = i % n_cols
            x = col
            y = n_rows - 1 - row  # baris pertama di ATAS

            pct = sector["return_pct"]
            intensity = min(abs(pct) / max_abs, 1.0)

            if pct > 0:
                # Hijau, makin terang makin kuat
                color = (0.0, 0.3 + 0.5 * intensity, 0.2 + 0.3 * intensity)
            elif pct < 0:
                # Merah, makin terang makin kuat (negatif)
                color = (0.3 + 0.5 * intensity, 0.0, 0.05)
            else:
                color = (0.3, 0.3, 0.3)  # netral/flat

            rect = mpatches.FancyBboxPatch(
                (x + 0.05, y + 0.05), 0.9, 0.9,
                boxstyle="round,pad=0.02,rounding_size=0.05",
                facecolor=color, edgecolor='#444444', linewidth=0.5,
            )
            ax.add_patch(rect)

            ax.text(x + 0.5, y + 0.62, sector["nama_sektor"], fontsize=10,
                     color='white', ha='center', va='center', fontweight='bold', wrap=True)
            ax.text(x + 0.5, y + 0.35, f"{pct:+.2f}%", fontsize=13,
                     color='white', ha='center', va='center', fontweight='bold')

        ax.set_xlim(0, n_cols)
        ax.set_ylim(0, n_rows)
        ax.set_xticks([])
        ax.set_yticks([])
        ax.set_frame_on(False)
        ax.set_aspect('equal')

        plt.title('HEATMAP PERFORMA SEKTOR (5 HARI)', color='white', fontsize=14, fontweight='bold', pad=15)
        plt.tight_layout()

        file_path = output_path or "sector_heatmap.png"
        plt.savefig(file_path, facecolor='#0d1117', dpi=150, bbox_inches='tight')
        plt.close(fig)
        apply_centered_watermark_to_file(file_path)

        return file_path

    except Exception as e:
        print(f"Error generating heatmap chart: {e}")
        plt.close('all')
        return None
