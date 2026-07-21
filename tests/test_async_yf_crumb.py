# Test utk core/async_yf.py penanganan 'Invalid Crumb'/401 Yahoo Finance.
# Latar: retry biasa TIDAK menyembuhkan 'Invalid Crumb' karena yfinance
# memakai ULANG crumb basi yang di-cache; obatnya membuang crumb (via
# _reset_yf_crumb) SEBELUM percobaan berikutnya. Ini akar berulangnya
# "kadang gagal memuat data" -- test ini menjaganya tidak regres.
import asyncio

import pandas as pd

import core.async_yf as ay


def test_is_crumb_error_classifies_auth_but_not_ratelimit():
    # Auth/crumb -> True (sembuh dgn re-negosiasi)
    assert ay._is_crumb_error(Exception("Invalid Crumb"))
    assert ay._is_crumb_error(Exception("HTTP Error 401: Unauthorized"))
    assert ay._is_crumb_error(Exception("Failed to get valid crumb"))
    # Rate-limit / jaringan -> False (re-negosiasi malah memperparah / tak relevan)
    assert not ay._is_crumb_error(Exception("Too Many Requests. Rate limited."))
    assert not ay._is_crumb_error(Exception("HTTP Error 429"))
    assert not ay._is_crumb_error(Exception("Connection timed out"))


def test_async_download_resets_crumb_then_recovers(monkeypatch):
    """Percobaan pertama lempar 'Invalid Crumb' -> HARUS reset crumb lalu
    percobaan kedua berhasil (bukan gagal total karena crumb basi dipakai
    ulang)."""
    calls = {"n": 0, "reset": 0}
    good = pd.DataFrame({"Close": [1.0]})

    def fake_download(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise Exception("Invalid Crumb")
        return good

    monkeypatch.setattr(ay.yf, "download", fake_download)
    monkeypatch.setattr(ay, "_reset_yf_crumb",
                        lambda: calls.__setitem__("reset", calls["reset"] + 1) or True)

    df = asyncio.run(ay.async_download("BBCA.JK", period="1mo"))

    assert df is not None and not df.empty
    assert calls["n"] == 2          # retry benar-benar terjadi
    assert calls["reset"] == 1      # crumb di-reset tepat sekali di antara percobaan


def test_async_download_does_not_reset_crumb_on_ratelimit(monkeypatch):
    """429 rate-limit: retry BOLEH, tapi crumb JANGAN di-reset -- re-negosiasi
    cookie saat sedang dibatasi rate malah memperparah."""
    calls = {"n": 0, "reset": 0}

    def fake_download(*a, **k):
        calls["n"] += 1
        raise Exception("Too Many Requests 429")

    monkeypatch.setattr(ay.yf, "download", fake_download)
    monkeypatch.setattr(ay, "_reset_yf_crumb",
                        lambda: calls.__setitem__("reset", calls["reset"] + 1) or True)

    try:
        asyncio.run(ay.async_download("BBCA.JK", max_retries=2))
    except Exception:
        pass

    assert calls["n"] == 2          # tetap retry
    assert calls["reset"] == 0      # TAPI tidak pernah reset crumb
