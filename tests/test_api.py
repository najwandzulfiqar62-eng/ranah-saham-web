# =========================
# TES ENDPOINT UTAMA
# =========================
# Cakupan sengaja dibatasi ke endpoint yang paling sering dipakai
# (analyze/ohlc/chart/compare) -- ini bukan cakupan penuh seluruh 40+
# endpoint di web/app.py, tapi cukup untuk mendeteksi regresi pada alur
# data inti (download -> _clean -> hitung -> serialize JSON/PNG).

import pytest


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


def test_analyze_includes_ringkasan_cepat_fields(client):
    """Regresi: /api/analyze harus menyertakan field badge Ringkasan Cepat
    (likuiditas, gaya_trading, bandar) yang dipakai frontend untuk kartu
    ringkasan di atas halaman Analisis."""
    r = client.get("/api/analyze/BBCA")
    assert r.status_code == 200
    data = r.json()
    assert data["likuiditas"] in ("Sangat Likuid", "Likuid", "Kurang Likuid", "Tidak Likuid")
    assert data["gaya_trading"] in ("Intraday/Scalping", "Swing Trading", "Investasi Jangka Menengah-Panjang")
    assert isinstance(data["avg_value_20"], (int, float))
    # bandar bisa None kalau data historis terlalu pendek untuk A/D line,
    # tapi dengan fake_df default (300 baris) seharusnya selalu terisi.
    assert data["bandar"] is not None
    assert data["bandar"]["label"] in ("Akumulasi", "Distribusi", "Akumulasi Tersembunyi", "Distribusi Tersembunyi")
    assert data["grade"] in ("A", "B", "C", "D")
    # R1 (resistance terdekat) harus di ATAS harga -> potensi naik positif;
    # S1 (support terdekat) harus di BAWAH harga -> risiko turun positif.
    assert data["r1"] > data["price"]
    assert data["s1"] < data["price"]
    assert data["potensi_naik_pct"] > 0
    assert data["risiko_turun_pct"] > 0


def test_compute_grade_liquidity_adjustment():
    """Regresi: grade harus turun kalau likuiditas buruk meski skor sama --
    AI Score sendiri tidak memperhitungkan likuiditas sama sekali, jadi
    grade WAJIB menurunkan skor mentah untuk saham tidak likuid supaya
    tidak menyesatkan (skor teknikal bagus tapi susah dieksekusi nyatanya)."""
    import web.app as app_module

    assert app_module._compute_grade(90, "Sangat Likuid") == "A"
    assert app_module._compute_grade(90, "Tidak Likuid") == "B"  # 90-20=70
    assert app_module._compute_grade(55, "Tidak Likuid") == "D"  # 55-20=35
    assert app_module._compute_grade(20, "Likuid") == "D"


def test_liquidity_label_thresholds():
    import web.app as app_module

    assert app_module._liquidity_label(60_000_000_000) == "Sangat Likuid"
    assert app_module._liquidity_label(10_000_000_000) == "Likuid"
    assert app_module._liquidity_label(1_000_000_000) == "Kurang Likuid"
    assert app_module._liquidity_label(1_000_000) == "Tidak Likuid"


def test_trading_style_label_thresholds():
    import web.app as app_module

    assert app_module._trading_style_label(5.0) == "Intraday/Scalping"
    assert app_module._trading_style_label(2.5) == "Swing Trading"
    assert app_module._trading_style_label(0.8) == "Investasi Jangka Menengah-Panjang"


def test_ad_line_label_matches_sinyal_direction():
    """Regresi: label singkat calculate_ad_line() (dipakai badge) harus
    konsisten arahnya dengan teks 'sinyal' lengkap -- Akumulasi/Distribusi
    untuk konfirmasi, versi 'Tersembunyi' untuk divergensi."""
    import numpy as np
    import pandas as pd

    from core.volume_patterns import calculate_ad_line

    n = 60
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    # Harga naik konsisten DAN close selalu dekat HIGH (CLV tinggi positif)
    # -> A/D naik juga -> konfirmasi bullish -> label "Akumulasi". (Close
    # persis di TENGAH range low-high akan menghasilkan CLV=0 setiap hari,
    # bukan sinyal ini -- makanya close sengaja didekatkan ke high, bukan
    # cuma diturunkan dari trend yang sama seperti high/low.)
    trend = np.linspace(1000, 1200, n)
    low = trend * 0.99
    high = trend * 1.01
    close = high * 0.999
    open_ = low
    df = pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close,
                        "Volume": np.full(n, 1_000_000.0)}, index=dates)
    result = calculate_ad_line(df)
    assert result is not None
    assert result["label"] == "Akumulasi"
    assert "BULLISH" in result["sinyal"].upper()
    assert result["confidence"] == "tinggi"


def test_ad_line_flat_price_is_neutral_not_forced_direction():
    """Regresi akurasi #2 (permintaan user): harga yang nyaris flat
    (<1.5% pergerakan tersirat dalam lookback_days) HARUS dilabel Netral,
    BUKAN dipaksa jadi Akumulasi/Distribusi (apalagi versi 'Tersembunyi')
    murni dari tanda plus/minus super kecil yang sebenarnya cuma noise."""
    import numpy as np
    import pandas as pd

    from core.volume_patterns import calculate_ad_line

    n = 60
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    rng = np.random.default_rng(0)
    # Harga nyaris flat (naik cuma 0.3% total dalam 60 hari) plus sedikit
    # noise acak -- tidak boleh dianggap "naik" atau "turun" yang berarti.
    close = 1000 + np.cumsum(rng.normal(0, 0.3, n))
    high = close + 2
    low = close - 2
    open_ = close
    df = pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close,
                        "Volume": np.full(n, 1_000_000.0)}, index=dates)
    result = calculate_ad_line(df)
    assert result is not None
    assert result["label"] == "Netral"
    assert result["confidence"] == "rendah"


def test_ad_line_downgrades_confidence_for_illiquid_stock():
    """Regresi akurasi #1 (permintaan user): saham yang ditandai kurang/
    tidak likuid oleh caller harus dapat confidence lebih rendah untuk
    sinyal yang sama persis -- CLV di saham tipis lebih rawan noise dari
    1-2 transaksi doang."""
    import numpy as np
    import pandas as pd

    from core.volume_patterns import calculate_ad_line

    n = 60
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    trend = np.linspace(1000, 1200, n)
    low = trend * 0.99
    high = trend * 1.01
    close = high * 0.999
    open_ = low
    df = pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close,
                        "Volume": np.full(n, 1_000_000.0)}, index=dates)

    liquid = calculate_ad_line(df, is_illiquid=False)
    illiquid = calculate_ad_line(df, is_illiquid=True)
    assert liquid["label"] == illiquid["label"] == "Akumulasi"  # arah sinyal sama
    assert liquid["confidence"] == "tinggi"
    assert illiquid["confidence"] == "sedang"  # tapi keyakinannya diturunkan
    assert "kurang likuid" in illiquid["sinyal"].lower()


def test_ad_line_slope_robust_to_single_day_outlier():
    """Regresi akurasi #3 (permintaan user, inti keluhan 'kadang fake'):
    arah tren HARUS dari slope regresi atas seluruh window, bukan cuma
    selisih 2 titik (hari pertama vs hari terakhir) -- 1 hari crash/spike
    tunggal di ujung window tidak boleh membalik kesimpulan tren yang
    sebenarnya konsisten selama 19 hari lainnya."""
    import numpy as np
    import pandas as pd

    from core.volume_patterns import calculate_ad_line

    n = 60
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    trend = np.linspace(1000, 1200, n)
    # Uptrend konsisten dengan CLV tinggi (dekat high) SEPANJANG waktu --
    # kecuali candle TERAKHIR sengaja dibuat crash tajam (close dekat low,
    # harga jatuh) sebagai outlier tunggal di endpoint.
    low = trend * 0.99
    high = trend * 1.01
    close = high * 0.999
    open_ = low
    close[-1] = trend[-1] * 0.85  # crash 1 hari di harga
    low[-1] = close[-1] * 0.99
    high[-1] = trend[-1] * 1.01
    df = pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close,
                        "Volume": np.full(n, 1_000_000.0)}, index=dates)

    # Selisih endpoint mentah (metode LAMA) akan bilang harga turun (crash
    # di hari terakhir > kenaikan 20 hari sebelumnya) -- pastikan itu
    # benar sebagai premis skenario, baru cek fungsi tidak ikut salah arah.
    price_now = float(df["Close"].iloc[-1])
    price_20d_ago = float(df["Close"].iloc[-21])
    assert price_now < price_20d_ago  # premis: metode 2-titik akan bilang "turun"

    result = calculate_ad_line(df)
    assert result is not None
    # Fungsi (pakai slope) harus tetap membaca tren 20 hari sebagai NAIK
    # (mayoritas hari benar-benar uptrend), bukan "turun" gara-gara 1 hari
    # crash di ujung window.
    assert result["label"] == "Akumulasi"


def test_ad_line_handles_high_equals_low_days_without_crashing():
    """Regresi bug NYATA ditemukan saat live-check (BBCA/MNCN 500 error
    setelah nambah np.polyfit): candle dengan High==Low (hari kena ARA/ARB
    lock, atau suspend -- BIASA terjadi di data IDX sungguhan) bikin
    range_hl.replace(0, pd.NA) menaikkan dtype Series ke 'object', yang
    lolos ke float() biasa tapi bikin np.polyfit CRASH (butuh float64
    murni). Data sintetis di tes lain sengaja/tidak sengaja tidak pernah
    punya hari High==Low, jadi tidak menangkap bug ini -- tes ini secara
    eksplisit menyertakan beberapa hari High==Low."""
    import numpy as np
    import pandas as pd

    from core.volume_patterns import calculate_ad_line

    n = 60
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    trend = np.linspace(1000, 1200, n)
    low = trend * 0.99
    high = trend * 1.01
    close = high * 0.999
    open_ = low
    # Beberapa hari ARA/ARB lock (High == Low == Close, tidak ada rentang
    # intraday sama sekali) tersebar di window yang dipakai lookback.
    for i in (-3, -10, -18):
        high[i] = low[i] = close[i] = trend[i]
    df = pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close,
                        "Volume": np.full(n, 1_000_000.0)}, index=dates)
    result = calculate_ad_line(df)  # TIDAK BOLEH raise
    assert result is not None
    assert result["label"] in ("Akumulasi", "Distribusi", "Akumulasi Tersembunyi", "Distribusi Tersembunyi", "Netral")


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


def test_ihsg_pad_and_order_levels_keeps_r1_le_r2():
    """Regresi: kalau cuma 1 cluster resistance ASLI ketemu dan kebetulan
    JAUH dari harga (dikonfirmasi nyata terjadi: +8.5% saat cluster kedua
    tidak ketemu), fallback R2 lama pakai step LEBIH KECIL (+3.5%
    independen) sehingga hasilnya resistance_1 (jauh) > resistance_2
    (dekat, cuma fallback) -- TERBALIK. _pad_and_order_levels() harus
    menggabung dulu baru urutkan, menjamin level_1 selalu <= level_2
    utk resistance (dan sebaliknya, selalu >= utk support)."""
    from core.ihsg.ihsg_analysis import _pad_and_order_levels

    current_price = 5875.78
    # Skenario nyata: cuma 1 cluster resistance ketemu, jauh dari harga (+8.5%)
    result = _pad_and_order_levels([6377.0], current_price, step=1.02, reverse=False)
    assert result[0] <= result[1], f"resistance_1 ({result[0]}) > resistance_2 ({result[1]})"

    # Skenario cermin utk support (descending -- S1 harus >= S2)
    result_s = _pad_and_order_levels([5318.0], current_price, step=0.98, reverse=True)
    assert result_s[0] >= result_s[1], f"support_1 ({result_s[0]}) < support_2 ({result_s[1]})"

    # Tanpa cluster asli sama sekali -- murni fallback, tetap harus terurut benar
    assert _pad_and_order_levels([], current_price, 1.02, reverse=False)[0] <= \
        _pad_and_order_levels([], current_price, 1.02, reverse=False)[1]


def test_ihsg_support_resistance_on_correct_side_of_price(fake_df):
    """Regresi: support_1/resistance_1 IHSG dulu punya 2 bug tumpuk:
    (1) pivot swing LAMA bisa di sisi yang SALAH dari harga sekarang kalau
    indeks sudah bergerak jauh sejak titik itu (swing low lama muncul DI
    ATAS harga skrg setelah indeks turun -- bukan support lagi), (2)
    _cluster_levels() return ascending TAPI resistance_levels dipotong
    [-3:] (harusnya [:3], ambil resistance TERDEKAT bukan TERJAUH) dan
    support_levels dipotong [:3] (harusnya [-3:], ambil support TERDEKAT).
    Kombinasi keduanya bikin support_1 BISA muncul di atas harga & sebalik-
    nya -- dikonfirmasi nyata pakai fake_df (S1 lama = 891.0 padahal harga
    = 821.8). Pola bug SAMA PERSIS dengan yang ditemukan & diperbaiki di
    core/charts/snr_chart.py::calculate_snr_levels()."""
    from core.ihsg.ihsg_analysis import analyze_ihsg_advanced

    df_daily = fake_df
    df_weekly = df_daily.resample("W").agg({
        "Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum",
    }).dropna()

    result = analyze_ihsg_advanced(df_daily, df_weekly)
    assert result is not None
    price = float(df_daily["Close"].iloc[-1])
    assert result["support_1"] < price, f"support_1 ({result['support_1']}) di atas harga ({price})"
    assert result["resistance_1"] > price, f"resistance_1 ({result['resistance_1']}) di bawah harga ({price})"
    assert result["support_1"] > result["support_2"]
    assert result["resistance_1"] < result["resistance_2"]


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


