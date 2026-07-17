# =========================
# TES FORUM KOMUNITAS (Tanya Jawab)
# =========================
# Permintaan user: "fitur chat buat komunitas ... lebih ke forum sih".
# Aplikasi ini TIDAK PUNYA sistem akun -- identitas poster HANYA nama
# bebas yang diketik user sendiri, `is_admin` per baris SATU-SATUNYA hal
# yang benar2 diverifikasi SERVER (hmac.compare_digest thd env var
# FORUM_ADMIN_SECRET, lihat _forum_is_admin di web/app.py) -- TIDAK PERNAH
# dipercaya dari klaim klien begitu saja.
import json

import pytest

_PNG_DATA_URL = "data:image/png;base64,iVBORw0KGgo="
_JPEG_DATA_URL = "data:image/jpeg;base64,/9j/4AAQSkZJRg=="


def test_create_thread_success(client, clean_forum_db):
    r = client.post("/api/forum/threads", json={"nama": "Budi", "judul": "Cara baca RSI?", "isi": "Tolong jelaskan RSI dong."})
    assert r.status_code == 200
    data = r.json()
    assert data["nama"] == "Budi"
    assert data["judul"] == "Cara baca RSI?"
    assert data["is_admin"] == 0

    listing = client.get("/api/forum/threads").json()
    assert any(t["id"] == data["id"] for t in listing)


@pytest.mark.parametrize("field", ["nama", "judul", "isi"])
def test_create_thread_missing_or_blank_field_rejected(client, clean_forum_db, field):
    body = {"nama": "Budi", "judul": "Judul", "isi": "Isi pertanyaan."}
    body[field] = "   "  # whitespace-only, harus ditolak sama dgn kosong
    r = client.post("/api/forum/threads", json=body)
    assert r.status_code == 400


def test_create_thread_length_limits_rejected(client, clean_forum_db):
    r = client.post("/api/forum/threads", json={"nama": "A" * 51, "judul": "Judul", "isi": "Isi"})
    assert r.status_code == 400

    r2 = client.post("/api/forum/threads", json={"nama": "Budi", "judul": "J" * 201, "isi": "Isi"})
    assert r2.status_code == 400

    r3 = client.post("/api/forum/threads", json={"nama": "Budi", "judul": "Judul", "isi": "I" * 5001})
    assert r3.status_code == 400


def test_create_thread_correct_admin_code_sets_is_admin(client, clean_forum_db):
    r = client.post("/api/forum/threads", json={
        "nama": "Admin", "judul": "Pengumuman", "isi": "Halo semua.",
        "admin_code": "test-secret-for-pytest-only",
    })
    assert r.status_code == 200
    assert r.json()["is_admin"] == 1


def test_create_thread_wrong_admin_code_rejected_and_nothing_inserted(client, clean_forum_db):
    r = client.post("/api/forum/threads", json={
        "nama": "Penipu", "judul": "Palsu", "isi": "Isi.",
        "admin_code": "kode-salah",
    })
    assert r.status_code == 400

    listing = client.get("/api/forum/threads").json()
    assert not any(t["judul"] == "Palsu" for t in listing), "baris TIDAK BOLEH ke-insert kalau kode admin salah"


def test_forum_admin_secret_unset_fails_closed(client, clean_forum_db, monkeypatch):
    """Regresi footgun: hmac.compare_digest("","") == True -- kalau
    FORUM_ADMIN_SECRET belum di-set, admin_code KOSONG maupun ISI APA PUN
    harus SAMA-SAMA ditolak/tidak pernah jadi admin, TIDAK PERNAH lolos
    diam-diam."""
    import core.config as cfg
    monkeypatch.setattr(cfg, "FORUM_ADMIN_SECRET", "")

    r1 = client.post("/api/forum/threads", json={"nama": "A", "judul": "J", "isi": "I", "admin_code": ""})
    assert r1.status_code == 200
    assert r1.json()["is_admin"] == 0

    r2 = client.post("/api/forum/threads", json={"nama": "A", "judul": "J2", "isi": "I", "admin_code": "anything"})
    assert r2.status_code == 400, "secret kosong + kode apa pun HARUS ditolak, bukan diam2 lolos"


