# =========================
# TES: FILTER KEYWORD DI core/news.py::_fetch_single_source
# =========================
# Regresi bug nyata: filter `keyword=kode saham` pada _fetch_single_source
# dulu pakai substring MENTAH (`keyword.upper() in haystack`) -- tanpa
# batas kata. Akibatnya cari berita kode RAJA ikut menyangkut artikel yang
# cuma memuat kata "Kerajaan"/"Rajabasa" (RAJA kebetulan substring di
# tengah kata lain), padahal artikel itu SAMA SEKALI tidak membahas saham
# RAJA. User melaporkan ini langsung dari UI ("ga nyambung mentang mentang
# ada kata raja"). Diperbaiki dengan reuse deteksi_emiten() (sudah dipakai
# tagging /news umum) supaya presisinya konsisten satu logika di semua
# tempat -- BUKAN substring kedua yang independen.
import asyncio

import httpx

from core.news import _fetch_single_source

_FAKE_RSS = """<?xml version="1.0"?>
<rss><channel>
<item>
  <title>Kisah Robohnya Kerajaan Bisnis Salim Usai Berjaya 3 Dekade</title>
  <link>https://example.test/salim</link>
  <pubDate>Fri, 03 Jul 2026 08:00:00 +0700</pubDate>
  <description>Cerita perjalanan bisnis keluarga konglomerat era 90an.</description>
</item>
<item>
  <title>KAI Palembang Operasikan Kereta Ekonomi Premium KA Rajabasa</title>
  <link>https://example.test/rajabasa</link>
  <pubDate>Fri, 03 Jul 2026 08:30:00 +0700</pubDate>
  <description>Layanan kereta baru untuk rute Rajabasa.</description>
</item>
<item>
  <title>Saham RAJA Melonjak Usai Rilis Kinerja Kuartal II</title>
  <link>https://example.test/raja</link>
  <pubDate>Fri, 03 Jul 2026 09:00:00 +0700</pubDate>
  <description>PT Rukun Raharja Tbk (RAJA) mencatat kinerja positif.</description>
</item>
</channel></rss>"""


class _FakeResponse:
    def __init__(self, content: bytes):
        self.content = content

    def raise_for_status(self):
        pass


def _run_fetch_with_fake_rss(monkeypatch, rss_text: str, keyword):
    async def fake_get(self, url, headers=None):
        return _FakeResponse(rss_text.encode())

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    async def _run():
        return await _fetch_single_source(
            {"name": "Test", "url": "https://example.test/rss"}, keyword=keyword, limit=10
        )

    return asyncio.run(_run())


def test_ticker_keyword_filter_rejects_substring_false_positive(monkeypatch):
    """'RAJA' TIDAK boleh menyangkut 'Kerajaan'/'Rajabasa' -- keduanya
    sekadar mengandung substring 'raja' di tengah kata lain, bukan
    penyebutan ticker RAJA yang sesungguhnya."""
    success, items = _run_fetch_with_fake_rss(monkeypatch, _FAKE_RSS, keyword="RAJA")
    assert success
    titles = [it["title"] for it in items]
    assert not any("Kerajaan" in t for t in titles)
    assert not any("Rajabasa" in t for t in titles)


def test_ticker_keyword_filter_keeps_real_mention(monkeypatch):
    """Artikel yang SUNGGUHAN menyebut ticker RAJA (mis. '(RAJA)') tetap
    lolos filter -- perbaikan presisi tidak boleh membuang hasil valid."""
    success, items = _run_fetch_with_fake_rss(monkeypatch, _FAKE_RSS, keyword="RAJA")
    assert success
    titles = [it["title"] for it in items]
    assert any("Saham RAJA Melonjak" in t for t in titles)


