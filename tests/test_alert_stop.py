"""Peringatan "menyentuh stop" -- dan kenapa ia tidak pernah menyala.

TEMUAN 11 OKT 2026, dari memeriksa server.

Pemeriksaan server menunjukkan tabel wa_alert_kirim belum ada sama sekali.
Menelusuri kenapa, cacatnya bukan di tempat yang diduga:

    _jalankan_alert_posisi() memanggil

        periksa_posisi(p, harga, b.get("level"))

    TIGA argumen. Argumen keempat periksa_posisi adalah `sl`, dan aturan
    PERTAMA di dalamnya berbunyi `if sl and harga <= sl`. Jadi `sl` selalu
    None, dan peringatan "harga menyentuh stop" -- satu-satunya yang
    ditandai PENTING dan dibebaskan dari jatah harian, yang catatannya
    sendiri berbunyi "paling mendesak: uangnya sedang keluar" -- TIDAK
    PERNAH bisa menyala di produksi.

KENAPA SELURUH UJI TETAP HIJAU. Karena ujinya memasok `sl` sendiri:

    periksa_posisi(POSISI, 600, sl=620)

Aturannya terbukti benar. Yang tidak pernah terbukti adalah bahwa ada
seseorang yang memanggilnya begitu. Uji yang memasok sendiri apa yang
produksi tidak punya membuktikan aturannya, bukan jalurnya -- dan itu
golongan kesalahan yang sudah berulang di proyek ini (lihat
test_lencana.py: medan `terakhir` yang tidak ada, dan lencana SMC yang
karenanya tak akan pernah muncul, diam-diam, tanpa error).

Karena itu berkas ini menjaga BENTUK PANGGILANNYA, bukan aturannya.
"""
import ast
import inspect
import io
import os

import pytest

AKAR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------------------
# Jalurnya: argumen `sl` BENAR-BENAR dipasok
# ---------------------------------------------------------------------------

def _panggilan_periksa_posisi():
    """Tiap panggilan periksa_posisi() di web/app.py, lewat AST.

    Dibaca dengan AST, bukan pencarian teks: catatan di sekitar kodenya
    MEMBAHAS panggilan ini (termasuk bentuk lamanya yang salah), dan
    penjaga yang menyala karena kalimat penjelasan akan dimatikan orang.
    Kesalahan itu sudah terjadi empat kali di proyek ini.
    """
    src = io.open(os.path.join(AKAR, "web", "app.py"), encoding="utf-8").read()
    out = []
    for n in ast.walk(ast.parse(src)):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        nama = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
        if nama == "periksa_posisi":
            out.append(n)
    return out


def test_produksi_memasok_argumen_stop():
    """CACAT YANG DITUTUP. Tanpa argumen keempat, aturan stop mati --
    dan matinya tidak terlihat dari mana pun: tidak ada error, tidak ada
    log, cuma peringatan yang tidak pernah datang."""
    panggilan = _panggilan_periksa_posisi()
    assert panggilan, "panggilan periksa_posisi() hilang dari web/app.py"
    for c in panggilan:
        n_arg = len(c.args) + len(c.keywords)
        assert n_arg >= 4, (
            f"periksa_posisi dipanggil dengan {n_arg} argumen; tanpa `sl` "
            "aturan 'menyentuh stop' tidak akan pernah menyala")


def test_stop_diambil_dari_sinyal_yang_diaudit():
    """Posisi portofolio TIDAK menyimpan stop -- tidak ada kolomnya di
    porto_transaksi. Jadi angkanya harus datang dari rencana yang memang
    dibuat aplikasi ini sendiri, yaitu sinyal di Audit Sinyal."""
    import web.app as app_module
    src = inspect.getsource(app_module._jalankan_alert_posisi)
    assert "sl_rencana_kode" in src


def test_pengambilan_stop_tidak_menahan_event_loop():
    """Kueri SQLite sinkron di dalam loop yang memeriksa semua posisi
    semua anggota. Dipanggil langsung, ia menahan event loop sekali per
    posisi -- dan aturan nomor satu di proyek ini adalah permintaan
    pengunjung tidak boleh ikut tertahan."""
    import web.app as app_module
    src = inspect.getsource(app_module._jalankan_alert_posisi)
    assert "asyncio.to_thread(sl_rencana_kode" in src


# ---------------------------------------------------------------------------
# sl_rencana_kode: tiga penyaringan yang mengubah jawabannya
# ---------------------------------------------------------------------------

