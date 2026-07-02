# =========================
# SCAN SAHAM SINYAL BUY (STOCHASTIC + GOLDEN CROSS + VOLUME)
# =========================
# Migrasi scan_stocks_for_buy_signals dari main.py lama.
#
# FIX BUG: stocksignal_cmd di kode lama mengakses r['above_ma20'] dan
# r['above_ma50'] saat memformat hasil, tapi scan_stocks_for_buy_signals()
# TIDAK PERNAH memasukkan key tersebut ke dictionary hasil -- artinya
# setiap kali ada saham yang benar-benar lolos kriteria BUY (jadi list
# results tidak kosong), command akan CRASH dengan KeyError saat mencoba
# menampilkan hasilnya ke user. Bug ini kemungkinan belum pernah ketahuan
# karena kriteria BUY-nya cukup ketat (oversold + golden cross + volume
# spike sekaligus), jadi list hasil sering kosong (yang punya code path
# berbeda, tidak menyentuh bagian yang error). Fix: tambahkan kalkulasi
# above_ma20/above_ma50 ke hasil scan, sesuai niat asli kode (menampilkan
# status MA sebagai info tambahan di pesan).

from core.indicators import calculate_stochrsi


async def scan_stocks_for_buy_signals(tickers: list[str]) -> list[dict]:
    """Scan saham dengan kondisi: Stochastic oversold (K<20 dan D<20) DAN
    golden cross (K baru saja naik di atas D) DAN volume spike (>1.5x MA20).
    SEMUA kondisi harus terpenuhi untuk sinyal BUY.
    """
    from core.async_yf import async_download_many
    from core.stock_data import fix_yf_columns
    import pandas as pd

    data_by_ticker = await async_download_many(tickers, period="3mo", interval="1d")
    results = []

    for ticker, df in data_by_ticker.items():
        try:
            df = fix_yf_columns(df)
            df = df.apply(pd.to_numeric, errors='coerce')
            df = df.dropna()

            if len(df) < 50:
                continue

            stoch_k, stoch_d = calculate_stochrsi(df['Close'])

            volume = df['Volume']
            vol_ma20 = volume.rolling(20).mean()

            current_price = float(df['Close'].iloc[-1])
            prev_close = float(df['Close'].iloc[-2])
            daily_change = ((current_price / prev_close) - 1) * 100

            current_volume = float(volume.iloc[-1])
            vol_ratio = current_volume / vol_ma20.iloc[-1] if vol_ma20.iloc[-1] > 0 else 1

            last_stoch_k = stoch_k.iloc[-1]
            last_stoch_d = stoch_d.iloc[-1]

            is_oversold = (last_stoch_k < 20 and last_stoch_d < 20)

            is_golden_cross = False
            if len(stoch_k) >= 2:
                prev_k = stoch_k.iloc[-2]
                prev_d = stoch_d.iloc[-2]
                current_k = stoch_k.iloc[-1]
                current_d = stoch_d.iloc[-1]
                if prev_k <= prev_d and current_k > current_d:
                    is_golden_cross = True

            is_volume_spike = (vol_ratio > 1.5)

            if is_oversold and is_golden_cross and is_volume_spike:
                confidence = 85
                if vol_ratio > 2.0:
                    confidence = 95
                elif vol_ratio > 1.8:
                    confidence = 90

                # FIX: tambahan above_ma20/above_ma50 yang dulu hilang
                ma20 = df['Close'].rolling(20).mean().iloc[-1]
                ma50 = df['Close'].rolling(50).mean().iloc[-1]
                above_ma20 = current_price > ma20
                above_ma50 = current_price > ma50

                results.append({
                    "ticker": ticker.replace(".JK", ""), "price": current_price,
                    "change": daily_change, "volume_ratio": round(vol_ratio, 1),
                    "stoch_k": round(last_stoch_k, 1), "stoch_d": round(last_stoch_d, 1),
                    "reasons": (
                        f"Oversold (K={last_stoch_k:.1f}/D={last_stoch_d:.1f}) "
                        f"+ Golden Cross + Volume Spike ({vol_ratio:.1f}x)"
                    ),
                    "confidence": confidence,
                    "above_ma20": above_ma20, "above_ma50": above_ma50,
                })

        except Exception as e:
            print(f"Error scanning {ticker}: {e}")
            continue

    results.sort(key=lambda x: (-x["confidence"], -x["volume_ratio"]))
    return results
