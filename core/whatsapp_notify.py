# =========================
# BROADCAST SINYAL KE GRUP WHATSAPP
# =========================
# Transport + cursor SAJA -- membangun teks digest (sinyal baru + X-15) tetap
# di web/app.py karena butuh helper yang sudah ada di sana (_fetch_x15_today,
# _split_x15_items) dan core/signal_history.get_signal_notifications. Modul
# ini sengaja bodoh: kirim teks apa adanya ke sidecar wa-bot/ (Baileys, lihat
# README di situ) lewat HTTP, plus simpan "sampai mana sudah dikirim" supaya
# app utama tidak perlu tahu apa-apa soal WhatsApp.
#
# send_wa_text TIDAK PERNAH melempar exception ke pemanggil -- wa-bot belum
# di-pairing/down adalah keadaan NORMAL (setup awal, restart, dst), bukan
# alasan meruntuhkan loop background atau endpoint admin.

import httpx

from core.config import WA_BOT_URL, WA_BOT_SECRET
from core.database import get_db

_ensured = False


def _ensure():
    global _ensured
    if _ensured:
        return
    with get_db() as c:
        c.execute("CREATE TABLE IF NOT EXISTS app_config (k TEXT PRIMARY KEY, v TEXT NOT NULL)")
    _ensured = True


def _get_config(k: str) -> str | None:
    _ensure()
    with get_db() as c:
        r = c.execute("SELECT v FROM app_config WHERE k = ?", (k,)).fetchone()
    return r["v"] if r else None


def _set_config(k: str, v: str):
    _ensure()
    with get_db() as c:
        c.execute(
            "INSERT INTO app_config (k, v) VALUES (?, ?) "
            "ON CONFLICT(k) DO UPDATE SET v = excluded.v",
            (k, v),
        )


def get_last_signal_id() -> int | None:
    """None = belum pernah kirim sama sekali (baseline belum diset) --
    beda dgn 0, yang berarti "kirim dari awal riwayat" (tidak pernah kita
    inginkan, lihat catatan bootstrap di web/app.py::_build_wa_digest_text)."""
    v = _get_config("wa_last_signal_id")
    return int(v) if v is not None else None


def set_last_signal_id(signal_id: int):
    _set_config("wa_last_signal_id", str(signal_id))


def get_last_daily_sent_date() -> str | None:
    return _get_config("wa_last_daily_sent_date")


def set_last_daily_sent_date(date_str: str):
    _set_config("wa_last_daily_sent_date", date_str)


async def send_wa_text(text: str) -> bool:
    """Kirim teks ke grup WA lewat sidecar wa-bot. Return False (BUKAN
    exception) kalau WA_BOT_URL/SECRET belum diisi, wa-bot belum terhubung,
    atau request gagal apapun sebabnya -- caller (loop background/endpoint
    admin) cukup cek return value, tidak perlu try/except sendiri."""
    if not WA_BOT_URL or not WA_BOT_SECRET:
        return False
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            res = await client.post(
                f"{WA_BOT_URL}/send",
                json={"text": text},
                headers={"Authorization": f"Bearer {WA_BOT_SECRET}"},
            )
            res.raise_for_status()
            return bool(res.json().get("ok"))
    except Exception as e:
        print(f"⚠️ Gagal kirim WA broadcast: {type(e).__name__}: {e}")
        return False
