# =========================
# CHART: SMC (SMART MONEY CONCEPTS) VISUALIZATION
# =========================
# Satu modul untuk semua 5 command SMC: /bos, /choch, /orderblock,
# /fvg, /liquidity. Semuanya pakai candlestick chart dasar yang sama
# (dark theme, konsisten dengan chart lain di project ini), lalu
# overlay elemen SMC yang relevan di atasnya.

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

from core.charts.watermark import apply_centered_watermark_to_file


def _draw_candlesticks(ax, df, lookback: int = 60):
    """Gambar candlestick untuk lookback baris terakhir. Returns (df_plot, n, price_min, price_max)."""
    n = min(lookback, len(df))
    df_plot = df.iloc[-n:].reset_index(drop=True)

    price_min = float(df_plot["Low"].min())
    price_max = float(df_plot["High"].max())

    for i in range(len(df_plot)):
        is_bull = float(df_plot["Close"].iloc[i]) >= float(df_plot["Open"].iloc[i])
        color = "#00c9ff" if is_bull else "#ff6b6b"
        ax.plot([i, i],
                [float(df_plot["Low"].iloc[i]), float(df_plot["High"].iloc[i])],
                color=color, linewidth=0.7, alpha=0.8)
        body_lo = min(float(df_plot["Open"].iloc[i]), float(df_plot["Close"].iloc[i]))
        body_hi = max(float(df_plot["Open"].iloc[i]), float(df_plot["Close"].iloc[i]))
        body_h = max(body_hi - body_lo, float(df_plot["Close"].iloc[i]) * 0.001)
        rect = plt.Rectangle((i - 0.35, body_lo), 0.7, body_h,
                               facecolor=color, edgecolor=color,
                               linewidth=0.3, alpha=0.85)
        ax.add_patch(rect)

    return df_plot, n, price_min, price_max


def _style_axis(ax, title: str, df_plot, price_min: float, price_max: float):
    """Apply dark theme ke axis dengan y-range yang benar."""
    ax.set_facecolor("#0d1117")
    ax.tick_params(colors="#8b949e", labelsize=8)
    for spine in ax.spines.values():
        spine.set_edgecolor("#30363d")
    ax.yaxis.tick_right()
    ax.set_xlim(-1, len(df_plot))
    # Set y-axis ke range harga yang relevan dengan sedikit padding
    padding = (price_max - price_min) * 0.08
    ax.set_ylim(price_min - padding, price_max + padding)
    ax.set_title(title, color="#e6edf3", fontsize=10, fontweight="bold", pad=8)
    ax.grid(axis="y", color="#30363d", linewidth=0.4, alpha=0.6)