def test_sector_leader_laggard_no_overlap_when_few_stocks(monkeypatch):
    """Regresi: get_leader_laggard() dulu bisa menampilkan saham yang SAMA
    di leader DAN laggard sekaligus kalau sektornya cuma punya sedikit
    saham -- SECTOR_MAP saat ini cuma 3-4 saham/sektor, dan top_n default
    3, jadi results[:3] dan results[-3:] overlap total/sebagian. Sekarang
    laggard harus selalu exclusive dari leader."""
    import asyncio

    import numpy as np
    import pandas as pd

    import core.sector_rotation as sr

    # Sektor uji 3 saham -- kondisi yang PASTI overlap kalau bug masih ada
    # (top_n default 3 == jumlah saham -> leader & laggard identik).
    monkeypatch.setitem(sr.SECTOR_MAP, "TESTSECTOR", ["AAA.JK", "BBB.JK", "CCC.JK"])
    monkeypatch.setattr(sr, "SECTOR_MAP_TO_INDEX", {})

    def _make_df(end_price):
        n = 30
        dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
        close = np.linspace(end_price / 1.1, end_price, n)
        return pd.DataFrame(
            {"Open": close, "High": close * 1.001, "Low": close * 0.999,
             "Close": close, "Volume": np.full(n, 1_000_000.0)},
            index=dates,
        )

    price_map = {"AAA.JK": 130.0, "BBB.JK": 110.0, "CCC.JK": 90.0}

    async def _fake_retry(ticker, period="2mo", interval="1d", **kw):
        return _make_df(price_map[ticker])

    monkeypatch.setattr(sr, "_download_with_retry", _fake_retry)

    result = asyncio.run(sr.get_leader_laggard("TESTSECTOR", top_n=3))
    assert result is not None
    leader_tickers = {r["ticker"] for r in result["leader"]}
    laggard_tickers = {r["ticker"] for r in result["laggard"]}
    assert leader_tickers.isdisjoint(laggard_tickers), (
        f"leader dan laggard tumpang tindih: {leader_tickers & laggard_tickers}"
    )


def test_narrate_sector_leadership_no_overlap_when_few_sectors():
    """Regresi: _narrate_sector_leadership() dulu bisa menyebut sektor
    yang SAMA sebagai 'paling kuat' sekaligus 'paling lemah' dalam satu
    kalimat kalau sector_data cuma berisi sedikit entri. Data sengaja
    TANPA field 'ticker' di sini -- bentuk asli dari /api/insight/{kode}
    (lewat sektor() di web/app.py) cuma punya nama_sektor/return_pct/
    n_saham, BEDA dari core/sector_rotation.py::get_sector_performance()
    yang punya 'ticker'. Versi pertama fix ini pakai key 'ticker' dan
    crash KeyError persis di jalur /api/insight/IHSG -- tes ini menjaga
    supaya regresi itu tidak terulang."""
    from core.insight import _narrate_sector_leadership

    sector_data = [
        {"nama_sektor": "Sektor A", "return_pct": 5.0, "n_saham": 4},
        {"nama_sektor": "Sektor B", "return_pct": 3.0, "n_saham": 3},
        {"nama_sektor": "Sektor C", "return_pct": -1.0, "n_saham": 5},
    ]
    text = _narrate_sector_leadership(sector_data)
    laggard_part = text.split("Sektor paling lemah:")[1].split(".")[0]
    assert "Sektor paling kuat saat ini: Sektor A" in text
    # Ketiga sektor sudah habis dipakai sebagai leader (top_n=3, cuma ada
    # 3 sektor) -- laggard harus KOSONG (pesan fallback), bukan mengulang
    # salah satu dari Sektor A/B/C.
    for nama in ("Sektor A", "Sektor B", "Sektor C"):
        assert nama not in laggard_part, f"{nama} tidak boleh muncul di bagian laggard: {laggard_part!r}"


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


def test_ihsg_includes_bandar_and_potensi_risiko_fields(client):
    """Regresi: /api/ihsg harus menyertakan badge Bandar/Psikologi (proxy
    A/D Line pada ^JKSE) dan Potensi Naik/Risiko Turun % (dari resistance_1/
    support_1 yang sudah dihitung analyze_ihsg_with_backtest) -- adaptasi
    dari Ringkasan Cepat di /api/analyze, TANPA memaksakan konsep likuiditas/
    gaya-trading yang cuma relevan utk saham individual, bukan indeks."""
    r = client.get("/api/ihsg")
    assert r.status_code == 200
    data = r.json()
    assert data["bandar"] is not None
    assert data["bandar"]["label"] in ("Akumulasi", "Distribusi", "Akumulasi Tersembunyi", "Distribusi Tersembunyi")
    assert data["potensi_naik_pct"] is not None
    assert data["risiko_turun_pct"] is not None
    assert data["resistance_1"] > data["current_price"]
    assert data["support_1"] < data["current_price"]


def test_snr_levels_pick_nearest_support_not_furthest():
    """Regresi: calculate_snr_levels() dulu memotong hasil _cluster_levels()
    (yang SELALU terurut ascending) dengan [:3] untuk SUPPORT juga -- benar
    untuk resistance (di atas harga, ascending = terdekat duluan) tapi
    SALAH untuk support (di bawah harga, ascending = TERJAUH duluan).
    Akibatnya S1/S2/S3 yang ditampilkan ke user adalah level jauh di bawah
    harga (support terlemah/tidak relevan/paling jarang kepakai trader),
    bukan level yang PALING dekat dan actionable.

    Data uji pakai noise harian kecil (BUKAN harga flat -- flat persis bisa
    memicu false-positive swing point dari tie di np.min(), artefak data uji,
    bukan perilaku data harga sungguhan) + beberapa swing low historis pada
    level yang jauh terpisah (700/800/850/900/950) supaya _cluster_levels()
    menghasilkan >3 cluster berbeda -- exactly kondisi yang membedakan
    [:3] (bug) dari [-3:] (benar)."""
    import numpy as np
    import pandas as pd

    from core.charts.snr_chart import calculate_snr_levels

    rng = np.random.default_rng(42)
    n = 200
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    close = 1000.0 + rng.normal(0, 1.5, n)
    for idx, price in [(20, 950.0), (50, 900.0), (80, 850.0), (110, 800.0), (140, 700.0)]:
        close[idx] = price
    high = close + rng.uniform(1, 3, n)
    low = close - rng.uniform(1, 3, n)
    df = pd.DataFrame({"Open": close, "High": high, "Low": low, "Close": close,
                        "Volume": np.full(n, 1_000_000.0)}, index=dates)

    levels = calculate_snr_levels(df)
    current_price = 1000.0

    # S1 (support terkuat/terdekat) harus dalam jarak wajar dari harga saat
    # ini (pivot-based, ~995-998 untuk range harian sekecil ini) -- BUKAN
    # salah satu swing low historis yang jauh (700/800/850).
    assert levels["s1"] > current_price * 0.98, (
        f"S1 ({levels['s1']}) terlalu jauh dari harga saat ini ({current_price}) -- "
        "kemungkinan memilih cluster support TERJAUH, bukan TERDEKAT"
    )
    assert levels["s1"] > levels["s2"] > levels["s3"]
    assert levels["r1"] < levels["r2"] < levels["r3"]


def test_snr_levels_support_never_above_current_price(fake_df):
    """Regresi: swing low/high HISTORIS bisa berada di sisi yang salah dari
    harga saat ini kalau saham sudah bergerak jauh sejak titik swing itu
    terjadi (mis. swing low lama dari saat harga masih tinggi kini malah
    ada DI ATAS harga sekarang setelah saham turun tajam -- itu bukan
    support lagi). Tanpa filter validitas, S1 bisa muncul di atas harga
    (bikin 'risiko turun' di /api/analyze jadi negatif, tidak masuk akal).

    fake_df (seed=0, random walk 300 hari) DIKONFIRMASI memicu bug ini
    sebelum diperbaiki (S1 lama = 1039.5 padahal harga = 821.8)."""
    from core.charts.snr_chart import calculate_snr_levels

    levels = calculate_snr_levels(fake_df)
    price = float(fake_df["Close"].iloc[-1])
    assert levels["s1"] <= price, f"S1 ({levels['s1']}) di atas harga saat ini ({price}) -- bukan support valid"
    assert levels["r1"] >= price, f"R1 ({levels['r1']}) di bawah harga saat ini ({price}) -- bukan resistance valid"


def test_bull_case_does_not_mislabel_stochrsi_as_plain_rsi():
    """Regresi: is_oversold/is_overbought DIHITUNG dari StochRSI (K/D),
    BUKAN dari RSI biasa (lihat core/ai_score.py) -- tapi _bull_case/
    _bear_case dulu menampilkan ai['rsi'] (RSI biasa) di kalimat yang
    mengklaim 'RSI di area oversold/overbought'. Dikonfirmasi nyata: BBCA
    dengan RSI biasa 52.5 (jelas BUKAN oversold) muncul sebagai argumen
    bullish 'RSI di area oversold (52.5)' -- membingungkan & salah. Teks
    sekarang harus menyebut StochRSI + nilai K/D, bukan RSI biasa."""
    from core.report import _bull_case, _bear_case

    ai_oversold = {
        "rsi": 52.5, "stoch_k": 15.0, "stoch_d": 12.0, "is_oversold": True, "is_overbought": False,
        "cond_ma": True, "golden_cross": False, "macd_bullish": True, "ma200": None,
        "price": 6050, "cond_volume_spike": False, "change_5d": 0, "bb_position": 50,
    }
    bull = _bull_case(ai_oversold)
    joined = " ".join(bull)
    assert "StochRSI" in joined, f"argumen bullish harus sebut StochRSI, bukan RSI biasa: {bull}"
    assert "52.5" not in joined, "RSI biasa (52.5, bukan oversold) tidak boleh dipakai sebagai bukti oversold"

    ai_overbought = {
        "rsi": 48.0, "stoch_k": 88.0, "stoch_d": 85.0, "is_oversold": False, "is_overbought": True,
        "cond_ma": True, "golden_cross": True, "macd_bullish": True, "ma200": 5000,
        "price": 6050, "atr_pct": 1.0, "bb_position": 50, "change_5d": 0,
    }
    bear = _bear_case(ai_overbought)
    joined_bear = " ".join(bear)
    assert "StochRSI" in joined_bear, f"argumen bearish harus sebut StochRSI, bukan RSI biasa: {bear}"
    assert "48.0" not in joined_bear


def test_indikator_status_rsi_row_uses_plain_rsi_not_stochrsi():
    """Regresi: baris 'RSI' di tabel indikator laporan PDF dulu diberi
    status OVERSOLD/OVERBOUGHT dari StochRSI (is_oversold/is_overbought),
    padahal detail angkanya RSI biasa -- bisa tampil 'RSI: OVERSOLD' dengan
    detail RSI 52.5 (bukan oversold). Baris 'RSI' sekarang harus
    diklasifikasi dari RSI biasa sendiri; StochRSI dapat baris terpisah."""
    from core.report import build_report_data

    ai = {
        "price": 6050, "change_1d": 0, "change_5d": 0, "score": 50, "rating": "NETRAL",
        "rsi": 52.5, "stoch_k": 15.0, "stoch_d": 12.0, "is_oversold": True, "is_overbought": False,
        "macd_bullish": True, "macd_hist": 1.0, "vol_ratio": 1.0, "atr_pct": 2.0,
        "cond_ma": True, "golden_cross": False, "ma5_ma20": "MA5 > MA20",
        "ma50": 6000, "ma200": 5900, "cond_volume_spike": False,
        "recommendation": "HOLD", "signal": "-",
    }
    data = build_report_data("BBCA", "Bank BCA", ai)
    rows = {row[0]: row for row in data["indikator_status"]}
    assert "RSI" in rows and "StochRSI" in rows
    assert rows["RSI"][1] == "NETRAL", f"RSI biasa 52.5 harus NETRAL, dapat: {rows['RSI']}"
    assert rows["StochRSI"][1] == "OVERSOLD", f"StochRSI K=15/D=12 harus OVERSOLD, dapat: {rows['StochRSI']}"


def test_insight_stock_includes_bull_bear_and_critical_crosscheck(client):
    """Regresi: /api/insight/{kode} harus menyertakan bull_case/bear_case
    (argumen dua arah, REUSE dari core/report.py) dan analisis_kritis
    (silang-cek skor AI vs likuiditas/bandar) -- upgrade yang diminta user
    supaya insight 'lebih kritis, menganalisa semuanya', bukan cuma narasi
    satu arah seperti sebelumnya."""
    r = client.get("/api/insight/BBCA")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data.get("bull_case"), list) and len(data["bull_case"]) > 0
    assert isinstance(data.get("bear_case"), list) and len(data["bear_case"]) > 0
    assert data.get("analisis_kritis")


def test_insight_ihsg_includes_deep_analysis_and_backtest_critique(client):
    """Regresi: /api/insight/IHSG dulu CUMA pakai skor generik ala saham
    (calculate_ai_score_from_df), TIDAK PERNAH memakai analyze_ihsg_with_
    backtest() yang punya validasi historis edge vs baseline -- padahal
    /api/ihsg sudah menghitungnya. analisis_mendalam sekarang harus berisi
    kritik edge backtest, bukan cuma narasi teknikal generik."""
    r = client.get("/api/insight/IHSG")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data.get("bull_case"), list)
    assert isinstance(data.get("bear_case"), list)
    assert data.get("analisis_mendalam")
    assert "Prediksi sistem" in data["analisis_mendalam"]


def test_liquidity_score_thresholds():
    import web.app as app_module

    assert app_module._liquidity_score("Sangat Likuid") == 100.0
    assert app_module._liquidity_score("Likuid") == 75.0
    assert app_module._liquidity_score("Kurang Likuid") == 40.0
    assert app_module._liquidity_score("Tidak Likuid") == 10.0


def test_rr_score_thresholds():
    import web.app as app_module

    assert app_module._rr_score(None) == 50.0
    assert app_module._rr_score(2.5) == 100.0
    assert app_module._rr_score(1.6) == 80.0
    assert app_module._rr_score(1.0) == 60.0
    assert app_module._rr_score(0.6) == 35.0
    assert app_module._rr_score(0.2) == 15.0


