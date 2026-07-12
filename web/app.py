# =========================
# WEB API - FastAPI di atas core/
# =========================
# Lapisan web yang MEMBUNGKUS fungsi core/ yang sudah ada jadi HTTP API.
# TIDAK ada logika analisis baru di sini -- semua tetap di core/ (sumber
# kebenaran tunggal).
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
import re
import sys
import time
import asyncio
import tempfile
import hashlib
import hmac
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

from core.async_yf import async_download, async_download_many
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
# DIPERLUAS (permintaan user: Top Pick jangan cuma LQ45) supaya cakupan
# penuh sama dgn LIQUID_250 (178 saham) -- entri BARU di bawah diturunkan
# LANGSUNG dari pengelompokan komentar sektor yang SUDAH ada di LIQIUD_250
# sendiri (bukan riset baru dari nol), TAPI diverifikasi dulu tidak
# menimpa entri yang SUDAH benar di atas (mis. KLBF sengaja TETAP
# Healthcare, meski di LIQUID_250 kebetulan dikelompokkan dekat saham
# consumer -- pengelompokan LIQUID_250 itu cuma kemudahan visual daftar,
# bukan klasifikasi GICS yang presisi). Dua kategori baru ("Real Estate",
# "Transportation & Logistics") ditambah krn LIQUID_250 punya saham dari
# 2 grup itu yang sebelumnya sama sekali tidak terwakili di sini.
SECTOR_MAP_UNIVERSE = {
    "BBCA": "Financials", "BBRI": "Financials", "BMRI": "Financials", "BBNI": "Financials",
    "BRIS": "Financials", "ARTO": "Financials",
    "BTPS": "Financials", "MEGA": "Financials", "BDMN": "Financials", "BJTM": "Financials",
    "BJBR": "Financials", "PNBN": "Financials", "NISP": "Financials", "BNGA": "Financials",
    "BNLI": "Financials", "BBMD": "Financials", "ADMF": "Financials", "BFIN": "Financials",
    "MFIN": "Financials", "VRNA": "Financials", "WOMF": "Financials", "MREI": "Financials",
    "ASBI": "Financials",
    "TLKM": "Infrastructure", "EXCL": "Infrastructure", "ISAT": "Infrastructure",
    "TOWR": "Infrastructure", "TBIG": "Infrastructure", "JSMR": "Infrastructure",
    "SUPR": "Infrastructure", "WIKA": "Infrastructure", "WSKT": "Infrastructure",
    "PTPP": "Infrastructure", "ADHI": "Infrastructure", "PPRE": "Infrastructure", "LINK": "Infrastructure",
    "ASII": "Industrials", "UNTR": "Industrials",
    "AUTO": "Industrials", "SMSM": "Industrials", "IMAS": "Industrials", "INDS": "Industrials",
    "BRAM": "Industrials", "HEXA": "Industrials", "ASSA": "Industrials", "BIRD": "Industrials",
    "GIAA": "Industrials", "GJTL": "Industrials", "FASW": "Industrials", "SRIL": "Industrials",
    "SMDR": "Industrials",
    "UNVR": "Consumer Non-Cyclical", "ICBP": "Consumer Non-Cyclical", "INDF": "Consumer Non-Cyclical",
    "GGRM": "Consumer Non-Cyclical", "HMSP": "Consumer Non-Cyclical", "CPIN": "Consumer Non-Cyclical",
    "JPFA": "Consumer Non-Cyclical", "AMRT": "Consumer Non-Cyclical",
    "SIDO": "Consumer Non-Cyclical", "ULTJ": "Consumer Non-Cyclical", "MYOR": "Consumer Non-Cyclical",
    "ROTI": "Consumer Non-Cyclical", "DLTA": "Consumer Non-Cyclical", "MLBI": "Consumer Non-Cyclical",
    "LSIP": "Consumer Non-Cyclical", "AALI": "Consumer Non-Cyclical", "SGRO": "Consumer Non-Cyclical",
    "SSMS": "Consumer Non-Cyclical", "PALM": "Consumer Non-Cyclical", "TBLA": "Consumer Non-Cyclical",
    "BWPT": "Consumer Non-Cyclical", "TAPG": "Consumer Non-Cyclical", "STTP": "Consumer Non-Cyclical",
    "CAMP": "Consumer Non-Cyclical", "GOOD": "Consumer Non-Cyclical", "KEJU": "Consumer Non-Cyclical",
    "KLBF": "Healthcare",
    "MIKA": "Healthcare", "SILO": "Healthcare", "HEAL": "Healthcare", "PRDA": "Healthcare",
    "IRRA": "Healthcare", "DVLA": "Healthcare", "TSPC": "Healthcare", "KAEF": "Healthcare",
    "SCPI": "Healthcare", "SOHO": "Healthcare", "PHAR": "Healthcare",
    "ADRO": "Energy", "PTBA": "Energy", "ITMG": "Energy", "MEDC": "Energy", "PGAS": "Energy",
    "BRMS": "Energy", "RAJA": "Energy", "AKRA": "Energy",
    "BYAN": "Energy", "HRUM": "Energy", "DSSA": "Energy", "TOBA": "Energy", "GEMS": "Energy",
    "BSSR": "Energy", "KKGI": "Energy", "MYOH": "Energy", "DEWA": "Energy", "FIRE": "Energy",
    "INDY": "Energy", "ELSA": "Energy", "PTRO": "Energy", "SMMT": "Energy", "CUAN": "Energy",
    "ARCI": "Energy", "PGEO": "Energy", "AMMN": "Energy",
    "ANTM": "Basic Materials", "INCO": "Basic Materials", "MDKA": "Basic Materials",
    "TINS": "Basic Materials", "SMGR": "Basic Materials", "INTP": "Basic Materials",
    "BRPT": "Basic Materials", "TPIA": "Basic Materials",
    "SMBR": "Basic Materials", "WTON": "Basic Materials", "BTON": "Basic Materials",
    "ISSP": "Basic Materials", "KRAS": "Basic Materials", "NIKL": "Basic Materials",
    "AMFG": "Basic Materials", "AGII": "Basic Materials", "MLIA": "Basic Materials",
    "INKP": "Basic Materials", "TKIM": "Basic Materials", "ALKA": "Basic Materials",
    "NCKL": "Basic Materials", "DPUM": "Basic Materials",
    "MNCN": "Consumer Cyclical", "ACES": "Consumer Cyclical", "MAPI": "Consumer Cyclical",
    "ERAA": "Consumer Cyclical",
    "LPPF": "Consumer Cyclical", "RALS": "Consumer Cyclical", "KINO": "Consumer Cyclical",
    "MAPB": "Consumer Cyclical", "EMTK": "Consumer Cyclical", "MLPL": "Consumer Cyclical",
    "MIDI": "Consumer Cyclical", "CSMI": "Consumer Cyclical", "PZZA": "Consumer Cyclical",
    "GOTO": "Technology", "BUKA": "Technology",
    "DMMX": "Technology", "KREN": "Technology", "MTDL": "Technology", "DCII": "Technology",
    "ARNA": "Technology",
    "CTRA": "Real Estate", "BSDE": "Real Estate", "SMRA": "Real Estate", "PWON": "Real Estate",
    "LPKR": "Real Estate", "JRPT": "Real Estate", "APLN": "Real Estate", "MDLN": "Real Estate",
    "DUTI": "Real Estate", "DMAS": "Real Estate", "MKPI": "Real Estate", "PLIN": "Real Estate",
    "GPRA": "Real Estate", "NRCA": "Real Estate", "CITY": "Real Estate", "KIJA": "Real Estate",
    "BEST": "Real Estate",
    "HITS": "Transportation & Logistics", "LEAD": "Transportation & Logistics",
    "TMAS": "Transportation & Logistics", "SHIP": "Transportation & Logistics",
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
# Filing X-15 untuk hari>=1 (kemarin dst) sudah final dan TIDAK PERNAH
# berubah lagi -- beda dengan data harga/skor yang terus bergerak. Re-scrape
# tiap 5 menit (_CACHE_TTL biasa) untuk hari yang sama persis itu boros:
# tiap request PDF KSEI per emiten di-download+parse ulang lewat cloudscraper
# (lihat _fetch_x15_today), dan sejak jendela hari yang bisa diminta
# diperpanjang jadi ~sebulan (lihat api_x15/api_insider), beban itu jauh
# lebih terasa. TTL panjang di sini HANYA untuk hari>=1; hari=0 (hari ini)
# tetap pakai _CACHE_TTL biasa karena filing baru bisa masuk kapan saja
# selama jam bursa.
_CACHE_TTL_HISTORICAL = 86400  # 24 jam


def _cache_get(key):
    try:
        val = _redis.get(f"cache:{key}")
        if val is None:
            return None
        return pickle.loads(val)
    except Exception:
        # fallback to None if redis error
        return None


def _cache_set(key, val, ttl=None):
    try:
        serialized = pickle.dumps(val)
        _redis.setex(f"cache:{key}", ttl or _CACHE_TTL, serialized)
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
            # BUG NYATA ditemukan lewat laporan user ("kenapa lagi nih" --
            # 429 bertubi-tubi walau endpoint-nya sendiri sehat): `expire()`
            # DULU dipanggil di SETIAP request (bukan cuma saat counter baru
            # dibuat), mengubah ini dari fixed-window jadi jendela yang
            # SELALU refresh sendiri -- selama masih ada request masuk
            # (dijamin ada, market-strip auto-refresh tiap 30 detik), TTL
            # 60 detik itu TIDAK PERNAH benar-benar habis. Begitu counter
            # kelewat 1200 sekali saja (mudah tercapai: satu buka Beranda
            # nembak ~11 endpoint sekaligus + user pindah2 tab), user itu
            # macet kena 429 SELAMANYA -- termasuk request yang DIBLOKIR pun
            # ikut me-refresh window-nya (pipe.incr jalan sebelum threshold
            # dicek), jadi tidak pernah ada celah 60 detik kosong utk reset.
            # Fix: expire cuma dipasang SEKALI, saat count==1 (key baru
            # dibuat) -- window sekarang benar2 reset tiap 60 detik apa pun
            # volume trafiknya.
            pipe = _redis.pipeline()
            pipe.incr(key)
            count, = pipe.execute()
            if count == 1:
                _redis.expire(key, _RATE_WINDOW)
            if count > _RATE_MAX:
                return JSONResponse(
                    {"error": "Terlalu banyak permintaan. Coba lagi sebentar."},
                    status_code=429)
        except Exception:
            # If Redis fails, fail open to avoid blocking service
            pass
    return await call_next(request)


# ---------- Forum komunitas (Tanya Jawab) ----------
# Permintaan user: "fitur chat buat komunitas ... lebih ke forum sih".
# Aplikasi ini TIDAK PUNYA sistem akun/login (dihapus dead code sesi
# sebelumnya) -- identitas poster HANYA nama bebas yang diketik user
# sendiri (bukan terverifikasi). `is_admin` per baris SATU-SATUNYA hal
# yang benar2 diverifikasi SERVER (hmac.compare_digest thd FORUM_ADMIN_
# SECRET) -- kode admin BOLEH di-cache di localStorage sisi klien utk
# kenyamanan autofill, TAPI klien TIDAK PERNAH dipercaya begitu saja soal
# status admin, konsisten dgn prinsip "tidak ada kunci/token di sisi
# browser" di atas (baris awal file ini).
FORUM_NAMA_MAX, FORUM_JUDUL_MAX, FORUM_ISI_MAX = 50, 200, 5000

# Limiter TERPISAH & lebih ketat dari rate_limit() global di atas (1200/60d
# terlalu longgar utk anti-spam endpoint tulis spesifik) -- SAMA PERSIS pola
# INCR + expire-HANYA-saat-count==1 (fix bug "stuck window" di komentar
# rate_limit() di atas) -- JANGAN panggil expire() unconditional di sini.
_FORUM_RATE_MAX = 8        # tulis/hapus
_FORUM_RATE_WINDOW = 300   # per 5 menit


def _forum_rate_limit(request: Request):
    ip = request.client.host if request.client else "unknown"
    key = f"forum_write:{ip}"
    try:
        pipe = _redis.pipeline()
        pipe.incr(key)
        count, = pipe.execute()
        if count == 1:
            _redis.expire(key, _FORUM_RATE_WINDOW)
        if count > _FORUM_RATE_MAX:
            raise HTTPException(429, "Terlalu banyak aktivitas forum. Coba lagi beberapa menit lagi.")
    except HTTPException:
        raise
    except Exception:
        pass  # Redis down -- fail open, konsisten dgn limiter global


def _forum_is_admin(admin_code: str | None) -> bool:
    """Kode kosong ATAU FORUM_ADMIN_SECRET belum di-set -> SELALU False
    (fail-closed) -- SEBELUM compare_digest, supaya hmac.compare_digest
    ("","") == True tidak pernah jadi celah kalau secret env lupa diisi."""
    from core.config import FORUM_ADMIN_SECRET
    if not admin_code or not FORUM_ADMIN_SECRET:
        return False
    return hmac.compare_digest(admin_code, FORUM_ADMIN_SECRET)


def _forum_text(value, max_len: int, label: str) -> str:
    v = (value or "").strip()
    if not v:
        raise HTTPException(400, f"{label} wajib diisi.")
    if len(v) > max_len:
        raise HTTPException(400, f"{label} maksimal {max_len} karakter.")
    return v


def _forum_admin_flag(body: dict) -> bool:
    """Kode kosong/whitespace -> posting biasa (bukan error). Kode ADA
    tapi SALAH -> error eksplisit (bukan diam2 turun jadi non-admin) --
    supaya admin sadar kalau salah ketik, bukan bingung kenapa postingnya
    tidak dapat badge."""
    code = (body.get("admin_code") or "").strip()
    if not code:
        return False
    if not _forum_is_admin(code):
        raise HTTPException(400, "Kode admin salah.")
    return True


# Set kategori TETAP (bukan tabel dinamis) -- cukup utk skala forum ini,
# divalidasi thd dict ini di endpoint (bukan di core/forum.py, modul data
# itu tetap tidak tahu apa pun soal validasi HTTP-facing, sama prinsip dgn
# _forum_text di atas).
FORUM_KATEGORI = {
    "umum": "Umum",
    "pertanyaan": "Pertanyaan",
    "teknikal": "Analisis Teknikal",
    "fundamental": "Analisis Fundamental",
    "fitur": "Fitur Website",
}
_FORUM_SORT = {"terbaru", "populer"}
_FORUM_STATUS = {"belum_dijawab"}


def _forum_kategori_flag(value) -> str:
    """Kosong/tidak dikirim -> default 'umum'. Dikirim tapi bukan salah
    satu key FORUM_KATEGORI -> error eksplisit (mencegah nilai sampah
    mengotori chip filter kategori)."""
    v = (value or "").strip() or "umum"
    if v not in FORUM_KATEGORI:
        raise HTTPException(400, "Kategori tidak dikenal.")
    return v


def _forum_like_escape(q: str) -> str:
    """Escape literal `%`/`_` (dan escape char `\\` itu sendiri lebih
    dulu) sebelum dibungkus jadi pola LIKE '%...%' -- supaya user yang
    ketik '%' atau '_' di kotak pencarian tidak diam2 memicu wildcard SQL
    yang tidak dia maksud."""
    return q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _forum_tickers(teks: str) -> list[str]:
    """Deteksi kode saham yang disebut di teks bebas (forum), utk auto-link
    ke halaman Analisis di frontend. WAJIB reuse deteksi_emiten() dari
    core/news_emiten.py -- SATU-SATUNYA implementasi matching ticker-di-
    teks-bebas yang benar di codebase ini (case-sensitive, ada guard kode
    rawan-false-positive spt GOOD/LABA/CARE); core/news.py pernah punya
    implementasi kedua yang lebih naif (substring match) dan itu bug yang
    sudah diperbaiki -- JANGAN bikin regex ticker baru di sini.

    Pre-filter kandidat via regex "4 huruf kapital utuh" dulu (bukan cek
    seluruh ~800 kode emiten per post) -- deteksi_emiten(kandidat_kode=...)
    memang didesain utk shortlist spt ini, penting utk performa krn forum
    bisa nampilkan puluhan post sekaligus di satu request list."""
    from core.news_emiten import deteksi_emiten
    candidates = list(set(re.findall(r"\b[A-Z]{4}\b", teks)))
    if not candidates:
        return []
    return deteksi_emiten(teks, kandidat_kode=candidates)


@app.get("/api/forum/threads")
async def api_forum_list_threads(request: Request):
    from core.forum import list_threads
    qp = request.query_params
    q = (qp.get("q") or "").strip()
    kategori = (qp.get("kategori") or "").strip()
    if kategori and kategori not in FORUM_KATEGORI:
        raise HTTPException(400, "Kategori tidak dikenal.")
    sort = qp.get("sort") or "terbaru"
    if sort not in _FORUM_SORT:
        sort = "terbaru"
    status = qp.get("status") or None
    if status not in _FORUM_STATUS:
        status = None
    threads = await asyncio.to_thread(
        list_threads,
        200,
        _forum_like_escape(q) if q else None,
        kategori or None,
        sort,
        status,
    )
    for t in threads:
        t["tickers"] = _forum_tickers(f"{t['judul']} {t['isi']}")
    return _py(threads)


@app.get("/api/forum/threads/{thread_id}")
async def api_forum_thread_detail(thread_id: int):
    from core.forum import get_thread, list_replies
    thread = await asyncio.to_thread(get_thread, thread_id)
    if thread is None:
        raise HTTPException(404, "Thread tidak ditemukan.")
    replies = await asyncio.to_thread(list_replies, thread_id)
    thread["tickers"] = _forum_tickers(f"{thread['judul']} {thread['isi']}")
    for r in replies:
        r["tickers"] = _forum_tickers(r["isi"])
    return _py({"thread": thread, "replies": replies})


@app.post("/api/forum/threads")
async def api_forum_create_thread(request: Request):
    _forum_rate_limit(request)
    body = await request.json()
    nama = _forum_text(body.get("nama"), FORUM_NAMA_MAX, "Nama")
    judul = _forum_text(body.get("judul"), FORUM_JUDUL_MAX, "Judul")
    isi = _forum_text(body.get("isi"), FORUM_ISI_MAX, "Isi")
    is_admin = _forum_admin_flag(body)
    kategori = _forum_kategori_flag(body.get("kategori"))
    from core.forum import create_thread
    return _py(await asyncio.to_thread(create_thread, nama, judul, isi, is_admin, kategori))


@app.post("/api/forum/threads/{thread_id}/replies")
async def api_forum_create_reply(thread_id: int, request: Request):
    _forum_rate_limit(request)
    body = await request.json()
    nama = _forum_text(body.get("nama"), FORUM_NAMA_MAX, "Nama")
    isi = _forum_text(body.get("isi"), FORUM_ISI_MAX, "Isi")
    is_admin = _forum_admin_flag(body)
    from core.forum import create_reply
    reply = await asyncio.to_thread(create_reply, thread_id, nama, isi, is_admin)
    if reply is None:
        raise HTTPException(404, "Thread tidak ditemukan.")
    return _py(reply)


@app.delete("/api/forum/threads/{thread_id}")
async def api_forum_delete_thread(thread_id: int, request: Request):
    _forum_rate_limit(request)
    body = await request.json()
    if not _forum_is_admin((body.get("admin_code") or "").strip()):
        raise HTTPException(400, "Kode admin salah/kosong.")
    from core.forum import delete_thread
    if not await asyncio.to_thread(delete_thread, thread_id):
        raise HTTPException(404, "Thread tidak ditemukan.")
    return {"ok": True}


@app.delete("/api/forum/replies/{reply_id}")
async def api_forum_delete_reply(reply_id: int, request: Request):
    _forum_rate_limit(request)
    body = await request.json()
    if not _forum_is_admin((body.get("admin_code") or "").strip()):
        raise HTTPException(400, "Kode admin salah/kosong.")
    from core.forum import delete_reply
    if not await asyncio.to_thread(delete_reply, reply_id):
        raise HTTPException(404, "Balasan tidak ditemukan.")
    return {"ok": True}


@app.post("/api/forum/replies/{reply_id}/upvote")
async def api_forum_upvote_reply(reply_id: int, request: Request):
    _forum_rate_limit(request)
    from core.forum import upvote_reply
    reply = await asyncio.to_thread(upvote_reply, reply_id)
    if reply is None:
        raise HTTPException(404, "Balasan tidak ditemukan.")
    return _py(reply)


@app.post("/api/forum/replies/{reply_id}/best-answer")
async def api_forum_best_answer(reply_id: int, request: Request):
    _forum_rate_limit(request)
    body = await request.json()
    if not _forum_is_admin((body.get("admin_code") or "").strip()):
        raise HTTPException(400, "Kode admin salah/kosong.")
    from core.forum import set_best_answer
    reply = await asyncio.to_thread(set_best_answer, reply_id)
    if reply is None:
        raise HTTPException(404, "Balasan tidak ditemukan.")
    return _py(reply)


@app.post("/api/forum/threads/{thread_id}/report")
async def api_forum_report_thread(thread_id: int, request: Request):
    _forum_rate_limit(request)
    from core.forum import report_thread
    if not await asyncio.to_thread(report_thread, thread_id):
        raise HTTPException(404, "Thread tidak ditemukan.")
    return {"ok": True}


@app.post("/api/forum/replies/{reply_id}/report")
async def api_forum_report_reply(reply_id: int, request: Request):
    _forum_rate_limit(request)
    from core.forum import report_reply
    if not await asyncio.to_thread(report_reply, reply_id):
        raise HTTPException(404, "Balasan tidak ditemukan.")
    return {"ok": True}


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


async def _backfill_recent_gap(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """BUG NYATA ditemukan lewat 2 laporan user di hari yang sama: (1) IHSG
    tetap tampil "BULLISH 91%" walau user tahu persis kemarin pasar merah
    ("kayanya emg datanya yg ngaco deh"), (2) sinyal ARTO baru (TOP_PICK,
    dicatat 2026-07-09 00:01) entry_price=953 yang sama sekali tidak nyambung
    dengan histori harga ARTO sungguhan ("arto aneh bgt hari ini aja arto di
    harga 1000 bukan 950"). Ditelusuri sampai akar: Yahoo Finance kadang
    GAGAL menerbitkan bar HARIAN utk hari bursa yang baru saja selesai --
    utk ^JKSE baris hari itu HILANG SAMA SEKALI dari respons, utk saham
    individual (ARTO) baris itu ADA tapi OHLC-nya semua NaN (cuma Volume
    yang terisi) -- dropna() di _clean() lalu diam-diam MEMBUANG baris NaN
    itu. Efeknya SAMA: dataframe harian "macet" 1 hari bursa di belakang,
    dan SEMUA yang dihitung darinya (RSI, MACD, tren MA, volume_trend,
    skor bullish/bearish IHSG, skenario entry price Trading Plan) diam-diam
    buta terhadap pergerakan hari yang hilang itu -- padahal harga REAL-TIME
    (fast_info/quote langsung, jalur terpisah) tetap benar, jadi yang
    tampil ke user JADI KONTRADIKTIF (harga live sudah pindah jauh, tapi
    "analisis teknikal" masih baca kondisi 1 hari sebelumnya).

    Dibuktikan nyata: data INTRADAY (interval per jam) untuk hari yang
    "hilang" itu SELALU LENGKAP walau data harian gagal -- jadi hari yang
    hilang/NaN itu ditambal dengan meresample candle per-jam jadi 1 candle
    harian (Open=jam pertama, High/Low=ekstrem, Close=jam terakhir,
    Volume=jumlah), HANYA utk tanggal yang benar2 hilang/tidak lengkap di
    data harian -- tanggal yang SUDAH ada & valid di data harian tidak
    disentuh sama sekali (data harian resmi tetap diutamakan kalau ada).

    Fail-safe: kalau fetch intraday-nya sendiri gagal/kosong (mis. ticker
    yang memang tidak py data per-jam), balikin df apa adanya -- tidak
    boleh menggagalkan seluruh analisis cuma gara2 tambalan ini gagal."""
    if df is None or df.empty:
        return df
    try:
        hourly = await async_download(ticker, period="5d", interval="1h", progress=False)
        hourly = fix_yf_columns(hourly).apply(pd.to_numeric, errors="coerce").dropna()
        return _merge_hourly_gap(df, hourly)
    except Exception:
        return df


def _merge_hourly_gap(df: pd.DataFrame, hourly: pd.DataFrame) -> pd.DataFrame:
    """Logika inti (sinkron, dipakai bareng oleh _backfill_recent_gap versi
    1-ticker & versi batch _backfill_recent_gap_batch): resample candle
    per-jam yang SUDAH bersih jadi candle harian, lalu tambal HANYA tanggal
    yang belum ada di df harian -- lihat docstring _backfill_recent_gap utk
    latar belakang bug-nya."""
    if hourly is None or hourly.empty:
        return df
    try:
        if hourly.index.tz is not None:
            hourly.index = hourly.index.tz_localize(None)
        daily_from_hourly = hourly.resample("1D").agg(
            {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
        ).dropna()
        daily_from_hourly.index = daily_from_hourly.index.normalize()

        df_norm_index = df.index.tz_localize(None) if df.index.tz is not None else df.index
        existing_dates = set(pd.DatetimeIndex(df_norm_index).normalize())
        missing = daily_from_hourly[~daily_from_hourly.index.isin(existing_dates)]
        if missing.empty:
            return df

        df2 = df.copy()
        df2.index = df_norm_index
        return pd.concat([df2, missing]).sort_index()
    except Exception:
        return df


async def _backfill_recent_gap_batch(daily_map: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Versi batch dari _backfill_recent_gap -- dipakai _confidence_raw_
    signals() yang menganalisis SCREENER_UNIVERSE sekaligus (bukan 1
    ticker), supaya penambalannya TETAP 1 panggilan batch tambahan (lewat
    async_download_many, yang sudah py throttling/retry sendiri) BUKAN N
    panggilan per-ticker terpisah yang bisa memicu rate-limit Yahoo
    Finance sendiri. Fail-safe: kalau batch intraday-nya gagal total,
    balikin daily_map apa adanya."""
    try:
        hourly_map = await async_download_many(list(daily_map.keys()), period="5d", interval="1h")
    except Exception:
        return daily_map
    if not hourly_map:
        return daily_map
    result = {}
    for ticker, df in daily_map.items():
        hourly = hourly_map.get(ticker)
        if hourly is not None and not hourly.empty:
            try:
                hourly = fix_yf_columns(hourly).apply(pd.to_numeric, errors="coerce").dropna()
            except Exception:
                hourly = None
        result[ticker] = _merge_hourly_gap(df, hourly) if hourly is not None else df
    return result


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
        # Tambal celah bar harian terbaru yang hilang/NaN (lihat
        # _backfill_recent_gap) -- HANYA relevan utk data harian; interval
        # lain (mis. mingguan utk tren, atau per-jam itu sendiri) tidak
        # kena bug spesifik ini.
        if interval == "1d":
            df = await _backfill_recent_gap(df, ticker)
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
    likuiditas = _liquidity_label(avg_value_20)
    # is_illiquid diteruskan ke calculate_ad_line supaya sinyal Akumulasi/
    # Distribusi (Tersembunyi)-nya menurunkan confidence utk saham
    # transaksi tipis -- CLV di situ lebih rawan digerakkan 1-2 order
    # doang, bukan pola akumulasi/distribusi yang luas.
    ad = calculate_ad_line(df, is_illiquid=likuiditas in ("Kurang Likuid", "Tidak Likuid"))
    current_price = ai.get("price") or 0
    # R1/S1 pakai calculate_snr_levels() (core/charts/snr_chart.py), lihat
    # catatan lengkap soal kenapa BUKAN calculate_target_levels() di commit
    # sebelumnya (pivot 1-candle vs pivot+swing histori sungguhan).
    snr = calculate_snr_levels(df)
    r1 = snr["r1"]
    s1 = snr["s1"]
    potensi_naik_pct = ((r1 / current_price) - 1) * 100 if current_price else 0.0
    risiko_turun_pct = (1 - (s1 / current_price)) * 100 if current_price else 0.0
    return {
        "likuiditas": likuiditas,
        "avg_value_20": round(avg_value_20, 0),
        "gaya_trading": _trading_style_label(ai.get("atr_pct") or 0),
        "bandar": None if not ad else {"label": ad["label"], "sinyal": ad["sinyal"], "confidence": ad["confidence"]},
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


def _fundamental_median_upside_pct(val: dict) -> float | None:
    """Upside vs MEDIAN dari semua metode valuasi -- BUKAN val['upside_pct']
    (yang dari MEAN/'mid'). Median jauh lebih tahan outlier: ditemukan nyata
    saat live-check GGRM, metode 'PBV x 2' menghasilkan Rp66.635 (4x lebih
    tinggi dari metode kedua tertinggi) krn BVPS GGRM memang tinggi -- itu
    BUKAN data korup (lolos guard _add() di _valuation()), tapi tetap
    menarik MEAN jauh ke atas (upside 70%) dibanding median (upside 42%).
    Dipakai KHUSUS utk skor Top Pick di sini -- SENGAJA TIDAK mengubah
    val['mid']/val['upside_pct'] yang sudah dipakai panel Fundamental &
    Valuasi di halaman Analisis (frontend di sana malah sudah pakai
    median-nya sendiri utk 'Konsensus Fair Value', konsisten dgn pilihan
    yang sama di sini)."""
    methods = val.get("methods") or {}
    price = val.get("price")
    vals = sorted(v for v in methods.values() if v and v > 0)
    if not vals or not price:
        return None
    n = len(vals)
    median = (vals[n // 2 - 1] + vals[n // 2]) / 2 if n % 2 == 0 else vals[n // 2]
    return round((median / price - 1) * 100, 1)


def _apply_liquidity_cap(score: float, likuiditas: str) -> tuple[float, bool]:
    """Batasi (bukan hilangkan) skor gabungan kalau likuiditas buruk --
    lihat catatan di atas _CONFIDENCE_DEFAULT_WEIGHTS. Returns (skor akhir,
    apakah kena batas)."""
    if likuiditas == "Tidak Likuid" and score > 35:
        return 35.0, True
    if likuiditas == "Kurang Likuid" and score > 55:
        return 55.0, True
    return score, False


def _display_pct_capped(pct: float, cap: float = 100.0) -> str:
    """Format persentase utk teks reason/warning, dibatasi ke +-cap%.
    Ditemukan nyata (MNCN): metode 'PER x 15' bisa menghasilkan upside
    600%+ kalau PE riil suatu saham jauh di bawah asumsi 'PE wajar 15x' --
    angka itu SECARA MATEMATIS benar dari formula yang ada, tapi
    menampilkannya apa adanya ('+612% upside') kedengaran bombastis,
    melanggar prinsip project ini sendiri (tidak ada klaim return
    berlebihan). Dibatasi TAPI TIDAK DISEMBUNYIKAN -- ditandai '>=100%'
    (bukan dibulatkan jadi angka pasti '100%') supaya tetap jujur bahwa
    aslinya lebih ekstrem dari yang ditampilkan."""
    if abs(pct) >= cap:
        return f"{'+' if pct >= 0 else '-'}>={cap:.0f}%"
    return f"{pct:+.0f}%"


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
    fund_verdict = it.get("fund_verdict")
    fund_upside = it.get("fund_upside_pct")
    if fund_verdict == "Undervalued":
        reasons.append(
            f"Fundamental: Undervalued vs estimasi wajar ({_display_pct_capped(fund_upside)} upside)"
            if fund_upside is not None else "Fundamental: Undervalued vs estimasi wajar"
        )
    kepemilikan = it.get("kepemilikan_change_pct")
    if kepemilikan is not None and kepemilikan > 0:
        reasons.append(f"Pemegang saham substansial menambah kepemilikan (+{kepemilikan:.2f}% belakangan ini)")

    if it["likuiditas"] in ("Tidak Likuid", "Kurang Likuid"):
        warnings.append(f"Likuiditas {it['likuiditas']} -- eksekusi & spread bisa jadi kendala nyata")
    if rr is not None and rr < 1:
        warnings.append(f"Risiko stop loss lebih besar dari target take profit (RR {rr:.1f}:1)")
    if bandar and bandar["label"] in ("Distribusi", "Distribusi Tersembunyi"):
        warnings.append(f"Proxy volume: {bandar['label']} -- volume belum mengonfirmasi penguatan")
    if it.get("pattern") and it.get("pattern_bias") == "BEARISH":
        warnings.append(f"{pattern_label}: {it['pattern']} (bearish) -- perlu diwaspadai meski skor gabungan tinggi")
    if fund_verdict == "Overvalued":
        warnings.append(
            f"Fundamental: Overvalued vs estimasi wajar ({_display_pct_capped(fund_upside)}) -- valuasi tergolong mahal"
            if fund_upside is not None else "Fundamental: Overvalued vs estimasi wajar"
        )
    if kepemilikan is not None and kepemilikan < 0:
        warnings.append(f"Pemegang saham substansial mengurangi kepemilikan ({kepemilikan:.2f}% belakangan ini)")

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


async def _signal_audit_price_lookup(kode: str):
    """Harga REAL-TIME (reuse _realtime_price, SAMA sumber yang dipakai
    _signal_entry_price_lookup saat entry BARU dicatat) dipakai utk audit
    sinyal yang SUDAH tercatat, dibarengi tanggal "hari ini" (kutipan
    real-time selalu berarti "sekarang" secara definisi).

    REVISI (bug NYATA ditemukan live: TPIA/ARTO ter-'Kena SL' padahal user
    melihat sendiri harganya NAIK hari itu): versi SEBELUMNYA pakai
    closing harian dari _clean()/.download() -- SUMBER BEDA dari fast_info
    yang dipakai merekam entry_price. Dua sumber yang tidak sinkron ini
    ternyata bisa BEDA JAUH: bar harian yfinance utk hari terbaru kadang
    masih NaN/belum terbit, jadi setelah dropna() harga yang kepakai bisa
    closing BEBERAPA HARI sebelumnya -- lebih basi dari entry_price yang
    justru direkam dari kutipan real-time yang lebih baru. Staleness guard
    sempat ditambahkan di audit_open_signals() utk menahan resolusi palsu
    semacam ini, TAPI itu jadi memblokir SEMUA progres TP/SL yang SAH juga
    selama bar harian macet -- perbaikan yang lebih mendasar: pakai SUMBER
    YANG SAMA dgn entry (fast_info), supaya tidak ada lagi mismatch antar
    sumber sama sekali, staleness guard tetap ada sbg jaring pengaman
    (selalu lolos kalau sumbernya konsisten begini, tidak pernah
    memblokir progres yang genuinely terjadi)."""
    try:
        from datetime import date as _date
        rt = await _realtime_price(kode + ".JK")
        if rt is None or not rt.get("price"):
            return None
        return float(rt["price"]), _date.today()
    except Exception:
        return None


async def _run_pending_entry_audit() -> list[dict]:
    """Audit semua sinyal PENDING_ENTRY (entry tersentuh -> OPEN, atau
    kadaluarsa -> EXPIRED_NO_ENTRY). Dipanggil SEBELUM _run_signal_audit
    (audit posisi OPEN) di satu putaran auto-cycle -- urutan ini sengaja:
    entry yang baru saja tersentuh di siklus INI belum perlu dicek TP/SL
    sampai siklus BERIKUTNYA (posisi baru saja aktif, wajar belum
    kemana-mana)."""
    from core.signal_history import audit_pending_entries

    return await audit_pending_entries(_signal_audit_price_lookup)


async def _run_signal_audit() -> list[dict]:
    """Audit semua sinyal OPEN, kembalikan yang BARU selesai. Dipakai
    bersama oleh /api/signals (dipicu user membuka halaman Audit Sinyal)
    DAN oleh siklus otomatis berkala (_run_signal_auto_cycle) -- satu
    sumber logic, tidak ada duplikasi antara jalur manual dan jalur
    background."""
    from core.signal_history import audit_open_signals

    return await audit_open_signals(_signal_audit_price_lookup)


# Interval siklus auto-audit background (detik) -- default 600 (10 menit),
# meniru cadence kompetitor yang jadi rujukan user. Bisa diubah lewat env
# var tanpa redeploy kode kalau perlu diperlambat/dipercepat.
SIGNAL_AUTO_INTERVAL_SECONDS = int(os.getenv("SIGNAL_AUTO_INTERVAL_SECONDS", "600"))


async def _run_signal_auto_cycle():
    """Satu putaran auto-audit: (1) refresh Top Pick -- otomatis mencatat
    sinyal baru (logic ada di dalam confidence(), dipanggil LANGSUNG
    sebagai fungsi biasa, pola yang sama dipakai /api/insight/{kode}
    memanggil ihsg()); (2) scan & catat anomali Smart Money (source
    ketiga, reuse items confidence() yang SAMA utk TP/SL/likuiditas --
    lihat _record_smart_money_cycle); (3) audit semua sinyal OPEN utk
    yang baru selesai; (4) catat snapshot harian (permintaan user: "track
    sinyalnya, besok yg lanjut naik apa yg turun apa" -- lihat
    record_daily_snapshots, idempotent per hari jadi aman dipanggil tiap
    10 menit). Dipisah dari loop-nya sendiri (bukan langsung di dalam
    while True) supaya SATU putaran bisa dipanggil & ditest langsung
    tanpa perlu menunggu interval sungguhan."""
    confidence_items = []
    try:
        confidence_result = await confidence()
        confidence_items = confidence_result.get("items", [])
    except Exception as e:
        print(f"⚠️ auto-cycle: gagal refresh Top Pick: {type(e).__name__}: {e}")
    try:
        await _record_smart_money_cycle(confidence_items)
    except Exception as e:
        print(f"⚠️ auto-cycle: gagal catat Smart Money: {type(e).__name__}: {e}")
    try:
        await _run_pending_entry_audit()
    except Exception as e:
        print(f"⚠️ auto-cycle: gagal audit pending-entry: {type(e).__name__}: {e}")
    try:
        await _run_signal_audit()
    except Exception as e:
        print(f"⚠️ auto-cycle: gagal audit sinyal: {type(e).__name__}: {e}")
    try:
        from core.signal_history import record_daily_snapshots
        await record_daily_snapshots(_signal_entry_price_lookup)
    except Exception as e:
        print(f"⚠️ auto-cycle: gagal catat snapshot harian: {type(e).__name__}: {e}")


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

    from core.screening_pro import _score_minervini, calculate_confluence, detect_patterns

    ihsg_raw = await _clean("^JKSE", period="1y")
    market_close = ihsg_raw["Close"] if ihsg_raw is not None and len(ihsg_raw) else None

    shares = _load_shares()
    # Universe DIPERLUAS (permintaan user: "di top pick tambahin jgn cuman
    # lq45") dari SCREENER_UNIVERSE (~45, LQ45-ish) ke LIQUID_250 (178
    # saham likuid, SUDAH dipakai fitur lain scope='medium' di scale yang
    # sama -- lihat async_download_many, batching+retry sudah teruji utk
    # ~200 ticker). SCREENER_UNIVERSE ⊂ LIQUID_250 penuh, jadi fitur lain
    # yang masih pakai SCREENER_UNIVERSE (Screener default, Smart Money
    # scanner _SM_UNIVERSE, Backtest, dst) TIDAK terpengaruh -- join-nya
    # (_record_smart_money_cycle) tetap valid krn cuma superset, bukan
    # ganti universe. record_top_picks() di confidence() tetap MAX_
    # RECORDED_PER_DAY=10/hari, jadi Audit Sinyal tidak dibanjiri meski
    # kandidat yang di-scan sekarang jauh lebih banyak.
    tickers = [t + ".JK" for t in LIQUID_250]
    data = await async_download_many(tickers, period="1y", interval="1d")
    data = {t: fix_yf_columns(d).apply(pd.to_numeric, errors="coerce").dropna() for t, d in data.items()}
    # Tambal celah bar harian terbaru (lihat _backfill_recent_gap) -- SATU
    # panggilan batch tambahan utk semua ticker, bukan N panggilan per-
    # ticker (lihat _backfill_recent_gap_batch).
    data = await _backfill_recent_gap_batch(data)

    items = []
    for ticker, df in data.items():
        kode = ticker.replace(".JK", "")
        try:
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
            # REVISI KEDUA (permintaan user langsung: "kamu jadi analyst,
            # nentuin entrinya dimana, nanti tinggal liat kena entry yg
            # disaranin apa engga"): versi SEBELUM ini pakai get_hit_
            # scenarios() utk klaim entry "sudah kena HARI INI" -- itu
            # BUG NYATA yang baru ketemu (kasus ARTO 2026-07-09, entry
            # Rp953 yang tidak nyambung sama sekali dgn histori harga
            # sungguhan): sinyal baru DICATAT hari ini, jadi mengklaim
            # entry di harga pullback yang sudah "kena" HARI YANG SAMA
            # sama saja mengklaim trader bisa mundur waktu ke harga yang
            # sudah lewat sebelum sinyalnya sendiri ada. Sekarang SELALU
            # pakai skenario 'pullback' (S1) sbg REKOMENDASI (bukan klaim
            # sudah terjadi) -- record_top_picks() menyimpannya sbg status
            # PENDING_ENTRY, lalu audit_pending_entries() (core/signal_
            # history.py) yang menentukan kapan (kalau pernah) level ini
            # BENERAN tersentuh ke depannya, sebelum TP/SL mulai berlaku.
            # REVISI KETIGA (permintaan user langsung: "skenario nya antara
            # pullback atau breakout aja tapi valid soalnya kalo pullback
            # kadang ga kena yg ada malah kena tp") -- pullback SELALU
            # dipakai apa adanya kadang tidak realistis: kalau saham SEDANG
            # breakout momentum (harga tembus R1 dgn volume), harga jarang
            # mundur lagi ke S1 -- sinyal berakhir EXPIRED_NO_ENTRY padahal
            # harga sudah lanjut jalan (bahkan sempat menyentuh level yang
            # SEHARUSNYA jadi TP kalau entry-nya breakout, bukan pullback).
            # calculate_fixed_entry_levels_from_df() sekarang menentukan
            # recommended_scenario ('breakout' vs 'pullback') sendiri
            # berdasar is_breakout (harga > R1) + volume_confirmation (vol >
            # 1.3x rata2 20 hari) -- lihat catatan lengkap di situ. Fallback
            # ke 'normal' kalau skenario yang direkomendasikan entah kenapa
            # tidak ada (harusnya nyaris tidak pernah -- _determine_entry_
            # points selalu punya fallback sintetis).
            from core.trading_plan import calculate_fixed_entry_levels_from_df
            plan = calculate_fixed_entry_levels_from_df(df, "")
            scenarios = (plan or {}).get("scenarios") or {}
            recommended_key = (plan or {}).get("recommended_scenario", "pullback")
            chosen = scenarios.get(recommended_key) or scenarios.get("pullback") or scenarios.get("normal")
            potensi_naik_pct = chosen["tp1_pct"] if chosen else None
            risiko_turun_pct = chosen["risk_pct"] if chosen else None
            # TP2/TP3 (permintaan user: "kena tp1 tandai, lanjut ke tp
            # selanjutnya") -- SUDAH dihitung _calc_entry_levels sbg bagian
            # dari skenario yang sama (tp2=tp1x2, tp3=tp1x3), cuma belum
            # pernah diekstrak/disimpan sebelum ini.
            tp2_pct_val = chosen["tp2_pct"] if chosen else None
            tp3_pct_val = chosen["tp3_pct"] if chosen else None
            # Entry level REKOMENDASI (skenario pullback/S1), dipakai
            # belakangan utk pencatatan signal_history (status PENDING_
            # ENTRY) supaya entry_price konsisten dgn skenario tp_pct/
            # sl_pct yang dipilih -- BEDA dari "harga" di bawah (harga
            # pasar berjalan saat ini, tetap dipakai apa adanya utk
            # tampilan tabel Top Pick).
            entry_price_signal = chosen["entry"] if chosen else None
            rr_ratio = (potensi_naik_pct / risiko_turun_pct
                        if potensi_naik_pct and risiko_turun_pct and risiko_turun_pct > 0 else None)
            ad = calculate_ad_line(df, is_illiquid=likuiditas in ("Kurang Likuid", "Tidak Likuid"))
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

            items.append({
                "kode": kode,
                "harga": price,
                "entry_price": entry_price_signal,
                "sektor": SECTOR_MAP_UNIVERSE.get(kode, "Lainnya"),
                "market_cap": market_cap,
                "ai_score": ai["score"],
                "ai_rating": ai["rating"],
                "ringkasan_teknikal": _ringkasan_sinyal_teknikal(ai),
                "minervini_score": mv["skor"],
                "minervini_criteria_met": mv["criteria_met"],
                "confluence_bullish": cf["bullish"],
                "confluence_bearish": cf["bearish"],
                "likuiditas": likuiditas,
                "avg_value_20": round(avg_value_20, 0),
                "potensi_naik_pct": round(potensi_naik_pct, 2) if potensi_naik_pct is not None else None,
                "risiko_turun_pct": round(risiko_turun_pct, 2) if risiko_turun_pct is not None else None,
                "tp2_pct": round(tp2_pct_val, 2) if tp2_pct_val is not None else None,
                "tp3_pct": round(tp3_pct_val, 2) if tp3_pct_val is not None else None,
                "rr_ratio": round(rr_ratio, 2) if rr_ratio is not None else None,
                "bandar": None if not ad else {"label": ad["label"], "sinyal": ad["sinyal"], "confidence": ad["confidence"]},
                "pattern": pattern_name,
                "pattern_bias": pattern_bias,
            })
        except Exception:
            continue

    # ===== FUNDAMENTAL (permintaan user) =====
    # SENGAJA BUKAN komponen skor berbobot (percobaan awal sempat membuat
    # ini bobot tetap, tapi user koreksi: saham IDX kadang naik/turun
    # TIDAK terlalu dipengaruhi fundamental -- menjadikannya bobot tetap
    # bisa menyeret skor saham yang teknikalnya kuat tapi kebetulan
    # "Overvalued" secara valuasi, padahal itu belum tentu relevan dgn
    # pergerakan harga jangka pendek di IDX). Diperlakukan SAMA seperti
    # proxy bandar & kepemilikan di bawah: kontekstual di reasons/warnings
    # kalau valuasinya jelas Undervalued/Overvalued, TIDAK memengaruhi
    # confidence_score sama sekali.
    # Fetch SEMUA saham SEKALIGUS secara concurrent (bukan di dalam loop
    # utama di atas, yang sengaja sinkron murni tanpa I/O per-iterasi) --
    # supaya waktu tunggu total tidak bertambah linear per saham.
    # fetch_fundamental() sendiri sudah cache 7 hari (lihat core/
    # fundamental.py), jadi setelah run pertama nyaris instan.
    try:
        from core.fundamental import fetch_fundamental
        fund_results = await asyncio.gather(
            *[fetch_fundamental(it["kode"] + ".JK") for it in items],
            return_exceptions=True,
        )
        for it, fund in zip(items, fund_results):
            if isinstance(fund, Exception) or not fund:
                it["fund_verdict"] = None
                it["fund_upside_pct"] = None
                continue
            val = _valuation(fund)
            it["fund_verdict"] = val.get("verdict")
            it["fund_upside_pct"] = _fundamental_median_upside_pct(val)
    except Exception as e:
        print(f"⚠️ Gagal fetch fundamental utk Top Pick: {type(e).__name__}: {e}")
        for it in items:
            it.setdefault("fund_verdict", None)
            it.setdefault("fund_upside_pct", None)

    # ===== KEPEMILIKAN (X-15, permintaan user) =====
    # SENGAJA BUKAN komponen skor berbobot (beda dengan fundamental di
    # atas) -- filing kepemilikan substansial adalah EVENT LANGKA, mayoritas
    # dari 45 saham universe TIDAK akan punya filing baru di hari mana pun
    # (dikonfirmasi lewat pengecekan manual sebelum implementasi: dari 7
    # hari filing, cuma segelintir yang kena saham di universe ini).
    # Memberi bobot tetap ke sinyal sesparse ini akan membuat sebagian
    # besar saham dapat nilai "netral" secara default yang mengencerkan
    # komponen lain, tanpa menambah daya beda nyata. Jadi diperlakukan SAMA
    # seperti proxy bandar: kontekstual di reasons/warnings kalau KEBETULAN
    # ada filing, bukan bagian rumus. Dibatasi 4 hari terakhir + timeout,
    # supaya kalau IDX lambat/down, Top Pick tetap selesai dihitung.
    try:
        x15_batches = await asyncio.wait_for(
            asyncio.gather(*[_fetch_x15_today(days_back=d) for d in range(4)], return_exceptions=True),
            timeout=25.0,
        )
        x15_by_kode: dict[str, float] = {}
        for batch in x15_batches:
            if isinstance(batch, Exception):
                continue
            substansial = [x for x in batch if x["pct_setelah"] >= 5.0 or x["pct_sebelum"] >= 5.0 or x["pengendali"]]
            for x in substansial:
                x15_by_kode[x["kode"]] = x15_by_kode.get(x["kode"], 0.0) + x["perubahan"]
        for it in items:
            it["kepemilikan_change_pct"] = round(x15_by_kode[it["kode"]], 3) if it["kode"] in x15_by_kode else None
    except Exception as e:
        print(f"⚠️ Gagal fetch X-15 utk Top Pick: {type(e).__name__}: {e}")
        for it in items:
            it.setdefault("kepemilikan_change_pct", None)

    # TTL LEBIH PANJANG dari _CACHE_TTL default (300s) -- SENGAJA, ditemukan
    # lewat pengukuran latency live setelah universe diperluas ke LIQUID_250
    # (178 saham, sebelumnya SCREENER_UNIVERSE ~45): compute dingin sekarang
    # ~44 detik (diverifikasi langsung), sedangkan auto-cycle background
    # (_run_signal_auto_cycle, lihat SIGNAL_AUTO_INTERVAL_SECONDS=600s) yang
    # SEHARUSNYA menjaga cache tetap hangat cuma jalan tiap 10 menit -- kalau
    # TTL cache tetap 300s (5 menit), ada jendela 5 menit tiap siklus di
    # mana cache SUDAH kadaluarsa tapi auto-cycle BELUM refresh lagi, jadi
    # user pertama yang buka Top Pick di jendela itu kena compute dingin
    # penuh 44 detik. TTL 900s (>600s interval auto-cycle + jeda aman) --
    # cache SELALU sempat di-refresh auto-cycle sebelum kadaluarsa, user
    # nyaris tidak pernah kena compute dingin lagi di luar restart server.
    _cache_set("confidence:raw", items, ttl=900)
    return items


def _confidence_weights() -> tuple[dict, str]:
    """Bobot gabungan untuk Skor Keyakinan (AI Score + Minervini +
    Confluence + Likuiditas + Risk/Reward). Versi web memakai bobot tetap
    (tanpa personalisasi per-akun). Fundamental & kepemilikan SENGAJA
    tidak ikut bobot -- lihat catatan lengkap di _confidence_raw_signals
    (permintaan user: saham IDX kadang naik/turun tidak terlalu
    dipengaruhi fundamental, jadi diperlakukan kontekstual di reasons/
    warnings saja, bukan komponen skor)."""
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
    # PERNAH menggagalkan respons Top Pick itu sendiri.
    try:
        from core.signal_history import record_top_picks

        await record_top_picks(items, price_lookup=_signal_entry_price_lookup)
    except Exception as e:
        print(f"⚠️ Gagal mencatat signal history (Top Pick): {type(e).__name__}: {e}")

    # Entry point MACD Histogram Cross DIHAPUS (permintaan user -- terlalu
    # banyak entry yang tumpang tindih dengan Top Pick/Smart Money, bikin
    # Audit Sinyal ramai tanpa menambah kejelasan). record_macd_cross_
    # signals() masih ada di core/signal_history.py tapi sudah tidak
    # dipanggil dari sini -- baris MACD_CROSS lama di riwayat tetap
    # dibiarkan menyelesaikan siklusnya sendiri (TP_HIT/SL_HIT/EXPIRED),
    # tidak dihapus paksa dari database.

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
        "universe": len(LIQUID_250),
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
        await _run_pending_entry_audit()
    except Exception as e:
        print(f"⚠️ Gagal audit pending-entry: {type(e).__name__}: {e}")
    try:
        await _run_signal_audit()
    except Exception as e:
        print(f"⚠️ Gagal audit signal history: {type(e).__name__}: {e}")

    report = await asyncio.to_thread(get_signal_report)

    # Floating P&L utk sinyal yang MASIH OPEN (permintaan user: "liatkan
    # floatingnya juga", lalu dikoreksi lagi: "maksudnya ga harga real
    # time" -- floating HARUS mencerminkan harga SEKARANG, bukan closing
    # harian yang bisa basi) -- get_signal_report() sendiri murni baca DB
    # (sengaja tanpa I/O jaringan supaya gampang ditest), jadi pengayaan
    # harga live dilakukan DI SINI (lapisan endpoint), bukan di dalam
    # get_signal_report().
    #
    # SENGAJA pakai _signal_entry_price_lookup (fast_info/real-time quote,
    # SAMA yang dipakai saat entry BARU dicatat), BUKAN _signal_audit_
    # price_lookup (basis closing harian dgn staleness guard, dipakai
    # audit_open_signals() utk keputusan TP/SL) -- keduanya punya tujuan
    # BEDA: audit butuh bar harian yang SUDAH final (hindari noise
    # intraday/lookahead), floating P&L justru harus "kalau ditutup
    # SEKARANG nilainya berapa", jadi butuh kutipan SEPALING BARU yang ada
    # (ditemukan nyata: bar harian yfinance utk hari terbaru kadang masih
    # NaN/belum terbit, sementara fast_info.last_price tetap mencerminkan
    # kutipan terkini walau bar harian belum final).
    open_signals = [s for s in report.get("signals", []) if s.get("status") == "OPEN"]
    if open_signals:
        prices = await asyncio.gather(
            *[_signal_entry_price_lookup(s["kode"]) for s in open_signals],
            return_exceptions=True,
        )
        for sig, price in zip(open_signals, prices):
            if isinstance(price, Exception) or not price:
                continue
            entry = sig["entry_price"]
            is_sell = sig.get("direction") == "SELL"
            floating_pct = (entry / price - 1) * 100 if is_sell else (price / entry - 1) * 100
            sig["floating_price"] = round(price, 2)
            sig["floating_return_pct"] = round(floating_pct, 2)

    # "Jarak ke entry" utk PENDING_ENTRY (migrasi ke-16) -- sama semangat
    # dgn floating P&L di atas, tapi maknanya beda: ini BUKAN untung/rugi
    # (belum ada posisi), murni "harga sekarang segini, entry yang
    # disarankan segini, tinggal berapa % lagi turun supaya kena". Reuse
    # lookup live yang SAMA (bukan basis harian) -- alasan identik dgn di
    # atas.
    pending_signals = [s for s in report.get("signals", []) if s.get("status") == "PENDING_ENTRY"]
    if pending_signals:
        prices = await asyncio.gather(
            *[_signal_entry_price_lookup(s["kode"]) for s in pending_signals],
            return_exceptions=True,
        )
        for sig, price in zip(pending_signals, prices):
            if isinstance(price, Exception) or not price:
                continue
            entry = sig["entry_price"]
            sig["current_price"] = round(price, 2)
            sig["distance_to_entry_pct"] = round((price / entry - 1) * 100, 2)

    return _py(report)


@app.get("/api/signals/riwayat-harian")
async def api_signals_riwayat_harian(tanggal: str | None = None):
    """Riwayat HARIAN Audit Sinyal -- permintaan user langsung: "track
    sinyalnya, hari ini wr berapa loss berapa yg berjalan apa aja,
    besoknya yg lanjut naik apa yg turun apa, sama di riwayat ada tombol
    tanggal jadi bisa liat riwayat wr signal". tanggal opsional
    ('YYYY-MM-DD', default hari ini).

    Memicu record_daily_snapshots() dulu (idempotent per hari, SAMA pola
    dgn /api/signals memicu audit) supaya snapshot HARI INI selalu ada
    saat endpoint ini dibuka, tidak menunggu siklus background 10 menit --
    TAPI HANYA kalau tanggal yang diminta adalah HARI INI (atau tidak
    diisi). REVISI: sebelumnya dipanggil UNCONDITIONAL di setiap request,
    termasuk saat date-picker di frontend browsing ke tanggal LAMPAU --
    itu SIA-SIA (snapshot HARI INI tidak relevan utk recap tanggal lain)
    dan BOROS (record_daily_snapshots melakukan real-time price lookup
    sama lambatnya dgn /api/signals, ~detikan per sinyal OPEN x puluhan
    sinyal) -- ketauan dari trace Playwright: klik date-picker ke tanggal
    lampau tetap makan puluhan detik, padahal seharusnya cuma query
    SQLite biasa (cepat) krn tidak perlu snapshot baru sama sekali."""
    from datetime import datetime as _dt
    from core.signal_history import get_daily_recap, record_daily_snapshots

    if tanggal is None or tanggal == _dt.now().strftime("%Y-%m-%d"):
        try:
            await record_daily_snapshots(_signal_entry_price_lookup)
        except Exception as e:
            print(f"⚠️ Gagal catat snapshot harian: {type(e).__name__}: {e}")

    recap = await asyncio.to_thread(get_daily_recap, tanggal)
    return _py(recap)


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

    cleaned = {}
    for t in tickers:
        df = data.get(t) if isinstance(data, dict) else None
        if df is None:
            continue
        try:
            cleaned[t] = fix_yf_columns(df).apply(pd.to_numeric, errors="coerce").dropna()
        except Exception:
            continue
    # Tambal celah bar harian terbaru (lihat _backfill_recent_gap) -- endpoint
    # ini jalur fetch KETIGA yang terpisah dari _clean()/_confidence_raw_
    # signals() dan sama-sama kena bug yang sama (price/change_1d di sini
    # dihitung langsung dari Close baris terakhir, jadi kalau baris itu
    # hilang/basi, harga & % perubahan yang ditampilkan ikut basi juga --
    # inilah kenapa marquee/Top Movers/Pasar keliatan "macet" walau
    # cache sisi klien sudah diperbaiki).
    cleaned = await _backfill_recent_gap_batch(cleaned)

    items = []
    for t in tickers:
        kode = t.replace(".JK", "")
        df = cleaned.get(t)
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
async def averagedown(kode: str, avg_price: float, lots: int, add_lots: int = 0, target_price: float | None = None):
    """Kalkulator Average Down: harga rata-rata baru + P/L kalau nambah
    lot. Konteks fundamental (undervalued/overvalued, reuse _valuation()
    yang sama dipakai /api/fundamental) ditambahkan best-effort -- kalau
    fetch fundamental gagal/data tidak cukup, kalkulasi murninya tetap
    dikembalikan tanpa konteks itu.

    target_price (opsional): permintaan eksplisit user -- kalkulasi
    utama (dan verdict fundamental) HARUS bisa dihitung di harga yang
    BENAR-BENAR mau dia pakai untuk beli (mis. limit order di bawah
    harga sekarang), BUKAN dipaksa selalu pakai harga live sekarang.
    Kalau tidak diisi, fallback ke harga sekarang (perilaku lama).
    current_price (harga live, dipakai buat filter suggestions) TETAP
    dikembalikan terpisah supaya user bisa lihat keduanya.

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
    buy_price = target_price if target_price and target_price > 0 else current_price

    res = calculate_average_down(avg_price, lots, buy_price, add_lots)
    if not res:
        raise HTTPException(422, "Input tidak valid (cek harga rata-rata, lot dipegang, dan tambahan lot).")
    # calculate_average_down() sendiri menamai parameter harganya
    # 'current_price' (dipakai di banyak tempat lain sebagai "harga saat
    # beli") -- di sini itu SEBENARNYA buy_price (bisa target_price
    # custom), jadi disimpan eksplisit sebagai 'buy_price' dulu SEBELUM
    # 'current_price' ditimpa dengan harga live sungguhan, supaya kedua
    # angka tetap kebaca jelas & tidak ada yang hilang.
    res["buy_price"] = res["current_price"]
    res["current_price"] = round(current_price, 2)
    res["is_custom_target"] = bool(target_price and target_price > 0)

    suggestions = []
    fv_lo = fv_hi = None  # rentang wajar, None kalau fetch fundamental gagal/tidak cukup data

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
            fv_lo, fv_hi = val.get("range_low"), val.get("range_high")
            if val.get("mid"):
                res["fair_value_mid"] = val["mid"]
                res["fair_value_verdict"] = _verdict_for_price(buy_price, fv_lo, fv_hi)
            if fv_lo and 0 < fv_lo < current_price:
                calc = calculate_average_down(avg_price, lots, fv_lo, add_lots)
                if calc:
                    suggestions.append({"label": "Estimasi Wajar Terendah (Floor)", "price": fv_lo, **calc})
    except Exception:
        pass

    # Verdict per level referensi -- None kalau valuasi fundamental gagal
    # diambil (fv_lo/fv_hi tetap None), bukan dipaksa nebak.
    for s in suggestions:
        s["verdict"] = _verdict_for_price(s["price"], fv_lo, fv_hi)

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


@app.get("/api/whymove/{kode}")
async def whymove(kode: str):
    """'Kenapa saham ini naik/turun hari ini' -- merangkai beberapa
    sinyal yang SUDAH ada & teruji (volume hari ini, proxy tekanan
    beli/jual, momentum yang baru terpicu, level harga yang baru
    ditembus, berita terbaru yang menyebut saham ini) jadi satu ringkasan
    tentang HARI INI spesifik -- BUKAN modul baru dari nol.

    PRINSIP JUJUR (sama seperti core/news_signal.py): SEMUA faktor di
    sini adalah KORELASI WAKTU (kebetulan terjadi di hari yang sama),
    BUKAN klaim sebab-akibat. Kalau ada berita DAN harga bergerak di hari
    yang sama, itu ditampilkan BERSAMPINGAN sebagai dua fakta terpisah --
    TIDAK PERNAH diklaim "berita X menyebabkan harga naik", karena itu
    tidak pernah bisa dibuktikan hanya dari data harga+berita."""
    ticker = _resolve_ticker(kode)
    try:
        df = await _clean(ticker)
    except Exception:
        raise HTTPException(502, "Gagal mengambil data harga.")
    if df is None or len(df) < 51:
        raise HTTPException(404, "Data tidak cukup.")

    price_now = float(df["Close"].iloc[-1])
    price_prev = float(df["Close"].iloc[-2])
    change_pct = round((price_now / price_prev - 1) * 100, 2)

    from core.volume_patterns import detect_volume_spikes, calculate_ad_line
    from core.screening_pro import detect_patterns
    from core.indicators import calculate_support_resistance_deep

    factors = []

    # 1. Volume HARI INI (lookback_days=1 -> baris terakhir df persis)
    try:
        vs = detect_volume_spikes(df, lookback_days=1)
        spike = vs["spikes"][0] if vs["spikes"] else None
        if spike:
            factors.append({
                "kategori": "Volume",
                "teks": f"Volume hari ini {spike['vol_ratio']:.1f}x rata-rata 20 hari -- {spike['arah']}",
            })
        else:
            factors.append({
                "kategori": "Volume",
                "teks": "Volume hari ini tidak jauh berbeda dari rata-rata 20 hari (tidak ada lonjakan).",
            })
    except Exception:
        pass

    # 2. Proxy tekanan beli/jual HARI INI (CLV -- posisi close dalam
    # rentang high-low candle terakhir, bagian dari Chaikin A/D Line)
    try:
        ad = calculate_ad_line(df)
        if ad:
            factors.append({
                "kategori": "Tekanan Beli/Jual",
                "teks": f"Penutupan hari ini {ad['clv_label']} (posisi close dalam rentang high-low hari ini).",
            })
    except Exception:
        pass

    # 3. Momentum yang BARU terpicu HARI INI -- HANYA MACD Histogram
    # Cross (pola struktur seperti Double Top/HH-LL SENGAJA tidak
    # dimasukkan di sini karena itu kondisi yang sudah berlangsung lama,
    # bukan sesuatu yang "terjadi hari ini" spesifik).
    try:
        pattern_result = detect_patterns(df, kode)
        macd_today = next(
            (p for p in pattern_result.get("patterns", []) if p["nama"].startswith("MACD HISTOGRAM")), None
        )
        if macd_today:
            factors.append({"kategori": "Momentum", "teks": macd_today["desc"]})
    except Exception:
        pass

    # 4. Level harga yang BARU ditembus hari ini -- S/R dihitung dari data
    # SEBELUM hari ini (df tanpa baris terakhir), supaya perbandingan
    # "tembus hari ini" tidak bocor pakai harga hari ini sendiri.
    try:
        df_before_today = df.iloc[:-1]
        if len(df_before_today) >= 50:
            sr = calculate_support_resistance_deep(df_before_today)
            if price_now > sr["R1"] and price_prev <= sr["R1"]:
                factors.append({
                    "kategori": "Level Harga",
                    "teks": f"Harga menembus ke atas resistance R1 (Rp{sr['R1']:,.0f}) hari ini.",
                })
            elif price_now < sr["S1"] and price_prev >= sr["S1"]:
                factors.append({
                    "kategori": "Level Harga",
                    "teks": f"Harga menembus ke bawah support S1 (Rp{sr['S1']:,.0f}) hari ini.",
                })
    except Exception:
        pass

    # 5. Berita TERBARU yang menyebut saham ini -- ditampilkan APA
    # ADANYA dengan tanggal terbit asli, BUKAN difilter ketat ke "2 hari
    # terakhir" (saham yang jarang diliput bisa jadi tidak akan pernah
    # muncul kalau filternya terlalu ketat) -- user sendiri yang menilai
    # relevansi dari tanggalnya.
    news_items = []
    try:
        from datetime import datetime as _dt, timezone as _tz
        from core.news import fetch_news, _parse_pub_date
        raw_news = await fetch_news(keyword=kode, limit=3)
        if raw_news:
            now_utc = _dt.now(_tz.utc)
            for n in raw_news:
                parsed = _parse_pub_date(n.get("pub_date", ""))
                is_recent = bool(parsed and (now_utc - parsed).days <= 2)
                news_items.append({
                    "title": n.get("title"), "source": n.get("source"),
                    "link": n.get("link"), "pub_date": n.get("pub_date"),
                    "is_recent": is_recent,
                })
    except Exception as e:
        print(f"⚠️ Gagal fetch berita utk whymove {kode}: {type(e).__name__}: {e}")

    return _py({
        "kode": kode, "price": price_now, "change_pct": change_pct,
        "factors": factors, "news": news_items,
    })


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


def _verdict_for_price(price: float | None, lo: float | None, hi: float | None) -> str | None:
    """Verdict Undervalued/Overvalued/Wajar di HARGA MANAPUN yang diberikan
    (bukan cuma harga sekarang) -- dipisah dari _valuation() supaya bisa
    dipakai ulang utk mengevaluasi harga rencana beli user sendiri (mis. di
    Kalkulator Average Down) terhadap rentang wajar yang SAMA, tanpa
    menghitung ulang seluruh metode valuasi."""
    if not (price and lo and hi):
        return None
    if price < lo * 0.9:
        return "Undervalued"
    if price > hi * 1.1:
        return "Overvalued"
    return "Wajar (dalam rentang)"


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
        if not (val and val > 0):
            return
        # Sanity guard: metode yang hasilnya <5% atau >2000% dari harga
        # sekarang HAMPIR PASTI karena field fundamental yang korup/salah
        # skala di sumber data (ditemukan nyata: BVPS Yahoo Finance utk
        # TPIA = Rp0.045, bikin PBV×2 & ROE-implied menghasilkan "harga
        # wajar" Rp0.09/Rp0.16 utk saham dengan EPS positif Rp378 -- laba
        # positif tidak mungkin genuinely wajar dihargai mendekati nol).
        # Ini BUKAN menyembunyikan valuasi ekstrem yang sah (deep value/
        # growth tetap lolos di rentang 0.05x-20x), cuma menolak angka
        # yang jelas-jelas artefak data, bukan sinyal.
        if price and price > 0 and not (price * 0.05 <= val <= price * 20):
            return
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
            "verdict": _verdict_for_price(price, lo, hi),
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


@app.get("/api/screenerfundamental")
async def screener_fundamental():
    """Screening berbasis valuasi FUNDAMENTAL murni (PER, PBV, ROE,
    Dividend Yield, estimasi harga wajar) atas SCREENER_UNIVERSE --
    SENGAJA TERPISAH dari Top Pick/Skor Keyakinan (yang tetap 100%
    teknikal, permintaan eksplisit user: saham IDX kadang naik/turun
    tidak terlalu dipengaruhi fundamental, jadi jangan dicampur jadi satu
    skor). Ini utk yang MEMANG mau screening dari sisi fundamental saja.

    Cakupan dibatasi ke SCREENER_UNIVERSE (~45, BUKAN opsi ~200/793 SEMUA
    IDX seperti Screener teknikal) -- fetch fundamental per saham lewat
    yfinance .info jauh lebih lambat/kurang reliable drpd data harga OHLCV,
    memperluas cakupan akan bikin waktu tunggu & risiko gagal parsial naik
    signifikan tanpa manfaat sepadan utk versi pertama fitur ini."""
    cached = _cache_get("screenerfundamental")
    if cached is not None:
        return cached

    from core.fundamental import fetch_fundamental
    fund_results = await asyncio.gather(
        *[fetch_fundamental(kode + ".JK") for kode in SCREENER_UNIVERSE],
        return_exceptions=True,
    )

    items = []
    for kode, fund in zip(SCREENER_UNIVERSE, fund_results):
        if isinstance(fund, Exception) or not fund:
            continue
        val = _valuation(fund)
        if not val.get("methods"):
            continue  # tidak cukup data (EPS/BVPS dsb) utk estimasi harga wajar sama sekali
        upside = _fundamental_median_upside_pct(val)
        items.append({
            "kode": kode,
            "sektor": SECTOR_MAP_UNIVERSE.get(kode, "Lainnya"),
            "harga": val.get("price"),
            "pe_trailing": fund.get("pe_trailing"),
            "pbv": fund.get("pbv"),
            "roe_pct": fund.get("roe_pct"),
            "dividend_yield_pct": fund.get("dividend_yield_pct"),
            "verdict": val.get("verdict"),
            "upside_pct": upside,
            "upside_display": _display_pct_capped(upside) if upside is not None else None,
            "fair_value_mid": val.get("mid"),
            "n_methods": len(val.get("methods") or {}),
        })

    # Undervalued dulu, lalu diurutkan dari upside (median) tertinggi --
    # BUKAN skor gabungan (sengaja terpisah dari Top Pick, lihat docstring).
    _verdict_rank = {"Undervalued": 0, "Wajar (dalam rentang)": 1, "Overvalued": 2}
    items.sort(key=lambda x: (_verdict_rank.get(x["verdict"], 3), -(x["upside_pct"] if x["upside_pct"] is not None else -999)))

    payload = _py({"items": items, "universe": len(SCREENER_UNIVERSE)})
    _cache_set("screenerfundamental", payload)
    return payload


_MACRO_TICKERS = {
    # Kurs -- icon dipakai sbg kode ticker singkat (teks polos), BUKAN emoji
    # flag/pictogram: emoji flag (regional indicator) tidak render sbg
    # bendera sungguhan di banyak font Windows (jadi teks 2-huruf acak),
    # dan emoji lain (medali, tong minyak, dst) tampil belang dgn sistem
    # ikon SVG custom yang sudah dipakai di seluruh halaman lain -- sama
    # kelas masalah dgn sweep ikon Screener/Audit Sinyal, ketemu belakangan
    # krn halaman Makro tidak ikut ter-render saat sweep awal dilakukan.
    # icon dikosongkan utk kurs -- label ("USD / IDR") sendiri SUDAH berupa
    # kode, kasih prefix kode lagi cuma bikin duplikat ("USD USD / IDR").
    "USDIDR=X": {"label": "USD / IDR",    "cat": "kurs",      "unit": "IDR",       "icon": ""},
    "EURIDR=X": {"label": "EUR / IDR",    "cat": "kurs",      "unit": "IDR",       "icon": ""},
    "JPYIDR=X": {"label": "JPY / IDR",    "cat": "kurs",      "unit": "IDR",       "icon": ""},
    "CNHIDR=X": {"label": "CNY / IDR",    "cat": "kurs",      "unit": "IDR",       "icon": ""},
    # Energi & Logam — CME/COMEX, batch-compatible
    "GC=F":     {"label": "Emas",         "cat": "komoditas", "unit": "USD/oz",    "icon": "XAU"},
    "SI=F":     {"label": "Perak",        "cat": "komoditas", "unit": "USD/oz",    "icon": "XAG"},
    "HG=F":     {"label": "Tembaga",      "cat": "komoditas", "unit": "USD/lb",    "icon": "CU"},
    "CL=F":     {"label": "Minyak WTI",   "cat": "komoditas", "unit": "USD/bbl",   "icon": "WTI"},
    "BZ=F":     {"label": "Minyak Brent", "cat": "komoditas", "unit": "USD/bbl",   "icon": "BRENT"},
    "NG=F":     {"label": "Gas Alam",     "cat": "komoditas", "unit": "USD/MMBtu", "icon": "NG"},
    # Nickel, CPO, Batu Bara — gunakan ETC London sebagai proxy (ICE/LME futures tidak tersedia di Yahoo)
    "NICL.L":   {"label": "Nickel",       "cat": "komoditas", "unit": "GBX/unit",  "icon": "NI"},
    "PALM.L":   {"label": "CPO",          "cat": "komoditas", "unit": "GBX/unit",  "icon": "CPO"},
    # Agri & Bahan Pokok — ICE/CBOT (KC=F/CC=F diambil individual karena batch gagal)
    "KC=F":     {"label": "Kopi Arabika", "cat": "agri",      "unit": "¢/lb",      "icon": "KC", "individual": True},
    "SB=F":     {"label": "Gula",         "cat": "agri",      "unit": "¢/lb",      "icon": "SB"},
    "CC=F":     {"label": "Kakao",        "cat": "agri",      "unit": "USD/t",     "icon": "CC", "individual": True},
    "ZC=F":     {"label": "Jagung",       "cat": "agri",      "unit": "¢/bu",      "icon": "CORN"},
    "ZS=F":     {"label": "Kedelai",      "cat": "agri",      "unit": "¢/bu",      "icon": "SOY"},
    "ZW=F":     {"label": "Gandum",       "cat": "agri",      "unit": "¢/bu",      "icon": "WHEAT"},
    "ZR=F":     {"label": "Beras",        "cat": "agri",      "unit": "USD/cwt",   "icon": "RICE"},
    "ZL=F":     {"label": "Minyak Sawit", "cat": "agri",      "unit": "¢/lb",      "icon": "PALM"},
    # Pasar Global
    "^GSPC":    {"label": "S&P 500",      "cat": "global",    "unit": "pts",       "icon": "SPX"},
    "^DJI":     {"label": "Dow Jones",    "cat": "global",    "unit": "pts",       "icon": "DJI"},
    "^IXIC":    {"label": "Nasdaq",       "cat": "global",    "unit": "pts",       "icon": "IXIC"},
    "^N225":    {"label": "Nikkei 225",   "cat": "global",    "unit": "pts",       "icon": "N225"},
    "^HSI":     {"label": "Hang Seng",    "cat": "global",    "unit": "pts",       "icon": "HSI"},
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
    "NICL.L":  {"naik": ["ANTM", "INCO", "MDKA"],                 "sektor": "Nickel / Mineral (proxy ETC)"},
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
    """Klasifikasi pola institusional berdasarkan volume + price action.

    chg1 & rsi SEKARANG benar-benar dipakai (BUG NYATA ditemukan lewat
    audit: dulu keduanya ada di signature tapi tak sekali pun dipakai di
    body -- saham yang hari itu SENDIRI ambruk tajam, atau RSI sudah
    sangat overbought/oversold, tetap bisa dilabeli "Agresif" hanya dari
    vol_ratio + tren 5 hari, padahal momentumnya sedang berbalik/jenuh).
    Sekarang keduanya jadi guard exhaustion/reversal: kondisi "Agresif"
    diturunkan ke versi biasa kalau ada tanda pembalikan/kejenuhan.

    chg1 JUGA dipakai sbg pembeda kategori "Breakout Volume" (lonjakan
    SATU hari) -- definisi lama (`chg5 > 5`) selalu jadi subset PENUH dari
    kondisi Akumulasi/Siluman di bawahnya, sehingga TIDAK PERNAH bisa
    tercapai (dead code, dibuktikan lewat pembuktian boolean lengkap saat
    audit, dan sudah jadi UI mismatch aktif -- legend menjanjikan kategori
    yang backend tidak pernah bisa kembalikan)."""
    high_vol = vol_ratio >= 1.8
    very_high = vol_ratio >= 2.5
    rising = chg5 > 1.5
    falling = chg5 < -1.5
    overbought = rsi is not None and rsi >= 80
    oversold = rsi is not None and rsi <= 20
    reversal_down = chg1 <= -3  # hari ini sendiri ambruk -- lawan arah tren naik 5 hari
    reversal_up = chg1 >= 3     # hari ini sendiri rebound -- lawan arah tren turun 5 hari

    if chg1 > 3 and vol_ratio >= 1.3:
        return "Breakout Volume"
    if very_high and rising:
        return "Akumulasi" if (reversal_down or overbought) else "Akumulasi Agresif"
    if high_vol and rising:
        return "Akumulasi"
    if very_high and falling:
        return "Distribusi" if (reversal_up or oversold) else "Distribusi Agresif"
    if high_vol and falling:
        return "Distribusi"
    if not high_vol and rising and chg5 > 3:
        return "Siluman (quiet buy)"
    return ""


# Minimum data historis (hari bursa) sebelum saham layak di-scan -- guard
# umur listing (BUG NYATA ditemukan lewat audit: saham IPO baru/baru lepas
# suspensi dengan baseline <20 hari menghasilkan vol_ratio yang tidak
# stabil/palsu, tidak ada guard ini sebelumnya). 45 (bukan ~60/3-bulan
# penuh) -- diverifikasi live: period="3mo" yfinance SETELAH filter
# Volume>0 konsisten menghasilkan ~58 hari trading utk saham likuid biasa
# (BUKAN 60+), jadi threshold 60 justru mengecualikan SEMUA saham lama
# sekalipun (ditemukan saat verifikasi live, BBCA pun ikut ter-skip).
# 45 memberi margin aman di bawah ~58 utk saham normal, sambil tetap jauh
# di atas kasus IPO super baru (biasanya <20-30 hari trading).
_SM_MIN_TRADING_DAYS = 45

# Gap kalender maksimum (hari) yang dianggap wajar antar candle berurutan
# dalam window yang dipakai -- weekend/libur pendek biasa cuma 1-4 hari;
# gap lebih besar mengindikasikan suspensi bursa. Tanpa guard ini, window
# vol_avg20/chg5 bisa diam-diam melompati suspensi berminggu-minggu,
# membandingkan harga SEBELUM vs SESUDAH suspensi tapi disajikan seolah
# tren 5 hari yang sungguhan (temuan audit, dikonfirmasi lewat trace kode).
_SM_MAX_GAP_DAYS = 10

# Toleransi (poin persentase) di bawah batas ARA/ARB resmi supaya tetap
# terdeteksi "kemungkinan ARA/ARB" walau harga penutupan tidak PERSIS di
# batas float (tick size/round-lot bikin harga jarang mendarat pas di
# angka batas, tapi mendekati batas itu sendiri sudah indikasi kuat hari
# itu limit-locked -- volume yg terjadi saat limit biasanya cuma order
# matching tipis di harga cap, BUKAN indikasi minat institusional genuine,
# temuan audit).
_ARA_ARB_MARGIN_PCT = 2.0


def _get_ara_arb_bands(price: float) -> tuple[float, float]:
    """Batas auto-reject BEI (ARA=batas atas, ARB=batas bawah) berdasar
    tier harga, sbg fraksi (0.20 = 20%).

    SUMBER (diverifikasi via web search Juli 2026, bukan diasumsikan dari
    training data lama): per revisi BEI/OJK 8 April 2025 --
    - ARA tetap bertingkat: 35% (Rp50-200), 25% (Rp200-5.000), 20% (>Rp5.000)
    - ARB SEKARANG FLAT 15% utk SEMUA tier harga (asimetris terhadap ARA;
      sebelumnya ARB juga bertingkat sama seperti ARA)
    (Kompas, CNBC Indonesia, Metro TV News, idx.co.id resmi -- konsisten
    lintas sumber utk detail ini.)

    KETERBATASAN YANG JUJUR DICATAT: BEI SERING merevisi ambang ini
    (ARB pernah 7%->10%->15% dalam periode singkat, ARA juga pernah
    direvisi di masa lalu) -- angka ini SNAPSHOT per pengamatan sesi ini,
    BUKAN jaminan berlaku selamanya. Kalau ternyata sudah berubah lagi,
    cukup update konstanta di fungsi ini, tidak perlu ubah logic lain."""
    if price < 200:
        ara = 0.35
    elif price < 5000:
        ara = 0.25
    else:
        ara = 0.20
    arb = 0.15  # flat semua tier, per revisi 8 April 2025
    return ara, arb


def _process_sm_df(kode: str, df_tr) -> dict | None:
    """Proses DataFrame hari-trading untuk deteksi anomali volume SM."""
    try:
        close = df_tr["Close"]
        volume = df_tr["Volume"]
        if len(close) < _SM_MIN_TRADING_DAYS or len(volume) < _SM_MIN_TRADING_DAYS:
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
        window_start = max(0, end_vol - 20)

        # Deteksi gap suspensi lewat kontinuitas TANGGAL KALENDER (bukan
        # cuma jumlah bar) dalam rentang yang dipakai vol_avg20 + hari
        # valid_idx sendiri.
        window_dates = df_tr.index[window_start:end_vol + 1]
        if len(window_dates) >= 2:
            gaps = window_dates.to_series().diff().dt.days.dropna()
            if (gaps > _SM_MAX_GAP_DAYS).any():
                return None

        vol_today = float(volume.iloc[valid_idx])
        vol_window = volume.iloc[window_start:end_vol]
        # off-by-one lama: window ini dulu 21 elemen ([end_vol-21:end_vol)),
        # bukan 20 seperti nama variabelnya -- diperbaiki jadi persis 20.
        vol_avg20 = float(vol_window.mean()) if len(vol_window) >= 5 else vol_baseline
        vol_ratio = round(vol_today / vol_avg20, 2) if vol_avg20 > 0 else 1.0

        price = float(close.iloc[valid_idx])
        prev = float(close.iloc[valid_idx - 1]) if abs(valid_idx) < len(close) else price
        chg1 = round((price / prev - 1) * 100, 2) if prev else 0.0
        end_close = len(close) + valid_idx
        chg5 = round((price / float(close.iloc[max(0, end_close - 5)]) - 1) * 100, 2) if end_close >= 5 else 0.0

        # Deteksi ARA/ARB (lihat _get_ara_arb_bands) -- hari yang harganya
        # mendekati/kena batas auto-reject SENGAJA di-skip: volume yang
        # terjadi saat limit biasanya cuma order matching tipis di harga
        # cap (kadang malah sangat kecil, terutama saat ARB gorengan float
        # kecil), bukan indikasi minat institusional genuine, dan chg1/chg5
        # jadi ekstrem murni krn mentok batas, bukan momentum sungguhan.
        ara_frac, arb_frac = _get_ara_arb_bands(price)
        if chg1 >= (ara_frac * 100) - _ARA_ARB_MARGIN_PCT or chg1 <= -(arb_frac * 100) + _ARA_ARB_MARGIN_PCT:
            return None

        # Filter likuiditas (reuse _liquidity_label -- field yang SAMA
        # dipakai record_smart_money_signals utk memastikan sinyal "bisa
        # dieksekusi secara wajar"). BUG NYATA ditemukan lewat audit: dulu
        # TIDAK ADA filter likuiditas sama sekali di scanner ini, padahal
        # saham illikuid paling rentan vol_ratio palsu (satu transaksi
        # ganjil bisa melonjakkan ratio tanpa mencerminkan minat
        # institusional sungguhan).
        avg_value_20 = float((close.iloc[window_start:end_vol] * volume.iloc[window_start:end_vol]).mean()) if end_vol > window_start else 0.0
        likuiditas = _liquidity_label(avg_value_20)
        if likuiditas in ("Kurang Likuid", "Tidak Likuid"):
            return None

        # RSI dihitung dari histori SAMPAI hari valid_idx (bukan hari
        # terakhir mentah di df) -- BUG NYATA ditemukan lewat audit: window
        # RSI dulu SELALU memakai .iloc[-1] tanpa peduli valid_idx sudah
        # mundur beberapa hari (mis. karena 1-4 hari terakhir volumenya
        # nyaris kosong), sehingga RSI bisa mencerminkan kondisi BEBERAPA
        # HARI SETELAH hari yang sebenarnya dianalisis -- bisa terbalik
        # arah sepenuhnya (oversold vs overbought).
        close_upto_valid = close.iloc[:end_close + 1]
        delta = close_upto_valid.diff().dropna()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        if len(gain) == 0 or _np.isnan(gain.iloc[-1]) or _np.isnan(loss.iloc[-1]):
            rsi = None  # window RSI (14 hari) belum cukup data sampai hari valid_idx
        else:
            gain_last, loss_last = float(gain.iloc[-1]), float(loss.iloc[-1])
            if loss_last == 0 and gain_last == 0:
                rsi = 50.0  # harga flat total 14 hari terakhir -- tak ada naik/turun sama sekali
            elif loss_last == 0:
                rsi = 100.0  # semua hari naik -- RS -> tak hingga (BUG lama: dulu return None)
            else:
                rsi = round(100 - 100 / (1 + gain_last / loss_last), 1)

        pattern = _sm_classify(vol_ratio, chg5, chg1, rsi)
        if not pattern:
            return None

        # Freshness: berapa hari yang lalu anomali ini sebenarnya terjadi
        # relatif ke hari terakhir data yang tersedia -- dulu tidak
        # diekspos sama sekali (temuan audit), caller/UI tidak bisa
        # membedakan "anomali hari ini" vs "anomali beberapa hari lalu
        # yang baru terdeteksi karena data tipis".
        hari_lalu = abs(valid_idx) - 1
        tanggal = str(df_tr.index[valid_idx].date())

        return {"kode": kode, "harga": int(price), "chg1": chg1, "chg5": chg5,
                "vol_ratio": vol_ratio, "rsi": rsi, "pola": pattern,
                "hari_lalu": hari_lalu, "tanggal": tanggal,
                "likuiditas": likuiditas,
                "grup": GRUP_KONGLOMERASI.get(kode, "Independen")}
    except Exception:
        return None


async def _scan_one_sm(kode: str) -> dict | None:
    """Scan satu ticker untuk anomali volume."""
    try:
        df = await _clean(kode + ".JK", period="3mo", interval="1d")
        # Selaras dgn guard umur listing di _process_sm_df (_SM_MIN_TRADING_
        # DAYS) -- skip lebih awal di sini juga supaya tidak buang compute
        # utk saham yang sudah pasti gagal guard itu.
        if df is None or len(df) < _SM_MIN_TRADING_DAYS:
            return None
        df_tr = df[df["Volume"] > 0].dropna(subset=["Close", "Volume"])
        return _process_sm_df(kode, df_tr)
    except Exception:
        return None


def _add_cross_sectional_rank(items: list) -> list:
    """Tambahkan percentile rank vol_ratio SETIAP saham RELATIF terhadap
    peer-nya DALAM GRUP LIKUIDITAS YANG SAMA -- BUKAN threshold absolut
    flat ke semua saham. Temuan audit: varians volume itu heteroskedastik,
    blue chip (varians harian rendah) vol_ratio 1.8x sudah cukup berarti,
    sementara saham tidur bisa lompat 3-5x hanya dari SATU transaksi
    ganjil. Percentile menjawab "seberapa menonjol saham ini DIBANDING
    saham setara likuiditasnya", bukan angka absolut yang bias tier.

    KETERBATASAN YANG JUJUR DICATAT: percentile dihitung HANYA di antara
    saham yang SUDAH LOLOS threshold absolut _sm_classify (di `items`),
    BUKAN terhadap SELURUH universe yang di-scan (termasuk yang gagal
    threshold) -- percentile "penuh" butuh restrukturisasi scan jadi 2
    tahap (kumpulkan semua metrik mentah dulu, baru klasifikasi setelah
    tahu distribusi seluruh batch), perubahan arsitektur besar yang di
    luar cakupan perbaikan ini. Field ini SENGAJA cuma menambah KONTEKS/
    URUTAN tampilan, TIDAK mengubah kriteria kategori Akumulasi/
    Distribusi/dst yang sudah ada -- supaya tidak mengubah semantik
    sinyal yang sudah tercatat di signal_history via source SMART_MONEY."""
    by_group = defaultdict(list)
    for it in items:
        by_group[it.get("likuiditas", "Kurang Likuid")].append(it)
    for group_items in by_group.values():
        vol_ratios = sorted(x["vol_ratio"] for x in group_items)
        n = len(vol_ratios)
        for it in group_items:
            if n <= 1:
                it["vol_ratio_percentile"] = 100.0
                continue
            rank = sum(1 for v in vol_ratios if v <= it["vol_ratio"])
            it["vol_ratio_percentile"] = round(rank / n * 100, 1)
    return items


def _build_sm_payload(items: list, total: int, scope: str) -> dict:
    items = _add_cross_sectional_rank(items)
    akumulasi = sorted(
        [x for x in items if any(p in x["pola"] for p in ("Akumulasi", "Breakout", "Siluman"))],
        key=lambda x: x["vol_ratio_percentile"], reverse=True,
    )
    distribusi = sorted(
        [x for x in items if "Distribusi" in x["pola"]],
        key=lambda x: x["vol_ratio_percentile"], reverse=True,
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


def _ringkasan_sinyal_teknikal(ai: dict) -> dict:
    """Replika SERVER-SIDE dari _buildTechSummary() di web/static/index.html
    (panel "Ringkasan Sinyal Teknikal" pada halaman Analisis -- 6 indikator
    RSI/MACD/Volume/AI Score/%1 Hari/%5 Hari, masing-masing "beli"/"netral"
    /"jual", diringkas jadi satu verdict BELI KUAT/BELI/CENDERUNG BELI/
    NETRAL/CENDERUNG JUAL/JUAL/JUAL KUAT).

    Permintaan eksplisit user: gerbang konfirmasi Smart Money SEBELUMNYA
    pakai ai_rating (calculate_ai_score_from_df, cuma 1 dimensi skor) --
    user menunjuk panel Ringkasan Sinyal Teknikal ini secara spesifik
    ("smart money itu di combo ama ini") sbg maksud "teknikal" yang
    dipakai utk konfirmasi, bukan ai_rating.

    PENTING -- RISIKO DRIFT: ini PORTING MANUAL dari JS ke Python, bukan
    satu sumber logic yang di-share. Kalau _buildTechSummary() di
    index.html diubah (threshold RSI/volume/dst berubah), fungsi ini
    HARUS ikut diperbarui -- persis kelas risiko yang sama dgn "2
    implementasi ticker-matching yang divergen" yang pernah jadi bug
    nyata di core/news.py (lihat memory news_ticker_matching_accuracy).
    Field input (rsi/macd_bullish/vol_ratio/score/change_1d/change_5d)
    SEMUA sudah dihitung calculate_ai_score_from_df (core/ai_score.py),
    persis field yang sama dipakai /api/analyze utk render panel JS-nya --
    jadi verdict di sini dijamin sama persis dgn yang user lihat di
    Analisis, bukan angka baru yang beda."""
    rsi = ai.get("rsi") if ai.get("rsi") is not None else 50
    macd_bullish = bool(ai.get("macd_bullish"))
    vol_ratio = ai.get("vol_ratio") or 0
    score = ai.get("score") or 0
    c1 = ai.get("change_1d") or 0
    c5 = ai.get("change_5d") or 0

    def _sig(cond_beli, cond_jual):
        return "beli" if cond_beli else ("jual" if cond_jual else "netral")

    signals = [
        _sig(rsi < 45, rsi >= 70),
        "beli" if macd_bullish else "jual",
        _sig(vol_ratio >= 1.2, vol_ratio < 0.5),
        _sig(score >= 65, score < 40),
        _sig(c1 >= 1, c1 <= -1),
        _sig(c5 >= 3, c5 <= -3),
    ]
    beli, jual = signals.count("beli"), signals.count("jual")
    netral = signals.count("netral")

    if beli >= 5:
        overall = "BELI KUAT"
    elif beli >= 4:
        overall = "BELI"
    elif jual >= 5:
        overall = "JUAL KUAT"
    elif jual >= 4:
        overall = "JUAL"
    elif beli > jual:
        overall = "CENDERUNG BELI"
    elif jual > beli:
        overall = "CENDERUNG JUAL"
    else:
        overall = "NETRAL"
    return {"overall": overall, "beli": beli, "netral": netral, "jual": jual}


# Verdict "Ringkasan Sinyal Teknikal" yang dianggap cukup meyakinkan sbg
# gerbang konfirmasi kedua utk Smart Money -- sengaja HANYA 2 tingkat
# teratas (BELI KUAT/BELI, setara >=4 dari 6 indikator searah beli),
# BUKAN termasuk "CENDERUNG BELI" (cuma menang tipis, beli>jual tanpa
# ambang) -- konsisten dgn skop ai_rating lama yang juga cuma 2 tingkat
# teratas dari 5 (SANGAT BAGUS/BAGUS).
_RINGKASAN_TEKNIKAL_BUY = ("BELI KUAT", "BELI")


async def _record_smart_money_cycle(confidence_items: list[dict]):
    """Scan anomali volume Smart Money (universe scope='core', 45 saham --
    _SM_UNIVERSE == SCREENER_UNIVERSE sbg SET, jadi join by kode di bawah
    valid tanpa perlu hitung ulang TP/SL) dan catat sbg source kedua di
    signal_history ('SMART_MONEY'), reuse pola yang sama dgn Top Pick di
    confidence().

    HANYA pola akumulasi (SMART_MONEY_BUY_POLA) yang direkam, dan HANYA
    kalau "Ringkasan Sinyal Teknikal" (panel yang sama persis dgn di
    halaman Analisis -- lihat _ringkasan_sinyal_teknikal) JUGA bilang
    BELI/BELI KUAT -- permintaan eksplisit user: "smart money itu di
    combo ama ini" (menunjuk panel Ringkasan Sinyal Teknikal, BUKAN
    ai_rating yang dipakai versi sebelumnya -- ai_rating cuma 1 dimensi
    skor komposit, Ringkasan Sinyal Teknikal gabungan 6 indikator RSI/
    MACD/Volume/AI Score/%1H/%5H yang SAMA PERSIS dgn yang user lihat di
    Analisis, jadi user bisa langsung verifikasi silang). Supaya Smart
    Money jadi KONFIRMASI tambahan di atas sinyal teknikal yang sudah
    bagus, bukan sumber sinyal berdiri sendiri yang bisa bertentangan
    arah dgn teknikal (dulu Distribusi direkam sbg SELL independen --
    dihentikan, terlalu sering menambah entry yang membingungkan saat
    dibandingkan dgn Top Pick di panel yang sama).

    confidence_items: HARUS berasal dari return value confidence() (yang
    SUDAH dihitung confidence_score-nya), BUKAN _confidence_raw_signals()
    -- field itu belum ada di cache raw (pre-scoring), cuma dihitung di
    loop kedua confidence() sendiri. Kalau confidence_items kosong (mis.
    confidence() barusan gagal), skip seluruhnya -- tanpa TP/SL/likuiditas
    dari situ, tidak ada dasar wajar utk mencatat entry apa pun."""
    if not confidence_items:
        return
    from core.signal_history import record_smart_money_signals, SMART_MONEY_BUY_POLA

    tasks = [_scan_one_sm(k) for k in _SM_UNIVERSE]
    sm_items = [r for r in await asyncio.gather(*tasks, return_exceptions=False) if r]
    if not sm_items:
        return

    conf_by_kode = {it["kode"]: it for it in confidence_items}
    enriched = []
    for sm in sm_items:
        if sm.get("pola") not in SMART_MONEY_BUY_POLA:
            continue  # buang pola Distribusi/Distribusi Agresif sepenuhnya
        conf = conf_by_kode.get(sm["kode"])
        if not conf:
            continue
        ringkasan = conf.get("ringkasan_teknikal") or {}
        if ringkasan.get("overall") not in _RINGKASAN_TEKNIKAL_BUY:
            continue  # Ringkasan Sinyal Teknikal belum bilang BELI -- jangan catat dulu
        enriched.append({
            **sm,
            "potensi_naik_pct": conf.get("potensi_naik_pct"),
            "risiko_turun_pct": conf.get("risiko_turun_pct"),
            "entry_price": conf.get("entry_price"),
            "tp2_pct": conf.get("tp2_pct"),
            "tp3_pct": conf.get("tp3_pct"),
            "likuiditas": conf.get("likuiditas"),
            "confidence_score": conf.get("confidence_score"),
            "ai_score": conf.get("ai_score"),
            # Kolom `recommendation` di signal_history (diisi dari key
            # "ai_rating" ini oleh record_smart_money_signals) SEKARANG
            # menyimpan verdict Ringkasan Sinyal Teknikal (BELI KUAT/BELI),
            # BUKAN ai_rating lagi -- itu yang SUNGGUHAN menggerbangkan
            # entry ini (lihat pengecekan di atas), jadi itu yang harus
            # tercatat sbg alasan konfirmasinya, bukan metrik lain yang
            # kebetulan juga ada di conf.
            "ai_rating": ringkasan.get("overall"),
        })

    await record_smart_money_signals(enriched, price_lookup=_signal_entry_price_lookup)


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

    def _clean_nama(s: str) -> str:
        """Beberapa laporan buyback/repurchase agreement yang dilaporkan
        via anggota Direksi/Komisaris (bukan investor individu ber-SID)
        punya field 'Nama (sesuai SID)' yang oleh sistem IDX sendiri
        di-render literal jadi teks 'null' (bukan dikosongkan/'Tidak
        ditampilkan' seperti field privasi lain) -- BUKAN bug parsing
        di sisi kita, tapi tetap harus disaring supaya 'null' tidak
        bocor sebagai nama sungguhan ke UI/konsumen lain."""
        return "" if s.strip().lower() == "null" else s

    nama = _clean_nama(_find_val("sesuai SID", "Name (SID", "Name \\(SID"))
    perusahaan = _clean_nama(_find_val("Nama Perusahaan Tbk", "Issuer"))
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


# WIB sebagai offset TETAP (UTC+7, tidak ada DST) -- BUKAN ZoneInfo("Asia/
# Jakarta") yang di Windows/container minimal butuh package tzdata terpasang
# (kalau tidak ada, ZoneInfoNotFoundError). Bug nyata yang ini perbaiki:
# server produksi berjam UTC menganggap "hari ini" masih kemarin (mis. sudah
# 13 Jul WIB tapi hari=0 dihitung 12 Jul) -- tanggal filing IDX itu tanggal
# WIB, jadi acuan "hari ini" HARUS WIB, bukan jam lokal server.
from datetime import timezone as _tz, timedelta as _td_wib
_WIB = _tz(_td_wib(hours=7))


class X15FetchError(RuntimeError):
    """idx.co.id tidak terjangkau/menolak (429, blokir Cloudflare thd IP
    datacenter, dst). SENGAJA exception sendiri -- kegagalan fetch TIDAK
    BOLEH menyamar jadi list kosong "tidak ada filing" (bug nyata di
    deploy VPS: halaman Pemegang tampil 'Tidak ada data' berhari-hari,
    padahal sebenarnya IDX memblokir IP servernya -- user tidak bisa
    membedakan itu dari hari yang memang sepi filing)."""


async def _fetch_x15_today(days_back: int = 0) -> list:
    """Fetch SEMUA laporan kepemilikan saham (X-15/POJK 4-2024) dari IDX +
    parse PDF KSEI, TANPA filter jenis pemegang -- filtering (≥5% & pengendali
    untuk /api/x15, jabatan direksi/komisaris untuk /api/insider) dilakukan
    masing-masing oleh endpoint pemanggil, bukan di sini. Field 'jabatan'
    hasil parse SUDAH berisi posisi resmi (Direktur/Komisaris/dst) untuk
    pelapor insider -- makanya transaksi insider tidak perlu sumber data
    baru, cuma perlu tidak dibuang oleh filter ≥5%.

    Cache HASIL MENTAH per-hari DI SINI (key 'x15raw:{days_back}') -- BUKAN
    cuma di lapisan endpoint (/api/x15, /api/insider) seperti sebelumnya.
    Ditemukan nyata: /api/pemegang-saham/{kode} (dipakai halaman Pemegang
    Saham) butuh scan sampai 90 hari SEKALIGUS per saham, dan kalau tiap
    hari selalu fetch ULANG ke idx.co.id (tidak reuse cache /api/x15/
    /api/insider yang sudah ada), beberapa panggilan berturut-turut
    (mis. cek beberapa saham cepat) bisa dengan mudah menembak >100
    request ke idx.co.id dalam hitungan detik -- PERSIS yang terjadi:
    idx.co.id sendiri membalas 429 (rate-limited PIHAK MEREKA, bukan
    limiter kita), yang kalau dibiarkan bisa membuat IP kita diblokir dan
    MEROBOHKAN /api/x15 & /api/insider yang sudah berjalan baik. Dengan
    cache di sini, KETIGA konsumen (x15, insider, pemegang-saham) berbagi
    SATU hasil fetch per hari, bukan tiga (atau lebih) fetch terpisah."""
    from datetime import timedelta as _td, datetime as _dt
    import cloudscraper as _cs

    cache_key = f"x15raw:{days_back}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    def _sync():
        sc = _cs.create_scraper(browser={"browser": "chrome", "platform": "windows", "mobile": False})
        # Tanggal acuan = WIB (lihat _WIB di atas), bukan jam lokal server.
        today = (_dt.now(_WIB) - _td(days=days_back)).strftime("%Y%m%d")
        r = sc.get(
            "https://www.idx.co.id/primary/ListedCompany/GetAnnouncement",
            params={"emitenType": "*", "indexFrom": 0, "pageSize": 100,
                    "dateFrom": today, "dateTo": today, "lang": "id", "keyword": "kepemilikan"},
            timeout=15,
        )
        if r.status_code != 200:
            # Termasuk 429 (rate-limited idx.co.id sendiri) -- raise, JANGAN
            # return kosong (kosong = "tidak ada filing", ini beda kasus) dan
            # JANGAN cache, biar dicoba lagi nanti.
            raise X15FetchError(f"idx.co.id membalas HTTP {r.status_code}")
        try:
            replies = r.json().get("Replies", [])
        except ValueError:
            # 200 tapi bukan JSON = halaman challenge/blokir Cloudflare
            # (umum menimpa IP datacenter/VPS) -- sama: bukan "tidak ada
            # filing", jangan menyamar jadi list kosong.
            raise X15FetchError("respons idx.co.id bukan JSON (kemungkinan challenge/blokir Cloudflare thd IP server)")
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
    results = await loop.run_in_executor(None, _sync)
    _cache_set(cache_key, results, ttl=_CACHE_TTL if days_back == 0 else _CACHE_TTL_HISTORICAL)
    return results


def _is_insider_jabatan(jabatan: str) -> bool:
    """True kalau field 'jabatan' hasil parse PDF menunjukkan pelapor adalah
    insider (direksi/komisaris), bukan sekadar pemegang saham substansial."""
    j = (jabatan or "").lower()
    return any(kw in j for kw in ("direktur", "komisaris", "direksi"))


def _split_x15_items(items: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """Klasifikasi item X-15 jadi akumulasi (naik) / distribusi (turun) /
    aksi_korporasi (tanpa perubahan %), dipakai SAMA oleh /api/x15 dan
    /api/insider (dulu 2 salinan logika yang sama persis -- risiko satu
    diperbaiki, satunya lupa, seperti kasus nyata ticker-matching di
    core/news.py sebelumnya).

    akumulasi/distribusi HARUS strictly non-zero (>0 / <0) -- bukan
    >=0/<=0 -- karena beberapa laporan (mis. buyback/repurchase
    agreement yang dilaporkan lewat anggota Direksi/Komisaris atas nama
    pengendali) punya pct_sebelum==pct_setelah (0.00% perubahan, sekadar
    reafirmasi/otorisasi formal, BUKAN transaksi akumulasi/distribusi
    sungguhan) dan field nama individu yang kosong (IDX sendiri
    merender 'null'). User MASIH ingin laporan tanpa-perubahan ini
    ditampilkan sebagai KONTEKS aksi korporasi (bukan disembunyikan
    total) -- makanya dipisah ke kategori ketiga, bukan cuma dibuang."""
    akumulasi = sorted(
        [x for x in items if x["jenis"] == "beli" and x["perubahan"] > 0],
        key=lambda x: x["perubahan"], reverse=True,
    )
    distribusi = sorted(
        [x for x in items if x["jenis"] in ("jual", "transfer") or x["perubahan"] < 0],
        key=lambda x: x["perubahan"],
    )
    aksi_korporasi = sorted(
        [x for x in items if x["perubahan"] == 0],
        key=lambda x: x["kode"],
    )
    return akumulasi, distribusi, aksi_korporasi


def _latest_x15_holders_for_kode(items: list[dict]) -> list[dict]:
    """Dari SEMUA filing X-15 milik SATU kode (rentang beberapa hari/bulan),
    ambil HANYA filing TERBARU per pelapor (nama, atau perusahaan kalau
    nama kosong/'null') sbg status kepemilikannya SAAT INI -- kalau
    orang/entitas yang sama lapor beberapa kali (tiap kali ada perubahan),
    filing LAMA-nya sudah basi (sudah digantikan filing baru), jangan
    ditampilkan dobel.

    Diurutkan dari % kepemilikan TERBESAR (pct_setelah) -- meniru
    tampilan 'top holder' walau ini BUKAN registry lengkap (cuma yang
    PERNAH lapor wajib ≥5%/insider, retail/pemegang kecil tidak pernah
    muncul krn tidak wajib lapor)."""
    latest_by_person: dict[str, dict] = {}
    for it in items:
        person_key = (it.get("nama") or it.get("perusahaan") or "").strip().lower()
        if not person_key:
            continue  # tidak bisa diidentifikasi (nama 'null' & perusahaan kosong) -- lewati, jangan ditebak
        existing = latest_by_person.get(person_key)
        if existing is None or it["tanggal"] > existing["tanggal"]:
            latest_by_person[person_key] = it
    return sorted(latest_by_person.values(), key=lambda x: x["pct_setelah"], reverse=True)


async def _fetch_x15_history_for_kode(kode: str, days: int = 90) -> list[dict]:
    """Kumpulkan SEMUA filing X-15 utk SATU kode dari rentang 'days' hari
    kalender terakhir -- reuse _fetch_x15_today(days_back=d), yang SEKARANG
    (lihat catatan di fungsi itu) sudah cache hasil MENTAH per-hari sendiri
    ('x15raw:{d}'), jadi hari yang SUDAH pernah di-scan (oleh /api/x15,
    /api/insider, ATAU kode lain yang lebih dulu dicek lewat endpoint ini)
    tidak perlu fetch ulang ke idx.co.id.

    Concurrency DIBATASI (semaphore, bukan asyncio.gather polos utk semua
    hari sekaligus) -- ditemukan nyata: gather 90 request SEKALIGUS ke
    idx.co.id (apalagi kalau di-panggil utk beberapa saham berturut-turut
    dgn cache dingin) memicu idx.co.id MEMBALAS 429 (rate-limit di PIHAK
    MEREKA), yang kalau dibiarkan bisa membuat IP kita diblokir dan
    merobohkan /api/x15 & /api/insider yang sudah berjalan baik sebelum
    fitur ini ada. 8 konkuren cukup cepat tanpa membombardir sekaligus."""
    days = max(1, min(90, days))
    sem = asyncio.Semaphore(8)

    async def _fetch_one(d):
        async with sem:
            return await _fetch_x15_today(days_back=d)

    results_per_day = await asyncio.gather(
        *[_fetch_one(d) for d in range(days)],
        return_exceptions=True,
    )
    kode = kode.upper()
    items = []
    for day_result in results_per_day:
        if isinstance(day_result, Exception):
            continue
        items.extend(x for x in day_result if x["kode"] == kode)
    return items


@app.get("/api/pemegang-saham/{kode}")
async def api_pemegang_saham(kode: str):
    """Pemegang saham ≥5% & insider (Direksi/Komisaris/Pengendali) utk
    SATU saham, dari filing X-15/POJK 4-2024 resmi IDX yang sama dgn
    /api/x15 -- BUKAN registry lengkap KSEI (lihat catatan jujur di
    'disclaimer' respons): cuma pelapor yang PERNAH mengajukan filing
    wajib dalam 90 hari terakhir yang muncul, pemegang kecil (di bawah 5%
    & bukan insider) tidak pernah tercatat krn memang tidak wajib lapor.
    Persentase, BUKAN jumlah lembar saham/nilai Rupiah -- filing X-15
    cuma melaporkan hak suara sebelum/sesudah dalam %, tidak menyertakan
    jumlah saham mentah."""
    kode = kode.upper().strip()
    cache_key = f"pemegang_saham:{kode}"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    try:
        raw_items = await _fetch_x15_history_for_kode(kode, days=90)
    except Exception as e:
        raise HTTPException(502, f"Gagal fetch data pemegang saham: {e}")

    holders = _latest_x15_holders_for_kode(raw_items)
    for h in holders:
        h["is_insider"] = _is_insider_jabatan(h["jabatan"])
        h["nama_tampil"] = h.get("nama") or h.get("perusahaan") or "(tidak diketahui)"

    payload = _py({
        "kode": kode,
        "holders": holders,
        "total": len(holders),
        "disclaimer": ("Data dari filing X-15/POJK 4-2024 resmi IDX (pemegang ≥5% & insider yang "
                       "wajib lapor perubahan kepemilikan), 90 hari terakhir. BUKAN daftar lengkap "
                       "seluruh pemegang saham -- pemegang di bawah 5% (termasuk retail) tidak wajib "
                       "lapor sehingga tidak pernah muncul di sini. Persentase hak suara, bukan jumlah "
                       "saham/nilai Rupiah (tidak dilaporkan dalam filing ini)."),
    })
    _cache_set(cache_key, payload, ttl=_CACHE_TTL_HISTORICAL)
    return payload


@app.get("/api/x15")
async def api_x15(hari: int = 0):
    """Ringkasan harian transaksi kepemilikan ≥5% dari IDX X-15 filings.
    hari=0 → hari ini, hari=1 → kemarin, dst (max 31, ~sebulan kalender agar
    cukup untuk melacak pola akumulasi/distribusi jangka lebih panjang,
    bukan cuma seminggu)."""
    hari = max(0, min(31, hari))
    cache_key = f"x15:{hari}"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    try:
        raw_items = await _fetch_x15_today(days_back=hari)
    except X15FetchError as e:
        # Pesan eksplisit: kegagalan sumber ≠ hari sepi filing -- frontend
        # menampilkan ini sbg error box, BUKAN "Tidak ada data".
        raise HTTPException(502, f"Sumber data IDX tidak terjangkau dari server ({e}) — bukan berarti tidak ada laporan hari ini.")
    except Exception as e:
        raise HTTPException(502, f"Gagal fetch X-15: {e}")

    # Hanya pemegang saham substansial (≥5%) atau pengendali -- transaksi
    # insider kecil (direksi/komisaris di bawah 5%) sengaja disaring keluar
    # di sini, lihat /api/insider untuk itu.
    items = [x for x in raw_items if x["pct_setelah"] >= 5.0 or x["pct_sebelum"] >= 5.0 or x["pengendali"]]
    akumulasi, distribusi, aksi_korporasi = _split_x15_items(items)

    from datetime import timedelta as _td, datetime as _dt
    tgl_str = (_dt.now(_WIB) - _td(days=hari)).strftime("%d %b %Y")

    payload = _py({
        "akumulasi": akumulasi,
        "distribusi": distribusi,
        "aksi_korporasi": aksi_korporasi,
        "total": len(items),
        "tanggal": tgl_str,
        "hari": hari,
    })
    # hari>=1 = filing historis yang sudah final (lihat _CACHE_TTL_HISTORICAL) --
    # hari=0 tetap TTL pendek karena filing hari ini masih bisa nambah.
    _cache_set(cache_key, payload, ttl=_CACHE_TTL if hari == 0 else _CACHE_TTL_HISTORICAL)
    return payload


@app.get("/api/insider")
async def api_insider(hari: int = 0):
    """Ringkasan harian transaksi INSIDER (direksi/komisaris beli-jual
    saham perusahaannya sendiri) dari filing IDX X-15/POJK 4-2024 yang sama
    dengan /api/x15 -- bedanya difilter dari field 'jabatan', bukan ≥5%
    kepemilikan (transaksi insider biasanya persentasenya kecil).
    hari=0 → hari ini, hari=1 → kemarin, dst (max 31, ~sebulan kalender)."""
    hari = max(0, min(31, hari))
    cache_key = f"insider:{hari}"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    try:
        raw_items = await _fetch_x15_today(days_back=hari)
    except X15FetchError as e:
        raise HTTPException(502, f"Sumber data IDX tidak terjangkau dari server ({e}) — bukan berarti tidak ada laporan hari ini.")
    except Exception as e:
        raise HTTPException(502, f"Gagal fetch data insider: {e}")

    items = [x for x in raw_items if _is_insider_jabatan(x["jabatan"])]
    akumulasi, distribusi, aksi_korporasi = _split_x15_items(items)

    from datetime import timedelta as _td, datetime as _dt
    tgl_str = (_dt.now(_WIB) - _td(days=hari)).strftime("%d %b %Y")

    payload = _py({
        "akumulasi": akumulasi,
        "distribusi": distribusi,
        "aksi_korporasi": aksi_korporasi,
        "total": len(items),
        "tanggal": tgl_str,
        "hari": hari,
    })
    _cache_set(cache_key, payload, ttl=_CACHE_TTL if hari == 0 else _CACHE_TTL_HISTORICAL)
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
