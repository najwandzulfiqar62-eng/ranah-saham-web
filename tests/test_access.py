"""Kontrak keamanan akses akun gratis + approval admin."""

import pytest


@pytest.fixture
def clean_access_db():
    from core.access import ensure_bootstrap_admin, ensure_access_tables, invalidate_session_cache
    from core.database import get_db

    ensure_access_tables()
    with get_db() as conn:
        conn.execute("DELETE FROM access_session")
        conn.execute("DELETE FROM access_user")
    # Baris dihapus lewat SQL langsung, jadi cache sesi di memori TIDAK ikut
    # tahu -- tanpa ini sisa entri dari tes sebelumnya bisa bocor ke tes lain.
    invalidate_session_cache()
    ensure_bootstrap_admin()
    yield
    with get_db() as conn:
        conn.execute("DELETE FROM access_session")
        conn.execute("DELETE FROM access_user")
    invalidate_session_cache()


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
        "phone": "081234567890",
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
        "login": "081234567890", "password": "password-pengguna-aman",
    })
    assert approved_login.status_code == 200
    me = client.get("/api/access/me").json()["user"]
    assert me["email"] == "baru@example.com"
    assert me["status"] == "approved"


def test_rejected_email_can_resubmit_with_new_proof(clean_access_db):
    from core.access import list_users, register_user, set_user_status

    register_user("Pemohon", "ulang@example.com", "password-pengguna-aman", "bukti-lama.jpg", "081234567891")
    user = list_users("pending")[0]
    set_user_status(user["id"], "rejected")

    again = register_user("Pemohon Baru", "ulang@example.com", "password-baru-aman", "bukti-baru.jpg", "081234567891")
    assert "Pendaftaran ulang" in again["message"]
    pending = list_users("pending")
    assert len(pending) == 1
    assert pending[0]["email"] == "ulang@example.com"
    assert pending[0]["has_proof"] is True


def test_admin_history_delete_keeps_decided_account_active(clean_access_db):
    from core.access import delete_access_history_user, list_users, register_user, set_user_status

    register_user("Riwayat Hapus", "hapus@example.com", "password-pengguna-aman", "bukti-hapus.jpg", "081234567892")
    user = list_users("pending")[0]
    set_user_status(user["id"], "rejected")

    hidden = delete_access_history_user(user["id"])
    assert hidden["history_hidden"] is True
    # Riwayat disembunyikan dari panel, tetapi akun/database tidak dihapus.
    assert not [u for u in list_users("all") if u["email"] == "hapus@example.com"]

    # Jika akun diperiksa secara langsung, kredensial dan statusnya tetap ada.
    from core.database import get_db
    with get_db() as conn:
        row = conn.execute("SELECT status, proof_filename FROM access_user WHERE id = ?", (user["id"],)).fetchone()
    assert row["status"] == "rejected"
    assert row["proof_filename"] == "bukti-hapus.jpg"


# =========================
# BEBAN LOGIN & SESI
# =========================
# Tiga keluhan nyata dari user yang ditangani blok tes ini: situs terasa
# berat, user merasa "dikeluarkan" padahal sesinya hidup, dan password yang
# sudah benar kadang ditolak.


def _hitung_query(monkeypatch):
    """Hitung berapa kali core.access menyentuh database."""
    from core import access

    calls = []
    asli = access.get_db

    def dihitung():
        calls.append(1)
        return asli()

    monkeypatch.setattr(access, "get_db", dihitung)
    return calls


def test_sesi_yang_sama_tidak_query_ulang_tiap_request(clean_access_db, monkeypatch):
    """Satu kali buka Beranda menembak ~11 endpoint. Tanpa cache, itu ~11 query
    SQLite hanya untuk memvalidasi satu cookie yang sama -- dan tiap query bisa
    ikut mengantre di belakang loop latar yang sedang menulis."""
    from core import access

    _, token = access.authenticate("admin-access-test@example.com", "admin-access-test-password")
    assert access.get_session_user(token) is not None  # query pertama mengisi cache

    calls = _hitung_query(monkeypatch)
    for _ in range(11):
        assert access.get_session_user(token)["is_admin"] is True
    assert calls == []


def test_logout_langsung_menutup_sesi_tanpa_menunggu_cache(clean_access_db):
    from core import access

    _, token = access.authenticate("admin-access-test@example.com", "admin-access-test-password")
    assert access.get_session_user(token) is not None
    access.revoke_session(token)
    # Kalau cache tidak dibatalkan, sesi ini masih hidup sampai TTL habis.
    assert access.get_session_user(token) is None


def test_pencabutan_akses_admin_berlaku_seketika(clean_access_db):
    from core import access

    access.register_user("Dicabut", "cabut@example.com", "password-pengguna-aman", "bukti.jpg", "081234567893")
    pemohon = access.list_users("pending")[0]
    access.set_user_status(pemohon["id"], "approved")
    _, token = access.authenticate("cabut@example.com", "password-pengguna-aman")
    assert access.get_session_user(token) is not None

    access.revoke_user_approval(pemohon["id"])
    assert access.get_session_user(token) is None


def test_file_statis_tidak_menyentuh_database_sesi(client, clean_access_db, monkeypatch):
    """Frontend di-mount di "/", jadi dulu setiap CSS/JS/gambar ikut menembak
    DB padahal gate hanya pernah mengunci /api/*."""
    calls = _hitung_query(monkeypatch)
    assert client.get("/").status_code == 200
    assert calls == []


def test_kegagalan_scrypt_bukan_berarti_password_salah(clean_access_db, monkeypatch):
    """Laporan user: "kadang ada beberapa yg kata sandi udah bener jadi salah"."""
    from core import access

    tersimpan = access._hash_password("password-pengguna-aman")
    assert access.verify_password("password-pengguna-aman", tersimpan) is True
    assert access.verify_password("password-keliru-sekali", tersimpan) is False
    # Hash tersimpan yang rusak memang bukan kecocokan -- itu tetap False.
    assert access.verify_password("password-pengguna-aman", "bukan-hash-scrypt") is False

    # Tetapi kalau scrypt-nya sendiri tidak bisa jalan (kehabisan memori),
    # jawabannya TIDAK BOLEH "password salah".
    monkeypatch.setattr(access, "_SCRYPT_MAXMEM", 1024)
    with pytest.raises(access.PasswordCheckUnavailable):
        access.verify_password("password-pengguna-aman", tersimpan)


def test_login_menjawab_503_saat_password_belum_bisa_diperiksa(client, clean_access_db, monkeypatch):
    from core import access

    def _gagal(_password, _tersimpan):
        raise access.PasswordCheckUnavailable("memory limit exceeded")

    monkeypatch.setattr(access, "verify_password", _gagal)
    res = client.post("/api/access/login", json={
        "email": "admin-access-test@example.com", "password": "admin-access-test-password",
    })
    # 403 akan berbunyi "password tidak tepat" dan membuat user mengganti
    # password yang sebenarnya sudah benar.
    assert res.status_code == 503
    assert "sibuk" in res.json()["detail"].lower()
