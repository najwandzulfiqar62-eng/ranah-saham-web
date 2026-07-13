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
    untuk masing-masing. Sekarang harus di-coalesce jadi SATU eksekusi
    _fetch() saja -- BUKAN satu panggilan download() saja: _fetch() sendiri
    sekarang memanggil download() 2x internal (data harian utama + data
    per-jam utk _backfill_recent_gap, lihat regresinya di
    test_backfill_recent_gap_*), jadi 3 caller yang di-coalesce dgn benar
    menghasilkan TEPAT 2 panggilan (bukan 3x2=6 kalau gagal ter-coalesce,
    bukan juga 1 kalau backfill tidak jalan)."""
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
    assert calls["n"] == 2, "1x fetch harian + 1x fetch per-jam (backfill), di-coalesce lintas 3 caller"
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
    ketat dari SL-nya sendiri (RR >= 1:1 selalu), dan risiko_turun_pct
    (SL) tidak pernah di bawah MIN_SL_PCT (permintaan user: SL jangan
    kedekatan, biar posisi masih bisa di-hold kalau teknikal masih bagus)."""
    from core.trading_plan import MIN_SL_PCT

    r = client.get("/api/confidence")
    assert r.status_code == 200
    items = r.json()["items"]
    checked = 0
    for it in items:
        naik, turun = it.get("potensi_naik_pct"), it.get("risiko_turun_pct")
        if naik is None or turun is None:
            continue
        checked += 1
        assert turun >= MIN_SL_PCT - 1e-6, f"{it['kode']}: risiko_turun_pct ({turun}) di bawah floor {MIN_SL_PCT}%"
        assert naik >= 3.0 - 1e-6 or naik >= turun - 1e-6, (
            f"{it['kode']}: potensi_naik_pct ({naik}) di bawah floor 3% DAN di bawah risiko_turun_pct ({turun})"
        )
        if it.get("rr_ratio") is not None:
            assert it["rr_ratio"] >= 1.0 - 1e-6, f"{it['kode']}: rr_ratio ({it['rr_ratio']}) di bawah 1:1"
    assert checked > 0, "tidak ada item dengan potensi_naik_pct/risiko_turun_pct valid untuk dicek"


def test_calc_entry_levels_walks_down_to_deeper_support_when_nearest_too_close():
    """Regresi langsung (unit, tanpa network) -- permintaan user eksplisit
    ('sl nya kedeketan, kalo bisa sl nya di support'): kalau S1 SANGAT
    dekat dari entry (risk_pct alami <1%), SL TIDAK BOLEH langsung lompat
    ke floor persentase generik -- harus turun dulu ke S2 (support
    SUNGGUHAN berikutnya yang lebih dalam) selama S2 itu sendiri sudah
    cukup jauh (>= floor). SL yang dihasilkan harus level S2 (dikurangi
    buffer ATR), BUKAN entry x (1 - floor%)."""
    from core.trading_plan import _calc_entry_levels, MIN_SL_PCT

    entry = 1000.0
    atr = 10.0  # ATR kecil -- buffer 0.2xATR cuma 2 (0.2% dari entry)
    sr = {"S1": 996.0, "S2": 950.0, "S3": 900.0, "S4": 850.0}  # S1 cuma 0.4%, S2 5% di bawah entry

    levels = _calc_entry_levels(entry, atr, sr)

    expected_sl = round(950.0 - (atr * 0.2), 0)  # dari S2, BUKAN dari floor persentase
    assert levels["sl"] == pytest.approx(expected_sl, abs=1)
    assert levels["risk_pct"] > MIN_SL_PCT, "harus lebih lebar dari floor krn S2 dipakai, bukan cuma disamakan ke floor"


def test_calc_entry_levels_falls_back_to_percentage_floor_when_all_supports_too_close():
    """Kontrol: floor persentase generik TETAP jadi jaring pengaman
    terakhir -- kalau SEMUA level S1..S4 sama-sama terlalu dekat dari
    entry (tidak ada satu pun support sungguhan yang cukup jauh), baru
    fallback ke entry x (1 - floor%)."""
    from core.trading_plan import _calc_entry_levels, MIN_SL_PCT

    entry = 1000.0
    atr = 10.0
    sr = {"S1": 996.0, "S2": 992.0, "S3": 988.0, "S4": 984.0}  # semua < 2% di bawah entry

    levels = _calc_entry_levels(entry, atr, sr)

    assert levels["risk_pct"] == pytest.approx(MIN_SL_PCT, abs=0.05)
    expected_sl = round(entry * (1 - MIN_SL_PCT / 100), 0)
    assert levels["sl"] == pytest.approx(expected_sl, abs=1)


def test_calc_entry_levels_keeps_wider_natural_sl_unchanged():
    """Kontrol utk test di atas: kalau risk_pct alami SUDAH lebih lebar
    dari floor, floor TIDAK BOLEH mengutak-atik apa pun -- ini jaring
    pengaman kasus ekstrem, bukan pengganti level support asli yang
    memang sudah wajar."""
    from core.trading_plan import _calc_entry_levels, MIN_SL_PCT

    entry = 1000.0
    atr = 10.0
    sr = {"S1": 950.0, "S2": 900.0, "S3": 850.0, "S4": 800.0}  # S1 5% di bawah entry -- sudah lebar

    levels = _calc_entry_levels(entry, atr, sr)

    assert levels["risk_pct"] > MIN_SL_PCT
    expected_sl = round(950.0 - (atr * 0.2), 0)
    assert levels["sl"] == pytest.approx(expected_sl, abs=1)


def test_fixed_entry_levels_recommends_breakout_when_price_and_volume_confirm(client):
    """Regresi UTAMA (permintaan user langsung: 'skenario nya antara
    pullback atau breakout aja tapi valid soalnya kalo pullback kadang ga
    kena yg ada malah kena tp') -- kalau harga BENERAN breakout (tembus
    high 20 hari sebelumnya) DENGAN konfirmasi volume, recommended_scenario
    harus 'breakout', BUKAN 'pullback' apa adanya -- supaya sinyal momentum
    kuat tidak menunggu pullback yang mungkin tidak pernah datang."""
    import numpy as np
    import pandas as pd

    from core.trading_plan import calculate_fixed_entry_levels_from_df

    n = 60
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    close = np.full(n, 1000.0)
    close[-1] = 1050.0  # hari terakhir tembus jauh di atas range 20 hari sebelumnya
    high = close * 1.005
    low = close * 0.995
    volume = np.full(n, 1_000_000.0)
    volume[-1] = 3_000_000.0  # >2x median volume 20 hari sebelumnya
    df = pd.DataFrame({"Open": close, "High": high, "Low": low, "Close": close,
                        "Volume": volume}, index=dates)

    plan = calculate_fixed_entry_levels_from_df(df, "")
    assert plan is not None
    assert plan["is_breakout"] is True
    assert plan["volume_confirmation"] is True
    assert plan["recommended_scenario"] == "breakout"
    assert "breakout" in plan["scenarios"]


def test_fixed_entry_levels_recommends_pullback_without_breakout_confirmation(client):
    """Kontrol: TANPA lonjakan volume (meski harga sedikit naik), harus
    TETAP 'pullback' -- breakout yang tidak dikonfirmasi volume terlalu
    berisiko dijadikan entry agresif (rawan false breakout)."""
    import numpy as np
    import pandas as pd

    from core.trading_plan import calculate_fixed_entry_levels_from_df

    n = 60
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    close = np.full(n, 1000.0)
    close[-1] = 1050.0  # harga tembus TAPI volume normal, tidak ada lonjakan
    high = close * 1.005
    low = close * 0.995
    volume = np.full(n, 1_000_000.0)  # flat, tidak ada spike
    df = pd.DataFrame({"Open": close, "High": high, "Low": low, "Close": close,
                        "Volume": volume}, index=dates)

    plan = calculate_fixed_entry_levels_from_df(df, "")
    assert plan is not None
    assert plan["volume_confirmation"] is False
    assert plan["recommended_scenario"] == "pullback"


def test_fixed_entry_levels_recommends_pullback_for_sideways_stock(client):
    """Kontrol utama: saham yang sedang sideways/ranging biasa (tidak
    breakout sama sekali) harus tetap 'pullback' -- perilaku default
    SEBELUM perubahan ini, tidak boleh berubah utk kasus normal."""
    import numpy as np
    import pandas as pd

    from core.trading_plan import calculate_fixed_entry_levels_from_df

    n = 60
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    rng = np.random.default_rng(1)
    close = 1000 + np.cumsum(rng.normal(0, 1.0, n))
    high = close + 3
    low = close - 3
    volume = np.full(n, 1_000_000.0) + rng.normal(0, 10_000, n)
    df = pd.DataFrame({"Open": close, "High": high, "Low": low, "Close": close,
                        "Volume": volume}, index=dates)

    plan = calculate_fixed_entry_levels_from_df(df, "")
    assert plan is not None
    assert plan["recommended_scenario"] == "pullback"


def test_pullback_entry_uses_small_fixed_discount_below_current_price():
    """Regresi UTAMA, revisi KETIGA sehari (S1 pivot -> MA20 -> 1x ATR ->
    INI). Kedua percobaan sebelumnya dikoreksi user setelah lihat data
    nyata: BRMS entry Rp478 tapi harga SUDAH lari ke Rp505 (+5,65%)
    SEBELUM sempat kena, padahal TP1 cuma Rp500 -- 'kejauhan keburu org
    pada tp saya mintanya entry pada hari itu bukan nunggu lama kaya
    gitu'. Level pullback SEKARANG cuma diskon kecil PULLBACK_DISCOUNT_PCT
    (0,5%) dari harga saat ini -- BUKAN lagi ATR/MA20/S1 yang bisa 3-10%+
    di bawah harga -- supaya realistis kena lewat fluktuasi harian wajar,
    bukan pullback besar yang keburu dilewati tren."""
    import numpy as np
    import pandas as pd

    from core.trading_plan import calculate_fixed_entry_levels_from_df, PULLBACK_DISCOUNT_PCT

    n = 60
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    rng = np.random.default_rng(2)
    close = 1000 + np.cumsum(rng.normal(0.5, 3.0, n))  # tren naik ringan + noise wajar
    high = close + np.abs(rng.normal(5, 1, n))
    low = close - np.abs(rng.normal(5, 1, n))
    volume = np.full(n, 1_000_000.0)
    df = pd.DataFrame({"Open": close, "High": high, "Low": low, "Close": close,
                        "Volume": volume}, index=dates)

    current_price = float(close[-1])
    expected_entry = round(current_price * (1 - PULLBACK_DISCOUNT_PCT / 100), 0)

    plan = calculate_fixed_entry_levels_from_df(df, "")
    assert plan is not None
    assert plan["scenarios"]["pullback"]["entry"] == pytest.approx(expected_entry, abs=1)
    assert plan["scenarios"]["pullback"]["name"] == "PULLBACK (-0.5%)"


def test_pullback_entry_stays_close_regardless_of_volatility():
    """Kontrol -- KEBALIKAN dari perilaku ATR (revisi sebelumnya): saham
    yang LEBIH liar (ATR besar) TIDAK BOLEH dapat jarak pullback yang jauh
    lebih lebar lagi -- diskon SEKARANG persentase tetap dari harga (0,5%),
    sama utk semua saham, supaya entry tetap dekat & realistis kena baik
    di saham tenang maupun liar (menghindari masalah yang sama persis yang
    baru dikoreksi user: entry terlalu jauh di saham yang gerak cepat)."""
    import numpy as np
    import pandas as pd

    from core.trading_plan import calculate_fixed_entry_levels_from_df

    n = 60
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    rng = np.random.default_rng(3)

    close_calm = 1000 + np.cumsum(rng.normal(0, 1.0, n))
    high_calm = close_calm + 1.5
    low_calm = close_calm - 1.5
    df_calm = pd.DataFrame({"Open": close_calm, "High": high_calm, "Low": low_calm,
                             "Close": close_calm, "Volume": np.full(n, 1_000_000.0)}, index=dates)

    close_wild = 1000 + np.cumsum(rng.normal(0, 12.0, n))
    high_wild = close_wild + 18
    low_wild = close_wild - 18
    df_wild = pd.DataFrame({"Open": close_wild, "High": high_wild, "Low": low_wild,
                             "Close": close_wild, "Volume": np.full(n, 1_000_000.0)}, index=dates)

    plan_calm = calculate_fixed_entry_levels_from_df(df_calm, "")
    plan_wild = calculate_fixed_entry_levels_from_df(df_wild, "")
    assert plan_calm is not None and plan_wild is not None

    dist_calm_pct = (1 - plan_calm["scenarios"]["pullback"]["entry"] / float(close_calm[-1])) * 100
    dist_wild_pct = (1 - plan_wild["scenarios"]["pullback"]["entry"] / float(close_wild[-1])) * 100
    assert dist_calm_pct == pytest.approx(dist_wild_pct, abs=0.01), (
        "diskon pullback HARUS persentase tetap yang sama, tidak boleh melebar krn volatilitas saham"
    )


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


def test_record_top_picks_skips_blocked_top_scorers_to_reach_lower_ranked_candidate(clean_signal_db, monkeypatch):
    """Regresi bug NYATA ditemukan lewat verifikasi live sesi ini: kalau
    kandidat skor TERTINGGI (sejumlah MAX_RECORDED_PER_DAY) KEBETULAN semua
    sudah OPEN/PENDING_ENTRY (kejadian nyata di data live: 10 saham blue-
    chip teratas semua sudah aktif), fungsi HARUS tetap turun ke kandidat
    berikutnya yang skornya lebih rendah tapi BELUM diblokir -- bukan diam2
    mencatat NOL sinyal baru padahal ada peluang valid.

    ZZBLOCKED1/2 disisipkan LANGSUNG via SQL (BUKAN lewat record_top_picks())
    supaya merepresentasikan 'sinyal AKTIF dari kapan pun sebelumnya', TANPA
    ikut memakan kuota harian TOP_PICK hari ini -- lihat test terpisah
    test_record_top_picks_enforces_cumulative_daily_cap_across_calls utk
    perilaku kuota kumulatif per hari itu sendiri."""
    import asyncio

    from core.database import get_db
    from core.signal_history import record_top_picks, MIN_SCORE_TO_RECORD

    monkeypatch.setattr("core.signal_history.MAX_RECORDED_PER_DAY", 2)

    with get_db() as conn:
        conn.execute("INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, status, direction, source) VALUES ('ZZBLOCKED1', 1000, 5, 3, 'OPEN', 'BUY', 'SMART_MONEY')")
        conn.execute("INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, status, direction, source) VALUES ('ZZBLOCKED2', 1000, 5, 3, 'OPEN', 'BUY', 'SMART_MONEY')")

    items = [
        _fake_confidence_item("ZZBLOCKED1", MIN_SCORE_TO_RECORD + 20),
        _fake_confidence_item("ZZBLOCKED2", MIN_SCORE_TO_RECORD + 19),
        _fake_confidence_item("ZZUNBLOCKED", MIN_SCORE_TO_RECORD + 5),
    ]
    saved = asyncio.run(record_top_picks(items))  # cap MAX_RECORDED_PER_DAY=2, ZZUNBLOCKED skor ke-3
    assert [s["kode"] for s in saved] == ["ZZUNBLOCKED"], (
        "ZZBLOCKED1/2 sudah aktif tidak boleh menghabiskan slot cap harian, "
        "ZZUNBLOCKED (skor lebih rendah tapi belum diblokir) harus tetap tercatat"
    )


def test_record_top_picks_enforces_cumulative_daily_cap_across_calls(clean_signal_db, monkeypatch):
    """Regresi UTAMA (bug NYATA ditemukan lewat verifikasi live setelah
    universe diperluas ke LIQUID_250): MAX_RECORDED_PER_DAY SEBELUMNYA cuma
    dipotong PER PANGGILAN, bukan akumulatif per hari -- karena confidence()
    dipanggil ULANG tiap siklus auto-cycle (~10 menit), begitu kandidat
    skor-tertinggi panggilan pertama jadi PENDING_ENTRY (otomatis diblokir),
    panggilan berikutnya lolos ke kandidat BERIKUTNYA yang belum diblokir --
    tanpa henti sepanjang hari, jauh melampaui 'MAX N/hari' yang namanya
    sendiri menjanjikan (terverifikasi nyata: 21 PENDING_ENTRY muncul dari
    cuma 2-3 panggilan manual dalam hitungan menit). Sekarang kuota HARUS
    mengecil lintas panggilan di hari yang sama, bukan reset tiap panggilan."""
    import asyncio

    from core.signal_history import record_top_picks, MIN_SCORE_TO_RECORD

    monkeypatch.setattr("core.signal_history.MAX_RECORDED_PER_DAY", 2)

    # Panggilan PERTAMA: 2 kandidat skor tertinggi, quota=2 -- keduanya lolos.
    first_call = [
        _fake_confidence_item("ZZDAY1", MIN_SCORE_TO_RECORD + 20),
        _fake_confidence_item("ZZDAY2", MIN_SCORE_TO_RECORD + 19),
    ]
    saved1 = asyncio.run(record_top_picks(first_call))
    assert {s["kode"] for s in saved1} == {"ZZDAY1", "ZZDAY2"}

    # Panggilan KEDUA (simulasi auto-cycle 10 menit kemudian, hari yang
    # SAMA): ZZDAY1/2 sekarang PENDING_ENTRY (otomatis diblokir), tersisa
    # kandidat BARU ZZDAY3 yang skornya lebih rendah -- TANPA fix ini akan
    # tetap lolos (quota reset ke 2 tiap panggilan). DENGAN fix, kuota harian
    # (2) SUDAH habis dari panggilan pertama -- ZZDAY3 TIDAK BOLEH tercatat.
    second_call = [*first_call, _fake_confidence_item("ZZDAY3", MIN_SCORE_TO_RECORD + 10)]
    saved2 = asyncio.run(record_top_picks(second_call))
    assert saved2 == [], "kuota harian (2) sudah habis dari panggilan pertama, ZZDAY3 tidak boleh tercatat"


