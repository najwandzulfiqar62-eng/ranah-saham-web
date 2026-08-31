"""Kontrak keamanan akses akun gratis + approval admin."""

import pytest


@pytest.fixture
def clean_access_db():
    from core.access import ensure_bootstrap_admin, ensure_access_tables
    from core.database import get_db

    ensure_access_tables()
    with get_db() as conn:
        conn.execute("DELETE FROM access_session")
        conn.execute("DELETE FROM access_user")
    ensure_bootstrap_admin()
    yield
    with get_db() as conn:
        conn.execute("DELETE FROM access_session")
        conn.execute("DELETE FROM access_user")


def test_access_requires_approved_account_and_admin_can_approve(client, clean_access_db):
    # Endpoint bisnis terkunci dari awal; layar login tidak sekadar kosmetik.
    assert client.get("/api/ihsg").status_code == 401

    # Screenshot PNG 1×1: bukti anggota kini wajib sebelum admin bisa approve.
    proof_png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\x0dIDATx\x9cc\xf8\xcf\xc0\xf0\x1f\x00\x05\x00\x01\xff\x89\x99=\x1d\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    registered = client.post("/api/access/register", data={
        "name": "Pengguna Baru",
        "email": "baru@example.com",
        "password": "password-pengguna-aman",
    }, files={"proof": ("bukti.png", proof_png, "image/png")})
    assert registered.status_code == 200

    # Sebelum persetujuan, password tepat pun belum dapat membuka aplikasi.
    pending_login = client.post("/api/access/login", json={
        "email": "baru@example.com", "password": "password-pengguna-aman",
    })
    assert pending_login.status_code == 403
    assert "menunggu" in pending_login.json()["detail"]

    admin_login = client.post("/api/access/login", json={
        "email": "admin-access-test@example.com", "password": "admin-access-test-password",
    })
    assert admin_login.status_code == 200
    pending = client.get("/api/access/admin/users?status=pending").json()["users"]
    assert len(pending) == 1

    approved = client.post(f"/api/access/admin/users/{pending[0]['id']}/approve")
    assert approved.status_code == 200
    client.post("/api/access/logout")

    approved_login = client.post("/api/access/login", json={
        "email": "baru@example.com", "password": "password-pengguna-aman",
    })
    assert approved_login.status_code == 200
    me = client.get("/api/access/me").json()["user"]
    assert me["email"] == "baru@example.com"
    assert me["status"] == "approved"