def generate_bos_chart(df, ticker: str, events: list[dict],
                        output_path: str = None) -> str | None:
    """Chart BOS (Break of Structure) + swing points overlay."""
    try:
        fig, ax = plt.subplots(figsize=(12, 5), facecolor="#0d1117")
        df_plot, n, price_min, price_max = _draw_candlesticks(ax, df)
        offset = len(df) - n

        # Plot swing highs & lows sebagai titik referensi
        from core.smc import detect_swing_points
        swings = detect_swing_points(df).iloc[-n:].reset_index(drop=True)
        for i in range(len(swings)):
            sh = swings["swing_high"].iloc[i]
            sl = swings["swing_low"].iloc[i]
            if not np.isnan(sh) and sh > 0:
                ax.scatter(i, float(sh), marker="^", color="#ffd93d", s=60, zorder=5, alpha=0.9)
            if not np.isnan(sl) and sl > 0:
                ax.scatter(i, float(sl), marker="v", color="#ffd93d", s=60, zorder=5, alpha=0.9)

        # Plot BOS events
        bos_events = [e for e in events if e["type"] == "BOS"]
        for ev in bos_events[-5:]:
            idx = ev["index"] - offset
            if 0 <= idx < n:
                color = "#00ff88" if ev["direction"] == "bullish" else "#ff4d4d"
                ax.axhline(y=ev["broken_level"], color=color,
                           linestyle="--", linewidth=1.2, alpha=0.7,
                           xmin=max(0, (idx-10)/n), xmax=min(1, (idx+2)/n))
                ax.annotate(
                    f"BOS {'↑' if ev['direction']=='bullish' else '↓'}",
                    xy=(idx, ev["broken_level"]),
                    color=color, fontsize=8, fontweight="bold",
                    bbox=dict(boxstyle="round,pad=0.2", facecolor="#0d1117",
                              edgecolor=color, alpha=0.8),
                )

        _style_axis(ax, f"{ticker} — Break of Structure (BOS)", df_plot, price_min, price_max)

        # Legend
        legend_items = [
            mpatches.Patch(color="#00ff88", label="BOS Bullish (uptrend lanjut)"),
            mpatches.Patch(color="#ff4d4d", label="BOS Bearish (downtrend lanjut)"),
            plt.Line2D([0], [0], marker="^", color="#ffd93d", linestyle="None",
                       markersize=8, label="Swing High/Low"),
        ]
        ax.legend(handles=legend_items, loc="upper left",
                  facecolor="#161b22", edgecolor="#30363d",
                  labelcolor="#e6edf3", fontsize=8)

        plt.tight_layout(pad=0.5)
        path = output_path or f"{ticker}_bos.png"
        plt.savefig(path, facecolor="#0d1117", dpi=150, bbox_inches="tight")
        plt.close(fig)
        apply_centered_watermark_to_file(path)
        return path
    except Exception:
        plt.close("all")
        return None


def generate_choch_chart(df, ticker: str, events: list[dict],
                          output_path: str = None) -> str | None:
    """Chart CHoCH (Change of Character) — sama seperti BOS tapi highlight CHoCH."""
    try:
        fig, ax = plt.subplots(figsize=(12, 5), facecolor="#0d1117")
        df_plot, n, price_min, price_max = _draw_candlesticks(ax, df)
        offset = len(df) - n

        from core.smc import detect_swing_points
        swings = detect_swing_points(df).iloc[-n:].reset_index(drop=True)
        for i in range(len(swings)):
            sh = swings["swing_high"].iloc[i]
            sl = swings["swing_low"].iloc[i]
            if not np.isnan(sh) and sh > 0:
                ax.scatter(i, float(sh), marker="^", color="#ffd93d", s=50, zorder=5, alpha=0.8)
            if not np.isnan(sl) and sl > 0:
                ax.scatter(i, float(sl), marker="v", color="#ffd93d", s=50, zorder=5, alpha=0.8)

        choch_events = [e for e in events if e["type"] == "CHOCH"]
        for ev in choch_events[-3:]:
            idx = ev["index"] - offset
            if 0 <= idx < n:
                color = "#00ff88" if ev["direction"] == "bullish" else "#ff4d4d"
                # CHoCH = garis lebih tebal dan annotasi lebih besar
                ax.axhline(y=ev["broken_level"], color=color,
                           linestyle="-.", linewidth=1.8, alpha=0.85,
                           xmin=max(0, (idx-12)/n), xmax=min(1, (idx+3)/n))
                ax.annotate(
                    f"CHoCH {'↑' if ev['direction']=='bullish' else '↓'}\n(Reversal signal!)",
                    xy=(idx, ev["broken_level"]),
                    color=color, fontsize=8, fontweight="bold",
                    bbox=dict(boxstyle="round,pad=0.3", facecolor="#0d1117",
                              edgecolor=color, linewidth=1.5, alpha=0.9),
                )

        _style_axis(ax, f"{ticker} — Change of Character (CHoCH)", df_plot, price_min, price_max)

        legend_items = [
            mpatches.Patch(color="#00ff88", label="CHoCH Bullish (reversal ke atas)"),
            mpatches.Patch(color="#ff4d4d", label="CHoCH Bearish (reversal ke bawah)"),
        ]
        ax.legend(handles=legend_items, loc="upper left",
                  facecolor="#161b22", edgecolor="#30363d",
                  labelcolor="#e6edf3", fontsize=8)

        plt.tight_layout(pad=0.5)
        path = output_path or f"{ticker}_choch.png"
        plt.savefig(path, facecolor="#0d1117", dpi=150, bbox_inches="tight")
        plt.close(fig)
        apply_centered_watermark_to_file(path)
        return path
    except Exception:
        plt.close("all")
        return None


