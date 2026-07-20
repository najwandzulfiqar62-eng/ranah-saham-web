# =========================
# WEB PUSH (notifikasi HP walau app tertutup)
# =========================
# Permintaan user: notifikasi tetap masuk ke HP walau app tidak dibuka.
# Ini butuh Web Push (VAPID) -- server MENDORONG pesan ke push service
# browser (FCM/Mozilla/dst), lalu service worker menampilkan notifikasi.
#
# Kunci VAPID DISIMPAN SEKALI di DB (tabel app_config) supaya STABIL antar
# restart server. Regenerate kunci = SEMUA langganan lama batal, jadi jangan
# pernah di-generate ulang selama masih ada subscriber. Endpoint langganan
# browser (fcm.googleapis.com dst) TIDAK bergantung URL ngrok -- jadi
# langganan tetap sah walau URL ngrok berubah tiap restart.
#
# Langganan mati (push service balas 404/410) dihapus otomatis saat kirim,
# supaya tabel tidak menumpuk endpoint basi.

import base64
import json

from core.database import get_db

# "sub" wajib ada di klaim VAPID (kontak developer, mailto/https).
_VAPID_SUB = "mailto:najwandzulfiqar62@gmail.com"
_ensured = False


def _ensure():
    global _ensured
    if _ensured:
        return
    with get_db() as c:
        c.execute("CREATE TABLE IF NOT EXISTS app_config (k TEXT PRIMARY KEY, v TEXT NOT NULL)")
        c.execute('''
            CREATE TABLE IF NOT EXISTS push_subscription (
                endpoint   TEXT PRIMARY KEY,
                p256dh     TEXT NOT NULL,
                auth       TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            )
        ''')
        # Thread forum yang diikuti tiap langganan push -- MIRROR server-side
        # dari peta client-side rs_forum_follows (localStorage), supaya balasan
        # forum baru bisa di-push WALAU app tertutup (permintaan user: "balasan
        # forum cepat"). Sebelum ini forum HANYA dicek via poll klien 45 detik
        # yang berhenti total saat tab tidak dibuka -- push forum tidak pernah
        # terjadi sama sekali kalau app tertutup. last_reply_id = baseline
        # (SAMA semantik dgn rs_forum_follows klien): balasan br sendiri yg baru
        # dikirim TIDAK memicu notif ke diri sendiri.
        c.execute('''
            CREATE TABLE IF NOT EXISTS push_forum_follow (
                endpoint      TEXT NOT NULL,
                thread_id     INTEGER NOT NULL,
                last_reply_id INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (endpoint, thread_id)
            )
        ''')
    _ensured = True


def _get_config(k):
    _ensure()
    with get_db() as c:
        r = c.execute("SELECT v FROM app_config WHERE k = ?", (k,)).fetchone()
    return r["v"] if r else None


def _set_config(k, v):
    _ensure()
    with get_db() as c:
        c.execute(
            "INSERT INTO app_config (k, v) VALUES (?, ?) "
            "ON CONFLICT(k) DO UPDATE SET v = excluded.v",
            (k, v),
        )


def _vapid():
    """Return (Vapid01 object SUDAH ter-load, application_server_key_b64url).
    Kunci di-generate SEKALI lalu disimpan sbg PEM di DB; pemanggilan
    berikutnya memuat ulang dari DB (stabil).

    BUG NYATA yang diperbaiki (laporan user: 5 langganan push tersimpan --
    termasuk Safari iOS & Windows, jadi client-side SUDAH benar -- tapi
    SEMUA gagal terkirim, "Belum ada perangkat terdaftar / gagal"):
    sebelumnya fungsi ini return PEM STRING (dgn header/footer
    "-----BEGIN PRIVATE KEY-----"), dan caller mengoper STRING itu langsung
    ke pywebpush.webpush(vapid_private_key=...). Saat diberi string,
    pywebpush internal memanggil py_vapid.Vapid.from_string(), yang
    mengasumsikan input itu base64url MENTAH (raw/DER), BUKAN PEM ber-armor
    -- decode base64 atas teks PEM (termasuk "-----BEGIN...", "-----END...")
    menghasilkan byte sampah, gagal parse ASN.1 ("invalid length") utk
    SEMUA pengiriman, tanpa terkecuali. Fix: return OBJEK Vapid01 yang
    SUDAH ter-load (bukan string PEM-nya) -- pywebpush.webpush() menerima
    objek py_vapid langsung (lihat signature: vapid_private_key: Vapid02 |
    str) dan memakainya apa adanya, tanpa re-parse string yang rawan salah
    format."""
    from py_vapid import Vapid01
    from cryptography.hazmat.primitives import serialization

    priv_pem = _get_config("vapid_private_pem")
    if not priv_pem:
        v = Vapid01()
        v.generate_keys()
        pem = v.private_pem()
        priv_pem = pem.decode() if isinstance(pem, (bytes, bytearray)) else pem
        _set_config("vapid_private_pem", priv_pem)

    v = Vapid01.from_pem(priv_pem.encode())
    raw = v.public_key.public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )
    appkey = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    return v, appkey


