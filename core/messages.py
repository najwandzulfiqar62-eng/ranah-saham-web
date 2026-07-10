# =========================
# MESSAGE FORMATTING HELPERS
# =========================
# Modul ini berisi fungsi format pesan yang dipakai bersama oleh banyak
# command handler. Dipisah dari logic screener/trading_plan supaya data
# mentah (list of dict) bisa diformat dengan cara berbeda di tempat
# berbeda tanpa perlu duplikasi logic kalkulasi.

OPENING = """
🤖 AI STOCK SCREENER (IDX) - READY!

📊 *SCREENING:*
/signal - Cari Saham (Umum)
/bsjp - Cari Saham (BSJP)
/bsjpplan BBCA - BSJP Trading Plan
/bsjptop - Top BSJP Auto Plan
/stocksignal - Saham Sinyal BUY Kuat
/topsignal - Top 5 Sinyal BUY

🎯 *FILTER:*
/filter bullish - Trend Bullish
/filter breakout - Saham Breakout
/filter volume - Volume Spike
/filter reversal - Reversal Oversold

⭐ *WATCHLIST:*
/watchlist - Kelola Watchlist
/rekapwl - Rekap Watchlist
/wlstatus - Status Watchlist (Cepat)
/checkalerts - Cek Alert Manual

🔔 *PRICE ALERT:*
/alert - Set Alert Harga
/myalerts - Lihat Alert Aktif
/removealert - Hapus Alert

📈 *ANALISIS:*
/compare - Bandingkan Saham
/plan BBCA - Rencana Trading
/snr BBCA - Support Resistance
/ta BBCA - Technical Analysis Lengkap (4 MA + Fibonacci + ADX + Stoch, alias /ml)

🧠 *RANAH AI:*
/ranah BBCA - Analisis AI Lengkap
/aiscore BBCA - Breakdown Skor AI
/airank - Top 20 Ranking AI Score

🆕 *ANALISIS LANJUTAN:*
/backtest BBCA - Validasi Statistik Historis
/rs BBCA - Relative Strength vs IHSG & Sektor

🆕 *IHSG ANALYSIS:*
/ihsg - Analisis IHSG + Prediksi Besok

📐 *MARKET STRUCTURE (SMC):*
/bos BBCA - Break of Structure
/choch BBCA - Change of Character
/orderblock BBCA - Zona Order Block
/fvg BBCA - Fair Value Gap
/liquidity BBCA - Liquidity Pool

⚖️ *RISK MANAGEMENT:*
/rr ENTRY SL TP - Risk/Reward Calculator
/target BBCA - Target Harga (S/R + Fibonacci)
/cutloss BBCA - Area Cut Loss (ATR)
/positionsize MODAL RISIKO% ENTRY CL - Kalkulasi Lot

🔄 *SEKTOR & ROTASI:*
/sektor - Ranking Kekuatan Sektor
/rotasi - Rotasi Sektor (momentum)
/leader SEKTOR - Saham Terkuat di Sektor
/laggard SEKTOR - Saham Terlemah di Sektor
/beta BBCA - Koefisien Beta vs IHSG
/relative BBCA - Relative Strength (alias /rs)

📊 *VOLUME PATTERNS:*
/volumespike BBCA - Histori Lonjakan Volume
/adline BBCA - Accumulation/Distribution Line

🔬 *SCREENING PREMIUM:*
/screenerpro - Screener Minervini (Saham Terkuat IDX)
/multitimeframe BBCA - Analisis 3 Timeframe (1D/1W/1M)
/confluence BBCA - Confluence 6 Indikator Sekaligus
/patternscan BBCA - Deteksi Pola Chart (Double Top/Bottom, HH/LL)
/correlation BBCA IHSG - Korelasi Antar Aset (Pearson 60H)
/backtestpro BBCA [mode] - Walk-Forward Backtest

📰 *NEWS:*
/news [kode] - Berita Pasar/Saham Terkini

📊 *FUNDAMENTAL:*
/fundamental BBCA - PE, PBV, ROE, DER, Dividend Yield, EPS

🧩 *INSIGHT:*
/insight BBCA - Narasi Gabungan Teknikal + Konteks IHSG + Berita
/insight IHSG - Insight Market-Wide (Rotasi Sektor + Breadth)

🆕 *CHART COMMANDS:*
/chart BBCA - Advanced Chart
/signals BBCA - Trading Signals Chart

📊 *MARKET:*
/daily - Daily Market Report
/topgainer - Top Gainer
/topvolume - Top Volume
/toploser - Top Loser
/topvalue - Top Value (Nilai Transaksi)
/heatmap - Heatmap Sektor (visual)
/hotstock - Saham Potensial

🆕 *AUTO NOTIFICATION:*
/subscribe - Dapatkan Daily Summary
/unsubscribe - Berhenti Daily Summary

💡 Atau ketik kode saham langsung (contoh: `BBCA`) untuk menu cepat!
/howto - Cara Pakai Fitur Ketik Kode Saham

/help - Tutorial Lengkap (dengan contoh penggunaan)
/id - Chat ID
"""

