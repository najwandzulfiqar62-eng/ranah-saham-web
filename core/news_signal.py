# =========================
# NEWS x SINYAL TEKNIKAL
# =========================
# "Merangkai" bagian news dengan AI Score teknikal: untuk emiten yang
# DISEBUT di sebuah berita (hasil tagging di core/news_emiten.py),
# lampirkan kondisi teknikalnya SAAT INI (score 0-100, rating, sinyal).
# Sehingga feed berita tidak cuma "ada kabar soal BBCA", tapi "ada kabar
# soal BBCA, dan secara teknikal BBCA sekarang 🟢 72/100 (Akumulasi)".
#
# MEMANFAATKAN YANG SUDAH ADA, bukan bikin baru dari nol:
# - Daftar emiten yang disebut: dari field 'emiten' (core/news_emiten.py).
# - Skor teknikal: calculate_ai_score_from_df() di core/ai_score.py --
#   fungsi PERSIS yang dipakai /ranah & /airank, jadi angkanya KONSISTEN
#   lintas fitur (berita & /ranah tidak akan kasih skor beda untuk saham
#   yang sama di waktu sama).
# - Download data: async_download_many() di core/async_yf.py -- SUDAH
#   punya batching + retry + rate-limit (YF_BATCH_SIZE/DELAY), jadi
#   skoring banyak emiten sekaligus tidak membombardir Yahoo Finance.
#
# KENAPA TIDAK DI-ENRICH OTOMATIS DI fetch_news():
# Skoring = download data harga (lambat & kena rate-limit), beda sifat
# dari fetch RSS yang ringan. Kalau /news umum (tanpa kode) bisa menyentuh
# belasan emiten sekaligus -> mahal & lambat. Maka enrichment ini DIPANGGIL
# TERPISAH oleh handler, dan default-nya cuma untuk /news <KODE> (fokus 1
# saham, 1 download, relevan & murah). Lihat handlers/news_handlers.py.
#
# BATAS JUJUR: ini menempelkan kondisi teknikal di SAMPING berita, BUKAN
# mengklaim beritanya yang MENYEBABKAN kondisi teknikal itu. Korelasi
# waktu, bukan kausalitas. Jangan ditampilkan seolah "berita X bikin harga
# naik" -- yang benar "ada berita X; secara terpisah, teknikalnya begini".

import asyncio
from collections import Counter

from core.async_yf import async_download_many
from core.stock_data import fix_yf_columns
from core.ai_score import calculate_ai_score_from_df

# Cap jumlah emiten yang di-skor dalam satu panggilan enrichment, supaya
# /news umum (banyak emiten lintas berita) tidak memicu puluhan download.
MAX_EMITEN_TO_SCORE = 12
SIGNAL_PERIOD = "6mo"  # cukup utk MACD/RSI/MA50; MA200 opsional di ai_score


def _ringkas_sinyal(result: dict) -> dict:
    """Ambil HANYA field yang relevan untuk ditempel di berita -- tidak
    perlu seluruh dict ai_score yang besar."""
    return {
        "score": result["score"],
        "rating": result["rating"],
        "signal": result["signal"],            # emoji 🟢/🟡/🔴
        "recommendation": result["recommendation"],
        "change_1d": result["change_1d"],
        "price": result["price"],
    }


async def score_emiten(kode_list: list[str]) -> dict[str, dict]:
    """Download + hitung AI Score untuk daftar kode emiten (TANPA '.JK').

    Returns {KODE: sinyal_ringkas}. Emiten yang gagal di-download atau
    datanya tidak cukup (<50 hari) cukup TIDAK muncul di hasil -- TIDAK
    menggagalkan emiten lain (pola error-isolation yang sama dengan
    multi-sumber di core/news.py).
    """
    if not kode_list:
        return {}

    tickers = [k + ".JK" for k in kode_list]
    data_by_ticker = await async_download_many(tickers, period=SIGNAL_PERIOD, interval="1d")

    hasil: dict[str, dict] = {}
    for ticker, df in data_by_ticker.items():
        kode = ticker.replace(".JK", "")
        try:
            df = fix_yf_columns(df).dropna()
            result = calculate_ai_score_from_df(df)
            if result is None:  # data < 50 hari
                continue
            hasil[kode] = _ringkas_sinyal(result)
        except Exception as e:
            print(f"⚠️ Gagal skor {kode} untuk rangkai berita: {type(e).__name__}: {e}")
            continue

    return hasil


async def enrich_news_with_signals(items: list[dict],
                                   max_emiten: int = MAX_EMITEN_TO_SCORE) -> list[dict]:
    """Lampirkan AI Score teknikal ke emiten yang disebut di tiap berita.

    Setelah dipanggil, tiap item punya field 'sinyal': dict {KODE:
    sinyal_ringkas} HANYA untuk emiten yang berhasil di-skor. Emiten yang
    di-tag tapi gagal di-skor cukup absen dari 'sinyal' (item tetap tampil).

    Mengumpulkan kode unik lintas SEMUA item dulu (BBCA yang muncul di 3
    berita = 1 download saja), prioritaskan yang paling sering disebut,
    lalu potong ke max_emiten supaya hemat. Modifikasi & kembalikan list
    yang sama.
    """
    counter: Counter = Counter()
    for it in items:
        for kode in it.get("emiten", []):
            counter[kode] += 1

    kode_unik = [kode for kode, _ in counter.most_common(max_emiten)]
    skor_map = await score_emiten(kode_unik)

    for it in items:
        it["sinyal"] = {
            kode: skor_map[kode]
            for kode in it.get("emiten", [])
            if kode in skor_map
        }
    return items
