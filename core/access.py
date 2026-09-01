"""Akun akses gratis dengan persetujuan admin.

Password tidak pernah disimpan mentah. Sesi juga server-side: browser hanya
memegang token acak HttpOnly, sedangkan database menyimpan hash tokennya.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone

from core.config import ACCESS_ADMIN_EMAIL, ACCESS_ADMIN_PASSWORD
from core.database import get_db

SESSION_DAYS = 30
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _normalize_phone(value: str | None) -> str:
    """Normalisasi nomor WhatsApp Indonesia ke format +62xxxxxxxxxx."""
    digits = re.sub(r"\D", "", value or "")
    if digits.startswith("0"):
        digits = "62" + digits[1:]
    elif digits.startswith("8"):
        digits = "62" + digits
    if not digits.startswith("62") or not 10 <= len(digits) <= 15:
        raise ValueError("Nomor WhatsApp tidak valid. Gunakan nomor Indonesia aktif, mis. 0812xxxx.")
    return "+" + digits


def _hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P
    )
    return "scrypt${}${}${}${}${}".format(
        _SCRYPT_N,
        _SCRYPT_R,
        _SCRYPT_P,
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, n, r, p, salt, expected = stored.split("$")
        if algorithm != "scrypt":
            return False
        got = hashlib.scrypt(
            password.encode("utf-8"),
            salt=base64.urlsafe_b64decode(salt.encode("ascii")),
            n=int(n), r=int(r), p=int(p),
        )
        return hmac.compare_digest(got, base64.urlsafe_b64decode(expected.encode("ascii")))
    except (ValueError, TypeError):
        return False


def _public(row) -> dict:
    return {
        "id": int(row["id"]),
        "name": row["name"],
        "email": row["email"],
        "phone": row["phone"] if "phone" in row.keys() else None,
        "status": row["status"],
        "is_admin": bool(row["is_admin"]),
        "created_at": row["created_at"],
        "approved_at": row["approved_at"],
        "avatar_url": row["avatar_url"] if "avatar_url" in row.keys() else None,
        "bio": row["bio"] if "bio" in row.keys() else "",
        "has_proof": bool(row["proof_filename"]) if "proof_filename" in row.keys() else False,
        "has_google_login": bool(row["google_sub"]) if "google_sub" in row.keys() else False,
        "history_hidden": bool(row["history_hidden"]) if "history_hidden" in row.keys() else False,
    }


_ensured = False


def ensure_access_tables() -> None:
    global _ensured
    if _ensured:
        return
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS access_user (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending', 'approved', 'rejected')),
                is_admin INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                approved_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS access_session (
                token_hash TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES access_user(id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_access_user_status ON access_user(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_access_session_expiry ON access_session(expires_at)")
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(access_user)").fetchall()}
        if "avatar_url" not in cols:
            conn.execute("ALTER TABLE access_user ADD COLUMN avatar_url TEXT")
        if "bio" not in cols:
            conn.execute("ALTER TABLE access_user ADD COLUMN bio TEXT NOT NULL DEFAULT ''")
        if "proof_filename" not in cols:
            conn.execute("ALTER TABLE access_user ADD COLUMN proof_filename TEXT")
        if "google_sub" not in cols:
            conn.execute("ALTER TABLE access_user ADD COLUMN google_sub TEXT")
        if "history_hidden" not in cols:
            conn.execute("ALTER TABLE access_user ADD COLUMN history_hidden INTEGER NOT NULL DEFAULT 0")
        if "phone" not in cols:
            conn.execute("ALTER TABLE access_user ADD COLUMN phone TEXT")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_access_user_google_sub ON access_user(google_sub) WHERE google_sub IS NOT NULL")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_access_user_phone ON access_user(phone) WHERE phone IS NOT NULL")
    _ensured = True


def ensure_bootstrap_admin() -> bool:
    """Pastikan email admin dari environment selalu menjadi admin aktif.

    Kasus penting: pemilik web bisa saja sudah lebih dulu mendaftarkan email
    yang sama lewat formulir publik. Jangan biarkan baris `pending` itu
    menghalangi bootstrap admin; konfigurasi server harus menjadi sumber
    kebenaran untuk akun pemilik.
    """
    ensure_access_tables()
    if not ACCESS_ADMIN_EMAIL or not ACCESS_ADMIN_PASSWORD:
        return False
    with get_db() as conn:
        row = conn.execute("SELECT id FROM access_user WHERE email = ?", (ACCESS_ADMIN_EMAIL,)).fetchone()
        password_hash = _hash_password(ACCESS_ADMIN_PASSWORD)
        if row is None:
            conn.execute(
                """INSERT INTO access_user
                   (name, email, password_hash, status, is_admin, created_at, approved_at)
                   VALUES (?, ?, ?, 'approved', 1, ?, ?)""",
                ("Admin Ranah Saham", ACCESS_ADMIN_EMAIL, password_hash, _now(), _now()),
            )
        else:
            conn.execute(
                """UPDATE access_user
                   SET password_hash = ?, status = 'approved', is_admin = 1,
                       approved_at = COALESCE(approved_at, ?)
                   WHERE id = ?""",
                (password_hash, _now(), row["id"]),
            )
    return True


def admin_is_configured() -> bool:
    return bool(ACCESS_ADMIN_EMAIL and ACCESS_ADMIN_PASSWORD)


def register_user(name: str, email: str, password: str, proof_filename: str | None = None, phone: str | None = None) -> dict:
    ensure_access_tables()
    name = " ".join((name or "").strip().split())
    email = (email or "").strip().lower()
    phone = _normalize_phone(phone)
    if not 2 <= len(name) <= 60:
        raise ValueError("Nama harus terdiri dari 2–60 karakter.")
    if len(email) > 254 or "@" not in email or email.startswith("@") or email.endswith("@"):
        raise ValueError("Alamat email tidak valid.")
    if not 10 <= len(password or "") <= 128:
        raise ValueError("Password minimal 10 karakter.")
    if not proof_filename:
        raise ValueError("Bukti anggota grup WhatsApp Ranah Invest wajib diunggah.")
    with get_db() as conn:
        exists = conn.execute("SELECT id, status, is_admin, proof_filename FROM access_user WHERE email = ?", (email,)).fetchone()
        phone_owner = conn.execute("SELECT id FROM access_user WHERE phone = ?", (phone,)).fetchone()
        if phone_owner and (not exists or phone_owner["id"] != exists["id"]):
            raise ValueError("Nomor WhatsApp ini sudah terdaftar pada akun lain.")
        if exists:
            # Penolakan bukan blokir permanen: pemohon boleh memperbaiki
            # screenshot bukti lalu mengirim pendaftaran ulang dengan email
            # yang sama. Akun admin tidak pernah boleh tersentuh jalur ini.
            if exists["status"] == "rejected" and not exists["is_admin"]:
                old_proof = exists["proof_filename"]
                conn.execute(
                    """UPDATE access_user
                       SET name = ?, password_hash = ?, status = 'pending',
                           created_at = ?, approved_at = NULL, proof_filename = ?, phone = ?, history_hidden = 0
                       WHERE id = ?""",
                    (name, _hash_password(password), _now(), proof_filename, phone, exists["id"]),
                )
                return {
                    "message": "Pendaftaran ulang diterima. Bukti baru akan diperiksa admin.",
                    "_old_proof_filename": old_proof,
                }
            raise ValueError("Email ini sudah terdaftar. Silakan masuk atau tunggu persetujuan admin.")
        conn.execute(
            """INSERT INTO access_user (name, email, phone, password_hash, status, is_admin, created_at, proof_filename)
               VALUES (?, ?, ?, ?, 'pending', 0, ?, ?)""",
            (name, email, phone, _hash_password(password), _now(), proof_filename),
        )
    return {"message": "Pendaftaran diterima. Tunggu persetujuan admin sebelum masuk."}


def authenticate(identifier: str, password: str) -> tuple[dict | None, str | None]:
    ensure_access_tables()
    identifier = (identifier or "").strip()
    email = identifier.lower() if "@" in identifier else None
    try:
        phone = None if email else _normalize_phone(identifier)
    except ValueError:
        return None, "Email/nomor HP atau password tidak tepat."
    with get_db() as conn:
        row = conn.execute("SELECT * FROM access_user WHERE email = ? OR phone = ?", (email, phone)).fetchone()
        if row is None or not verify_password(password or "", row["password_hash"]):
            return None, "Email/nomor HP atau password tidak tepat."
        user = _public(row)
        if user["status"] != "approved":
            return None, "Akunmu masih menunggu persetujuan admin."
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        expires = (datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)).isoformat(timespec="seconds")
        conn.execute("DELETE FROM access_session WHERE expires_at <= ?", (_now(),))
        conn.execute(
            "INSERT INTO access_session (token_hash, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)",
            (token_hash, user["id"], expires, _now()),
        )
    return user, token


def get_session_user(token: str | None, include_pending: bool = False) -> dict | None:
    if not token:
        return None
    ensure_access_tables()
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with get_db() as conn:
        row = conn.execute(
            """SELECT u.* FROM access_session s JOIN access_user u ON u.id = s.user_id
               WHERE s.token_hash = ? AND s.expires_at > ?""",
            (token_hash, _now()),
        ).fetchone()
        if row is None:
            return None
        user = _public(row)
        return user if include_pending or user["status"] == "approved" else None


def revoke_session(token: str | None) -> None:
    if not token:
        return
    ensure_access_tables()
    with get_db() as conn:
        conn.execute("DELETE FROM access_session WHERE token_hash = ?", (hashlib.sha256(token.encode("utf-8")).hexdigest(),))


def update_profile(user_id: int, name: str, bio: str | None = None, avatar_url: str | None = None, phone: str | None = None) -> dict:
    ensure_access_tables()
    name = " ".join((name or "").strip().split())
    if not 2 <= len(name) <= 60:
        raise ValueError("Nama harus terdiri dari 2–60 karakter.")
    bio = " ".join((bio or "").strip().split())
    if len(bio) > 180:
        raise ValueError("Bio maksimal 180 karakter.")
    avatar_url = (avatar_url or "").strip() or None
    if avatar_url and (len(avatar_url) > 2048 or not avatar_url.startswith(("https://", "http://", "/profile_uploads/"))):
        raise ValueError("Lokasi foto profil tidak valid.")
    phone = _normalize_phone(phone)
    with get_db() as conn:
        owner = conn.execute("SELECT id FROM access_user WHERE phone = ? AND id != ?", (phone, user_id)).fetchone()
        if owner:
            raise ValueError("Nomor WhatsApp ini sudah terdaftar pada akun lain.")
        conn.execute("UPDATE access_user SET name = ?, bio = ?, avatar_url = ?, phone = ? WHERE id = ?", (name, bio, avatar_url, phone, user_id))
        row = conn.execute("SELECT * FROM access_user WHERE id = ?", (user_id,)).fetchone()
    return _public(row)


def create_session_for_user(user_id: int) -> str:
    ensure_access_tables()
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    expires = (datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)).isoformat(timespec="seconds")
    with get_db() as conn:
        conn.execute("DELETE FROM access_session WHERE expires_at <= ?", (_now(),))
        conn.execute("INSERT INTO access_session (token_hash, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)", (token_hash, user_id, expires, _now()))
    return token


def upsert_google_user(google_sub: str, email: str, name: str, avatar_url: str | None) -> dict:
    """Link akun Google terverifikasi ke akun lokal berdasarkan sub/email."""
    ensure_access_tables()
    email = (email or "").strip().lower()
    name = " ".join((name or "").strip().split())[:60] or email.split("@", 1)[0]
    with get_db() as conn:
        row = conn.execute("SELECT * FROM access_user WHERE google_sub = ?", (google_sub,)).fetchone()
        if row is None:
            row = conn.execute("SELECT * FROM access_user WHERE email = ?", (email,)).fetchone()
        if row is None:
            conn.execute(
                """INSERT INTO access_user (name, email, password_hash, status, is_admin, created_at, google_sub, avatar_url)
                   VALUES (?, ?, 'google-only', 'pending', 0, ?, ?, ?)""",
                (name, email, _now(), google_sub, avatar_url),
            )
            row = conn.execute("SELECT * FROM access_user WHERE email = ?", (email,)).fetchone()
        else:
            conn.execute("UPDATE access_user SET google_sub = ?, avatar_url = COALESCE(avatar_url, ?) WHERE id = ?", (google_sub, avatar_url, row["id"]))
            row = conn.execute("SELECT * FROM access_user WHERE id = ?", (row["id"],)).fetchone()
    return _public(row)


def list_users(status: str = "pending") -> list[dict]:
    ensure_access_tables()
    if status not in {"pending", "approved", "rejected", "all"}:
        raise ValueError("Status pengguna tidak dikenal.")
    query = "SELECT * FROM access_user"
    params: tuple = ()
    if status == "all":
        # Antrean selalu perlu terlihat; keputusan lama yang disembunyikan
        # admin tidak perlu memenuhi panel riwayat lagi.
        query += " WHERE status = 'pending' OR history_hidden = 0"
    elif status == "pending":
        query += " WHERE status = ?"
        params = (status,)
    else:
        query += " WHERE status = ? AND history_hidden = 0"
        params = (status,)
    query += " ORDER BY created_at DESC"
    with get_db() as conn:
        return [_public(row) for row in conn.execute(query, params).fetchall()]


def set_user_status(user_id: int, status: str) -> dict | None:
    ensure_access_tables()
    if status not in {"approved", "rejected"}:
        raise ValueError("Status pengguna tidak valid.")
    with get_db() as conn:
        if status == "approved":
            existing = conn.execute("SELECT proof_filename FROM access_user WHERE id = ?", (user_id,)).fetchone()
            if not existing or not existing["proof_filename"]:
                raise ValueError("Bukti anggota grup WhatsApp Ranah Invest belum diunggah.")
        conn.execute(
            "UPDATE access_user SET status = ?, approved_at = ?, history_hidden = 0 WHERE id = ? AND is_admin = 0",
            (status, _now() if status == "approved" else None, user_id),
        )
        row = conn.execute("SELECT * FROM access_user WHERE id = ?", (user_id,)).fetchone()
        return _public(row) if row else None


def revoke_user_approval(user_id: int) -> dict | None:
    """Cabut akses tanpa menghapus akun; akun kembali ke antrean approval."""
    ensure_access_tables()
    with get_db() as conn:
        conn.execute(
            "UPDATE access_user SET status = 'pending', approved_at = NULL WHERE id = ? AND is_admin = 0 AND status = 'approved'",
            (user_id,),
        )
        row = conn.execute("SELECT * FROM access_user WHERE id = ?", (user_id,)).fetchone()
        return _public(row) if row else None


def delete_access_history_user(user_id: int) -> dict | None:
    """Sembunyikan keputusan lama dari riwayat admin, tanpa menghapus akun.

    Antrean aktif sengaja tidak bisa dihapus lewat fungsi ini; admin harus
    memilih Setujui atau Tolak dulu. Akun admin juga selalu dilindungi.
    Ini sengaja hanya mengatur penanda tampilan. Kredensial, sesi, dan bukti
    anggota tetap utuh sehingga anggota yang sudah disetujui tetap dapat masuk.
    """
    ensure_access_tables()
    with get_db() as conn:
        row = conn.execute("SELECT * FROM access_user WHERE id = ?", (user_id,)).fetchone()
        if row is None or row["is_admin"] or row["status"] == "pending":
            return None
        conn.execute("UPDATE access_user SET history_hidden = 1 WHERE id = ?", (user_id,))
        row = conn.execute("SELECT * FROM access_user WHERE id = ?", (user_id,)).fetchone()
    return _public(row)


def get_proof_filename(user_id: int) -> str | None:
    ensure_access_tables()
    with get_db() as conn:
        row = conn.execute("SELECT proof_filename FROM access_user WHERE id = ?", (user_id,)).fetchone()
    return row["proof_filename"] if row and row["proof_filename"] else None


def update_proof_filename(user_id: int, proof_filename: str) -> dict | None:
    ensure_access_tables()
    with get_db() as conn:
        conn.execute("UPDATE access_user SET proof_filename = ? WHERE id = ? AND status = 'pending'", (proof_filename, user_id))
        row = conn.execute("SELECT * FROM access_user WHERE id = ?", (user_id,)).fetchone()
    return _public(row) if row else None