@pytest.fixture
def sinyal():
    from core.database import get_db

    import core.signal_history as sh
    sh._ensure_table()
    with get_db() as c:
        c.execute("DELETE FROM signal_history WHERE kode LIKE 'ZZ%'")
    yield sh
    with get_db() as c:
        c.execute("DELETE FROM signal_history WHERE kode LIKE 'ZZ%'")


def _rekam(kode, entry, sl_pct, status="OPEN"):
    from core.database import get_db
    with get_db() as c:
        c.execute(
            "INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, "
            "status) VALUES (?, ?, ?, ?, ?)", (kode, entry, 10.0, sl_pct, status))


def test_stop_dihitung_dari_entry_dan_persen(sinyal):
    _rekam("ZZA", 1000.0, 5.0)
    r = sinyal.sl_rencana_kode("ZZA")
    assert r and r["sl"] == pytest.approx(950.0)


def test_hanya_sinyal_OPEN(sinyal):
    """PENDING_ENTRY berarti harga entry-nya BELUM tersentuh. Rencananya
    belum berjalan, jadi menyebut angkanya "stop rencanamu" keliru --
    orangnya belum masuk lewat pintu itu."""
    _rekam("ZZB", 1000.0, 5.0, status="PENDING_ENTRY")
    assert sinyal.sl_rencana_kode("ZZB") is None
    _rekam("ZZC", 1000.0, 5.0, status="SL_HIT")
    assert sinyal.sl_rencana_kode("ZZC") is None


def test_stop_di_atas_entry_ditolak(sinyal):
    """Stop di ATAS entry adalah sinyal JUAL. Peringatan ini untuk saham
    yang DIPEGANG; stop sebuah sinyal jual tidak berlaku bagi pemegangnya,
    dan memakainya akan menyuruh orang menjual di harga yang justru naik."""
    _rekam("ZZD", 1000.0, -5.0)          # sl_pct negatif -> stop di atas
    assert sinyal.sl_rencana_kode("ZZD") is None


def test_beda_skala_karena_aksi_korporasi_ditolak(sinyal):
    """Kasus nyata RAJA (split ~1:5): entry lama Rp1000, harga sesudah
    split Rp200. Stop yang dihitung dari entry lama akan SELALU terlihat
    tersentuh, dan isi pesannya menyuruh MENJUAL. Peringatan salah skala
    lebih buruk daripada tidak ada peringatan."""
    _rekam("ZZE", 1000.0, 5.0)
    assert sinyal.sl_rencana_kode("ZZE", harga=200.0) is None
    assert sinyal.sl_rencana_kode("ZZE", harga=980.0) is not None


def test_teks_tidak_mengaku_stop_itu_setelan_penggunanya():
    """Angka stop datang dari Audit Sinyal, bukan dari sesuatu yang
    orangnya pernah setel -- posisi portofolio tidak menyimpan stop sama
    sekali. Teks lamanya berbunyi "di bawah stop RENCANAMU", yang membuat
    pembacanya mengira ia diingatkan soal keputusannya sendiri lalu
    menindaklanjutinya dengan keyakinan yang tidak pernah ia berikan."""
    from core.wa_alert import periksa_posisi
    a = periksa_posisi({"kode": "ERAA", "harga_avg": 720}, 600, None, 620)
    assert a and a["jenis"] == "sl"
    assert "rencanamu" not in a["teks"]
    assert "Audit Sinyal" in a["teks"]


def test_tanpa_sinyal_mengembalikan_None(sinyal):
    assert sinyal.sl_rencana_kode("ZZTIDAKADA") is None
    assert sinyal.sl_rencana_kode("") is None
    assert sinyal.sl_rencana_kode(None) is None


def test_angka_cacat_tidak_meledak(sinyal):
    _rekam("ZZF", 0.0, 5.0)
    assert sinyal.sl_rencana_kode("ZZF") is None


# ---------------------------------------------------------------------------
# Nadi: membedakan "diam karena sehat" dari "diam karena rusak"
# ---------------------------------------------------------------------------

@pytest.fixture
def nadi():
    from core.database import get_db

    import core.wa_alert as al
    al.ensure_alert_tables()
    # wa_alert_kirim IKUT dibersihkan, dan itu bukan kerapian belaka.
    # Tanpa ini, uji ujung-ke-ujung kedua yang mengirim peringatan yang
    # SAMA akan ditahan oleh penjaga anti-ulang milik uji sebelumnya --
    # keadaan yang sempat terbaca sebagai "nadinya tidak mencatat
    # kiriman", padahal penjaganya yang justru sedang bekerja benar.
    with get_db() as c:
        c.execute("DELETE FROM wa_alert_nadi")
        c.execute("DELETE FROM wa_alert_kirim")
    yield al
    with get_db() as c:
        c.execute("DELETE FROM wa_alert_nadi")
        c.execute("DELETE FROM wa_alert_kirim")


