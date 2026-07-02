# =========================
# NEWS - EMITEN TAGGING
# =========================
# Mendeteksi kode emiten (ticker BEI) mana yang DISEBUT di sebuah berita,
# supaya /news bisa menampilkan "Saham terkait: BBCA, BMRI" per item dan
# filter per-saham jadi lebih tepat daripada sekadar substring mentah.
#
# KENAPA TERPISAH DARI core/news.py: fungsi ini murni teks-processing
# (tidak ada network), jadi BISA di-unit-test tanpa mock RSS sama sekali
# -- sama semangatnya dengan format_news_message() yang sengaja dipisah
# dari handler.
#
# SUMBER DAFTAR EMITEN: data/saham.xlsx (kolom 'Kode' & 'Nama
# Perusahaan'), file yang SAMA dipakai screener -- jadi tidak ada daftar
# ticker kedua yang bisa basi sendiri. Di-cache di memori seperti
# load_tickers() di core/stock_data.py (file Excel jarang berubah).
#
# KETERBATASAN YANG JUJUR DICATAT:
# - Matching ticker pakai BATAS KATA (\bKODE\b) supaya "BBCA" tidak
#   ikut nyangkut di kata lain. Tapi ada kode emiten yang KEBETULAN
#   kata umum (mis. "GOOD", "CARE", "NICE", "PURE", "DOID") -- ini bisa
#   FALSE POSITIVE kalau muncul sebagai kata biasa di berita. Risiko ini
#   diterima sadar; alternatifnya (butuh konteks "saham X") malah banyak
#   MISS. Untuk skripsi: cukup catat keterbatasan ini di bab analisis.
# - Nama perusahaan dicocokkan setelah dibuang suffix "Tbk." dan hanya
#   kalau cukup panjang (>= 6 huruf) supaya nama generik pendek tidak
#   over-match.
# - Ini BUKAN named-entity recognition -- ini heuristik kamus sederhana.
#   Jangan diklaim sebagai NLP di sidang; sebut apa adanya.

import re

import pandas as pd

from core.config import SAHAM_XLSX_PATH

# Cache: {KODE: nama_perusahaan_dinormalisasi}. Diisi saat pertama dipakai.
_emiten_cache: dict[str, str] | None = None

# Kode emiten yang KEBETULAN juga kata umum bahasa Indonesia/Inggris.
# Untuk kode-kode ini, JANGAN tag hanya dari kemunculan kata telanjang --
# wajib ada konteks (didahului "saham"/"emiten"/"$" atau diikuti ".JK").
# Daftar ini sengaja konservatif & bisa ditambah; lebih baik miss
# daripada banjir false positive yang bikin tag tidak dipercaya user.
_KODE_RAWAN_FALSE_POSITIVE = {
    "GOOD", "CARE", "NICE", "PURE", "DOID", "BEST", "HOPE", "LIFE",
    "RICH", "MARI", "SAME", "KING", "STAR", "DUTI", "RUNS", "DATA",
    # Ditemukan saat unit-test pakai saham.xlsx asli: ini kode emiten
    # SUNGGUHAN yang kebetulan kata umum bahasa Indonesia -> wajib konteks.
    "LABA", "NAIK", "TURUN", "BISA", "MASA", "PURI", "RAYA",
}


def _normalisasi_nama(nama: str) -> str:
    """Buang suffix umum & kapitalisasi supaya cocok dgn teks berita.

    'Astra Agro Lestari Tbk.' -> 'ASTRA AGRO LESTARI'
    """
    nama = nama.upper()
    nama = re.sub(r"\bTBK\.?\b", "", nama)
    nama = re.sub(r"\bPT\b", "", nama)
    nama = re.sub(r"[^A-Z0-9 ]", " ", nama)
    return re.sub(r"\s+", " ", nama).strip()