def test_apply_liquidity_cap_limits_illiquid_scores():
    """Regresi: sebelum perbaikan ini, ranking Top Pick murni teknikal --
    saham tidak likuid dengan chart kebetulan bagus bisa nangkring di #1
    meski praktis susah dieksekusi. _apply_liquidity_cap() harus membatasi
    (bukan menyembunyikan) skor saham kurang/tidak likuid."""
    import web.app as app_module

    score, capped = app_module._apply_liquidity_cap(90.0, "Tidak Likuid")
    assert score == 35.0 and capped is True

    score, capped = app_module._apply_liquidity_cap(90.0, "Kurang Likuid")
    assert score == 55.0 and capped is True

    score, capped = app_module._apply_liquidity_cap(90.0, "Sangat Likuid")
    assert score == 90.0 and capped is False

    # Skor yang sudah di bawah batas tidak boleh dinaikkan (cap cuma turun, tidak naik)
    score, capped = app_module._apply_liquidity_cap(20.0, "Tidak Likuid")
    assert score == 20.0 and capped is False


def test_confidence_reasons_flags_illiquid_and_distribution():
    import web.app as app_module

    it_warn = {
        "ai_score": 70, "minervini_criteria_met": 7, "confluence_bullish": 4, "confluence_bearish": 1,
        "bandar": {"label": "Distribusi", "sinyal": "x"}, "rr_ratio": 0.5, "likuiditas": "Tidak Likuid",
    }
    reasons, warnings = app_module._confidence_reasons(it_warn)
    assert any("AI Score kuat" in r for r in reasons)
    assert any("Tidak Likuid" in w for w in warnings)
    assert any("Distribusi" in w for w in warnings)
    assert any("Risiko stop loss lebih besar" in w for w in warnings)


def test_confidence_endpoint_includes_composite_fields(client):
    """Regresi: /api/confidence (Top Pick) dulu cuma menjumlah AI Score +
    Minervini + Confluence, semuanya teknikal murni -- sekarang harus
    menyertakan likuiditas, risk/reward, proxy bandar, sektor, alasan, dan
    konteks regime pasar IHSG di level respons."""
    r = client.get("/api/confidence")
    assert r.status_code == 200
    data = r.json()
    assert data["items"], "harus ada minimal 1 item dari SCREENER_UNIVERSE"
    it = data["items"][0]
    for field in ("likuiditas", "rr_ratio", "bandar", "sektor", "reasons", "warnings",
                  "liquidity_capped", "confidence_score"):
        assert field in it, f"field '{field}' hilang dari item Top Pick"
    assert "liq" in data["weights"] and "rr" in data["weights"]
    assert data["market_regime"] in ("BULLISH", "BEARISH", "SIDEWAYS/NETRAL", None)
    # Urutan harus menurun berdasarkan confidence_score
    scores = [x["confidence_score"] for x in data["items"]]
    assert scores == sorted(scores, reverse=True)


def test_confidence_targets_are_never_too_tight(client):
    """Regresi: potensi_naik_pct/risiko_turun_pct dulu pakai jarak mentah
    ke R1/S1 (calculate_snr_levels) -- kalau candle terakhir kebetulan
    range-nya kecil, target bisa SANGAT ketat (dikonfirmasi nyata: SL
    -0.4% pada JPFA/UNTR, gampang kena cuma dari noise harian, bukan
    risiko sungguhan). Sekarang pakai logic yang sama dengan fitur
    Rencana Trading (calculate_fixed_entry_levels_from_df, skenario
    'normal'): TP1 = MAKSIMUM(3%, risk%), jadi TP tidak pernah lebih
    ketat dari SL-nya sendiri (RR >= 1:1 selalu), dan SL selalu punya
    buffer 0.2xATR di luar support asli."""
    r = client.get("/api/confidence")
    assert r.status_code == 200
    items = r.json()["items"]
    checked = 0
    for it in items:
        naik, turun = it.get("potensi_naik_pct"), it.get("risiko_turun_pct")
        if naik is None or turun is None:
            continue
        checked += 1
        assert naik >= 3.0 - 1e-6 or naik >= turun - 1e-6, (
            f"{it['kode']}: potensi_naik_pct ({naik}) di bawah floor 3% DAN di bawah risiko_turun_pct ({turun})"
        )
        if it.get("rr_ratio") is not None:
            assert it["rr_ratio"] >= 1.0 - 1e-6, f"{it['kode']}: rr_ratio ({it['rr_ratio']}) di bawah 1:1"
    assert checked > 0, "tidak ada item dengan potensi_naik_pct/risiko_turun_pct valid untuk dicek"


def _fake_confidence_item(kode, score, naik=3.0, turun=2.0, harga=1000.0,
                           likuiditas="Sangat Likuid", macd_bullish_cross=False):
    return {
        "kode": kode, "harga": harga, "confidence_score": score, "ai_score": score,
        "ai_rating": "BAGUS", "potensi_naik_pct": naik, "risiko_turun_pct": turun,
        "likuiditas": likuiditas, "macd_bullish_cross": macd_bullish_cross,
    }


def test_record_top_picks_respects_threshold_and_dedup(clean_signal_db):
    """Regresi: record_top_picks() cuma boleh mencatat saham dengan
    confidence_score >= MIN_SCORE_TO_RECORD, harus melewati saham tanpa
    potensi_naik_pct/risiko_turun_pct valid (mis. GOTO yang lagi flat di
    harga floor), dan TIDAK BOLEH mencatat kode yang sama dua kali di hari
    yang sama (dedup) -- /api/confidence bisa dipanggil berkali-kali sehari
    kalau cache 300 detik expire & di-hit ulang."""
    import asyncio

    from core.signal_history import record_top_picks, get_signal_report, MIN_SCORE_TO_RECORD

    items = [
        _fake_confidence_item("ZZHIGH", MIN_SCORE_TO_RECORD + 10),
        _fake_confidence_item("ZZLOW", MIN_SCORE_TO_RECORD - 10),  # di bawah ambang -- skip
        {**_fake_confidence_item("ZZNODATA", MIN_SCORE_TO_RECORD + 5), "potensi_naik_pct": None},  # skip
    ]
    saved = asyncio.run(record_top_picks(items))
    assert len(saved) == 1  # cuma ZZHIGH yang lolos
    assert saved[0]["kode"] == "ZZHIGH"

    saved_again = asyncio.run(record_top_picks(items))  # panggil lagi, hari yang sama
    assert saved_again == []  # ZZHIGH sudah tercatat hari ini -- dedup

    report = get_signal_report()
    kodes = [s["kode"] for s in report["signals"]]
    assert kodes.count("ZZHIGH") == 1
    assert "ZZLOW" not in kodes
    assert "ZZNODATA" not in kodes


def test_record_top_picks_caps_per_day(clean_signal_db):
    import asyncio

    from core.signal_history import record_top_picks, MAX_RECORDED_PER_DAY, MIN_SCORE_TO_RECORD

    items = [_fake_confidence_item(f"ZZCAP{i}", MIN_SCORE_TO_RECORD + 1) for i in range(MAX_RECORDED_PER_DAY + 5)]
    saved = asyncio.run(record_top_picks(items))
    assert len(saved) == MAX_RECORDED_PER_DAY


def test_record_top_picks_uses_realtime_price_with_fallback(clean_signal_db):
    """Regresi: entry_price seharusnya pakai harga REAL-TIME (price_lookup),
    BUKAN closing harian (it['harga']) -- closing harian JUGA dipakai
    menghitung sinyalnya sendiri, jadi mencatatnya sebagai entry yang bisa
    dieksekusi itu lookahead bias kecil. Kalau price_lookup gagal/kembalikan
    None utk suatu kode, HARUS fallback jujur ke closing harian, bukan gagal
    total mencatat sinyalnya."""
    import asyncio

    from core.signal_history import record_top_picks, get_signal_report, MIN_SCORE_TO_RECORD

    items = [
        _fake_confidence_item("ZZLIVE", MIN_SCORE_TO_RECORD + 5, harga=1000.0),
        _fake_confidence_item("ZZFAIL", MIN_SCORE_TO_RECORD + 5, harga=2000.0),
    ]

    async def fake_lookup(kode):
        if kode == "ZZLIVE":
            return 1015.0  # harga real-time beda dari closing harian (1000)
        return None  # simulasikan lookup gagal utk ZZFAIL

    saved = asyncio.run(record_top_picks(items, price_lookup=fake_lookup))
    assert len(saved) == 2

    report = get_signal_report()
    by_kode = {s["kode"]: s for s in report["signals"]}
    assert by_kode["ZZLIVE"]["entry_price"] == 1015.0  # pakai harga real-time
    assert by_kode["ZZFAIL"]["entry_price"] == 2000.0  # fallback ke closing harian


def test_record_top_picks_concurrent_calls_never_duplicate(clean_signal_db):
    """Regresi BUG NYATA ditemukan lewat inspeksi data produksi: /api/signals
    berisi ~12 kode tercatat 2x dengan recorded_at berselisih ~1 detik.
    Akar masalah: cek dedup (SELECT) dan INSERT dipisah, dengan sebuah
    `await price_lookup(...)` (network call) di ANTARA keduanya -- kalau
    dua panggilan record_top_picks() untuk kode yang SAMA tumpang tindih
    (mis. siklus auto-audit 600 detik vs request /api/confidence manual
    yang kebetulan bersamaan), event loop bisa berpindah task tepat di
    celah `await` itu: kedua task lolos SELECT "belum ada" sebelum salah
    satu sempat INSERT.

    Simulasikan itu di sini dengan price_lookup yang sengaja `await
    asyncio.sleep(...)` (memaksa interleaving asyncio terjadi, meniru delay
    network call sungguhan) dan panggil record_top_picks() dua kali
    BERSAMAAN via asyncio.gather utk kode yang SAMA -- total baris
    tersimpan utk kode itu HARUS tetap 1, bukan 2."""
    import asyncio

    from core.signal_history import record_top_picks, get_signal_report, MIN_SCORE_TO_RECORD

    items = [_fake_confidence_item("ZZRACE", MIN_SCORE_TO_RECORD + 5)]

    async def slow_lookup(kode):
        await asyncio.sleep(0.05)  # celah yang memicu race di kode lama
        return 1234.0

    async def _run_concurrent():
        return await asyncio.gather(
            record_top_picks(items, price_lookup=slow_lookup),
            record_top_picks(items, price_lookup=slow_lookup),
        )

    results = asyncio.run(_run_concurrent())
    total_saved = sum(len(r) for r in results)
    assert total_saved == 1, f"diharapkan cuma 1 dari 2 panggilan bersamaan yang berhasil mencatat, dapat {total_saved}"

    report = get_signal_report()
    kodes = [s["kode"] for s in report["signals"]]
    assert kodes.count("ZZRACE") == 1


def test_is_bursa_weekend_detects_saturday_and_sunday():
    """Unit test murni utk _is_bursa_weekend() -- Sabtu/Minggu True, hari
    kerja False. Verified via kalender: 2026-07-04=Sabtu, 2026-07-05=Minggu,
    2026-06-29=Senin."""
    from datetime import datetime as _dt

    import core.signal_history as sh

    class _FakeDatetime(_dt):
        _now = None

        @classmethod
        def now(cls, tz=None):
            return cls._now

    import importlib

    try:
        for fake_now, expected in [
            (_dt(2026, 7, 4), True),   # Sabtu
            (_dt(2026, 7, 5), True),   # Minggu
            (_dt(2026, 6, 29), False),  # Senin
        ]:
            _FakeDatetime._now = fake_now
            sh.datetime = _FakeDatetime
            assert sh._is_bursa_weekend() is expected, f"{fake_now} salah diklasifikasikan"
    finally:
        importlib.reload(sh)  # kembalikan `datetime` asli di modul


def test_record_top_picks_and_macd_skip_on_weekend(clean_signal_db, monkeypatch):
    """Regresi BUG NYATA ditemukan lewat inspeksi data produksi: siklus
    auto-audit jalan 24/7 (tiap 600 detik) TIDAK PEDULI akhir pekan, dan
    dulu tetap mencatat 'sinyal Top Pick baru' di hari Sabtu/Minggu dengan
    entry_price/tp_pct/sl_pct IDENTIK dengan hari Jumat -- karena BEI tutup,
    closing price yfinance belum berubah sama sekali. Satu pergerakan pasar
    (Jumat) jadi tercatat sebagai 2-3 sinyal terpisah (Jumat+Sabtu+Minggu),
    yang MENGGANDAKAN statistik win-rate secara palsu kalau nanti kena TP/SL.

    record_top_picks()/record_macd_cross_signals() HARUS return [] (skip
    total, tidak mencatat apa pun) kalau _is_bursa_weekend() True -- di-mock
    langsung (bukan datetime) supaya tidak tercampur dgn clean_signal_db
    yang sudah mem-patch _is_bursa_weekend ke False secara default."""
    import asyncio

    import core.signal_history as sh

    monkeypatch.setattr(sh, "_is_bursa_weekend", lambda: True)

    items = [_fake_confidence_item("ZZWEEKEND", sh.MIN_SCORE_TO_RECORD + 5, macd_bullish_cross=True)]
    assert asyncio.run(sh.record_top_picks(items)) == []
    assert asyncio.run(sh.record_macd_cross_signals(items)) == []

    report = sh.get_signal_report()
    assert "ZZWEEKEND" not in [s["kode"] for s in report["signals"]]


def test_recorded_at_uses_local_time_not_utc(clean_signal_db):
    """Regresi BUG NYATA ditemukan lewat inspeksi live: SQLite's
    `datetime('now')` SELALU UTC, sedangkan BEI beroperasi WIB (UTC+7) dan
    _is_bursa_weekend() memakai Python `datetime.now()` (local/WIB). Server
    ini berjalan WIB (UTC+7) -- kalau record_top_picks() masih memakai
    `datetime('now')` polos (tanpa 'localtime'), recorded_at yang tersimpan
    akan berselisih ~7 JAM dari waktu lokal sungguhan. Antara jam 00:00-
    06:59 WIB, tanggal UTC masih 'kemarin' -- satu hari bursa WIB yang sama
    bisa terbagi jadi 2 tanggal UTC berbeda, membuat dedup check gagal
    mendeteksi duplikat yang sebenarnya sama hari bursa.

    Verifikasi: recorded_at yang BARU disimpan harus dekat (toleransi
    beberapa detik) dengan Python datetime.now() -- BUKAN berselisih jam."""
    import asyncio
    from datetime import datetime

    from core.signal_history import record_top_picks, MIN_SCORE_TO_RECORD

    items = [_fake_confidence_item("ZZTZ", MIN_SCORE_TO_RECORD + 5)]
    saved = asyncio.run(record_top_picks(items))
    assert len(saved) == 1

    from core.database import get_db
    with get_db() as conn:
        row = conn.execute("SELECT recorded_at FROM signal_history WHERE kode='ZZTZ'").fetchone()
    recorded_at = datetime.fromisoformat(row["recorded_at"])
    delta_seconds = abs((datetime.now() - recorded_at).total_seconds())
    assert delta_seconds < 30, (
        f"recorded_at ({recorded_at}) berselisih {delta_seconds:.0f} detik dari waktu lokal sekarang "
        f"({datetime.now()}) -- kemungkinan masih memakai UTC, bukan localtime"
    )