def test_nadi_kosong_sebelum_putaran_pertama(nadi):
    assert nadi.baca_nadi() is None


def test_nadi_mencatat_apa_yang_DILIHAT_bukan_cuma_yang_dikirim(nadi):
    """Inilah seluruh gunanya. "Nol terkirim" punya empat sebab yang
    sangat berbeda -- tidak ada anggota, tidak ada posisi, harga gagal
    diambil, atau semuanya sehat dan memang belum ada yang layak
    dikirim. Hanya yang terakhir wajar, dan tanpa angka-angka ini
    keempatnya terlihat identik dari luar: tabel yang kosong."""
    nadi.catat_nadi(3, 7, 7, 2, 0)
    r = nadi.baca_nadi()
    assert r["n_user"] == 3 and r["n_posisi"] == 7
    assert r["n_berharga"] == 7 and r["n_ber_sl"] == 2
    assert r["n_kirim"] == 0 and r["putaran"] == 1


def test_putaran_dan_kiriman_menumpuk_antar_putaran(nadi):
    """Jumlah yang dilihat diganti tiap putaran (keadaan SEKARANG), tapi
    putaran dan kiriman MENUMPUK -- keduanya riwayat, dan riwayat yang
    ditimpa tiap 15 menit tidak bisa menjawab "pernah berbunyi tidak"."""
    nadi.catat_nadi(1, 2, 2, 0, 1)
    nadi.catat_nadi(1, 3, 3, 1, 2)
    r = nadi.baca_nadi()
    assert r["putaran"] == 2
    assert r["n_kirim"] == 3            # 1 + 2, bukan 2
    assert r["n_posisi"] == 3           # keadaan terakhir, bukan 5


def test_nadi_dicatat_walau_tidak_ada_anggota():
    """Pulang lebih awal TANPA mencatat membuat "tidak ada anggota
    ber-nomor-HP" tidak bisa dibedakan dari "loop-nya mati" -- padahal
    yang pertama cuma data kosong dan yang kedua kerusakan."""
    import web.app as app_module
    src = inspect.getsource(app_module._jalankan_alert_posisi)
    i = src.index("if not aktif:")
    assert "catat_nadi" in src[i:src.index("return 0", i)]


def test_tabel_disiapkan_saat_START_bukan_saat_kirim_pertama():
    """Sebelum ini ensure_alert_tables() cuma terpanggil dari dalam
    boleh_kirim(). Akibatnya tabelnya tidak ada sampai ada peringatan
    pertama yang layak dikirim -- dan "tabelnya tidak ada" lalu tidak
    bisa dibedakan dari "jalurnya rusak". Diperiksa di server 11 Okt
    2026: memang belum ada, dan tidak ada cara tahu apakah itu wajar."""
    src = io.open(os.path.join(AKAR, "web", "app.py"), encoding="utf-8").read()
    i = src.index("async def _lifespan")
    blok = src[i:src.index("asyncio.create_task(_wa_alert_loop())", i)]
    assert "ensure_alert_tables()" in blok


# ---------------------------------------------------------------------------
# Skrip pemeriksa server: tiga cacatnya tidak boleh kembali
# ---------------------------------------------------------------------------

def _skrip():
    return io.open(os.path.join(AKAR, "tools", "cek_server.sh"),
                   encoding="utf-8").read()


def _skrip_kode():
    """Skripnya TANPA komentar dan TANPA baris echo.

    Penjaga di bawah memeriksa apa yang skrip itu KERJAKAN. Komentarnya
    justru membahas perintah-perintah yang salah (itu gunanya), dan
    baris echo-nya mencetak perintah yang harus DIJALANKAN ORANG. Penjaga
    yang menyala karena kalimat penjelasan atau karena petunjuk di layar
    akan dimatikan orang -- dan di proyek ini itu sudah terjadi empat
    kali sebelum hari ini, lalu sekali lagi pada berkas ini sendiri.
    """
    baris = []
    for b in _skrip().splitlines():
        t = b.strip()
        if t.startswith("#") or t.startswith("echo ") or t == "echo":
            continue
        baris.append(b)
    return "\n".join(baris)


