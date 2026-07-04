# =========================
# WEB API - FastAPI di atas core/
# =========================
# Lapisan web yang MEMBUNGKUS fungsi core/ yang sudah ada jadi HTTP API.
# TIDAK ada logika analisis baru di sini -- semua tetap di core/ (sumber
# kebenaran tunggal), jadi web & bot Telegram memberi hasil identik.
#
# PRINSIP KEAMANAN (penting untuk web publik):
# - Semua logika & data (yfinance, perhitungan) di SERVER. Frontend cuma
#   menampilkan. Tidak ada kunci/token di sisi browser.
# - Ada cache TTL untuk MELINDUNGI Yahoo Finance dari rentetan request
#   publik (kalau tidak, mudah kena rate-limit / IP diblokir).
# - Ada rate limit per-IP sederhana (in-memory). UNTUK PRODUKSI SKALA
#   BESAR ini perlu diganti rate-limit berbasis Redis + autentikasi;
#   versi ini fondasi, bukan benteng final. Lihat catatan di bawah.
#
# Jalankan:
#   pip install fastapi uvicorn
#   uvicorn web.app:app --host 0.0.0.0 --port 8000
# lalu buka http://localhost:8000

import os
import sys
import time
import asyncio
import tempfile
import hashlib
from collections import defaultdict
from contextlib import asynccontextmanager

import redis
import pickle
import pandas as pd


# socket_connect_timeout/socket_timeout WAJIB diisi: redis-py sinkron
# memblokir event loop selagi menunggu koneksi. Tanpa timeout, Redis yang
# mati/lambat membuat SELURUH server freeze untuk SEMUA user (setiap
# request lewat /api/* menyentuh Redis lewat middleware rate limit) --
# ditemukan nyata: di Windows, connect ke port tertutup tidak langsung
# "connection refused" seperti di Linux, jadi bisa menggantung lama alih-
# alih langsung gagal ke jalur fail-open yang sudah ada di setiap caller.
_redis = redis.from_url(
    os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    socket_connect_timeout=0.5,
    socket_timeout=0.5,
)

import pandas as pd
# emoji dipakai di banyak print() log (mis. "⚠️ Gagal fetch..." di
# core/news.py) -- itu melempar UnicodeEncodeError yang JUSTRU menjatuhkan
# request (mis. /api/news 500) meski logikanya sendiri sudah didesain
# graceful (1 sumber gagal tidak menggagalkan yang lain). Paksa UTF-8 di
# awal proses supaya print() manapun aman.
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd
import yfinance as yf
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.gzip import GZipMiddleware

from core.async_yf import async_download
from core.stock_data import fix_yf_columns
from core.ai_score import calculate_ai_score_from_df
from core.insight import _narrate_technical
from core.report import (
    build_smc_summary, build_report_data, build_ihsg_report_data,
)
from core.charts.advanced_chart import generate_advanced_chart
from core.smc import detect_bos_choch, detect_order_blocks, detect_fvg, detect_liquidity_pools
from core.charts.smc_chart import (
    generate_bos_chart, generate_orderblock_chart, generate_fvg_chart, generate_liquidity_chart,
)
from core.charts.report_pdf import generate_report_pdf, generate_ihsg_report_pdf
from core.news import fetch_news
from core.news_signal import enrich_news_with_signals
from core.ihsg.ihsg_analysis import analyze_ihsg_with_backtest
from core.wyckoff import detect_phases
from core.risk_management import (
    calculate_risk_reward, calculate_target_levels,
    calculate_cutloss_levels, calculate_position_size,
    calculate_average_down,
)
from core.sector_rotation import calculate_beta
from core.relative_strength import calculate_relative_strength
from core.volume_patterns import calculate_ad_line
from core.charts.snr_chart import calculate_snr_levels
from core.config import SAHAM_XLSX_PATH

# Peta sektor untuk universe likuid (akurat, IDX-IC). Data sektor penuh
# tidak tersedia dari yfinance, jadi dipetakan manual untuk universe ini.
SECTOR_MAP_UNIVERSE = {
    "BBCA": "Financials", "BBRI": "Financials", "BMRI": "Financials", "BBNI": "Financials",
    "BRIS": "Financials", "ARTO": "Financials",
    "TLKM": "Infrastructure", "EXCL": "Infrastructure", "ISAT": "Infrastructure",
    "TOWR": "Infrastructure", "TBIG": "Infrastructure", "JSMR": "Infrastructure",
    "ASII": "Industrials", "UNTR": "Industrials",
    "UNVR": "Consumer Non-Cyclical", "ICBP": "Consumer Non-Cyclical", "INDF": "Consumer Non-Cyclical",
    "GGRM": "Consumer Non-Cyclical", "HMSP": "Consumer Non-Cyclical", "CPIN": "Consumer Non-Cyclical",
    "JPFA": "Consumer Non-Cyclical", "AMRT": "Consumer Non-Cyclical",
    "KLBF": "Healthcare",
    "ADRO": "Energy", "PTBA": "Energy", "ITMG": "Energy", "MEDC": "Energy", "PGAS": "Energy",
    "BRMS": "Energy", "RAJA": "Energy", "AKRA": "Energy",
    "ANTM": "Basic Materials", "INCO": "Basic Materials", "MDKA": "Basic Materials",
    "TINS": "Basic Materials", "SMGR": "Basic Materials", "INTP": "Basic Materials",
    "BRPT": "Basic Materials", "TPIA": "Basic Materials",
    "MNCN": "Consumer Cyclical", "ACES": "Consumer Cyclical", "MAPI": "Consumer Cyclical",
    "ERAA": "Consumer Cyclical",
    "GOTO": "Technology", "BUKA": "Technology",
}

# Peta grup konglomerasi (kepemilikan/afiliasi bisnis keluarga besar IDX).
# BEST-EFFORT dari pengetahuan publik yang cukup mapan -- BUKAN data resmi
# real-time dari BEI/KSEI. Struktur kepemilikan bisa berubah (divestasi,
# akuisisi), jadi ini sengaja dibatasi ke afiliasi yang cukup terdokumentasi
# secara luas; saham yang tidak masuk (independen/BUMN/asing/tidak pasti)
# default ke "Independen", BUKAN diasumsikan tanpa grup sama sekali.
GRUP_KONGLOMERASI = {
    "ASII": "Grup Astra", "UNTR": "Grup Astra", "AUTO": "Grup Astra", "AALI": "Grup Astra",
    "BBCA": "Grup Djarum", "TOWR": "Grup Djarum",
    "INDF": "Grup Salim", "ICBP": "Grup Salim", "LSIP": "Grup Salim", "ROTI": "Grup Salim",
    "BRPT": "Grup Barito Pacific", "TPIA": "Grup Barito Pacific",
    "CUAN": "Grup Barito Pacific", "PTRO": "Grup Barito Pacific",
    "BREN": "Grup Barito Pacific",
    "MDKA": "Grup Merdeka (Soeryadjaya/Thohir)", "MBMA": "Grup Merdeka (Soeryadjaya/Thohir)",
    "ADRO": "Grup Adaro (Garibaldi Thohir)", "ADMR": "Grup Adaro (Garibaldi Thohir)",
    "AADI": "Grup Adaro (Garibaldi Thohir)",
    "INDY": "Grup Indika Energy",
    "MEDC": "Grup Medco (Panigoro)", "AMMN": "Grup Medco (Panigoro)",
    "BRMS": "Grup Bakrie", "BUMI": "Grup Bakrie", "BNBR": "Grup Bakrie",
    "ENRG": "Grup Bakrie",
    "MNCN": "Grup MNC (Hary Tanoesoedibjo)",
    "BSDE": "Grup Sinar Mas", "DUTI": "Grup Sinar Mas", "DMAS": "Grup Sinar Mas",
    "INKP": "Grup Sinar Mas", "TKIM": "Grup Sinar Mas",
    "DSSA": "Grup Sinar Mas", "GEMS": "Grup Sinar Mas",
    "LPKR": "Grup Lippo", "MPPA": "Grup Lippo", "SILO": "Grup Lippo", "MLPL": "Grup Lippo",
    "MEGA": "Grup CT Corp",
    "PNBN": "Grup Panin",
    "EMTK": "Grup Emtek", "BUKA": "Grup Emtek",
    "AKRA": "Grup AKR (Adikoesoemo)",
    "JPFA": "Grup Japfa (Santosa)",
    "SGRO": "Grup Sampoerna (Putera Sampoerna)",
    "NCKL": "Grup Harita",
    "GJTL": "Grup Gajah Tunggal (Nursalim)",
    "MAPI": "Grup MAP (Mitra Adiperkasa)", "MAPB": "Grup MAP (Mitra Adiperkasa)",
    "KLBF": "Grup Kalbe (Boenjamin Setiawan)", "MIKA": "Grup Kalbe (Boenjamin Setiawan)",
    "CPIN": "Grup Charoen Pokphand (Thailand)",
    "GGRM": "Grup Gudang Garam (Wonowidjojo)",
    "MINA": "Grup Raharja (Happy Hapsoro)", "BUVA": "Grup Raharja (Happy Hapsoro)",
    "RAJA": "Grup Raharja (Happy Hapsoro)", "RATU": "Grup Raharja (Happy Hapsoro)",
    "JARR": "Grup Jhonlin (Haji Isam)",
}

_SHARES = {}
_TICKER_DIR = []  # [{kode, nama}] dari saham.xlsx (seluruh emiten IDX, kecuali Pemantauan Khusus)


def _load_ticker_directory():
    """Daftar lengkap emiten IDX (kode + nama) untuk pencarian. Mengecualikan
    papan Pemantauan Khusus, konsisten dengan load_tickers."""
    global _TICKER_DIR
    if _TICKER_DIR:
        return _TICKER_DIR
    try:
        df = pd.read_excel(SAHAM_XLSX_PATH)
        if "Papan Pencatatan" in df.columns:
            df = df[~df["Papan Pencatatan"].astype(str).str.strip().eq("Pemantauan Khusus")]
        out = []
        for _, r in df.iterrows():
            kode = str(r.get("Kode", "")).strip().upper()
            nama = str(r.get("Nama Perusahaan", "")).strip()
            if kode and kode != "NAN":
                out.append({"kode": kode, "nama": nama})
        out.sort(key=lambda x: x["kode"])
        _TICKER_DIR = out
    except Exception as e:
        print(f"⚠️ gagal load ticker directory: {e}")
        _TICKER_DIR = []
    return _TICKER_DIR


def _load_shares():
    """Jumlah lembar saham per emiten dari saham.xlsx (untuk market cap)."""
    global _SHARES
    if _SHARES:
        return _SHARES
    try:
        df = pd.read_excel(SAHAM_XLSX_PATH)
        for _, r in df.iterrows():
            kode = str(r.get("Kode", "")).strip().upper()
            raw = str(r.get("Saham", "")).replace(".", "").replace(",", "").strip()
            if kode and raw.isdigit():
                _SHARES[kode] = int(raw)
    except Exception as e:
        print(f"⚠️ gagal load shares: {e}")
    return _SHARES


@asynccontextmanager
async def _lifespan(_app: "FastAPI"):
    """Nyalakan background task auto-audit sinyal (_signal_auto_loop,
    didefinisikan di bawah dekat kode signal_history lainnya) saat
    aplikasi start, matikan bersih saat berhenti. TIDAK ADA proses/infra
    baru -- cuma 1 asyncio task dalam proses yang sama (bukan Celery/cron
    terpisah), cukup untuk skala aplikasi ini."""
    task = asyncio.create_task(_signal_auto_loop())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="Ranah Saham API", version="1.0", lifespan=_lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1000)

_BASE = os.path.dirname(os.path.abspath(__file__))
_STATIC = os.path.join(_BASE, "static")


@app.get("/health")
async def health():
    """Health check untuk Railway / load balancer."""
    return {"status": "ok"}

# ---------- cache TTL sederhana (lindungi Yahoo Finance) ----------
_CACHE_TTL = 300  # detik


def _cache_get(key):
    try:
        val = _redis.get(f"cache:{key}")
        if val is None:
            return None
        return pickle.loads(val)
    except Exception:
        # fallback to None if redis error
        return None


def _cache_set(key, val):
    try:
        serialized = pickle.dumps(val)
        _redis.setex(f"cache:{key}", _CACHE_TTL, serialized)
    except Exception:
        # fallback: do nothing (cache miss next time)
        pass


# ---------- harga real-time (cache 60 detik, terpisah dari cache analisis) ----------
# yf.download(interval="1d") hanya punya candle H-1 selama sesi berlangsung.
# fast_info memberikan harga live (15-mnt delayed untuk IDX) langsung dari
# Yahoo Finance tanpa perlu download seluruh dataset historis.
_RT_TTL = 60  # detik


async def _realtime_price(ticker: str) -> dict | None:
    """Return {'price', 'prev_close', 'change_1d'} dari fast_info.
    Cache 60 detik. Return None kalau gagal (fallback ke data harian)."""
    try:
        cached = _redis.get(f"rt:{ticker}")
        if cached is not None:
            return pickle.loads(cached)
    except Exception:
        pass  # fall through to fetch

    def _fetch():
        fi = yf.Ticker(ticker).fast_info
        last = fi.last_price
        prev = fi.previous_close
        return (float(last) if last else None,
                float(prev) if prev else None)

    last, prev = await asyncio.to_thread(_fetch)
    if last and last > 0:
        change = ((last - prev) / prev * 100) if (prev and prev > 0) else 0.0
        result = {"price": last, "prev_close": prev, "change_1d": round(change, 4)}
    else:
        result = None

    try:
        if result is not None:
            _redis.setex(f"rt:{ticker}", _RT_TTL, pickle.dumps(result))
    except Exception:
        pass
    return result


# ---------- rate limit per-IP berbasis Redis ----------
# 120/menit ternyata terlalu ketat: satu kali buka halaman Beranda saja
# menembak ~11 endpoint sekaligus (tickers, universe, sektor, foreign-flow,
# macro, bsjp, ihsg, breadth, ihsgnews, screener, ohlc) + auto-refresh
# market-strip/IHSG tiap 30 detik. Dinaikkan ke 300 -- MASIH kena juga:
# ditemukan nyata di log, 1 pengguna aktif pindah antar tab (Beranda ->
# Screener -> Smart $ -> Analisis) dalam semenit sudah lewat 300 juga,
# dan begitu limit di window itu terlewati, SISA request di window yang
# sama ikut ditolak semua (bukan cuma yang "berlebihan"). Untuk demo
# 1-2 pengguna lewat ngrok (bukan layanan publik ramai), longgarkan jauh
# lebih besar -- proteksi dari scraper otomatis tetap ada, cuma budgetnya
# tidak lagi mepet untuk pemakaian wajar satu orang.
_RATE_MAX = 1200      # request
_RATE_WINDOW = 60     # per 60 detik


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    if request.url.path.startswith("/api/"):
        ip = request.client.host if request.client else "unknown"
        key = f"rate_limit:{ip}"
        try:
            # Increment and set expiry if new
            pipe = _redis.pipeline()
            pipe.incr(key)
            pipe.expire(key, _RATE_WINDOW)
            count, _ = pipe.execute()
            if count > _RATE_MAX:
                return JSONResponse(
                    {"error": "Terlalu banyak permintaan. Coba lagi sebentar."},
                    status_code=429)
        except Exception:
            # If Redis fails, fail open to avoid blocking service
            pass
    return await call_next(request)


# ---------- cache chart PNG (Redis) ----------
# generate_advanced_chart/generate_*_chart (core/charts/) menulis file PNG ke
# disk dan TIDAK PERNAH menghapusnya -- dipanggil ulang tiap request lewat
# FileResponse berarti: (1) matplotlib di-render ulang tiap kali walau data
# & parameter sama persis dalam window cache 300s, (2) file PNG menumpuk
# permanen di working directory (lihat mis. JPFA_bos.png, IHSG_fvg.png, dst
# di root repo -- sisa dari pemanggilan lama). _render_chart menulis ke file
# temp yang SELALU dihapus setelah dibaca, dan meng-cache bytes-nya di Redis
# supaya request berikutnya dengan data identik tidak perlu render ulang.
_CHART_CACHE_TTL = 300  # detik, selaras dengan _CACHE_TTL data harian


def _chart_cache_key(label: str, kind: str, df: pd.DataFrame) -> str:
    last = df.index[-1]
    sig = f"{label}:{kind}:{len(df)}:{last}:{float(df['Close'].iloc[-1])}"
    return "chart:" + hashlib.md5(sig.encode(), usedforsecurity=False).hexdigest()


async def _render_chart(label: str, kind: str, df: pd.DataFrame, gen_fn, *gen_args) -> Response:
    key = _chart_cache_key(label, kind, df)
    try:
        cached = _redis.get(key)
    except Exception:
        cached = None
    if cached is not None:
        return Response(content=cached, media_type="image/png")

    fd, tmp_path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        path = await asyncio.to_thread(gen_fn, *gen_args, output_path=tmp_path)
        if not path or not os.path.exists(path):
            raise HTTPException(500, "Gagal membuat chart.")
        with open(path, "rb") as f:
            data = f.read()
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    try:
        _redis.setex(key, _CHART_CACHE_TTL, data)
    except Exception:
        pass
    return Response(content=data, media_type="image/png")


# ---------- helper ----------
_inflight: dict[str, asyncio.Task] = {}