def test_create_reply_success(client, clean_forum_db):
    thread = client.post("/api/forum/threads", json={"nama": "Budi", "judul": "Q", "isi": "I"}).json()
    r = client.post(f"/api/forum/threads/{thread['id']}/replies", json={"nama": "Ani", "isi": "Jawabannya begini..."})
    assert r.status_code == 200
    data = r.json()
    assert data["nama"] == "Ani"
    assert data["thread_id"] == thread["id"]


def test_create_thread_with_image_data(client, clean_forum_db):
    r = client.post("/api/forum/threads", json={
        "nama": "Budi",
        "judul": "Profit BBCA",
        "isi": "Share hasil trading.",
        "image_data": _PNG_DATA_URL,
    })
    assert r.status_code == 200
    data = r.json()
    assert data["image_data"] == _PNG_DATA_URL
    assert data["images"] == [_PNG_DATA_URL]

    detail = client.get(f"/api/forum/threads/{data['id']}").json()
    assert detail["thread"]["image_data"] == _PNG_DATA_URL
    assert detail["thread"]["images"] == [_PNG_DATA_URL]


def test_create_reply_with_image_data(client, clean_forum_db):
    thread = client.post("/api/forum/threads", json={"nama": "A", "judul": "Q", "isi": "I"}).json()
    r = client.post(f"/api/forum/threads/{thread['id']}/replies", json={
        "nama": "Ani",
        "isi": "Ini screenshot profitnya.",
        "image_data": _PNG_DATA_URL,
    })
    assert r.status_code == 200
    assert r.json()["image_data"] == _PNG_DATA_URL
    assert r.json()["images"] == [_PNG_DATA_URL]

    detail = client.get(f"/api/forum/threads/{thread['id']}").json()
    assert detail["replies"][0]["image_data"] == _PNG_DATA_URL
    assert detail["replies"][0]["images"] == [_PNG_DATA_URL]


def test_create_thread_with_multiple_images(client, clean_forum_db):
    images = [_PNG_DATA_URL, _JPEG_DATA_URL]
    r = client.post("/api/forum/threads", json={
        "nama": "Budi",
        "judul": "Profit BBCA",
        "isi": "Beberapa screenshot.",
        "image_data": images,
    })
    assert r.status_code == 200
    data = r.json()
    assert json.loads(data["image_data"]) == images
    assert data["images"] == images

    detail = client.get(f"/api/forum/threads/{data['id']}").json()
    assert json.loads(detail["thread"]["image_data"]) == images
    assert detail["thread"]["images"] == images


def test_create_thread_accepts_images_alias(client, clean_forum_db):
    images = [_PNG_DATA_URL, _JPEG_DATA_URL]
    r = client.post("/api/forum/threads", json={
        "nama": "Budi",
        "judul": "Profit BBCA",
        "isi": "Alias payload frontend.",
        "images": images,
    })
    assert r.status_code == 200
    assert r.json()["images"] == images


def test_create_thread_with_multipart_image_files(client, clean_forum_db, tmp_path, monkeypatch):
    import web.app as app_module

    monkeypatch.setattr(app_module, "_FORUM_UPLOAD_DIR", str(tmp_path))

    r = client.post(
        "/api/forum/threads",
        data={"nama": "Budi", "judul": "Profit BBCA", "isi": "Upload file asli.", "kategori": "umum"},
        files=[
            ("images", ("profit-1.png", b"fakepng1", "image/png")),
            ("images", ("profit-2.jpg", b"fakejpg2", "image/jpeg")),
        ],
    )
    assert r.status_code == 200
    images = r.json()["images"]
    assert len(images) == 2
    assert all(u.startswith("/forum_uploads/") for u in images)
    assert all((tmp_path / u.rsplit("/", 1)[1]).exists() for u in images)

    detail = client.get(f"/api/forum/threads/{r.json()['id']}").json()
    assert detail["thread"]["images"] == images


def test_forum_image_data_rejects_too_many_images(client, clean_forum_db):
    r = client.post("/api/forum/threads", json={
        "nama": "A",
        "judul": "J",
        "isi": "I",
        "image_data": [_PNG_DATA_URL] * 6,
    })
    assert r.status_code == 400


