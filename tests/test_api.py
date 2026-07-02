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
