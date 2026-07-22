# =========================
# PERINGATAN AKSI KORPORASI (CORPORATE ACTION)
# =========================
# FITUR BARU (permintaan user 2026-07-22): Audit Sinyal harus MEMPERINGATKAN
# kalau sebuah emiten baru saja / sedang mengalami aksi korporasi (stock split
# atau pembagian dividen), supaya sinyal tidak salah dibaca sebagai "trap".
#
# DUA KASUS NYATA yang jadi latar permintaan:
# - STOCK SPLIT (kasus RAJA, split 1:5 2026-07-16): harga tiba-tiba "turun"
#   ~80% dalam semalam -- itu murni perubahan SKALA harga, bukan rugi. Audit
#   SUDAH menahan kasus ekstrem ini via is_price_scale_anomaly (core/signal_
#   history.py, ambang -40%), TAPI itu reaktif & diam-diam; user mau tanda
#   EKSPLISIT.
# - DIVIDEND TRAP (kasus ERAA, ex-dividen 2026-07-08 Rp25): pada tanggal ex-
#   dividen harga turun kira-kira sebesar dividen. Penurunan ini biasanya
#   KECIL (beberapa %), JAUH di bawah ambang anomali split -0.4x -- jadi TIDAK
#   tertangkap guard split & BISA memicu SL palsu. Ini celah nyata yang
#   ditutup peringatan ini: kasih tahu user "penurunan sebagian karena
#   dividen, bukan murni rugi pasar".
#
# Sumber data: yfinance Ticker(...).dividends / .splits (terverifikasi tersedia
# & akurat utk emiten .JK). Di-ambil batch (yf.download actions=True) & di-cache
# di lapisan web/app.py -- modul INI murni fungsi (tanpa I/O jaringan), supaya
# gampang ditest & logika deteksinya terpisah dari fetch/cache.
#
# SIKAP JUJUR yang dipegang: peringatan ini hanya MEMBERI TAHU/menandai, TIDAK
# otomatis mengubah/menghapus status sinyal (mis. tidak diam-diam membatalkan
# SL_HIT yang mungkin memang sah). Konsisten dgn prinsip modul signal_history
# "jangan pernah mengarang/menyembunyikan track record" -- keputusan tetap di
# tangan user yang sekarang diberi informasinya.

import pandas as pd

# Aksi korporasi dianggap "relevan/masih hangat" kalau terjadi dalam N hari
# kalender terakhir -- cukup lebar utk menaungi horison audit sinyal
# (MAX_HOLD_DAYS = 20 hari BURSA ~= 28 hari kalender) supaya split/dividen yang
# jatuh SELAMA sebuah sinyal masih OPEN pasti ikut tertandai.
CORP_ACTION_WINDOW_DAYS = 30


def extract_recent_actions(df, window_days: int = CORP_ACTION_WINDOW_DAYS, now=None) -> list[dict]:
    """Dari OHLC df yang di-download dengan actions=True (punya kolom
    'Dividends' & 'Stock Splits'), ambil aksi korporasi NON-NOL dalam
    window_days hari terakhir. Return list {type, date, value} terurut
    tanggal TERBARU dulu. MURNI (tanpa I/O) -- gampang ditest dgn df sintetis.

    `now` bisa di-inject utk test deterministik (default: hari ini)."""
    if df is None or len(df) == 0:
        return []
    ref = pd.Timestamp(now).normalize() if now is not None else pd.Timestamp.now().normalize()
    cutoff = ref - pd.Timedelta(days=window_days)
    out = []

    def _scan(col_name, kind):
        if col_name not in df.columns:
            return
        for dt, v in df[col_name].items():
            try:
                val = float(v)
            except (TypeError, ValueError):
                continue
            # NaN LOLOS dari `val <= 0` (semua perbandingan NaN = False) -- WAJIB
            # ditolak eksplisit. Muncul nyata di jalur BATCH (async_download_many
            # menyelaraskan banyak ticker pada satu index tanggal, mengisi NaN di
            # kolom aksi utk tanggal yg ticker ini tak punya aksi).
            if val != val:  # NaN
                continue
            if val <= 0:
                continue
            # split value 1.0 = "tidak ada split" (beberapa sumber isi 1.0)
            if kind == "split" and val == 1.0:
                continue
            d = pd.Timestamp(dt).normalize()
            if cutoff <= d <= ref:
                out.append({"type": kind, "date": str(d.date()), "value": round(val, 4)})

    _scan("Dividends", "dividen")
    _scan("Stock Splits", "split")
    out.sort(key=lambda a: a["date"], reverse=True)
    return out


def build_warning(actions: list[dict]) -> dict | None:
    """Ringkas daftar aksi korporasi jadi objek peringatan siap tampil, atau
    None kalau tidak ada. Dipakai frontend utk badge + catatan di Audit Sinyal."""
    if not actions:
        return None
    has_div = any(a["type"] == "dividen" for a in actions)
    has_split = any(a["type"] == "split" for a in actions)
    parts = []
    for a in actions:
        if a["type"] == "dividen":
            parts.append(f"ex-dividen {a['date']} (Rp{a['value']:g})")
        else:
            parts.append(f"stock split {a['date']} (1:{a['value']:g})")
    if has_split:
        note = ("Skala harga berubah karena stock split -- penurunan besar itu "
                "ARTEFAK split, BUKAN rugi. Hati-hati salah baca sinyal.")
    else:
        note = ("Sebagian penurunan harga karena pembagian dividen (harga turun "
                "~sebesar dividen di tanggal ex), BUKAN murni rugi pasar -- "
                "waspada SL/entry palsu di sekitar tanggal itu.")
    return {
        "actions": actions,
        "has_dividen": has_div,
        "has_split": has_split,
        "summary": "; ".join(parts),
        "note": note,
    }
