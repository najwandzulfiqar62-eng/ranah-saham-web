# =========================
# NEWS - KETERBUKAAN INFORMASI IDX
# =========================
# Adapter untuk menarik pengumuman / keterbukaan informasi resmi dari
# Bursa Efek Indonesia (idx.co.id) -- aksi korporasi, dividen, RUPS,
# publikasi laporan keuangan, dll. Ini sumber PRIMER (langsung dari
# bursa), beda sifat dari RSS media di core/news.py yang sekunder
# (jurnalistik).
#
# ‼️ STATUS: NONAKTIF DEFAULT (ENABLE_IDX_DISCLOSURES = False). Aktifkan
#    SENDIRI hanya SETELAH membaca 3 catatan jujur di bawah. Ini SENGAJA
#    tidak dinyalakan diam-diam, supaya konsisten dengan disiplin di
#    core/news.py: sumber cuma dipakai kalau sudah DIVERIFIKASI bisa
#    diakses langsung, bukan diasumsikan.
#
# CATATAN 1 -- BELUM DIVERIFIKASI DI SINI:
#    Endpoint di bawah TIDAK bisa diverifikasi dari environment tempat
#    kode ini dirakit (akses keluar ke idx.co.id diblokir di sana). Jadi
#    BERBEDA dari 3 sumber RSS yang sudah di-fetch-test langsung. Kamu
#    WAJIB jalankan & cek sendiri di mesinmu sebelum mengandalkannya.
#    IDX juga kerap mengubah struktur endpoint internalnya tanpa
#    pengumuman -- kalau hasilnya kosong, kemungkinan besar endpoint /
#    nama field berubah, bukan tidak ada data.
#
# CATATAN 2 -- LISENSI / ToS (PENTING untuk skripsi):
#    Syarat penggunaan situs BEI MELARANG web scraping/crawling, dan
#    penggunaan non-komersial hanya boleh dengan mencantumkan sumber
#    lengkap + tanggal akses. Endpoint JSON di bawah adalah endpoint
#    INTERNAL situs (bukan API publik resmi yang dibuka untuk umum --
#    API resmi BEI sifatnya berlangganan/berbayar). Untuk prototipe
#    skripsi non-komersial dengan atribusi ini lazimnya wilayah abu-abu
#    yang ditoleransi, TAPI:
#      - JANGAN klaim ini "API resmi IDX" di laporan/sidang.
#      - Cantumkan atribusi "Sumber: Keterbukaan Informasi BEI,
#        diakses <tanggal>" tiap kali menampilkannya.
#      - Beri jeda antar-request & jangan polling agresif.
#    Pertimbangkan: untuk skripsi, sumber RSS media (yang memang
#    disediakan publisher untuk disindikasi) posisinya jauh lebih aman
#    dipertanggungjawabkan daripada scraping endpoint internal.
#
# CATATAN 3 -- HEADLINE vs DOKUMEN:
#    Pengumuman IDX seringnya cuma judul + tautan ke PDF. Bot ini HANYA
#    menampilkan judul + tautan (tidak mengunduh/parse isi PDF), sama
#    seperti kebijakan RSS: tampilkan headline, jangan reproduksi isi.

import asyncio
from datetime import datetime, timezone

import httpx

# ---- SAKLAR UTAMA ----
ENABLE_IDX_DISCLOSURES = False  # set True SETELAH baca catatan & verifikasi sendiri

# Endpoint internal idx.co.id untuk pengumuman saham. PERLU DIVERIFIKASI
# & kemungkinan perlu disesuaikan (lihat CATATAN 1). Disimpan sbg konstanta
# supaya gampang diganti tanpa mengubah logika.
IDX_ANNOUNCEMENT_URL = "https://www.idx.co.id/primary/NewsAnnouncement/GetAnnouncement"
IDX_FETCH_TIMEOUT = 12.0
IDX_DEFAULT_PARAMS = {
    "indexFrom": 0,
    "pageSize": 20,
    "dateFrom": "",
    "dateTo": "",
    "lang": "id",
    "keyword": "",
}


def _parse_idx_date(raw: str):
    """Coba beberapa format tanggal yang lazim dipakai IDX -> datetime
    UTC-aware (supaya AMAN diurutkan bareng item RSS di core/news.py,
    yang juga menormalkan semua tanggal jadi aware). Return None kalau
    gagal -- item tetap dipakai, ditaruh di akhir saat sorting."""
    if not raw:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d %b %Y %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(raw.strip()[:19], fmt)
            return dt.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue
    return None


async def fetch_idx_disclosures(keyword: str | None = None, limit: int = 15) -> tuple[bool, list[dict]]:
    """Tarik pengumuman keterbukaan informasi dari IDX.

    Mengembalikan (success, items) -- KONTRAK SAMA dengan
    _fetch_single_source() di core/news.py supaya bisa digabung mulus ke
    pipeline yang sudah ada (gather + dedup + sort). success=False hanya
    kalau fetch/parse gagal total; success=True items=[] kalau hasil
    kosong tapi request berhasil.

    Tiap item dikembalikan dalam SKEMA YANG SAMA dengan item RSS:
    {'title','link','pub_date','summary','source','_parsed_date'} +
    'kategori'='keterbukaan_informasi' (penanda supaya handler bisa
    menampilkannya beda dari berita media biasa).
    """
    if not ENABLE_IDX_DISCLOSURES:
        # Belum diaktifkan user -- diam saja, jangan ganggu sumber lain.
        return True, []

    try:
        params = dict(IDX_DEFAULT_PARAMS)
        if keyword:
            params["keyword"] = keyword
        params["pageSize"] = max(limit, params["pageSize"])

        async with httpx.AsyncClient(timeout=IDX_FETCH_TIMEOUT, follow_redirects=True) as client:
            headers = {
                "User-Agent": "Mozilla/5.0 (compatible; RanahSahamBot/1.0)",
                "Accept": "application/json",
            }
            resp = await client.get(IDX_ANNOUNCEMENT_URL, params=params, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        # Struktur respons IDX bisa berubah -- coba beberapa kemungkinan
        # lokasi list pengumuman secara defensif.
        rows = (
            data.get("Replies")
            or data.get("Items")
            or data.get("data")
            or (data if isinstance(data, list) else [])
        )

        results = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            title = (row.get("JudulPengumuman") or row.get("Title")
                     or row.get("judul") or "").strip()
            link = (row.get("Url") or row.get("Link")
                    or row.get("attachments") or "").strip()
            raw_date = (row.get("TglPengumuman") or row.get("PublishDate")
                        or row.get("tanggal") or "")
            kode = (row.get("KodeEmiten") or row.get("Kode") or "").strip()

            if not title:
                continue

            summary = f"Keterbukaan informasi" + (f" — {kode}" if kode else "")

            results.append({
                "title": title,
                "link": link,
                "pub_date": str(raw_date),
                "summary": summary,
                "source": "IDX (Keterbukaan Informasi)",
                "kategori": "keterbukaan_informasi",
                "_parsed_date": _parse_idx_date(str(raw_date)),
            })
            if len(results) >= limit:
                break

        return True, results

    except Exception as e:
        print(f"⚠️ Gagal fetch keterbukaan informasi IDX: {type(e).__name__}: {e}")
        print("   (Cek IDX_ANNOUNCEMENT_URL — endpoint internal IDX sering berubah. "
              "Lihat catatan di core/news_idx.py)")
        return False, []
