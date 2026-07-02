# =========================
# FUNDAMENTAL DATA
# =========================
# FITUR BARU. /fundamental KODE -- data fundamental (PE, PBV, ROE, DER,
# Dividend Yield, EPS, dst) dari yfinance .info, BUKAN integrasi API
# baru -- reuse async_ticker_info() yang sudah ada di core/async_yf.py
# (sudah dipakai core/screener.py untuk field marketCap di BSJP screener,
# jadi field ini terkonfirmasi bekerja untuk ticker .JK).
#
# BUKTI YANG DIPAKAI (dicatat untuk transparansi, sama seperti catatan
# di IDX_SECTORAL_INDICES core/market.py): TIDAK BISA dicoba eksekusi
# langsung dari sandbox development (finance.yahoo.com tidak ada di
# allowlist jaringan sandbox). Bukti yang dipakai: (1) field marketCap
# SUDAH dipakai di kode produksi (core/screener.py) sebelum sesi ini,
# (2) ditemukan contoh implementasi nyata (MCP server pihak ketiga,
# mcp-idx di GitHub) yang memakai field trailingPE/forwardPE/
# priceToBook/marketCap/enterpriseValue + income_stmt/balance_sheet/
# cash_flow untuk SAHAM IDX SPESIFIK, dikonfirmasi via web search Juni
# 2026. (3) Halaman Yahoo Finance individual untuk ticker .JK (BFIN,
# CPIN, JPFA) terkonfirmasi punya data perusahaan lengkap.
#
# CATATAN JUJUR SOAL AMBIGUITAS FORMAT FIELD: dividendYield, returnOnEquity,
# dan debtToEquity di yfinance TIDAK punya dokumentasi resmi yang jelas
# soal unit (desimal 0.025 vs sudah-persen 2.5) -- ini masalah yang
# DIKENAL LUAS di komunitas yfinance (format pernah berubah antar versi
# untuk sebagian ticker/exchange). Karena TIDAK BISA diverifikasi
# langsung, dipakai HEURISTIK yang masuk akal (dijelaskan di kode di
# bawah) BUKAN kepastian -- dan setiap pesan ke user MENYERTAKAN
# disclaimer eksplisit untuk cross-check ke sumber resmi (laporan
# keuangan BEI/perusahaan) sebelum dipakai mengambil keputusan.

from core.async_yf import async_ticker_info
from core.database import get_cached_fundamental_db, save_fundamental_cache_db

FUNDAMENTAL_CACHE_MAX_AGE_DAYS = 7


def _safe_get(info: dict, key: str, default=None):
    """Ambil field dari info dict dengan aman -- yfinance .info SERING
    punya field yang None atau hilang sama sekali, TERUTAMA untuk saham
    kecil/kurang likuid di IDX (data fundamental Yahoo Finance untuk
    saham non-large-cap Indonesia kemungkinan kurang lengkap dibanding
    saham AS -- ini batasan jujur, bukan bug)."""
    val = info.get(key, default)
    return val if val is not None else default


def _normalize_percent_field(raw_value: float | None) -> float | None:
    """Normalisasi field yang BISA berupa desimal (0.025) ATAU sudah
    dalam bentuk persen (2.5) -- ambiguitas yang DIKENAL LUAS di
    yfinance (lihat catatan panjang di awal file). HEURISTIK yang
    dipakai: dividend yield & ROE realistis untuk saham sungguhan
    HAMPIR SELALU di bawah 100% (rasio 1.0) dalam bentuk desimal --
    kalau raw_value > 1, hampir pasti itu SUDAH dalam bentuk persen
    (karena desimal >1 berarti yield/ROE >100%, sangat jarang terjadi
    untuk perusahaan yang masih beroperasi normal). Kalau <= 1, asumsi
    desimal, dikali 100.

    INI HEURISTIK, BUKAN KEPASTIAN -- nilai ekstrem (mis. ROE sungguhan
    perusahaan yang baru rugi besar lalu untung kecil bisa >100%) bisa
    salah dikategorikan. Itu sebabnya hasil fungsi ini SELALU ditandai
    dengan asumsi di pesan ke user, bukan diklaim sebagai angka pasti."""
    if raw_value is None:
        return None
    try:
        raw_value = float(raw_value)
    except (TypeError, ValueError):
        return None
    return round(raw_value * 100, 2) if abs(raw_value) <= 1 else round(raw_value, 2)