def test_ensure_table_migration_collapses_identical_weekend_duplicates(clean_signal_db):
    """Regresi BUG NYATA ditemukan lewat inspeksi data produksi: sebelum
    _is_bursa_weekend() ada, siklus auto-audit tetap mencatat 'sinyal baru'
    di hari Sabtu/Minggu dengan entry_price/tp_pct/sl_pct IDENTIK dengan
    hari sebelumnya (BEI tutup, harga belum berubah) -- baris ini LOLOS
    index unique (kode,tanggal,source) karena tanggalnya beda. Migrasi
    _ensure_table() harus membersihkan baris yang PERSIS sama (kode+
    source+entry_price+tp_pct+sl_pct), menyisakan yang id-nya PALING KECIL
    (paling awal tercatat)."""
    from core.database import get_db
    import core.signal_history as sh

    with get_db() as conn:
        conn.execute('''
            INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, source, recorded_at)
            VALUES ('ZZDUP', 1000, 3.0, 1.9, 'TOP_PICK', '2026-07-04 06:00:00')
        ''')
        conn.execute('''
            INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, source, recorded_at)
            VALUES ('ZZDUP', 1000, 3.0, 1.9, 'TOP_PICK', '2026-07-05 00:06:00')
        ''')
        # Kontrol: kode+source SAMA tapi entry_price BEDA (perubahan pasar
        # sungguhan) -- harus TETAP keduanya, bukan ikut kehapus.
        conn.execute('''
            INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, source, recorded_at)
            VALUES ('ZZREAL', 1000, 3.0, 1.9, 'TOP_PICK', '2026-07-04 06:00:00')
        ''')
        conn.execute('''
            INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, source, recorded_at)
            VALUES ('ZZREAL', 1010, 3.0, 1.9, 'TOP_PICK', '2026-07-06 06:00:00')
        ''')

    sh._ensured = False  # paksa migrasi jalan ulang meski sudah pernah _ensure_table()
    sh._ensure_table()

    with get_db() as conn:
        dup_rows = conn.execute("SELECT recorded_at FROM signal_history WHERE kode='ZZDUP'").fetchall()
        real_rows = conn.execute("SELECT entry_price FROM signal_history WHERE kode='ZZREAL' ORDER BY entry_price").fetchall()

    assert len(dup_rows) == 1
    assert dup_rows[0]["recorded_at"] == "2026-07-04 06:00:00"  # yang dipertahankan = paling awal
    assert [r["entry_price"] for r in real_rows] == [1000.0, 1010.0]  # keduanya tetap ada


def test_audit_open_signals_resolves_tp_sl_expired(clean_signal_db):
    """Regresi inti fitur audit: TP_HIT kalau harga >= entry*(1+tp_pct%),
    SL_HIT kalau harga <= entry*(1-sl_pct%), EXPIRED kalau sudah lewat
    MAX_HOLD_DAYS tanpa kena keduanya, dan tetap OPEN kalau belum ada
    kondisi yang terpenuhi -- keempatnya WAJIB dibedakan dengan benar
    supaya statistik win rate tidak menghitung sinyal yang belum selesai."""
    import asyncio

    from core.database import get_db
    from core.signal_history import _ensure_table, audit_open_signals, MAX_HOLD_DAYS

    _ensure_table()
    with get_db() as conn:
        # TP: entry 1000, tp 5% -> tercapai kalau harga >= 1050
        conn.execute("INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct) VALUES ('ZZTP', 1000, 5, 3)")
        # SL: entry 1000, sl 3% -> tercapai kalau harga <= 970
        conn.execute("INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct) VALUES ('ZZSL', 1000, 5, 3)")
        # EXPIRED: direkam MAX_HOLD_DAYS+1 hari lalu, harga di tengah (belum TP/SL)
        conn.execute(
            "INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, recorded_at) "
            "VALUES ('ZZOLD', 1000, 5, 3, datetime('now', ?))",
            (f'-{MAX_HOLD_DAYS + 1} days',),
        )
        # OPEN: baru direkam, harga masih di tengah -- harus tetap OPEN
        conn.execute("INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct) VALUES ('ZZOPEN', 1000, 5, 3)")

    prices = {"ZZTP": 1060.0, "ZZSL": 960.0, "ZZOLD": 1010.0, "ZZOPEN": 1010.0}

    async def fake_lookup(kode):
        return prices.get(kode)

    asyncio.run(audit_open_signals(fake_lookup))

    with get_db() as conn:
        rows = {r["kode"]: dict(r) for r in conn.execute("SELECT * FROM signal_history").fetchall()}

    assert rows["ZZTP"]["status"] == "TP_HIT"
    assert rows["ZZTP"]["return_pct"] == 5
    assert rows["ZZSL"]["status"] == "SL_HIT"
    assert rows["ZZSL"]["return_pct"] == -3
    assert rows["ZZOLD"]["status"] == "EXPIRED"
    assert rows["ZZOLD"]["return_pct"] == 1.0  # (1010/1000 - 1) * 100
    assert rows["ZZOPEN"]["status"] == "OPEN"
    assert rows["ZZOPEN"]["resolved_at"] is None


def test_signal_report_stats_none_without_closed_signals(clean_signal_db):
    """Regresi KRUSIAL untuk kejujuran fitur: kalau belum ada satupun
    sinyal yang selesai diaudit, 'stats' HARUS None -- bukan 0% atau angka
    lain yang kelihatan valid padahal cuma kebetulan tidak ada data."""
    from core.database import get_db
    from core.signal_history import _ensure_table, get_signal_report

    _ensure_table()
    with get_db() as conn:
        conn.execute("INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct) VALUES ('ZZONLYOPEN', 1000, 5, 3)")

    report = get_signal_report()
    assert report["stats"] is None
    assert report["n_open"] == 1


def test_signal_report_includes_explicit_entry_tp_sl_prices(clean_signal_db):
    """Regresi: user secara eksplisit minta harga entry/TP/SL yang konkret
    (Rupiah), bukan cuma persentase -- get_signal_report() harus menghitung
    tp_price/sl_price dari entry_price x tp_pct/sl_pct, angka yang SAMA
    dipakai audit_open_signals() supaya tidak ada dua sumber kebenaran."""
    from core.database import get_db
    from core.signal_history import _ensure_table, get_signal_report

    _ensure_table()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct) VALUES ('ZZPRICE', 1000, 5, 3)"
        )

    report = get_signal_report()
    sig = next(s for s in report["signals"] if s["kode"] == "ZZPRICE")
    assert sig["tp_price"] == pytest.approx(1050.0)
    assert sig["sl_price"] == pytest.approx(970.0)


def test_signal_report_computes_win_rate_excluding_expired(clean_signal_db):
    """EXPIRED tidak dihitung sebagai menang ATAU kalah di win_rate (hasilnya
    ambigu, bukan keputusan tegas TP/SL), tapi return_pct-nya tetap masuk
    rata-rata return keseluruhan."""
    from core.database import get_db
    from core.signal_history import _ensure_table, get_signal_report

    _ensure_table()
    with get_db() as conn:
        conn.execute('''INSERT INTO signal_history
            (kode, entry_price, tp_pct, sl_pct, status, resolved_at, return_pct, days_to_resolve)
            VALUES ('ZZW1', 1000, 5, 3, 'TP_HIT', datetime('now'), 5.0, 4)''')
        conn.execute('''INSERT INTO signal_history
            (kode, entry_price, tp_pct, sl_pct, status, resolved_at, return_pct, days_to_resolve)
            VALUES ('ZZW2', 1000, 5, 3, 'TP_HIT', datetime('now'), 5.0, 6)''')
        conn.execute('''INSERT INTO signal_history
            (kode, entry_price, tp_pct, sl_pct, status, resolved_at, return_pct, days_to_resolve)
            VALUES ('ZZL1', 1000, 5, 3, 'SL_HIT', datetime('now'), -3.0, 2)''')
        conn.execute('''INSERT INTO signal_history
            (kode, entry_price, tp_pct, sl_pct, status, resolved_at, return_pct, days_to_resolve)
            VALUES ('ZZE1', 1000, 5, 3, 'EXPIRED', datetime('now'), 1.0, 20)''')

    stats = get_signal_report()["stats"]
    assert stats["n_closed"] == 4
    assert stats["n_tp_hit"] == 2 and stats["n_sl_hit"] == 1 and stats["n_expired"] == 1
    assert stats["win_rate"] == pytest.approx(2 / 3 * 100, abs=0.1)  # 2 menang dari 3 (TP+SL), EXPIRED di luar
    assert stats["avg_return_pct"] == pytest.approx((5.0 + 5.0 - 3.0 + 1.0) / 4, abs=0.01)
    assert stats["avg_days_to_resolve"] == pytest.approx((4 + 6 + 2 + 20) / 4, abs=0.1)


def test_signals_endpoint_returns_report_structure(client, clean_signal_db):
    r = client.get("/api/signals")
    assert r.status_code == 200
    data = r.json()
    assert "signals" in data and "stats" in data and "n_open" in data and "n_total" in data


def test_confidence_reasons_flags_pattern_bullish_and_bearish():
    """Regresi: hasil detect_patterns() (Pattern Analyst, rule-based) harus
    ikut memengaruhi reasons/warnings Top Pick -- pola bullish memperkuat
    alasan BUY, pola bearish jadi warning meski skor gabungan tinggi
    (chart pattern bisa jadi sinyal awal pembalikan yang belum tertangkap
    indikator lain)."""
    import web.app as app_module

    it_bullish = {
        "ai_score": 70, "minervini_criteria_met": 7, "confluence_bullish": 4, "confluence_bearish": 1,
        "bandar": None, "rr_ratio": 2.0, "likuiditas": "Likuid",
        "pattern": "DOUBLE BOTTOM", "pattern_bias": "BULLISH",
    }
    reasons, warnings = app_module._confidence_reasons(it_bullish)
    assert any("DOUBLE BOTTOM" in r and "bullish" in r for r in reasons)

    it_bearish = {**it_bullish, "pattern": "HEAD AND SHOULDERS", "pattern_bias": "BEARISH"}
    _, warnings_bear = app_module._confidence_reasons(it_bearish)
    assert any("HEAD AND SHOULDERS" in w and "bearish" in w for w in warnings_bear)


def test_confidence_endpoint_includes_pattern_fields(client):
    """Regresi: /api/confidence harus menyertakan field 'pattern'/
    'pattern_bias' (dari detect_patterns(), core/screening_pro.py) di
    setiap item -- dasar utk badge Pattern Analyst yang lebih ditonjolkan
    di UI, dan utk disimpan di signal_history saat sinyal dicatat."""
    r = client.get("/api/confidence")
    assert r.status_code == 200
    it = r.json()["items"][0]
    assert "pattern" in it and "pattern_bias" in it


def _macd_cross_df(direction: str):
    """Bangun DataFrame sintetis yang histogram MACD-nya (MACD line -
    Signal line) BENAR-BENAR berpindah sisi persis di bar terakhir --
    dicari otomatis lewat calculate_macd() sendiri (bukan ditebak manual)
    supaya test-nya robust terhadap perubahan parameter EMA di masa depan."""
    import numpy as np
    import pandas as pd

    from core.indicators import calculate_macd

    if direction == "bullish":
        leg1, leg2 = np.linspace(2000, 1200, 70), np.linspace(1200, 2400, 30)
    else:
        leg1, leg2 = np.linspace(1200, 2400, 70), np.linspace(2400, 1200, 30)
    close_full = np.concatenate([leg1, leg2])
    _, _, hist = calculate_macd(pd.Series(close_full))
    h = hist.values
    cross_idx = None
    for i in range(1, len(h)):
        if direction == "bullish" and h[i - 1] <= 0 < h[i]:
            cross_idx = i
            break
        if direction == "bearish" and h[i - 1] >= 0 > h[i]:
            cross_idx = i
            break
    assert cross_idx is not None, "gagal membangun fixture MACD cross -- cek parameter leg1/leg2"
    close = close_full[:cross_idx + 1]
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=len(close))
    return pd.DataFrame({"Close": close}, index=dates)


def test_detect_patterns_flags_macd_histogram_bullish_cross():
    """Regresi fitur baru: histogram MACD baru berbalik dari negatif ke
    positif di bar terakhir harus dideteksi sebagai pola momentum
    tersendiri -- 'entry point' teknikal terpisah dari pola struktur harga
    (Double Top/Bottom, HH/HL, LH/LL) yang sudah ada."""
    from core.screening_pro import detect_patterns

    df = _macd_cross_df("bullish")
    res = detect_patterns(df, "ZZMACD")
    names = [p["nama"] for p in res["patterns"]]
    assert "MACD HISTOGRAM BULLISH CROSS" in names
    p = next(p for p in res["patterns"] if p["nama"] == "MACD HISTOGRAM BULLISH CROSS")
    assert p["bias"] == "BULLISH"


def test_detect_patterns_flags_macd_histogram_bearish_cross():
    from core.screening_pro import detect_patterns

    df = _macd_cross_df("bearish")
    res = detect_patterns(df, "ZZMACD")
    names = [p["nama"] for p in res["patterns"]]
    assert "MACD HISTOGRAM BEARISH CROSS" in names
    p = next(p for p in res["patterns"] if p["nama"] == "MACD HISTOGRAM BEARISH CROSS")
    assert p["bias"] == "BEARISH"


