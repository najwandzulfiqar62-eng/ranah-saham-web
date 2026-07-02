# =========================
# STRATEGI IHSG (FORMATTING)
# =========================
# Migrasi get_ihsg_strategy_advanced dari main.py lama. Murni formatting
# string berdasarkan dict hasil analyze_ihsg_advanced() -- tidak ada
# kalkulasi baru di sini, jadi tidak ada perubahan logic dari versi lama.

def get_ihsg_strategy_advanced(analysis: dict) -> str:
    """Generate strategi trading berdasarkan hasil analyze_ihsg_advanced()."""

    if "BULLISH" in analysis['prediction']:
        if analysis['confidence'] == "TINGGI (70%+)":
            return f"""
✅ *STRATEGI AGGRESSIF (High Confidence)*

🎯 *ENTRY ZONE:*
{analysis['entry_zone']}

📊 *TARGET:*
├─ TP1: {analysis['take_profit']:,}
├─ TP2: {analysis['take_profit'] * 1.01:.0f}
└─ Target pergerakan: {analysis['target_move']}

🛑 *STOP LOSS:*
{analysis['stop_loss']:,}

📐 *KEY LEVELS:*
├─ Support: {analysis['support_1']:,}
├─ Resistance: {analysis['resistance_1']:,}
├─ POC: {analysis['poc']:,}
└─ Fib 618: {analysis['fib_618']:,}

💡 *CONFLUENCE SIGNALS:*
• RSI: {analysis['rsi']} ({'Momentum menguat' if analysis['rsi'] > analysis.get('prev_rsi', 50) else 'Momentum melemah'})
• MACD: {analysis['macd_signal']}
• Volume: {analysis['volume_trend']} ({analysis['volume_ratio']}x)
• RSI Divergence: {analysis['rsi_divergence']}

🎯 *EKSEKUSI:*
1. Entry saat harga di {analysis['entry_zone']}
2. Pasang SL di {analysis['stop_loss']:,}
3. Scale out di TP1 (50%), TP2 (50%)
4. Trail SL setelah +1%
"""
        else:
            return f"""
📊 *STRATEGI MODERAT (Medium Confidence)*

🎯 *ENTRY ZONE:*
Support {analysis['support_1']:,} - {analysis['support_2']:,}

🎯 *TARGET:*
TP1: {analysis['take_profit']:,}
TP2: {analysis['resistance_1']:,}

🛑 *STOP LOSS:*
{analysis['stop_loss']:,}

⚠️ *CATATAN:*
• Gunakan 30-40% modal
• Konfirmasi volume > 1.2x
• Jangan FOMO jika gap up
• Tunggu pullback ke support

📊 *INDIKATOR KUNCI:*
• BB Position: {analysis['bb_position']}%
• Fib Level: {analysis['fib_position']}
• Trend: {analysis['ma_trend']}
"""

    elif "BEARISH" in analysis['prediction']:
        if analysis['confidence'] == "TINGGI (70%+)":
            return f"""
🔴 *STRATEGI DEFENSIF (High Confidence)*

🚫 *TINDAKAN:*
├─ HINDARI pembelian baru
├─ TUTUP posisi long yang masih profit
└─ KURANGI eksposure 50-70%

🎯 *LEVEL KRITIS:*
├─ Support utama: {analysis['support_1']:,}
├─ Jika tembus → Sell signal
└─ Target koreksi: {analysis['target_move']}

📐 *RESISTANCE YANG HARUS DIWASPADAI:*
├─ R1: {analysis['resistance_1']:,}
└─ R2: {analysis['resistance_2']:,}

⚠️ *RISK SIGNALS:*
• RSI: {analysis['rsi']} ({'Overbought' if analysis['rsi'] > 70 else 'Melemah'})
• MACD: {analysis['macd_signal']}
• Volume: {analysis['volume_trend']}
• BB Position: {analysis['bb_position']}%
• Divergence: {analysis['rsi_divergence']}

💡 *REKOMENDASI:*
• Jangan averaging down
• Pantau candle 30 menit pertama
• Tunggu bottom confirmation (hammer/engulfing)
"""
        else:
            return f"""
⚠️ *STRATEGI KONSERVATIF (Medium Confidence)*

📊 *RANGE TRADING:*
Support: {analysis['support_1']:,}
Resistance: {analysis['resistance_1']:,}

💡 *TINDAKAN:*
• Kurangi posisi beli 30-50%
• Pantau volume untuk konfirmasi
• Entry hanya jika ada reversal pattern

🔍 *YANG DIMONITOR:*
├─ Break support {analysis['support_1']:,} → bearish
├─ Break resistance {analysis['resistance_1']:,} → bullish
└─ BB Squeeze: {'Aktif (siap breakout)' if analysis['bb_squeeze'] else 'Tidak aktif'}

📈 *PROBABILITAS:*
Bullish: {analysis['bullish_score']}% vs Bearish: {analysis['bearish_score']}%
"""

    else:  # SIDEWAYS / MIXED
        return f"""
⚪ *STRATEGI SIDEWAYS (Low Confidence)*

🔄 *RANGE TRADING MODE:*

🎯 *BUY ZONE:*
{analysis['support_1']:,} - {analysis['support_2']:,}

🎯 *SELL ZONE:*
{analysis['resistance_2']:,} - {analysis['resistance_1']:,}

📊 *TARGET:*
Profit 0.5-1% per transaksi

🛑 *STOP LOSS:*
15-20 poin dari entry

💡 *TIPS:*
• Gunakan 20% modal max
• Jangan trading di tengah range
• Pantau untuk breakout

🔍 *BREAKOUT WATCH:*
• Bullish breakout: > {analysis['resistance_1']:,} + volume spike
• Bearish breakout: < {analysis['support_1']:,} + volume spike
• BB Squeeze: {'Siap breakout' if analysis['bb_squeeze'] else 'Range masih lebar'}

📈 *PROBABILITAS PERGERAKAN:*
Naik: {analysis['bullish_score']}% | Turun: {analysis['bearish_score']}%
"""