async def _clean(ticker: str, period: str = "1y", interval: str = "1d"):
    key = f"df:{ticker}:{period}:{interval}"
    cached = _cache_get(key)
    if cached is not None:
        return cached

    # Request coalescing: kalau ticker+period+interval yang SAMA sedang
    # di-fetch oleh request lain yang datang lebih dulu (belum sempat masuk
    # cache), tunggu hasil fetch itu saja -- jangan tembak Yahoo Finance
    # dobel. Ditemukan perlu nyata: banyak pengguna simultan sering minta
    # ticker populer yang sama (mis. BBCA) dalam detik yang hampir
    # bersamaan, sebelum cache Redis sempat terisi dari permintaan pertama.
    existing = _inflight.get(key)
    if existing is not None:
        return await existing

    async def _fetch():
        df = await async_download(ticker, period=period, interval=interval, progress=False)
        df = fix_yf_columns(df).apply(pd.to_numeric, errors="coerce").dropna()
        _cache_set(key, df)
        return df

    task = asyncio.ensure_future(_fetch())
    _inflight[key] = task
    try:
        return await task
    finally:
        _inflight.pop(key, None)


def _py(o):
    """Konversi tipe numpy (bool_/integer/floating) jadi tipe Python native
    supaya bisa di-serialize JSON oleh FastAPI. Rekursif untuk dict/list."""
    import numpy as np
    if isinstance(o, dict):
        return {k: _py(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_py(x) for x in o]
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return float(o)
    return o


def _norm_kode(kode: str) -> str:
    return kode.strip().upper().replace(".JK", "")


_IHSG_ALIASES = {"IHSG", "JKSE", "^JKSE", "COMPOSITE"}


def _resolve_ticker(kode: str) -> str:
    """Kembalikan ticker Yahoo yang benar: IHSG -> ^JKSE (tanpa .JK),
    saham biasa -> KODE.JK."""
    k = _norm_kode(kode).replace("^", "")
    if k in _IHSG_ALIASES or kode.strip().upper() in _IHSG_ALIASES:
        return "^JKSE"
    return k + ".JK"


# ---------- endpoints ----------
@app.get("/api/health")
async def health():
    return {"status": "ok"}


def _vwap_fair_value(df, lookback: int = 44) -> dict:
    """Nilai wajar berbasis VWAP (mirip kartu 'VWAP Fair Value' ARTHARA).
    MURNI dari OHLCV: VWAP = Σ(harga tipikal × volume) / Σ volume atas
    `lookback` hari terakhir. Deviasi harga vs VWAP dilaporkan dalam %
    dan z-score (dislokasi). Label klasifikasi diskon/premium."""
    d = df.tail(lookback)
    tp = (d["High"] + d["Low"] + d["Close"]) / 3.0
    volsum = float(d["Volume"].sum())
    if volsum <= 0:
        return None
    vwap = float((tp * d["Volume"]).sum() / volsum)
    price = float(df["Close"].iloc[-1])
    dev_pct = (price - vwap) / vwap * 100 if vwap else 0.0
    devs = (d["Close"] - vwap) / vwap
    sd = float(devs.std())
    z = round((dev_pct / 100) / sd, 2) if sd else 0.0
    if dev_pct <= -8:
        label = "Deep Discount"
    elif dev_pct <= -2:
        label = "Discount"
    elif dev_pct < 2:
        label = "Fair Value"
    elif dev_pct < 8:
        label = "Premium"
    else:
        label = "Deep Premium"
    return {"vwap": round(vwap, 2), "dev_pct": round(dev_pct, 2), "z": z, "label": label,
            "lookback": lookback}


def _liquidity_label(avg_value_20: float) -> str:
    """Klasifikasi likuiditas heuristik dari rata-rata NILAI transaksi
    (Rp harga x volume) 20 hari terakhir. Ambang batas KASAR berdasarkan
    pengamatan umum karakteristik saham IDX (blue chip vs saham tidur),
    BUKAN standar resmi/formal BEI -- dicatat jujur, konsisten dengan
    disiplin project ini soal tidak mengklaim lebih presisi dari yang
    sebenarnya bisa dipertanggungjawabkan."""
    if avg_value_20 >= 50_000_000_000:
        return "Sangat Likuid"
    if avg_value_20 >= 5_000_000_000:
        return "Likuid"
    if avg_value_20 >= 500_000_000:
        return "Kurang Likuid"
    return "Tidak Likuid"


def _trading_style_label(atr_pct: float) -> str:
    """Klasifikasi gaya trading heuristik dari volatilitas harian (ATR%
    terhadap harga). Saham dengan ayunan harian besar secara alami lebih
    cocok untuk horizon pendek (peluang profit cepat tapi risiko harian
    juga besar); saham dengan ayunan kecil lebih cocok dipegang lebih
    lama karena butuh waktu lebih panjang untuk pergerakan berarti.
    Heuristik sederhana, BUKAN rekomendasi horizon investasi personal."""
    if atr_pct >= 4:
        return "Intraday/Scalping"
    if atr_pct >= 2:
        return "Swing Trading"
    return "Investasi Jangka Menengah-Panjang"


def _compute_grade(score: float, likuiditas: str) -> str:
    """Grade huruf A-D: ringkasan sekali-huruf dari AI Score + likuiditas.
    Likuiditas sengaja ikut mempengaruhi grade (bukan cuma skor teknikal
    mentah) karena AI Score sendiri TIDAK memperhitungkan likuiditas sama
    sekali -- saham dengan skor teknikal bagus tapi susah ditransaksikan
    (bid/ask tipis, sering ARB/suspend) secara PRAKTIS kurang layak untuk
    dieksekusi, meski chart-nya kelihatan menarik. Heuristik gabungan
    sederhana untuk ringkasan cepat, BUKAN rating agency formal."""
    adj = score
    if likuiditas == "Tidak Likuid":
        adj -= 20
    elif likuiditas == "Kurang Likuid":
        adj -= 10
    elif likuiditas == "Sangat Likuid":
        adj += 5

    if adj >= 80:
        return "A"
    if adj >= 65:
        return "B"
    if adj >= 50:
        return "C"
    return "D"


def _compute_ringkasan_cepat(df, ai: dict) -> dict:
    """Hitung field Ringkasan Cepat (grade, likuiditas, gaya trading,
    bandar/A-D Line, potensi naik/risiko turun) dari df OHLCV + hasil
    calculate_ai_score_from_df(). DIPISAH dari _analyze_payload supaya
    /api/insight bisa REUSE persis logic yang sama (satu sumber kebenaran)
    alih-alih menghitung ulang terpisah -- menghindari risiko dua endpoint
    menampilkan angka Ringkasan Cepat yang berbeda untuk saham yang sama."""
    avg_value_20 = float((df["Close"] * df["Volume"]).tail(20).mean())
    ad = calculate_ad_line(df)
    current_price = ai.get("price") or 0
    # R1/S1 pakai calculate_snr_levels() (core/charts/snr_chart.py), lihat
    # catatan lengkap soal kenapa BUKAN calculate_target_levels() di commit
    # sebelumnya (pivot 1-candle vs pivot+swing histori sungguhan).
    snr = calculate_snr_levels(df)
    r1 = snr["r1"]
    s1 = snr["s1"]
    potensi_naik_pct = ((r1 / current_price) - 1) * 100 if current_price else 0.0
    risiko_turun_pct = (1 - (s1 / current_price)) * 100 if current_price else 0.0
    likuiditas = _liquidity_label(avg_value_20)
    return {
        "likuiditas": likuiditas,
        "avg_value_20": round(avg_value_20, 0),
        "gaya_trading": _trading_style_label(ai.get("atr_pct") or 0),
        "bandar": None if not ad else {"label": ad["label"], "sinyal": ad["sinyal"]},
        "grade": _compute_grade(ai.get("score") or 0, likuiditas),
        "potensi_naik_pct": round(potensi_naik_pct, 2),
        "risiko_turun_pct": round(risiko_turun_pct, 2),
        "r1": round(r1, 2), "s1": round(s1, 2),
    }


async def _analyze_payload(kode: str):
    """Bangun payload analisis untuk satu kode (dipakai /api/analyze &
    /api/compare). Mengembalikan dict atau melempar HTTPException."""
    kode = _norm_kode(kode)
    cache_key = f"analyze:{kode}"
    cached = _cache_get(cache_key)

    if cached is None:
        try:
            df = await _clean(kode + ".JK")
        except Exception:
            raise HTTPException(502, "Gagal mengambil data harga. Coba lagi sebentar.")
        if df is None or len(df) < 50:
            raise HTTPException(404, f"Data {kode} tidak cukup untuk analisis (butuh ≥50 hari).")
        ai = calculate_ai_score_from_df(df)
        if ai is None:
            raise HTTPException(422, f"Gagal menganalisis {kode}.")
        smc = build_smc_summary(df)
        # ===== RINGKASAN CEPAT (badge di atas halaman Analisis, & dipakai
        # ulang oleh /api/insight -- lihat _compute_ringkasan_cepat) =====
        ringkasan = _compute_ringkasan_cepat(df, ai)
        payload = {
            "kode": kode,
            "score": ai.get("score"), "rating": ai.get("rating"),
            "recommendation": ai.get("recommendation"), "signal": ai.get("signal"),
            "price": ai.get("price"), "change_1d": ai.get("change_1d"), "change_5d": ai.get("change_5d"),
            "rsi": ai.get("rsi"), "macd_bullish": ai.get("macd_bullish"),
            "vol_ratio": ai.get("vol_ratio"), "atr_pct": ai.get("atr_pct"),
            "ma20": ai.get("ma20"), "ma50": ai.get("ma50"), "ma200": ai.get("ma200"),
            "bullish_count": ai.get("bullish_count"), "bearish_count": ai.get("bearish_count"),
            "netral_count": ai.get("netral_count"),
            "insight": _narrate_technical(ai),
            "vwap_fv": _vwap_fair_value(df),
            "likuiditas": ringkasan["likuiditas"],
            "avg_value_20": ringkasan["avg_value_20"],
            "gaya_trading": ringkasan["gaya_trading"],
            "bandar": ringkasan["bandar"],
            "grade": ringkasan["grade"],
            "potensi_naik_pct": ringkasan["potensi_naik_pct"],
            "risiko_turun_pct": ringkasan["risiko_turun_pct"],
            "r1": ringkasan["r1"], "s1": ringkasan["s1"],
            "smc": None if not smc else {
                "narasi": smc.get("narasi"),
                "n_bos": smc.get("n_bos"), "n_choch": smc.get("n_choch"),
                "ob_bullish": smc.get("ob_bullish"), "ob_bearish": smc.get("ob_bearish"),
                "fvg_unfilled": smc.get("fvg_unfilled"),
                "liq_high": smc.get("liq_high"), "liq_low": smc.get("liq_low"),
            },
        }
        cached = _py(payload)
        _cache_set(cache_key, cached)

    # Override harga & change dengan data real-time (fast_info, 60-detik cache).
    # Dilakukan SETIAP REQUEST (cache hit maupun miss) supaya harga selalu
    # segar -- analisis teknikal dari daily data tetap di-cache 300 detik.
    rt = await _realtime_price(kode + ".JK")
    if rt:
        result = dict(cached)
        result["price"]     = rt["price"]
        result["change_1d"] = rt["change_1d"]
        return result

    return cached


@app.get("/api/analyze/{kode}")
async def analyze(kode: str):
    return await _analyze_payload(kode)



@app.get("/api/ohlc/{kode}")
async def ohlc(kode: str, days: int = 140):
    """Data candlestick + MA untuk chart interaktif (lightweight-charts)."""
    ticker = _resolve_ticker(kode)
    label = "IHSG" if ticker == "^JKSE" else _norm_kode(kode)
    try:
        df = await _clean(ticker)
    except Exception:
        raise HTTPException(502, "Gagal mengambil data harga.")
    if df is None or len(df) < 50:
        raise HTTPException(404, "Data tidak cukup.")
    df = df.tail(max(days, 60)).copy()
    ma20 = df["Close"].rolling(20).mean()
    ma50 = df["Close"].rolling(50).mean()
    candles, vol, m20, m50 = [], [], [], []
    for i in range(len(df)):
        t = df.index[i].strftime("%Y-%m-%d")
        o, h, l, c = (float(df["Open"].iloc[i]), float(df["High"].iloc[i]),
                      float(df["Low"].iloc[i]), float(df["Close"].iloc[i]))
        candles.append({"time": t, "open": o, "high": h, "low": l, "close": c})
        vol.append({"time": t, "value": float(df["Volume"].iloc[i]),
                    "color": "rgba(47,181,126,.5)" if c >= o else "rgba(224,86,107,.5)"})
        if not pd.isna(ma20.iloc[i]):
            m20.append({"time": t, "value": round(float(ma20.iloc[i]), 2)})
        if not pd.isna(ma50.iloc[i]):
            m50.append({"time": t, "value": round(float(ma50.iloc[i]), 2)})
    # ---- Real-time: satukan harga live ke bar TERAKHIR supaya grafik segar ----
    # Data harian Yahoo untuk bar "hari ini" sering tertinggal selama sesi.
    # fast_info memberi harga live (delayed ~15 mnt untuk IDX). Kita perbarui
    # bar terakhir (atau tambahkan bar hari ini bila belum ada) memakai harga
    # live tersebut, sehingga ujung grafik mengikuti harga terkini.
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    now_jkt = _dt.now(_tz(_td(hours=7)))
    today_jkt = now_jkt.strftime("%Y-%m-%d")
    last_price = candles[-1]["close"] if candles else None
    realtime = False
    try:
        rt = await _realtime_price(ticker)
    except Exception:
        rt = None
    if rt and rt.get("price") and candles:
        lp = float(rt["price"])
        if candles[-1]["time"] == today_jkt:
            candles[-1]["close"] = lp
            candles[-1]["high"] = max(candles[-1]["high"], lp)
            candles[-1]["low"] = min(candles[-1]["low"], lp)
        elif today_jkt > candles[-1]["time"]:
            op = float(rt.get("prev_close") or lp)
            candles.append({"time": today_jkt, "open": op,
                            "high": max(op, lp), "low": min(op, lp), "close": lp})
            vol.append({"time": today_jkt, "value": 0.0,
                        "color": "rgba(47,181,126,.5)" if lp >= op else "rgba(224,86,107,.5)"})
        last_price = lp
        realtime = True
    return {"kode": label, "candles": candles, "volume": vol, "ma20": m20, "ma50": m50,
            "phases": detect_phases(df),
            "last_price": last_price, "realtime": realtime, "as_of": now_jkt.strftime("%H:%M")}


@app.get("/api/compare")
async def compare(kodes: str = ""):
    """Bandingkan beberapa saham (mis. ?kodes=BBCA,BMRI,TLKM)."""
    lst = [k for k in (kodes or "").split(",") if k.strip()][:5]
    if not lst:
        raise HTTPException(400, "Sertakan minimal 1 kode, mis. ?kodes=BBCA,BMRI")
    # Fetch semua ticker konkuren (maks 5, sudah dibatasi di atas) -- dulu
    # sekuensial per-ticker, jadi total waktu tunggu = jumlah waktu semua
    # ticker; asyncio.gather membuatnya paralel (waktu tunggu ~= ticker
    # paling lambat saja).
    results = await asyncio.gather(*(_analyze_payload(k) for k in lst), return_exceptions=True)
    out = []
    for k, res in zip(lst, results):
        if isinstance(res, HTTPException):
            out.append({"kode": _norm_kode(k), "error": res.detail})
        elif isinstance(res, Exception):
            raise res
        else:
            p = res
            out.append({"kode": p["kode"], "score": p["score"], "rating": p["rating"],
                        "recommendation": p["recommendation"], "price": p["price"],
                        "change_1d": p["change_1d"], "change_5d": p["change_5d"],
                        "rsi": p["rsi"], "macd_bullish": p["macd_bullish"],
                        "vol_ratio": p.get("vol_ratio"), "atr_pct": p.get("atr_pct"),
                        "ma50": p.get("ma50"), "ma200": p.get("ma200"),
                        "bullish_count": p["bullish_count"], "bearish_count": p["bearish_count"],
                        "netral_count": p.get("netral_count")})
    return {"items": out}


@app.get("/api/chart/{kode}")
async def chart(kode: str):
    kode = _norm_kode(kode)
    try:
        df = await _clean(kode + ".JK")
    except Exception:
        raise HTTPException(502, "Gagal mengambil data harga.")
    if df is None or len(df) < 50:
        raise HTTPException(404, "Data tidak cukup.")
    return await _render_chart(kode, "advanced", df, generate_advanced_chart, df, kode)


@app.get("/api/news")
async def news(kode: str = "", limit: int = 40):
    kode = _norm_kode(kode) if kode else ""
    items = await fetch_news(keyword=kode or None, limit=min(limit, 80))
    if items is None:
        # Semua sumber sedang gagal diakses. Jangan lempar 502 (tampil
        # sebagai kotak error merah di UI) -- balas 200 dengan daftar
        # kosong + catatan lembut supaya pengguna cukup mencoba lagi.
        return {"kode": kode, "items": [],
                "note": "Sumber berita sedang tidak dapat diakses. Coba lagi sebentar."}
    if kode and items:
        try:
            items = await enrich_news_with_signals(items)
        except Exception:
            pass
    out = [{
        "title": it.get("title"), "source": it.get("source"), "link": it.get("link"),
        "summary": (it.get("summary") or "")[:280],
        "pub_date": it.get("pub_date") or "",
        "sumber_lain": it.get("sumber_lain") or [],
        "emiten": it.get("emiten") or [],
        "sinyal": {k: {"score": v["score"], "rating": v["rating"], "signal": v["signal"]}
                   for k, v in (it.get("sinyal") or {}).items()},
    } for it in (items or [])]
    return {"kode": kode, "items": out}


@app.get("/api/report/{kode}")
async def report(kode: str):
    from core.trading_plan import calculate_fixed_entry_levels_from_df
    from core.insight import generate_insight, _derive_recommendation
    from core.smc import detect_bos_choch, detect_order_blocks, detect_fvg, detect_liquidity_pools
    from core.charts.smc_chart import (
        generate_bos_chart, generate_orderblock_chart, generate_fvg_chart, generate_liquidity_chart,
    )
    import datetime as _dt

    kode = _norm_kode(kode)
    try:
        df = await _clean(kode + ".JK")
    except Exception:
        raise HTTPException(502, "Gagal mengambil data harga.")
    if df is None or len(df) < 50:
        raise HTTPException(404, "Data tidak cukup.")
    ai = calculate_ai_score_from_df(df)
    if ai is None:
        raise HTTPException(422, "Gagal menganalisis.")

    # Fetch IHSG + news secara paralel
    async def _safe(coro):
        try: return await coro
        except: return None

    df_ihsg, news_items = await asyncio.gather(
        _safe(_clean("^JKSE")),
        _safe(fetch_news(keyword=kode, limit=8)),
    )

    # Konteks IHSG + RS
    ai_ihsg, rs_data = None, None
    if df_ihsg is not None and len(df_ihsg) >= 50:
        try: ai_ihsg = calculate_ai_score_from_df(df_ihsg)
        except: pass
        try:
            rs_data = calculate_relative_strength(df, df_ihsg)
        except: pass

    # VWAP fair value
    vwap_fv = None
    try: vwap_fv = _vwap_fair_value(df)
    except: pass

    # Fixed entry levels (trading plan)
    fixed_entries = None
    try:
        created_date = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        fixed_entries = calculate_fixed_entry_levels_from_df(df, created_date)
    except: pass

    # SMC
    smc = build_smc_summary(df)

    # SMC charts — generate semua 4 jenis
    smc_charts = {}
    for label, gen_fn, detect_fn in [
        ("BOS/CHoCH", generate_bos_chart, lambda: detect_bos_choch(df, 5, 5)),
        ("Order Block", generate_orderblock_chart, lambda: detect_order_blocks(df)),
        ("Fair Value Gap", generate_fvg_chart, lambda: detect_fvg(df)),
        ("Liquidity", generate_liquidity_chart, lambda: detect_liquidity_pools(df)),
    ]:
        try:
            path = await asyncio.to_thread(gen_fn, df, kode, detect_fn())
            if path and os.path.exists(path):
                smc_charts[label] = path
        except: pass

    # Full insight naratif
    insight = {"teknikal": _narrate_technical(ai)}
    try:
        insight = await generate_insight(kode, ai, ai_ihsg, rs_data, news_items)
    except: pass

    # Recommendation
    rec_badge = None
    try: rec_badge = _derive_recommendation(ai, ai_ihsg)
    except: pass

    # Chart utama
    chart_path = None
    try:
        chart_path = await asyncio.to_thread(generate_advanced_chart, df, kode)
    except Exception as _ce:
        import traceback
        print(f"⚠️ [report] chart gagal: {_ce}\n{traceback.format_exc()}")

    try:
        rd = build_report_data(kode, kode, ai, insight=insight, ai_ihsg=ai_ihsg,
                               rs_data=rs_data, news_items=news_items,
                               chart_path=chart_path, smc=smc, smc_charts=smc_charts,
                               vwap_fv=vwap_fv, fixed_entries=fixed_entries,
                               rec_badge=rec_badge)
    except Exception as _rde:
        import traceback
        print(f"⚠️ [report] build_report_data gagal: {_rde}\n{traceback.format_exc()}")
        raise HTTPException(500, f"Gagal menyusun laporan: {_rde}")

    out = os.path.join(tempfile.gettempdir(), f"Laporan_{kode}.pdf")
    try:
        await asyncio.to_thread(generate_report_pdf, rd, out)
    except Exception as _pdfe:
        import traceback
        print(f"⚠️ [report] generate_report_pdf gagal: {_pdfe}\n{traceback.format_exc()}")
        raise HTTPException(500, f"Gagal render PDF: {_pdfe}")

    if not os.path.exists(out):
        raise HTTPException(500, "File PDF tidak terbuat.")
    return FileResponse(out, media_type="application/pdf", filename=f"Laporan_{kode}.pdf")


@app.get("/api/ihsg")
async def ihsg():
    cached = _cache_get("ihsg:analyze")

    if cached is None:
        try:
            dd = await _clean("^JKSE", period="3mo")
            dw = await _clean("^JKSE", period="1y", interval="1wk")
            dl = await _clean("^JKSE", period="2y")
        except Exception:
            raise HTTPException(502, "Gagal mengambil data IHSG.")
        analysis = analyze_ihsg_with_backtest(dd, dw, dl)
        if not analysis:
            raise HTTPException(422, "Gagal menganalisis IHSG.")
        bt = analysis.get("backtest_result") or {}
        smc = build_smc_summary(dd)
        # ===== RINGKASAN CEPAT untuk IHSG (sama semangat dgn /api/analyze) =====
        # HANYA 2 tambahan yang genuinely masuk akal utk INDEKS (bukan saham
        # individual) -- "Likuiditas"/"Grade"/"Gaya Trading" dari versi saham
        # SENGAJA tidak dipaksakan ke sini karena tidak relevan: IHSG bukan
        # instrumen yang "kurang likuid" atau "cocok utk scalping", konsepnya
        # cuma masuk akal per-saham individual.
        # 1. Bandar/psikologi pasar -- proxy sama (Chaikin A/D Line) tapi
        #    dihitung di atas data ^JKSE, jadi baca "akumulasi/distribusi
        #    pasar secara keseluruhan", bukan 1 saham.
        # 2. Potensi Naik/Risiko Turun % -- REUSE murni dari resistance_1/
        #    support_1 yang SUDAH dihitung analyze_ihsg_with_backtest(),
        #    cuma dibingkai ulang jadi persentase jarak dari harga sekarang
        #    (bukan komputasi baru).
        ihsg_ad = calculate_ad_line(dd)
        ihsg_price = analysis.get("current_price") or 0
        ihsg_r1 = analysis.get("resistance_1")
        ihsg_s1 = analysis.get("support_1")
        ihsg_potensi_naik_pct = ((ihsg_r1 / ihsg_price) - 1) * 100 if (ihsg_price and ihsg_r1) else None
        ihsg_risiko_turun_pct = (1 - (ihsg_s1 / ihsg_price)) * 100 if (ihsg_price and ihsg_s1) else None
        payload = {
            "prediction": analysis.get("prediction"),
            "confidence": analysis.get("confidence"),
            "action": analysis.get("action"),
            "target_move": analysis.get("target_move"),
            "current_price": analysis.get("current_price"),
            "daily_change": analysis.get("daily_change"),
            "bullish_score": analysis.get("bullish_score"),
            "bearish_score": analysis.get("bearish_score"),
            "rsi": analysis.get("rsi"),
            "rsi_divergence": analysis.get("rsi_divergence"),
            "macd_signal": analysis.get("macd_signal"),
            "bb_position": analysis.get("bb_position"),
            "bb_squeeze": analysis.get("bb_squeeze"),
            "ma_trend": analysis.get("ma_trend"),
            "ma20": analysis.get("ma20"), "ma50": analysis.get("ma50"),
            "volume_trend": analysis.get("volume_trend"),
            "volume_ratio": analysis.get("volume_ratio"),
            "fib_position": analysis.get("fib_position"),
            "fib_382": analysis.get("fib_382"), "fib_500": analysis.get("fib_500"),
            "fib_618": analysis.get("fib_618"),
            "poc": analysis.get("poc"),
            "support_1": analysis.get("support_1"), "support_2": analysis.get("support_2"),
            "resistance_1": analysis.get("resistance_1"), "resistance_2": analysis.get("resistance_2"),
            "entry_zone": analysis.get("entry_zone"),
            "stop_loss": analysis.get("stop_loss"),
            "candle_patterns": analysis.get("candle_patterns"),
            "bandar": None if not ihsg_ad else {"label": ihsg_ad["label"], "sinyal": ihsg_ad["sinyal"]},
            "potensi_naik_pct": round(ihsg_potensi_naik_pct, 2) if ihsg_potensi_naik_pct is not None else None,
            "risiko_turun_pct": round(ihsg_risiko_turun_pct, 2) if ihsg_risiko_turun_pct is not None else None,
            "backtest": {"win_rate": bt.get("win_rate"), "base_rate": bt.get("base_rate"),
                         "edge": bt.get("edge"), "n": bt.get("n")} if bt else None,
            "smc": None if not smc else {
                "narasi": smc.get("narasi"), "n_bos": smc.get("n_bos"), "n_choch": smc.get("n_choch"),
                "ob_bullish": smc.get("ob_bullish"), "ob_bearish": smc.get("ob_bearish"),
                "fvg_unfilled": smc.get("fvg_unfilled"),
                "liq_high": smc.get("liq_high"), "liq_low": smc.get("liq_low"),
            },
        }
        cached = _py(payload)
        _cache_set("ihsg:analyze", cached)

    # Override harga IHSG dengan real-time setiap request (60-detik cache)
    rt = await _realtime_price("^JKSE")
    if rt:
        result = dict(cached)
        result["current_price"] = rt["price"]
        result["daily_change"]  = rt["change_1d"]
        return result

    return cached


@app.get("/api/ihsg/report")
async def ihsg_report():
    from core.sector_rotation import get_sector_performance
    from core.insight import generate_market_insight
    from core.smc import detect_bos_choch, detect_order_blocks, detect_fvg, detect_liquidity_pools
    from core.charts.smc_chart import (
        generate_bos_chart, generate_orderblock_chart, generate_fvg_chart, generate_liquidity_chart,
    )

    async def _safe(coro):
        try: return await coro
        except: return None

    try:
        dd = await _clean("^JKSE", period="3mo")
        dw = await _clean("^JKSE", period="1y", interval="1wk")
        dl = await _clean("^JKSE", period="2y")
    except Exception:
        raise HTTPException(502, "Gagal mengambil data IHSG.")
    analysis = analyze_ihsg_with_backtest(dd, dw, dl)
    if not analysis:
        raise HTTPException(422, "Gagal menganalisis IHSG.")

    # Sector + news in parallel
    sector_data, news_items = await asyncio.gather(
        _safe(get_sector_performance()),
        _safe(fetch_news(keyword="IHSG bursa saham", limit=8)),
    )

    # Market insight naratif
    ai_ihsg = None
    market_insight = None
    try:
        ai_ihsg = calculate_ai_score_from_df(dd)
        market_insight = await generate_market_insight(ai_ihsg, sector_data, news_items)
    except: pass

    smc = build_smc_summary(dd)

    # SMC charts
    smc_charts = {}
    for label, gen_fn, detect_fn in [
        ("BOS/CHoCH", generate_bos_chart, lambda: detect_bos_choch(dd, 5, 5)),
        ("Order Block", generate_orderblock_chart, lambda: detect_order_blocks(dd)),
        ("Fair Value Gap", generate_fvg_chart, lambda: detect_fvg(dd)),
        ("Liquidity", generate_liquidity_chart, lambda: detect_liquidity_pools(dd)),
    ]:
        try:
            path = await asyncio.to_thread(gen_fn, dd, "IHSG", detect_fn())
            if path and os.path.exists(path):
                smc_charts[label] = path
        except: pass

    chart_path = await asyncio.to_thread(generate_advanced_chart, dd, "IHSG")
    rd = build_ihsg_report_data(analysis, sector_data, market_insight, news_items,
                                chart_path, smc=smc, smc_charts=smc_charts)
    out = os.path.join(tempfile.gettempdir(), "Laporan_IHSG.pdf")
    await asyncio.to_thread(generate_ihsg_report_pdf, rd, out)
    return FileResponse(out, media_type="application/pdf", filename="Laporan_IHSG.pdf")


# Universe Tier-1 (~45 saham paling likuid) untuk scan cepat di screener.
SCREENER_UNIVERSE = [
    "BBCA", "BBRI", "BMRI", "BBNI", "TLKM", "ASII", "UNVR", "ICBP", "INDF", "KLBF",
    "GGRM", "HMSP", "UNTR", "ADRO", "PTBA", "ITMG", "ANTM", "INCO", "MDKA", "TINS",
    "SMGR", "INTP", "CPIN", "JPFA", "AKRA", "EXCL", "ISAT", "TOWR", "TBIG", "MNCN",
    "ACES", "MAPI", "ERAA", "AMRT", "GOTO", "BUKA", "BRPT", "TPIA", "BRIS", "ARTO",
    "MEDC", "PGAS", "JSMR", "BRMS", "RAJA",
]

# Universe Tier-2 (~250 saham likuid IDX) — lebih luas dari Tier-1 tapi
# jauh lebih cepat dari scan semua 793. Dipakai saat scope="medium".
LIQUID_250 = [
    # ── Perbankan & Keuangan ──
    "BBCA", "BBRI", "BMRI", "BBNI", "BRIS", "ARTO", "BTPS", "MEGA",
    "BDMN", "BJTM", "BJBR", "PNBN", "NISP", "BNGA", "BNLI", "BBMD",
    "ADMF", "BFIN", "MFIN", "VRNA", "WOMF", "MREI", "ASBI",
    # ── Consumer Non-Cyclical ──
    "UNVR", "ICBP", "INDF", "KLBF", "GGRM", "HMSP", "SIDO", "ULTJ",
    "MYOR", "ROTI", "DLTA", "MLBI", "CPIN", "JPFA", "AMRT", "LSIP",
    "AALI", "SGRO", "SSMS", "PALM", "TBLA", "BWPT", "TAPG", "STTP",
    "CAMP", "GOOD", "KEJU",
    # ── Energi & Pertambangan ──
    "ADRO", "PTBA", "ITMG", "MEDC", "PGAS", "AKRA", "BYAN", "HRUM",
    "DSSA", "TOBA", "GEMS", "BSSR", "KKGI", "MYOH", "BRMS", "RAJA",
    "DEWA", "FIRE", "INDY", "ELSA", "PTRO", "SMMT", "CUAN", "ARCI",
    "PGEO", "AMMN",
    # ── Material Dasar ──
    "ANTM", "INCO", "MDKA", "TINS", "SMGR", "INTP", "BRPT", "TPIA",
    "SMBR", "WTON", "BTON", "ISSP", "KRAS", "NIKL", "AMFG", "AGII",
    "MLIA", "INKP", "TKIM", "ALKA", "NCKL", "DPUM",
    # ── Infrastruktur ──
    "TLKM", "EXCL", "ISAT", "TOWR", "TBIG", "JSMR", "SUPR",
    "WIKA", "WSKT", "PTPP", "ADHI", "PPRE", "LINK",
    # ── Industri ──
    "ASII", "UNTR", "AUTO", "SMSM", "IMAS", "INDS", "BRAM", "HEXA",
    "ASSA", "BIRD", "GIAA", "GJTL", "FASW", "SRIL", "SMDR",
    # ── Consumer Cyclical ──
    "MNCN", "ACES", "MAPI", "ERAA", "LPPF", "RALS", "KINO",
    "MAPB", "EMTK", "MLPL", "MIDI", "CSMI", "PZZA",
    # ── Kesehatan ──
    "MIKA", "SILO", "HEAL", "PRDA", "IRRA", "DVLA",
    "TSPC", "KAEF", "SCPI", "SOHO", "PHAR",
    # ── Teknologi ──
    "GOTO", "BUKA", "DMMX", "KREN", "MTDL", "DCII", "ARNA",
    # ── Properti & Real Estate ──
    "CTRA", "BSDE", "SMRA", "PWON", "LPKR", "JRPT", "APLN",
    "MDLN", "DUTI", "DMAS", "MKPI", "PLIN", "GPRA", "NRCA",
    "CITY", "KIJA", "BEST",
    # ── Logistik & Transportasi ──
    "HITS", "LEAD", "TMAS", "SHIP",
]


@app.get("/api/smc/{kode}/{kind}")
async def smc_chart(kode: str, kind: str):
    """Chart SMC per komponen (PNG). kind: bos | ob | fvg | liq. Mendukung
    saham maupun IHSG (kode=IHSG -> ^JKSE)."""
    ticker = _resolve_ticker(kode)
    label = "IHSG" if ticker == "^JKSE" else _norm_kode(kode)
    try:
        df = await _clean(ticker)
    except Exception:
        raise HTTPException(502, "Gagal mengambil data harga.")
    if df is None or len(df) < 50:
        raise HTTPException(404, "Data tidak cukup.")
    kind = kind.lower()
    mapping = {
        "bos": (generate_bos_chart, lambda: detect_bos_choch(df, 5, 5)),
        "ob": (generate_orderblock_chart, lambda: detect_order_blocks(df)),
        "fvg": (generate_fvg_chart, lambda: detect_fvg(df)),
        "liq": (generate_liquidity_chart, lambda: detect_liquidity_pools(df)),
    }
    if kind not in mapping:
        raise HTTPException(400, "kind harus salah satu: bos, ob, fvg, liq")
    gen, detect = mapping[kind]
    try:
        return await _render_chart(label, kind, df, gen, df, label, detect())
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(500, "Gagal membuat chart SMC.")


@app.get("/api/screenerpro")
async def screenerpro():
    """Screener gaya Minervini (8 kriteria trend template + RS vs IHSG +
    momentum). Skor ≥65 saja. Atas universe likuid, di-cache."""
    cached = _cache_get("screenerpro")
    if cached is not None:
        return cached
    from core.screening_pro import run_screenerpro
    try:
        ihsg_raw = await _clean("^JKSE", period="1y")
        market_close = ihsg_raw["Close"] if ihsg_raw is not None and len(ihsg_raw) else None
        res = await run_screenerpro([t + ".JK" for t in SCREENER_UNIVERSE], market_close=market_close)
    except Exception:
        raise HTTPException(502, "Gagal menjalankan screener pro.")
    payload = _py({"items": res or [], "universe": len(SCREENER_UNIVERSE)})
    _cache_set("screenerpro", payload)
    return payload


# ---------- skor keyakinan (confidence score / Top Pick) ----------
# REVISI (Juli 2026, permintaan eksplisit user): ranking SEBELUMNYA cuma
# menggabungkan AI Score + Minervini + Confluence -- semuanya murni
# TEKNIKAL, tidak ada satupun yang mempertimbangkan likuiditas atau
# risk/reward, jadi saham tidak likuid dengan chart kebetulan bagus bisa
# nangkring di #1 Top Pick walau praktis susah dieksekusi. Bobot sekarang
# menyertakan likuiditas & risk/reward teknikal (REUSE fungsi yang sama
# dipakai Ringkasan Cepat di /api/analyze -- _liquidity_label,
# calculate_snr_levels, calculate_ad_line -- BUKAN heuristik baru
# terpisah), plus saham "Tidak Likuid"/"Kurang Likuid" DIBATASI skor
# maksimalnya (bukan disembunyikan total -- tetap tampil dengan warning
# eksplisit, sesuai instruksi "hindari ATAU beri warning jelas").
# Fundamental minimum SENGAJA tidak ikut jadi bobot skor -- fetch
# fundamental per-saham (yfinance .info) lambat & unitnya tidak selalu
# konsisten (lihat catatan jujur di core/fundamental.py), jadi market cap
# (dari shares x harga, sudah ada lokal tanpa network call) dipakai
# sebagai KONTEKS tampilan saja, bukan komponen skor.
_CONFIDENCE_DEFAULT_WEIGHTS = {"ai": 0.25, "mv": 0.20, "cf": 0.15, "liq": 0.20, "rr": 0.20}


def _confluence_norm(bullish: int, bearish: int) -> float:
    return round(max(0.0, min(100.0, 50 + (bullish - bearish) * (50 / 6))), 1)


def _liquidity_score(likuiditas: str) -> float:
    return {"Sangat Likuid": 100.0, "Likuid": 75.0, "Kurang Likuid": 40.0, "Tidak Likuid": 10.0}.get(likuiditas, 50.0)


def _rr_score(rr: float | None) -> float:
    """Skor 0-100 dari rasio risk/reward teknikal (potensi naik ke R1
    dibanding risiko turun ke S1). None (data tidak cukup) dianggap netral
    (50), BUKAN nol -- supaya tidak menghukum saham yang datanya kebetulan
    tidak lengkap padahal indikator lain bagus."""
    if rr is None:
        return 50.0
    if rr >= 2:
        return 100.0
    if rr >= 1.5:
        return 80.0
    if rr >= 1:
        return 60.0
    if rr >= 0.5:
        return 35.0
    return 15.0


def _apply_liquidity_cap(score: float, likuiditas: str) -> tuple[float, bool]:
    """Batasi (bukan hilangkan) skor gabungan kalau likuiditas buruk --
    lihat catatan di atas _CONFIDENCE_DEFAULT_WEIGHTS. Returns (skor akhir,
    apakah kena batas)."""
    if likuiditas == "Tidak Likuid" and score > 35:
        return 35.0, True
    if likuiditas == "Kurang Likuid" and score > 55:
        return 55.0, True
    return score, False


def _confidence_reasons(it: dict) -> tuple[list[str], list[str]]:
    """Alasan (kenapa masuk top pick) & warning (risiko yang perlu
    diwaspadai) -- SEMUA diturunkan dari field yang sudah dihitung, tidak
    ada klaim baru. Dipisah 2 list supaya frontend bisa tampilkan beda
    warna (netral vs waspada)."""
    reasons, warnings = [], []
    if it["ai_score"] >= 65:
        reasons.append(f"AI Score kuat ({it['ai_score']:.0f}/100)")
    if it["minervini_criteria_met"] >= 6:
        reasons.append(f"Kriteria Minervini terpenuhi ({it['minervini_criteria_met']}/8)")
    if it["confluence_bullish"] > it["confluence_bearish"]:
        reasons.append(f"Konfluensi bullish {it['confluence_bullish']}-{it['confluence_bearish']}")
    bandar = it.get("bandar")
    if bandar and bandar["label"] in ("Akumulasi", "Akumulasi Tersembunyi"):
        reasons.append(f"Proxy volume: {bandar['label']}")
    rr = it.get("rr_ratio")
    if rr is not None and rr >= 1.5:
        reasons.append(f"RR teknikal {rr:.1f}:1 (target take profit > risiko stop loss)")
    if it["likuiditas"] in ("Sangat Likuid", "Likuid"):
        reasons.append(f"Likuiditas {it['likuiditas']}")
    pattern_label = "Sinyal momentum" if (it.get("pattern") or "").startswith("MACD") else "Pola chart"
    if it.get("pattern") and it.get("pattern_bias") == "BULLISH":
        reasons.append(f"{pattern_label}: {it['pattern']} (bullish)")

    if it["likuiditas"] in ("Tidak Likuid", "Kurang Likuid"):
        warnings.append(f"Likuiditas {it['likuiditas']} -- eksekusi & spread bisa jadi kendala nyata")
    if rr is not None and rr < 1:
        warnings.append(f"Risiko stop loss lebih besar dari target take profit (RR {rr:.1f}:1)")
    if bandar and bandar["label"] in ("Distribusi", "Distribusi Tersembunyi"):
        warnings.append(f"Proxy volume: {bandar['label']} -- volume belum mengonfirmasi penguatan")
    if it.get("pattern") and it.get("pattern_bias") == "BEARISH":
        warnings.append(f"{pattern_label}: {it['pattern']} (bearish) -- perlu diwaspadai meski skor gabungan tinggi")

    if not reasons:
        reasons.append("Skor gabungan cukup untuk masuk daftar, tanpa satu faktor yang menonjol.")
    return reasons, warnings


async def _signal_entry_price_lookup(kode: str) -> float | None:
    """Harga REAL-TIME (reuse _realtime_price) dipakai sebagai entry_price
    saat mencatat sinyal BARU -- BUKAN closing harian, yang JUGA dipakai
    menghitung sinyalnya sendiri (lookahead bias kecil, lihat catatan di
    core/signal_history.py::record_top_picks). Dipisah jadi fungsi modul
    (bukan closure lokal di dalam confidence()) supaya bisa dipakai ulang
    oleh siklus auto-audit berkala (_run_signal_auto_cycle)."""
    try:
        rt = await _realtime_price(kode + ".JK")
        return rt["price"] if rt else None
    except Exception:
        return None


async def _signal_audit_price_lookup(kode: str) -> float | None:
    """Harga closing harian terakhir (via _clean, sudah cache 300 detik)
    dipakai utk audit sinyal yang SUDAH tercatat -- horison audit historis
    (hari/minggu) tidak butuh presisi real-time, dan reuse cache yang sama
    dgn endpoint lain menghindari panggilan jaringan tambahan."""
    try:
        df = await _clean(kode + ".JK")
        if df is None or len(df) == 0:
            return None
        return float(df["Close"].iloc[-1])
    except Exception:
        return None


async def _run_signal_audit_and_notify() -> list[dict]:
    """Audit semua sinyal OPEN + kirim notifikasi Telegram (kalau
    dikonfigurasi -- lihat core/telegram_notify.py, no-op aman kalau
    tidak) utk yang BARU selesai. Dipakai bersama oleh /api/signals
    (dipicu user membuka halaman Audit Sinyal) DAN oleh siklus otomatis
    berkala (_run_signal_auto_cycle) -- satu sumber logic, tidak ada
    duplikasi antara jalur manual dan jalur background."""
    from core.signal_history import audit_open_signals
    from core.telegram_notify import send_message, format_signal_resolved

    resolved = await audit_open_signals(_signal_audit_price_lookup)
    for sig in resolved:
        try:
            await send_message(format_signal_resolved(sig))
        except Exception as e:
            print(f"⚠️ Gagal kirim notifikasi sinyal selesai: {type(e).__name__}: {e}")
    return resolved


# Interval siklus auto-audit background (detik) -- default 600 (10 menit),
# meniru cadence kompetitor yang jadi rujukan user. Bisa diubah lewat env
# var tanpa redeploy kode kalau perlu diperlambat/dipercepat.
SIGNAL_AUTO_INTERVAL_SECONDS = int(os.getenv("SIGNAL_AUTO_INTERVAL_SECONDS", "600"))


async def _run_signal_auto_cycle():
    """Satu putaran auto-audit: (1) refresh Top Pick -- otomatis mencatat
    sinyal baru & mengirim notifikasi Telegram utk itu (logic ada di
    dalam confidence(), dipanggil LANGSUNG sebagai fungsi biasa, pola yang
    sama dipakai /api/insight/{kode} memanggil ihsg()); (2) audit semua
    sinyal OPEN + notifikasi utk yang baru selesai. Dipisah dari loop-nya
    sendiri (bukan langsung di dalam while True) supaya SATU putaran bisa
    dipanggil & ditest langsung tanpa perlu menunggu interval sungguhan."""
    try:
        await confidence()
    except Exception as e:
        print(f"⚠️ auto-cycle: gagal refresh Top Pick: {type(e).__name__}: {e}")
    try:
        await _run_signal_audit_and_notify()
    except Exception as e:
        print(f"⚠️ auto-cycle: gagal audit sinyal: {type(e).__name__}: {e}")


async def _signal_auto_loop():
    """Loop background tak berhenti: tunggu SIGNAL_AUTO_INTERVAL_SECONDS,
    jalankan 1 putaran, ulangi. Kegagalan tak terduga pada satu putaran
    (di luar yang sudah ditangani _run_signal_auto_cycle sendiri) TIDAK
    BOLEH menghentikan loop selamanya -- dibungkus try/except supaya
    proses auto-audit tetap hidup sampai aplikasi benar-benar berhenti."""
    while True:
        await asyncio.sleep(SIGNAL_AUTO_INTERVAL_SECONDS)
        try:
            await _run_signal_auto_cycle()
        except Exception as e:
            print(f"⚠️ signal auto loop error tak terduga: {type(e).__name__}: {e}")


async def _confidence_raw_signals() -> list[dict]:
    """Hitung AI Score + Minervini + Confluence + likuiditas + risk/reward
    + proxy bandar untuk SCREENER_UNIVERSE dari satu fetch period=1y
    bersama. Cache global 300 detik (sama untuk semua user, tidak
    bergantung personalisasi)."""
    cached = _cache_get("confidence:raw")
    if cached is not None:
        return cached

    from core.async_yf import async_download_many
    from core.screening_pro import _score_minervini, calculate_confluence, detect_patterns

    ihsg_raw = await _clean("^JKSE", period="1y")
    market_close = ihsg_raw["Close"] if ihsg_raw is not None and len(ihsg_raw) else None

    shares = _load_shares()
    tickers = [t + ".JK" for t in SCREENER_UNIVERSE]
    data = await async_download_many(tickers, period="1y", interval="1d")

    items = []
    for ticker, df_raw in data.items():
        kode = ticker.replace(".JK", "")
        try:
            df = fix_yf_columns(df_raw).apply(pd.to_numeric, errors="coerce").dropna()
            if len(df) < 200:
                continue
            ai = calculate_ai_score_from_df(df)
            mv = _score_minervini(df, kode, market_close)
            cf = calculate_confluence(df, kode)
            if not ai or not mv or not cf:
                continue

            price = mv["harga"] or 0
            avg_value_20 = float((df["Close"] * df["Volume"]).tail(20).mean())
            likuiditas = _liquidity_label(avg_value_20)
            # BUG NYATA yang diperbaiki (temuan user langsung dari Audit
            # Sinyal): potensi_naik_pct/risiko_turun_pct SEBELUMNYA pakai
            # calculate_snr_levels() (jarak ke R1/S1 pivot+swing terdekat) --
            # itu cocok utk badge Ringkasan Cepat ("seberapa dekat level
            # berikutnya", murni informasional), TAPI SALAH dipakai sebagai
            # target trading plan Top Pick/Audit Sinyal: kalau hari terakhir
            # kebetulan range-nya kecil, R1/S1 bisa cuma berjarak <1% dari
            # harga -- target SEKETAT itu (mis. SL -0.4%, dilihat nyata pada
            # JPFA/UNTR) hampir pasti kena cuma dari noise harian biasa,
            # bukan risiko sungguhan yang terealisasi. Diganti pakai logic
            # yang SAMA dipakai fitur "Rencana Trading" (calculate_fixed_
            # entry_levels_from_df, skenario 'normal') -- SL = support
            # terdekat DIKURANGI buffer 0.2xATR (bukan support mentah), TP1
            # = MAKSIMUM(3%, risk%) sehingga RR selalu >= 1:1 dan TP tidak
            # pernah lebih ketat dari SL-nya sendiri. Ini logic yang SUDAH
            # ada & teruji (dipakai "Rencana Trading" di halaman Analisis),
            # bukan heuristik baru.
            from core.trading_plan import calculate_fixed_entry_levels_from_df
            plan = calculate_fixed_entry_levels_from_df(df, "")
            normal = (plan or {}).get("scenarios", {}).get("normal")
            potensi_naik_pct = normal["tp1_pct"] if normal else None
            risiko_turun_pct = normal["risk_pct"] if normal else None
            rr_ratio = (potensi_naik_pct / risiko_turun_pct
                        if potensi_naik_pct and risiko_turun_pct and risiko_turun_pct > 0 else None)
            ad = calculate_ad_line(df)
            market_cap = (shares.get(kode, 0) * price) or None
            # Pattern Analyst: reuse detect_patterns() (core/screening_pro.py,
            # rule-based, sudah ada & teruji lewat "Pattern Scan") -- BUKAN
            # heuristik baru. Cuma pola PERTAMA (kalau ada) yang disimpan
            # sebagai konteks ringkas "kenapa sinyal ini muncul", ditampilkan
            # di alasan Top Pick & kartu Signal Confirmed.
            pattern_result = detect_patterns(df, kode)
            first_pattern = pattern_result["patterns"][0] if pattern_result.get("patterns") else None
            pattern_name = first_pattern["nama"] if first_pattern else None
            pattern_bias = first_pattern["bias"] if first_pattern else None
            # Dicek TERPISAH dari pattern_name/pattern_bias di atas (yang
            # cuma menyimpan pola PERTAMA sebagai badge ringkas) -- kalau
            # saham kebetulan punya pola struktur (mis. Double Top) DAN
            # histogram MACD baru cross bullish di saat bersamaan,
            # pattern_name hanya akan berisi yang pertama, tapi entry point
            # MACD Cross (record_macd_cross_signals di core/signal_history.py)
            # tetap harus terdeteksi apa adanya, tidak boleh "tertutup" pola lain.
            macd_bullish_cross = any(
                p["nama"] == "MACD HISTOGRAM BULLISH CROSS" for p in pattern_result.get("patterns", [])
            )

            items.append({
                "kode": kode,
                "harga": price,
                "sektor": SECTOR_MAP_UNIVERSE.get(kode, "Lainnya"),
                "market_cap": market_cap,
                "ai_score": ai["score"],
                "ai_rating": ai["rating"],
                "minervini_score": mv["skor"],
                "minervini_criteria_met": mv["criteria_met"],
                "confluence_bullish": cf["bullish"],
                "confluence_bearish": cf["bearish"],
                "likuiditas": likuiditas,
                "avg_value_20": round(avg_value_20, 0),
                "potensi_naik_pct": round(potensi_naik_pct, 2) if potensi_naik_pct is not None else None,
                "risiko_turun_pct": round(risiko_turun_pct, 2) if risiko_turun_pct is not None else None,
                "rr_ratio": round(rr_ratio, 2) if rr_ratio is not None else None,
                "bandar": None if not ad else {"label": ad["label"], "sinyal": ad["sinyal"]},
                "pattern": pattern_name,
                "pattern_bias": pattern_bias,
                "macd_bullish_cross": macd_bullish_cross,
            })
        except Exception:
            continue

    _cache_set("confidence:raw", items)
    return items


def _confidence_weights() -> tuple[dict, str]:
    """Bobot gabungan untuk Skor Keyakinan (AI Score + Minervini +
    Confluence + Likuiditas + Risk/Reward). Versi web memakai bobot tetap
    (tanpa personalisasi per-akun)."""
    return dict(_CONFIDENCE_DEFAULT_WEIGHTS), "default"


@app.get("/api/confidence")
async def confidence():
    """Skor Keyakinan (Top Pick): gabungan AI Score + Minervini +
    Confluence + Likuiditas + Risk/Reward teknikal dalam satu peringkat
    atas universe likuid (bobot tetap). Saham 'Tidak Likuid'/'Kurang
    Likuid' skornya DIBATASI (bukan disembunyikan) supaya tidak nangkring
    di posisi teratas meski chart-nya kebetulan menarik -- tetap tampil
    dengan warning eksplisit. Menyertakan konteks regime IHSG supaya
    sinyal individual tidak dibaca lepas dari kondisi pasar."""
    try:
        raw_items = await _confidence_raw_signals()
    except Exception:
        raise HTTPException(502, "Gagal menghitung Skor Keyakinan.")

    weights, weight_source = _confidence_weights()

    items = []
    for it in raw_items:
        cf_norm = _confluence_norm(it["confluence_bullish"], it["confluence_bearish"])
        liq_sc = _liquidity_score(it["likuiditas"])
        rr_sc = _rr_score(it.get("rr_ratio"))
        score = (it["ai_score"] * weights["ai"] + it["minervini_score"] * weights["mv"]
                 + cf_norm * weights["cf"] + liq_sc * weights["liq"] + rr_sc * weights["rr"])
        score, capped = _apply_liquidity_cap(score, it["likuiditas"])
        reasons, warnings = _confidence_reasons(it)
        items.append({
            **it, "confluence_norm": cf_norm, "confidence_score": round(score, 1),
            "liquidity_capped": capped, "reasons": reasons, "warnings": warnings,
        })

    items.sort(key=lambda x: x["confidence_score"], reverse=True)

    # Catat Top Pick hari ini ke signal_history untuk Audit Sinyal (/api/
    # signals) -- SEBELUM user tahu hasilnya, supaya track record kredibel
    # (lihat catatan lengkap di core/signal_history.py). Dibungkus try/except
    # supaya kegagalan/lambatnya SQLite atau lookup harga real-time TIDAK
    # PERNAH menggagalkan respons Top Pick itu sendiri. Notifikasi Telegram
    # (kalau dikonfigurasi -- lihat core/telegram_notify.py, no-op aman
    # kalau tidak) dikirim utk tiap sinyal yang BENAR-BENAR baru dicatat
    # (bukan yang di-skip krn dedup harian).
    try:
        from core.signal_history import record_top_picks
        from core.telegram_notify import send_message, format_signal_new

        newly_recorded = await record_top_picks(items, price_lookup=_signal_entry_price_lookup)
        for sig in newly_recorded:
            try:
                await send_message(format_signal_new(sig))
            except Exception as e:
                print(f"⚠️ Gagal kirim notifikasi sinyal baru: {type(e).__name__}: {e}")
    except Exception as e:
        print(f"⚠️ Gagal mencatat signal history (Top Pick): {type(e).__name__}: {e}")

    # Entry point kedua yang independen: MACD Histogram Cross (permintaan
    # eksplisit user -- lihat core/signal_history.py::record_macd_cross_
    # signals). Dibungkus try/except TERPISAH dari Top Pick di atas supaya
    # kegagalan salah satu tidak pernah menggagalkan yang lain maupun
    # respons Top Pick itu sendiri.
    try:
        from core.signal_history import record_macd_cross_signals
        from core.telegram_notify import send_message, format_signal_new

        newly_macd = await record_macd_cross_signals(items, price_lookup=_signal_entry_price_lookup)
        for sig in newly_macd:
            try:
                await send_message(format_signal_new(sig))
            except Exception as e:
                print(f"⚠️ Gagal kirim notifikasi sinyal MACD Cross: {type(e).__name__}: {e}")
    except Exception as e:
        print(f"⚠️ Gagal mencatat signal history (MACD Cross): {type(e).__name__}: {e}")

    # Konteks regime pasar (IHSG) -- satu kali untuk semua, BUKAN per saham,
    # supaya user tahu skor individual di atas dibaca dalam kondisi pasar
    # apa (skor bagus di tengah IHSG bearish beda maknanya dari saat bullish).
    market_regime, market_regime_score = None, None
    try:
        ihsg_df = await _clean("^JKSE", period="1y")
        ai_ihsg = calculate_ai_score_from_df(ihsg_df) if ihsg_df is not None and len(ihsg_df) >= 50 else None
        if ai_ihsg:
            market_regime_score = ai_ihsg["score"]
            market_regime = ("BULLISH" if market_regime_score >= 60
                              else "BEARISH" if market_regime_score < 40 else "SIDEWAYS/NETRAL")
    except Exception:
        pass

    return _py({
        "items": items,
        "weights": weights,
        "weight_source": weight_source,
        "universe": len(SCREENER_UNIVERSE),
        "market_regime": market_regime,
        "market_regime_score": market_regime_score,
        "computed_at": int(time.time()),
    })


@app.get("/api/signals")
async def signals():
    """Audit Sinyal: daftar sinyal Top Pick yang pernah dicatat otomatis
    (lihat core/signal_history.py) + statistik win rate/return, HANYA dari
    sinyal yang sudah selesai (TP/SL tercapai atau kadaluarsa). Kalau belum
    ada satupun sinyal yang selesai, 'stats' bernilai None -- frontend WAJIB
    menampilkan ini sebagai "belum cukup data", BUKAN mengarang angka.

    Audit juga jalan otomatis via background task berkala (lihat
    _signal_auto_loop) -- pemanggilan endpoint ini TIDAK LAGI satu-satunya
    pemicu audit, cuma memastikan data terbaru saat halaman dibuka."""
    from core.signal_history import get_signal_report

    try:
        await _run_signal_audit_and_notify()
    except Exception as e:
        print(f"⚠️ Gagal audit signal history: {type(e).__name__}: {e}")

    report = await asyncio.to_thread(get_signal_report)
    return _py(report)


@app.post("/api/backtest")
async def api_backtest(request: Request):
    """Backtest kondisi sinyal terhadap histori 2 tahun universe likuid.
    Body JSON: {conditions: {...}, holding_days: int}"""
    body = await request.json()
    conditions: dict = body.get("conditions", {})
    holding_days = max(1, min(60, int(body.get("holding_days", 10))))

    if not conditions:
        raise HTTPException(400, "Pilih minimal satu kondisi.")

    from core.backtest import _find_signals_for_stock, aggregate_backtest
    from core.async_yf import async_download_many

    tickers_jk = [t + ".JK" for t in SCREENER_UNIVERSE]
    try:
        data = await async_download_many(tickers_jk, period="2y", interval="1d")
    except Exception:
        raise HTTPException(502, "Gagal mengambil data historis.")

    def _process(kode: str):
        df = data.get(kode + ".JK")
        return _find_signals_for_stock(kode, df, conditions, holding_days)

    results = await asyncio.gather(*[
        asyncio.to_thread(_process, kode) for kode in SCREENER_UNIVERSE
    ])

    all_trades = [t for sub in results for t in sub]
    result = aggregate_backtest(all_trades, len(SCREENER_UNIVERSE), holding_days)
    return _py(result)


@app.get("/api/universe")
async def universe(scope: str = "core"):
    """Pindai universe, hitung metrik per saham (untuk screener multi-filter
    & heatmap). Berat -> di-cache. scope='core' = ±45 likuid (cepat, default,
    dipakai Beranda/Heatmap/Sektor). scope='medium' = ~200 saham likuid.
    scope='all' = SELURUH emiten IDX dari saham.xlsx (793, lambat ~1-2 menit)."""
    if scope == "all":
        scope = "all"
    elif scope == "medium":
        scope = "medium"
    else:
        scope = "core"
    cache_key = f"universe:{scope}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    from core.async_yf import async_download_many
    from core.stock_data import load_tickers
    shares = _load_shares()
    if scope == "all":
        tickers = load_tickers()  # sudah termasuk .JK & exclude Pemantauan Khusus
    elif scope == "medium":
        tickers = [t + ".JK" for t in LIQUID_250]
    else:
        tickers = [t + ".JK" for t in SCREENER_UNIVERSE]
    try:
        data = await async_download_many(tickers, period="6mo", interval="1d")
    except Exception:
        raise HTTPException(502, "Gagal memuat data universe. Coba lagi sebentar.")

    items = []
    for t in tickers:
        kode = t.replace(".JK", "")
        df = data.get(t) if isinstance(data, dict) else None
        if df is None:
            continue
        try:
            df = fix_yf_columns(df).apply(pd.to_numeric, errors="coerce").dropna()
        except Exception:
            continue
        if df is None or len(df) < 50:
            continue
        try:
            ai = calculate_ai_score_from_df(df)
            if ai is None:
                continue
            price = float(df["Close"].iloc[-1])
            prev = float(df["Close"].iloc[-2]) if len(df) > 1 else price
            change_1d = (price / prev - 1) * 100 if prev else 0.0

            def _pct(n):
                if len(df) > n:
                    base = float(df["Close"].iloc[-1 - n])
                    return (price / base - 1) * 100 if base else 0.0
                return 0.0
            change_5d = _pct(5)
            change_20d = _pct(20)
            fv = _vwap_fair_value(df)
            ma20 = ai.get("ma20") or price
            firing = bool(ai.get("macd_bullish") and price > ma20 and (ai.get("rsi") or 0) > 50)
            mcap = (shares.get(kode, 0) * price) or None
            avg_val = float((df["Close"] * df["Volume"]).tail(20).mean())
            last_vol = float(df["Volume"].iloc[-1])
            items.append({
                "kode": kode, "sector": SECTOR_MAP_UNIVERSE.get(kode, "Lainnya"),
                "grup": GRUP_KONGLOMERASI.get(kode, "Independen"),
                "price": round(price), "change_1d": round(change_1d, 2),
                "score": ai.get("score"), "rating": ai.get("rating"),
                "rsi": ai.get("rsi"), "macd_bullish": ai.get("macd_bullish"),
                "vwap_label": (fv or {}).get("label"), "vwap_dev": (fv or {}).get("dev_pct"),
                "firing": firing, "market_cap": mcap, "avg_value": avg_val,
                "volume": last_vol, "value": price * last_vol,
                "change_5d": round(change_5d, 2), "change_20d": round(change_20d, 2),
            })
        except Exception:
            continue

    payload = {"items": items, "count": len(items), "scope": scope,
               "scanned": len(tickers),
               "as_of": (items and __import__("datetime").date.today().isoformat()) or None}
    payload = _py(payload)
    _cache_set(cache_key, payload)
    return payload


@app.get("/api/screener")
async def screener():
    """Screener breakout bullish (MA5>MA20 + lonjakan volume + likuid),
    memakai run_screener() yang SAMA dengan bot. Hasil di-cache (mahal)."""
    cached = _cache_get("screener")
    if cached is not None:
        return cached
    from core.screener import run_screener
    try:
        res = await run_screener([t + ".JK" for t in SCREENER_UNIVERSE])
    except Exception:
        raise HTTPException(502, "Gagal menjalankan screener. Coba lagi sebentar.")
    payload = {"items": res or [], "universe": len(SCREENER_UNIVERSE)}
    _cache_set("screener", payload)
    return payload


@app.get("/api/smc_data/{kode}")
async def smc_data(kode: str):
    """Candle + deteksi SMC (BOS/CHoCH, Order Block, FVG, Liquidity) dalam
    JSON, untuk dioverlay ke chart interaktif (menggantikan PNG statis)."""
    ticker = _resolve_ticker(kode)
    label = "IHSG" if ticker == "^JKSE" else _norm_kode(kode)
    try:
        df = await _clean(ticker)
    except Exception:
        raise HTTPException(502, "Gagal mengambil data harga.")
    if df is None or len(df) < 50:
        raise HTTPException(404, "Data tidak cukup.")

    win = df.tail(220).copy()
    ma20 = win["Close"].rolling(20).mean()
    candles, m20 = [], []
    for i in range(len(win)):
        t = win.index[i].strftime("%Y-%m-%d")
        candles.append({"time": t, "open": float(win["Open"].iloc[i]), "high": float(win["High"].iloc[i]),
                        "low": float(win["Low"].iloc[i]), "close": float(win["Close"].iloc[i])})
        if not pd.isna(ma20.iloc[i]):
            m20.append({"time": t, "value": round(float(ma20.iloc[i]), 2)})

    first_t = win.index[0]

    def dstr(idx):
        try:
            ts = df.index[idx]
            return ts.strftime("%Y-%m-%d") if ts >= first_t else None
        except Exception:
            return None

    def dt(x):
        v = x.get("date")
        try:
            return v.strftime("%Y-%m-%d") if hasattr(v, "strftime") and v >= first_t else None
        except Exception:
            return None

    try:
        bos = [{"time": dt(x), "type": x["type"], "direction": x["direction"],
                "price": x["price"], "broken": x.get("broken_level")}
               for x in detect_bos_choch(df, 5, 5)]
        bos = [b for b in bos if b["time"]]
    except Exception:
        bos = []
    try:
        obs = [{"time": dstr(x["ob_index"]), "type": x["type"], "low": x["zone_low"],
                "high": x["zone_high"], "fresh": x["is_fresh"]} for x in detect_order_blocks(df)]
        obs = [o for o in obs if o["time"]]
    except Exception:
        obs = []
    try:
        fvgs = [{"type": x["type"], "low": x["zone_low"], "high": x["zone_high"], "filled": x["filled"]}
                for x in detect_fvg(df) if not x.get("filled")]
    except Exception:
        fvgs = []
    try:
        liqs = [{"type": x["type"], "price": x["price_level"], "swept": x["swept"]}
                for x in detect_liquidity_pools(df)]
    except Exception:
        liqs = []

    return _py({"kode": label, "candles": candles, "ma20": m20,
                "bos": bos, "ob": obs, "fvg": fvgs, "liq": liqs})


@app.get("/api/bsjp")
async def bsjp(scope: str = "core"):
    """Screener BSJP (Beli Sore Jual Pagi).
    scope=core → ~45 cepat. scope=medium → ~200 likuid. scope=all → seluruh IDX (lambat)."""
    if scope == "all":
        scope = "all"
    elif scope == "medium":
        scope = "medium"
    else:
        scope = "core"
    cache_key = f"bsjp:{scope}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    from core.screener import run_bsjp_screener
    from core.stock_data import load_tickers
    if scope == "all":
        tickers = load_tickers()
    elif scope == "medium":
        tickers = [t + ".JK" for t in LIQUID_250]
    else:
        tickers = [t + ".JK" for t in SCREENER_UNIVERSE]
    try:
        res = await run_bsjp_screener(tickers)
    except Exception:
        raise HTTPException(502, "Gagal menjalankan screener BSJP.")
    payload = _py({"items": res or [], "scope": scope, "universe": len(tickers)})
    _cache_set(cache_key, payload)
    return payload


@app.get("/api/filter")
async def filter_(mode: str = "bullish"):
    """Filter cepat: bullish | breakout | volume | reversal (sama dengan
    /filter di bot). Di-cache per mode."""
    mode = (mode or "bullish").lower()
    if mode not in {"bullish", "breakout", "volume", "reversal"}:
        raise HTTPException(400, "mode harus: bullish, breakout, volume, atau reversal")
    cached = _cache_get(f"filter:{mode}")
    if cached is not None:
        return cached
    from core.market import run_filter
    try:
        res = await run_filter([t + ".JK" for t in SCREENER_UNIVERSE], mode)
    except Exception:
        raise HTTPException(502, "Gagal menjalankan filter.")
    payload = _py({"mode": mode, "items": res or []})
    _cache_set(f"filter:{mode}", payload)
    return payload


# ---------- risk management ----------
@app.get("/api/rr")
async def rr(entry: float, sl: float, tp: float):
    res = calculate_risk_reward(entry, sl, tp)
    if not res:
        raise HTTPException(422, "Input tidak valid (pastikan entry, SL, TP berbeda dan masuk akal).")
    return _py(res)


@app.get("/api/positionsize")
async def positionsize(modal: float, risk: float, entry: float, sl: float):
    res = calculate_position_size(modal, risk, entry, sl)
    if not res:
        raise HTTPException(422, "Input tidak valid (cek modal, risiko%, entry, dan stop loss).")
    return _py(res)


@app.get("/api/target/{kode}")
async def target(kode: str):
    ticker = _resolve_ticker(kode)
    try:
        df = await _clean(ticker)
    except Exception:
        raise HTTPException(502, "Gagal mengambil data harga.")
    if df is None or len(df) < 50:
        raise HTTPException(404, "Data tidak cukup.")
    return _py(calculate_target_levels(df))


@app.get("/api/cutloss/{kode}")
async def cutloss(kode: str):
    ticker = _resolve_ticker(kode)
    try:
        df = await _clean(ticker)
    except Exception:
        raise HTTPException(502, "Gagal mengambil data harga.")
    if df is None or len(df) < 50:
        raise HTTPException(404, "Data tidak cukup.")
    return _py(calculate_cutloss_levels(df))


@app.get("/api/averagedown/{kode}")
async def averagedown(kode: str, avg_price: float, lots: int, add_lots: int = 0):
    """Kalkulator Average Down: harga rata-rata baru + P/L kalau nambah
    lot di harga sekarang. Konteks fundamental (undervalued/overvalued,
    reuse _valuation() yang sama dipakai /api/fundamental) ditambahkan
    best-effort -- kalau fetch fundamental gagal/data tidak cukup,
    kalkulasi murninya tetap dikembalikan tanpa konteks itu.

    'suggestions': permintaan eksplisit user -- BUKAN rekomendasi "harus
    beli di sini" (tetap bukan financial advisor), tapi referensi DESKRIPTIF
    berupa level harga yang SUDAH biasa dipakai analisis teknikal/fundamental
    (support pivot terdekat, batas bawah estimasi wajar) plus hasil kalkulasi
    akurat di level itu -- keputusan & angka lot tetap sepenuhnya di user."""
    ticker = _resolve_ticker(kode)
    try:
        df = await _clean(ticker)
    except Exception:
        raise HTTPException(502, "Gagal mengambil data harga.")
    if df is None or len(df) < 5:
        raise HTTPException(404, "Data tidak cukup.")
    current_price = float(df["Close"].iloc[-1])

    res = calculate_average_down(avg_price, lots, current_price, add_lots)
    if not res:
        raise HTTPException(422, "Input tidak valid (cek harga rata-rata, lot dipegang, dan tambahan lot).")

    suggestions = []

    try:
        from core.indicators import calculate_support_resistance_deep
        sr = calculate_support_resistance_deep(df)
        for key, label in (("S1", "Support Terdekat (S1)"), ("S2", "Support Lebih Dalam (S2)")):
            level = sr.get(key)
            if level and 0 < level < current_price:
                calc = calculate_average_down(avg_price, lots, level, add_lots)
                if calc:
                    suggestions.append({"label": label, "price": level, **calc})
    except Exception:
        pass

    try:
        from core.fundamental import fetch_fundamental
        fund = await fetch_fundamental(ticker)
        if fund:
            val = _valuation(fund)
            if val.get("mid"):
                res["fair_value_mid"] = val["mid"]
                res["fair_value_verdict"] = val.get("verdict")
            floor = val.get("range_low")
            if floor and 0 < floor < current_price:
                calc = calculate_average_down(avg_price, lots, floor, add_lots)
                if calc:
                    suggestions.append({"label": "Estimasi Wajar Terendah (Floor)", "price": floor, **calc})
    except Exception:
        pass

    suggestions.sort(key=lambda s: s["price"], reverse=True)
    res["suggestions"] = suggestions

    return _py(res)


# ---------- sektor & relative strength ----------
@app.get("/api/sektor")
async def sektor():
    """Kekuatan sektor dari rata-rata saham konstituen likuid (Yahoo tidak
    menyediakan indeks sektoral IDX, jadi diturunkan dari konstituen)."""
    data = await universe()
    items = data.get("items", [])
    by = {}
    for it in items:
        by.setdefault(it["sector"], []).append(it)
    out = []
    for sec, arr in by.items():
        if sec == "Lainnya" or not arr:
            continue
        avg5 = sum(x.get("change_5d", 0) for x in arr) / len(arr)
        out.append({"nama_sektor": sec, "return_pct": round(avg5, 2), "n_saham": len(arr)})
    out.sort(key=lambda x: -x["return_pct"])
    return _py({"items": out, "basis": "rata-rata saham likuid per sektor (5 hari)"})


@app.get("/api/rotasi")
async def rotasi():
    """Rotasi sektor: momentum pendek (5h) vs panjang (20h) dari konstituen."""
    data = await universe()
    items = data.get("items", [])
    by = {}
    for it in items:
        by.setdefault(it["sector"], []).append(it)
    out = []
    for sec, arr in by.items():
        if sec == "Lainnya" or not arr:
            continue
        rs = sum(x.get("change_5d", 0) for x in arr) / len(arr)
        rl = sum(x.get("change_20d", 0) for x in arr) / len(arr)
        shift = rs - rl
        if rs > 0 and rl > 0:
            fase = "Leading 🟢" if shift >= 0 else "Weakening 🟡"
        elif rs > 0 >= rl:
            fase = "Improving 🔵"
        elif rs <= 0 and rl <= 0:
            fase = "Bottoming 🟠" if shift >= 0 else "Lagging 🔴"
        else:
            fase = "Weakening 🟡"
        out.append({"nama_sektor": sec, "return_short": round(rs, 2),
                    "return_long": round(rl, 2), "momentum_shift": round(shift, 2), "fase": fase})
    out.sort(key=lambda x: -x["momentum_shift"])
    return _py({"items": out})


@app.get("/api/rs/{kode}")
async def rs(kode: str):
    """Relative strength saham vs IHSG (20 hari)."""
    kode = _norm_kode(kode)
    try:
        sdf = await _clean(kode + ".JK")
        idf = await _clean("^JKSE")
    except Exception:
        raise HTTPException(502, "Gagal mengambil data harga.")
    if sdf is None or len(sdf) < 30 or idf is None or len(idf) < 30:
        raise HTTPException(404, "Data tidak cukup.")
    res = calculate_relative_strength(sdf, idf, period_days=20)
    if not res:
        raise HTTPException(422, "Gagal menghitung relative strength.")
    return _py(res)


@app.get("/api/beta/{kode}")
async def beta(kode: str):
    """Koefisien beta saham vs IHSG."""
    kode = _norm_kode(kode)
    try:
        sdf = await _clean(kode + ".JK")
        idf = await _clean("^JKSE")
    except Exception:
        raise HTTPException(502, "Gagal mengambil data harga.")
    if sdf is None or len(sdf) < 30 or idf is None or len(idf) < 30:
        raise HTTPException(404, "Data tidak cukup.")
    res = calculate_beta(sdf, idf)
    if not res:
        raise HTTPException(422, "Gagal menghitung beta.")
    return _py(res)


# ---------- analisis lanjutan ----------
@app.get("/api/confluence/{kode}")
async def confluence(kode: str):
    from core.screening_pro import calculate_confluence
    kode = _norm_kode(kode)
    try:
        df = await _clean(kode + ".JK")
    except Exception:
        raise HTTPException(502, "Gagal mengambil data harga.")
    if df is None or len(df) < 50:
        raise HTTPException(404, "Data tidak cukup.")
    res = calculate_confluence(df, kode)
    if not res:
        raise HTTPException(422, "Gagal menghitung confluence.")
    return _py(res)


@app.get("/api/patternscan/{kode}")
async def patternscan(kode: str):
    from core.screening_pro import detect_patterns
    kode = _norm_kode(kode)
    try:
        df = await _clean(kode + ".JK")
    except Exception:
        raise HTTPException(502, "Gagal mengambil data harga.")
    if df is None or len(df) < 50:
        raise HTTPException(404, "Data tidak cukup.")
    return _py(detect_patterns(df, kode))


@app.get("/api/backtestpro/{kode}")
async def backtestpro(kode: str, mode: str = "momentum"):
    from core.screening_pro import run_backtestpro
    kode = _norm_kode(kode)
    try:
        df = await _clean(kode + ".JK", period="2y")
    except Exception:
        raise HTTPException(502, "Gagal mengambil data harga.")
    if df is None or len(df) < 120:
        raise HTTPException(404, "Data tidak cukup untuk walk-forward (butuh histori panjang).")
    res = run_backtestpro(df, kode, mode)
    if not res:
        raise HTTPException(422, "Gagal menjalankan backtest pro.")
    return _py(res)


@app.get("/api/multitimeframe/{kode}")
async def multitimeframe(kode: str):
    from core.screening_pro import analyze_multitimeframe
    kode = _norm_kode(kode)
    cache_key = f"multitimeframe:{kode}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    try:
        res = await analyze_multitimeframe(kode)  # fungsi menambahkan .JK sendiri -> kirim kode mentah
    except Exception:
        raise HTTPException(502, "Gagal menganalisis multi-timeframe.")
    if not res:
        raise HTTPException(422, "Data multi-timeframe tidak cukup.")
    payload = _py(res)
    _cache_set(cache_key, payload)
    return payload


@app.get("/api/correlation")
async def correlation(a: str, b: str = "IHSG"):
    from core.screening_pro import calculate_correlation
    # calculate_correlation menambahkan .JK sendiri & menangani IHSG -> kirim kode mentah
    ra = _norm_kode(a)
    rb = "IHSG" if b.strip().upper() in _IHSG_ALIASES else _norm_kode(b)
    try:
        res = await calculate_correlation(ra, rb)
    except Exception:
        raise HTTPException(502, "Gagal menghitung korelasi.")
    if not res:
        raise HTTPException(422, "Data korelasi tidak cukup.")
    return _py(res)


# ---------- trading plan & support/resistance ----------
@app.get("/api/plan/{kode}")
async def plan(kode: str):
    from core.trading_plan import calculate_advanced_plan_from_df
    kode = _norm_kode(kode)
    try:
        df = await _clean(kode + ".JK")
    except Exception:
        raise HTTPException(502, "Gagal mengambil data harga.")
    if df is None or len(df) < 50:
        raise HTTPException(404, "Data tidak cukup.")
    res = calculate_advanced_plan_from_df(df, kode)
    if not res:
        raise HTTPException(422, "Gagal menyusun rencana trading.")
    return _py(res)


@app.get("/api/snr/{kode}")
async def snr(kode: str):
    from core.indicators import calculate_support_resistance_deep
    ticker = _resolve_ticker(kode)
    try:
        df = await _clean(ticker)
    except Exception:
        raise HTTPException(502, "Gagal mengambil data harga.")
    if df is None or len(df) < 50:
        raise HTTPException(404, "Data tidak cukup.")
    sr = calculate_support_resistance_deep(df)
    if not sr:
        raise HTTPException(422, "Gagal menghitung support/resistance.")
    sr = dict(sr)
    sr["current_price"] = round(float(df["Close"].iloc[-1]), 2)
    return _py(sr)


def _valuation(fund: dict) -> dict:
    """Estimasi harga wajar dari beberapa metode valuasi. Setiap metode punya
    asumsi berbeda — TIDAK ada yang definitif. Gunakan sebagai rentang referensi."""
    eps = fund.get("eps_trailing")
    eps_fwd = fund.get("eps_forward")
    bvps = fund.get("book_value_per_share")
    price = fund.get("harga_sekarang")
    pe_trailing = fund.get("pe_trailing")
    roe = fund.get("roe_pct")
    growth_e = fund.get("earnings_growth_pct")   # % mis. 12.5
    growth_r = fund.get("revenue_growth_pct")
    div_yield = fund.get("dividend_yield_pct")    # % mis. 3.5
    payout = fund.get("payout_ratio_pct")         # %
    net_margin = fund.get("net_margin_pct")
    methods, ests, methods_meta = {}, [], {}

    def _add(key, val, label, note):
        if val and val > 0:
            methods[key] = round(val, 2)
            methods_meta[key] = {"label": label, "note": note}
            ests.append(val)

    # --- ABSOLUTE METHODS ---
    # 1. Graham Number (value/defensif — sering conservative untuk growth)
    if eps and bvps and eps > 0 and bvps > 0:
        g_val = (22.5 * eps * bvps) ** 0.5
        _add("graham", g_val, "Graham Number",
             "√(22.5 × EPS × BVPS) — konservatif, cocok saham value/defensif, meremehkan growth")

    # 2. PER × 15 (acuan umum pasar berkembang)
    if eps and eps > 0:
        _add("per_x15", eps * 15, "PER × 15",
             "EPS trailing × 15 — asumsi PE wajar 15× untuk saham mature")

    # 3. PBV × 2
    if bvps and bvps > 0:
        _add("pbv_x2", bvps * 2, "PBV × 2",
             "Book value per saham × 2 — P/B wajar 2× untuk sektor non-keuangan")

    # 4. DCF Sederhana (1-stage, g=growth pendapatan atau 7%, r=12%)
    if eps_fwd and eps_fwd > 0:
        g_dcf = min((growth_e or growth_r or 7.0) / 100, 0.25)  # cap 25%
        r_dcf = 0.12  # discount rate IDX tipikal (risk premium + rf)
        if r_dcf > g_dcf:
            # Gordon Growth / No-growth terminal: sum 5 tahun + terminal
            pv = sum(eps_fwd * ((1 + g_dcf) ** t) / ((1 + r_dcf) ** t) for t in range(1, 6))
            tv = (eps_fwd * (1 + g_dcf) ** 5 * (1 + g_dcf * 0.4)) / ((r_dcf - g_dcf * 0.4) * (1 + r_dcf) ** 5)
            _add("dcf_simple", pv + tv, "DCF 5-Tahun",
                 f"Discounted EPS forward, g={round(g_dcf*100,1)}%, r=12% — sensitif terhadap asumsi growth")

    # 5. PEG-implied (Lynch: PE wajar = growth rate EPS)
    if eps and eps > 0 and growth_e and growth_e > 0:
        peg_pe_fair = min(growth_e, 30)  # cap PE 30× walau growth tinggi
        _add("peg_implied", eps * peg_pe_fair, "PEG Implied (Lynch)",
             f"EPS × {peg_pe_fair:.0f} (growth={growth_e:.1f}%) — PE wajar = growth rate, cocok saham growth")

    # 6. DDM Gordon Growth (hanya jika dividen ada & payout masuk akal)
    if div_yield and div_yield > 0 and price and price > 0:
        div_per_share = price * div_yield / 100
        g_div = min((growth_r or growth_e or 4.0) / 100, 0.10)
        r_div = 0.12
        if r_div > g_div and div_per_share > 0:
            ddm = div_per_share * (1 + g_div) / (r_div - g_div)
            _add("ddm", ddm, "Gordon Growth Model",
                 f"D₁/(r-g) — Div/lembar Rp{div_per_share:.0f}, g={g_div*100:.0f}%, r=12%. Hanya valid untuk saham dengan dividen stabil")

    # 7. ROE-implied Intrinsic Value (Buffett-style: P = BV × ROE / r)
    if roe and roe > 0 and bvps and bvps > 0:
        buffett_val = bvps * (roe / 100) / 0.12
        _add("roe_implied", buffett_val, "ROE / r (Buffett-style)",
             f"BVPS × ROE/r — Rp{bvps:.0f} × {roe:.1f}% / 12%. Saham bagus yang hasilkan ROE tinggi wajar dihargai premium")

    # Rangkum
    out = {"methods": methods, "methods_meta": methods_meta, "eps": eps, "bvps": bvps, "price": price}

    # Hitung PEG ratio aktual
    if pe_trailing and pe_trailing > 0 and growth_e and growth_e > 0:
        out["peg_actual"] = round(pe_trailing / growth_e, 2)

    if ests and price:
        lo, hi, mid = min(ests), max(ests), sum(ests) / len(ests)
        out.update({
            "range_low": round(lo, 2), "range_high": round(hi, 2), "mid": round(mid, 2),
            "upside_pct": round((mid / price - 1) * 100, 1),
            "verdict": "Undervalued" if price < lo * 0.9
                       else "Overvalued" if price > hi * 1.1
                       else "Wajar (dalam rentang)",
        })
    return out


@app.get("/api/fundamental/{kode}")
async def fundamental(kode: str):
    """Data fundamental (PE, PBV, ROE, DER, dividend, EPS) + estimasi harga
    wajar. Data dari yfinance .info (bisa tidak lengkap untuk saham IDX)."""
    from core.fundamental import fetch_fundamental
    kode = _norm_kode(kode)
    cache_key = f"fund:{kode}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    try:
        f = await fetch_fundamental(kode + ".JK")
    except Exception:
        raise HTTPException(502, "Gagal mengambil data fundamental.")
    if not f:
        raise HTTPException(404, "Data fundamental tidak tersedia untuk saham ini.")
    f = dict(f)
    f["valuasi"] = _valuation(f)
    payload = _py(f)
    _cache_set(cache_key, payload)
    return payload


_MACRO_TICKERS = {
    # Kurs
    "USDIDR=X": {"label": "USD / IDR",    "cat": "kurs",      "unit": "IDR",       "icon": "🇺🇸"},
    "EURIDR=X": {"label": "EUR / IDR",    "cat": "kurs",      "unit": "IDR",       "icon": "🇪🇺"},
    "JPYIDR=X": {"label": "JPY / IDR",    "cat": "kurs",      "unit": "IDR",       "icon": "🇯🇵"},
    "CNHIDR=X": {"label": "CNY / IDR",    "cat": "kurs",      "unit": "IDR",       "icon": "🇨🇳"},
    # Energi & Logam — CME/COMEX, batch-compatible
    "GC=F":     {"label": "Emas",         "cat": "komoditas", "unit": "USD/oz",    "icon": "🥇"},
    "SI=F":     {"label": "Perak",        "cat": "komoditas", "unit": "USD/oz",    "icon": "🥈"},
    "HG=F":     {"label": "Tembaga",      "cat": "komoditas", "unit": "USD/lb",    "icon": "🟠"},
    "CL=F":     {"label": "Minyak WTI",   "cat": "komoditas", "unit": "USD/bbl",   "icon": "🛢"},
    "BZ=F":     {"label": "Minyak Brent", "cat": "komoditas", "unit": "USD/bbl",   "icon": "🛢"},
    "NG=F":     {"label": "Gas Alam",     "cat": "komoditas", "unit": "USD/MMBtu", "icon": "🔥"},
    # Nikel, CPO, Batu Bara — gunakan ETC London sebagai proxy (ICE/LME futures tidak tersedia di Yahoo)
    "NICL.L":   {"label": "Nikel",        "cat": "komoditas", "unit": "GBX/unit",  "icon": "⚙"},
    "PALM.L":   {"label": "CPO",          "cat": "komoditas", "unit": "GBX/unit",  "icon": "🌴"},
    # Agri & Bahan Pokok — ICE/CBOT (KC=F/CC=F diambil individual karena batch gagal)
    "KC=F":     {"label": "Kopi Arabika", "cat": "agri",      "unit": "¢/lb",      "icon": "☕", "individual": True},
    "SB=F":     {"label": "Gula",         "cat": "agri",      "unit": "¢/lb",      "icon": "🍬"},
    "CC=F":     {"label": "Kakao",        "cat": "agri",      "unit": "USD/t",     "icon": "🍫", "individual": True},
    "ZC=F":     {"label": "Jagung",       "cat": "agri",      "unit": "¢/bu",      "icon": "🌽"},
    "ZS=F":     {"label": "Kedelai",      "cat": "agri",      "unit": "¢/bu",      "icon": "🫘"},
    "ZW=F":     {"label": "Gandum",       "cat": "agri",      "unit": "¢/bu",      "icon": "🌾"},
    "ZR=F":     {"label": "Beras",        "cat": "agri",      "unit": "USD/cwt",   "icon": "🍚"},
    "ZL=F":     {"label": "Minyak Sawit", "cat": "agri",      "unit": "¢/lb",      "icon": "🌻"},
    # Pasar Global
    "^GSPC":    {"label": "S&P 500",      "cat": "global",    "unit": "pts",       "icon": "🇺🇸"},
    "^DJI":     {"label": "Dow Jones",    "cat": "global",    "unit": "pts",       "icon": "🏛"},
    "^IXIC":    {"label": "Nasdaq",       "cat": "global",    "unit": "pts",       "icon": "💻"},
    "^N225":    {"label": "Nikkei 225",   "cat": "global",    "unit": "pts",       "icon": "🇯🇵"},
    "^HSI":     {"label": "Hang Seng",    "cat": "global",    "unit": "pts",       "icon": "🇭🇰"},
}

_MACRO_SECTOR_IMPACT = {
    "GC=F":    {"naik": ["ANTM", "MDKA", "BRMS", "PSAB"],        "sektor": "Pertambangan Emas"},
    "SI=F":    {"naik": ["ANTM", "MDKA"],                         "sektor": "Pertambangan Perak"},
    "HG=F":    {"naik": ["ANTM", "MDKA", "BRMS"],                 "sektor": "Pertambangan Tembaga"},
    "CL=F":    {"naik": ["MEDC", "ELSA", "PGAS", "AKRA", "ADRO", "PTBA", "ITMG"],
                "turun": ["BRPT", "TPIA", "MYOR", "ICBP"],        "sektor": "Energi (Migas + Batu Bara) & Petrokimia"},
    "BZ=F":    {"naik": ["MEDC", "ELSA", "PGAS"],
                "turun": ["BRPT", "TPIA"],                         "sektor": "Minyak Brent / Petrokimia"},
    "NG=F":    {"naik": ["PGAS", "MEDC", "ELSA"],
                "turun": ["AGII", "INDF"],                         "sektor": "Gas Alam"},
    "NICL.L":  {"naik": ["ANTM", "INCO", "MDKA"],                 "sektor": "Nikel / Mineral (proxy ETC)"},
    "PALM.L":  {"naik": ["AALI", "SIMP", "LSIP", "TAPG"],        "sektor": "Perkebunan CPO (proxy ETC)"},
    "KC=F":    {"naik": ["MYOR", "DLTA", "AISA"],                 "sektor": "Kopi / Minuman"},
    "SB=F":    {"turun": ["MYOR", "ICBP", "ULTJ", "DLTA"],        "sektor": "Industri Makanan & Minuman (biaya gula naik)"},
    "CC=F":    {"turun": ["MYOR", "DLTA"],                         "sektor": "Industri Cokelat & Minuman"},
    "ZC=F":    {"turun": ["CPIN", "JPFA", "MAIN", "SIPD"],         "sektor": "Pakan Ternak (biaya jagung naik)"},
    "ZS=F":    {"turun": ["CPIN", "JPFA", "MAIN"],                 "sektor": "Pakan Ternak (biaya kedelai naik)"},
    "ZW=F":    {"turun": ["ICBP", "MYOR", "GOOD"],                 "sektor": "Industri Pangan (biaya gandum naik)"},
    "USDIDR=X":{"naik": ["ADRO", "ANTM", "TLKM"],
                "turun": ["UNVR", "ICBP", "MYOR", "KLBF"],        "sektor": "Eksportir vs Importir"},
}


@app.get("/api/macro")
async def macro():
    """Kurs, komoditas, dan indeks global — data live dari Yahoo Finance.
    Semua ticker di-fetch paralel via fast_info, cache 5 menit."""
    cached = _cache_get("macro:v2")
    if cached is not None:
        return cached

    def _fi_one(t: str) -> dict | None:
        """Ambil harga real-time via fast_info, fallback ke history(5d)."""
        try:
            fi = yf.Ticker(t).fast_info
            last = fi.last_price
            prev = fi.previous_close
            if last and float(last) > 0:
                price = float(last)
                p     = float(prev) if prev and float(prev) > 0 else price
                chg   = round((price / p - 1) * 100, 2) if p else 0.0
                return {"price": round(price, 4), "change_pct": chg}
        except Exception:
            pass
        # Fallback: ambil beberapa hari historis supaya selalu ada 2 baris
        try:
            hist   = yf.Ticker(t).history(period="5d")
            prices = hist["Close"].dropna()
            if len(prices) < 1:
                return None
            price = float(prices.iloc[-1])
            prev  = float(prices.iloc[-2]) if len(prices) >= 2 else price
            chg   = round((price / prev - 1) * 100, 2) if prev else 0.0
            return {"price": round(price, 4), "change_pct": chg}
        except Exception:
            return None

    # Jalankan semua fetch paralel di thread pool
    tasks = [asyncio.to_thread(_fi_one, t) for t in _MACRO_TICKERS]
    results_list = await asyncio.gather(*tasks)
    raw = dict(zip(_MACRO_TICKERS.keys(), results_list))

    items = {}
    for ticker, meta in _MACRO_TICKERS.items():
        d = raw.get(ticker)
        if not d:
            continue
        items[ticker] = {
            **meta,
            "price":      d["price"],
            "change_pct": d["change_pct"],
        }

    # Sector impact — ambil hanya ticker yang berhasil di-fetch
    impacts = {}
    for ticker, imp in _MACRO_SECTOR_IMPACT.items():
        if ticker in items:
            impacts[ticker] = {**imp, "price": items[ticker]["price"],
                               "change_pct": items[ticker]["change_pct"],
                               "label": _MACRO_TICKERS[ticker]["label"]}

    payload = _py({"items": items, "impacts": impacts, "cats": ["kurs", "komoditas", "agri", "global"]})
    _cache_set("macro:v2", payload)
    return payload


@app.get("/api/breadth")
async def breadth():
    """Market breadth (keluasan) dari saham likuid: advancers/decliners,
    % bullish, % momentum firing. Indikator KESEHATAN pasar — apakah
    pergerakan luas atau sempit — BUKAN prediksi arah."""
    data = await universe()
    items = data.get("items", [])
    if not items:
        raise HTTPException(502, "Data breadth belum tersedia.")
    n = len(items)
    adv = sum(1 for x in items if (x.get("change_1d") or 0) > 0)
    dec = sum(1 for x in items if (x.get("change_1d") or 0) < 0)
    bullish = sum(1 for x in items if (x.get("score") or 0) >= 60)
    firing = sum(1 for x in items if x.get("firing"))
    macd_bull = sum(1 for x in items if x.get("macd_bullish"))
    above_disc = sum(1 for x in items if "Discount" in (x.get("vwap_label") or ""))
    avg_change = sum((x.get("change_1d") or 0) for x in items) / n
    adv_pct = adv / n * 100
    if adv_pct >= 65:
        verdict = "Sangat luas (risk-on)"
    elif adv_pct >= 50:
        verdict = "Cenderung positif"
    elif adv_pct >= 35:
        verdict = "Cenderung negatif"
    else:
        verdict = "Lemah (risk-off)"
    return _py({
        "n": n, "advancers": adv, "decliners": dec, "unchanged": n - adv - dec,
        "adv_pct": round(adv_pct, 1), "pct_bullish": round(bullish / n * 100, 1),
        "pct_firing": round(firing / n * 100, 1), "pct_macd_bullish": round(macd_bull / n * 100, 1),
        "pct_discount": round(above_disc / n * 100, 1), "avg_change": round(avg_change, 2),
        "verdict": verdict,
    })


_IHSG_NEWS_KW = (
    "ihsg", "bursa", "bei ", "idx composite", "indeks", "rupiah", "kurs", "dolar as",
    "the fed", "suku bunga", "inflasi", "bi rate", "bi-rate", "bank indonesia",
    "wall street", "dow jones", "nasdaq", "s&p 500", "bursa asia", "nikkei", "hang seng",
    "asing", "net buy", "net sell", "net foreign", "foreign", "outflow", "inflow",
    "obligasi", "yield", "sentimen pasar", "aliran modal", "ekonomi global", "makro",
    "saham gabungan", "pasar saham", "modal asing", "capital",
)


async def _market_news_pool(limit: int = 10):
    """Ambil pool berita lalu saring jadi berita pasar/makro (bukan satu emiten)."""
    items = await fetch_news(keyword=None, limit=40)
    if not items:
        return []

    def is_market(it):
        t = ((it.get("title") or "") + " " + (it.get("summary") or "")).lower()
        return any(k in t for k in _IHSG_NEWS_KW)

    return [it for it in items if is_market(it)][:limit]


@app.get("/api/ihsgnews")
async def ihsg_news():
    """Berita khusus pasar/IHSG (makro & indeks), bukan berita satu emiten."""
    items = await fetch_news(keyword=None, limit=40)
    if items is None:
        raise HTTPException(502, "Sumber berita tidak bisa diakses saat ini.")
    filtered = await _market_news_pool(10)
    out = [{"title": it.get("title"), "source": it.get("source"), "link": it.get("link")}
           for it in filtered]
    return {"items": out, "filtered": True}


@app.get("/api/insight/{kode}")
async def insight(kode: str):
    """Narasi insight: untuk saham (teknikal + konteks IHSG + RS + berita)
    atau IHSG market-wide (teknikal + rotasi sektor + berita). DESKRIPTIF +
    konteks probabilistik -- BUKAN ramalan arah (lihat catatan metodologi)."""
    from core.ai_score import calculate_ai_score_from_df
    from core.insight import generate_insight, generate_market_insight

    raw = kode.strip().upper()
    is_ihsg = raw in _IHSG_ALIASES

    try:
        idf = await _clean("^JKSE")
    except Exception:
        idf = None
    ai_ihsg = calculate_ai_score_from_df(idf) if (idf is not None and len(idf) >= 50) else None

    if is_ihsg:
        if ai_ihsg is None:
            raise HTTPException(404, "Data IHSG tidak cukup untuk insight.")
        try:
            sek = await sektor()
            sector_data = sek.get("items") or None
        except Exception:
            sector_data = None
        try:
            news_items = await _market_news_pool(10)
        except Exception:
            news_items = None
        # Insight IHSG sebelumnya CUMA pakai ai_ihsg (skor generik ala
        # saham) -- tidak pernah memakai analyze_ihsg_with_backtest() yang
        # punya validasi historis (edge vs baseline), level S/R, RSI
        # divergence, BB squeeze, pola candlestick, PADAHAL /api/ihsg
        # SUDAH menghitung semua itu. Panggil langsung handler /api/ihsg
        # (fungsi biasa, cache 300s-nya ikut kepakai) supaya tidak
        # menghitung ulang analyze_ihsg_with_backtest() dari nol di sini.
        try:
            ihsg_payload = await ihsg()
        except Exception:
            ihsg_payload = None
        ringkasan_ihsg = None
        if ihsg_payload:
            ringkasan_ihsg = {
                "bandar": ihsg_payload.get("bandar"),
                "potensi_naik_pct": ihsg_payload.get("potensi_naik_pct"),
                "risiko_turun_pct": ihsg_payload.get("risiko_turun_pct"),
            }
        res = await generate_market_insight(
            ai_ihsg, sector_data, news_items,
            ihsg_analysis=ihsg_payload, ringkasan=ringkasan_ihsg,
        )
        return _py(res)

    kode_n = _norm_kode(kode)
    try:
        sdf = await _clean(kode_n + ".JK")
    except Exception:
        raise HTTPException(502, "Gagal mengambil data harga.")
    if sdf is None or len(sdf) < 50:
        raise HTTPException(404, "Data tidak cukup.")
    ai_score = calculate_ai_score_from_df(sdf)
    rs_data = None
    if ai_ihsg is not None and idf is not None:
        try:
            rs_data = calculate_relative_strength(sdf, idf)
        except Exception:
            rs_data = None
    try:
        news_items = await fetch_news(keyword=kode_n, limit=8)
    except Exception:
        news_items = None
    try:
        ringkasan = _compute_ringkasan_cepat(sdf, ai_score)
    except Exception:
        ringkasan = None
    res = await generate_insight(kode_n, ai_score, ai_ihsg, rs_data, news_items, ringkasan=ringkasan)
    return _py(res)


@app.get("/api/tickers")
async def tickers():
    """Daftar lengkap emiten IDX (kode + nama) untuk autocomplete pencarian."""
    d = _load_ticker_directory()
    return {"items": d, "count": len(d)}


@app.get("/api/normchart")
async def normchart(kodes: str = "", window: int = 60):
    """Return ternormalisasi (% return dari harga awal window) untuk N saham
    + IHSG sebagai benchmark. Cocok untuk chart interaktif multi-garis di
    frontend (bukan PNG -- JSON supaya bisa dirender lightweight-charts).

    Contoh: /api/normchart?kodes=BBCA,BMRI,TLKM&window=60
    Maks 8 saham per request (lebih dari itu chart tidak terbaca)."""
    lst = [_norm_kode(k) for k in (kodes or "").split(",") if k.strip()][:8]
    if not lst:
        raise HTTPException(400, "Sertakan minimal 1 kode, mis. ?kodes=BBCA,BMRI")
    window = max(20, min(window, 250))

    tickers = [k + ".JK" for k in lst] + ["^JKSE"]
    try:
        from core.async_yf import async_download_many
        raw = await async_download_many(tickers, period="1y", interval="1d")
    except Exception:
        raise HTTPException(502, "Gagal mengambil data harga. Coba lagi sebentar.")

    series = []

    def _norm_series(df, label, is_benchmark=False):
        """Kembalikan [{time, value}] ternormalisasi dari window terakhir."""
        try:
            df = fix_yf_columns(df).apply(pd.to_numeric, errors="coerce").dropna()
            if len(df) < 5:
                return None
            w = min(len(df), window)
            d = df.tail(w)
            base = float(d["Close"].iloc[0])
            if base == 0:
                return None
            points = []
            for i in range(len(d)):
                t = d.index[i].strftime("%Y-%m-%d")
                val = round((float(d["Close"].iloc[i]) / base - 1) * 100, 3)
                points.append({"time": t, "value": val})
            return {"label": label, "data": points, "benchmark": is_benchmark,
                    "final": points[-1]["value"] if points else None}
        except Exception:
            return None

    # IHSG sebagai benchmark abu-abu
    ihsg_df = raw.get("^JKSE")
    if ihsg_df is not None and not ihsg_df.empty:
        s = _norm_series(ihsg_df, "IHSG", is_benchmark=True)
        if s:
            series.append(s)

    # Saham yang diminta
    missing = []
    for k in lst:
        df = raw.get(k + ".JK")
        if df is None or df.empty:
            missing.append(k)
            continue
        s = _norm_series(df, k)
        if s:
            series.append(s)
        else:
            missing.append(k)

    if not any(not s["benchmark"] for s in series):
        raise HTTPException(404, "Tidak ada data yang cukup untuk saham yang diminta.")

    return _py({
        "window": window,
        "series": series,
        "missing": missing,
        "note": "Return ternormalisasi dari harga awal window (%). IHSG = benchmark.",
    })


# ── SMART MONEY / VOLUME ANOMALI SCANNER ─────────────────────────────────
# Mendeteksi aktivitas institusional lewat anomali volume dan price action.
# Tidak bergantung BEI scraping — pakai yfinance yang sudah ada.

import numpy as _np

_SM_UNIVERSE = [
    "BBCA", "BBRI", "BMRI", "BBNI", "TLKM", "ASII", "UNVR", "ICBP", "INDF", "KLBF",
    "GGRM", "HMSP", "UNTR", "ADRO", "PTBA", "ITMG", "ANTM", "INCO", "MDKA", "TINS",
    "SMGR", "INTP", "CPIN", "JPFA", "AKRA", "EXCL", "ISAT", "TOWR", "TBIG",
    "ACES", "MAPI", "AMRT", "GOTO", "BUKA", "BRPT", "TPIA", "BRIS", "ARTO",
    "MEDC", "PGAS", "JSMR", "BRMS", "RAJA", "MNCN", "ERAA",
]


def _sm_classify(vol_ratio: float, chg5: float, chg1: float, rsi: float | None) -> str:
    """Klasifikasi pola institusional berdasarkan volume + price action."""
    high_vol = vol_ratio >= 1.8
    very_high = vol_ratio >= 2.5
    rising = chg5 > 1.5
    falling = chg5 < -1.5
    if very_high and rising:
        return "Akumulasi Agresif"
    if high_vol and rising:
        return "Akumulasi"
    if very_high and falling:
        return "Distribusi Agresif"
    if high_vol and falling:
        return "Distribusi"
    if not high_vol and rising and chg5 > 3:
        return "Siluman (quiet buy)"
    if chg5 > 5 and vol_ratio >= 1.3:
        return "Breakout Volume"
    return ""


def _process_sm_df(kode: str, df_tr) -> dict | None:
    """Proses DataFrame hari-trading untuk deteksi anomali volume SM."""
    try:
        close = df_tr["Close"]
        volume = df_tr["Volume"]
        if len(close) < 6 or len(volume) < 10:
            return None

        vol_baseline = float(volume.iloc[:-1].mean()) if len(volume) > 1 else float(volume.mean())
        min_threshold = vol_baseline * 0.10

        valid_idx = None
        for i in range(-1, -min(len(volume), 6), -1):
            if float(volume.iloc[i]) >= min_threshold:
                valid_idx = i
                break
        if valid_idx is None:
            return None

        end_vol = len(volume) + valid_idx
        vol_today = float(volume.iloc[valid_idx])
        vol_window = volume.iloc[max(0, end_vol - 21):end_vol]
        vol_avg20 = float(vol_window.mean()) if len(vol_window) >= 5 else vol_baseline
        vol_ratio = round(vol_today / vol_avg20, 2) if vol_avg20 > 0 else 1.0

        price = float(close.iloc[valid_idx])
        prev = float(close.iloc[valid_idx - 1]) if abs(valid_idx) < len(close) else price
        chg1 = round((price / prev - 1) * 100, 2) if prev else 0.0
        end_close = len(close) + valid_idx
        chg5 = round((price / float(close.iloc[max(0, end_close - 5)]) - 1) * 100, 2) if end_close >= 5 else 0.0

        delta = close.diff().dropna()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs_val = gain.iloc[-1] / loss.iloc[-1] if (loss.iloc[-1] != 0 and not _np.isnan(loss.iloc[-1])) else None
        rsi = round(100 - 100 / (1 + rs_val), 1) if rs_val is not None else None

        pattern = _sm_classify(vol_ratio, chg5, chg1, rsi)
        if not pattern:
            return None

        return {"kode": kode, "harga": int(price), "chg1": chg1, "chg5": chg5,
                "vol_ratio": vol_ratio, "rsi": rsi, "pola": pattern,
                "grup": GRUP_KONGLOMERASI.get(kode, "Independen")}
    except Exception:
        return None


async def _scan_one_sm(kode: str) -> dict | None:
    """Scan satu ticker untuk anomali volume."""
    try:
        df = await _clean(kode + ".JK", period="3mo", interval="1d")
        if df is None or len(df) < 15:
            return None
        df_tr = df[df["Volume"] > 0].dropna(subset=["Close", "Volume"])
        return _process_sm_df(kode, df_tr)
    except Exception:
        return None


def _build_sm_payload(items: list, total: int, scope: str) -> dict:
    akumulasi = sorted(
        [x for x in items if any(p in x["pola"] for p in ("Akumulasi", "Breakout", "Siluman"))],
        key=lambda x: x["vol_ratio"], reverse=True,
    )
    distribusi = sorted(
        [x for x in items if "Distribusi" in x["pola"]],
        key=lambda x: x["vol_ratio"], reverse=True,
    )
    return _py({
        "akumulasi": akumulasi[:20],
        "distribusi": distribusi[:20],
        "net_score": len(akumulasi) - len(distribusi),
        "total_scan": total,
        "anomali_count": len(items),
        "sumber": "Volume analysis (yfinance)",
        "scope": scope,
    })


@app.get("/api/foreign-flow")
async def api_foreign_flow(scope: str = "core"):
    """Scan volume anomali / smart money.
    scope=core → ~45 cepat. scope=medium → ~200 likuid. scope=all → seluruh IDX (~1-2 mnt)."""
    if scope == "all":
        scope = "all"
    elif scope == "medium":
        scope = "medium"
    else:
        scope = "core"
    cache_key = f"foreign_flow:{scope}"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    try:
        if scope == "all":
            from core.stock_data import load_tickers
            from core.async_yf import async_download_many
            all_tickers = load_tickers()
            all_data = await async_download_many(all_tickers, period="3mo", interval="1d")
            items = []
            for ticker in all_tickers:
                kode = ticker.replace(".JK", "")
                df_raw = all_data.get(ticker) if isinstance(all_data, dict) else None
                if df_raw is None:
                    continue
                try:
                    df = fix_yf_columns(df_raw).apply(pd.to_numeric, errors="coerce")
                    df_tr = df[df["Volume"] > 0].dropna(subset=["Close", "Volume"])
                    r = _process_sm_df(kode, df_tr)
                    if r:
                        items.append(r)
                except Exception:
                    continue
            total = len(all_tickers)
        elif scope == "medium":
            from core.async_yf import async_download_many
            med_tickers = [t + ".JK" for t in LIQUID_250]
            all_data = await async_download_many(med_tickers, period="3mo", interval="1d")
            items = []
            for ticker in med_tickers:
                kode = ticker.replace(".JK", "")
                df_raw = all_data.get(ticker) if isinstance(all_data, dict) else None
                if df_raw is None:
                    continue
                try:
                    df = fix_yf_columns(df_raw).apply(pd.to_numeric, errors="coerce")
                    df_tr = df[df["Volume"] > 0].dropna(subset=["Close", "Volume"])
                    r = _process_sm_df(kode, df_tr)
                    if r:
                        items.append(r)
                except Exception:
                    continue
            total = len(med_tickers)
        else:
            tasks = [_scan_one_sm(k) for k in _SM_UNIVERSE]
            items = [r for r in await asyncio.gather(*tasks, return_exceptions=False) if r]
            total = len(_SM_UNIVERSE)

        payload = _build_sm_payload(items, total, scope)
        _cache_set(cache_key, payload)
        return payload

    except Exception as e:
        raise HTTPException(502, f"Gagal scan volume anomali: {e}")


import zlib as _zlib
import re as _re


def _parse_ksei_pdf(pdf_bytes: bytes) -> dict:
    """Extract data kepemilikan dari PDF X-15 KSEI (FlateDecode streams)."""
    strings: list[str] = []
    for m in _re.finditer(rb"stream\r?\n(.*?)endstream", pdf_bytes, _re.S):
        try:
            text = _zlib.decompress(m.group(1).strip()).decode("latin-1", errors="replace")
            strings.extend(_re.findall(r"\(([^)]+)\)", text))
        except Exception:
            pass

    def _find_val(*keywords: str) -> str:
        """Cari nilai setelah label yang mengandung salah satu keyword (ID/EN)."""
        for i in range(len(strings) - 1):
            s_low = strings[i].lower()
            if any(kw.lower() in s_low for kw in keywords):
                for j in range(i + 1, min(i + 4, len(strings))):
                    s = strings[j].strip()
                    if s.startswith(":"):
                        return s[1:].strip()
        return ""

    def _parse_pct(s: str) -> float:
        s = s.replace("%", "").replace(",", ".").strip()
        try:
            return float(s)
        except Exception:
            return 0.0

    nama = _find_val("sesuai SID", "Name (SID", "Name \\(SID")
    perusahaan = _find_val("Nama Perusahaan Tbk", "Issuer")
    jabatan = _find_val("Jabatan", "Position")
    pct_sebelum = _parse_pct(_find_val("Hak Suara Sebelum", "Voting rights before"))
    pct_setelah = _parse_pct(_find_val("Hak Suara Setelah", "Voting rights after"))
    pengendali_raw = _find_val("Keterangan Pengendali", "Controlling Shareholder").lower()
    is_pengendali = pengendali_raw.startswith("ya") or pengendali_raw == ": ya" or pengendali_raw.startswith("yes")

    all_text = " ".join(strings).lower()
    if "penjualan" in all_text or "divestasi" in all_text:
        jenis = "jual"
    elif "pembelian" in all_text or "repurchase" in all_text:
        jenis = "beli"
    elif "hibah" in all_text or "transfer" in all_text or "waris" in all_text:
        jenis = "transfer"
    else:
        jenis = "lain"

    return {
        "nama": nama,
        "perusahaan": perusahaan,
        "jabatan": jabatan,
        "pct_sebelum": pct_sebelum,
        "pct_setelah": pct_setelah,
        "perubahan": round(pct_setelah - pct_sebelum, 4),
        "jenis": jenis,
        "pengendali": is_pengendali,
    }


async def _fetch_x15_today(days_back: int = 0) -> list:
    """Fetch SEMUA laporan kepemilikan saham (X-15/POJK 4-2024) dari IDX +
    parse PDF KSEI, TANPA filter jenis pemegang -- filtering (≥5% & pengendali
    untuk /api/x15, jabatan direksi/komisaris untuk /api/insider) dilakukan
    masing-masing oleh endpoint pemanggil, bukan di sini. Field 'jabatan'
    hasil parse SUDAH berisi posisi resmi (Direktur/Komisaris/dst) untuk
    pelapor insider -- makanya transaksi insider tidak perlu sumber data
    baru, cuma perlu tidak dibuang oleh filter ≥5%."""
    from datetime import timedelta as _td, datetime as _dt
    import cloudscraper as _cs

    def _sync():
        sc = _cs.create_scraper(browser={"browser": "chrome", "platform": "windows", "mobile": False})
        today = (_dt.now() - _td(days=days_back)).strftime("%Y%m%d")
        r = sc.get(
            "https://www.idx.co.id/primary/ListedCompany/GetAnnouncement",
            params={"emitenType": "*", "indexFrom": 0, "pageSize": 100,
                    "dateFrom": today, "dateTo": today, "lang": "id", "keyword": "kepemilikan"},
            timeout=15,
        )
        replies = r.json().get("Replies", []) if r.status_code == 200 else []
        results = []
        for rep in replies:
            p = rep["pengumuman"]
            kode = p.get("Kode_Emiten", "").strip()
            tgl = p.get("TglPengumuman", "")[:10]
            atts = rep.get("attachments", [])
            if not atts or not kode:
                continue
            pdf_url = atts[0].get("FullSavePath", "")
            if not pdf_url:
                continue
            try:
                pr = sc.get(pdf_url, timeout=12)
                if pr.status_code != 200:
                    continue
                parsed = _parse_ksei_pdf(pr.content)
                # Skip jika tidak bisa parse nama (PDF format tidak dikenal)
                if not parsed["nama"] and parsed["pct_setelah"] == 0.0 and parsed["pct_sebelum"] == 0.0:
                    continue
                results.append({
                    "kode": kode,
                    "tanggal": tgl,
                    "pdf_url": pdf_url,
                    **parsed,
                })
            except Exception:
                continue
        return results

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _sync)


