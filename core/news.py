# =========================
# NEWS FEED
# =========================
# /news [kode] -- berita pasar/saham terkini, AGREGASI dari 3 RSS feed
# publik Indonesia (sumber gratis, tidak butuh API key).
#
# REVISI (Juni 2026, permintaan eksplisit user "lebih luas lagi" cakupan
# beritanya): SEBELUMNYA cuma 1 sumber (CNBC Indonesia Market). Sekarang
# AGREGASI dari 3 portal berita besar Indonesia, masing-masing
# DIVERIFIKASI aktif via fetch langsung sebelum diintegrasikan (bukan
# cuma asumsi dari listing aggregator):
# 1. CNBC Indonesia - Market (https://www.cnbcindonesia.com/market/rss/)
#    -- fokus saham/market, paling relevan untuk konteks per-emiten.
# 2. CNN Indonesia - Ekonomi (https://www.cnnindonesia.com/ekonomi/rss)
#    -- cakupan ekonomi makro lebih luas (rupiah, komoditas, kebijakan).
# 3. Detik Finance (https://finance.detik.com/rss) -- portal berita
#    terbesar Indonesia, kategori finance/bursa.
#
# KANDIDAT YANG DICOBA TAPI DITOLAK (dicatat jujur): Kontan.co.id
# (rss.kontan.co.id) SEMPAT dicoba tapi diblokir (bot detection) saat
# verifikasi langsung -- subdomain RSS-nya kemungkinan rusak/tidak
# dikelola lagi (indikasi lain: halaman default Apache, bukan SSL).
# TIDAK dipaksakan masuk meski namanya sering muncul di daftar
# aggregator RSS lain -- semua sumber di atas DIVERIFIKASI BISA DIAKSES
# LANGSUNG sebelum ditambahkan, bukan diasumsikan dari nama besar media.
#
# ARSITEKTUR: SEMUA sumber di-fetch PARALEL (asyncio.gather), masing-
# masing DIBUNGKUS try/except SENDIRI -- 1-2 sumber gagal (rate-limit,
# network) TIDAK menggagalkan yang lain, hasil dari sumber yang berhasil
# TETAP ditampilkan. Hasil gabungan diurutkan ulang berdasarkan tanggal
# publikasi SUNGGUHAN (parse RFC 822 pubDate dari XML, BUKAN cuma
# digabung mentah per-sumber) supaya berita TERBARU lintas semua sumber
# yang muncul duluan, bukan terkelompok per portal.
#
# KETERBATASAN YANG JUJUR DICATAT (masih berlaku, diperluas):
# - RSS feed ini mencampur berita ekonomi/saham SUNGGUHAN dengan konten
#   umum (kebijakan pemerintah, harga BBM, dst) -- filter kata kunci
#   ticker membantu mempersempit, tapi tidak sempurna.
# - 3 sumber TETAP bukan agregasi LENGKAP semua portal berita Indonesia
#   -- keterbatasan waktu/scope, BUKAN klaim ini cakupan terlengkap.
# - Tidak ada analisis sentimen otomatis (positif/negatif) -- user
#   membaca judul & ringkasan sendiri untuk menilai, bot tidak mengklaim
#   bisa membaca "nada" berita secara otomatis.

import defusedxml.ElementTree as ET  # guard terhadap XML attack (billion laughs, dll) saat parse RSS eksternal
import re
import asyncio
from datetime import datetime, timezone
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime

import httpx

from core.news_emiten import tag_items, deteksi_emiten, _load_emiten
from core.news_idx import fetch_idx_disclosures, ENABLE_IDX_DISCLOSURES

# Ambang kemiripan judul untuk dianggap berita DUPLIKAT lintas sumber.
# 0.82 = cukup ketat: "BBCA cetak laba Rp X" di CNBC vs Detik dianggap
# sama, tapi dua berita beda soal BBCA tetap dibedakan. Bisa di-tune.
DEDUP_SIMILARITY_THRESHOLD = 0.82