def public_key() -> str:
    """applicationServerKey (base64url) yang dipakai browser saat subscribe."""
    return _vapid()[1]


def save_subscription(sub: dict) -> bool:
    """Simpan/ubah langganan PushSubscription dari browser. Return False
    kalau bentuknya tidak lengkap (endpoint + keys.p256dh + keys.auth)."""
    _ensure()
    if not isinstance(sub, dict):
        return False
    endpoint = sub.get("endpoint")
    keys = sub.get("keys") or {}
    p256dh, auth = keys.get("p256dh"), keys.get("auth")
    if not (endpoint and p256dh and auth):
        return False
    with get_db() as c:
        c.execute(
            "INSERT INTO push_subscription (endpoint, p256dh, auth) VALUES (?, ?, ?) "
            "ON CONFLICT(endpoint) DO UPDATE SET p256dh = excluded.p256dh, auth = excluded.auth",
            (endpoint, p256dh, auth),
        )
    return True


def delete_subscription(endpoint: str):
    """Hapus langganan BESERTA follow forum-nya (cascade manual -- PRAGMA
    foreign_keys tidak diaktifkan di proyek ini, sama pola dgn
    core/forum.py::delete_thread)."""
    _ensure()
    with get_db() as c:
        c.execute("DELETE FROM push_forum_follow WHERE endpoint = ?", (endpoint,))
        c.execute("DELETE FROM push_subscription WHERE endpoint = ?", (endpoint,))


def sync_forum_follows(endpoint: str, follows: dict) -> bool:
    """Timpa SELURUH daftar thread yang diikuti `endpoint` dengan `follows`
    ({thread_id: last_reply_id}) -- full-replace, MIRROR persis peta
    localStorage klien (rs_forum_follows) yang jadi sumber kebenaran.
    Endpoint harus SUDAH terdaftar di push_subscription (kalau belum,
    langganan push-nya sendiri belum tersimpan -- jangan simpan follow
    forum utk endpoint yang tak dikenal)."""
    _ensure()
    with get_db() as c:
        exists = c.execute("SELECT 1 FROM push_subscription WHERE endpoint = ?", (endpoint,)).fetchone()
        if exists is None:
            return False
        c.execute("DELETE FROM push_forum_follow WHERE endpoint = ?", (endpoint,))
        rows = []
        for tid, last_id in (follows or {}).items():
            try:
                tid_i, last_i = int(tid), int(last_id or 0)
            except (TypeError, ValueError):
                continue
            if tid_i > 0:
                rows.append((endpoint, tid_i, last_i))
        if rows:
            c.executemany(
                "INSERT INTO push_forum_follow (endpoint, thread_id, last_reply_id) VALUES (?, ?, ?)",
                rows,
            )
    return True


def subscription_count() -> int:
    _ensure()
    with get_db() as c:
        r = c.execute("SELECT COUNT(*) AS n FROM push_subscription").fetchone()
    return r["n"] if r else 0


def _all_subscriptions():
    _ensure()
    with get_db() as c:
        rows = c.execute("SELECT endpoint, p256dh, auth FROM push_subscription").fetchall()
    return [dict(r) for r in rows]


def _send_one(priv, sub_row: dict, payload: str) -> str:
    """Kirim SATU push, return 'sent' | 'dead' (404/410, caller harus hapus
    langganannya) | 'failed' (transient, jangan dihapus). Dipakai bersama
    oleh send_to_all() (broadcast semua) dan send_to_endpoint()/
    check_forum_follows_and_push() (target spesifik).

    BUG NYATA yang diperbaiki (laporan user: "notif nya delay/ga langsung
    masuk"): pywebpush.webpush() DEFAULT ttl=0. Per RFC 8030, TTL=0 berarti
    "kirim SEKARANG atau BUANG" -- push service TIDAK antre/retry sama
    sekali kalau perangkat sedang tak terjangkau saat itu juga (layar mati,
    mode hemat baterai/Doze, jaringan putus sesaat -- kondisi yang SANGAT
    umum di HP). Notifikasi bukan "telat", tapi DIBUANG diam-diam, dan baru
    "kelihatan telat" saat user buka app lagi & lihat lewat poll biasa.
    ttl=14400 (4 jam) menyuruh push service MENGANTRE & coba lagi selama
    itu kalau perangkat belum terjangkau -- notifikasi menyusul begitu HP
    online lagi, bukan hilang. Header Urgency=high mendorong push service
    membangunkan perangkat lebih segera drpd dibatch dgn notifikasi
    prioritas rendah lain (RFC 8030 sec 5.3)."""
    from pywebpush import webpush, WebPushException

    info = {"endpoint": sub_row["endpoint"], "keys": {"p256dh": sub_row["p256dh"], "auth": sub_row["auth"]}}
    try:
        webpush(
            subscription_info=info,
            data=payload,
            vapid_private_key=priv,
            vapid_claims={"sub": _VAPID_SUB},
            timeout=10,
            ttl=14400,
            headers={"Urgency": "high"},
        )
        return "sent"
    except WebPushException as e:
        code = getattr(getattr(e, "response", None), "status_code", None)
        return "dead" if code in (404, 410) else "failed"
    except Exception:
        return "failed"