HELP_TEXT = """
📚 TUTORIAL

📊 *SCREENING:*
/signal → screening saham umum
/bsjp → screening saham BSJP
/bsjpplan BBCA → BSJP Trading Plan
/bsjptop → Top BSJP Auto Plan
/stocksignal → saham dengan sinyal BUY kuat
/topsignal → Top 5 sinyal BUY terkuat

🎯 *FILTER:*
/filter bullish
/filter breakout
/filter volume
/filter reversal

⭐ *WATCHLIST:*
/watchlist add BBCA
/watchlist remove BBCA
/watchlist show
/rekapwl → rekap performa
/wlstatus → status cepat
/checkalerts → cek alert manual

🔔 *PRICE ALERT:*
/alert BBCA 9500 → alert saat harga capai target
/myalerts → lihat alert aktif
/removealert [id] → hapus alert

📈 *ANALISIS:*
/compare BBCA BBRI → AI Score + chart visual perbandingan 2 saham
/plan BBCA → Advanced Trading Plan
/snr BBCA
/ta BBCA → Technical Analysis lengkap: candlestick + MA5/20/50/200 + Fibonacci + S/R + ADX + Stochastic + MACD (alias: /ml)

🧠 *RANAH AI:*
/ranah BBCA → analisis AI lengkap
/aiscore BBCA → breakdown skor AI
/airank → Top 20 ranking AI Score

🆕 *ANALISIS LANJUTAN:*
/backtest BBCA → validasi statistik historis sinyal
/rs BBCA → relative strength vs IHSG & sektor

🆕 *IHSG ANALYSIS:*
/ihsg - Analisis IHSG + Prediksi Besok

📐 *MARKET STRUCTURE (SMC):*
/bos BBCA → break of structure (trend continuation) terbaru
/choch BBCA → change of character (sinyal awal reversal) terbaru
/orderblock BBCA → zona order block institusional
/fvg BBCA → fair value gap yang belum terisi
/liquidity BBCA → liquidity pool (zona stop-loss terkumpul)

⚖️ *RISK MANAGEMENT:*
/rr 5000 4800 5600 → hitung rasio risk/reward dari entry, stop loss, take profit
/target BBCA → target harga via support/resistance + fibonacci
/cutloss BBCA → area cut loss ideal berbasis ATR (konservatif & agresif)
/positionsize 10000000 1 5000 4800 → jumlah lot (modal, risiko%, entry, cutloss)

🔄 *SEKTOR & ROTASI:*
/sektor → ranking 11 sektor resmi IDX-IC dari terkuat ke terlemah
/rotasi → fase momentum tiap sektor (akselerasi/konsisten/melemah)
/leader BANKING → saham terkuat di sektor (terbatas sektor yang terdaftar)
/laggard BANKING → saham terlemah di sektor (terbatas sektor yang terdaftar)
/beta BBCA → koefisien beta (volatilitas relatif) vs IHSG
/relative BBCA → alias /rs, relative strength vs IHSG & sektor

📊 *VOLUME PATTERNS:*
/volumespike BBCA → histori lonjakan volume vs rata-rata 20 hari (10 hari terakhir)
/adline BBCA → Chaikin Accumulation/Distribution Line, deteksi divergensi harga vs volume

🔬 *SCREENING PREMIUM:*
/screenerpro → Minervini Trend Template: scan 200 saham IDX dengan 8 kriteria + MACD/RSI (skor ≥65/100 = kandidat Stage 2)
/multitimeframe BBCA → sinyal RSI + MACD + MA di 3 timeframe (1D, 1W, 1M) + alignment check
/confluence BBCA → alignment 6 indikator sekaligus (RSI, MACD, MA, BB, StochRSI, Volume)
/patternscan BBCA → deteksi double top, double bottom, higher highs/lower lows
/correlation BBCA IHSG → korelasi Pearson rolling 60 hari; pakai 'IHSG' atau kode saham lain
/backtestpro BBCA momentum 4 → walk-forward validation (lebih rigorous dari /backtest biasa)

📰 *NEWS:*
/news → berita market terkini, agregasi dari 3 sumber (CNBC Indonesia, CNN Indonesia, Detik Finance), diurutkan berdasarkan waktu terbaru
/news BBCA → berita yang menyebut kode saham tertentu (filter kata kunci, dicek di semua sumber), dilengkapi sinyal teknikal (AI Score) untuk saham yang disebut

📄 *LAPORAN PDF:*
/laporan BBCA → laporan analisis saham lengkap dalam PDF: snapshot, grafik harga, Ranah AI, perspektif Bull vs Bear, SMC lengkap (BOS/CHoCH, order block, FVG, liquidity pool) beserta chart-nya, skenario & manajemen risiko
/laporan IHSG (atau /laporan tanpa argumen) → laporan PDF market-wide IHSG: prediksi + backtest, grafik, level kunci, dan rotasi sektor

📊 *FUNDAMENTAL:*
/fundamental BBCA → PE Ratio, PBV, ROE, DER, Dividend Yield, EPS, pertumbuhan YoY (dari Yahoo Finance, cek catatan di pesan soal keterbatasan data)

🧩 *INSIGHT:*
/insight BBCA → narasi yang merangkai AI Score (teknikal saham), konteks arah IHSG (termasuk outperform/underperform pasar), dan berita jadi satu paragraf -- rule-based (bukan AI generatif), bahasa deskriptif bukan rekomendasi
/insight IHSG (atau /insight tanpa argumen) → insight market-wide IHSG: kondisi teknikal IHSG sendiri, sektor mana yang memimpin/tertinggal, dan apakah pergerakan IHSG didukung mayoritas sektor (broad-based) atau cuma segelintir (narrow)

🆕 *CHART BARU:*
/chart BBCA → Candlestick + MA + BB + RSI
/signals BBCA → Chart dengan sinyal trading

📊 *MARKET:*
/daily → Daily Market Report
/topgainer → Top Gainer
/topvolume → Top Volume
/toploser → Top Loser (kebalikan top gainer)
/topvalue → Top Value, nilai transaksi (harga x volume) -- pengganti /TOPFREQ, lihat catatan di core/market.py
/heatmap → Heatmap visual performa 11 sektor resmi IDX-IC (hijau=menguat, merah=melemah)
/hotstock → Saham Potensial

🔔 *NOTIFIKASI:*
/subscribe → Daily summary (08:30 & 16:30)
/unsubscribe → Berhenti

💡 Atau ketik kode saham langsung (contoh: `BBCA`) untuk menu cepat!
/howto → cara pakai fitur ketik kode saham

🔧 *LAINNYA:*
/start → tampilkan ulang daftar command
/id → lihat chat ID kamu

⚠️ DISCLAIMER: Bukan ajakan beli/jual. DYOR!
"""