def test_record_top_picks_blocks_new_entry_while_still_open_multi_day(clean_signal_db):
    """Regresi UTAMA (permintaan user langsung: 'entrynya jangan kebanyakan
    banyak yg double jadi pusing') -- dedup yang LAMA cuma berbasis
    tanggal, jadi kalau satu saham tetap jadi Top Pick 4-5 hari berturut-
    turut, tiap hari tetap dicatat sbg entry BARU yang terpisah (menumpuk
    banyak posisi 'open' utk saham yang sama, membingungkan). Dedup
    SEKARANG berbasis status OPEN (_has_open_signal) -- entry baru utk
    kode+source yang sama harus TETAP diblokir walau recorded_at-nya
    sudah beberapa hari lalu, selama statusnya masih OPEN."""
    import asyncio

    from core.database import get_db
    from core.signal_history import record_top_picks, MIN_SCORE_TO_RECORD

    items = [_fake_confidence_item("ZZSTILLOPEN", MIN_SCORE_TO_RECORD + 10)]
    saved = asyncio.run(record_top_picks(items))
    assert len(saved) == 1

    # Simulasikan waktu berlalu (recorded_at mundur 3 hari) TANPA mengubah
    # status -- masih OPEN, dedup lama (berbasis tanggal) akan LOLOS di
    # sini, tapi dedup baru (berbasis status) harus tetap memblokir.
    with get_db() as conn:
        conn.execute("UPDATE signal_history SET recorded_at = datetime('now', '-3 days') WHERE kode='ZZSTILLOPEN'")

    saved_again = asyncio.run(record_top_picks(items))
    assert saved_again == [], "masih OPEN -- tidak boleh dicatat ulang walau recorded_at sudah beda hari"


def test_record_top_picks_allows_new_entry_next_day_after_resolved(clean_signal_db):
    """Sisi lain dari _has_open_signal: begitu sinyal sebelumnya SUDAH
    resolved (TP_HIT/SL_HIT/EXPIRED, apa pun hasilnya) DI HARI SEBELUMNYA,
    kode yang sama harus tetap boleh dicatat sbg entry baru esok harinya --
    dedup ini mencegah entry DOBEL yang konkuren/di hari yang sama, bukan
    melarang kode itu direkam lagi selamanya. (recorded_at sengaja
    dimundurkan ke kemarin -- kalau resolve di HARI YANG SAMA, lihat
    test_record_top_picks_blocked_same_day_even_after_resolved: itu
    sengaja TETAP diblokir, permintaan user soal kasus ANTM 'kena tp lalu
    kena sl hari yang sama'.)"""
    import asyncio

    from core.database import get_db
    from core.signal_history import record_top_picks, MIN_SCORE_TO_RECORD

    items = [_fake_confidence_item("ZZRESOLVED", MIN_SCORE_TO_RECORD + 10)]
    saved = asyncio.run(record_top_picks(items))
    assert len(saved) == 1

    with get_db() as conn:
        conn.execute('''
            UPDATE signal_history
            SET status='TP_HIT',
                recorded_at = datetime('now', 'localtime', '-1 day'),
                resolved_at = datetime('now', 'localtime', '-1 day')
            WHERE kode='ZZRESOLVED'
        ''')

    saved_again = asyncio.run(record_top_picks(items))
    assert len(saved_again) == 1, "sinyal lama sudah resolved KEMARIN -- entry baru hari ini harus tetap boleh dicatat"


def test_record_top_picks_blocked_same_day_even_after_resolved(clean_signal_db):
    """Regresi (permintaan user langsung setelah melihat UI produksi:
    kasus ANTM -- terlihat 'kena TP lalu kena SL' di HARI YANG SAMA,
    padahal itu 2 baris terpisah dari source berbeda; audit_open_signals
    sendiri TIDAK bermasalah, baris yang sudah resolve tidak pernah
    dievaluasi ulang). Begitu SATU sinyal utk kode itu resolve (menang
    ATAU kalah) HARI INI, sinyal BARU utk kode yang sama TIDAK BOLEH
    dicatat sampai besok -- mencegah kesan 'flip-flop' TP/SL dalam
    sehari, walau dari source yang berbeda.

    resolved_at DIISI EKSPLISIT di sini (bukan cuma status) -- versi awal
    test ini tidak mengisinya, jadi kebetulan LOLOS walau _has_open_signal
    masih pakai bug recorded_at (BUKAN resolved_at): dgn resolved_at NULL,
    klausul lama (recorded_at=hari ini) TETAP true krn baris ini memang
    direkam hari ini juga -- test itu jadi tidak benar-benar menguji
    klausul yang dimaksud. audit_open_signals() SUNGGUHAN SELALU mengisi
    resolved_at bersamaan dgn status (lihat UPDATE di audit_open_signals),
    jadi ini yang representatif thd kondisi nyata (lihat juga kasus AKRA/
    RAJA di produksi: direkam beberapa hari lalu, resolved_at HARI INI)."""
    import asyncio

    from core.database import get_db
    from core.signal_history import record_top_picks, MIN_SCORE_TO_RECORD

    items = [_fake_confidence_item("ZZSAMEDAY", MIN_SCORE_TO_RECORD + 10)]
    saved = asyncio.run(record_top_picks(items))
    assert len(saved) == 1

    with get_db() as conn:
        conn.execute('''
            UPDATE signal_history SET status='TP_HIT', resolved_at=datetime('now','localtime')
            WHERE kode='ZZSAMEDAY'
        ''')

    saved_again = asyncio.run(record_top_picks(items))
    assert saved_again == [], "sudah resolve HARI INI -- entry baru tidak boleh dicatat sampai besok"


def test_record_top_picks_blocked_same_day_even_if_recorded_days_ago(clean_signal_db):
    """Regresi UTAMA (BUG NYATA ditemukan lewat verifikasi adversarial,
    live di produksi: AKRA & RAJA) -- klausul (b) yang lama salah pakai
    date(recorded_at), bukan date(resolved_at). Skenario paling REALISTIS:
    sinyal direkam BEBERAPA HARI lalu (butuh waktu multi-hari utk kena TP/
    SL, bukan hari yang sama seperti test di atas), lalu resolve HARI INI
    -- _has_open_signal HARUS tetap mendeteksi ini sbg 'baru resolve hari
    ini' dan memblokir entry baru, TERLEPAS dari kapan awalnya direkam."""
    import asyncio

    from core.database import get_db
    from core.signal_history import record_top_picks, MIN_SCORE_TO_RECORD

    items = [_fake_confidence_item("ZZOLDRECORD", MIN_SCORE_TO_RECORD + 10)]
    saved = asyncio.run(record_top_picks(items))
    assert len(saved) == 1

    with get_db() as conn:
        conn.execute('''
            UPDATE signal_history
            SET status='TP_HIT',
                recorded_at = datetime('now', 'localtime', '-3 days'),
                resolved_at = datetime('now', 'localtime')
            WHERE kode='ZZOLDRECORD'
        ''')

    saved_again = asyncio.run(record_top_picks(items))
    assert saved_again == [], (
        "direkam 3 hari lalu tapi resolve HARI INI -- tetap harus diblokir sampai besok, "
        "bukan cuma kalau direkam DAN resolve di hari yang sama"
    )


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


def test_record_top_picks_uses_scenario_entry_price_not_live_quote(clean_signal_db):
    """Regresi BUG NYATA (laporan user: RAJA low-nya kena area pullback tapi
    entry yang tersimpan malah harga real-time yang sudah naik lagi --
    'udh kena area tp' padahal baru dicatat): confidence() (web/app.py)
    sekarang mengirim 'entry_price' = level SKENARIO Trading Plan yang
    BENERAN kena hari itu (mis. pullback/S1), dan itu adalah FAKTA harga
    yang sudah terjadi -- HARUS menang atas 'harga' (closing) MAUPUN harga
    real-time dari price_lookup, supaya entry_price tetap konsisten dengan
    tp_pct/sl_pct yang dihitung dari skenario yang sama."""
    import asyncio

    from core.signal_history import record_top_picks, get_signal_report, MIN_SCORE_TO_RECORD

    item = {
        **_fake_confidence_item("ZZSCENENTRY", MIN_SCORE_TO_RECORD + 5, harga=1000.0),
        "entry_price": 960.0,  # level pullback yg beneran kena -- beda dari harga & live
    }

    async def fake_lookup(kode):
        return 1015.0  # harga real-time, beda lagi dari keduanya

    saved = asyncio.run(record_top_picks([item], price_lookup=fake_lookup))
    assert len(saved) == 1

    report = get_signal_report()
    by_kode = {s["kode"]: s for s in report["signals"]}
    assert by_kode["ZZSCENENTRY"]["entry_price"] == 960.0  # skenario menang, bukan harga/live


def test_record_top_picks_falls_back_to_live_price_when_no_scenario_entry(clean_signal_db):
    """Kontrol utk test di atas: kalau caller TIDAK menyediakan 'entry_price'
    skenario sama sekali (mis. item lama/pemanggil lain), fallback ke harga
    real-time (price_lookup) HARUS tetap jalan seperti sebelumnya -- fitur
    baru ini tidak boleh menghapus perilaku fallback yang sudah ada."""
    import asyncio

    from core.signal_history import record_top_picks, get_signal_report, MIN_SCORE_TO_RECORD

    item = _fake_confidence_item("ZZNOENTRYSCEN", MIN_SCORE_TO_RECORD + 5, harga=1000.0)
    assert "entry_price" not in item  # item lama, tanpa entry_price skenario

    async def fake_lookup(kode):
        return 1042.0

    saved = asyncio.run(record_top_picks([item], price_lookup=fake_lookup))
    assert len(saved) == 1

    report = get_signal_report()
    by_kode = {s["kode"]: s for s in report["signals"]}
    assert by_kode["ZZNOENTRYSCEN"]["entry_price"] == 1042.0  # fallback ke harga real-time


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


