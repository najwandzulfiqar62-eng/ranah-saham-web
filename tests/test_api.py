# =========================
# TES ENDPOINT UTAMA
# =========================
# Cakupan sengaja dibatasi ke endpoint yang paling sering dipakai
# (analyze/ohlc/chart/compare) -- ini bukan cakupan penuh seluruh 40+
# endpoint di web/app.py, tapi cukup untuk mendeteksi regresi pada alur
# data inti (download -> _clean -> hitung -> serialize JSON/PNG).


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_analyze_ok(client):
    r = client.get("/api/analyze/BBCA")
    assert r.status_code == 200
    data = r.json()
    assert data["kode"] == "BBCA"
    assert data["score"] is not None
    assert data["rating"] is not None
    assert isinstance(data["price"], (int, float))


def test_analyze_normalizes_kode(client):
    r = client.get("/api/analyze/bbca")
    assert r.status_code == 200
    assert r.json()["kode"] == "BBCA"


def test_analyze_insufficient_history_404(client, monkeypatch, fake_df):
    import core.async_yf as async_yf

    monkeypatch.setattr(async_yf.yf, "download", lambda *a, **kw: fake_df.head(10).copy())
    r = client.get("/api/analyze/BBCA")
    assert r.status_code == 404


def test_ohlc_ok(client):
    r = client.get("/api/ohlc/BBCA?days=50")
    assert r.status_code == 200
    data = r.json()
    assert len(data["candles"]) > 0
    first = data["candles"][0]
    assert set(["time", "open", "high", "low", "close"]) <= set(first.keys())


def test_compare_ok(client):
    r = client.get("/api/compare?kodes=BBCA,TLKM")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 2
    assert {it["kode"] for it in items} == {"BBCA", "TLKM"}


def test_compare_partial_failure_keeps_other_items(client, monkeypatch, fake_df):
    """Satu ticker gagal tidak boleh menggagalkan seluruh /api/compare
    (regresi untuk refactor sequential-loop -> asyncio.gather)."""
    import core.async_yf as async_yf

    def _download(*args, **kw):
        ticker = args[0] if args else kw.get("tickers")
        if ticker == "BADTICKER.JK":
            raise RuntimeError("simulated fetch failure")
        return fake_df.copy()

    monkeypatch.setattr(async_yf.yf, "download", _download)
    r = client.get("/api/compare?kodes=BBCA,BADTICKER")
    assert r.status_code == 200
    items = {it["kode"]: it for it in r.json()["items"]}
    assert "score" in items["BBCA"]
    assert "error" in items["BADTICKER"]


def test_multitimeframe_fetches_concurrently_and_caches(client, monkeypatch, fake_df):
    """Regresi: dulu 3 timeframe (1D/1W/1M) di-download SEKUENSIAL tanpa
    cache, jadi tiap klik selalu menunggu 3x round-trip Yahoo Finance.
    Sekarang harus konkuren (asyncio.gather) dan hasilnya di-cache Redis."""
    import core.async_yf as async_yf
    import web.app as app_module

    calls = {"n": 0}

    def _counting(*a, **kw):
        calls["n"] += 1
        return fake_df.copy()

    monkeypatch.setattr(async_yf.yf, "download", _counting)

    r1 = client.get("/api/multitimeframe/BBCA")
    assert r1.status_code == 200
    data = r1.json()
    assert data["ticker"] == "BBCA"
    assert set(data["timeframes"].keys()) == {"1D (Harian)", "1W (Mingguan)", "1M (Bulanan)"}
    assert calls["n"] == 3  # satu download per timeframe

    r2 = client.get("/api/multitimeframe/BBCA")
    assert r2.status_code == 200
    assert r2.json() == data
    assert calls["n"] == 3  # panggilan kedua dari cache, bukan download ulang


