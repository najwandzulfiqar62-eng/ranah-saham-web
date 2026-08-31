"""Akun akses gratis dengan persetujuan admin.

Password tidak pernah disimpan mentah. Sesi juga server-side: browser hanya
memegang token acak HttpOnly, sedangkan database menyimpan hash tokennya.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
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
        "status": row["status"],
        "is_admin": bool(row["is_admin"]),
        "created_at": row["created_at"],
        "approved_at": row["approved_at"],
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


def register_user(name: str, email: str, password: str) -> dict:
    ensure_access_tables()
    name = " ".join((name or "").strip().split())
    email = (email or "").strip().lower()
    if not 2 <= len(name) <= 60:
        raise ValueError("Nama harus terdiri dari 2–60 karakter.")
    if len(email) > 254 or "@" not in email or email.startswith("@") or email.endswith("@"):
        raise ValueError("Alamat email tidak valid.")
    if not 10 <= len(password or "") <= 128:
        raise ValueError("Password minimal 10 karakter.")
    with get_db() as conn:
        exists = conn.execute("SELECT 1 FROM access_user WHERE email = ?", (email,)).fetchone()
        if exists:
            raise ValueError("Email ini sudah terdaftar. Silakan masuk atau tunggu persetujuan admin.")
        conn.execute(
            """INSERT INTO access_user (name, email, password_hash, status, is_admin, created_at)
               VALUES (?, ?, ?, 'pending', 0, ?)""",
            (name, email, _hash_password(password), _now()),
        )
    return {"message": "Pendaftaran diterima. Tunggu persetujuan admin sebelum masuk."}


def authenticate(email: str, password: str) -> tuple[dict | None, str | None]:
    ensure_access_tables()
    email = (email or "").strip().lower()
    with get_db() as conn:
        row = conn.execute("SELECT * FROM access_user WHERE email = ?", (email,)).fetchone()
        if row is None or not verify_password(password or "", row["password_hash"]):
            return None, "Email atau password tidak tepat."
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


def get_session_user(token: str | None) -> dict | None:
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
        return user if user["status"] == "approved" else None


def revoke_session(token: str | None) -> None:
    if not token:
        return
    ensure_access_tables()
    with get_db() as conn:
        conn.execute("DELETE FROM access_session WHERE token_hash = ?", (hashlib.sha256(token.encode("utf-8")).hexdigest(),))


def list_users(status: str = "pending") -> list[dict]:
    ensure_access_tables()
    if status not in {"pending", "approved", "rejected", "all"}:
        raise ValueError("Status pengguna tidak dikenal.")
    query = "SELECT * FROM access_user"
    params: tuple = ()
    if status != "all":
        query += " WHERE status = ?"
        params = (status,)
    query += " ORDER BY created_at DESC"
    with get_db() as conn:
        return [_public(row) for row in conn.execute(query, params).fetchall()]


def set_user_status(user_id: int, status: str) -> dict | None:
    ensure_access_tables()
    if status not in {"approved", "rejected"}:
        raise ValueError("Status pengguna tidak valid.")
    with get_db() as conn:
        conn.execute(
            "UPDATE access_user SET status = ?, approved_at = ? WHERE id = ? AND is_admin = 0",
            (status, _now() if status == "approved" else None, user_id),
        )
        row = conn.execute("SELECT * FROM access_user WHERE id = ?", (user_id,)).fetchone()
        return _public(row) if row else None