def generate_orderblock_chart(df, ticker: str, obs: list[dict],
                               output_path: str = None) -> str | None:
    """Chart Order Block — zona highlighted di atas candlestick."""
    try:
        fig, ax = plt.subplots(figsize=(12, 5), facecolor="#0d1117")
        df_plot, n, price_min, price_max = _draw_candlesticks(ax, df)
        offset = len(df) - n

        for ob in obs:
            color = "#00ff88" if ob["type"] == "BULLISH" else "#ff4d4d"
            ob_idx = ob["ob_index"] - offset
            if ob_idx < 0:
                ob_idx = 0  # kalau di luar window, gambar dari kiri

            freshness = "● Fresh" if ob["is_fresh"] else "○ Mitigated"
            alpha = 0.25 if ob["is_fresh"] else 0.10

            # Zona persegi panjang dari ob_index sampai hari terakhir
            rect = mpatches.FancyBboxPatch(
                (ob_idx, ob["zone_low"]),
                n - ob_idx, ob["zone_high"] - ob["zone_low"],
                boxstyle="square,pad=0",
                facecolor=color, edgecolor=color,
                linewidth=1.2, alpha=alpha,
            )
            ax.add_patch(rect)
            # Border
            ax.hlines([ob["zone_low"], ob["zone_high"]], ob_idx, n - 1,
                      colors=color, linewidth=0.8, alpha=0.6)
            # Label
            mid = (ob["zone_low"] + ob["zone_high"]) / 2
            ax.text(ob_idx + 1, mid,
                    f"{ob['type']} OB {freshness}",
                    color=color, fontsize=8, va="center",
                    bbox=dict(boxstyle="round,pad=0.2", facecolor="#0d1117",
                              edgecolor=color, alpha=0.7))

        _style_axis(ax, f"{ticker} — Order Blocks", df_plot, price_min, price_max)

        legend_items = [
            mpatches.Patch(color="#00ff88", alpha=0.4, label="Bullish OB (support potensial)"),
            mpatches.Patch(color="#ff4d4d", alpha=0.4, label="Bearish OB (resistance potensial)"),
        ]
        ax.legend(handles=legend_items, loc="upper left",
                  facecolor="#161b22", edgecolor="#30363d",
                  labelcolor="#e6edf3", fontsize=8)

        plt.tight_layout(pad=0.5)
        path = output_path or f"{ticker}_orderblock.png"
        plt.savefig(path, facecolor="#0d1117", dpi=150, bbox_inches="tight")
        plt.close(fig)
        apply_centered_watermark_to_file(path)
        return path
    except Exception:
        plt.close("all")
        return None