DISCLAIMER = """
⚠️ DISCLAIMER

Bukan ajakan beli/jual.
DYOR & Manage Your Risk.
"""


def format_screener_results(results: list[dict]) -> str:
    """Format hasil run_screener() (list of dict) jadi pesan teks /signal.

    REVISI: run_screener() dulu mengirim field 'signal' SUDAH berisi emoji
    ("🔥 STRONG BUY"/"✅ BUY") -- diubah jadi teks bersih ("STRONG BUY"/"BUY")
    supaya web UI (yang tidak lagi pakai emoji sbg ikon) tidak perlu strip
    emoji dari data. Emoji utk pesan Telegram ini (medium yang MEMANG cocok
    pakai emoji) ditambahkan DI SINI saja, di lapisan format pesan -- bukan
    dibakar ke field data mentahnya."""
    if not results:
        return "❌ Tidak ada saham sesuai signal"

    msg = "🔥 SIGNAL SAHAM 🔥\n\n"
    for r in results[:15]:
        emoji = "🔥" if r["signal"] == "STRONG BUY" else "✅"
        msg += f"{emoji} {r['signal']}\n{r['ticker']} | {r['price']}\n\n"
    return msg


def format_bsjp_screener_results(results: list[dict]) -> str:
    """Format hasil run_bsjp_screener() (list of dict) jadi pesan teks /bsjp."""
    if not results:
        return "❌ Tidak ada saham sesuai rules BSJP"

    msg = "🚀 BSJP SIGNAL\n\n"
    for r in results[:10]:
        msg += (
            f"🔥 {r['ticker']}\n"
            f"Price : {r['price']}\n"
            f"Change : {r['change']}%\n"
            f"Volume : {r['volume']:,}\n"
            f"Value : {round(r['value']/1e9,2)}B\n\n"
        )
    return msg