def _parse_fundamental_info(info: dict, ticker_name: str) -> dict:
    """Parse raw yfinance .info dict jadi struktur fundamental yang
    rapi. SETIAP field diambil dengan _safe_get -- field yang hilang
    jadi None (BUKAN 0 atau placeholder menyesatkan), supaya handler
    bisa menampilkan 'data tidak tersedia' secara eksplisit per field,
    bukan menampilkan angka 0 yang seolah-olah valid."""
    long_name = _safe_get(info, "longName") or _safe_get(info, "shortName") or ticker_name

    return {
        "ticker": ticker_name,
        "nama_perusahaan": long_name,
        "sektor": _safe_get(info, "sector"),
        "industri": _safe_get(info, "industry"),
        "market_cap": _safe_get(info, "marketCap"),
        "harga_sekarang": _safe_get(info, "currentPrice") or _safe_get(info, "regularMarketPrice"),

        # ===== VALUASI =====
        "pe_trailing": _safe_get(info, "trailingPE"),
        "pe_forward": _safe_get(info, "forwardPE"),
        "pbv": _safe_get(info, "priceToBook"),
        "ps_ratio": _safe_get(info, "priceToSalesTrailing12Months"),
        "ev_ebitda": _safe_get(info, "enterpriseToEbitda"),

        # ===== PROFITABILITAS & EFISIENSI (heuristik format, lihat catatan) =====
        "roe_pct": _normalize_percent_field(_safe_get(info, "returnOnEquity")),
        "roa_pct": _normalize_percent_field(_safe_get(info, "returnOnAssets")),
        "net_margin_pct": _normalize_percent_field(_safe_get(info, "profitMargins")),

        # ===== DIVIDEN (heuristik format, lihat catatan panjang di awal file) =====
        "dividend_yield_pct": _normalize_percent_field(_safe_get(info, "dividendYield")),
        "payout_ratio_pct": _normalize_percent_field(_safe_get(info, "payoutRatio")),

        # ===== LEVERAGE -- TIDAK pakai heuristik normalisasi (lihat
        # catatan: yfinance secara konsisten return field ini SUDAH
        # dikali 100 setahu kami dari dokumentasi komunitas, tapi TIDAK
        # diverifikasi langsung -- ditampilkan apa adanya dengan label
        # eksplisit "asumsi %", bukan dinormalisasi otomatis) =====
        "der_raw": _safe_get(info, "debtToEquity"),
        "current_ratio": _safe_get(info, "currentRatio"),

        # ===== PERTUMBUHAN =====
        "revenue_growth_pct": _normalize_percent_field(_safe_get(info, "revenueGrowth")),
        "earnings_growth_pct": _normalize_percent_field(_safe_get(info, "earningsGrowth")),

        # ===== PER SAHAM =====
        "eps_trailing": _safe_get(info, "trailingEps"),
        "eps_forward": _safe_get(info, "forwardEps"),
        "book_value_per_share": _safe_get(info, "bookValue"),
    }


async def fetch_fundamental(ticker: str, use_cache: bool = True) -> dict | None:
    """Ambil data fundamental untuk satu ticker, dengan caching (lihat
    FUNDAMENTAL_CACHE_MAX_AGE_DAYS -- data fundamental berubah lambat,
    TIDAK perlu fresh tiap request seperti data harga).

    Returns None kalau fetch gagal TOTAL (network error, ticker tidak
    ditemukan, dll) -- BUKAN dict kosong, supaya caller bisa membedakan
    'gagal ambil data' dari 'data ada tapi banyak field kosong' (kasus
    kedua tetap return dict, cuma field individualnya None)."""
    if use_cache:
        cached = get_cached_fundamental_db(ticker, max_age_days=FUNDAMENTAL_CACHE_MAX_AGE_DAYS)
        if cached is not None:
            return cached

    try:
        info = await async_ticker_info(ticker)
        if not info or len(info) < 3:
            # .info yang valid biasanya punya puluhan field -- kalau
            # cuma 0-2 field, kemungkinan besar ticker invalid atau
            # request gagal diam-diam (yfinance kadang return dict
            # nyaris kosong alih-alih raise exception saat gagal)
            return None

        ticker_name = ticker.replace(".JK", "")
        parsed = _parse_fundamental_info(info, ticker_name)

        save_fundamental_cache_db(ticker, parsed)
        return parsed

    except Exception as e:
        print(f"⚠️ Gagal fetch fundamental {ticker}: {type(e).__name__}: {e}")
        return None