def generate_fvg_chart(df, ticker: str, gaps: list[dict],
                        output_path: str = None) -> str | None:
    """Chart Fair Value Gap — zona ketidakseimbangan harga."""
    try:
        fig, ax = plt.subplots(figsize=(12, 5), facecolor="#0d1117")
        df_plot, n, price_min, price_max = _draw_candlesticks(ax, df)
        offset = len(df) - n

        for gap in gaps:
            color = "#00ff88" if gap["type"] == "BULLISH" else "#ff4d4d"
            gap_idx = gap["index"] - offset
            if gap_idx < 0:
                gap_idx = 0

            gap_h = gap["zone_high"] - gap["zone_low"]
            alpha = 0.30 if not gap["filled"] else 0.10

            rect = mpatches.FancyBboxPatch(
                (gap_idx, gap["zone_low"]),
                n - gap_idx, gap_h,
                boxstyle="square,pad=0",
                facecolor=color, edgecolor=color,
                linewidth=1.0, alpha=alpha, linestyle="--",
            )
            ax.add_patch(rect)
            ax.hlines([gap["zone_low"], gap["zone_high"]], gap_idx, n - 1,
                      colors=color, linewidth=0.8, linestyles="--", alpha=0.7)

            label = f"{'Bullish' if gap['type']=='BULLISH' else 'Bearish'} FVG"
            if gap["filled"]:
                label += " (filled)"
            ax.text(gap_idx + 0.5, (gap["zone_low"] + gap["zone_high"]) / 2,
                    label, color=color, fontsize=8, va="center",
                    bbox=dict(boxstyle="round,pad=0.2", facecolor="#0d1117",
                              edgecolor=color, alpha=0.75))

        _style_axis(ax, f"{ticker} — Fair Value Gap (FVG)", df_plot, price_min, price_max)

        legend_items = [
            mpatches.Patch(color="#00ff88", alpha=0.4, label="Bullish FVG (price imbalance naik)"),
            mpatches.Patch(color="#ff4d4d", alpha=0.4, label="Bearish FVG (price imbalance turun)"),
        ]
        ax.legend(handles=legend_items, loc="upper left",
                  facecolor="#161b22", edgecolor="#30363d",
                  labelcolor="#e6edf3", fontsize=8)

        plt.tight_layout(pad=0.5)
        path = output_path or f"{ticker}_fvg.png"
        plt.savefig(path, facecolor="#0d1117", dpi=150, bbox_inches="tight")
        plt.close(fig)
        apply_centered_watermark_to_file(path)
        return path
    except Exception:
        plt.close("all")
        return None


def generate_liquidity_chart(df, ticker: str, pools: list[dict],
                              output_path: str = None) -> str | None:
    """Chart Liquidity Pool — zona konsentrasi stop-loss."""
    try:
        fig, ax = plt.subplots(figsize=(12, 5), facecolor="#0d1117")
        df_plot, n, price_min, price_max = _draw_candlesticks(ax, df)

        for pool in pools:
            is_high = pool["type"] == "HIGH"
            color = "#ff4d4d" if is_high else "#00c9ff"
            price = pool["price_level"]

            ax.axhline(y=price, color=color, linewidth=1.5,
                       linestyle=":", alpha=0.85)

            # Area bayangan tipis di sekitar level
            price_range = float(df["Close"].iloc[-1]) * 0.005
            ax.axhspan(price - price_range, price + price_range,
                       alpha=0.12, color=color)

            swept_label = " (SWEPT)" if pool["swept"] else ""
            label = (f"{'Sell-Side' if is_high else 'Buy-Side'} Liquidity "
                     f"@ {price:,.0f}{swept_label} "
                     f"[{pool['n_swings']} swings, {pool['distance_pct']:.1f}%]")
            ax.text(n - 1, price,
                    label, color=color, fontsize=8,
                    ha="right", va="bottom" if is_high else "top",
                    bbox=dict(boxstyle="round,pad=0.2", facecolor="#0d1117",
                              edgecolor=color, alpha=0.75))

        _style_axis(ax, f"{ticker} — Liquidity Pools", df_plot, price_min, price_max)

        legend_items = [
            plt.Line2D([0], [0], color="#ff4d4d", linewidth=2, linestyle=":",
                       label="Sell-Side Liquidity (highs — stop hunt target)"),
            plt.Line2D([0], [0], color="#00c9ff", linewidth=2, linestyle=":",
                       label="Buy-Side Liquidity (lows — stop hunt target)"),
        ]
        ax.legend(handles=legend_items, loc="upper left",
                  facecolor="#161b22", edgecolor="#30363d",
                  labelcolor="#e6edf3", fontsize=8)

        plt.tight_layout(pad=0.5)
        path = output_path or f"{ticker}_liquidity.png"
        plt.savefig(path, facecolor="#0d1117", dpi=150, bbox_inches="tight")
        plt.close(fig)
        apply_centered_watermark_to_file(path)
        return path
    except Exception:
        plt.close("all")
        return None
