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
