# =========================
# FIXTURE BERSAMA UNTUK TES API
# =========================
# Semua tes berjalan TANPA jaringan asli (Yahoo Finance) dan TANPA Redis
# asli:
# - yfinance di-monkeypatch supaya deterministik & cepat.
# - REDIS_URL diarahkan ke port yang tidak dipakai SEBELUM web.app diimpor,
#   supaya _redis client gagal connect. Ini aman karena semua helper cache
#   di web/app.py (`_cache_get`, `_cache_set`, `_realtime_price`, middleware
#   rate limit) sudah fail-open (try/except) saat Redis tidak terjangkau --
#   jadi tes tetap jalan benar, hanya tanpa cache hit.
import os
import tempfile

os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:6399/0")
# DATABASE_URL diarahkan ke file SQLite terpisah di temp dir SEBELUM
# core.config diimpor di mana pun -- supaya tes signal_history/fundamental
# cache tidak menulis ke ranah_saham.db pemakaian sungguhan (lihat pola
# yang sama untuk REDIS_URL di atas).
os.environ.setdefault("DATABASE_URL", os.path.join(tempfile.gettempdir(), "ranah_saham_test.db"))

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient


def _fake_ohlcv(n: int = 300, start_price: float = 1000.0, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    returns = rng.normal(0, 0.015, n)
    close = start_price * np.cumprod(1 + returns)
    open_ = close * (1 + rng.normal(0, 0.003, n))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.005, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.005, n)))
    volume = rng.integers(1_000_000, 20_000_000, n).astype(float)
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume},
        index=dates,
    )


@pytest.fixture
def fake_df() -> pd.DataFrame:
    return _fake_ohlcv()


class _FakePipeline:
    """Cukup untuk pola `pipe.incr(k); pipe.expire(k, t); pipe.execute()`
    yang dipakai middleware rate limit di web/app.py."""

    def __init__(self, redis):
        self._redis = redis
        self._ops = []

    def incr(self, key):
        self._ops.append(("incr", key))
        return self

    def expire(self, key, ttl):
        self._ops.append(("expire", key, ttl))
        return self

    def execute(self):
        results = []
        for op, key, *rest in self._ops:
            if op == "incr":
                results.append(self._redis.incr(key))
            else:
                results.append(True)
        self._ops = []
        return results


class _FakeRedis:
    """Stub in-memory pengganti redis-py: cukup untuk get/setex/incr/expire/
    pipeline yang dipakai web/app.py, supaya tes bisa memverifikasi perilaku
    cache & rate-limit tanpa server Redis sungguhan."""

    def __init__(self):
        self.store: dict = {}

    def get(self, key):
        return self.store.get(key)

    def setex(self, key, ttl, value):
        self.store[key] = value

    def incr(self, key):
        self.store[key] = int(self.store.get(key, 0)) + 1
        return self.store[key]

    def expire(self, key, ttl):
        return True

    def pipeline(self):
        return _FakePipeline(self)


@pytest.fixture(autouse=True)
def no_network(monkeypatch, fake_df):
    import core.async_yf as async_yf

    monkeypatch.setattr(async_yf.yf, "download", lambda *a, **kw: fake_df.copy())

    class _FakeFastInfo:
        last_price = float(fake_df["Close"].iloc[-1])
        previous_close = float(fake_df["Close"].iloc[-2])

    class _FakeTicker:
        def __init__(self, *a, **kw):
            self.fast_info = _FakeFastInfo()

    import web.app as app_module

    monkeypatch.setattr(app_module.yf, "Ticker", _FakeTicker)
    monkeypatch.setattr(app_module, "_redis", _FakeRedis())

    # _fetch_x15_today() scrapes idx.co.id langsung (cloudscraper, bukan
    # yfinance) utk data kepemilikan X-15 -- TIDAK ada di allowlist mock
    # yfinance di atas, jadi di-mock TERPISAH supaya tes /api/confidence
    # (yang sekarang juga fetch X-15) tidak pernah menyentuh jaringan asli.
    async def _fake_x15(days_back=0):
        return []

    monkeypatch.setattr(app_module, "_fetch_x15_today", _fake_x15)
    yield


@pytest.fixture
def client():
    from web.app import app

    return TestClient(app)


@pytest.fixture
def clean_signal_db(monkeypatch):
    """Kosongkan tabel signal_history sebelum & sesudah tes -- supaya
    assertion statistik (win rate, avg return, dst) tidak terpengaruh sisa
    baris dari tes lain yang jalan lebih dulu di sesi pytest yang sama.

    Juga mem-patch _is_bursa_weekend() di core.signal_history supaya
    SELALU False (hari kerja) -- record_top_picks()/record_macd_cross_
    signals() sengaja SKIP pencatatan di akhir pekan, jadi tanpa ini
    SEMUA tes yang mengandalkan fixture ini akan gagal kalau kebetulan
    dijalankan di hari Sabtu/Minggu sungguhan (bukan bug tes, tapi
    lingkungan tes yang harus deterministik terlepas dari kapan `pytest`
    dijalankan). Sengaja patch fungsi ini SAJA (bukan `datetime` module-
    level) -- audit_open_signals() di modul yang sama juga pakai
    datetime.now() sungguhan utk hitung EXPIRED (MAX_HOLD_DAYS), jadi
    memalsukan seluruh datetime modul akan merusak perhitungan itu. Tes
    yang KHUSUS menguji perilaku akhir pekan (lihat
    test_record_top_picks_and_macd_skip_on_weekend) mem-patch ulang
    _is_bursa_weekend() jadi True sendiri setelah fixture ini, jadi tetap
    bisa override."""
    import core.signal_history as _sh

    monkeypatch.setattr(_sh, "_is_bursa_weekend", lambda: False)

    from core.signal_history import _ensure_table
    from core.database import get_db

    _ensure_table()
    with get_db() as conn:
        conn.execute("DELETE FROM signal_history")
    yield
    with get_db() as conn:
        conn.execute("DELETE FROM signal_history")
