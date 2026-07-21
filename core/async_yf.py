# =========================
# ASYNC WRAPPER UNTUK YFINANCE
# =========================
# INI ADALAH FIX UNTUK BUG PALING FATAL di versi lama:
#
# yfinance bersifat SINKRON/BLOCKING (pakai requests biasa, bukan asyncio).
# Tapi hampir semua command handler di main.py lama adalah `async def` dan
# memanggil yfinance LANGSUNG di dalamnya tanpa run_in_executor. Karena
# python-telegram-bot menjalankan SATU event loop untuk SEMUA user, ini
# berarti: ketika User A menjalankan /plan BBCA dan menunggu data dari
# Yahoo Finance turun, SELURUH BOT FREEZE untuk SEMUA USER LAIN sampai
# download itu selesai -- termasuk /start sekalipun.
#
# Fix-nya: bungkus setiap panggilan yfinance dengan asyncio.to_thread(),
# yang menjalankan kode blocking itu di thread terpisah, sehingga event
# loop utama tetap bisa melayani user lain selagi menunggu.
#
# Modul ini juga menambahkan BATCHING dengan delay untuk loop banyak
# ticker (dipakai oleh screener dan auto-alert check), supaya tidak
# membombardir Yahoo Finance sekaligus dan kena rate-limit/IP block --
# bug lain yang ditemukan di check_watchlist_alerts() versi lama yang
# loop ratusan ticker secara sequential tanpa delay sama sekali.

import asyncio
import yfinance as yf
import pandas as pd

from core.config import YF_BATCH_SIZE, YF_BATCH_DELAY_SECONDS


def _is_crumb_error(exc: Exception) -> bool:
    """Deteksi error otentikasi Yahoo yang SEMBUH dengan negosiasi ulang
    cookie+crumb (bukan sekadar tunggu-lalu-ulang). Yahoo mewajibkan 'crumb'
    anti-CSRF; kalau crumb yang di-cache yfinance basi/rusak, request balik
    HTTP 401 'Invalid Crumb'. Rate-limit (429/'too many requests') SENGAJA
    TIDAK termasuk -- itu butuh mundur, bukan re-negosiasi (malah memperparah)."""
    msg = str(exc).lower()
    return ("crumb" in msg or "invalid cookie" in msg
            or "401" in msg or "unauthorized" in msg)


def _reset_yf_crumb() -> bool:
    """Paksa yfinance mengambil ULANG cookie+crumb Yahoo di request berikutnya.
    'Invalid Crumb' (401) tak sembuh dengan retry biasa karena crumb basi yang
    SAMA dipakai ulang dari cache in-memory singleton YfData -- membuangnya
    memaksa _get_cookie_and_crumb() menegosiasi ulang. Dilindungi _cookie_lock
    (yfinance 1.x) supaya aman terhadap request lain yang jalan paralel."""
    try:
        from yfinance.data import YfData
        d = YfData()  # singleton -- reset berlaku utk semua request selanjutnya
        lock = getattr(d, "_cookie_lock", None)
        if lock is not None:
            with lock:
                d._crumb = None
                d._cookie = None
        else:
            d._crumb = None
            d._cookie = None
        return True
    except Exception:
        return False


async def async_download(*args, max_retries: int = 2, **kwargs) -> pd.DataFrame:
    """Versi non-blocking dari yf.download(). Dipakai untuk SATU ticker
    atau SATU panggilan batch, dipanggil langsung dari handler async.

    Retry ringan (default 2x percobaan, jeda 0.4 detik) untuk gangguan
    Yahoo Finance sesaat -- baik yang melempar exception maupun yang cuma
    balik DataFrame kosong tanpa error (pola gagal-diam yang sama sudah
    ditemukan nyata di async_download_many). Sengaja lebih ringan dari
    retry batch di bawah (2x tetap vs 3x escalating) karena ini dipanggil
    langsung dalam siklus request/response -- pengguna menunggu di depan
    layar, jadi tidak boleh menambah latency terlalu besar saat gagal.

    Khusus error 'Invalid Crumb'/401 (lihat _is_crumb_error): buang crumb
    yfinance yang basi SEBELUM percobaan berikutnya, kalau tidak retry-nya
    cuma memakai ulang crumb rusak yang sama dan gagal lagi -- ini akar dari
    'kadang gagal memuat data' yang berulang."""
    last_exc = None
    df = None
    for attempt in range(max_retries):
        try:
            df = await asyncio.to_thread(yf.download, *args, **kwargs)
            if df is not None and not df.empty:
                return df
            last_exc = None
        except Exception as e:
            last_exc = e
            df = None
            if _is_crumb_error(e):
                _reset_yf_crumb()
        if attempt < max_retries - 1:
            await asyncio.sleep(0.4)
    if last_exc is not None:
        raise last_exc
    return df