def test_free_text_keyword_still_uses_plain_substring(monkeypatch):
    """Keyword yang BUKAN kode emiten dikenal (mis. frasa bebas 'ihsg
    bursa saham') tetap pakai substring biasa -- tidak semua caller
    fetch_news() mencari ticker spesifik."""
    rss = """<?xml version="1.0"?>
<rss><channel>
<item>
  <title>IHSG Bursa Saham Ditutup Menguat</title>
  <link>https://example.test/ihsg</link>
  <pubDate>Fri, 03 Jul 2026 10:00:00 +0700</pubDate>
  <description>Rangkuman penutupan perdagangan.</description>
</item>
<item>
  <title>Harga Emas Dunia Naik</title>
  <link>https://example.test/emas</link>
  <pubDate>Fri, 03 Jul 2026 10:30:00 +0700</pubDate>
  <description>Tidak berkaitan dengan bursa saham.</description>
</item>
</channel></rss>"""
    success, items = _run_fetch_with_fake_rss(monkeypatch, rss, keyword="IHSG Bursa Saham")
    assert success
    assert len(items) == 1
    assert "IHSG Bursa Saham" in items[0]["title"]


def test_berita_pasar_tidak_mengambil_dua_kali_lalu_membuang_satunya(monkeypatch):
    """Terbukti dari log produksi (7 Sep 2026) inilah penahan utama server:
    "lambat 20.88s GET /api/ihsgnews" berulang-ulang, dengan event loop
    tertahan 4-5 detik tiap kali.

    Versi lama memanggil fetch_news() DUA KALI: sekali langsung -- hasilnya
    dibuang, cuma dipakai memeriksa None -- lalu sekali lagi di dalam
    _market_news_pool(). Sepuluh sumber RSS dengan timeout 12 detik, dikerjakan
    dua kali, untuk nol tambahan informasi."""
    import asyncio

    import web.app as app_module

    panggilan = {"pool": 0, "fetch": 0}

    async def _pool(limit=10):
        panggilan["pool"] += 1
        return [{"title": "IHSG menguat", "source": "Uji", "link": "https://c/1"}]

    async def _fetch(keyword=None, limit=8):
        panggilan["fetch"] += 1
        return [{"title": "x"}]

    monkeypatch.setattr(app_module, "_market_news_pool", _pool)
    monkeypatch.setattr(app_module, "fetch_news", _fetch)
    try:
        app_module._redis.delete("cache:ihsgnews:v1")
    except Exception:
        pass

    hasil = asyncio.run(app_module._berita_pasar())
    assert hasil["items"] and hasil["items"][0]["title"] == "IHSG menguat"
    assert panggilan["pool"] == 1
    # fetch_news hanya diperiksa ULANG saat pool-nya KOSONG -- untuk
    # membedakan "tidak ada berita pasar" dari "semua sumber mati". Selama
    # ada isinya, ia tidak boleh dipanggil sama sekali.
    assert panggilan["fetch"] == 0, (
        "fetch_news tetap dipanggil walau pool berisi; hasilnya pasti dibuang")


def test_permintaan_berita_bersamaan_hanya_satu_pengambilan(monkeypatch):
    """Sepuluh pengunjung tidak boleh berarti sepuluh kali sepuluh sumber RSS."""
    import asyncio

    import web.app as app_module

    panggilan = {"n": 0}

    async def _lambat(limit=10):
        panggilan["n"] += 1
        await asyncio.sleep(0.05)
        return [{"title": "IHSG", "source": "Uji", "link": "https://c/1"}]

    monkeypatch.setattr(app_module, "_market_news_pool", _lambat)

    async def _serentak():
        try:
            app_module._redis.delete("cache:ihsgnews:v1")
        except Exception:
            pass
        return await asyncio.gather(*[app_module._berita_pasar() for _ in range(8)])

    hasil = asyncio.run(_serentak())
    assert len(hasil) == 8
    assert panggilan["n"] == 1, (
        f"{panggilan['n']} pengambilan untuk 8 permintaan bersamaan; "
        f"single-flight tidak bekerja")