NEWS_SOURCES = [
    # ── Sumber RSS langsung ──
    {"name": "CNBC Indonesia", "url": "https://www.cnbcindonesia.com/market/rss/"},
    {"name": "CNN Indonesia",  "url": "https://www.cnnindonesia.com/ekonomi/rss"},
    {"name": "Detik Finance",  "url": "https://finance.detik.com/rss"},
    {"name": "ANTARA Bursa",   "url": "https://www.antaranews.com/rss/ekonomi-bursa.xml"},
    {"name": "ANTARA Bisnis",  "url": "https://www.antaranews.com/rss/ekonomi-bisnis.xml"},
    {"name": "ANTARA Ekonomi", "url": "https://www.antaranews.com/rss/ekonomi.xml"},
    # DIBUANG (laporan user "gagal muat data" + spam log tiap fetch, diverifikasi
    # langsung 2026-07-20): Bisnis.com (ekonomi.bisnis.com/rss -> 404), Kompas
    # Ekonomi (ekonomi.kompas.com/rss/ -> 404), Tempo Bisnis (bisnis.tempo.co/
    # rss/20 -> 200 tapi BUKAN XML, ParseError tiap parse), Investor.id
    # (investor.id/feed -> 404). Keempatnya gagal SETIAP fetch -- tiap
    # kegagalan makan waktu (koneksi/timeout/retry) & mengotori log, tanpa
    # pernah menyumbang satu berita pun. 9 sumber sehat yang tersisa (CNBC,
    # CNN, Detik, ANTARA x3, Google News x3) sudah lebih dari cukup. Kalau
    # nanti ada URL RSS baru yang valid utk media ini, tinggal tambah lagi.
    # ── Google News RSS ── aggregasi berbagai media, selalu bisa diakses,
    # tiap item menyertakan tag <source> berisi nama penerbit aslinya.
    {"name": "Google News", "url": "https://news.google.com/rss/search?q=IHSG+saham+bursa+efek+Indonesia&hl=id&gl=ID&ceid=ID:id", "google": True},
    {"name": "Google News", "url": "https://news.google.com/rss/search?q=emiten+korporasi+IDX+Indonesia&hl=id&gl=ID&ceid=ID:id",  "google": True},
    {"name": "Google News", "url": "https://news.google.com/rss/search?q=investasi+pasar+modal+Indonesia&hl=id&gl=ID&ceid=ID:id", "google": True},
]
NEWS_FETCH_TIMEOUT = 12.0
NEWS_PER_SOURCE_LIMIT = 20  # per sumber, sebelum gabung+potong ke limit final

# UA browser nyata -- penting agar situs yg pakai Cloudflare / bot-detection
# (CNBC, CNN, Detik, Bisnis, Kompas) tidak memblokir request.
_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)
_FETCH_HEADERS = {
    "User-Agent": _BROWSER_UA,
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache",
}


def _parse_pub_date(pub_date_str: str):
    """Parse RFC 822 pubDate (format standar RSS, mis. 'Fri, 29 May 2026
    15:49:03 +0700') jadi datetime untuk sorting lintas sumber. SELALU
    return timezone-AWARE datetime (kalau berhasil parse) -- BUG NYATA
    ditemukan & diperbaiki saat development: parsedate_to_datetime BISA
    return datetime naive (tanpa timezone) untuk string tanpa offset,
    dan membandingkan datetime naive vs aware di sort() Python akan
    CRASH (TypeError) -- dinormalisasi ke UTC kalau naive, supaya SEMUA
    item yang berhasil di-parse selalu timezone-aware dan aman
    dibandingkan satu sama lain di sorting.

    Returns None kalau gagal parse total -- item dengan tanggal tak
    terparse TETAP ditampilkan (ditaruh di akhir saat sorting, lihat
    fetch_news), BUKAN dibuang."""
    if not pub_date_str:
        return None
    try:
        parsed = parsedate_to_datetime(pub_date_str)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except (TypeError, ValueError):
        return None