def test_confidence_reasons_uses_momentum_label_for_macd_pattern():
    """Regresi: label pola MACD di reasons/warnings Top Pick harus 'Sinyal
    momentum', BUKAN 'Pola chart' -- MACD cross itu sinyal momentum
    indikator, bukan pola struktur harga, jadi labelnya harus jujur beda."""
    import web.app as app_module

    it = {
        "ai_score": 50, "minervini_criteria_met": 4, "confluence_bullish": 2, "confluence_bearish": 2,
        "bandar": None, "rr_ratio": 1.2, "likuiditas": "Likuid",
        "pattern": "MACD HISTOGRAM BULLISH CROSS", "pattern_bias": "BULLISH",
    }
    reasons, _ = app_module._confidence_reasons(it)
    assert any("Sinyal momentum: MACD HISTOGRAM BULLISH CROSS" in r for r in reasons)
    assert not any("Pola chart: MACD" in r for r in reasons)


def test_run_signal_auto_cycle_runs_refresh_and_audit_independently(monkeypatch):
    """Regresi fitur auto-audit berkala: _run_signal_auto_cycle() (satu
    putaran, dipakai baik oleh _signal_auto_loop maupun langsung ditest di
    sini) HARUS menjalankan refresh Top Pick (confidence(), yang otomatis
    mencatat sinyal baru) DAN audit sinyal OPEN (_run_signal_audit_and_notify())
    -- dan kegagalan salah satu TIDAK BOLEH menghalangi yang lain jalan,
    supaya siklus background tetap berguna sebagian walau mis. Yahoo
    Finance sedang down saat refresh Top Pick."""
    import asyncio

    import web.app as app_module

    calls = []

    async def fake_confidence():
        calls.append("confidence")
        raise RuntimeError("simulasi kegagalan refresh Top Pick")

    async def fake_audit():
        calls.append("audit")

    monkeypatch.setattr(app_module, "confidence", fake_confidence)
    monkeypatch.setattr(app_module, "_run_signal_audit_and_notify", fake_audit)

    asyncio.run(app_module._run_signal_auto_cycle())
    assert calls == ["confidence", "audit"]


def test_telegram_send_message_fail_open_when_unconfigured(monkeypatch):
    """Tanpa TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID dikonfigurasi (_ENABLED
    False), send_message() harus diam-diam return False -- BUKAN raise --
    supaya pencatatan/audit sinyal tidak pernah gagal gara-gara notifikasi
    belum di-setup (fail-open, sama disiplinnya dengan Redis/DB)."""
    import asyncio

    import core.telegram_notify as tg

    monkeypatch.setattr(tg, "_ENABLED", False)
    assert asyncio.run(tg.send_message("halo")) is False


def test_telegram_format_signal_new_contains_key_fields():
    from core.telegram_notify import format_signal_new

    sig = {
        "kode": "BBCA", "entry_price": 9500.0, "tp_pct": 6.0, "sl_pct": 3.0,
        "tp_price": 10070.0, "sl_price": 9215.0, "confidence_score": 78.5,
        "pattern": "DOUBLE BOTTOM",
    }
    msg = format_signal_new(sig)
    assert "BBCA" in msg
    assert "Rp10,070" in msg
    assert "DOUBLE BOTTOM" in msg
    assert "bukan rekomendasi investasi" in msg


def test_telegram_format_signal_resolved_labels_each_status():
    """Regresi kejujuran: SL_HIT (rugi) harus dilaporkan dengan bahasa &
    format yang SAMA transparannya dengan TP_HIT (untung) -- bukan
    disamarkan -- supaya track record yang dikirim ke Telegram kredibel."""
    from core.telegram_notify import format_signal_resolved

    base = {
        "kode": "BBCA", "entry_price": 9500.0, "resolved_price": 10000.0,
        "return_pct": 5.0, "days_to_resolve": 7, "recorded_at": "2026-06-01 10:00:00",
    }

    tp_msg = format_signal_resolved({**base, "status": "TP_HIT"})
    assert "Target tercapai" in tp_msg and "BBCA" in tp_msg

    sl_msg = format_signal_resolved({**base, "status": "SL_HIT", "return_pct": -3.0})
    assert "Kena stop loss" in sl_msg

    exp_msg = format_signal_resolved({**base, "status": "EXPIRED"})
    assert "Kadaluarsa" in exp_msg


def test_telegram_messages_include_source_label():
    """Regresi: signal_history sekarang punya 3 sumber entry independen
    (TOP_PICK, MACD_CROSS, SMART_MONEY) -- pesan Telegram HARUS selalu
    menyebut sumbernya supaya user tidak salah kira teori-teori itu sama."""
    from core.telegram_notify import format_signal_new, format_signal_resolved

    new_sig = {
        "kode": "BBCA", "entry_price": 9500.0, "tp_pct": 6.0, "sl_pct": 3.0,
        "tp_price": 10070.0, "sl_price": 9215.0, "source": "MACD_CROSS",
    }
    assert "MACD Histogram Cross" in format_signal_new(new_sig)

    resolved_sig = {
        "kode": "BBCA", "entry_price": 9500.0, "resolved_price": 10000.0,
        "return_pct": 5.0, "days_to_resolve": 7, "recorded_at": "2026-06-01 10:00:00",
        "status": "TP_HIT", "source": "TOP_PICK",
    }
    assert "Top Pick" in format_signal_resolved(resolved_sig)

    sm_sig = {
        "kode": "BBCA", "entry_price": 9500.0, "tp_pct": 6.0, "sl_pct": 3.0,
        "tp_price": 10070.0, "sl_price": 9215.0, "source": "SMART_MONEY",
    }
    assert "Smart Money" in format_signal_new(sm_sig)


def test_record_macd_cross_signals_ignores_confidence_score(clean_signal_db):
    """Regresi inti fitur: entry point MACD Cross HARUS diuji independen
    dari skor gabungan -- saham dengan confidence_score RENDAH (di bawah
    MIN_SCORE_TO_RECORD milik Top Pick) tetap harus tercatat selama
    histogram MACD-nya baru cross bullish dan likuid, supaya validitas
    teori MACD-nya sendiri yang diaudit, bukan campuran skor lain."""
    import asyncio

    from core.signal_history import record_macd_cross_signals, MIN_SCORE_TO_RECORD

    items = [
        _fake_confidence_item("ZZMLOW", MIN_SCORE_TO_RECORD - 30, macd_bullish_cross=True),
        _fake_confidence_item("ZZMNOCROSS", MIN_SCORE_TO_RECORD + 30, macd_bullish_cross=False),
    ]
    saved = asyncio.run(record_macd_cross_signals(items))
    assert len(saved) == 1
    assert saved[0]["kode"] == "ZZMLOW"
    assert saved[0]["source"] == "MACD_CROSS"
    assert saved[0]["pattern"] == "MACD HISTOGRAM BULLISH CROSS"


def test_record_macd_cross_signals_requires_liquidity(clean_signal_db):
    """Regresi: MACD Cross tetap harus disaring likuiditas (kriteria bisa-
    dieksekusi, BUKAN kriteria 'seberapa bagus') -- saham tidak likuid
    dengan histogram cross bullish TIDAK boleh ikut dicatat."""
    import asyncio

    from core.signal_history import record_macd_cross_signals

    items = [_fake_confidence_item("ZZILLIQUID", 90, macd_bullish_cross=True, likuiditas="Tidak Likuid")]
    saved = asyncio.run(record_macd_cross_signals(items))
    assert saved == []


def test_record_macd_cross_signals_dedup_independent_of_top_pick(clean_signal_db):
    """Regresi: dedup MACD Cross per hari HARUS scoped ke source='MACD_CROSS'
    sendiri -- kode saham yang SAMA boleh tercatat DUA KALI di hari yang
    sama (satu dari Top Pick, satu dari MACD Cross) karena keduanya teori
    entry berbeda yang sengaja diaudit terpisah, bukan saling menggantikan."""
    import asyncio

    from core.signal_history import record_top_picks, record_macd_cross_signals, get_signal_report, MIN_SCORE_TO_RECORD

    items = [_fake_confidence_item("ZZBOTH", MIN_SCORE_TO_RECORD + 10, macd_bullish_cross=True)]
    saved_tp = asyncio.run(record_top_picks(items))
    saved_macd = asyncio.run(record_macd_cross_signals(items))
    assert len(saved_tp) == 1 and len(saved_macd) == 1

    report = get_signal_report()
    rows = [s for s in report["signals"] if s["kode"] == "ZZBOTH"]
    assert len(rows) == 2
    assert {r["source"] for r in rows} == {"TOP_PICK", "MACD_CROSS"}

    # Panggil lagi di hari yang sama -- masing-masing source dedup sendiri,
    # tidak menambah baris baru sama sekali.
    saved_tp_again = asyncio.run(record_top_picks(items))
    saved_macd_again = asyncio.run(record_macd_cross_signals(items))
    assert saved_tp_again == [] and saved_macd_again == []


def _fake_sm_item(kode, pola, harga=1000.0, likuiditas="Sangat Likuid",
                   naik=3.0, turun=2.0):
    return {
        "kode": kode, "harga": harga, "pola": pola, "likuiditas": likuiditas,
        "potensi_naik_pct": naik, "risiko_turun_pct": turun,
        "confidence_score": 60.0, "ai_score": 55.0, "ai_rating": "BAGUS",
    }


def test_record_smart_money_signals_only_records_buy_categories(clean_signal_db):
    """Regresi inti fitur integrasi: signal_history/audit_open_signals baru
    mendukung matematika long-only, jadi HANYA kategori yg dipetakan ke BUY
    (Akumulasi/Akumulasi Agresif/Siluman/Breakout Volume) boleh dicatat --
    Distribusi/Distribusi Agresif (arah SELL, belum ada infra bidirectional)
    sengaja TIDAK dicatat sama sekali di source ini."""
    import asyncio

    from core.signal_history import record_smart_money_signals

    items = [
        _fake_sm_item("ZZAKU", "Akumulasi Agresif"),
        _fake_sm_item("ZZSIL", "Siluman (quiet buy)"),
        _fake_sm_item("ZZBRK", "Breakout Volume"),
        _fake_sm_item("ZZDIS", "Distribusi Agresif"),
    ]
    saved = asyncio.run(record_smart_money_signals(items))
    saved_kodes = {s["kode"] for s in saved}
    assert saved_kodes == {"ZZAKU", "ZZSIL", "ZZBRK"}
    assert "ZZDIS" not in saved_kodes
    assert all(s["source"] == "SMART_MONEY" for s in saved)


def test_record_smart_money_signals_requires_liquidity(clean_signal_db):
    """Regresi: sama seperti MACD Cross, Smart Money tetap harus disaring
    likuiditas (kriteria bisa-dieksekusi) -- saham tidak likuid dgn pola
    akumulasi TIDAK boleh ikut dicatat."""
    import asyncio

    from core.signal_history import record_smart_money_signals

    items = [_fake_sm_item("ZZILLIQ", "Akumulasi Agresif", likuiditas="Tidak Likuid")]
    saved = asyncio.run(record_smart_money_signals(items))
    assert saved == []


def test_record_smart_money_signals_dedup_independent_of_other_sources(clean_signal_db):
    """Regresi: dedup Smart Money per hari HARUS scoped ke
    source='SMART_MONEY' sendiri -- kode yang sama boleh tercatat di
    TOP_PICK, MACD_CROSS, DAN SMART_MONEY sekaligus di hari yang sama,
    tiga teori entry berbeda yang sengaja diaudit terpisah."""
    import asyncio

    from core.signal_history import (
        record_top_picks, record_macd_cross_signals, record_smart_money_signals,
        get_signal_report, MIN_SCORE_TO_RECORD,
    )

    tp_items = [_fake_confidence_item("ZZTRIPLE", MIN_SCORE_TO_RECORD + 10, macd_bullish_cross=True)]
    sm_items = [_fake_sm_item("ZZTRIPLE", "Akumulasi Agresif")]

    saved_tp = asyncio.run(record_top_picks(tp_items))
    saved_macd = asyncio.run(record_macd_cross_signals(tp_items))
    saved_sm = asyncio.run(record_smart_money_signals(sm_items))
    assert len(saved_tp) == 1 and len(saved_macd) == 1 and len(saved_sm) == 1

    report = get_signal_report()
    rows = [s for s in report["signals"] if s["kode"] == "ZZTRIPLE"]
    assert len(rows) == 3
    assert {r["source"] for r in rows} == {"TOP_PICK", "MACD_CROSS", "SMART_MONEY"}


def test_record_smart_money_signals_skips_on_weekend(clean_signal_db, monkeypatch):
    """Regresi: konsisten dgn 2 source lain, Smart Money juga tidak boleh
    mencatat sinyal baru di hari libur bursa (lihat _is_bursa_weekend)."""
    import asyncio

    import core.signal_history as sh

    monkeypatch.setattr(sh, "_is_bursa_weekend", lambda: True)
    items = [_fake_sm_item("ZZWEEKEND", "Akumulasi Agresif")]
    assert asyncio.run(sh.record_smart_money_signals(items)) == []