def test_forum_image_data_rejects_invalid_format_and_large_payload(client, clean_forum_db):
    bad = client.post("/api/forum/threads", json={
        "nama": "A",
        "judul": "J",
        "isi": "I",
        "image_data": "data:text/html;base64,PHNjcmlwdD4=",
    })
    assert bad.status_code == 400

    large_b64 = "A" * (701 * 1024 * 4 // 3)
    large = client.post("/api/forum/threads", json={
        "nama": "A",
        "judul": "J",
        "isi": "I",
        "image_data": f"data:image/png;base64,{large_b64}",
    })
    assert large.status_code == 400


def test_create_reply_to_nonexistent_thread_404(client, clean_forum_db):
    r = client.post("/api/forum/threads/999999/replies", json={"nama": "Ani", "isi": "Isi"})
    assert r.status_code == 404


def test_list_threads_newest_first_with_reply_count(client, clean_forum_db):
    t1 = client.post("/api/forum/threads", json={"nama": "A", "judul": "Pertama", "isi": "I"}).json()
    t2 = client.post("/api/forum/threads", json={"nama": "A", "judul": "Kedua", "isi": "I"}).json()
    client.post(f"/api/forum/threads/{t1['id']}/replies", json={"nama": "B", "isi": "balasan 1"})
    client.post(f"/api/forum/threads/{t1['id']}/replies", json={"nama": "C", "isi": "balasan 2"})

    listing = client.get("/api/forum/threads").json()
    ids = [t["id"] for t in listing]
    assert ids.index(t2["id"]) < ids.index(t1["id"]), "thread TERBARU (t2) harus muncul lebih dulu"

    t1_listed = next(t for t in listing if t["id"] == t1["id"])
    assert t1_listed["reply_count"] == 2


def test_thread_detail_includes_replies_chronological(client, clean_forum_db):
    thread = client.post("/api/forum/threads", json={"nama": "A", "judul": "Q", "isi": "I"}).json()
    client.post(f"/api/forum/threads/{thread['id']}/replies", json={"nama": "B", "isi": "duluan"})
    client.post(f"/api/forum/threads/{thread['id']}/replies", json={"nama": "C", "isi": "belakangan"})

    detail = client.get(f"/api/forum/threads/{thread['id']}").json()
    assert detail["thread"]["id"] == thread["id"]
    assert [r["isi"] for r in detail["replies"]] == ["duluan", "belakangan"]


def test_thread_detail_404_when_not_found(client, clean_forum_db):
    r = client.get("/api/forum/threads/999999")
    assert r.status_code == 404


def test_delete_thread_requires_correct_admin_code(client, clean_forum_db):
    thread = client.post("/api/forum/threads", json={"nama": "A", "judul": "Q", "isi": "I"}).json()

    r_wrong = client.request("DELETE", f"/api/forum/threads/{thread['id']}", json={"admin_code": "salah"})
    assert r_wrong.status_code == 400
    assert client.get(f"/api/forum/threads/{thread['id']}").status_code == 200

    r_ok = client.request("DELETE", f"/api/forum/threads/{thread['id']}", json={"admin_code": "test-secret-for-pytest-only"})
    assert r_ok.status_code == 200
    assert client.get(f"/api/forum/threads/{thread['id']}").status_code == 404


def test_delete_thread_cascades_replies(client, clean_forum_db):
    """Regresi LANGSUNG utk fix cascade manual (FK tidak di-enforce SQLite
    di proyek ini) -- hapus thread HARUS ikut menghapus balasannya, bukan
    menyisakan baris forum_reply yatim."""
    thread = client.post("/api/forum/threads", json={"nama": "A", "judul": "Q", "isi": "I"}).json()
    reply1 = client.post(f"/api/forum/threads/{thread['id']}/replies", json={"nama": "B", "isi": "r1"}).json()
    reply2 = client.post(f"/api/forum/threads/{thread['id']}/replies", json={"nama": "C", "isi": "r2"}).json()

    r = client.request("DELETE", f"/api/forum/threads/{thread['id']}", json={"admin_code": "test-secret-for-pytest-only"})
    assert r.status_code == 200

    from core.database import get_db
    with get_db() as conn:
        remaining = conn.execute(
            "SELECT COUNT(*) c FROM forum_reply WHERE id IN (?, ?)", (reply1["id"], reply2["id"])
        ).fetchone()
    assert remaining["c"] == 0, "balasan yatim TIDAK BOLEH tersisa setelah thread induknya dihapus"


def test_delete_reply_requires_correct_admin_code(client, clean_forum_db):
    thread = client.post("/api/forum/threads", json={"nama": "A", "judul": "Q", "isi": "I"}).json()
    reply = client.post(f"/api/forum/threads/{thread['id']}/replies", json={"nama": "B", "isi": "r1"}).json()

    r_wrong = client.request("DELETE", f"/api/forum/replies/{reply['id']}", json={"admin_code": "salah"})
    assert r_wrong.status_code == 400

    r_ok = client.request("DELETE", f"/api/forum/replies/{reply['id']}", json={"admin_code": "test-secret-for-pytest-only"})
    assert r_ok.status_code == 200

    detail = client.get(f"/api/forum/threads/{thread['id']}").json()
    assert detail["replies"] == []


def test_delete_nonexistent_thread_404(client, clean_forum_db):
    r = client.request("DELETE", "/api/forum/threads/999999", json={"admin_code": "test-secret-for-pytest-only"})
    assert r.status_code == 404


def test_forum_rate_limit_exceeded(client, clean_forum_db):
    """Limiter forum TERPISAH dari limiter global (1200/60d, terlalu
    longgar) -- _FORUM_RATE_MAX=8 per 300 detik. Request ke-9 dalam
    jendela yang sama harus 429."""
    for i in range(8):
        r = client.post("/api/forum/threads", json={"nama": "A", "judul": f"Q{i}", "isi": "I"})
        assert r.status_code == 200, f"request ke-{i+1} seharusnya masih di bawah ambang"

    r9 = client.post("/api/forum/threads", json={"nama": "A", "judul": "Q9", "isi": "I"})
    assert r9.status_code == 429


def test_forum_content_stored_raw_no_backend_sanitization(client, clean_forum_db):
    """Dokumentasi eksplisit: proteksi XSS adalah tanggung jawab RENDER-
    TIME frontend (escHtml() di web/static/index.html), BUKAN sanitasi
    backend -- backend menyimpan teks APA ADANYA (utuh, tidak diubah)."""
    payload = "<script>alert(1)</script>"
    r = client.post("/api/forum/threads", json={"nama": "A", "judul": payload, "isi": payload})
    assert r.status_code == 200
    data = r.json()
    assert data["judul"] == payload
    assert data["isi"] == payload


# =========================
# FORUM v2: kategori, upvote/jawaban terbaik, search/sort, ticker, lapor
# =========================


def test_ensure_table_migration_idempotent_preserves_data(client, clean_forum_db):
    """Regresi migrasi additive-only: panggil _ensure_table() ulang pada
    tabel yang SUDAH punya kolom baru & baris data TIDAK BOLEH error
    (duplicate column) ATAU mengubah/menghapus baris yang sudah ada --
    skenario nyata yang terjadi tiap kali server production restart thd DB
    dev yang sudah berisi data (lihat catatan "Migration 10/12 RETRAKSI"
    di core/signal_history.py utk insiden data-loss sejenis)."""
    import core.forum as forum_mod
    t = forum_mod.create_thread("Budi", "Judul asli", "Isi asli", False, "teknikal")
    forum_mod._ensured = False  # simulasikan restart server yang menjalankan ulang migrasi
    forum_mod._ensure_table()
    from core.database import get_db
    with get_db() as conn:
        row = conn.execute("SELECT * FROM forum_thread WHERE id = ?", (t["id"],)).fetchone()
    assert row["judul"] == "Judul asli"
    assert row["kategori"] == "teknikal"


def test_create_thread_default_kategori_umum(client, clean_forum_db):
    r = client.post("/api/forum/threads", json={"nama": "A", "judul": "J", "isi": "I"})
    assert r.json()["kategori"] == "umum"


def test_create_thread_valid_kategori_saved(client, clean_forum_db):
    r = client.post("/api/forum/threads", json={"nama": "A", "judul": "J", "isi": "I", "kategori": "teknikal"})
    assert r.json()["kategori"] == "teknikal"


def test_create_thread_unknown_kategori_rejected(client, clean_forum_db):
    r = client.post("/api/forum/threads", json={"nama": "A", "judul": "J", "isi": "I", "kategori": "ngasal"})
    assert r.status_code == 400


def test_list_threads_search_matches_judul_or_isi(client, clean_forum_db):
    client.post("/api/forum/threads", json={"nama": "A", "judul": "Cara baca RSI", "isi": "pertanyaan umum"})
    client.post("/api/forum/threads", json={"nama": "A", "judul": "Lain-lain", "isi": "bahas soal RSI juga di sini"})
    client.post("/api/forum/threads", json={"nama": "A", "judul": "Tidak nyambung", "isi": "MACD saja"})
    listing = client.get("/api/forum/threads", params={"q": "RSI"}).json()
    judul_list = [t["judul"] for t in listing]
    assert "Cara baca RSI" in judul_list
    assert "Lain-lain" in judul_list
    assert "Tidak nyambung" not in judul_list


def test_list_threads_search_no_match_returns_empty(client, clean_forum_db):
    client.post("/api/forum/threads", json={"nama": "A", "judul": "J", "isi": "I"})
    listing = client.get("/api/forum/threads", params={"q": "zzzznotfound"}).json()
    assert listing == []


def test_list_threads_search_literal_percent_not_wildcard(client, clean_forum_db):
    """Regresi escape LIKE: user ketik '%' literal di kotak cari TIDAK
    BOLEH diam2 jadi wildcard SQL yang mencocokkan thread lain."""
    client.post("/api/forum/threads", json={"nama": "A", "judul": "Diskon 50%", "isi": "promo"})
    client.post("/api/forum/threads", json={"nama": "A", "judul": "Tidak terkait", "isi": "lain"})
    listing = client.get("/api/forum/threads", params={"q": "50%"}).json()
    judul_list = [t["judul"] for t in listing]
    assert judul_list == ["Diskon 50%"]


def test_list_threads_filter_by_kategori(client, clean_forum_db):
    client.post("/api/forum/threads", json={"nama": "A", "judul": "T", "isi": "I", "kategori": "teknikal"})
    client.post("/api/forum/threads", json={"nama": "A", "judul": "F", "isi": "I", "kategori": "fundamental"})
    listing = client.get("/api/forum/threads", params={"kategori": "teknikal"}).json()
    assert len(listing) == 1
    assert listing[0]["judul"] == "T"


def test_list_threads_unknown_kategori_filter_rejected(client, clean_forum_db):
    r = client.get("/api/forum/threads", params={"kategori": "ngasal"})
    assert r.status_code == 400


def test_list_threads_sort_populer_by_total_upvotes(client, clean_forum_db):
    t1 = client.post("/api/forum/threads", json={"nama": "A", "judul": "T1", "isi": "I"}).json()
    t2 = client.post("/api/forum/threads", json={"nama": "A", "judul": "T2", "isi": "I"}).json()
    r1 = client.post(f"/api/forum/threads/{t1['id']}/replies", json={"nama": "B", "isi": "balasan"}).json()
    client.post(f"/api/forum/replies/{r1['id']}/upvote")
    client.post(f"/api/forum/replies/{r1['id']}/upvote")
    listing = client.get("/api/forum/threads", params={"sort": "populer"}).json()
    ids = [t["id"] for t in listing]
    assert ids.index(t1["id"]) < ids.index(t2["id"]), "thread dgn total upvote balasan lebih tinggi harus di atas"


def test_list_threads_status_belum_dijawab_only_zero_replies(client, clean_forum_db):
    t1 = client.post("/api/forum/threads", json={"nama": "A", "judul": "Dijawab", "isi": "I"}).json()
    client.post("/api/forum/threads", json={"nama": "A", "judul": "Belum", "isi": "I"})
    client.post(f"/api/forum/threads/{t1['id']}/replies", json={"nama": "B", "isi": "jawaban"})
    listing = client.get("/api/forum/threads", params={"status": "belum_dijawab"}).json()
    judul_list = [t["judul"] for t in listing]
    assert "Belum" in judul_list
    assert "Dijawab" not in judul_list


def test_upvote_reply_increments_and_no_server_dedup(client, clean_forum_db):
    thread = client.post("/api/forum/threads", json={"nama": "A", "judul": "Q", "isi": "I"}).json()
    reply = client.post(f"/api/forum/threads/{thread['id']}/replies", json={"nama": "B", "isi": "jawaban"}).json()
    r1 = client.post(f"/api/forum/replies/{reply['id']}/upvote")
    assert r1.status_code == 200
    assert r1.json()["upvotes"] == 1
    r2 = client.post(f"/api/forum/replies/{reply['id']}/upvote")
    assert r2.json()["upvotes"] == 2, "TIDAK ADA dedup server -- upvote berkali-kali harus tetap increment (desain disetujui, dedup di localStorage)"


def test_upvote_nonexistent_reply_404(client, clean_forum_db):
    r = client.post("/api/forum/replies/999999/upvote")
    assert r.status_code == 404


def test_best_answer_requires_correct_admin_code(client, clean_forum_db):
    thread = client.post("/api/forum/threads", json={"nama": "A", "judul": "Q", "isi": "I"}).json()
    reply = client.post(f"/api/forum/threads/{thread['id']}/replies", json={"nama": "B", "isi": "jawaban"}).json()
    r_wrong = client.post(f"/api/forum/replies/{reply['id']}/best-answer", json={"admin_code": "salah"})
    assert r_wrong.status_code == 400
    r_ok = client.post(f"/api/forum/replies/{reply['id']}/best-answer", json={"admin_code": "test-secret-for-pytest-only"})
    assert r_ok.status_code == 200
    assert r_ok.json()["is_best_answer"] == 1


def test_best_answer_only_one_per_thread_and_floats_to_top(client, clean_forum_db):
    thread = client.post("/api/forum/threads", json={"nama": "A", "judul": "Q", "isi": "I"}).json()
    r1 = client.post(f"/api/forum/threads/{thread['id']}/replies", json={"nama": "B", "isi": "jawaban1"}).json()
    r2 = client.post(f"/api/forum/threads/{thread['id']}/replies", json={"nama": "C", "isi": "jawaban2"}).json()
    client.post(f"/api/forum/replies/{r1['id']}/best-answer", json={"admin_code": "test-secret-for-pytest-only"})
    client.post(f"/api/forum/replies/{r2['id']}/best-answer", json={"admin_code": "test-secret-for-pytest-only"})
    detail = client.get(f"/api/forum/threads/{thread['id']}").json()
    best_flags = [r["is_best_answer"] for r in detail["replies"]]
    assert best_flags.count(1) == 1, "maksimal SATU jawaban terbaik per thread"
    assert detail["replies"][0]["id"] == r2["id"], "jawaban terbaik naik ke atas balasan lain"


def test_best_answer_toggle_off(client, clean_forum_db):
    thread = client.post("/api/forum/threads", json={"nama": "A", "judul": "Q", "isi": "I"}).json()
    reply = client.post(f"/api/forum/threads/{thread['id']}/replies", json={"nama": "B", "isi": "jawaban"}).json()
    client.post(f"/api/forum/replies/{reply['id']}/best-answer", json={"admin_code": "test-secret-for-pytest-only"})
    r2 = client.post(f"/api/forum/replies/{reply['id']}/best-answer", json={"admin_code": "test-secret-for-pytest-only"})
    assert r2.json()["is_best_answer"] == 0


def test_best_answer_nonexistent_reply_404(client, clean_forum_db):
    r = client.post("/api/forum/replies/999999/best-answer", json={"admin_code": "test-secret-for-pytest-only"})
    assert r.status_code == 404


def test_report_thread_increments_count(client, clean_forum_db):
    thread = client.post("/api/forum/threads", json={"nama": "A", "judul": "Q", "isi": "I"}).json()
    assert client.post(f"/api/forum/threads/{thread['id']}/report").status_code == 200
    from core.database import get_db
    with get_db() as conn:
        row = conn.execute("SELECT report_count FROM forum_thread WHERE id=?", (thread["id"],)).fetchone()
    assert row["report_count"] == 1


def test_report_reply_increments_count(client, clean_forum_db):
    thread = client.post("/api/forum/threads", json={"nama": "A", "judul": "Q", "isi": "I"}).json()
    reply = client.post(f"/api/forum/threads/{thread['id']}/replies", json={"nama": "B", "isi": "jawaban"}).json()
    assert client.post(f"/api/forum/replies/{reply['id']}/report").status_code == 200
    from core.database import get_db
    with get_db() as conn:
        row = conn.execute("SELECT report_count FROM forum_reply WHERE id=?", (reply["id"],)).fetchone()
    assert row["report_count"] == 1


def test_report_nonexistent_thread_and_reply_404(client, clean_forum_db):
    assert client.post("/api/forum/threads/999999/report").status_code == 404
    assert client.post("/api/forum/replies/999999/report").status_code == 404


def test_thread_and_reply_include_detected_tickers(client, clean_forum_db):
    """Reuse deteksi_emiten() (core/news_emiten.py) via _forum_tickers() di
    web/app.py -- ticker yang disebut di judul/isi/balasan harus muncul di
    field `tickers` pada response list & detail (dipakai frontend utk
    auto-link ke halaman Analisis)."""
    created = client.post("/api/forum/threads", json={"nama": "A", "judul": "Analisis saham", "isi": "Menurutku BBCA lagi bagus."}).json()

    listing = client.get("/api/forum/threads").json()
    listed = next(t for t in listing if t["id"] == created["id"])
    assert "BBCA" in listed["tickers"]

    reply = client.post(f"/api/forum/threads/{created['id']}/replies", json={"nama": "B", "isi": "Setuju, TLKM juga menarik."}).json()
    detail = client.get(f"/api/forum/threads/{created['id']}").json()
    assert "BBCA" in detail["thread"]["tickers"]
    reply_detail = next(r for r in detail["replies"] if r["id"] == reply["id"])
    assert "TLKM" in reply_detail["tickers"]


def test_thread_no_ticker_mentioned_empty_list(client, clean_forum_db):
    created = client.post("/api/forum/threads", json={"nama": "A", "judul": "Tanya umum", "isi": "Ga nyebut kode saham apapun di sini."}).json()
    detail = client.get(f"/api/forum/threads/{created['id']}").json()
    assert detail["thread"]["tickers"] == []


# =========================
# NOTIFIKASI FORUM (lonceng)
# =========================


def test_notif_forum_reply_counts_for_followed_threads(client, clean_forum_db):
    """Endpoint /api/notifications/forum: klien kirim daftar thread yang
    diikuti, server balas count + latest_reply_id per thread supaya klien
    bisa deteksi balasan baru dgn membandingkan latest_reply_id."""
    t1 = client.post("/api/forum/threads", json={"nama": "A", "judul": "Q1", "isi": "I"}).json()
    t2 = client.post("/api/forum/threads", json={"nama": "A", "judul": "Q2", "isi": "I"}).json()
    r1 = client.post(f"/api/forum/threads/{t1['id']}/replies", json={"nama": "B", "isi": "jawab1"}).json()
    client.post(f"/api/forum/threads/{t1['id']}/replies", json={"nama": "C", "isi": "jawab2"})

    resp = client.post("/api/notifications/forum", json={"thread_ids": [t1["id"], t2["id"]]})
    assert resp.status_code == 200
    threads = resp.json()["threads"]
    # kunci JSON selalu string
    assert threads[str(t1["id"])]["count"] == 2
    assert threads[str(t1["id"])]["latest_reply_id"] >= r1["id"]
    # thread tanpa balasan tetap muncul dgn count 0 (bukan hilang)
    assert threads[str(t2["id"])]["count"] == 0
    assert threads[str(t2["id"])]["latest_reply_id"] == 0


def test_notif_forum_empty_and_sanitizes_ids(client, clean_forum_db):
    """thread_ids kosong -> {}. Nilai non-integer/negatif dibuang, tidak
    error (input dari klien tidak dipercaya mentah)."""
    assert client.post("/api/notifications/forum", json={"thread_ids": []}).json()["threads"] == {}
    # id sampah dibuang; id valid yang tidak ada tetap dijawab count 0
    resp = client.post("/api/notifications/forum", json={"thread_ids": ["abc", -5, 999999]})
    assert resp.status_code == 200
    threads = resp.json()["threads"]
    assert "999999" in threads and threads["999999"]["count"] == 0
    assert "abc" not in threads and "-5" not in threads


def test_notif_signals_since_id_baseline_and_new(client, clean_signal_db):
    """/api/notifications/signals: since_id=0 -> items kosong (cuma
    baseline latest_id, tidak membanjiri riwayat); since_id < id sinyal
    yang ada -> muncul sbg baru."""
    from core.database import get_db
    with get_db() as conn:
        conn.execute("INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, source, status) "
                     "VALUES ('ZZNOTIF', 1000, 5, 3, 'TOP_PICK', 'PENDING_ENTRY')")
        new_id = conn.execute("SELECT MAX(id) m FROM signal_history").fetchone()["m"]

    base = client.get("/api/notifications/signals?since_id=0").json()
    assert base["items"] == [] and base["latest_id"] == new_id

    fresh = client.get(f"/api/notifications/signals?since_id={new_id - 1}").json()
    assert fresh["n_new"] >= 1
    assert any(i["kode"] == "ZZNOTIF" for i in fresh["items"])