def _is_insider_jabatan(jabatan: str) -> bool:
    """True kalau field 'jabatan' hasil parse PDF menunjukkan pelapor adalah
    insider (direksi/komisaris), bukan sekadar pemegang saham substansial."""
    j = (jabatan or "").lower()
    return any(kw in j for kw in ("direktur", "komisaris", "direksi"))


@app.get("/api/x15")
async def api_x15(hari: int = 0):
    """Ringkasan harian transaksi kepemilikan ≥5% dari IDX X-15 filings.
    hari=0 → hari ini, hari=1 → kemarin, dst (max 7)."""
    hari = max(0, min(7, hari))
    cache_key = f"x15:{hari}"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    try:
        raw_items = await _fetch_x15_today(days_back=hari)
    except Exception as e:
        raise HTTPException(502, f"Gagal fetch X-15: {e}")

    # Hanya pemegang saham substansial (≥5%) atau pengendali -- transaksi
    # insider kecil (direksi/komisaris di bawah 5%) sengaja disaring keluar
    # di sini, lihat /api/insider untuk itu.
    items = [x for x in raw_items if x["pct_setelah"] >= 5.0 or x["pct_sebelum"] >= 5.0 or x["pengendali"]]

    akumulasi = sorted(
        [x for x in items if x["jenis"] in ("beli",) and x["perubahan"] >= 0],
        key=lambda x: x["perubahan"], reverse=True,
    )
    distribusi = sorted(
        [x for x in items if x["jenis"] in ("jual", "transfer") or x["perubahan"] < 0],
        key=lambda x: x["perubahan"],
    )

    from datetime import timedelta as _td, datetime as _dt
    tgl_str = (_dt.now() - _td(days=hari)).strftime("%d %b %Y")

    payload = _py({
        "akumulasi": akumulasi,
        "distribusi": distribusi,
        "total": len(items),
        "tanggal": tgl_str,
        "hari": hari,
    })
    _cache_set(cache_key, payload)
    return payload