def send_to_all(title: str, body: str, url: str = "/", tag: str = "ranah") -> dict:
    """Kirim satu notifikasi push ke SEMUA langganan. SINKRON (blocking
    jaringan) -- caller (web/app.py) membungkusnya di asyncio.to_thread.
    Langganan yang sudah mati (404/410 dari push service) dihapus otomatis.
    Return ringkasan {total, sent, failed, removed}."""
    priv, _ = _vapid()
    payload = json.dumps({"title": title, "body": body, "url": url, "tag": tag})
    subs = _all_subscriptions()
    sent = failed = removed = 0
    for s in subs:
        result = _send_one(priv, s, payload)
        if result == "sent":
            sent += 1
        elif result == "dead":
            delete_subscription(s["endpoint"])
            removed += 1
        else:
            failed += 1
    return {"total": len(subs), "sent": sent, "failed": failed, "removed": removed}


def send_to_endpoint(endpoint: str, title: str, body: str, url: str = "/", tag: str = "ranah") -> str:
    """Kirim push ke SATU endpoint spesifik (bukan broadcast). Return
    'sent'/'dead'/'failed'/'unknown' (endpoint tak terdaftar). Endpoint mati
    dihapus otomatis (cascade follow forum-nya juga ikut lewat
    delete_subscription)."""
    _ensure()
    with get_db() as c:
        row = c.execute(
            "SELECT endpoint, p256dh, auth FROM push_subscription WHERE endpoint = ?", (endpoint,)
        ).fetchone()
    if row is None:
        return "unknown"
    priv, _ = _vapid()
    payload = json.dumps({"title": title, "body": body, "url": url, "tag": tag})
    result = _send_one(priv, dict(row), payload)
    if result == "dead":
        delete_subscription(endpoint)
    return result


def check_forum_follows_and_push() -> dict:
    """Bandingkan last_reply_id tersimpan thd balasan TERKINI (reuse
    core/forum.py::reply_counts_for_threads -- SATU query batch utk semua
    thread yang diikuti siapa pun, bukan N query per-langganan) -- kalau
    ada balasan baru, push ke endpoint itu SAJA (bukan broadcast, forum
    inherently per-thread/per-follower) & geser baseline. SINKRON, caller
    (web/app.py) membungkus di asyncio.to_thread. Murni query DB (TIDAK ada
    panggilan yfinance/jaringan berat lain) -- aman dipanggil sering (mis.
    tiap 30-45 detik) tanpa risiko rate-limit apa pun, beda total dgn
    siklus audit sinyal yang berat. Return {checked, pushed}."""
    from core.forum import reply_counts_for_threads

    _ensure()
    with get_db() as c:
        rows = [dict(r) for r in c.execute(
            "SELECT endpoint, thread_id, last_reply_id FROM push_forum_follow"
        ).fetchall()]
    if not rows:
        return {"checked": 0, "pushed": 0}

    thread_ids = list({r["thread_id"] for r in rows})
    info_by_tid = reply_counts_for_threads(thread_ids)

    pushed = 0
    for r in rows:
        info = info_by_tid.get(r["thread_id"]) or {}
        latest = info.get("latest_reply_id") or 0
        if latest and latest > r["last_reply_id"]:
            res = send_to_endpoint(
                r["endpoint"],
                "Ranah Saham — balasan forum",
                f"Ada balasan baru di pertanyaanmu (thread #{r['thread_id']})",
                "/",
                "reply",
            )
            if res == "sent":
                pushed += 1
            if res in ("sent", "failed"):
                # Geser baseline WALAU 'failed' (transient) -- push service down
                # sementara tidak boleh bikin notif yang SAMA menumpuk & dikirim
                # ulang tak berkesudahan begitu pulih; 'dead' TIDAK perlu
                # di-update krn baris follow-nya sudah ikut terhapus (endpoint
                # dibuang lewat delete_subscription di send_to_endpoint).
                with get_db() as c:
                    c.execute(
                        "UPDATE push_forum_follow SET last_reply_id = ? WHERE endpoint = ? AND thread_id = ?",
                        (latest, r["endpoint"], r["thread_id"]),
                    )
    return {"checked": len(rows), "pushed": pushed}