def test_x15_and_insider_filter_correctly(client, monkeypatch):
    """/api/x15 (pemegang >=5%/pengendali) dan /api/insider (jabatan
    direksi/komisaris) berbagi satu fetch (_fetch_x15_today), tapi
    filternya harus tetap terpisah -- transaksi insider kecil tidak boleh
    ikut ke x15, dan pemegang >=5% tanpa jabatan tidak boleh ikut ke
    insider."""
    import web.app as app_module

    raw_items = [
        {"kode": "BBCA", "tanggal": "2026-07-02", "pdf_url": "x", "nama": "Big Fund",
         "perusahaan": "BBCA", "jabatan": "", "pct_sebelum": 10.0, "pct_setelah": 12.0,
         "perubahan": 2.0, "jenis": "beli", "pengendali": False},
        {"kode": "TLKM", "tanggal": "2026-07-02", "pdf_url": "x", "nama": "Budi",
         "perusahaan": "TLKM", "jabatan": "Direktur Utama", "pct_sebelum": 0.01, "pct_setelah": 0.02,
         "perubahan": 0.01, "jenis": "beli", "pengendali": False},
        {"kode": "ASII", "tanggal": "2026-07-02", "pdf_url": "x", "nama": "Siti",
         "perusahaan": "ASII", "jabatan": "Komisaris Independen", "pct_sebelum": 0.5, "pct_setelah": 0.3,
         "perubahan": -0.2, "jenis": "jual", "pengendali": False},
        {"kode": "GOTO", "tanggal": "2026-07-02", "pdf_url": "x", "nama": "Retail Investor",
         "perusahaan": "GOTO", "jabatan": "", "pct_sebelum": 1.0, "pct_setelah": 0.8,
         "perubahan": -0.2, "jenis": "jual", "pengendali": False},
    ]

    async def _fake_fetch(days_back=0):
        return raw_items

    monkeypatch.setattr(app_module, "_fetch_x15_today", _fake_fetch)

    x15 = client.get("/api/x15?hari=0").json()
    x15_kodes = {it["kode"] for it in x15["akumulasi"] + x15["distribusi"]}
    assert x15_kodes == {"BBCA"}

    insider = client.get("/api/insider?hari=0").json()
    insider_kodes = {it["kode"] for it in insider["akumulasi"] + insider["distribusi"]}
    assert insider_kodes == {"TLKM", "ASII"}


def test_clean_coalesces_concurrent_requests_for_same_ticker(monkeypatch, fake_df):
    """Regresi: banyak request bersamaan untuk ticker yang SAMA (sebelum
    cache Redis sempat terisi) dulu memicu fetch terpisah ke Yahoo Finance
    untuk masing-masing. Sekarang harus di-coalesce jadi SATU fetch saja."""
    import asyncio
    import time as _time

    import core.async_yf as async_yf
    import web.app as app_module

    calls = {"n": 0}

    def _slow_download(*a, **kw):
        calls["n"] += 1
        _time.sleep(0.2)  # simulasikan network delay supaya 3 caller overlap
        return fake_df.copy()

    monkeypatch.setattr(async_yf.yf, "download", _slow_download)

    async def _run():
        return await asyncio.gather(
            app_module._clean("BBCA.JK"),
            app_module._clean("BBCA.JK"),
            app_module._clean("BBCA.JK"),
        )

    results = asyncio.run(_run())
    assert calls["n"] == 1
    assert all(r is not None and not r.empty for r in results)