def test_tidak_menyimpulkan_dari_tabel_yang_belum_ada():
    """CACAT 1. Versi pertama menyimpulkan "jalur peringatan belum pernah
    jalan sekali pun" dari tabel yang belum ada. Tidak mengikuti: tabel
    itu lahir saat peringatan pertama DIKIRIM, jadi kosongnya juga
    konsisten dengan sistem yang sehat dan sedang diam."""
    s = _skrip()
    assert "BELUM PERNAH jalan sekali pun" not in s
    assert "wa_alert_nadi" in s, "harus membaca nadi, bukan menebak"


def test_galat_wa_bot_dicari_di_dalam_JSON_bukan_lewat_prioritas():
    """CACAT 2. `journalctl -p err` menyaring prioritas syslog, sementara
    wa-bot menulis JSON pino ke stdout -- yang oleh journald selalu
    diberi prioritas "info". Tingkat galatnya ada DI DALAM JSON, jadi
    -p err akan berbunyi "No entries" berapa pun banyak galatnya.

    Terbukti di layar server: jejak 2 jam memuat dua "level":50 sementara
    "galat 24 jam" di bawahnya bilang tidak ada apa-apa. Skrip yang
    membantah dirinya sendiri dalam satu tampilan."""
    assert "-p err" not in _skrip_kode()
    assert '"level":(50|60)' in _skrip()


def test_kematian_layanan_tidak_dicari_pakai_kata_failed():
    """CACAT 3. `grep -iE "killed|failed"` pada log ranahsaham menangkap
    "3 Failed downloads:" dari yfinance -- pesan rutin. Di bawah judul
    "layanan pernah mati mendadak?", delapan baris itu terbaca sebagai
    YA, padahal jawabannya tidak."""
    s = _skrip()
    assert "systemd\\[1\\]:" in s, "harus membatasi ke baris systemd sendiri"
    for salah in ('grep -iE "killed|failed', "grep -iE 'killed|failed"):
        assert salah not in s


def test_skrip_tetap_hanya_membaca():
    """Dijalankan di produksi oleh penulis sendiri. Satu perintah yang
    mengubah keadaan di dalamnya adalah hal terakhir yang pantas ada di
    alat diagnostik.

    Diperiksa pada BAGIAN YANG DIJALANKAN saja: skrip ini MENCETAK
    "jalankan: git pull && sudo systemctl restart ranahsaham" sebagai
    petunjuk, dan petunjuk di layar bukan perintah yang ia jalankan."""
    kode = _skrip_kode()
    for bahaya in ("rm ", "DELETE", "DROP", "UPDATE ", "INSERT ",
                   "systemctl restart", "systemctl stop", "> $DB", "chmod"):
        assert bahaya not in kode, bahaya


# ---------------------------------------------------------------------------
# Ujung ke ujung: putaran sungguhan, bukan cuma bentuk panggilannya
# ---------------------------------------------------------------------------
# Penjaga AST di atas memastikan `sl` DIPASOK. Ia tidak memastikan bahwa
# memasoknya benar-benar menghasilkan peringatan -- dan cacat aslinya
# justru jenis yang lolos dari semua uji satuan: tiap bagian benar,
# sambungannya tidak ada.
#
# Uji ini menjalankan _jalankan_alert_posisi() sungguhan, dengan satu
# anggota, satu posisi, dan satu sinyal OPEN yang stopnya di atas harga
# sekarang. Kalau peringatan "sl" tidak keluar, sambungannya putus lagi
# di suatu tempat -- di mana pun itu.


def _jalankan(monkeypatch, harga, sl_entry, sl_pct, posisi=None):
    import asyncio

    import core.access as access
    import core.portofolio as porto
    import core.whatsapp_notify as notify
    import web.app as app_module

    terkirim = []

    monkeypatch.setattr(access, "list_users", lambda status="pending": [
        {"id": 901, "name": "Uji", "phone": "628000000000"}])
    monkeypatch.setattr(porto, "posisi_user", lambda uid: posisi or [
        {"kode": "ZZG", "harga_avg": 1000.0, "lot": 10, "modal": 1_000_000}])

    async def _baris(p):
        return {**p, "harga": harga, "level": None}
    monkeypatch.setattr(app_module, "_porto_baris", _baris)

    async def _kirim(teks, to=None):
        terkirim.append((teks, to))
        return True
    monkeypatch.setattr(notify, "send_wa_text", _kirim)

    if sl_entry:
        _rekam("ZZG", sl_entry, sl_pct)
    asyncio.run(app_module._jalankan_alert_posisi())
    return terkirim