def _load_emiten() -> dict[str, str]:
    """Muat {KODE: nama_normalisasi} dari saham.xlsx, sekali lalu di-cache.

    Kalau file gagal dibaca, return dict KOSONG dengan warning jelas
    (bukan crash) -- tagging cuma jadi tidak aktif, berita tetap tampil.
    Pola sama dengan load_tickers(): kegagalan baca Excel TIDAK boleh
    menjatuhkan fitur lain.
    """
    global _emiten_cache
    if _emiten_cache is not None:
        return _emiten_cache

    try:
        df = pd.read_excel(SAHAM_XLSX_PATH)
        mapping = {}
        for _, row in df.iterrows():
            kode = str(row["Kode"]).strip().upper()
            nama = _normalisasi_nama(str(row.get("Nama Perusahaan", "")))
            if kode and kode != "NAN":
                mapping[kode] = nama
        _emiten_cache = mapping
        print(f"✅ Loaded {len(mapping)} emiten untuk tagging berita dari saham.xlsx")
    except Exception as e:
        print(f"⚠️ GAGAL load emiten untuk tagging berita: {type(e).__name__}: {e}")
        print("⚠️ Tagging emiten di /news NONAKTIF sementara (berita tetap tampil tanpa tag).")
        _emiten_cache = {}

    return _emiten_cache


def deteksi_emiten(teks: str, kandidat_kode: list[str] | None = None) -> list[str]:
    """Deteksi kode emiten yang disebut di `teks` (judul + ringkasan).

    Args:
        teks: gabungan judul & ringkasan berita.
        kandidat_kode: kalau diisi, HANYA cek kode-kode ini (lebih cepat,
            dipakai kalau sudah ada keyword/ticker spesifik). None =
            cek seluruh daftar emiten.

    Returns:
        List kode emiten unik yang terdeteksi, terurut sesuai kemunculan.
    """
    emiten = _load_emiten()
    if not emiten:
        return []

    teks_upper = teks.upper()
    kode_list = kandidat_kode if kandidat_kode is not None else list(emiten.keys())

    ditemukan: list[str] = []
    for kode in kode_list:
        if kode not in emiten:
            continue

        cocok = False

        if kode in _KODE_RAWAN_FALSE_POSITIVE:
            # Kode yang kebetulan kata umum: wajib ada konteks eksplisit,
            # dicek di teks_upper supaya tetap kena di judul ALL-CAPS.
            pola_konteks = [
                rf"\bSAHAM {kode}\b",
                rf"\bEMITEN {kode}\b",
                rf"\${kode}\b",
                rf"\b{kode}\.JK\b",
                rf"\b{kode}\b \(",      # "GOOD (" pola penyebutan emiten
            ]
            cocok = any(re.search(p, teks_upper) for p in pola_konteks)
        else:
            # Kode normal: match sebagai kata utuh & CASE-SENSITIVE pada
            # teks ASLI. Penting: berita menulis SAHAM-nya kapital ("LABA")
            # tapi kata biasanya huruf kecil ("laba") -- case-sensitive
            # inilah yang memisahkan ticker dari kata umum (bug nyata yang
            # ketahuan saat unit-test: "cetak laba" sempat ke-tag LABA).
            if re.search(rf"\b{re.escape(kode)}\b", teks):
                cocok = True

        # Cadangan: cocokkan nama perusahaan (kalau cukup panjang & khas)
        if not cocok:
            nama = emiten[kode]
            if len(nama) >= 6 and nama in teks_upper:
                cocok = True

        if cocok and kode not in ditemukan:
            ditemukan.append(kode)

    # Urutkan sesuai kemunculan pertama di teks (kode yang dicocokkan via
    # nama perusahaan, posisinya -1, ditaruh di akhir).
    ditemukan.sort(key=lambda k: (teks_upper.find(k) if teks_upper.find(k) >= 0 else 10**9))
    return ditemukan


def tag_items(items: list[dict]) -> list[dict]:
    """Tambahkan field 'emiten' (list kode) ke tiap item berita.

    Memodifikasi & mengembalikan list yang sama. Aman dipanggil meski
    daftar emiten gagal di-load (field 'emiten' jadi list kosong).
    """
    for item in items:
        teks = f"{item.get('title', '')} {item.get('summary', '')}"
        item["emiten"] = deteksi_emiten(teks)
    return items