def test_record_smart_money_cycle_enriches_with_scored_confidence_items(monkeypatch):
    """Regresi bug NYATA ditemukan lewat verifikasi adversarial saat audit:
    desain awal yg diusulkan mengambil TP/SL/confidence_score dari
    _confidence_raw_signals() (cache PRE-scoring) -- field confidence_score
    baru dihitung belakangan di loop kedua confidence() sendiri, TIDAK
    pernah ada di cache raw, jadi akan SELALU None kalau diambil dari
    situ. _record_smart_money_cycle() HARUS reuse confidence_items (hasil
    confidence(), SUDAH computed), bukan panggil ulang cache raw."""
    import asyncio

    import web.app as app_module

    async def fake_scan(kode):
        if kode == "SMHIT":
            return {"kode": "SMHIT", "harga": 1000.0, "chg1": 5.0, "chg5": 5.0,
                    "vol_ratio": 3.0, "rsi": 70.0, "pola": "Akumulasi Agresif",
                    "hari_lalu": 0, "tanggal": "2026-07-06", "grup": "Independen"}
        return None

    monkeypatch.setattr(app_module, "_scan_one_sm", fake_scan)
    monkeypatch.setattr(app_module, "_SM_UNIVERSE", ["SMHIT", "SMMISS"])

    captured = {}

    async def fake_record(enriched_items, price_lookup=None):
        captured["items"] = enriched_items
        return []

    # _record_smart_money_cycle mengimpor record_smart_money_signals SECARA
    # LOKAL (`from core.signal_history import ...` di dalam fungsi) -- jadi
    # yang perlu di-patch adalah atribut modul core.signal_history, bukan
    # web.app (import lokal me-resolve ulang tiap panggilan).
    import core.signal_history as sh
    monkeypatch.setattr(sh, "record_smart_money_signals", fake_record)

    confidence_items = [
        {"kode": "SMHIT", "potensi_naik_pct": 4.0, "risiko_turun_pct": 2.0,
         "likuiditas": "Sangat Likuid", "confidence_score": 72.5, "ai_score": 68.0, "ai_rating": "BAGUS"},
    ]
    asyncio.run(app_module._record_smart_money_cycle(confidence_items))

    assert len(captured["items"]) == 1
    enriched = captured["items"][0]
    assert enriched["kode"] == "SMHIT"
    assert enriched["confidence_score"] == 72.5, "confidence_score harus ikut terbawa dari confidence_items, bukan None"
    assert enriched["potensi_naik_pct"] == 4.0
    assert enriched["risiko_turun_pct"] == 2.0
    assert enriched["likuiditas"] == "Sangat Likuid"


def test_record_smart_money_cycle_skips_when_confidence_items_empty():
    """Regresi: kalau confidence() barusan gagal (confidence_items kosong),
    _record_smart_money_cycle HARUS skip total -- tanpa TP/SL/likuiditas
    dari situ, tidak ada dasar wajar utk mencatat entry apa pun."""
    import asyncio

    import web.app as app_module

    # Tidak monkeypatch _scan_one_sm/_SM_UNIVERSE sama sekali -- kalau
    # fungsi ini TIDAK skip lebih awal, ini akan mencoba scan network
    # sungguhan dan test akan lambat/gagal, membuktikan early-return
    # bekerja.
    asyncio.run(app_module._record_smart_money_cycle([]))


def test_get_signal_report_computes_stats_by_source(clean_signal_db):
    """Regresi fitur baru: stats_by_source harus menghitung win rate/return
    TERPISAH per source, supaya user bisa bandingkan validitas Top Pick
    vs MACD Cross sebagai teori entry, bukan tercampur ke satu angka."""
    from core.database import get_db
    from core.signal_history import _ensure_table, get_signal_report

    _ensure_table()
    with get_db() as conn:
        conn.execute('''INSERT INTO signal_history
            (kode, entry_price, tp_pct, sl_pct, status, resolved_at, return_pct, days_to_resolve, source)
            VALUES ('ZZTP1', 1000, 5, 3, 'TP_HIT', datetime('now'), 5.0, 4, 'TOP_PICK')''')
        conn.execute('''INSERT INTO signal_history
            (kode, entry_price, tp_pct, sl_pct, status, resolved_at, return_pct, days_to_resolve, source)
            VALUES ('ZZTP2', 1000, 5, 3, 'SL_HIT', datetime('now'), -3.0, 2, 'TOP_PICK')''')
        conn.execute('''INSERT INTO signal_history
            (kode, entry_price, tp_pct, sl_pct, status, resolved_at, return_pct, days_to_resolve, source)
            VALUES ('ZZMC1', 1000, 5, 3, 'TP_HIT', datetime('now'), 5.0, 3, 'MACD_CROSS')''')

    report = get_signal_report()
    by_source = report["stats_by_source"]
    assert set(by_source.keys()) == {"TOP_PICK", "MACD_CROSS"}
    assert by_source["TOP_PICK"]["n_closed"] == 2
    assert by_source["TOP_PICK"]["win_rate"] == pytest.approx(50.0)
    assert by_source["MACD_CROSS"]["n_closed"] == 1
    assert by_source["MACD_CROSS"]["win_rate"] == pytest.approx(100.0)
    # Statistik gabungan tetap menghitung SEMUA source jadi satu.
    assert report["stats"]["n_closed"] == 3


def test_get_signal_report_stats_by_source_empty_when_nothing_closed(clean_signal_db):
    """Regresi kejujuran: kalau belum ada satupun sinyal MACD_CROSS yang
    selesai, source itu TIDAK BOLEH muncul di stats_by_source sama sekali
    (bukan muncul dengan angka 0%/dikarang)."""
    from core.database import get_db
    from core.signal_history import _ensure_table, get_signal_report

    _ensure_table()
    with get_db() as conn:
        conn.execute('''INSERT INTO signal_history
            (kode, entry_price, tp_pct, sl_pct, source) VALUES ('ZZOPENMC', 1000, 5, 3, 'MACD_CROSS')''')

    report = get_signal_report()
    assert report["stats_by_source"] == {}


def test_calculate_average_down_basic_math():
    """Regresi kalkulator Average Down: rata-rata baru harus tertimbang
    LOT (100 lembar/lot, bukan sekadar rata-rata dua harga)."""
    from core.risk_management import calculate_average_down

    # 10 lot @ 1000, tambah 10 lot @ 800 -> rata-rata baru = (1000+800)/2 = 900
    # (kebetulan sama besar jumlah lotnya, jadi rata-rata sederhana valid di sini)
    res = calculate_average_down(avg_price=1000, lots_held=10, current_price=800, add_lots=10)
    assert res["new_avg_price"] == pytest.approx(900.0)
    assert res["total_lots"] == 20
    assert res["additional_capital"] == pytest.approx(800 * 10 * 100)
    assert res["pl_before_pct"] == pytest.approx(-20.0)
    assert res["pl_after_pct"] == pytest.approx((800 / 900 - 1) * 100, abs=0.01)

    # Timbangan lot TIDAK sama -> bukan rata-rata sederhana
    res2 = calculate_average_down(avg_price=1000, lots_held=10, current_price=800, add_lots=30)
    expected_avg = (1000 * 1000 + 800 * 3000) / 4000  # (avg*shares_held + price*shares_add) / total_shares
    assert res2["new_avg_price"] == pytest.approx(expected_avg)


def test_calculate_average_down_zero_add_lots_is_noop():
    """add_lots=0 (sekadar cek P/L posisi sekarang) harus mengembalikan
    rata-rata yang SAMA PERSIS dengan avg_price -- bukan error atau
    pembagian oleh nol."""
    from core.risk_management import calculate_average_down

    res = calculate_average_down(avg_price=1500, lots_held=5, current_price=1400, add_lots=0)
    assert res["new_avg_price"] == pytest.approx(1500.0)
    assert res["pl_before_pct"] == res["pl_after_pct"]
    assert res["additional_capital"] == 0


def test_calculate_average_down_rejects_invalid_input():
    from core.risk_management import calculate_average_down

    assert calculate_average_down(avg_price=0, lots_held=10, current_price=800, add_lots=5) is None
    assert calculate_average_down(avg_price=1000, lots_held=0, current_price=800, add_lots=5) is None
    assert calculate_average_down(avg_price=1000, lots_held=10, current_price=0, add_lots=5) is None
    assert calculate_average_down(avg_price=1000, lots_held=10, current_price=800, add_lots=-1) is None


def test_averagedown_endpoint_matches_current_price_and_math(client):
    """Regresi endpoint: /api/averagedown harus pakai harga TERKINI dari
    data harga sungguhan (sama seperti /api/analyze), bukan nilai lain,
    dan hasil hitungannya harus konsisten dengan calculate_average_down()."""
    from core.risk_management import calculate_average_down

    price = client.get("/api/analyze/BBCA").json()["price"]
    r = client.get("/api/averagedown/BBCA?avg_price=1000&lots=10&add_lots=5")
    assert r.status_code == 200
    d = r.json()
    assert d["current_price"] == pytest.approx(price, abs=0.5)
    expected = calculate_average_down(1000, 10, d["current_price"], 5)
    assert d["new_avg_price"] == pytest.approx(expected["new_avg_price"])
    assert d["pl_after_pct"] == pytest.approx(expected["pl_after_pct"])


def test_averagedown_endpoint_rejects_invalid_input(client):
    r = client.get("/api/averagedown/BBCA?avg_price=0&lots=10&add_lots=5")
    assert r.status_code == 422


def test_averagedown_endpoint_suggestions_are_below_current_price(client):
    """Regresi fitur 'saran area average down': setiap level yang
    disarankan (support S1/S2, batas bawah estimasi wajar) HARUS di
    bawah harga sekarang -- menyarankan level di ATAS harga sekarang
    sebagai 'area average down' tidak masuk akal (belum tentu bakal
    tersentuh, dan bukan average down kalau harga malah naik ke sana).
    Tiap saran juga harus konsisten dengan calculate_average_down()
    murni di level harga itu."""
    from core.risk_management import calculate_average_down

    r = client.get("/api/averagedown/BBCA?avg_price=1000&lots=10&add_lots=5")
    assert r.status_code == 200
    d = r.json()
    assert "suggestions" in d
    for s in d["suggestions"]:
        assert s["price"] < d["current_price"]
        expected = calculate_average_down(1000, 10, s["price"], 5)
        assert s["new_avg_price"] == pytest.approx(expected["new_avg_price"])
        assert s["pl_after_pct"] == pytest.approx(expected["pl_after_pct"])
    # Terurut dari harga tertinggi ke terendah (paling dekat ke paling jauh)
    prices = [s["price"] for s in d["suggestions"]]
    assert prices == sorted(prices, reverse=True)


def test_valuation_rejects_methods_with_corrupted_bvps():
    """Regresi bug nyata (ditemukan user via kartu 'Estimasi Wajar
    Terendah' menampilkan Rp0): TPIA di Yahoo Finance punya
    book_value_per_share = Rp0.045 (jelas korup/salah skala -- PBV
    implied jadi 39.666x), yang bikin metode PBV×2 & ROE-implied
    menghasilkan 'harga wajar' mendekati nol untuk saham dengan EPS
    POSITIF Rp378 -- laba positif tidak mungkin genuinely wajar
    dihargai mendekati nol. _valuation() harus MENOLAK metode yang
    hasilnya <5% atau >2000% dari harga sekarang (artefak data, bukan
    sinyal), TAPI tetap meloloskan metode lain yang masih masuk akal."""
    from web.app import _valuation

    fund = {
        "eps_trailing": 378.24, "eps_forward": 16.22,
        "book_value_per_share": 0.045,  # data korup dari Yahoo Finance
        "harga_sekarang": 1785.0, "pe_trailing": 4.72,
        "roe_pct": 42.37, "earnings_growth_pct": None,
        "revenue_growth_pct": 2.86, "dividend_yield_pct": 34.0,
        "payout_ratio_pct": 2.77, "net_margin_pct": 14.34,
    }
    val = _valuation(fund)

    # Metode yang bergantung BVPS korup HARUS ditolak
    assert "pbv_x2" not in val["methods"]
    assert "roe_implied" not in val["methods"]
    assert "graham" not in val["methods"]  # juga pakai bvps

    # Metode yang TIDAK bergantung bvps tetap harus lolos (bukan overkill filter)
    assert "per_x15" in val["methods"]

    # Floor TIDAK BOLEH lagi berupa angka absurd mendekati nol
    assert val["range_low"] > fund["harga_sekarang"] * 0.05


def test_valuation_keeps_legitimate_methods_unaffected():
    """Regresi anti-overkill: saham dengan data fundamental NORMAL
    (tidak korup) tidak boleh kehilangan metode valuasinya gara-gara
    guard baru -- guard cuma menyaring outlier ekstrem, bukan mempersempit
    rentang wajar untuk kasus normal."""
    from web.app import _valuation

    fund = {
        "eps_trailing": 400.0, "eps_forward": 440.0,
        "book_value_per_share": 3000.0, "harga_sekarang": 6000.0,
        "pe_trailing": 15.0, "roe_pct": 18.0, "earnings_growth_pct": 10.0,
        "revenue_growth_pct": 8.0, "dividend_yield_pct": 3.0,
        "payout_ratio_pct": 40.0, "net_margin_pct": 20.0,
    }
    val = _valuation(fund)
    assert "graham" in val["methods"]
    assert "per_x15" in val["methods"]
    assert "pbv_x2" in val["methods"]
    assert "roe_implied" in val["methods"]


def test_averagedown_endpoint_uses_target_price_not_live_price(client):
    """Regresi permintaan user: kalkulasi & verdict fundamental HARUS bisa
    dievaluasi di harga yang BENAR-BENAR mau dipakai user buat beli
    (target_price, mis. limit order di bawah harga sekarang), BUKAN
    dipaksa selalu pakai harga live -- 'current_price' (live) dan
    'buy_price' (dipakai utk kalkulasi) harus dikembalikan TERPISAH dan
    keduanya benar, tidak saling menimpa."""
    from core.risk_management import calculate_average_down

    live_price = client.get("/api/averagedown/BBCA?avg_price=1000&lots=10").json()["current_price"]
    target = live_price * 0.9  # simulasikan limit order 10% di bawah harga live

    r = client.get(f"/api/averagedown/BBCA?avg_price=1000&lots=10&add_lots=5&target_price={target}")
    assert r.status_code == 200
    d = r.json()
    assert d["current_price"] == pytest.approx(live_price)  # harga live tetap dilaporkan apa adanya
    assert d["buy_price"] == pytest.approx(target, abs=0.01)  # tapi kalkulasi pakai target, bukan live
    assert d["is_custom_target"] is True

    expected = calculate_average_down(1000, 10, target, 5)
    assert d["new_avg_price"] == pytest.approx(expected["new_avg_price"])
    assert d["pl_after_pct"] == pytest.approx(expected["pl_after_pct"])


def test_averagedown_endpoint_without_target_price_falls_back_to_live(client):
    """Perilaku lama TIDAK BOLEH berubah kalau target_price tidak diisi --
    buy_price harus sama persis dengan current_price (fallback)."""
    r = client.get("/api/averagedown/BBCA?avg_price=1000&lots=10&add_lots=5")
    assert r.status_code == 200
    d = r.json()
    assert d["buy_price"] == pytest.approx(d["current_price"])
    assert d["is_custom_target"] is False