@app.get("/api/insider")
async def api_insider(hari: int = 0):
    """Ringkasan harian transaksi INSIDER (direksi/komisaris beli-jual
    saham perusahaannya sendiri) dari filing IDX X-15/POJK 4-2024 yang sama
    dengan /api/x15 -- bedanya difilter dari field 'jabatan', bukan ≥5%
    kepemilikan (transaksi insider biasanya persentasenya kecil).
    hari=0 → hari ini, hari=1 → kemarin, dst (max 7)."""
    hari = max(0, min(7, hari))
    cache_key = f"insider:{hari}"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    try:
        raw_items = await _fetch_x15_today(days_back=hari)
    except Exception as e:
        raise HTTPException(502, f"Gagal fetch data insider: {e}")

    items = [x for x in raw_items if _is_insider_jabatan(x["jabatan"])]

    akumulasi = sorted(
        [x for x in items if x["jenis"] in ("beli",) and x["perubahan"] >= 0],
        key=lambda x: x["perubahan"], reverse=True,
    )
    distribusi = sorted(
        [x for x in items if x["jenis"] in ("jual", "transfer") or x["perubahan"] < 0],
        key=lambda x: x["perubahan"],
    )

    from datetime import timedelta as _td, datetime as _dt
    tgl_str = (_dt.now() - _td(days=hari)).strftime("%d %b %Y")

    payload = _py({
        "akumulasi": akumulasi,
        "distribusi": distribusi,
        "total": len(items),
        "tanggal": tgl_str,
        "hari": hari,
    })
    _cache_set(cache_key, payload)
    return payload