async def async_ticker_info(ticker: str) -> dict:
    """Versi non-blocking dari yf.Ticker(ticker).info."""
    def _fetch():
        return yf.Ticker(ticker).info
    return await asyncio.to_thread(_fetch)


async def async_download_many(tickers: list[str], **download_kwargs) -> dict[str, pd.DataFrame]:
    """Download data untuk BANYAK ticker, dengan batching otomatis supaya
    tidak membombardir Yahoo Finance sekaligus.

    Kompatibel dengan yfinance versi lama (0.2.x) maupun versi baru (1.x+)
    yang mengubah urutan level di MultiIndex column.

    RETRY PER BATCH (BARU, Juni 2026): SEBELUMNYA batch yang gagal/kosong
    langsung dilewati tanpa dicoba ulang -- kalau Yahoo Finance lagi
    rate-limit, SEMUA batch bisa gagal beruntun dan hasil akhirnya KOSONG
    TOTAL (ditemukan nyata: /airank dengan 200 ticker/5 batch, error log
    user menunjukkan SEMUA batch gagal, "Gagal menghitung ranking" tanpa
    penjelasan). Retry per BATCH (bukan per-ticker individual -- 1 batch
    = 1 panggilan API untuk puluhan ticker sekaligus, jauh lebih efisien
    daripada retry per-ticker untuk download sebanyak ini) dengan backoff
    menaikkan peluang berhasil signifikan, konsisten dengan pola
    _download_with_retry yang sudah dipakai core/sector_rotation.py &
    handlers/ihsg_handlers.py untuk masalah yang sama persis.

    Returns: dict {ticker: DataFrame individual} sudah dipisah per ticker.
    """
    result: dict[str, pd.DataFrame] = {}
    max_retries_per_batch = 3

    for i in range(0, len(tickers), YF_BATCH_SIZE):
        batch = tickers[i:i + YF_BATCH_SIZE]
        batch_succeeded = False

        for attempt in range(max_retries_per_batch):
            try:
                data = await async_download(
                    batch,
                    group_by="ticker",
                    progress=False,
                    threads=False,
                    **download_kwargs,
                )

                if data.empty:
                    if attempt < max_retries_per_batch - 1:
                        await asyncio.sleep(YF_BATCH_DELAY_SECONDS * (attempt + 2))
                        continue
                    break

                for ticker in batch:
                    try:
                        if len(batch) == 1:
                            # yfinance tidak pakai MultiIndex kalau cuma 1 ticker
                            result[ticker] = data
                        elif isinstance(data.columns, pd.MultiIndex):
                            # Deteksi format MultiIndex: lama (OHLCV, ticker)
                            # atau baru (ticker, OHLCV)
                            ohlcv = {"Open", "High", "Low", "Close", "Volume", "Adj Close"}
                            level0 = set(data.columns.get_level_values(0))
                            if level0 & ohlcv:
                                # Format lama: level 0 = OHLCV, level 1 = ticker
                                if ticker in data.columns.get_level_values(1):
                                    df_ticker = data.xs(ticker, axis=1, level=1)
                                    result[ticker] = df_ticker
                            else:
                                # Format baru: level 0 = ticker, level 1 = OHLCV
                                if ticker in data.columns.get_level_values(0):
                                    result[ticker] = data[ticker]
                        else:
                            # Flat columns - jarang terjadi untuk multi ticker
                            result[ticker] = data
                    except Exception:
                        continue

                batch_succeeded = True
                break

            except Exception as e:
                if attempt < max_retries_per_batch - 1:
                    print(f"⚠️ Batch {batch[:3]}... gagal (percobaan {attempt+1}/{max_retries_per_batch}): {e}")
                    await asyncio.sleep(YF_BATCH_DELAY_SECONDS * (attempt + 2))
                else:
                    print(f"⚠️ Batch {batch[:3]}... gagal TOTAL setelah {max_retries_per_batch}x percobaan: {e}")

        if not batch_succeeded:
            print(f"⚠️ Batch {batch[:3]}... ({len(batch)} ticker) dilewati -- semua percobaan gagal.")

        # Delay antar batch, kecuali batch terakhir.
        if i + YF_BATCH_SIZE < len(tickers):
            await asyncio.sleep(YF_BATCH_DELAY_SECONDS)

    return result