def test_putaran_penuh_menghasilkan_peringatan_stop(monkeypatch, sinyal, nadi):
    """Entry 1000, stop 5% -> 950. Harga sekarang 940: di bawah stop.

    Inilah keadaan yang selama ini TIDAK pernah menghasilkan apa pun."""
    terkirim = _jalankan(monkeypatch, harga=940.0, sl_entry=1000.0, sl_pct=5.0)
    assert len(terkirim) == 1, "peringatan stop tidak keluar"
    teks, ke = terkirim[0]
    assert ke == "628000000000", "harus JAPRI, bukan grup"
    assert "stop" in teks.lower()
    assert "Audit Sinyal" in teks


def test_harga_di_atas_stop_tidak_memicu_apa_pun(monkeypatch, sinyal, nadi):
    """Penjaga arah. Peringatan yang menyala saat harga AMAN jauh lebih
    merusak daripada yang tidak menyala: bot yang salah bunyi akan
    di-mute, dan sesudah di-mute yang benar pun tidak sampai."""
    terkirim = _jalankan(monkeypatch, harga=990.0, sl_entry=1000.0, sl_pct=5.0)
    assert terkirim == []


def test_tanpa_sinyal_OPEN_tidak_ada_peringatan_stop(monkeypatch, sinyal, nadi):
    """Tanpa rencana, tidak ada stop. Posisi -6% saja bukan alasan: itu
    cuma kerugian berjalan, bukan batas yang pernah ditetapkan."""
    terkirim = _jalankan(monkeypatch, harga=940.0, sl_entry=None, sl_pct=None)
    assert terkirim == []


def test_nadi_terisi_sesudah_putaran_sungguhan(monkeypatch, sinyal, nadi):
    """Pertanyaan yang memulai semua ini -- "peringatan posisi pernah
    berbunyi?" -- sekarang punya jawaban yang bisa dibaca dari basis
    data, bukan disimpulkan dari ada-tidaknya sebuah tabel."""
    _jalankan(monkeypatch, harga=940.0, sl_entry=1000.0, sl_pct=5.0)
    r = nadi.baca_nadi()
    assert r is not None, "putaran berjalan tapi tidak tercatat"
    assert r["n_user"] == 1 and r["n_posisi"] == 1
    assert r["n_berharga"] == 1 and r["n_ber_sl"] == 1
    assert r["n_kirim"] == 1


# ---------------------------------------------------------------------------
# tools/cek_sinyal.sh -- alat diagnostik kedua, dan ia pun harus diragukan
# ---------------------------------------------------------------------------

def _skrip_sinyal():
    return io.open(os.path.join(AKAR, "tools", "cek_sinyal.sh"),
                   encoding="utf-8").read()


def test_cek_sinyal_tidak_menuntut_sqlite3_terpasang():
    """sqlite3 TIDAK terpasang di server (terbukti 12 Okt 2026), dan
    memasangnya cuma untuk membaca satu tabel adalah apt install yang
    tidak perlu -- Python yang menjalankan aplikasinya sudah membawa
    modul sqlite3 di pustaka bakunya."""
    s = _skrip_sinyal()
    kode = "\n".join(b for b in s.splitlines()
                     if not b.strip().startswith("#"))
    assert "sqlite3 " not in kode, "masih memanggil perintah sqlite3"
    assert "import sqlite3" in s


def test_cek_sinyal_membuka_basis_data_HANYA_BACA():
    """Alat diagnostik yang dijalankan di produksi tidak boleh punya
    kemampuan menulis sama sekali. mode=ro membuat kesalahan tulis jadi
    galat, bukan kerusakan."""
    assert "mode=ro" in _skrip_sinyal()


def test_win_rate_hanya_dari_yang_SUDAH_selesai():
    """Memasukkan OPEN membuat angkanya bergantung pada kapan kebetulan
    dibaca: posisi yang sedang untung belum tentu berakhir untung, dan
    angka yang berubah tiap hari tanpa ada sinyal baru bukan win rate.

    EXPIRED_NO_ENTRY juga dikeluarkan -- harga entry-nya tidak pernah
    tersentuh, jadi tidak ada posisi. Ia bukan kalah dan bukan menang."""
    s = _skrip_sinyal()
    i = s.index('tp = sum(')
    blok = s[i:s.index("CATATAN", i)]
    assert '"TP_HIT"' in blok and '"SL_HIT"' in blok
    for terlarang in ('"OPEN"', '"EXPIRED_NO_ENTRY"', '"PENDING_ENTRY"'):
        assert terlarang not in blok, f"{terlarang} ikut dihitung win rate"