@app.get("/api/holders/{kode}")
async def api_holders(kode: str):
    """Struktur kepemilikan saham: % insider, institusi, dan daftar fund asing."""
    kode = kode.upper().replace(".JK", "")
    cache_key = f"holders:{kode}"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    def _sync():
        import yfinance as yf
        t = yf.Ticker(f"{kode}.JK")
        out: dict = {"kode": kode, "pct": {}, "institusi": []}
        # 1. Ringkasan % kepemilikan
        try:
            mh = t.major_holders
            if mh is not None and not mh.empty:
                key_map = {
                    "insidersPercentHeld": "Pengendali / Insider",
                    "institutionsPercentHeld": "Institusi (Asing)",
                    "institutionsFloatPercentHeld": "Float Institusi",
                    "institutionsCount": "Jumlah Institusi",
                }
                for i in range(len(mh)):
                    try:
                        raw_key = str(mh.index[i]) if hasattr(mh, "index") else f"r{i}"
                        raw_key = str(mh.iloc[i, 0]) if mh.shape[1] > 1 else raw_key
                        breakdown_label = str(mh.iloc[i, 1]) if mh.shape[1] > 1 else raw_key
                        val = float(str(mh.iloc[i, 0]).replace("%", "").strip())
                        label = key_map.get(breakdown_label, breakdown_label)
                        # Normalize: jika <= 1 berarti desimal (0.6 = 60%)
                        pct = round(val * 100 if val <= 1.01 else val, 2)
                        out["pct"][breakdown_label] = {"label": label, "pct": pct}
                    except Exception:
                        pass
        except Exception:
            pass
        # 2. Top institutional holders
        try:
            ih = t.institutional_holders
            if ih is not None and not ih.empty:
                rows = []
                for _, row in ih.iterrows():
                    try:
                        nama = str(row.get("Holder", row.iloc[0]))
                        pct_raw = float(row.get("pctHeld", row.get("% Out", 0)))
                        pct = round(pct_raw * 100 if pct_raw < 1 else pct_raw, 3)
                        shares_raw = str(row.get("Shares", 0)).replace(",", "")
                        shares = int(float(shares_raw)) if shares_raw.replace(".", "").isdigit() else 0
                        chg = float(row.get("pctChange", 0)) * 100
                        tgl = str(row.get("Date Reported", ""))[:10]
                        rows.append({
                            "nama": nama,
                            "pct": pct,
                            "shares": shares,
                            "chg": round(chg, 2),  # % change dari kuartal lalu
                            "tgl": tgl,
                            "aksi": "beli" if chg > 0.5 else "jual" if chg < -0.5 else "tahan",
                        })
                    except Exception:
                        continue
                out["institusi"] = sorted(rows, key=lambda x: x["pct"], reverse=True)[:15]
        except Exception:
            pass
        return _py(out)

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _sync)
    _cache_set(cache_key, result)
    return result


# ---------- frontend statis ----------
if os.path.isdir(_STATIC):
    app.mount("/", StaticFiles(directory=_STATIC, html=True), name="static")
