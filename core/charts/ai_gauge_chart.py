# =========================
# CHART: AI SCORE GAUGE
# =========================
# Migrasi generate_ai_gauge_chart_simple dari main.py lama. Chart
# sederhana: horizontal bar sebagai gauge, warna berdasarkan score.

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from core.charts.watermark import apply_centered_watermark_to_file


def generate_ai_gauge_chart(ticker_name: str, result: dict, output_path: str = None) -> str | None:
    """Generate gauge chart untuk AI Score (horizontal bar 0-100).

    result: dict hasil calculate_ai_score_from_df() (core/ai_score.py).
    Returns: path file PNG, atau None kalau gagal.
    """
    try:
        fig, ax = plt.subplots(figsize=(6, 4), facecolor='#0d1117')
        fig.patch.set_facecolor('#0d1117')
        ax.set_facecolor('#161b22')

        score = result['score']

        if score >= 75:
            bar_color = '#00ff88'
        elif score >= 60:
            bar_color = '#00d2ff'
        elif score >= 45:
            bar_color = '#ffd700'
        elif score >= 30:
            bar_color = '#ff8c00'
        else:
            bar_color = '#ff4444'

        # Track abu-abu (0-100 penuh) HARUS digambar DULU, baru bar skor
        # berwarna di atasnya -- urutan sebelumnya TERBALIK (bar skor
        # duluan, baru track abu-abu semi-transparan menimpa SELURUH
        # lebar termasuk bagian yang sudah berwarna), bikin seluruh gauge
        # kelihatan pudar/keabuan alih-alih warna solid + track kosong
        # yang benar.
        ax.barh(0, 100, color='#333333', height=0.3, alpha=0.3)
        ax.barh(0, score, color=bar_color, height=0.3, alpha=0.9)

        ax.text(score / 2, 0, f'{score:.0f}', fontsize=28, color='white',
                 ha='center', va='center', fontweight='bold')

        ax.text(50, -0.5, result['recommendation'], fontsize=12, color=bar_color,
                 ha='center', va='center', fontweight='bold')

        ax.text(50, -0.8, result['rating'], fontsize=10, color='gray', ha='center', va='center')

        ax.set_xlim(0, 100)
        ax.set_ylim(-1, 0.5)
        ax.set_xticks([])
        ax.set_yticks([])
        ax.set_frame_on(False)

        plt.title(f'{ticker_name} - AI SCORE', color='white', fontsize=14, fontweight='bold')
        plt.tight_layout()

        file_path = output_path or f"{ticker_name}_ai_score.png"
        plt.savefig(file_path, facecolor='#0d1117', dpi=150, bbox_inches='tight')
        plt.close(fig)
        apply_centered_watermark_to_file(file_path)

        return file_path

    except Exception as e:
        print(f"Error generating gauge chart: {e}")
        plt.close('all')
        return None