def sanitize_for_markdown(text: str | None) -> str:
    """Bersihkan teks dari karakter spesial Markdown SEBELUM dimasukkan
    ke pesan parse_mode='Markdown' -- BARU, ditemukan sebagai bug laten
    saat membangun /insight (Juni 2026): teks dari sumber EKSTERNAL yang
    tidak dikontrol bot ini (judul berita RSS, nama perusahaan dari
    Yahoo Finance) BISA mengandung underscore/asterisk/backtick, dan
    kalau jumlahnya jadi GANJIL di pesan lengkap, Telegram gagal parsing
    SELURUH pesan dengan error "Can't parse entities" (PERSIS bug yang
    sama yang sudah ditemukan & diperbaiki di /ihsg sebelumnya, soal
    fib_position & nama candlestick pattern yang mengandung underscore).

    PENDEKATAN: ganti karakter spesial Markdown dengan karakter visual
    serupa yang AMAN (bukan escape dengan backslash -- Telegram
    parse_mode='Markdown' lama TIDAK mendukung escape backslash secara
    konsisten untuk semua karakter, beda dengan MarkdownV2). Cukup aman
    untuk teks yang cuma perlu DIBACA, bukan teks yang butuh
    mempertahankan formatting aslinya (judul berita/nama perusahaan
    tidak butuh italic/bold dari sumber asli).

    Dipakai di: /news (judul berita), /fundamental (nama perusahaan),
    /insight (judul berita di narasi) -- semua titik yang memasukkan
    teks dari sumber eksternal ke pesan Markdown."""
    if not text:
        return text or ""
    return (
        text.replace("_", "-")
            .replace("*", "")
            .replace("`", "'")
            .replace("[", "(")
            .replace("]", ")")
    )


def split_long_message(text: str, chunk_size: int = 4000) -> list[str]:
    """Pecah pesan panjang jadi beberapa chunk untuk menghindari limit
    4096 karakter Telegram. chunk_size diberi margin di bawah limit asli."""
    if len(text) <= 4096:
        return [text]
    return [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]