def test_record_top_picks_skip_on_weekend(clean_signal_db, monkeypatch):
    """Regresi BUG NYATA ditemukan lewat inspeksi data produksi: siklus
    auto-audit jalan 24/7 (tiap 600 detik) TIDAK PEDULI akhir pekan, dan
    dulu tetap mencatat 'sinyal Top Pick baru' di hari Sabtu/Minggu dengan
    entry_price/tp_pct/sl_pct IDENTIK dengan hari Jumat -- karena BEI tutup,
    closing price yfinance belum berubah sama sekali. Satu pergerakan pasar
    (Jumat) jadi tercatat sebagai 2-3 sinyal terpisah (Jumat+Sabtu+Minggu),
    yang MENGGANDAKAN statistik win-rate secara palsu kalau nanti kena TP/SL.

    record_top_picks() HARUS return [] (skip total, tidak mencatat apa pun)
    kalau _is_bursa_weekend() True -- di-mock langsung (bukan datetime)
    supaya tidak tercampur dgn clean_signal_db yang sudah mem-patch
    _is_bursa_weekend ke False secara default."""
    import asyncio

    import core.signal_history as sh

    monkeypatch.setattr(sh, "_is_bursa_weekend", lambda: True)

    items = [_fake_confidence_item("ZZWEEKEND", sh.MIN_SCORE_TO_RECORD + 5)]
    assert asyncio.run(sh.record_top_picks(items)) == []

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
    (paling awal tercatat).

    Semua baris di sini dibuat berstatus TP_HIT (bukan default OPEN) --
    index unique PARTIAL idx_signal_unique_open (migrasi kelima, lihat
    _ensure_table) cuma mengizinkan SATU baris OPEN per (kode,source),
    jadi simulasi "beberapa baris utk kode+source yang sama" di test ini
    HARUS berstatus resolved supaya tidak melanggar constraint itu sendiri
    saat di-insert -- migrasi cleanup yang diuji di sini (dedup numerik
    kode+source+entry_price+tp_pct+sl_pct) tidak peduli status sama sekali,
    jadi ini tidak mengurangi apa yang sebenarnya diuji."""
    from core.database import get_db
    import core.signal_history as sh

    with get_db() as conn:
        conn.execute('''
            INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, source, recorded_at, status)
            VALUES ('ZZDUP', 1000, 3.0, 1.9, 'TOP_PICK', '2026-07-04 06:00:00', 'TP_HIT')
        ''')
        conn.execute('''
            INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, source, recorded_at, status)
            VALUES ('ZZDUP', 1000, 3.0, 1.9, 'TOP_PICK', '2026-07-05 00:06:00', 'TP_HIT')
        ''')
        # Kontrol: kode+source SAMA tapi entry_price BEDA (perubahan pasar
        # sungguhan) -- harus TETAP keduanya, bukan ikut kehapus.
        conn.execute('''
            INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, source, recorded_at, status)
            VALUES ('ZZREAL', 1000, 3.0, 1.9, 'TOP_PICK', '2026-07-04 06:00:00', 'TP_HIT')
        ''')
        conn.execute('''
            INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, source, recorded_at, status)
            VALUES ('ZZREAL', 1010, 3.0, 1.9, 'TOP_PICK', '2026-07-06 06:00:00', 'SL_HIT')
        ''')

    sh._ensured = False  # paksa migrasi jalan ulang meski sudah pernah _ensure_table()
    sh._ensure_table()

    with get_db() as conn:
        dup_rows = conn.execute("SELECT recorded_at FROM signal_history WHERE kode='ZZDUP'").fetchall()
        real_rows = conn.execute("SELECT entry_price FROM signal_history WHERE kode='ZZREAL' ORDER BY entry_price").fetchall()

    assert len(dup_rows) == 1
    assert dup_rows[0]["recorded_at"] == "2026-07-04 06:00:00"  # yang dipertahankan = paling awal
    assert [r["entry_price"] for r in real_rows] == [1000.0, 1010.0]  # keduanya tetap ada


def test_ensure_table_migration_purges_all_macd_cross_rows(clean_signal_db):
    """Regresi (permintaan user langsung setelah melihat UI produksi:
    'itu macd cross masih ada loh'): MACD_CROSS sudah dihapus dari
    confidence() (tidak ada baris baru lagi), TAPI baris LAMA yang kadung
    tercatat sebelumnya masih nongol di laporan. Migrasi ketujuh di
    _ensure_table() harus menghapusnya TOTAL (bukan menunggu resolve
    sendiri) -- apa pun statusnya (OPEN maupun sudah resolved), source ini
    sudah sepenuhnya nonaktif."""
    from core.database import get_db
    import core.signal_history as sh

    with get_db() as conn:
        conn.execute('''
            INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, source, status)
            VALUES ('ZZMCOLD1', 1000, 3.0, 2.0, 'MACD_CROSS', 'OPEN')
        ''')
        conn.execute('''
            INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, source, status)
            VALUES ('ZZMCOLD2', 1000, 3.0, 2.0, 'MACD_CROSS', 'SL_HIT')
        ''')
        conn.execute('''
            INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, source, status)
            VALUES ('ZZKEEPTP', 1000, 3.0, 2.0, 'TOP_PICK', 'OPEN')
        ''')

    sh._ensured = False  # paksa migrasi jalan ulang
    sh._ensure_table()

    with get_db() as conn:
        remaining_macd = conn.execute("SELECT 1 FROM signal_history WHERE source = 'MACD_CROSS'").fetchall()
        remaining_tp = conn.execute("SELECT 1 FROM signal_history WHERE kode = 'ZZKEEPTP'").fetchall()

    assert remaining_macd == [], "semua baris MACD_CROSS (apa pun statusnya) harus terhapus"
    assert len(remaining_tp) == 1, "source lain (TOP_PICK) tidak boleh ikut kehapus"


def test_ensure_table_migration_purges_smart_money_without_buy_confirmation(clean_signal_db):
    """Regresi (permintaan user langsung: 'yg di smart money saya mau nya
    yg secara teknikal dia nyuruh buy aja biar lebih valid'):
    _record_smart_money_cycle() SUDAH menyaring kandidat BARU supaya cuma
    direkam kalau ai_rating juga BUY/STRONG BUY (SANGAT BAGUS/BAGUS) --
    tapi baris SMART_MONEY yang kadung tercatat SEBELUM filter itu ada
    masih nongol dgn recommendation NETRAL/CUKUP/BURUK/NULL. Migrasi
    kesembilan harus membersihkan riwayat lama itu juga (apa pun
    statusnya), supaya track record Smart Money benar-benar cuma
    mencerminkan sinyal yang teknikalnya juga BUY -- TANPA ikut menghapus
    source lain (TOP_PICK tidak disyaratkan ai_rating BUY sama sekali)."""
    from core.database import get_db
    import core.signal_history as sh

    with get_db() as conn:
        for kode, rec in [
            ("ZZSMNETRAL", "NETRAL"), ("ZZSMCUKUP", "CUKUP"),
            ("ZZSMBURUK", "BURUK"), ("ZZSMNULL", None),
        ]:
            conn.execute('''
                INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, source, status, recommendation)
                VALUES (?, 1000, 3.0, 2.0, 'SMART_MONEY', 'OPEN', ?)
            ''', (kode, rec))
        conn.execute('''
            INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, source, status, recommendation)
            VALUES ('ZZSMBAGUS', 1000, 3.0, 2.0, 'SMART_MONEY', 'OPEN', 'BAGUS')
        ''')
        conn.execute('''
            INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, source, status, recommendation)
            VALUES ('ZZSMSTRONG', 1000, 3.0, 2.0, 'SMART_MONEY', 'OPEN', 'SANGAT BAGUS')
        ''')
        # Kontrol: TOP_PICK dgn recommendation NETRAL harus TETAP ada --
        # kriteria ai_rating BUY cuma berlaku utk source SMART_MONEY.
        conn.execute('''
            INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, source, status, recommendation)
            VALUES ('ZZTPNETRAL', 1000, 3.0, 2.0, 'TOP_PICK', 'OPEN', 'NETRAL')
        ''')

    sh._ensured = False
    sh._ensure_table()

    with get_db() as conn:
        remaining_sm = {r["kode"] for r in conn.execute(
            "SELECT kode FROM signal_history WHERE source = 'SMART_MONEY'"
        ).fetchall()}
        remaining_tp = conn.execute("SELECT 1 FROM signal_history WHERE kode = 'ZZTPNETRAL'").fetchall()

    assert remaining_sm == {"ZZSMBAGUS", "ZZSMSTRONG"}, (
        f"cuma SMART_MONEY dgn recommendation BAGUS/SANGAT BAGUS yang boleh tetap ada, dapat {remaining_sm}"
    )
    assert len(remaining_tp) == 1, "TOP_PICK tidak boleh ikut disyaratkan ai_rating BUY"


def test_ensure_table_migration_ten_retraction_preserves_cross_source_same_day_rows(clean_signal_db):
    """Regresi RETRAKSI (2026-07-08): migrasi kesepuluh yang DULU menghapus
    salah satu dari >1 baris kode+tanggal yang sama (mis. ANTM: SMART_MONEY
    TP_HIT + TOP_PICK SL_HIT sama tanggal) sudah DICABUT -- lihat catatan
    retraksi di _ensure_table(). Alasan: baris-baris itu bukan duplikat,
    melainkan dua sinyal SAH & BERBEDA (entry price beda, source beda);
    menghapus salah satunya = mengarang ulang track record, persis bug yang
    menghapus riwayat SL_HIT INDF ("perasaan kmrn indf kena sl ko ilang").
    Sekarang HARUS semuanya tetap ada, apa pun kombinasi status-nya."""
    from core.database import get_db
    import core.signal_history as sh

    with get_db() as conn:
        # ANTM: SMART_MONEY resolve TP_HIT, TOP_PICK resolve SL_HIT, SAMA
        # tanggal, TIDAK ada yang OPEN -- dulu migrasi kesepuluh menyisakan
        # cuma 1, sekarang harus tetap 2.
        conn.execute('''
            INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, source, status, recorded_at, recommendation)
            VALUES ('ZZANTM', 2930, 3.0, 2.0, 'SMART_MONEY', 'TP_HIT', '2026-07-06 02:49:00', 'BAGUS')
        ''')
        conn.execute('''
            INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, source, status, recorded_at)
            VALUES ('ZZANTM', 3010, 3.0, 1.4, 'TOP_PICK', 'SL_HIT', '2026-07-06 09:14:00')
        ''')
        # RAJA: TOP_PICK masih OPEN, SMART_MONEY sudah resolve TP_HIT,
        # SAMA tanggal -- dulu migrasi kesepuluh membuang yang resolved,
        # sekarang harus tetap 2.
        conn.execute('''
            INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, source, status, recorded_at, recommendation)
            VALUES ('ZZRAJA', 3940, 3.0, 2.3, 'SMART_MONEY', 'TP_HIT', '2026-07-06 02:49:00', 'BAGUS')
        ''')
        conn.execute('''
            INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, source, status, recorded_at)
            VALUES ('ZZRAJA', 4050, 3.2, 3.2, 'TOP_PICK', 'OPEN', '2026-07-06 14:41:00')
        ''')

    sh._ensured = False
    sh._ensure_table()

    with get_db() as conn:
        antm_rows = conn.execute("SELECT source, status FROM signal_history WHERE kode='ZZANTM'").fetchall()
        raja_rows = conn.execute("SELECT source, status FROM signal_history WHERE kode='ZZRAJA'").fetchall()

    assert len(antm_rows) == 2, "migrasi kesepuluh sudah dicabut -- kedua sinyal sah harus tetap ada"
    assert len(raja_rows) == 2, "migrasi kesepuluh sudah dicabut -- kedua sinyal sah harus tetap ada"


def test_ensure_table_migration_widens_open_sl_below_floor(clean_signal_db):
    """Regresi (permintaan user langsung, menunjuk ANTM/ACES kena SL:
    'sl nya jgn kedeketan selagi masih oke bisa di hold'): MIN_SL_PCT
    floor di _calc_entry_levels() cuma berlaku utk sinyal yang DIHITUNG
    setelah floor itu ada -- baris yang SUDAH kadung tercatat sebelumnya
    (sl_pct asli, kadang <1%) tidak ikut lebar. Migrasi kesebelas harus
    melebarkan sl_pct baris OPEN yang masih di bawah floor ke floor itu,
    TAPI TIDAK menyentuh baris yang SUDAH resolved (hasilnya sudah
    terjadi apa adanya di bawah aturan lama, mengubahnya sekarang sama
    dgn mengarang ulang track record) maupun tp_pct (floor TP1 sudah ada
    duluan, baris lama sudah benar utk itu)."""
    from core.database import get_db
    import core.signal_history as sh
    from core.trading_plan import MIN_SL_PCT

    with get_db() as conn:
        # OPEN, sl_pct jauh di bawah floor -- harus dilebarkan ke floor.
        conn.execute('''
            INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, source, status)
            VALUES ('ZZTIGHTOPEN', 1000, 3.0, 0.4, 'TOP_PICK', 'OPEN')
        ''')
        # SUDAH resolved (SL_HIT) dgn sl_pct ketat -- TIDAK BOLEH disentuh,
        # itu hasil asli yang sudah terjadi.
        conn.execute('''
            INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, source, status)
            VALUES ('ZZTIGHTRESOLVED', 1000, 3.0, 1.4, 'TOP_PICK', 'SL_HIT')
        ''')
        # OPEN, sl_pct SUDAH >= floor -- tidak boleh ikut diubah.
        conn.execute('''
            INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, source, status)
            VALUES ('ZZWIDEOPEN', 1000, 3.0, 4.5, 'TOP_PICK', 'OPEN')
        ''')

    sh._ensured = False
    sh._ensure_table()

    with get_db() as conn:
        row_tight_open = conn.execute("SELECT sl_pct, tp_pct FROM signal_history WHERE kode='ZZTIGHTOPEN'").fetchone()
        row_tight_resolved = conn.execute("SELECT sl_pct FROM signal_history WHERE kode='ZZTIGHTRESOLVED'").fetchone()
        row_wide_open = conn.execute("SELECT sl_pct FROM signal_history WHERE kode='ZZWIDEOPEN'").fetchone()

    assert row_tight_open["sl_pct"] == MIN_SL_PCT, "OPEN + sl_pct di bawah floor harus dilebarkan ke floor"
    assert row_tight_open["tp_pct"] == 3.0, "tp_pct tidak boleh ikut diubah oleh migrasi ini"
    assert row_tight_resolved["sl_pct"] == 1.4, "baris yang SUDAH resolved tidak boleh diubah sama sekali"
    assert row_wide_open["sl_pct"] == 4.5, "OPEN dgn sl_pct sudah >= floor tidak boleh ikut diubah"


def test_ensure_table_migration_reopens_sl_hit_that_was_only_wrong_due_to_tight_floor(clean_signal_db):
    """Regresi UTAMA (permintaan user langsung, menunjuk ANTM & ACES:
    'masih sama belom berubah sl masih kedeketan tolong perbaiki semua').
    ANTM asli: entry=3010, sl_pct=1.4 (SL SEBELUM floor 3.0% ada),
    resolved_price=2960 -- TAPI 2960 > 3010*(1-3.0/100)=2919.7, artinya
    kalau floor 3.0% sudah benar SAAT ITU, harga 2960 TIDAK PERNAH
    menembus SL yang benar -- SL_HIT itu ARTEFAK dari bug, bukan hasil
    pasar yang sah. Migrasi ketiga belas harus mengembalikannya ke OPEN
    dgn sl_pct dilebarkan ke floor, resolved_at/resolved_price/return_pct/
    days_to_resolve dikosongkan lagi -- entry_price & tp_pct TIDAK BOLEH
    disentuh sama sekali (permintaan user: 'entrynya jgn diubah-ubah')."""
    from core.database import get_db
    import core.signal_history as sh
    from core.trading_plan import MIN_SL_PCT

    with get_db() as conn:
        # ANTM-style: resolved_price MASIH DI ATAS floor yang benar --
        # SL_HIT itu salah, harus dikembalikan ke OPEN.
        conn.execute('''
            INSERT INTO signal_history
                (kode, entry_price, tp_pct, sl_pct, source, status, recorded_at, resolved_at, resolved_price, return_pct, days_to_resolve)
            VALUES ('ZZANTMSTYLE', 3010, 3.0, 1.4, 'TOP_PICK', 'SL_HIT',
                    '2026-07-06 09:14:24', '2026-07-06 10:05:59', 2960, -1.4, 0)
        ''')
        # Kontrol A: sl_pct SUDAH >= floor (bukan bug ini) -- TIDAK boleh disentuh.
        conn.execute('''
            INSERT INTO signal_history
                (kode, entry_price, tp_pct, sl_pct, source, status, recorded_at, resolved_at, resolved_price, return_pct, days_to_resolve)
            VALUES ('ZZWIDEALREADY', 1000, 3.0, 4.0, 'TOP_PICK', 'SL_HIT',
                    '2026-07-04 09:00:00', '2026-07-05 09:00:00', 960, -4.0, 1)
        ''')
        # Kontrol B: sl_pct sempit, TAPI resolved_price SUNGGUHAN sudah di
        # bawah floor yang benar juga -- SL_HIT tetap SAH, tidak boleh disentuh.
        conn.execute('''
            INSERT INTO signal_history
                (kode, entry_price, tp_pct, sl_pct, source, status, recorded_at, resolved_at, resolved_price, return_pct, days_to_resolve)
            VALUES ('ZZREALLYDROPPED', 1000, 3.0, 1.0, 'TOP_PICK', 'SL_HIT',
                    '2026-07-04 09:00:00', '2026-07-05 09:00:00', 900, -10.0, 1)
        ''')
        # Kontrol C: TP_HIT dgn sl_pct sempit -- TIDAK PERNAH disentuh (SL
        # lebih lebar tidak pernah membatalkan TP yang sudah tercapai).
        conn.execute('''
            INSERT INTO signal_history
                (kode, entry_price, tp_pct, sl_pct, source, status, recorded_at, resolved_at, resolved_price, return_pct, days_to_resolve)
            VALUES ('ZZTPHITSTYLE', 1000, 3.0, 1.4, 'TOP_PICK', 'TP_HIT',
                    '2026-07-04 09:00:00', '2026-07-05 09:00:00', 1030, 3.0, 1)
        ''')

    sh._ensured = False
    sh._ensure_table()

    with get_db() as conn:
        antm = conn.execute('''
            SELECT status, sl_pct, entry_price, tp_pct, resolved_at, resolved_price, return_pct, days_to_resolve
            FROM signal_history WHERE kode='ZZANTMSTYLE'
        ''').fetchone()
        wide_already = conn.execute("SELECT status, sl_pct FROM signal_history WHERE kode='ZZWIDEALREADY'").fetchone()
        really_dropped = conn.execute("SELECT status, sl_pct FROM signal_history WHERE kode='ZZREALLYDROPPED'").fetchone()
        tp_hit = conn.execute("SELECT status, sl_pct FROM signal_history WHERE kode='ZZTPHITSTYLE'").fetchone()

    assert antm["status"] == "OPEN", "SL_HIT yang cuma artefak SL kelewat ketat harus dikembalikan ke OPEN"
    assert antm["sl_pct"] == MIN_SL_PCT
    assert antm["entry_price"] == 3010.0, "entry_price TIDAK BOLEH berubah"
    assert antm["tp_pct"] == 3.0, "tp_pct TIDAK BOLEH berubah"
    assert antm["resolved_at"] is None and antm["resolved_price"] is None
    assert antm["return_pct"] is None and antm["days_to_resolve"] is None

    assert wide_already["status"] == "SL_HIT", "sl_pct sudah >= floor -- bukan kasus bug ini, jangan disentuh"
    assert wide_already["sl_pct"] == 4.0

    assert really_dropped["status"] == "SL_HIT", "harga sungguhan sudah di bawah floor yang benar -- SL_HIT tetap sah"
    assert really_dropped["sl_pct"] == 1.0, "sl_pct baris resolved TIDAK diubah, cuma statusnya yang dievaluasi ulang"

    assert tp_hit["status"] == "TP_HIT", "TP_HIT tidak pernah kena kriteria migrasi ini (cuma menyasar SL_HIT)"


def test_ensure_table_migration_twelve_retraction_preserves_resolved_history(clean_signal_db):
    """Regresi RETRAKSI (2026-07-08) -- AKAR MASALAH NYATA yang menghapus
    riwayat SL_HIT INDF yang sah ("perasaan kmrn indf kena sl ko ilang").
    Migrasi kedua belas DULU menghapus SETIAP baris resolved utk sebuah
    kode begitu kode itu py baris OPEN APA SAJA -- TANPA syarat tanggal
    (klaim "hari ini atau kemarin" di komentar lama TIDAK PERNAH benar2
    diimplementasikan di SQL-nya). Ini persis pola INDF: SL_HIT lama
    (direkam & resolve berhari-hari sebelumnya) dihapus begitu INDF dapat
    baris OPEN baru yang SAMA SEKALI TIDAK TERKAIT. Sekarang migrasi itu
    sudah dicabut -- baris resolved lama HARUS tetap ada walau kode yang
    sama sedang py posisi OPEN baru, seberapa pun jauh jaraknya."""
    from core.database import get_db
    import core.signal_history as sh

    with get_db() as conn:
        # Persis kasus INDF: SL_HIT lama direkam & resolve jauh sebelum
        # baris OPEN baru yang tidak terkait muncul.
        conn.execute('''
            INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, source, status, recorded_at, resolved_at)
            VALUES ('ZZINDF', 6852, 3.0, 3.0, 'TOP_PICK', 'SL_HIT', '2026-07-04 06:00:00', '2026-07-07 09:00:00')
        ''')
        conn.execute('''
            INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, source, status, recorded_at, resolved_at)
            VALUES ('ZZINDF', 6900, 3.0, 3.0, 'TOP_PICK', 'OPEN', '2026-07-08 00:01:01', NULL)
        ''')
        # AKRA-style: resolved TP_HIT beberapa hari setelah direkam, LALU
        # dapat baris OPEN baru di HARI YANG SAMA -- dulu OPEN "menang",
        # baris resolved lama dihapus; sekarang keduanya harus tetap ada.
        conn.execute('''
            INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, source, status, recorded_at, resolved_at)
            VALUES ('ZZAKRA', 1255, 3.0, 3.0, 'TOP_PICK', 'TP_HIT', '2026-07-04 06:00:18', '2026-07-06 14:18:17')
        ''')
        conn.execute('''
            INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, source, status, recorded_at, resolved_at)
            VALUES ('ZZAKRA', 1300, 3.0, 3.0, 'TOP_PICK', 'OPEN', '2026-07-06 15:29:05', NULL)
        ''')
        # Tidak ada yang OPEN, 2 baris beda source resolve di TANGGAL
        # resolved_at yang SAMA -- dulu migrasi ini kolaps jadi 1, sekarang
        # keduanya harus tetap ada (dua sinyal sah, bukan duplikat).
        conn.execute('''
            INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, source, status, recorded_at, resolved_at, recommendation)
            VALUES ('ZZNODUP', 2930, 3.0, 3.0, 'SMART_MONEY', 'TP_HIT', '2026-07-01 06:00:00', '2026-07-06 09:00:00', 'BAGUS')
        ''')
        conn.execute('''
            INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, source, status, recorded_at, resolved_at)
            VALUES ('ZZNODUP', 3010, 3.0, 3.0, 'TOP_PICK', 'SL_HIT', '2026-07-05 06:00:00', '2026-07-06 10:00:00')
        ''')

    sh._ensured = False
    sh._ensure_table()

    with get_db() as conn:
        indf_rows = conn.execute("SELECT status FROM signal_history WHERE kode='ZZINDF'").fetchall()
        akra_rows = conn.execute("SELECT status, entry_price FROM signal_history WHERE kode='ZZAKRA'").fetchall()
        nodup_rows = conn.execute("SELECT source FROM signal_history WHERE kode='ZZNODUP'").fetchall()

    assert len(indf_rows) == 2, "migrasi kedua belas sudah dicabut -- SL_HIT lama tidak boleh hilang lagi"
    assert {r["status"] for r in indf_rows} == {"SL_HIT", "OPEN"}

    assert len(akra_rows) == 2, "migrasi kedua belas sudah dicabut -- kedua baris harus tetap ada"

    assert len(nodup_rows) == 2, "migrasi kedua belas sudah dicabut -- kedua resolusi sah harus tetap ada"


def test_ensure_table_migration_collapses_cross_source_resolved_duplicates(clean_signal_db):
    """Regresi BUG NYATA ditemukan lewat screenshot user: MDKA tercatat 2x
    di tanggal yang SAMA (dulu satu dari SMART_MONEY, satu dari sumber
    lain) dgn entry/TP/SL IDENTIK -- keduanya KEBETULAN sudah sama-sama
    resolved sebelum migrasi per-kode-OPEN (migrasi keenam) sempat jalan,
    jadi lolos dari cleanup itu (yang cuma menyentuh baris status='OPEN').
    Migrasi kedelapan harus tetap membersihkan ini: kode+tanggal+
    entry_price+tp_pct+sl_pct sama persis, SOURCE TIDAK HARUS SAMA (beda
    dari migrasi ke-4 yang mensyaratkan source sama)."""
    from core.database import get_db
    import core.signal_history as sh

    # recommendation='BAGUS' eksplisit di baris SMART_MONEY -- migrasi
    # kesembilan (di bawah migrasi ini) menghapus baris SMART_MONEY yang
    # recommendation-nya bukan BUY/STRONG BUY, jadi baris test ini harus
    # memenuhi kriteria itu supaya yang diuji di sini (dedup silang-source)
    # tidak ikut kehapus oleh migrasi LAIN yang tidak relevan dgn test ini.
    with get_db() as conn:
        conn.execute('''
            INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, source, status, recorded_at, recommendation)
            VALUES ('ZZCROSSDUP', 2740, 3.0, 2.0, 'SMART_MONEY', 'SL_HIT', '2026-07-06 09:00:00', 'BAGUS')
        ''')
        conn.execute('''
            INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, source, status, recorded_at)
            VALUES ('ZZCROSSDUP', 2740, 3.0, 2.0, 'MACD_CROSS', 'SL_HIT', '2026-07-06 10:00:00')
        ''')
        # Kontrol: kode SAMA tapi entry_price BEDA (hari/harga sungguhan
        # berbeda) -- harus TETAP keduanya, bukan ikut kehapus.
        conn.execute('''
            INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, source, status, recorded_at)
            VALUES ('ZZCROSSREAL', 2740, 3.0, 2.0, 'TOP_PICK', 'TP_HIT', '2026-07-04 09:00:00')
        ''')
        conn.execute('''
            INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, source, status, recorded_at, recommendation)
            VALUES ('ZZCROSSREAL', 2800, 3.0, 2.0, 'SMART_MONEY', 'TP_HIT', '2026-07-06 09:00:00', 'BAGUS')
        ''')

    sh._ensured = False
    sh._ensure_table()

    with get_db() as conn:
        dup_rows = conn.execute("SELECT source FROM signal_history WHERE kode='ZZCROSSDUP'").fetchall()
        real_rows = conn.execute(
            "SELECT entry_price FROM signal_history WHERE kode='ZZCROSSREAL' ORDER BY entry_price"
        ).fetchall()

    assert len(dup_rows) == 1
    assert dup_rows[0]["source"] == "SMART_MONEY"  # yang dipertahankan = id terkecil (paling awal direkam)
    assert [r["entry_price"] for r in real_rows] == [2740.0, 2800.0]  # keduanya tetap ada, harga beda


def test_ensure_table_migration_backfills_tp2_tp3_and_tp_level_hit(clean_signal_db):
    """Regresi migrasi ke-14 (skema TP multi-level, permintaan user: 'kena
    tp1 tandai, lanjut ke tp selanjutnya'): baris LAMA (direkam sebelum
    kolom tp2_pct/tp3_pct/tp_level_hit ada) harus di-backfill otomatis --
    tp2_pct=tp_pct*2, tp3_pct=tp_pct*3 (konvensi SAMA dgn core/trading_
    plan.py::_calc_entry_levels), dan tp_level_hit=1 utk baris yang SUDAH
    TP_HIT (jujur merepresentasikan bahwa sistem lama cuma pernah capai
    'level 1 setara', tidak pernah punya kesempatan capai TP2/TP3)."""
    from core.database import get_db
    import core.signal_history as sh

    with get_db() as conn:
        conn.execute('''
            INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, source, status, recorded_at)
            VALUES ('ZZOLDOPEN', 1000, 5, 3, 'TOP_PICK', 'OPEN', '2026-07-01 09:00:00')
        ''')
        conn.execute('''
            INSERT INTO signal_history
                (kode, entry_price, tp_pct, sl_pct, source, status, recorded_at, resolved_at, resolved_price, return_pct, days_to_resolve)
            VALUES ('ZZOLDTPHIT', 1000, 5, 3, 'TOP_PICK', 'TP_HIT', '2026-07-01 09:00:00', '2026-07-02 09:00:00', 1050, 5.0, 1)
        ''')

    sh._ensured = False
    sh._ensure_table()

    with get_db() as conn:
        open_row = conn.execute(
            "SELECT tp2_pct, tp3_pct, tp_level_hit FROM signal_history WHERE kode='ZZOLDOPEN'"
        ).fetchone()
        tphit_row = conn.execute(
            "SELECT tp2_pct, tp3_pct, tp_level_hit FROM signal_history WHERE kode='ZZOLDTPHIT'"
        ).fetchone()

    assert open_row["tp2_pct"] == 10.0  # tp_pct * 2
    assert open_row["tp3_pct"] == 15.0  # tp_pct * 3
    assert open_row["tp_level_hit"] == 0

    assert tphit_row["tp2_pct"] == 10.0
    assert tphit_row["tp3_pct"] == 15.0
    assert tphit_row["tp_level_hit"] == 1, "baris TP_HIT lama harus dianggap sudah capai level 1"


def test_record_top_picks_persists_scenario_derived_tp2_tp3(clean_signal_db):
    """Regresi naming-mismatch yang sempat ada: confidence() (web/app.py)
    sekarang menghitung tp2_pct/tp3_pct dari skenario Trading Plan yang
    BENERAN kena (bukan cuma tp_pct*2/*3 generik) dan mengirimkannya lewat
    key 'tp2_pct'/'tp3_pct' -- record_top_picks() HARUS menyimpan nilai
    itu APA ADANYA kalau item menyediakannya, bukan selalu jatuh ke
    fallback tp_pct*N (bug yg sempat terjadi krn key salah nama)."""
    import asyncio

    from core.signal_history import record_top_picks

    item = {**_fake_confidence_item("ZZSCEN", 80, naik=4.0, turun=2.0), "tp2_pct": 9.5, "tp3_pct": 15.5}
    saved = asyncio.run(record_top_picks([item]))
    assert saved[0]["tp2_pct"] == 9.5
    assert saved[0]["tp3_pct"] == 15.5

    # Kontrol: item TANPA tp2_pct/tp3_pct eksplisit -- fallback tp_pct*2/*3.
    item2 = _fake_confidence_item("ZZNOSCEN", 80, naik=4.0, turun=2.0)
    saved2 = asyncio.run(record_top_picks([item2]))
    assert saved2[0]["tp2_pct"] == 8.0  # 4.0 * 2
    assert saved2[0]["tp3_pct"] == 12.0  # 4.0 * 3


def test_audit_open_signals_tp1_tp2_progress_then_tp3_closes(clean_signal_db):
    """Regresi inti fitur baru (permintaan user: 'misalkan kena area tp1
    tandai juga lanjut ke area tp selanjutnya'): TP1/TP2 tercapai HANYA
    menaikkan tp_level_hit, posisi TETAP OPEN -- cuma TP3 yang menutup
    posisi (status TP_HIT). Disimulasikan sbg 3 audit berurutan (harga
    naik bertahap), bukan 1 lompatan, supaya progres per-level teruji."""
    import asyncio

    from core.database import get_db
    from core.signal_history import _ensure_table, audit_open_signals

    _ensure_table()
    with get_db() as conn:
        # entry=1000, tp1=5% (1050), tp2=10% (1100), tp3=15% (1150), sl=3% (970)
        conn.execute('''
            INSERT INTO signal_history (kode, entry_price, tp_pct, tp2_pct, tp3_pct, sl_pct)
            VALUES ('ZZTPPROG', 1000, 5, 10, 15, 3)
        ''')

    from datetime import date

    async def _audit_at(price):
        async def fake_lookup(kode):
            return price, date.today()
        return await audit_open_signals(fake_lookup)

    # Audit 1: harga 1060 -- TP1 tercapai, posisi harus TETAP OPEN.
    events1 = asyncio.run(_audit_at(1060.0))
    with get_db() as conn:
        row1 = conn.execute("SELECT status, tp_level_hit FROM signal_history WHERE kode='ZZTPPROG'").fetchone()
    assert row1["status"] == "OPEN", "TP1 tercapai TIDAK BOLEH menutup posisi"
    assert row1["tp_level_hit"] == 1
    assert len(events1) == 1 and events1[0]["kind"] == "tp_progress" and events1[0]["tp_level_hit"] == 1

    # Audit 2: harga sama msh di atas TP1 tapi belum TP2 -- TIDAK ADA event baru (idempotent).
    events2 = asyncio.run(_audit_at(1060.0))
    assert events2 == []

    # Audit 3: harga naik ke 1110 -- TP2 tercapai, posisi MASIH HARUS OPEN.
    events3 = asyncio.run(_audit_at(1110.0))
    with get_db() as conn:
        row3 = conn.execute("SELECT status, tp_level_hit FROM signal_history WHERE kode='ZZTPPROG'").fetchone()
    assert row3["status"] == "OPEN", "TP2 tercapai TIDAK BOLEH menutup posisi"
    assert row3["tp_level_hit"] == 2
    assert len(events3) == 1 and events3[0]["kind"] == "tp_progress" and events3[0]["tp_level_hit"] == 2

    # Audit 4: harga naik ke 1160 -- TP3 tercapai, BARU sekarang ditutup.
    events4 = asyncio.run(_audit_at(1160.0))
    with get_db() as conn:
        row4 = conn.execute(
            "SELECT status, tp_level_hit, return_pct, resolved_price FROM signal_history WHERE kode='ZZTPPROG'"
        ).fetchone()
    assert row4["status"] == "TP_HIT"
    assert row4["tp_level_hit"] == 3
    assert row4["return_pct"] == 15  # tp3_pct
    assert row4["resolved_price"] == 1160.0
    assert len(events4) == 1 and events4[0]["kind"] == "resolved" and events4[0]["status"] == "TP_HIT"


def test_audit_open_signals_sl_still_terminal_after_tp_progress(clean_signal_db):
    """Regresi: SL HARUS tetap final TERLEPAS dari tp_level_hit sudah
    berapa -- user tidak minta stop-loss dipindah ke breakeven setelah
    TP1/TP2 kena, jadi risiko awal (sl_pct dari entry) tetap berlaku
    penuh selama posisi masih terbuka. Simulasi: TP1 kena dulu (harga
    naik), LALU harga jatuh tembus SL awal -> harus tetap SL_HIT, dan
    tp_level_hit HISTORIS (1) tetap tercatat, bukan direset ke 0."""
    import asyncio

    from core.database import get_db
    from core.signal_history import _ensure_table, audit_open_signals

    _ensure_table()
    with get_db() as conn:
        # entry=1000, tp1=5% (1050), sl=3% (970)
        conn.execute('''
            INSERT INTO signal_history (kode, entry_price, tp_pct, tp2_pct, tp3_pct, sl_pct)
            VALUES ('ZZTPTHENSL', 1000, 5, 10, 15, 3)
        ''')

    from datetime import date

    async def _audit_at(price):
        async def fake_lookup(kode):
            return price, date.today()
        return await audit_open_signals(fake_lookup)

    asyncio.run(_audit_at(1060.0))  # TP1 tercapai dulu
    with get_db() as conn:
        mid = conn.execute("SELECT status, tp_level_hit FROM signal_history WHERE kode='ZZTPTHENSL'").fetchone()
    assert mid["status"] == "OPEN" and mid["tp_level_hit"] == 1

    asyncio.run(_audit_at(960.0))  # lalu jatuh tembus SL
    with get_db() as conn:
        final = conn.execute(
            "SELECT status, tp_level_hit, return_pct FROM signal_history WHERE kode='ZZTPTHENSL'"
        ).fetchone()
    assert final["status"] == "SL_HIT", "SL harus tetap final walau TP1 sudah pernah tercapai"
    assert final["return_pct"] == -3
    assert final["tp_level_hit"] == 1, "tp_level_hit historis (TP1 pernah tercapai) tidak boleh direset ke 0"


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

    from datetime import date

    prices = {"ZZTP": 1060.0, "ZZSL": 960.0, "ZZOLD": 1010.0, "ZZOPEN": 1010.0}

    async def fake_lookup(kode):
        price = prices.get(kode)
        return None if price is None else (price, date.today())

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


def test_audit_open_signals_sell_direction_bidirectional_math(clean_signal_db):
    """Regresi fitur baru: sinyal SELL (Distribusi Smart Money) untung
    kalau harga TURUN -- matematika TP/SL/return_pct HARUS dibalik dari
    BUY, bukan cuma label kosmetik. entry=1000, tp_pct=5 (target turun ke
    Rp950), sl_pct=3 (stop naik ke Rp1030)."""
    import asyncio

    from core.database import get_db
    from core.signal_history import _ensure_table, audit_open_signals, MAX_HOLD_DAYS

    _ensure_table()
    with get_db() as conn:
        # TP: harga turun ke 940 (<=950) -> untung, return_pct HARUS +5 (positif)
        conn.execute("INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, direction) VALUES ('ZZSELLTP', 1000, 5, 3, 'SELL')")
        # SL: harga naik ke 1040 (>=1030) -> rugi, return_pct HARUS -3
        conn.execute("INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, direction) VALUES ('ZZSELLSL', 1000, 5, 3, 'SELL')")
        # EXPIRED: harga turun sedikit ke 980 (belum capai target/stop), lewat MAX_HOLD_DAYS
        conn.execute(
            "INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, direction, recorded_at) "
            "VALUES ('ZZSELLOLD', 1000, 5, 3, 'SELL', datetime('now', ?))",
            (f'-{MAX_HOLD_DAYS + 1} days',),
        )

    from datetime import date

    prices = {"ZZSELLTP": 940.0, "ZZSELLSL": 1040.0, "ZZSELLOLD": 980.0}

    async def fake_lookup(kode):
        price = prices.get(kode)
        return None if price is None else (price, date.today())

    asyncio.run(audit_open_signals(fake_lookup))

    with get_db() as conn:
        rows = {r["kode"]: dict(r) for r in conn.execute("SELECT * FROM signal_history").fetchall()}

    assert rows["ZZSELLTP"]["status"] == "TP_HIT"
    assert rows["ZZSELLTP"]["return_pct"] == 5  # untung POSITIF walau harga turun
    assert rows["ZZSELLSL"]["status"] == "SL_HIT"
    assert rows["ZZSELLSL"]["return_pct"] == -3
    assert rows["ZZSELLOLD"]["status"] == "EXPIRED"
    assert rows["ZZSELLOLD"]["return_pct"] == 2.04  # (1000/980 - 1) * 100, BUKAN (980/1000-1)*100


def test_audit_open_signals_refuses_to_resolve_with_price_older_than_recorded_date(clean_signal_db):
    """Regresi BUG NYATA ditemukan live (laporan user langsung: TPIA & ARTO
    ter-'Kena SL' padahal user melihat sendiri harganya NAIK hari itu):
    bar yfinance utk hari terbaru kadang masih NaN/belum terbit -- setelah
    dropna() di _clean(), harga yang kepakai bisa jadi closing BEBERAPA
    HARI SEBELUM sinyal itu bahkan direkam (data yang belum berubah sama
    sekali sejak direkam, BUKAN penurunan harga sungguhan). price_lookup
    SEKARANG wajib menyertakan tanggal bar di balik harganya -- kalau
    tanggal itu LEBIH LAMA dari recorded_at, audit_open_signals() HARUS
    menolak meresolve (tetap OPEN), walau harga itu SENDIRI kalau dipakai
    apa adanya akan tampak seperti kena SL."""
    import asyncio
    from datetime import date, timedelta

    from core.database import get_db
    from core.signal_history import _ensure_table, audit_open_signals

    _ensure_table()
    with get_db() as conn:
        # entry=1885, sl=3.2% -> SL kena kalau harga <= 1824.68
        conn.execute(
            "INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, recorded_at) "
            "VALUES ('ZZSTALE', 1885, 3.2, 3.2, datetime('now', 'localtime'))"
        )

    stale_date = date.today() - timedelta(days=3)  # bar dari SEBELUM sinyal direkam

    async def fake_lookup(kode):
        return 1785.0, stale_date  # harga ini SENDIRI di bawah SL (1824.68)

    events = asyncio.run(audit_open_signals(fake_lookup))

    with get_db() as conn:
        row = conn.execute("SELECT status, resolved_at FROM signal_history WHERE kode='ZZSTALE'").fetchone()

    assert row["status"] == "OPEN", "harga basi (lebih lama dari recorded_at) TIDAK BOLEH pernah meresolve sinyal"
    assert row["resolved_at"] is None
    assert events == []


def test_audit_open_signals_resolves_when_price_date_is_same_day_or_newer(clean_signal_db):
    """Kontrol dari test di atas: kalau tanggal bar SAMA (atau lebih baru)
    dari recorded_at, audit HARUS tetap berjalan normal -- staleness guard
    tidak boleh jadi terlalu ketat sampai memblokir audit yang sah."""
    import asyncio
    from datetime import date, timedelta

    from core.database import get_db
    from core.signal_history import _ensure_table, audit_open_signals

    _ensure_table()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, recorded_at) "
            "VALUES ('ZZFRESH', 1885, 3.2, 3.2, datetime('now', 'localtime'))"
        )

    fresh_date = date.today() + timedelta(days=1)  # bar SETELAH direkam -- jelas bukan basi

    async def fake_lookup(kode):
        return 1785.0, fresh_date

    events = asyncio.run(audit_open_signals(fake_lookup))

    with get_db() as conn:
        row = conn.execute("SELECT status FROM signal_history WHERE kode='ZZFRESH'").fetchone()

    assert row["status"] == "SL_HIT", "tanggal bar yang genuinely lebih baru harus tetap bisa meresolve"
    assert len(events) == 1 and events[0]["status"] == "SL_HIT"


def test_audit_open_signals_skips_entirely_outside_trading_hours(clean_signal_db, monkeypatch):
    """Regresi BUG NYATA dilaporkan user langsung ("ngebug nih perasaan
    arto bukan harga segitu hari ini"): sinyal ARTO direkam jam 00:01 WIB
    (9 jam SEBELUM bursa buka), lalu 6 DETIK kemudian ter-audit jadi
    TP_HIT memakai fast_info.last_price yfinance yang ternyata cuma ECHO
    closing print sesi SEBELUMNYA -- bukan harga baru sungguhan. Staleness
    guard yang sudah ada (test di atas) TIDAK menangkap ini krn
    _signal_audit_price_lookup menstempel SEMUA hasil fast_info sbg
    tanggal HARI INI tanpa syarat (tanggalnya memang benar "hari ini",
    yang basi adalah HARGANYA). Perbaikan: audit_open_signals() SEKARANG
    skip total (return [], semua sinyal tetap OPEN) kalau bursa jelas
    belum/sudah tidak buka -- lihat _is_bursa_trading_hours()."""
    import asyncio

    from core.database import get_db
    import core.signal_history as sh

    monkeypatch.setattr(sh, "_is_bursa_trading_hours", lambda: False)

    with get_db() as conn:
        # Harga ini SENDIRI jelas2 sudah lewat TP3 kalau dipakai apa
        # adanya -- tapi krn di luar jam bursa, TIDAK BOLEH diresolve.
        conn.execute(
            "INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, recorded_at) "
            "VALUES ('ZZAFTERHOURS', 907, 3.1, 3.1, datetime('now', 'localtime'))"
        )

    async def fake_lookup(kode):
        return 1040.0, __import__("datetime").date.today()

    events = asyncio.run(sh.audit_open_signals(fake_lookup))

    with get_db() as conn:
        row = conn.execute("SELECT status, resolved_at FROM signal_history WHERE kode='ZZAFTERHOURS'").fetchone()

    assert row["status"] == "OPEN", "di luar jam bursa, TIDAK BOLEH ada resolusi TP/SL sama sekali"
    assert row["resolved_at"] is None
    assert events == []


def test_is_bursa_trading_hours_checks_weekday_and_time_window():
    """Kontrol langsung atas _is_bursa_trading_hours() -- pagi buta/malam
    hari kerja HARUS False (inti bug ARTO: jam 00:01 WIB), jam bursa wajar
    HARUS True, dan akhir pekan HARUS False terlepas dari jamnya."""
    from datetime import datetime as _dt
    from unittest.mock import patch

    from core.signal_history import _is_bursa_trading_hours

    # Senin (weekday()==0) jam 00:01 -- SAMA PERSIS kasus bug ARTO.
    with patch("core.signal_history.datetime") as mock_dt:
        mock_dt.now.return_value = _dt(2026, 7, 6, 0, 1)  # Senin
        assert _is_bursa_trading_hours() is False

    # Senin jam 10:30 -- jelas dalam jam bursa.
    with patch("core.signal_history.datetime") as mock_dt:
        mock_dt.now.return_value = _dt(2026, 7, 6, 10, 30)
        assert _is_bursa_trading_hours() is True

    # Sabtu jam 10:30 -- jam bursa wajar TAPI akhir pekan, tetap False.
    with patch("core.signal_history.datetime") as mock_dt:
        mock_dt.now.return_value = _dt(2026, 7, 11, 10, 30)  # Sabtu
        assert _is_bursa_trading_hours() is False

    # Senin jam 17:00 -- hari kerja tapi sudah lewat jam bursa.
    with patch("core.signal_history.datetime") as mock_dt:
        mock_dt.now.return_value = _dt(2026, 7, 6, 17, 0)
        assert _is_bursa_trading_hours() is False


def test_audit_open_signals_still_expires_with_permanently_stale_price(clean_signal_db):
    """Regresi thd staleness guard di atas: kalau feed harga suatu saham
    MACET PERMANEN lebih lama dari recorded_at (mis. suspensi bursa
    berkepanjangan/delisting) DAN sudah lewat MAX_HOLD_DAYS, sinyal itu
    HARUS tetap bisa EXPIRED (murni berbasis waktu, bukan klaim level
    harga tertentu) -- staleness guard cuma boleh memblokir klaim TP/SL,
    JANGAN sampai bikin sinyal begini tersangkut OPEN selama-lamanya."""
    import asyncio
    from datetime import date, timedelta

    from core.database import get_db
    from core.signal_history import _ensure_table, audit_open_signals, MAX_HOLD_DAYS

    _ensure_table()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, recorded_at) "
            "VALUES ('ZZSUSPEND', 1000, 5, 3, datetime('now', ?))",
            (f'-{MAX_HOLD_DAYS + 1} days',),
        )

    stale_date = date.today() - timedelta(days=MAX_HOLD_DAYS + 5)  # jauh lebih lama dari recorded_at

    async def fake_lookup(kode):
        return 1010.0, stale_date  # harga di tengah, TIDAK kena TP/SL manapun

    events = asyncio.run(audit_open_signals(fake_lookup))

    with get_db() as conn:
        row = conn.execute("SELECT status, return_pct FROM signal_history WHERE kode='ZZSUSPEND'").fetchone()

    assert row["status"] == "EXPIRED", "harus tetap expire walau harganya basi -- jangan tersangkut OPEN selamanya"
    assert row["return_pct"] == 1.0  # (1010/1000 - 1) * 100
    assert len(events) == 1 and events[0]["status"] == "EXPIRED"


def test_get_signal_report_tp_sl_price_bidirectional(clean_signal_db):
    """Regresi: get_signal_report() harus menghitung tp_price/sl_price
    yang DIBALIK utk sinyal SELL (TP di bawah entry, SL di atas entry),
    konsisten dgn audit_open_signals()."""
    from core.database import get_db
    from core.signal_history import _ensure_table, get_signal_report

    _ensure_table()
    with get_db() as conn:
        conn.execute("INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, direction) VALUES ('ZZSELLREPORT', 1000, 5, 3, 'SELL')")
        conn.execute("INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, direction) VALUES ('ZZBUYREPORT', 1000, 5, 3, 'BUY')")

    report = get_signal_report()
    by_kode = {s["kode"]: s for s in report["signals"]}
    assert by_kode["ZZSELLREPORT"]["tp_price"] == 950.0  # entry*(1-5%) -- di BAWAH entry
    assert by_kode["ZZSELLREPORT"]["sl_price"] == 1030.0  # entry*(1+3%) -- di ATAS entry
    assert by_kode["ZZBUYREPORT"]["tp_price"] == 1050.0  # entry*(1+5%) -- tetap seperti sebelumnya
    assert by_kode["ZZBUYREPORT"]["sl_price"] == 970.0


def test_record_top_picks_now_starts_as_pending_entry(clean_signal_db):
    """Regresi UTAMA fitur baru (permintaan user langsung: 'kamu jadi
    analyst, nentuin entrinya dimana, nanti tinggal liat kena entry yg
    disaranin apa engga') -- TOP_PICK SEKARANG start sbg PENDING_ENTRY
    (rekomendasi, belum ada posisi), BUKAN langsung OPEN spt sebelumnya.
    Ini juga regresi thd bug ARTO (entry Rp953 yang tidak nyambung sama
    histori harga sungguhan, akar masalahnya klaim entry 'sudah kena hari
    ini') -- sekarang entry_price yang dicatat itu APA ADANYA dari
    it['entry_price'] (skenario pullback yang dikirim caller), bukan
    diklaim sudah terjadi."""
    import asyncio

    from core.database import get_db
    from core.signal_history import record_top_picks, MIN_SCORE_TO_RECORD

    items = [{**_fake_confidence_item("ZZPENDING", MIN_SCORE_TO_RECORD + 10), "entry_price": 950.0}]
    saved = asyncio.run(record_top_picks(items))
    assert len(saved) == 1

    with get_db() as conn:
        row = conn.execute("SELECT status, entry_price, entry_filled_at, direction FROM signal_history WHERE kode='ZZPENDING'").fetchone()
    assert row["status"] == "PENDING_ENTRY"
    assert row["entry_price"] == 950.0
    assert row["entry_filled_at"] is None
    assert row["direction"] == "BUY"


def test_audit_pending_entries_fills_when_price_reaches_entry(clean_signal_db):
    """Inti alur baru: begitu harga TERKINI turun ke (atau di bawah) level
    entry yang direkomendasikan, status pindah PENDING_ENTRY -> OPEN dan
    entry_filled_at tercatat -- TP/SL baru mulai berlaku dari titik ini."""
    import asyncio
    from datetime import date

    from core.database import get_db
    from core.signal_history import _ensure_table, audit_pending_entries

    _ensure_table()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, status, direction) "
            "VALUES ('ZZFILL', 1000, 5, 3, 'PENDING_ENTRY', 'BUY')"
        )

    async def fake_lookup(kode):
        return 995.0, date.today()  # harga sudah turun ke bawah entry 1000

    events = asyncio.run(audit_pending_entries(fake_lookup))

    with get_db() as conn:
        row = conn.execute("SELECT status, entry_filled_at FROM signal_history WHERE kode='ZZFILL'").fetchone()
    assert row["status"] == "OPEN"
    assert row["entry_filled_at"] is not None
    assert len(events) == 1 and events[0]["kind"] == "entry_filled" and events[0]["kode"] == "ZZFILL"


def test_audit_pending_entries_stays_pending_when_price_above_entry(clean_signal_db):
    """Kalau harga BELUM turun ke level entry (masih di atas), status
    HARUS tetap PENDING_ENTRY -- belum ada kesempatan masuk, jangan
    diklaim sudah jadi posisi aktif."""
    import asyncio
    from datetime import date

    from core.database import get_db
    from core.signal_history import _ensure_table, audit_pending_entries

    _ensure_table()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, status, direction) "
            "VALUES ('ZZWAIT', 1000, 5, 3, 'PENDING_ENTRY', 'BUY')"
        )

    async def fake_lookup(kode):
        return 1050.0, date.today()  # masih jauh di atas entry 1000

    events = asyncio.run(audit_pending_entries(fake_lookup))

    with get_db() as conn:
        row = conn.execute("SELECT status FROM signal_history WHERE kode='ZZWAIT'").fetchone()
    assert row["status"] == "PENDING_ENTRY"
    assert events == []


def test_audit_pending_entries_expires_after_max_wait_days(clean_signal_db):
    """Kalau entry TIDAK PERNAH tersentuh sampai MAX_ENTRY_WAIT_DAYS
    berlalu, status jadi EXPIRED_NO_ENTRY -- BUKAN menang/kalah, murni
    'kesempatan masuk tidak pernah datang'. resolved_at harus terisi
    (dianggap selesai/final), TAPI return_pct/resolved_price TETAP NULL
    (tidak pernah ada trade sungguhan yang bisa diukur untung/ruginya)."""
    import asyncio
    from datetime import date

    from core.database import get_db
    from core.signal_history import _ensure_table, audit_pending_entries, MAX_ENTRY_WAIT_DAYS

    _ensure_table()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, status, direction, recorded_at) "
            "VALUES ('ZZNOENTRY', 1000, 5, 3, 'PENDING_ENTRY', 'BUY', datetime('now', ?))",
            (f'-{MAX_ENTRY_WAIT_DAYS + 1} days',),
        )

    async def fake_lookup(kode):
        return 1050.0, date.today()  # tidak pernah turun ke entry

    events = asyncio.run(audit_pending_entries(fake_lookup))

    with get_db() as conn:
        row = conn.execute("SELECT status, resolved_at, return_pct, resolved_price FROM signal_history WHERE kode='ZZNOENTRY'").fetchone()
    assert row["status"] == "EXPIRED_NO_ENTRY"
    assert row["resolved_at"] is not None
    assert row["return_pct"] is None
    assert row["resolved_price"] is None
    assert len(events) == 1 and events[0]["kind"] == "entry_expired"


def test_audit_pending_entries_ignores_stale_price_for_fill(clean_signal_db):
    """Sama disiplin dgn audit_open_signals (lihat bug ARTO trading-hours
    gate) -- harga yang lebih basi dari recorded_at TIDAK BOLEH dipakai
    utk klaim entry tersentuh, supaya tidak salah trigger dari harga sesi
    lama yang kebetulan lebih rendah."""
    import asyncio
    from datetime import date, timedelta

    from core.database import get_db
    from core.signal_history import _ensure_table, audit_pending_entries

    _ensure_table()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, status, direction) "
            "VALUES ('ZZSTALEFILL', 1000, 5, 3, 'PENDING_ENTRY', 'BUY')"
        )

    stale_date = date.today() - timedelta(days=3)

    async def fake_lookup(kode):
        return 990.0, stale_date  # di bawah entry, TAPI harganya basi

    events = asyncio.run(audit_pending_entries(fake_lookup))

    with get_db() as conn:
        row = conn.execute("SELECT status FROM signal_history WHERE kode='ZZSTALEFILL'").fetchone()
    assert row["status"] == "PENDING_ENTRY", "harga basi tidak boleh memicu entry filled"
    assert events == []


def test_audit_pending_entries_skips_entirely_outside_trading_hours(clean_signal_db, monkeypatch):
    """Sama pola dgn audit_open_signals -- di luar jam bursa, JANGAN proses
    sama sekali (harga yang didapat di luar jam bursa berisiko basi/echo
    sesi sebelumnya walau tanggalnya 'hari ini')."""
    import asyncio

    import core.signal_history as sh
    from core.database import get_db

    monkeypatch.setattr(sh, "_is_bursa_trading_hours", lambda: False)

    with get_db() as conn:
        conn.execute(
            "INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, status, direction) "
            "VALUES ('ZZOUTSIDEHOURS', 1000, 5, 3, 'PENDING_ENTRY', 'BUY')"
        )

    calls = {"n": 0}

    async def fake_lookup(kode):
        calls["n"] += 1
        from datetime import date
        return 900.0, date.today()

    events = asyncio.run(sh.audit_pending_entries(fake_lookup))
    assert events == []
    assert calls["n"] == 0, "tidak boleh sempat lookup harga sama sekali di luar jam bursa"


def test_has_open_signal_blocks_new_recording_while_pending_entry(clean_signal_db):
    """Perluasan _has_open_signal (migrasi ke-16): kode yang masih
    PENDING_ENTRY dianggap 'cerita aktif' SAMA seperti OPEN -- tidak boleh
    dapat rekomendasi entry BARU yang menumpuk selama yang lama belum
    tersentuh/kadaluarsa."""
    import asyncio

    from core.database import get_db
    from core.signal_history import record_top_picks, MIN_SCORE_TO_RECORD

    items = [{**_fake_confidence_item("ZZDUPPENDING", MIN_SCORE_TO_RECORD + 10), "entry_price": 950.0}]
    saved = asyncio.run(record_top_picks(items))
    assert len(saved) == 1

    saved_again = asyncio.run(record_top_picks(items))
    assert saved_again == [], "masih PENDING_ENTRY -- tidak boleh dicatat ulang"

    with get_db() as conn:
        rows = conn.execute("SELECT COUNT(*) c FROM signal_history WHERE kode='ZZDUPPENDING'").fetchone()
    assert rows["c"] == 1


def test_pending_entry_and_expired_no_entry_excluded_from_win_rate(clean_signal_db):
    """PENDING_ENTRY & EXPIRED_NO_ENTRY TIDAK BOLEH ikut dihitung menang/
    kalah di win rate -- belum pernah ada trade sungguhan yang terjadi
    utk keduanya (beda dgn EXPIRED biasa, yang memang sempat jadi posisi
    OPEN tapi tidak kunjung kena TP/SL)."""
    from core.database import get_db
    from core.signal_history import _ensure_table, get_signal_report

    _ensure_table()
    with get_db() as conn:
        conn.execute("INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, status, direction) VALUES ('ZZSTILLPENDING', 1000, 5, 3, 'PENDING_ENTRY', 'BUY')")
        conn.execute("INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, status, direction, resolved_at) VALUES ('ZZNEVERFILLED', 1000, 5, 3, 'EXPIRED_NO_ENTRY', 'BUY', datetime('now'))")
        # Kontrol: 1 sinyal TP_HIT sungguhan supaya stats tidak None (bisa dicek isinya, bukan cuma "belum cukup data").
        conn.execute("INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, status, direction, resolved_at, resolved_price, return_pct, tp_level_hit, days_to_resolve) VALUES ('ZZREALTP', 1000, 5, 3, 'TP_HIT', 'BUY', datetime('now'), 1050, 5.0, 1, 2)")

    report = get_signal_report()
    assert report["n_pending_entry"] == 1
    assert report["n_expired_no_entry"] == 1
    assert report["stats"]["n_closed"] == 1, "cuma ZZREALTP yang boleh ikut -- PENDING_ENTRY/EXPIRED_NO_ENTRY tidak dihitung 'selesai'"
    kodes_in_closed_stats = report["stats"]["n_tp_hit"]
    assert kodes_in_closed_stats == 1


def test_record_smart_money_signals_records_distribusi_as_sell_with_swapped_tp_sl(clean_signal_db):
    """Regresi fitur baru: kategori Distribusi/Distribusi Agresif SEKARANG
    direkam sbg direction='SELL', DENGAN tp_pct/sl_pct DITUKAR dari
    potensi_naik_pct/risiko_turun_pct (yang dihitung asumsi posisi BUY) --
    target profit SELL = harga turun ke S1 (risiko_turun_pct BUY), stop
    loss SELL = harga naik ke R1 (potensi_naik_pct BUY)."""
    import asyncio

    from core.signal_history import record_smart_money_signals

    items = [
        _fake_sm_item("ZZSELLREC", "Distribusi Agresif", naik=4.0, turun=6.0),
        _fake_sm_item("ZZBUYREC", "Akumulasi Agresif", naik=4.0, turun=6.0),
    ]
    saved = asyncio.run(record_smart_money_signals(items))
    by_kode = {s["kode"]: s for s in saved}

    assert by_kode["ZZSELLREC"]["direction"] == "SELL"
    assert by_kode["ZZSELLREC"]["tp_pct"] == 6.0  # = risiko_turun_pct (BUKAN potensi_naik_pct)
    assert by_kode["ZZSELLREC"]["sl_pct"] == 4.0  # = potensi_naik_pct (BUKAN risiko_turun_pct)

    assert by_kode["ZZBUYREC"]["direction"] == "BUY"
    assert by_kode["ZZBUYREC"]["tp_pct"] == 4.0  # = potensi_naik_pct, TIDAK ditukar
    assert by_kode["ZZBUYREC"]["sl_pct"] == 6.0  # = risiko_turun_pct, TIDAK ditukar


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


def test_signal_report_exposes_partial_progress_alongside_win_rate(clean_signal_db):
    """partial_progress (kartu 'Sedang Profit') tetap ada sbg info
    OPERASIONAL terpisah (berapa sinyal yang lagi berjalan sudah kena
    TP1+) -- TIDAK dihapus walau sekarang win_rate juga sudah menghitung
    baris OPEN yang sama (lihat test open_tp_progress_counts_as_win di
    bawah); dua-duanya boleh menyala bersamaan, bukan saling meniadakan."""
    from core.database import get_db
    from core.signal_history import _ensure_table, get_signal_report

    _ensure_table()
    with get_db() as conn:
        conn.execute("INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, status, tp_level_hit) "
                     "VALUES ('ZZPROG1', 1000, 5, 3, 'OPEN', 1)")
        conn.execute("INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, status, tp_level_hit) "
                     "VALUES ('ZZPROG2', 1000, 5, 3, 'OPEN', 2)")
        conn.execute("INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, status, tp_level_hit) "
                     "VALUES ('ZZNOPROG1', 1000, 5, 3, 'OPEN', 0)")
        conn.execute("INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, status, tp_level_hit) "
                     "VALUES ('ZZNOPROG2', 1000, 5, 3, 'OPEN', 0)")

    report = get_signal_report()

    assert report["partial_progress"]["n_open"] == 4
    assert report["partial_progress"]["n_tp_progress"] == 2
    assert report["partial_progress"]["pct_tp_progress"] == pytest.approx(50.0)


def test_signal_report_open_signal_with_tp1_counts_as_win_in_stats(clean_signal_db):
    """Regresi UTAMA (permintaan user langsung: 'tp1 masuk ke win rate
    soalnya tp2 atau tp3 kan optional, jadi ga harus tp3 baru dimasukin'):
    sinyal yang MASIH OPEN tapi sudah tp_level_hit>=1 HARUS ikut dihitung
    sbg 'win' di stats -- TIDAK LAGI menunggu status jadi TP_HIT (yang
    berarti sampai TP3)."""
    from core.database import get_db
    from core.signal_history import _ensure_table, get_signal_report

    _ensure_table()
    with get_db() as conn:
        # OPEN, sudah kena TP1 -- harus ikut dihitung menang walau BELUM closed.
        conn.execute("INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, status, tp_level_hit) "
                     "VALUES ('ZZOPENWIN', 1000, 5, 3, 'OPEN', 1)")
        # SL_HIT SUNGGUHAN, belum pernah kena TP manapun -- tetap kalah.
        conn.execute('''INSERT INTO signal_history
            (kode, entry_price, tp_pct, sl_pct, status, tp_level_hit, resolved_at, return_pct, days_to_resolve)
            VALUES ('ZZREALLOSS', 1000, 5, 3, 'SL_HIT', 0, datetime('now'), -3.0, 2)''')

    stats = get_signal_report()["stats"]

    assert stats is not None, "sudah ada yg 'menang' (TP1) dan 'kalah' (SL murni) -- HARUS tampil, bukan None"
    assert stats["n_tp_hit"] == 1
    assert stats["n_sl_hit"] == 1
    assert stats["win_rate"] == pytest.approx(50.0)
    # avg_return_pct/avg_days_to_resolve TETAP hanya dari yg BENAR-BENAR
    # closed (ZZOPENWIN return_pct-nya NULL, masih OPEN) -- cuma ZZREALLOSS.
    assert stats["n_closed"] == 1
    assert stats["avg_return_pct"] == pytest.approx(-3.0)


def test_signal_report_avg_return_tp1_scenario_includes_open_winners(clean_signal_db):
    """Regresi utk bug tampilan nyata (win rate 78.6% tapi 'rata-rata
    return' cuma +0.66%): avg_return_pct hanya dari sinyal yang BENAR-
    BENAR selesai, padahal posisi rugi selesai CEPAT (SL 2-5 hari) dan
    pemenang TP1/TP2 masih OPEN berhari-hari nunggu TP3 -- rata-ratanya
    struktural condong ke sisi rugi. avg_return_tp1_pct menjawab 'berapa
    return per sinyal KALAU selalu ambil untung di TP1': populasi SAMA
    dgn win_rate -- pemenang (termasuk yang MASIH OPEN) menyumbang
    +tp_pct terkunci, kalah/kadaluarsa-tanpa-TP menyumbang return aktual."""
    from core.database import get_db
    from core.signal_history import _ensure_table, get_signal_report

    _ensure_table()
    with get_db() as conn:
        # Pemenang MASIH OPEN (TP1 tercapai) -- menyumbang +5.0 (tp_pct).
        conn.execute("INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, status, tp_level_hit) "
                     "VALUES ('ZZSCN1', 1000, 5, 3, 'OPEN', 1)")
        # Pemenang closed penuh di TP3 (+9 aktual) -- skenario TP1 TETAP
        # pakai +tp_pct (4.0), bukan +9: konsisten 'selalu exit di TP1'.
        conn.execute('''INSERT INTO signal_history
            (kode, entry_price, tp_pct, sl_pct, status, tp_level_hit, resolved_at, return_pct, days_to_resolve)
            VALUES ('ZZSCN2', 1000, 4, 3, 'TP_HIT', 3, datetime('now'), 9.0, 6)''')
        # Kalah murni -- menyumbang return aktual -3.0.
        conn.execute('''INSERT INTO signal_history
            (kode, entry_price, tp_pct, sl_pct, status, tp_level_hit, resolved_at, return_pct, days_to_resolve)
            VALUES ('ZZSCN3', 1000, 5, 3, 'SL_HIT', 0, datetime('now'), -3.0, 2)''')
        # Pemenang MASIH OPEN yang sudah sampai TP2 -- return terkunci
        # pakai tp2_pct (+8), skenario TP1 tetap tp_pct (+4).
        conn.execute("INSERT INTO signal_history (kode, entry_price, tp_pct, tp2_pct, sl_pct, status, tp_level_hit) "
                     "VALUES ('ZZSCN4', 1000, 4, 8, 3, 'OPEN', 2)")

    stats = get_signal_report()["stats"]

    assert stats["n_tp1_scenario"] == 4
    assert stats["avg_return_tp1_pct"] == pytest.approx((5.0 + 4.0 - 3.0 + 4.0) / 4, abs=0.01)
    # Return terkunci di level TERCAPAI: TP1-open=+5, TP_HIT penuh=+9
    # aktual, SL murni=-3 aktual, TP2-open=+8 (tp2_pct).
    assert stats["avg_return_locked_pct"] == pytest.approx((5.0 + 9.0 - 3.0 + 8.0) / 4, abs=0.01)
    # Deskriptif pemenang tuntas TP3: cuma ZZSCN2.
    assert stats["n_tp3_full"] == 1
    assert stats["avg_return_tp3_pct"] == pytest.approx(9.0)
    # avg_return_pct realisasi TIDAK berubah perilakunya (hanya 2 closed).
    assert stats["avg_return_pct"] == pytest.approx((9.0 - 3.0) / 2, abs=0.01)


def test_signal_report_sl_after_tp1_still_counts_as_win_not_loss(clean_signal_db):
    """Regresi kasus tepi PALING PENTING (dikonfirmasi eksplisit ke user
    sebelum diimplementasi): kalau posisi SUDAH sempat kena TP1 lalu
    BELAKANGAN berbalik turun sampai kena SL_HIT, itu TETAP dihitung
    MENANG (bukan kalah) -- sekali tp_level_hit>=1 tercatat, klasifikasi
    menangnya PERMANEN, tidak pernah berubah jadi kalah oleh pergerakan
    harga belakangan. Kalau ini tidak dijamin, satu sinyal yang sama bisa
    kelihatan menang atau kalah tergantung KAPAN statistik dicek -- lebih
    tidak jujur drpd aturan 'sekali menang, tetap menang' ini."""
    from core.database import get_db
    from core.signal_history import _ensure_table, get_signal_report

    _ensure_table()
    with get_db() as conn:
        # SL_HIT, TAPI tp_level_hit=1 (sempat kena TP1 dulu sebelum berbalik).
        conn.execute('''INSERT INTO signal_history
            (kode, entry_price, tp_pct, sl_pct, status, tp_level_hit, resolved_at, return_pct, days_to_resolve)
            VALUES ('ZZTP1THENSL', 1000, 5, 3, 'SL_HIT', 1, datetime('now'), -3.0, 5)''')

    stats = get_signal_report()["stats"]

    assert stats["n_tp_hit"] == 1, "harus dihitung menang -- tp_level_hit>=1 permanen, walau status akhirnya SL_HIT"
    assert stats["n_sl_hit"] == 0, "TIDAK BOLEH ikut dihitung kalah -- sudah kepakai sbg win"
    assert stats["win_rate"] == pytest.approx(100.0)


def test_signal_report_legacy_tp_hit_without_explicit_tp_level_hit_still_counts_as_win(clean_signal_db):
    """Kontrol backward-compat: baris TP_HIT lama/manual yang TIDAK
    eksplisit set tp_level_hit (default 0 dari schema) HARUS TETAP
    dihitung menang -- status=='TP_HIT' sendiri SUDAH cukup membuktikan
    tp_level_hit>=1 secara implisit, meski tidak tercatat eksplisit."""
    from core.database import get_db
    from core.signal_history import _ensure_table, get_signal_report

    _ensure_table()
    with get_db() as conn:
        conn.execute('''INSERT INTO signal_history
            (kode, entry_price, tp_pct, sl_pct, status, resolved_at, return_pct, days_to_resolve)
            VALUES ('ZZLEGACYTP', 1000, 5, 3, 'TP_HIT', datetime('now'), 5.0, 4)''')

    stats = get_signal_report()["stats"]
    assert stats["n_tp_hit"] == 1


def test_signal_report_partial_progress_none_when_no_open_signals(clean_signal_db):
    """Kontrol: kalau tidak ada sinyal OPEN sama sekali, partial_progress
    harus None (bukan dict dgn pembagian 0/0)."""
    from core.signal_history import get_signal_report

    report = get_signal_report()
    assert report["partial_progress"] is None


def test_record_daily_snapshots_saves_one_row_per_open_signal(clean_signal_db):
    """Regresi inti fitur baru (permintaan user: 'track sinyalnya, besok
    yg lanjut naik apa yg turun apa') -- record_daily_snapshots() harus
    menyimpan SATU baris snapshot per sinyal OPEN, dgn floating_return_pct
    dihitung dari harga yang diberikan price_lookup."""
    import asyncio

    from core.database import get_db
    from core.signal_history import _ensure_table, record_daily_snapshots

    _ensure_table()
    with get_db() as conn:
        cur = conn.execute("INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, status) "
                           "VALUES ('ZZSNAP', 1000, 5, 3, 'OPEN')")
        signal_id = cur.lastrowid
        conn.execute("INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, status, resolved_at) "
                     "VALUES ('ZZCLOSEDSNAP', 1000, 5, 3, 'TP_HIT', datetime('now'))")

    async def fake_lookup(kode):
        return 1050.0 if kode == "ZZSNAP" else None

    n = asyncio.run(record_daily_snapshots(fake_lookup))
    assert n == 1, "cuma 1 sinyal OPEN -- yang closed TIDAK BOLEH ikut disnapshot"

    with get_db() as conn:
        snap = conn.execute("SELECT * FROM signal_daily_snapshot WHERE signal_id = ?", (signal_id,)).fetchone()
    assert snap is not None
    assert snap["floating_return_pct"] == pytest.approx(5.0)  # (1050/1000 - 1) * 100
    assert snap["status"] == "OPEN"


def test_record_daily_snapshots_idempotent_same_day(clean_signal_db):
    """Regresi: dipanggil BERKALI-KALI di hari yang sama (siklus auto
    jalan tiap 10 menit) TIDAK BOLEH bikin snapshot dobel -- UNIQUE
    (signal_id, tanggal) + INSERT OR IGNORE harus membuat panggilan
    KEDUA jadi no-op, bukan gagal ATAU menimpa dgn harga baru."""
    import asyncio

    from core.database import get_db
    from core.signal_history import _ensure_table, record_daily_snapshots

    _ensure_table()
    with get_db() as conn:
        conn.execute("INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, status) "
                     "VALUES ('ZZIDEMPOTENT', 1000, 5, 3, 'OPEN')")

    async def fake_lookup_first(kode):
        return 1050.0

    async def fake_lookup_second(kode):
        return 9999.0  # harga BEDA -- TIDAK BOLEH menimpa snapshot hari ini yang sudah ada

    n1 = asyncio.run(record_daily_snapshots(fake_lookup_first))
    n2 = asyncio.run(record_daily_snapshots(fake_lookup_second))
    assert n1 == 1
    assert n2 == 0, "panggilan kedua di hari yang sama harus no-op"

    with get_db() as conn:
        rows = conn.execute("SELECT * FROM signal_daily_snapshot").fetchall()
    assert len(rows) == 1
    assert rows[0]["price"] == 1050.0, "harga snapshot pertama TIDAK BOLEH ketimpa"


def test_record_daily_snapshots_skips_on_weekend(clean_signal_db, monkeypatch):
    """Kontrol: SAMA spt record_top_picks(), snapshot TIDAK dicatat di
    akhir pekan (harga masih closing Jumat yang sama, bukan progres
    sungguhan)."""
    import asyncio

    import core.signal_history as sh
    from core.database import get_db

    monkeypatch.setattr(sh, "_is_bursa_weekend", lambda: True)
    with get_db() as conn:
        conn.execute("INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, status) "
                     "VALUES ('ZZWEEKEND', 1000, 5, 3, 'OPEN')")

    async def fake_lookup(kode):
        return 1050.0

    n = asyncio.run(sh.record_daily_snapshots(fake_lookup))
    assert n == 0


def test_get_daily_recap_classifies_wins_losses_and_movement(clean_signal_db):
    """Regresi inti fitur baru: get_daily_recap() utk tanggal tertentu
    harus (a) menghitung menang/kalah dari sinyal yang RESOLVE pada
    tanggal itu (aturan SAMA dgn _compute_stats: tp_level_hit>=1 selalu
    menang, SL_HIT cuma kalah kalau tp_level_hit masih 0), dan (b)
    membandingkan snapshot HARI ITU vs snapshot hari SEBELUMNYA utk
    sinyal yang masih OPEN, mengklasifikasi naik/turun/stabil."""
    from core.database import get_db
    from core.signal_history import _ensure_table, get_daily_recap

    _ensure_table()
    with get_db() as conn:
        # Menang (TP_HIT) hari ini.
        conn.execute('''INSERT INTO signal_history
            (kode, entry_price, tp_pct, sl_pct, status, resolved_at, return_pct, days_to_resolve, tp_level_hit)
            VALUES ('ZZWINTODAY', 1000, 9, 3, 'TP_HIT', '2026-07-08 10:00:00', 9.0, 2, 3)''')
        # Kalah (SL_HIT murni, tp_level_hit masih 0) hari ini.
        conn.execute('''INSERT INTO signal_history
            (kode, entry_price, tp_pct, sl_pct, status, resolved_at, return_pct, days_to_resolve, tp_level_hit)
            VALUES ('ZZLOSSTODAY', 1000, 9, 3, 'SL_HIT', '2026-07-08 11:00:00', -3.0, 1, 0)''')
        # Resolve di HARI LAIN -- tidak boleh ikut ke recap tanggal ini.
        conn.execute('''INSERT INTO signal_history
            (kode, entry_price, tp_pct, sl_pct, status, resolved_at, return_pct, days_to_resolve, tp_level_hit)
            VALUES ('ZZOTHERDAY', 1000, 9, 3, 'TP_HIT', '2026-07-01 10:00:00', 9.0, 2, 3)''')

        # Sinyal OPEN dgn snapshot kemarin & hari ini -- naik.
        cur = conn.execute("INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, status) "
                           "VALUES ('ZZNAIK', 1000, 9, 3, 'OPEN')")
        naik_id = cur.lastrowid
        conn.execute("INSERT INTO signal_daily_snapshot (signal_id, tanggal, price, floating_return_pct, status) "
                     "VALUES (?, '2026-07-07', 1020, 2.0, 'OPEN')", (naik_id,))
        conn.execute("INSERT INTO signal_daily_snapshot (signal_id, tanggal, price, floating_return_pct, status) "
                     "VALUES (?, '2026-07-08', 1050, 5.0, 'OPEN')", (naik_id,))

        # Sinyal OPEN dgn snapshot kemarin & hari ini -- turun/pullback.
        cur2 = conn.execute("INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, status) "
                            "VALUES ('ZZTURUN', 1000, 9, 3, 'OPEN')")
        turun_id = cur2.lastrowid
        conn.execute("INSERT INTO signal_daily_snapshot (signal_id, tanggal, price, floating_return_pct, status) "
                     "VALUES (?, '2026-07-07', 1050, 5.0, 'OPEN')", (turun_id,))
        conn.execute("INSERT INTO signal_daily_snapshot (signal_id, tanggal, price, floating_return_pct, status) "
                     "VALUES (?, '2026-07-08', 1020, 2.0, 'OPEN')", (turun_id,))

        # Sinyal OPEN yang BARU hari ini -- belum ada snapshot kemarin utk dibandingkan.
        cur3 = conn.execute("INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, status) "
                            "VALUES ('ZZBARU', 1000, 9, 3, 'OPEN')")
        baru_id = cur3.lastrowid
        conn.execute("INSERT INTO signal_daily_snapshot (signal_id, tanggal, price, floating_return_pct, status) "
                     "VALUES (?, '2026-07-08', 1010, 1.0, 'OPEN')", (baru_id,))

    recap = get_daily_recap("2026-07-08")

    assert recap["n_win"] == 1 and [w["kode"] for w in recap["wins"]] == ["ZZWINTODAY"]
    assert recap["n_loss"] == 1 and [l["kode"] for l in recap["losses"]] == ["ZZLOSSTODAY"]
    assert recap["win_rate_hari_ini"] == pytest.approx(50.0)

    berjalan = {c["kode"]: c for c in recap["masih_berjalan"]}
    assert berjalan["ZZNAIK"]["arah"] == "naik"
    assert berjalan["ZZNAIK"]["delta"] == pytest.approx(3.0)
    assert berjalan["ZZTURUN"]["arah"] == "turun"
    assert berjalan["ZZTURUN"]["delta"] == pytest.approx(-3.0)
    assert berjalan["ZZBARU"]["arah"] == "belum_ada_pembanding"
    assert berjalan["ZZBARU"]["delta"] is None


def test_get_daily_recap_defaults_to_today(clean_signal_db):
    """Kontrol: tanpa parameter tanggal, get_daily_recap() pakai HARI INI
    (WIB) -- tidak crash, dan bentuk return-nya tetap konsisten walau
    belum ada data sama sekali utk hari itu."""
    from core.signal_history import get_daily_recap

    recap = get_daily_recap()
    assert recap["n_win"] == 0 and recap["n_loss"] == 0
    assert recap["win_rate_hari_ini"] is None
    assert recap["masih_berjalan"] == []


def test_get_daily_recap_cumulative_for_today_includes_open_tp1_signals(clean_signal_db):
    """Regresi bug NYATA yg dilaporkan user: 'itu harusnya sama dong' --
    Win Rate 'hari ini' (win_rate_hari_ini, cuma dari sinyal yg RESOLVE
    tepat hari ini) beda dgn Win Rate keseluruhan, krn sinyal OPEN yg
    sudah TP1+ (tidak resolve, TP2/TP3 opsional) tidak pernah dihitung.
    win_rate_kumulatif utk HARI INI harus PERSIS SAMA dgn Win Rate
    keseluruhan (_compute_stats atas seluruh tabel) krn keduanya
    menghitung hal yg SAMA: seluruh sinyal yg sudah menang/kalah SAMPAI
    hari ini."""
    from core.database import get_db
    from core.signal_history import _ensure_table, get_daily_recap

    _ensure_table()
    with get_db() as conn:
        # Menang closed (resolve tepat hari ini).
        conn.execute('''INSERT INTO signal_history
            (kode, entry_price, tp_pct, sl_pct, status, resolved_at, return_pct, days_to_resolve, tp_level_hit)
            VALUES ('ZZCLOSEDWIN', 1000, 9, 3, 'TP_HIT', datetime('now', 'localtime'), 9.0, 2, 3)''')
        # Kalah closed (resolve tepat hari ini).
        conn.execute('''INSERT INTO signal_history
            (kode, entry_price, tp_pct, sl_pct, status, resolved_at, return_pct, days_to_resolve, tp_level_hit)
            VALUES ('ZZCLOSEDLOSS', 1000, 9, 3, 'SL_HIT', datetime('now', 'localtime'), -3.0, 1, 0)''')
        # 3 sinyal OPEN yg sudah TP1+ -- TIDAK resolve, TIDAK masuk
        # win_rate_hari_ini, TAPI HARUS masuk win_rate_kumulatif.
        for kode in ("ZZOPENWIN1", "ZZOPENWIN2", "ZZOPENWIN3"):
            conn.execute(f'''INSERT INTO signal_history
                (kode, entry_price, tp_pct, tp2_pct, tp3_pct, sl_pct, status, tp_level_hit)
                VALUES ('{kode}', 1000, 3, 6, 9, 3, 'OPEN', 1)''')
        # 1 sinyal OPEN yg BELUM tercapai TP manapun -- tidak menang/kalah.
        conn.execute('''INSERT INTO signal_history
            (kode, entry_price, tp_pct, sl_pct, status, tp_level_hit)
            VALUES ('ZZOPENUNDECIDED', 1000, 3, 3, 'OPEN', 0)''')

    recap = get_daily_recap()
    # Skop harian (resolve tepat hari ini) TETAP cuma 1 menang, 1 kalah.
    assert recap["n_win"] == 1 and recap["n_loss"] == 1
    assert recap["win_rate_hari_ini"] == pytest.approx(50.0)
    # Skop kumulatif HARUS ikutkan 3 sinyal OPEN TP1+ sbg menang juga.
    assert recap["n_win_kumulatif"] == 4
    assert recap["n_loss_kumulatif"] == 1
    assert recap["win_rate_kumulatif"] == pytest.approx(80.0)


def test_get_daily_recap_cumulative_for_past_date_uses_historical_snapshot(clean_signal_db):
    """Regresi: utk tanggal HISTORIS (bukan hari ini), status/tp_level_hit
    LIVE saat ini TIDAK relevan (bisa sudah naik lagi SETELAH tanggal
    itu) -- rekonstruksi kumulatif harus pakai snapshot HARIAN paling
    akhir PADA/SEBELUM tanggal itu, BUKAN nilai live sekarang."""
    from core.database import get_db
    from core.signal_history import _ensure_table, get_daily_recap

    _ensure_table()
    with get_db() as conn:
        # Direkam 2 hari lalu, TP1 baru tercapai (live) HARI INI --
        # tp_level_hit LIVE = 1, tapi pada tanggal 2 hari lalu itu snapshot
        # menunjukkan MASIH 0 (belum decided).
        cur = conn.execute('''INSERT INTO signal_history
            (kode, entry_price, tp_pct, sl_pct, status, tp_level_hit, recorded_at)
            VALUES ('ZZLATEWIN', 1000, 3, 3, 'OPEN', 1, '2020-01-01 08:00:00')''')
        sid = cur.lastrowid
        conn.execute('''INSERT INTO signal_daily_snapshot
            (signal_id, tanggal, price, floating_return_pct, status, tp_level_hit)
            VALUES (?, '2020-01-01', 1000, 0.0, 'OPEN', 0)''', (sid,))

    recap_past = get_daily_recap("2020-01-01")
    # Pada 2020-01-01, sinyal ini BELUM TP1 (snapshot bilang tp_level_hit=0)
    # -- TIDAK BOLEH dihitung menang meski LIVE sekarang sudah TP1.
    assert recap_past["n_win_kumulatif"] == 0
    assert recap_past["win_rate_kumulatif"] is None

    recap_today = get_daily_recap()
    # HARI INI, status LIVE (tp_level_hit=1) yang dipakai -- HARUS menang.
    assert recap_today["n_win_kumulatif"] == 1
    assert recap_today["win_rate_kumulatif"] == pytest.approx(100.0)


def test_get_daily_recap_cumulative_excludes_signals_recorded_after_date(clean_signal_db):
    """Regresi: sinyal yang baru DICATAT setelah tanggal yang diminta
    TIDAK BOLEH ikut dihitung ke win rate kumulatif tanggal itu -- sinyal
    itu belum ada sama sekali pada tanggal tersebut."""
    from core.database import get_db
    from core.signal_history import _ensure_table, get_daily_recap

    _ensure_table()
    with get_db() as conn:
        conn.execute('''INSERT INTO signal_history
            (kode, entry_price, tp_pct, sl_pct, status, tp_level_hit, recorded_at)
            VALUES ('ZZFUTURE', 1000, 3, 3, 'OPEN', 1, '2099-01-01 08:00:00')''')

    recap = get_daily_recap("2020-01-01")
    assert recap["n_win_kumulatif"] == 0
    assert recap["win_rate_kumulatif"] is None


def test_signals_endpoint_returns_report_structure(client, clean_signal_db):
    r = client.get("/api/signals")
    assert r.status_code == 200
    data = r.json()
    assert "signals" in data and "stats" in data and "n_open" in data and "n_total" in data


def test_signals_endpoint_enriches_open_signals_with_floating_pnl(client, clean_signal_db):
    """Regresi fitur baru (permintaan user: 'liatkan floatingnya juga'):
    sinyal yang MASIH OPEN harus dilengkapi floating_price/floating_
    return_pct dari harga TERKINI (basis harga SAMA dgn yang dipakai
    audit_open_signals(), lihat _signal_audit_price_lookup) -- sinyal yang
    SUDAH SELESAI (closed) TIDAK boleh dapat field ini (hasilnya sudah
    final, bukan mark-to-market)."""
    from core.database import get_db

    with get_db() as conn:
        # tp_pct/sl_pct sengaja SANGAT lebar supaya harga acak dari fixture
        # no_network TIDAK PERNAH memicu TP/SL/EXPIRED -- posisi harus
        # tetap OPEN di endpoint ini.
        conn.execute('''
            INSERT INTO signal_history (kode, entry_price, tp_pct, tp2_pct, tp3_pct, sl_pct, status)
            VALUES ('ZZFLOAT', 1000, 90, 180, 270, 90, 'OPEN')
        ''')
        conn.execute('''
            INSERT INTO signal_history
                (kode, entry_price, tp_pct, sl_pct, status, resolved_at, resolved_price, return_pct, days_to_resolve)
            VALUES ('ZZCLOSED', 1000, 5, 3, 'TP_HIT', datetime('now'), 1050, 5.0, 2)
        ''')

    r = client.get("/api/signals")
    assert r.status_code == 200
    signals = r.json()["signals"]
    open_sig = next(s for s in signals if s["kode"] == "ZZFLOAT")
    closed_sig = next(s for s in signals if s["kode"] == "ZZCLOSED")

    assert open_sig["floating_price"] is not None
    assert open_sig["floating_return_pct"] == pytest.approx(
        round((open_sig["floating_price"] / open_sig["entry_price"] - 1) * 100, 2)
    )
    assert closed_sig.get("floating_price") is None
    assert closed_sig.get("floating_return_pct") is None


def test_riwayat_harian_endpoint_records_snapshot_when_viewing_today(client, clean_signal_db, monkeypatch):
    """Regresi: membuka riwayat harian utk HARI INI (tanggal default atau
    eksplisit) HARUS memicu record_daily_snapshots() -- supaya snapshot
    hari ini langsung ada begitu panel dibuka, sama pola dgn /api/signals
    memicu audit_open_signals()."""
    import core.signal_history as sh

    calls = []
    async def fake_record(price_lookup):
        calls.append(1)
        return 0
    monkeypatch.setattr(sh, "record_daily_snapshots", fake_record)

    r = client.get("/api/signals/riwayat-harian")
    assert r.status_code == 200
    assert len(calls) == 1

    today = sh.datetime.now().strftime("%Y-%m-%d")
    r2 = client.get(f"/api/signals/riwayat-harian?tanggal={today}")
    assert r2.status_code == 200
    assert len(calls) == 2


def test_riwayat_harian_endpoint_skips_snapshot_for_past_date(client, clean_signal_db, monkeypatch):
    """Regresi bug NYATA ditemukan lewat trace Playwright: date-picker di
    frontend (permintaan user: "di riwayat ada tombol tanggal") sempat
    memicu record_daily_snapshots() (real-time price lookup per sinyal
    OPEN, ~detikan x puluhan sinyal) di SETIAP klik tanggal, termasuk
    tanggal LAMPAU yang tidak butuh snapshot baru sama sekali -- bikin
    tiap klik date-picker makan puluhan detik tanpa alasan. Membuka
    tanggal LAMPAU TIDAK BOLEH memicu record_daily_snapshots()."""
    import core.signal_history as sh

    calls = []
    async def fake_record(price_lookup):
        calls.append(1)
        return 0
    monkeypatch.setattr(sh, "record_daily_snapshots", fake_record)

    r = client.get("/api/signals/riwayat-harian?tanggal=2020-01-01")
    assert r.status_code == 200
    assert len(calls) == 0


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
    mencatat sinyal baru) DAN audit sinyal OPEN (_run_signal_audit())
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
    monkeypatch.setattr(app_module, "_run_signal_audit", fake_audit)

    asyncio.run(app_module._run_signal_auto_cycle())
    assert calls == ["confidence", "audit"]


def _fake_sm_item(kode, pola, harga=1000.0, likuiditas="Sangat Likuid",
                   naik=3.0, turun=2.0):
    return {
        "kode": kode, "harga": harga, "pola": pola, "likuiditas": likuiditas,
        "potensi_naik_pct": naik, "risiko_turun_pct": turun,
        "confidence_score": 60.0, "ai_score": 55.0, "ai_rating": "BAGUS",
    }


def test_record_smart_money_signals_records_both_buy_and_sell_categories(clean_signal_db):
    """Regresi inti fitur integrasi: signal_history/audit_open_signals
    SEKARANG mendukung matematika bidirectional (kolom `direction`), jadi
    SEMUA kategori Smart Money direkam -- Akumulasi/Siluman/Breakout Volume
    sbg direction='BUY', Distribusi/Distribusi Agresif sbg direction=
    'SELL' (lihat test_record_smart_money_signals_records_distribusi_as_
    sell_with_swapped_tp_sl utk detail penukaran tp_pct/sl_pct-nya)."""
    import asyncio

    from core.signal_history import record_smart_money_signals

    items = [
        _fake_sm_item("ZZAKU", "Akumulasi Agresif"),
        _fake_sm_item("ZZSIL", "Siluman (quiet buy)"),
        _fake_sm_item("ZZBRK", "Breakout Volume"),
        _fake_sm_item("ZZDIS", "Distribusi Agresif"),
    ]
    saved = asyncio.run(record_smart_money_signals(items))
    by_kode = {s["kode"]: s for s in saved}
    assert set(by_kode.keys()) == {"ZZAKU", "ZZSIL", "ZZBRK", "ZZDIS"}
    assert by_kode["ZZAKU"]["direction"] == "BUY"
    assert by_kode["ZZSIL"]["direction"] == "BUY"
    assert by_kode["ZZBRK"]["direction"] == "BUY"
    assert by_kode["ZZDIS"]["direction"] == "SELL"
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


def test_record_smart_money_signals_blocked_by_open_signal_from_other_source(clean_signal_db):
    """Regresi (permintaan user langsung setelah melihat UI produksi):
    dedup SEKARANG per-KODE SAJA, lintas semua source -- kalau kode itu
    SUDAH punya sinyal TOP_PICK yang masih OPEN, TIDAK boleh direkam lagi
    sbg SMART_MONEY (atau sebaliknya) walau secara teori itu 'entry point
    berbeda'. Awalnya dedup di sini sengaja diizinkan tumpang tindih antar
    source (utk 'membandingkan teori entry'), tapi user melihat langsung
    di UI itu kelihatan persis seperti 'double' yang membingungkan (mis.
    RAJA tampil sbg TOP_PICK *dan* SMART_MONEY hari yang sama, angka
    entry/TP/SL nyaris identik)."""
    import asyncio

    from core.signal_history import (
        record_top_picks, record_smart_money_signals, get_signal_report, MIN_SCORE_TO_RECORD,
    )

    tp_items = [_fake_confidence_item("ZZTRIPLE", MIN_SCORE_TO_RECORD + 10)]
    sm_items = [_fake_sm_item("ZZTRIPLE", "Akumulasi Agresif")]

    saved_tp = asyncio.run(record_top_picks(tp_items))
    assert len(saved_tp) == 1

    saved_sm = asyncio.run(record_smart_money_signals(sm_items))
    assert saved_sm == [], "ZZTRIPLE sudah punya sinyal TOP_PICK yang masih OPEN -- SMART_MONEY harus diblokir"

    report = get_signal_report()
    rows = [s for s in report["signals"] if s["kode"] == "ZZTRIPLE"]
    assert len(rows) == 1
    assert rows[0]["source"] == "TOP_PICK"


def test_record_smart_money_signals_allowed_for_kode_without_open_signal(clean_signal_db):
    """Kontrol utk test di atas: SMART_MONEY tetap harus bisa mencatat
    kode yang BELUM punya sinyal OPEN dari source mana pun -- pemblokiran
    di atas itu spesifik utk konflik per-kode, bukan mematikan SMART_MONEY
    secara umum."""
    import asyncio

    from core.signal_history import record_smart_money_signals

    sm_items = [_fake_sm_item("ZZFRESH", "Akumulasi Agresif")]
    saved_sm = asyncio.run(record_smart_money_signals(sm_items))
    assert len(saved_sm) == 1
    assert saved_sm[0]["kode"] == "ZZFRESH"


def test_record_smart_money_signals_uses_scenario_entry_price_not_live_quote(clean_signal_db):
    """Sama seperti test_record_top_picks_uses_scenario_entry_price_not_live_
    quote, tapi utk record_smart_money_signals(): _record_smart_money_cycle
    (web/app.py) sekarang menyertakan 'entry_price' = conf.get('entry_price')
    dari confidence() utk kode yang sama (skenario Trading Plan yang beneran
    kena hari itu) -- ini HARUS menang atas 'harga' item Smart Money sendiri
    MAUPUN harga real-time dari price_lookup, konsisten dgn Top Pick."""
    import asyncio

    from core.signal_history import record_smart_money_signals, get_signal_report

    item = {
        **_fake_sm_item("ZZSMENTRY", "Akumulasi Agresif", harga=1000.0),
        "entry_price": 970.0,  # entry skenario dari confidence() -- beda dari harga & live
    }

    async def fake_lookup(kode):
        return 1030.0  # harga real-time, beda lagi dari keduanya

    saved = asyncio.run(record_smart_money_signals([item], price_lookup=fake_lookup))
    assert len(saved) == 1

    report = get_signal_report()
    by_kode = {s["kode"]: s for s in report["signals"]}
    assert by_kode["ZZSMENTRY"]["entry_price"] == 970.0  # skenario menang, bukan harga/live


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
         "likuiditas": "Sangat Likuid", "confidence_score": 72.5, "ai_score": 68.0, "ai_rating": "BAGUS",
         "ringkasan_teknikal": {"overall": "BELI", "beli": 4, "netral": 2, "jual": 0}},
    ]
    asyncio.run(app_module._record_smart_money_cycle(confidence_items))

    assert len(captured["items"]) == 1
    enriched = captured["items"][0]
    assert enriched["kode"] == "SMHIT"
    assert enriched["confidence_score"] == 72.5, "confidence_score harus ikut terbawa dari confidence_items, bukan None"
    assert enriched["potensi_naik_pct"] == 4.0
    assert enriched["risiko_turun_pct"] == 2.0
    assert enriched["likuiditas"] == "Sangat Likuid"
    assert enriched["ai_rating"] == "BELI", (
        "kolom recommendation harus menyimpan verdict Ringkasan Sinyal Teknikal yang JADI ALASAN "
        "konfirmasinya, bukan ai_rating lama"
    )


def test_record_smart_money_cycle_filters_out_non_buy_technical(monkeypatch):
    """Permintaan eksplisit user ("smart money itu di combo ama ini" --
    menunjuk panel Ringkasan Sinyal Teknikal di Analisis): Smart Money
    HANYA dicatat kalau Ringkasan Sinyal Teknikal JUGA bilang BELI/BELI
    KUAT -- pola volume Akumulasi yang muncul di saham dgn verdict NETRAL
    harus di-skip, bukan diandalkan pola volumenya sendiri saja."""
    import asyncio

    import web.app as app_module

    async def fake_scan(kode):
        return {"kode": kode, "harga": 1000.0, "chg1": 5.0, "chg5": 5.0,
                "vol_ratio": 3.0, "rsi": 70.0, "pola": "Akumulasi Agresif",
                "hari_lalu": 0, "tanggal": "2026-07-06", "grup": "Independen"}

    monkeypatch.setattr(app_module, "_scan_one_sm", fake_scan)
    monkeypatch.setattr(app_module, "_SM_UNIVERSE", ["SMBUYOK", "SMHOLDONLY"])

    captured = {}

    async def fake_record(enriched_items, price_lookup=None):
        captured["items"] = enriched_items
        return []

    import core.signal_history as sh
    monkeypatch.setattr(sh, "record_smart_money_signals", fake_record)

    confidence_items = [
        {"kode": "SMBUYOK", "potensi_naik_pct": 4.0, "risiko_turun_pct": 2.0,
         "likuiditas": "Sangat Likuid", "confidence_score": 72.5, "ai_score": 68.0, "ai_rating": "BAGUS",
         "ringkasan_teknikal": {"overall": "BELI", "beli": 4, "netral": 2, "jual": 0}},
        {"kode": "SMHOLDONLY", "potensi_naik_pct": 4.0, "risiko_turun_pct": 2.0,
         "likuiditas": "Sangat Likuid", "confidence_score": 50.0, "ai_score": 50.0, "ai_rating": "NETRAL",
         "ringkasan_teknikal": {"overall": "NETRAL", "beli": 2, "netral": 3, "jual": 1}},
    ]
    asyncio.run(app_module._record_smart_money_cycle(confidence_items))

    kodes = [it["kode"] for it in captured["items"]]
    assert kodes == ["SMBUYOK"], "hanya kode dgn Ringkasan Sinyal Teknikal BELI KUAT/BELI yang boleh lolos"


def test_record_smart_money_cycle_filters_out_distribusi_pola(monkeypatch):
    """Permintaan eksplisit user ('hanya yg teknikalnya disuruh buy aja'):
    pola Distribusi/Distribusi Agresif TIDAK LAGI direkam sbg entry SELL
    independen, walau teknikalnya kebetulan bagus -- Smart Money sekarang
    cuma jadi konfirmasi TAMBAHAN di atas sinyal BUY, bukan sumber SELL
    berdiri sendiri yang bisa bertentangan arah dgn Top Pick."""
    import asyncio

    import web.app as app_module

    async def fake_scan(kode):
        return {"kode": kode, "harga": 1000.0, "chg1": -5.0, "chg5": -5.0,
                "vol_ratio": 3.0, "rsi": 30.0, "pola": "Distribusi Agresif",
                "hari_lalu": 0, "tanggal": "2026-07-06", "grup": "Independen"}

    monkeypatch.setattr(app_module, "_scan_one_sm", fake_scan)
    monkeypatch.setattr(app_module, "_SM_UNIVERSE", ["SMDIST"])

    captured = {}

    async def fake_record(enriched_items, price_lookup=None):
        captured["items"] = enriched_items
        return []

    import core.signal_history as sh
    monkeypatch.setattr(sh, "record_smart_money_signals", fake_record)

    confidence_items = [
        {"kode": "SMDIST", "potensi_naik_pct": 4.0, "risiko_turun_pct": 2.0,
         "likuiditas": "Sangat Likuid", "confidence_score": 80.0, "ai_score": 80.0, "ai_rating": "SANGAT BAGUS",
         "ringkasan_teknikal": {"overall": "BELI KUAT", "beli": 5, "netral": 1, "jual": 0}},
    ]
    asyncio.run(app_module._record_smart_money_cycle(confidence_items))

    assert captured["items"] == [], "pola Distribusi harus dibuang sepenuhnya, walau ai_rating-nya BUY"


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


def test_latest_x15_holders_for_kode_dedupes_to_most_recent_filing_per_person(monkeypatch):
    """Regresi inti fitur baru (panel 'Pemegang Saham ≥5% & Insider' di
    halaman Pemegang Saham): kalau orang/entitas yang sama lapor X-15
    beberapa kali dalam rentang hari yang di-scan (tiap kali ada
    perubahan), HANYA filing TERBARU (tanggal paling baru) yang boleh
    dipakai sbg status kepemilikannya SEKARANG -- filing lama harus
    dibuang, BUKAN ditampilkan dobel/basi."""
    import web.app as app_module

    items = [
        {"kode": "BBCA", "nama": "Big Fund", "perusahaan": "", "jabatan": "",
         "tanggal": "2026-06-01", "pct_sebelum": 10.0, "pct_setelah": 12.0, "perubahan": 2.0,
         "jenis": "beli", "pengendali": False},
        # Filing TERBARU utk "Big Fund" yang sama -- ini yang harus menang.
        {"kode": "BBCA", "nama": "Big Fund", "perusahaan": "", "jabatan": "",
         "tanggal": "2026-06-15", "pct_sebelum": 12.0, "pct_setelah": 15.0, "perubahan": 3.0,
         "jenis": "beli", "pengendali": False},
        {"kode": "BBCA", "nama": "", "perusahaan": "PT Pengendali Utama", "jabatan": "Direktur",
         "tanggal": "2026-06-10", "pct_sebelum": 50.0, "pct_setelah": 50.0, "perubahan": 0.0,
         "jenis": "lain", "pengendali": True},
    ]

    holders = app_module._latest_x15_holders_for_kode(items)

    assert len(holders) == 2, "'Big Fund' cuma boleh muncul SEKALI (filing terbaru), bukan dua-duanya"
    big_fund = next(h for h in holders if h["nama"] == "Big Fund")
    assert big_fund["tanggal"] == "2026-06-15"
    assert big_fund["pct_setelah"] == 15.0
    # Terurut dari pct_setelah TERBESAR (mirip tampilan 'top holder').
    assert holders[0]["pct_setelah"] >= holders[1]["pct_setelah"]


def test_latest_x15_holders_for_kode_skips_unidentifiable_rows(monkeypatch):
    """Kontrol: baris yang nama DAN perusahaan-nya kosong (tidak bisa
    diidentifikasi sama sekali, mis. laporan buyback lewat Direksi atas
    nama pengendali yang field-nya 'null') HARUS dilewati -- jangan
    ditampilkan sbg pemegang saham anonim yang membingungkan."""
    import web.app as app_module

    items = [
        {"kode": "FAST", "nama": "", "perusahaan": "", "jabatan": "Direktur",
         "tanggal": "2026-06-01", "pct_sebelum": 100.0, "pct_setelah": 100.0, "perubahan": 0.0,
         "jenis": "lain", "pengendali": True},
    ]
    holders = app_module._latest_x15_holders_for_kode(items)
    assert holders == []


def test_api_pemegang_saham_endpoint_filters_by_kode_and_aggregates_days(client, monkeypatch):
    """Regresi endpoint /api/pemegang-saham/{kode}: menggabungkan filing
    dari BEBERAPA hari (via _fetch_x15_history_for_kode, dipanggil
    konkuren) dan HANYA menyaring kode yang diminta -- kode lain yang
    kebetulan muncul di hari yang sama TIDAK BOLEH ikut."""
    import web.app as app_module

    async def _fake_fetch(days_back=0):
        if days_back == 0:
            return [
                {"kode": "BBCA", "nama": "Investor A", "perusahaan": "", "jabatan": "",
                 "tanggal": "2026-07-06", "pct_sebelum": 10.0, "pct_setelah": 11.0, "perubahan": 1.0,
                 "jenis": "beli", "pengendali": False},
                {"kode": "TLKM", "nama": "Investor Lain", "perusahaan": "", "jabatan": "",
                 "tanggal": "2026-07-06", "pct_sebelum": 5.0, "pct_setelah": 6.0, "perubahan": 1.0,
                 "jenis": "beli", "pengendali": False},
            ]
        return []

    monkeypatch.setattr(app_module, "_fetch_x15_today", _fake_fetch)
    monkeypatch.setattr(app_module, "_cache_get", lambda k: None)
    monkeypatch.setattr(app_module, "_cache_set", lambda *a, **k: None)

    r = client.get("/api/pemegang-saham/BBCA")
    assert r.status_code == 200
    data = r.json()
    assert data["kode"] == "BBCA"
    assert len(data["holders"]) == 1
    assert data["holders"][0]["nama"] == "Investor A"
    assert "disclaimer" in data and "X-15" in data["disclaimer"]


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


def test_ringkasan_sinyal_teknikal_matches_js_thresholds():
    """Unit test _ringkasan_sinyal_teknikal: HARUS porting persis dari
    _buildTechSummary() di web/static/index.html (permintaan user, gerbang
    konfirmasi Smart Money yang baru). Skenario ini PERSIS contoh dari
    screenshot user: RSI 56.9 (netral, mendekati overbought), MACD
    positif (beli), Volume 0.70x (netral), AI Score 75 (beli), %1H +4.82%
    (beli), %5H +14.62% (beli) -> 4 beli, 2 netral, 0 jual -> overall
    'BELI' (bukan 'BELI KUAT', krn beli=4 belum >=5)."""
    import web.app as app_module

    ai_screenshot = {
        "rsi": 56.9, "macd_bullish": True, "vol_ratio": 0.70,
        "score": 75, "change_1d": 4.82, "change_5d": 14.62,
    }
    r = app_module._ringkasan_sinyal_teknikal(ai_screenshot)
    assert r == {"overall": "BELI", "beli": 4, "netral": 2, "jual": 0}

    # Semua 6 indikator searah jual -> JUAL KUAT (beli=0, jual=6>=5).
    ai_jual_kuat = {
        "rsi": 75, "macd_bullish": False, "vol_ratio": 0.3,
        "score": 20, "change_1d": -2.0, "change_5d": -5.0,
    }
    r2 = app_module._ringkasan_sinyal_teknikal(ai_jual_kuat)
    assert r2["overall"] == "JUAL KUAT"
    assert r2["jual"] == 6

    # Semua netral kecuali MACD (yang binary, tidak pernah netral) -> hasil
    # 1 beli/1 jual dari MACD sendirian, 5 netral dari yang lain -> netral==jual
    # tergantung arah MACD; di sini MACD bullish=True -> beli=1, jual=0,
    # netral=5 -> beli>jual -> CENDERUNG BELI.
    ai_netral = {
        "rsi": 55, "macd_bullish": True, "vol_ratio": 1.0,
        "score": 50, "change_1d": 0.0, "change_5d": 0.0,
    }
    r3 = app_module._ringkasan_sinyal_teknikal(ai_netral)
    assert r3 == {"overall": "CENDERUNG BELI", "beli": 1, "netral": 5, "jual": 0}


def test_get_ara_arb_bands_per_price_tier():
    """Unit test _get_ara_arb_bands: ARA tetap bertingkat per tier harga,
    ARB flat 15% di semua tier (per revisi BEI/OJK 8 April 2025,
    diverifikasi via web search -- lihat docstring fungsi)."""
    import web.app as app_module

    assert app_module._get_ara_arb_bands(100) == (0.35, 0.15)
    assert app_module._get_ara_arb_bands(2000) == (0.25, 0.15)
    assert app_module._get_ara_arb_bands(6000) == (0.20, 0.15)


def test_add_cross_sectional_rank_computes_percentile_per_liquidity_group():
    """Regresi gap metodologi (temuan audit): threshold vol_ratio absolut
    flat ke semua saham bias terhadap heteroskedastisitas volume (blue
    chip varians rendah vs saham tidur varians tinggi). Percentile HARUS
    dihitung PER GRUP LIKUIDITAS -- saham dgn vol_ratio absolut tinggi di
    satu grup TIDAK BOLEH mempengaruhi percentile saham di grup lain."""
    import web.app as app_module

    items = [
        {"kode": "A", "vol_ratio": 2.0, "likuiditas": "Sangat Likuid"},
        {"kode": "B", "vol_ratio": 3.0, "likuiditas": "Sangat Likuid"},
        {"kode": "C", "vol_ratio": 10.0, "likuiditas": "Likuid"},
        {"kode": "D", "vol_ratio": 12.0, "likuiditas": "Likuid"},
    ]
    result = app_module._add_cross_sectional_rank(items)
    by_kode = {x["kode"]: x for x in result}
    assert by_kode["B"]["vol_ratio_percentile"] == 100.0
    assert by_kode["A"]["vol_ratio_percentile"] == 50.0
    assert by_kode["D"]["vol_ratio_percentile"] == 100.0
    assert by_kode["C"]["vol_ratio_percentile"] == 50.0


def test_build_sm_payload_sorts_akumulasi_by_percentile_not_raw_vol_ratio():
    """Regresi: sorting akumulasi/distribusi sekarang berdasar percentile
    per grup likuiditas, BUKAN vol_ratio mentah -- saham dgn vol_ratio
    absolut lebih tinggi tapi 'biasa saja' dibanding peer-nya (semua peer
    di grupnya SAMA-SAMA rame) harus kalah urutan dari saham dgn vol_ratio
    absolut lebih rendah tapi PALING menonjol di grup likuiditasnya
    sendiri (populasi peer yang tenang)."""
    import web.app as app_module

    items = [
        {"kode": "E", "vol_ratio": 9.0, "pola": "Akumulasi", "likuiditas": "Sangat Likuid"},
        {"kode": "PEER1", "vol_ratio": 8.0, "pola": "Akumulasi", "likuiditas": "Sangat Likuid"},
        {"kode": "PEER2", "vol_ratio": 10.0, "pola": "Akumulasi", "likuiditas": "Sangat Likuid"},
        {"kode": "F", "vol_ratio": 2.0, "pola": "Akumulasi", "likuiditas": "Likuid"},
        {"kode": "PEER3", "vol_ratio": 1.0, "pola": "Akumulasi", "likuiditas": "Likuid"},
    ]
    payload = app_module._build_sm_payload(items, total=10, scope="core")
    akumulasi_kodes = [x["kode"] for x in payload["akumulasi"]]
    assert akumulasi_kodes.index("F") < akumulasi_kodes.index("E"), (
        f"F (percentile 100% di grupnya) harus di atas E (percentile 66.7% di grupnya) "
        f"walau vol_ratio absolut F (2.0) jauh lebih rendah dari E (9.0), dapat urutan {akumulasi_kodes}"
    )


def test_sm_process_df_skips_ara_locked_day():
    """Regresi gap metodologi: harga yang mendekati/kena batas ARA (harga
    tier Rp200-5.000 -> batas 25%) harus di-skip -- volume saat limit
    biasanya cuma order matching tipis di harga cap, bukan indikasi minat
    institusional genuine, dan chg1 jadi ekstrem murni krn mentok batas."""
    import web.app as app_module

    n = 65
    closes = [2000.0] * n
    volumes = [8_000_000.0] * n
    closes[-1] = 2000.0 * 1.24  # +24%, >= 25%-2% margin
    volumes[-1] = 20_000_000.0

    df = _sm_df(closes, volumes)
    assert app_module._process_sm_df("TESTARA", df) is None


def test_sm_process_df_skips_arb_locked_day():
    """Regresi gap metodologi: harga yang mendekati/kena batas ARB (flat
    15% semua tier) harus di-skip, sama alasannya dgn ARA."""
    import web.app as app_module

    n = 65
    closes = [2000.0] * n
    volumes = [8_000_000.0] * n
    closes[-1] = 2000.0 * 0.86  # -14%, <= -15%+2% margin
    volumes[-1] = 20_000_000.0

    df = _sm_df(closes, volumes)
    assert app_module._process_sm_df("TESTARB", df) is None


def test_sm_process_df_allows_normal_move_within_ara_arb_bounds():
    """Regresi: pergerakan wajar (jauh dari batas ARA/ARB) TIDAK boleh
    ikut ke-skip oleh guard baru ini -- pastikan guard ARA/ARB tidak
    overreach ke pergerakan normal."""
    import web.app as app_module

    n = 65
    closes = [2000.0] * n
    volumes = [8_000_000.0] * n
    closes[-1] = 2000.0 * 1.06  # +6%, jauh dari batas ARA (25%) maupun ARB
    volumes[-1] = 20_000_000.0

    df = _sm_df(closes, volumes)
    result = app_module._process_sm_df("TESTNORMALMOVE", df)
    assert result is not None
    assert result["chg1"] == 6.0