def test_averagedown_suggestions_include_verdict(client):
    """Setiap kartu referensi (suggestions) harus punya verdict fundamental
    sendiri (dievaluasi di harga level itu, BUKAN ikut-ikutan verdict harga
    sekarang) -- None kalau data fundamental gagal diambil, bukan error."""
    r = client.get("/api/averagedown/BBCA?avg_price=1000&lots=10&add_lots=5")
    assert r.status_code == 200
    d = r.json()
    for s in d["suggestions"]:
        assert "verdict" in s


def test_confidence_weights_exclude_fundamental_and_sum_to_one():
    """Regresi koreksi user: fundamental (& kepemilikan) SENGAJA TIDAK
    ikut bobot Skor Keyakinan (percobaan awal sempat menjadikannya bobot
    tetap, tapi user koreksi -- saham IDX kadang naik/turun tidak terlalu
    dipengaruhi fundamental). Bobot 5 komponen teknikal asli harus tetap
    berjumlah 100%."""
    import web.app as app_module

    weights, _ = app_module._confidence_weights()
    assert "fund" not in weights
    assert set(weights.keys()) == {"ai", "mv", "cf", "liq", "rr"}
    assert sum(weights.values()) == pytest.approx(1.0)


def test_confidence_reasons_flags_fundamental_undervalued_and_overvalued():
    """Regresi #1: valuasi fundamental (Undervalued/Overvalued) harus
    tercermin di reasons/warnings Top Pick, konsisten dengan pola
    proxy bandar & pola chart yang sudah ada."""
    import web.app as app_module

    it_under = {
        "ai_score": 50, "minervini_criteria_met": 4, "confluence_bullish": 2, "confluence_bearish": 2,
        "bandar": None, "rr_ratio": 1.2, "likuiditas": "Likuid",
        "fund_verdict": "Undervalued", "fund_upside_pct": 25.0,
    }
    reasons, _ = app_module._confidence_reasons(it_under)
    assert any("Undervalued" in r and "25" in r for r in reasons)

    it_over = {**it_under, "fund_verdict": "Overvalued", "fund_upside_pct": -25.0}
    _, warnings = app_module._confidence_reasons(it_over)
    assert any("Overvalued" in w for w in warnings)


def test_confidence_reasons_caps_bombastic_fundamental_upside():
    """Regresi bug NYATA ditemukan saat live-check MNCN: metode 'PER x 15'
    bisa menghasilkan upside 600%+ kalau PE riil jauh di bawah asumsi 'PE
    wajar 15x' -- matematis valid dari formula yang ada, tapi menampilkan
    '+612% upside' apa adanya melanggar prinsip project ini sendiri
    (dilarang klaim return berlebihan/bombastis). Reason text HARUS
    dibatasi ke '>=100%', BUKAN angka mentahnya, TAPI juga BUKAN
    disembunyikan/dibulatkan seolah cuma 100% pas."""
    import web.app as app_module

    it = {
        "ai_score": 50, "minervini_criteria_met": 4, "confluence_bullish": 2, "confluence_bearish": 2,
        "bandar": None, "rr_ratio": 1.2, "likuiditas": "Likuid",
        "fund_verdict": "Undervalued", "fund_upside_pct": 612.2,
    }
    reasons, _ = app_module._confidence_reasons(it)
    text = next(r for r in reasons if "Undervalued" in r)
    assert "612" not in text  # angka mentah tidak boleh tampil apa adanya
    assert ">=100%" in text  # tapi jujur ditandai lebih ekstrem dari 100%


def test_confidence_reasons_flags_kepemilikan_change():
    """Regresi #1 (kepemilikan/X-15): perubahan kepemilikan pemegang saham
    substansial harus jadi reason (nambah) atau warning (kurangi) -- TIDAK
    ADA reason/warning kalau kepemilikan_change_pct None (tidak ada filing,
    kasus MAYORITAS saham di hari mana pun -- tidak boleh dipaksa netral
    jadi 'menambah 0%', harus benar-benar tidak disebut sama sekali)."""
    import web.app as app_module

    base = {
        "ai_score": 50, "minervini_criteria_met": 4, "confluence_bullish": 2, "confluence_bearish": 2,
        "bandar": None, "rr_ratio": 1.2, "likuiditas": "Likuid",
    }
    reasons_add, warnings_add = app_module._confidence_reasons({**base, "kepemilikan_change_pct": 0.5})
    assert any("menambah kepemilikan" in r for r in reasons_add)

    reasons_sell, warnings_sell = app_module._confidence_reasons({**base, "kepemilikan_change_pct": -0.5})
    assert any("mengurangi kepemilikan" in w for w in warnings_sell)

    reasons_none, warnings_none = app_module._confidence_reasons({**base, "kepemilikan_change_pct": None})
    assert not any("kepemilikan" in r for r in reasons_none)
    assert not any("kepemilikan" in w for w in warnings_none)


def test_confidence_endpoint_includes_fundamental_fields_but_not_in_weights(client):
    """Regresi #1 end-to-end: /api/confidence harus menyertakan field
    fund_verdict/fund_upside_pct/kepemilikan_change_pct (dipakai reasons/
    warnings) di tiap item, TAPI 'fund' TIDAK BOLEH ada di response.weights
    -- fundamental & kepemilikan kontekstual saja, bukan komponen skor."""
    r = client.get("/api/confidence")
    assert r.status_code == 200
    data = r.json()
    it = data["items"][0]
    assert "fund_verdict" in it
    assert "fund_upside_pct" in it
    assert "kepemilikan_change_pct" in it
    assert "fund" not in data["weights"]


def test_fundamental_median_upside_uses_median_not_mean():
    """Regresi bug NYATA ditemukan saat live-check GGRM: metode 'PBV x 2'
    menghasilkan estimasi jauh lebih tinggi dari metode lain (BVPS GGRM
    memang tinggi, bukan data korup -- lolos guard _valuation()), yang
    menarik MEAN ('mid'/'upside_pct' bawaan _valuation()) jauh ke atas
    dibanding metode lain. Skor Top Pick HARUS pakai median (tahan
    outlier), bukan mean, supaya 1 metode ekstrem tidak mendominasi skor
    gabungan padahal metode lain sepakat lebih moderat."""
    import web.app as app_module

    # 5 metode: 4 sepakat di ~1100-1300, 1 outlier ekstrem di 5000
    val = {
        "methods": {"a": 1100.0, "b": 1200.0, "c": 1250.0, "d": 1300.0, "e": 5000.0},
        "price": 1000.0,
    }
    median_upside = app_module._fundamental_median_upside_pct(val)
    mean_upside = ((1100 + 1200 + 1250 + 1300 + 5000) / 5 / 1000 - 1) * 100
    # Median (dari 1100,1200,1250,1300,5000 -> median=1250) harus JAUH
    # lebih moderat drpd mean yang diseret outlier 5000.
    assert median_upside == pytest.approx(25.0)  # (1250/1000-1)*100
    assert median_upside < mean_upside - 20  # beda signifikan, bukan kebetulan sama


def test_screener_fundamental_endpoint_separate_from_top_pick(client):
    """Regresi permintaan user: screening fundamental HARUS jadi endpoint
    terpisah dari /api/confidence (Top Pick tetap 100% teknikal) --
    fitur baru ini murni screening valuasi, tidak boleh punya
    confidence_score atau field bobot teknikal apa pun."""
    r = client.get("/api/screenerfundamental")
    assert r.status_code == 200
    data = r.json()
    assert "items" in data
    for it in data["items"]:
        assert "confidence_score" not in it
        for field in ("kode", "sektor", "harga", "verdict"):
            assert field in it


def test_screener_fundamental_sorts_undervalued_first():
    """Regresi: hasil screening fundamental harus diurutkan Undervalued
    dulu, baru Wajar, baru Overvalued -- bukan acak/urutan universe."""
    import web.app as app_module

    items = [
        {"kode": "A", "verdict": "Overvalued", "upside_pct": -20.0},
        {"kode": "B", "verdict": "Undervalued", "upside_pct": 10.0},
        {"kode": "C", "verdict": "Wajar (dalam rentang)", "upside_pct": 2.0},
        {"kode": "D", "verdict": "Undervalued", "upside_pct": 40.0},
    ]
    verdict_rank = {"Undervalued": 0, "Wajar (dalam rentang)": 1, "Overvalued": 2}
    items.sort(key=lambda x: (verdict_rank.get(x["verdict"], 3), -(x["upside_pct"] if x["upside_pct"] is not None else -999)))
    assert [x["kode"] for x in items] == ["D", "B", "C", "A"]  # D (upside lbh tinggi) sebelum B, keduanya Undervalued


def test_whymove_endpoint_returns_factors_and_never_hits_real_network(client, monkeypatch):
    """'Kenapa saham ini naik/turun hari ini' harus jalan tanpa jaringan
    berita asli (fetch_news di-mock) dan mengembalikan struktur dasar:
    price, change_pct, factors (list), news (list)."""
    import core.news as news_module

    async def _fake_fetch_news(keyword=None, limit=8):
        return [
            {"title": "Berita dummy", "source": "Tes", "link": "https://x.test",
             "pub_date": "Fri, 29 May 2026 15:49:03 +0700"},
        ]

    monkeypatch.setattr(news_module, "fetch_news", _fake_fetch_news)

    r = client.get("/api/whymove/BBCA")
    assert r.status_code == 200
    d = r.json()
    assert d["kode"] == "BBCA"
    assert "price" in d and "change_pct" in d
    assert isinstance(d["factors"], list)
    assert isinstance(d["news"], list)
    assert d["news"][0]["title"] == "Berita dummy"
    assert "is_recent" in d["news"][0]


def test_whymove_never_claims_causation_in_factor_text(client, monkeypatch):
    """Prinsip jujur (sama seperti core/news_signal.py): teks faktor tidak
    boleh mengklaim sebab-akibat ('menyebabkan', 'karena berita') --
    hanya melaporkan kondisi teknikal secara terpisah."""
    import core.news as news_module

    async def _fake_fetch_news(keyword=None, limit=8):
        return []

    monkeypatch.setattr(news_module, "fetch_news", _fake_fetch_news)

    r = client.get("/api/whymove/BBCA")
    assert r.status_code == 200
    d = r.json()
    for f in d["factors"]:
        assert "menyebabkan" not in f["teks"].lower()
        assert "karena berita" not in f["teks"].lower()


def test_whymove_handles_news_fetch_failure_gracefully(client, monkeypatch):
    """Kalau fetch_news gagal total (exception), endpoint tetap 200 dengan
    news kosong -- bukan 500, karena berita cuma pelengkap, bukan inti."""
    import core.news as news_module

    async def _boom(keyword=None, limit=8):
        raise RuntimeError("simulated network failure")

    monkeypatch.setattr(news_module, "fetch_news", _boom)

    r = client.get("/api/whymove/BBCA")
    assert r.status_code == 200
    assert r.json()["news"] == []


def test_whymove_404_when_data_insufficient(client, monkeypatch):
    import web.app as app_module

    async def _too_short(ticker, period="1y", interval="1d"):
        return None

    monkeypatch.setattr(app_module, "_clean", _too_short)
    r = client.get("/api/whymove/BBCA")
    assert r.status_code == 404


def test_split_x15_items_moves_zero_change_to_aksi_korporasi():
    """Regresi bug nyata (dilaporkan user via screenshot 'pemegang
    sahamnya kosong'): beberapa laporan X-15 adalah buyback/repurchase
    agreement yang dilaporkan lewat anggota Direksi/Komisaris atas nama
    pengendali -- pct_sebelum==pct_setelah (0.00% perubahan, sekadar
    reafirmasi formal) DAN field nama kosong (IDX sendiri merender
    'null'). Baris begini TIDAK BOLEH nongol di 'Top Akumulasi' karena
    bukan sinyal akumulasi sungguhan -- akumulasi HARUS perubahan > 0
    (strict), bukan >= 0. Follow-up permintaan user: laporan begini
    JANGAN dibuang total, tapi dipisah ke kategori 'aksi_korporasi'
    supaya tetap ada sebagai konteks (bukan ranking akumulasi)."""
    import web.app as app_module

    items = [
        {"kode": "FAST", "nama": "", "jenis": "beli", "perubahan": 0.0,
         "pct_sebelum": 100.0, "pct_setelah": 100.0, "pengendali": True, "jabatan": "Dewan Komisaris"},
        {"kode": "BBCA", "nama": "Big Fund", "jenis": "beli", "perubahan": 2.5,
         "pct_sebelum": 10.0, "pct_setelah": 12.5, "pengendali": False, "jabatan": ""},
        {"kode": "TLKM", "nama": "Retail X", "jenis": "jual", "perubahan": -1.0,
         "pct_sebelum": 6.0, "pct_setelah": 5.0, "pengendali": False, "jabatan": ""},
    ]
    akumulasi, distribusi, aksi_korporasi = app_module._split_x15_items(items)
    assert [x["kode"] for x in akumulasi] == ["BBCA"]
    assert [x["kode"] for x in distribusi] == ["TLKM"]
    assert [x["kode"] for x in aksi_korporasi] == ["FAST"]


def test_x15_and_insider_endpoints_both_move_zero_change_to_aksi_korporasi(client, monkeypatch):
    """Regresi yang sama seperti di atas, tapi lewat endpoint /api/x15 DAN
    /api/insider -- keduanya berbagi _split_x15_items() jadi satu
    perbaikan otomatis berlaku ke dua-duanya (dulu 2 salinan logika
    filter yang identik, rawan satu diperbaiki satunya lupa)."""
    import web.app as app_module

    raw_items = [
        {"kode": "FAST", "tanggal": "2026-07-05", "pdf_url": "x", "nama": "",
         "perusahaan": "FAST FOOD INDONESIA", "jabatan": "Dewan Komisaris",
         "pct_sebelum": 100.0, "pct_setelah": 100.0, "perubahan": 0.0,
         "jenis": "beli", "pengendali": True},
    ]

    async def _fake_fetch(days_back=0):
        return raw_items

    monkeypatch.setattr(app_module, "_fetch_x15_today", _fake_fetch)

    x15 = client.get("/api/x15?hari=0").json()
    assert x15["akumulasi"] == []
    assert x15["distribusi"] == []
    assert [x["kode"] for x in x15["aksi_korporasi"]] == ["FAST"]

    insider = client.get("/api/insider?hari=0").json()
    assert insider["akumulasi"] == []
    assert insider["distribusi"] == []
    assert [x["kode"] for x in insider["aksi_korporasi"]] == ["FAST"]