def test_async_download_retries_on_transient_failure(monkeypatch, fake_df):
    """Regresi: async_download dulu langsung menyerah di percobaan pertama.
    Sekarang retry ringan (2x) untuk kegagalan sesaat (exception dari
    yfinance), supaya gangguan jaringan sekali tidak langsung jadi
    'Gagal memuat data' di UI."""
    import asyncio

    import core.async_yf as async_yf

    calls = {"n": 0}

    def _flaky(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("network blip")
        return fake_df.copy()

    monkeypatch.setattr(async_yf.yf, "download", _flaky)

    df = asyncio.run(async_yf.async_download("BBCA.JK", period="1y", interval="1d"))
    assert calls["n"] == 2
    assert not df.empty


def test_ihsg_entry_zone_upper_bound_is_sane(fake_df):
    """Regresi: entry_zone dulu SELALU menampilkan 'Rp0' sebagai batas atas
    (bug min(resistance, 0) -- resistance selalu positif jadi min-nya
    selalu jatuh ke 0). Batas atas sekarang harus > 0 dan > batas bawah."""
    import re

    from core.ihsg.ihsg_analysis import analyze_ihsg_advanced

    df_daily = fake_df
    df_weekly = df_daily.resample("W").agg({
        "Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum",
    }).dropna()

    result = analyze_ihsg_advanced(df_daily, df_weekly)
    assert result is not None

    m = re.match(r"Rp([\d,]+) - Rp([\d,]+)", result["entry_zone"])
    assert m, f"format entry_zone tidak dikenali: {result['entry_zone']!r}"
    lower = float(m.group(1).replace(",", ""))
    upper = float(m.group(2).replace(",", ""))
    assert upper > 0
    assert upper > lower


def test_ihsg_volume_trend_ignores_incomplete_zero_volume_bar():
    """Regresi: Yahoo Finance kadang balikin Volume=0 untuk bar hari
    berjalan (sesi bursa belum tertutup) -- ditemukan nyata di data live
    ^JKSE. Bar itu harus dibuang dari kalkulasi volume_trend, bukan ikut
    mencemari rata-rata 5 hari terakhir (bobot 1/5 cukup besar untuk
    membuatnya salah baca "DECREASING")."""
    import numpy as np
    import pandas as pd

    from core.ihsg.ihsg_analysis import analyze_ihsg_advanced

    n = 60
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    close = np.linspace(1000, 1100, n)
    volume = np.full(n, 200_000_000.0)  # volume stabil tiap hari...
    volume[-1] = 0  # ...KECUALI bar hari ini (belum lengkap)
    df_daily = pd.DataFrame(
        {"Open": close, "High": close * 1.001, "Low": close * 0.999, "Close": close, "Volume": volume},
        index=dates,
    )
    df_weekly = df_daily.resample("W").agg({
        "Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum",
    }).dropna()

    result = analyze_ihsg_advanced(df_daily, df_weekly)
    assert result is not None
    # Volume stabil 200jt/hari (kecuali bar terakhir yang harus dibuang)
    # -> recent_volume == avg_volume_50 -> STABLE, bukan DECREASING.
    assert result["volume_trend"] == "STABLE"


def test_ihsg_backtest_conditions_cache_indicators_per_dataframe(monkeypatch, fake_df):
    """Regresi: condition_ihsg_bullish_strong/bearish_strong dulu
    menghitung ulang RSI & MACD dari nol untuk SETIAP baris saat backtest
    scan ratusan hari histori (O(n) per baris x n baris). Sekarang
    di-cache di df.attrs per-DataFrame, jadi cuma dihitung sekali
    meskipun _detect_signal_occurrences memanggil condition_fn(df, i)
    ratusan kali."""
    import core.backtest as backtest

    calls = {"n": 0}
    original_rsi = backtest.calculate_rsi

    def _counting_rsi(*a, **kw):
        calls["n"] += 1
        return original_rsi(*a, **kw)

    monkeypatch.setattr(backtest, "calculate_rsi", _counting_rsi)

    backtest.backtest_condition(fake_df, backtest.condition_ihsg_bullish_strong, forward_days=5)
    assert calls["n"] == 1

    calls["n"] = 0
    backtest.backtest_condition(fake_df, backtest.condition_ihsg_bearish_strong, forward_days=5)
    assert calls["n"] == 0  # sudah ke-cache dari panggilan bullish_strong di atas (df sama)


def test_chart_returns_png(client):
    r = client.get("/api/chart/BBCA")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert len(r.content) > 0


def test_chart_is_cached_on_second_call(client, monkeypatch):
    """Panggilan kedua dengan data identik harus disajikan dari cache Redis
    tanpa memanggil generator chart lagi (bukan cuma kebetulan identik)."""
    import web.app as app_module

    calls = {"n": 0}
    original = app_module.generate_advanced_chart

    def _counting(*a, **kw):
        calls["n"] += 1
        return original(*a, **kw)

    monkeypatch.setattr(app_module, "generate_advanced_chart", _counting)

    r1 = client.get("/api/chart/BBCA")
    r2 = client.get("/api/chart/BBCA")
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.content == r2.content
    assert calls["n"] == 1


def test_smc_chart_invalid_kind_400(client):
    r = client.get("/api/smc/BBCA/invalid")
    assert r.status_code == 400


def test_macro_ok(client):
    r = client.get("/api/macro")
    assert r.status_code == 200
    data = r.json()
    assert "items" in data and "impacts" in data