async def _fetch_single_source(source: dict, keyword: str | None, limit: int) -> tuple[bool, list[dict]]:
    """Fetch & parse SATU sumber RSS. Returns (success, items)."""
    is_google = source.get("google", False)
    try:
        async with httpx.AsyncClient(timeout=NEWS_FETCH_TIMEOUT, follow_redirects=True) as client:
            response = await client.get(source["url"], headers=_FETCH_HEADERS)
            response.raise_for_status()

        root = ET.fromstring(response.content)
        items = root.findall(".//item")

        results = []
        for item in items:
            title_el   = item.find("title")
            link_el    = item.find("link")
            pubdate_el = item.find("pubDate")
            desc_el    = item.find("description")
            src_el     = item.find("source")   # ada di Google News RSS

            title    = title_el.text.strip()    if title_el    is not None and title_el.text    else ""
            link     = link_el.text.strip()     if link_el     is not None and link_el.text     else ""
            pub_date = pubdate_el.text.strip()  if pubdate_el  is not None and pubdate_el.text  else ""

            summary_raw = desc_el.text.strip() if desc_el is not None and desc_el.text else ""
            summary = re.sub(r"<[^>]+>", "", summary_raw).strip()

            # Google News: nama penerbit asli ada di <source>; judul sering
            # diakhiri " - Nama Penerbit" -- strip supaya tidak dobel.
            item_source = source["name"]
            if is_google and src_el is not None and src_el.text:
                item_source = src_el.text.strip()
                suffix = f" - {item_source}"
                if title.endswith(suffix):
                    title = title[: -len(suffix)]

            if not title or not link:
                continue

            if keyword:
                # BUG NYATA yang diperbaiki: dulu cuma substring mentah
                # (`keyword.upper() in haystack`), jadi cari berita kode
                # RAJA ikut menyangkut "KERAJAAN"/"RAJABASA" (RAJA
                # kebetulan substring di tengah kata lain). Kalau keyword
                # persis salah satu kode emiten dikenal, pakai
                # deteksi_emiten() yang SAMA dipakai tagging /news umum --
                # batas kata + guard kata umum (lihat
                # _KODE_RAWAN_FALSE_POSITIVE) -- supaya presisinya
                # konsisten di semua tempat, bukan cuma di tag "Saham
                # terkait". Keyword bebas (bukan kode emiten, mis. "IHSG
                # bursa saham") tetap substring biasa -- itu bukan lookup
                # ticker, tidak ada daftar kandidat buat dicocokkan.
                kw = keyword.strip().upper()
                haystack_text = title + " " + summary
                if kw in _load_emiten():
                    if not deteksi_emiten(haystack_text, kandidat_kode=[kw]):
                        continue
                elif kw not in haystack_text.upper():
                    continue

            results.append({
                "title": title,
                "link": link,
                "pub_date": pub_date,
                "summary": summary,
                "source": item_source,
                "kategori": "berita",
                "_parsed_date": _parse_pub_date(pub_date),
            })

            if len(results) >= limit:
                break

        return True, results

    except Exception as e:
        print(f"⚠️ Gagal fetch news dari {source['name']}: {type(e).__name__}: {e}")
        return False, []


def _normalisasi_judul(judul: str) -> str:
    """Normalisasi judul untuk perbandingan dedup: lowercase, buang
    tanda baca, rapatkan spasi. 'BBCA Cetak Laba!' -> 'bbca cetak laba'."""
    judul = judul.lower()
    judul = re.sub(r"[^a-z0-9 ]", " ", judul)
    return re.sub(r"\s+", " ", judul).strip()


def _deduplikasi(items: list[dict]) -> list[dict]:
    """Buang berita duplikat lintas sumber. Satu peristiwa (mis. laba
    emiten X) sering muncul di CNBC, CNN, DAN Detik dengan judul mirip --
    tanpa ini feed kelihatan spam berisi 3 berita "sama".

    Strategi: bandingkan judul ternormalisasi tiap item dengan item yang
    SUDAH disimpan. Kalau kemiripannya >= ambang, anggap duplikat dan
    SIMPAN yang ringkasannya lebih panjang (biasanya lebih informatif),
    sambil mencatat sumber tambahannya di field 'sumber_lain' untuk
    transparansi (user tetap tahu berita itu diliput beberapa portal).

    Item KETERBUKAAN INFORMASI IDX TIDAK pernah dianggap duplikat dari
    berita media (kategori beda) -- pengumuman resmi sengaja dipertahankan
    terpisah walau topiknya sama, karena nilainya beda (primer vs sekunder).
    """
    disimpan: list[dict] = []

    for item in items:
        norm = _normalisasi_judul(item.get("title", ""))
        if not norm:
            disimpan.append(item)
            continue

        duplikat_dari = None
        for kept in disimpan:
            # Jangan dedup lintas-kategori (berita media vs keterbukaan info)
            if kept.get("kategori") != item.get("kategori"):
                continue
            rasio = SequenceMatcher(None, norm, _normalisasi_judul(kept["title"])).ratio()
            if rasio >= DEDUP_SIMILARITY_THRESHOLD:
                duplikat_dari = kept
                break

        if duplikat_dari is None:
            disimpan.append(item)
        else:
            # Catat sumber tambahan untuk transparansi
            lain = duplikat_dari.setdefault("sumber_lain", [])
            if item.get("source") and item["source"] not in lain \
                    and item["source"] != duplikat_dari.get("source"):
                lain.append(item["source"])
            # Pertahankan yang ringkasannya lebih panjang/informatif. Ikut
            # timpa pub_date/_parsed_date bersamaan dengan title/link --
            # BUG NYATA yang diperbaiki: sebelumnya cuma title/summary/link
            # yang ditimpa, jadi tanggal yang ditampilkan bisa jadi milik
            # artikel sumber LAIN dari yang link-nya ditampilkan (mis. link
            # menuju artikel Detik tapi tanggalnya masih tanggal CNBC yang
            # ditemukan lebih dulu) -- sekarang seluruh field ikut sinkron
            # ke sumber yang dipertahankan.
            if len(item.get("summary", "")) > len(duplikat_dari.get("summary", "")):
                duplikat_dari["title"] = item.get("title", duplikat_dari.get("title", ""))
                duplikat_dari["summary"] = item.get("summary", "")
                if item.get("link"):
                    duplikat_dari["link"] = item["link"]
                duplikat_dari["pub_date"] = item.get("pub_date", duplikat_dari.get("pub_date", ""))
                duplikat_dari["_parsed_date"] = item.get("_parsed_date")

    return disimpan


