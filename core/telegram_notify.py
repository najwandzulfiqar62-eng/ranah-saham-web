# =========================
# TELEGRAM NOTIFIER (opsional)
# =========================
# Project ini AWALNYA bot Telegram sebelum dipindah ke web (lihat komentar
# "migrasi dari main.py lama" di banyak modul core/) -- modul ini
# menghidupkan KEMBALI satu jalur notifikasi itu, KHUSUS untuk sinyal Top
# Pick/Audit Sinyal (BUKAN mengembalikan seluruh bot lama dengan command-
# command interaktifnya).
#
# NONAKTIF SECARA DEFAULT: kalau TELEGRAM_BOT_TOKEN atau TELEGRAM_CHAT_ID
# tidak diisi di environment, send_message() diam-diam return False tanpa
# error -- fail-open, konsisten dengan disiplin project ini (Redis/DB juga
# begitu). Pemilik deployment WAJIB membuat bot sendiri via @BotFather dan
# mengisi kedua env var itu sebelum notifikasi benar-benar terkirim.
#
# BAHASA PESAN sengaja deskriptif & tidak bombastis (bandingkan dengan
# "SIGNAL CONFIRMED — PROFIT! 🏆" ala kompetitor yang terasa jualan) --
# konsisten dengan prinsip "edukasi, bukan rekomendasi" di seluruh project.

import os

import httpx

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
_ENABLED = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)
_TIMEOUT = 10.0

# signal_history punya 3 sumber entry point independen (lihat core/
# signal_history.py) -- label ini dipakai di pesan notifikasi supaya user
# selalu tahu teori entry mana yang dimaksud, tidak tercampur.
_SOURCE_LABEL = {
    "TOP_PICK": "Top Pick (skor gabungan)",
    "MACD_CROSS": "MACD Histogram Cross (momentum)",
    "SMART_MONEY": "Smart Money (anomali volume)",
}


async def send_message(text: str) -> bool:
    """Kirim satu pesan teks ke chat/grup yang dikonfigurasi. Returns True
    kalau terkirim, False kalau GAGAL ATAU belum dikonfigurasi -- caller
    TIDAK PERLU cek _ENABLED sendiri sebelum memanggil, fungsi ini sudah
    fail-open (diam, bukan exception) di kedua kasus supaya kegagalan
    kirim notifikasi tidak pernah menjatuhkan alur utama (pencatatan/audit
    sinyal harus tetap sukses meski Telegram sedang bermasalah)."""
    if not _ENABLED:
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(url, json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            })
            return resp.status_code == 200
    except Exception as e:
        print(f"⚠️ Gagal kirim notifikasi Telegram: {type(e).__name__}: {e}")
        return False


def format_signal_new(sig: dict) -> str:
    """Format pesan utk sinyal yang baru dicatat (BUY atau SELL -- lihat
    sig['direction'], default 'BUY' utk source lama yang murni long-only),
    meniru struktur info kompetitor (entry/TP/SL) TAPI tanpa klaim broker-
    flow/asing yang datanya tidak kita punya secara legal/gratis.

    Tanda +/- pada TP/SL mengikuti ARAH HARGA (bukan untung/rugi): BUY
    untung kalau harga naik (TP="+", SL="-"), SELL untung kalau harga
    turun (TP="-", SL="+") -- supaya user paham APA yang akan terjadi
    pada harga, bukan cuma label "Target/Stop Loss" yang ambigu arahnya."""
    direction = sig.get("direction", "BUY")
    is_sell = direction == "SELL"
    tp_sign, sl_sign = ("-", "+") if is_sell else ("+", "-")
    lines = [
        f"🆕 <b>{sig['kode']}</b> — sinyal {direction} baru dicatat",
        f"Sumber: {_SOURCE_LABEL.get(sig.get('source', 'TOP_PICK'), sig.get('source', '-'))}",
        f"Entry: Rp{sig['entry_price']:,.0f}",
        f"Target TP: Rp{sig['tp_price']:,.0f} ({tp_sign}{sig['tp_pct']:.1f}%)",
        f"Stop Loss: Rp{sig['sl_price']:,.0f} ({sl_sign}{sig['sl_pct']:.1f}%)",
    ]
    if sig.get("pattern"):
        lines.append(f"Pola chart: {sig['pattern']}")
    if sig.get("confidence_score") is not None:
        lines.append(f"Skor Keyakinan: {sig['confidence_score']:.1f}/100")
    lines.append("Analisis teknikal otomatis (rule-based) untuk edukasi — bukan rekomendasi investasi. DYOR.")
    return "\n".join(lines)


def format_signal_tp_progress(sig: dict) -> str:
    """Format pesan utk TP1/TP2 tercapai TAPI posisi BELUM ditutup (lihat
    tp_level_hit di core/signal_history.py::audit_open_signals) -- beda
    dgn format_signal_resolved yang HANYA dipakai utk status akhir
    (TP_HIT/SL_HIT/EXPIRED). Permintaan user: "kena tp1 tandai, lanjut ke
    tp selanjutnya" -- jadi ini notifikasi progres, bukan penutupan."""
    level = sig.get("tp_level_hit")
    lines = [
        f"🎯 <b>{sig['kode']}</b> — Target TP{level} tercapai (masih OPEN)",
        f"Sumber: {_SOURCE_LABEL.get(sig.get('source', 'TOP_PICK'), sig.get('source', '-'))}",
        f"Entry Rp{sig['entry_price']:,.0f} → harga sekarang Rp{sig['price']:,.0f}",
        "Posisi tetap dipantau menuju target berikutnya, belum ditutup.",
        "Analisis teknikal otomatis (rule-based) untuk edukasi — bukan rekomendasi investasi. DYOR.",
    ]
    return "\n".join(lines)


def format_signal_resolved(sig: dict) -> str:
    """Format pesan utk sinyal yang baru SELESAI diaudit (TP_HIT/SL_HIT/
    EXPIRED). Bahasa jujur apa adanya -- SL_HIT ditampilkan sama terus
    terangnya dengan TP_HIT, tidak disembunyikan (kredibilitas track
    record butuh keduanya sama-sama transparan)."""
    status_label = {
        "TP_HIT": "Target tercapai",
        "SL_HIT": "Kena stop loss",
        "EXPIRED": "Kadaluarsa (20 hari bursa, belum tercapai TP/SL)",
    }.get(sig["status"], sig["status"])
    emoji = {"TP_HIT": "✅", "SL_HIT": "🛑", "EXPIRED": "⏳"}.get(sig["status"], "")
    ret = sig.get("return_pct")
    ret_txt = f"{ret:+.2f}%" if ret is not None else "-"
    tanggal = str(sig.get("recorded_at", ""))[:10]
    lines = [
        f"{emoji} <b>{sig['kode']}</b> — {status_label}",
        f"Sumber: {_SOURCE_LABEL.get(sig.get('source', 'TOP_PICK'), sig.get('source', '-'))}",
        f"Entry Rp{sig['entry_price']:,.0f} → Rp{sig['resolved_price']:,.0f} ({ret_txt})",
        f"Dicatat {tanggal} · selesai dalam {sig.get('days_to_resolve', '-')} hari",
        "Analisis teknikal otomatis (rule-based) untuk edukasi — bukan rekomendasi investasi. DYOR.",
    ]
    return "\n".join(lines)