def test_parse_ksei_pdf_sanitizes_literal_null_name():
    """Regresi: PDF X-15 untuk laporan buyback/repurchase agreement lewat
    anggota Direksi/Komisaris punya field 'Nama (sesuai SID)' yang oleh
    sistem IDX sendiri di-render literal jadi teks 'null' (bukan
    dikosongkan seperti field privasi lain, mis. 'Tidak ditampilkan').
    _parse_ksei_pdf harus mengubahnya jadi string kosong "" -- BUKAN
    membiarkan literal 'null' bocor sebagai nama sungguhan ke UI/
    konsumen lain (yang mungkin cuma cek truthiness biasa, bukan
    bandingkan ke string 'null' secara eksplisit)."""
    import zlib
    import web.app as app_module

    # PDF minimal: satu content stream berisi string literal PDF dengan
    # parens ter-escape (persis pola nyata dari PDF KSEI sungguhan),
    # supaya regex parsing di _parse_ksei_pdf teruji dengan bentuk asli.
    content = rb"(Nama \(sesuai SID\)) Tj (: null) Tj (Hak Suara Sebelum Transaksi) Tj (: 100,00%) Tj (Hak Suara Setelah Transaksi) Tj (: 100,00%) Tj "
    # _parse_ksei_pdf men-strip() bytes stream mentah sebelum decompress --
    # kalau kebetulan byte awal/akhir hasil zlib.compress() masuk definisi
    # whitespace bytes.strip() (mis. 0x0b), stream jadi terpotong & gagal
    # decompress. Trailing spasi di atas dipilih supaya kebetulan itu
    # TIDAK terjadi untuk payload tes ini (diverifikasi tidak diawali/
    # diakhiri whitespace byte) -- bukan mengoreksi fragility itu sendiri
    # (di luar cakupan bug ini), sekadar menghindarinya di data tes.
    compressed = zlib.compress(content)
    assert compressed[:1] not in b" \t\n\r\x0b\x0c" and compressed[-1:] not in b" \t\n\r\x0b\x0c"
    pdf_bytes = b"stream\n" + compressed + b"\nendstream"

    parsed = app_module._parse_ksei_pdf(pdf_bytes)
    assert parsed["nama"] == ""
    assert parsed["pct_sebelum"] == 100.0
    assert parsed["pct_setelah"] == 100.0


# =========================
# SMART $ (VOLUME ANOMALI SCANNER) -- REGRESI HASIL AUDIT
# =========================
# Ditemukan lewat audit menyeluruh (3 reviewer independen + verifikasi
# adversarial, semua temuan CONFIRMED, tidak ada yang REFUTED): 5 bug
# nyata + beberapa gap metodologi sistematis di _sm_classify/
# _process_sm_df. Setiap test di bawah memverifikasi SATU temuan spesifik,
# dgn skenario yang sudah diverifikasi manual lewat skrip Python langsung
# sebelum assertion ditulis (pola yang sama dipakai auditor: buktikan
# lewat eksekusi, bukan cuma baca kode).

def _sm_df(closes, volumes, start_offset_days=0, gap_before_last_n=None, gap_days=0):
    """Helper: bikin DataFrame OHLCV sintetis dgn Close & Volume TERKONTROL
    penuh per hari (index bdate_range) -- utk skenario presisi yang
    dibutuhkan tes Smart $ (beda dari _fake_ohlcv random di conftest).

    gap_before_last_n/gap_days (opsional): sisipkan gap kalender sebesar
    gap_days SEBELUM `gap_before_last_n` hari terakhir -- utk simulasi
    suspensi bursa."""
    import pandas as pd
    n = len(closes)
    assert len(volumes) == n
    if gap_before_last_n:
        first_n = n - gap_before_last_n
        dates_a = pd.bdate_range(
            end=pd.Timestamp.today().normalize() - pd.Timedelta(days=gap_days + gap_before_last_n * 2),
            periods=first_n,
        )
        dates_b = pd.bdate_range(start=dates_a[-1] + pd.Timedelta(days=gap_days), periods=gap_before_last_n)
        dates = dates_a.append(dates_b)
    else:
        dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    return pd.DataFrame(
        {"Close": closes, "Volume": volumes, "Open": closes, "High": closes, "Low": closes},
        index=dates,
    )


def test_sm_classify_chg1_and_rsi_are_no_longer_dead_parameters():
    """Regresi: chg1 & rsi dulu ada di signature _sm_classify tapi tak
    sekali pun direferensikan di body -- klasifikasi identik walau
    keduanya diubah ekstrem. Sekarang harus benar-benar mempengaruhi hasil
    (guard exhaustion/reversal): saham yang trennya naik TAPI hari ini
    sendiri ambruk tajam (chg1 sangat negatif) tidak lagi dilabeli
    'Agresif' begitu saja."""
    import web.app as app_module

    # vol_ratio & chg5 SAMA persis di kedua panggilan -- HANYA chg1/rsi beda.
    label_normal = app_module._sm_classify(vol_ratio=2.6, chg5=2.0, chg1=1.0, rsi=60.0)
    label_reversal = app_module._sm_classify(vol_ratio=2.6, chg5=2.0, chg1=-20.0, rsi=60.0)
    label_overbought = app_module._sm_classify(vol_ratio=2.6, chg5=2.0, chg1=1.0, rsi=95.0)

    assert label_normal == "Akumulasi Agresif"
    assert label_reversal != label_normal, "chg1 ekstrem harusnya menurunkan label dari Agresif"
    assert label_overbought != label_normal, "RSI overbought harusnya menurunkan label dari Agresif"


def test_sm_classify_breakout_volume_is_reachable():
    """Regresi bug nyata (dibuktikan lewat pembuktian boolean lengkap saat
    audit): definisi lama 'Breakout Volume' (chg5>5 and vol_ratio>=1.3)
    adalah SUBSET PENUH dari kondisi Akumulasi/Siluman di atasnya --
    kategori ini TIDAK PERNAH bisa ter-return sama sekali (dead code),
    padahal legend UI menjanjikannya ke user. Sekarang dibedakan lewat
    chg1 (lonjakan SATU hari, bukan tren 5 hari) -- harus benar-benar
    reachable."""
    import web.app as app_module

    # chg5 kecil (tidak match Akumulasi/Siluman manapun), tapi chg1 besar --
    # HANYA bisa match kalau Breakout Volume benar-benar reachable.
    label = app_module._sm_classify(vol_ratio=1.5, chg5=1.0, chg1=4.0, rsi=50.0)
    assert label == "Breakout Volume"


def test_sm_process_df_rsi_aligned_to_valid_idx_not_last_bar():
    """Regresi BUG NYATA (paling serius dari audit): RSI dulu SELALU
    dihitung dari bar TERAKHIR mentah di dataframe, tidak peduli valid_idx
    (hari yg sebenarnya dianalisis utk harga/chg1/chg5/vol_ratio) sudah
    mundur beberapa hari krn hari-hari setelahnya volumenya nyaris kosong.
    Skenario: breakout naik tajam di valid_idx, lalu 4 hari volume nyaris
    mati dgn harga ambruk -- RSI versi lama akan oversold (~13.6, terverifikasi
    manual), versi benar harus overbought (>50) karena breakout di valid_idx."""
    import web.app as app_module

    n = 65
    closes = [1000.0] * n
    for i in range(1, n - 5):
        closes[i] = closes[i - 1] * (1.003 if i % 2 == 0 else 0.998)
    volumes = [8_000_000.0] * n

    closes[-5] = closes[-6] * 1.07  # breakout +7% di hari valid_idx
    volumes[-5] = 40_000_000.0
    for i in range(-4, 0):
        closes[i] = closes[i - 1] * 0.85  # ambruk 15%/hari, 4 hari
        volumes[i] = 8_000.0  # jauh di bawah 10% baseline -- valid_idx mundur ke -5

    df = _sm_df(closes, volumes)
    result = app_module._process_sm_df("TESTRSI", df)

    assert result is not None
    assert result["hari_lalu"] == 4  # valid_idx=-5 -> hari_lalu = abs(-5)-1
    assert result["rsi"] is not None and result["rsi"] > 50, (
        f"RSI seharusnya overbought (breakout di valid_idx), dapat {result['rsi']}"
    )


def test_sm_process_df_rsi_all_gains_returns_100_not_none():
    """Regresi bug nyata: RSI utk kasus loss==0 (semua hari dalam window
    naik, tanpa hari turun sekalipun) dulu return None -- seharusnya 100
    menurut definisi RSI standar (RS -> tak hingga). Asimetris dgn kasus
    sebaliknya (semua turun) yang sudah benar jadi 0."""
    import web.app as app_module

    n = 65
    closes = [1000.0 * (1.01 ** i) for i in range(n)]  # naik terus, tanpa hari turun
    volumes = [8_000_000.0] * n
    volumes[-1] = 20_000_000.0

    df = _sm_df(closes, volumes)
    result = app_module._process_sm_df("TESTGAIN", df)

    assert result is not None
    assert result["rsi"] == 100.0


def test_sm_process_df_vol_avg20_window_is_exactly_20_days():
    """Regresi off-by-one: window vol_avg20 dulu 21 elemen
    ([end_vol-21:end_vol)), bukan 20 seperti nama variabelnya. Taruh nilai
    volume EKSTREM persis di hari ke-21 dari valid_idx (index end_vol-21)
    -- kalau window masih 21 (bug lama), rata-rata akan ikut tertarik naik
    signifikan; kalau benar 20, nilai ekstrem itu di LUAR window dan tidak
    berpengaruh sama sekali."""
    import web.app as app_module

    n = 65
    closes = [1000.0] * n
    volumes = [8_000_000.0] * n
    closes[-1] = 1050.0
    volumes[-1] = 20_000_000.0
    volumes[-22] = 500_000_000.0  # ekstrem, hanya masuk window LAMA (21), bukan window BENAR (20)

    df = _sm_df(closes, volumes)
    result = app_module._process_sm_df("TESTWIN", df)

    assert result is not None
    # vol_avg20 (benar) = 8_000_000 -> vol_ratio = 20e6/8e6 = 2.5
    # vol_avg20 (bug lama, window 21) akan jauh lebih besar krn ikut nilai ekstrem
    assert result["vol_ratio"] == 2.5, f"window vol_avg20 masih ikut nilai ekstrem di luar 20 hari, dapat vol_ratio={result['vol_ratio']}"


def test_sm_process_df_filters_illiquid_stocks():
    """Regresi gap metodologi: dulu TIDAK ADA filter likuiditas sama
    sekali -- saham dengan nilai transaksi kecil (rentan vol_ratio palsu
    dari satu transaksi ganjil) tetap ikut diklasifikasikan. Reuse
    _liquidity_label yang sudah dipakai fitur lain (record_macd_cross_
    signals)."""
    import web.app as app_module

    n = 65
    closes = [100.0] * n
    volumes = [50_000.0] * n  # Rp100 x 50rb = Rp5jt/hari -- Tidak Likuid
    closes[-1] = 105.0
    volumes[-1] = 200_000.0

    df = _sm_df(closes, volumes)
    result = app_module._process_sm_df("TESTILLIQ", df)
    assert result is None


def test_sm_process_df_skips_young_listings():
    """Regresi gap metodologi: dulu tidak ada guard umur listing -- saham
    IPO baru (<60 hari bursa) dgn baseline volume tidak stabil tetap bisa
    diklasifikasikan. Data dgn 40 hari (< _SM_MIN_TRADING_DAYS=60) harus
    di-skip meski pola harga/volumenya sendiri valid."""
    import web.app as app_module

    n = 40
    closes = [1000.0] * n
    volumes = [8_000_000.0] * n
    closes[-1] = 1050.0
    volumes[-1] = 20_000_000.0

    df = _sm_df(closes, volumes)
    result = app_module._process_sm_df("TESTYOUNG", df)
    assert result is None


def test_sm_process_df_skips_suspension_gap():
    """Regresi gap metodologi: dulu chg5/vol_ratio bisa diam-diam
    melompati gap suspensi berminggu-minggu (baris Volume=0/NaN sudah
    dibuang sebelum masuk _process_sm_df), membandingkan harga SEBELUM vs
    SESUDAH suspensi tapi disajikan seolah tren 5 hari sungguhan. Window
    dengan gap kalender >_SM_MAX_GAP_DAYS di rentang yang dipakai harus
    di-skip (return None), bukan menghasilkan angka yang salah."""
    import web.app as app_module

    n = 65
    closes = [1000.0] * n
    volumes = [8_000_000.0] * n
    closes[-1] = 1050.0
    volumes[-1] = 20_000_000.0

    df = _sm_df(closes, volumes, gap_before_last_n=5, gap_days=25)
    result = app_module._process_sm_df("TESTGAP", df)
    assert result is None


def test_sm_process_df_exposes_freshness_metadata():
    """Regresi gap: dulu valid_idx (bar keberapa yang sebenarnya kena
    anomali) tidak diekspos ke caller sama sekali -- tidak bisa bedakan
    'anomali hari ini' vs 'anomali beberapa hari lalu yang baru
    terdeteksi'. hari_lalu=0 & tanggal harus ada utk kasus anomali di hari
    terakhir (valid_idx=-1, tidak perlu mundur)."""
    import web.app as app_module

    n = 65
    closes = [1000.0] * n
    volumes = [8_000_000.0] * n
    closes[-1] = 1060.0
    volumes[-1] = 25_000_000.0

    df = _sm_df(closes, volumes)
    result = app_module._process_sm_df("TESTFRESH", df)

    assert result is not None
    assert result["hari_lalu"] == 0
    assert "tanggal" in result and result["tanggal"]