async def fetch_news(keyword: str | None = None, limit: int = 8) -> list[dict] | None:
    """Download & parse RSS feed dari SEMUA sumber di NEWS_SOURCES
    PARALEL, gabung, urutkan berdasarkan tanggal publikasi TERBARU
    lintas semua sumber, potong ke limit. Opsional filter berdasarkan
    keyword (kode saham atau kata kunci bebas).

    keyword: kalau diisi, cuma return berita yang judul ATAU
    deskripsinya mengandung keyword ini (case-insensitive), dicek di
    MASING-MASING sumber sebelum digabung.

    Returns list of dict {'title','link','pub_date','summary','source'}
    terurut dari yang TERBARU (parse tanggal sungguhan, bukan cuma
    urutan asli per-feed). Returns None HANYA kalau SEMUA sumber gagal
    fetch total (network error dll) -- BUKAN list kosong, supaya caller
    bisa membedakan "tidak ada berita yang cocok keyword" (list kosong,
    semua sumber berhasil diakses tapi filter terlalu spesifik) dari
    "gagal ambil data sama sekali" (None, perlu pesan error berbeda)."""
    tasks = [_fetch_single_source(src, keyword, NEWS_PER_SOURCE_LIMIT) for src in NEWS_SOURCES]
    # Tambahkan keterbukaan informasi IDX sebagai sumber paralel (KONTRAK
    # return-nya sengaja dibuat sama: (success, items)). Kalau saklarnya
    # mati (ENABLE_IDX_DISCLOSURES=False), fungsi ini balik (True, []) --
    # tidak menambah apa-apa & tidak menggagalkan sumber lain.
    tasks.append(fetch_idx_disclosures(keyword, NEWS_PER_SOURCE_LIMIT))
    # return_exceptions=True: kalau SATU task melempar exception yang tak
    # tertangkap di dalamnya, JANGAN jatuhkan seluruh endpoint berita
    # (sebelumnya bisa bikin /api/news balas 500). Exception diperlakukan
    # sebagai sumber gagal (False, []), sumber lain tetap jalan.
    raw = await asyncio.gather(*tasks, return_exceptions=True)
    results_per_source = []
    for r in raw:
        if isinstance(r, Exception):
            print(f"⚠️ Sumber berita error tak terduga: {type(r).__name__}: {r}")
            results_per_source.append((False, []))
        else:
            results_per_source.append(r)

    any_source_succeeded = any(success for success, _ in results_per_source)
    if not any_source_succeeded:
        return None  # SEMUA sumber gagal fetch total

    all_items = []
    for success, items in results_per_source:
        all_items.extend(items)

    # Deduplikasi lintas sumber SEBELUM sorting & potong limit -- supaya
    # satu peristiwa yang diliput 3 portal tidak makan 3 slot di limit.
    all_items = _deduplikasi(all_items)

    # Urutkan berdasarkan tanggal publikasi SUNGGUHAN (terbaru duluan).
    # Item dengan tanggal tak terparse (None) ditaruh di AKHIR via
    # sentinel datetime.min YANG SUDAH UTC-aware (lihat _parse_pub_date
    # -- SEMUA tanggal yang berhasil di-parse SUDAH dinormalisasi jadi
    # timezone-aware juga, jadi sentinel ini AMAN dibandingkan, tidak
    # ada lagi campuran naive/aware yang bisa crash sort()).
    _MIN_DATE = datetime.min.replace(tzinfo=timezone.utc)
    all_items.sort(key=lambda x: x["_parsed_date"] or _MIN_DATE, reverse=True)

    # Buang field internal _parsed_date sebelum dikembalikan ke caller
    # (bukan bagian dari kontrak publik fungsi ini)
    final_items = []
    for item in all_items[:limit]:
        item_copy = {k: v for k, v in item.items() if k != "_parsed_date"}
        final_items.append(item_copy)

    # Tag emiten yang disebut di tiap berita (judul + ringkasan). Dilakukan
    # SETELAH potong limit supaya tidak mubazir men-tag item yang dibuang.
    final_items = tag_items(final_items)

    return final_items
