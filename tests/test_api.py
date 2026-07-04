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


def _fake_confidence_item(kode, score, naik=3.0, turun=2.0, harga=1000.0):
    return {
        "kode": kode, "harga": harga, "confidence_score": score, "ai_score": score,
        "ai_rating": "BAGUS", "potensi_naik_pct": naik, "risiko_turun_pct": turun,
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
