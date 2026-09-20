"""Portofolio anggota: bot tahu "kamu lagi bagaimana", bukan cuma "pasar".

Permintaan penulis 21 Sep 2026, beserta syaratnya: "ide bagus buat kan dong
eh tapi itu sekalian kasih tau kita entry dimana kan?" -- portofolio tanpa
jawaban "lalu harus apa, di harga berapa" cuma jadi kalkulator untung-rugi,
dan itu sudah ada di aplikasi sekuritas mana pun.
"""
import pytest

# Fixture bot WhatsApp dipakai ulang dari test_wa_bot.py -- uji privasi di
# bawah harus melewati jalur perintah yang SUNGGUHAN, bukan tiruan.
from tests.test_wa_bot import wa_bersih  # noqa: F401


@pytest.fixture
def porto():
    from core.database import get_db

    import core.portofolio as pf
    pf.ensure_porto_tables()
    with get_db() as conn:
        conn.execute("DELETE FROM porto_transaksi")
    yield pf
    with get_db() as conn:
        conn.execute("DELETE FROM porto_transaksi")


# ---------------------------------------------------------------------------
# Hitungan posisi
# ---------------------------------------------------------------------------

def test_beli_dua_kali_merata_ratakan_harganya(porto):
    porto.catat(1, "BBCA", "BELI", 5, 8000)
    p = porto.catat(1, "bbca", "BELI", 5, 7000)
    assert p["lot"] == 10
    assert p["harga_avg"] == 7500


def test_jual_mengurangi_lot_tanpa_mengubah_rata_rata(porto):
    """Rata-rata BERGERAK, seperti aplikasi sekuritas di Indonesia. Angka
    yang berbeda dari broker akan dianggap salah oleh penggunanya, seberapa
    pun benarnya secara akuntansi."""
    porto.catat(1, "BBCA", "BELI", 10, 7500)
    p = porto.catat(1, "BBCA", "JUAL", 4, 9000)
    assert p["lot"] == 6
    assert p["harga_avg"] == 7500, "menjual untung tidak boleh menggeser rata-rata"


def test_menjual_lebih_banyak_dari_yang_dipegang_ditolak(porto):
    """Hampir selalu salah ketik. Ditolak di sini, bukan dibiarkan jadi
    posisi negatif yang baru ketahuan aneh berhari-hari kemudian."""
    porto.catat(1, "BBCA", "BELI", 2, 8000)
    with pytest.raises(ValueError, match="memegang"):
        porto.catat(1, "BBCA", "JUAL", 5, 8000)


def test_posisi_habis_tidak_muncul_lagi(porto):
    porto.catat(1, "BBCA", "BELI", 3, 8000)
    porto.catat(1, "BBCA", "JUAL", 3, 8500)
    assert porto.posisi_user(1) == []


def test_posisi_milik_orang_lain_tidak_tercampur(porto):
    """Satu tabel, banyak anggota. Kalau penyaringan per user_id pernah
    luput, seseorang melihat posisi orang lain -- kebocoran yang paling
    tidak bisa dimaafkan di fitur ini."""
    porto.catat(1, "BBCA", "BELI", 5, 8000)
    porto.catat(2, "TLKM", "BELI", 5, 3000)
    assert [p["kode"] for p in porto.posisi_user(1)] == ["BBCA"]
    assert [p["kode"] for p in porto.posisi_user(2)] == ["TLKM"]


def test_hapus_membatalkan_catatan_bukan_mencatat_penjualan(porto):
    """Dua hal yang berbeda: salah ketik dibatalkan, penjualan sungguhan
    dicatat. Mencampurnya membuat riwayat berbohong."""
    porto.catat(1, "BBCA", "BELI", 5, 8000)
    assert porto.hapus_kode(1, "BBCA") == 1
    assert porto.posisi_user(1) == []
    assert porto.riwayat_kode(1, "BBCA") == []


@pytest.mark.parametrize("lot,harga", [(0, 8000), (-1, 8000), (5, 0), (5, -3)])
def test_angka_tidak_masuk_akal_ditolak(porto, lot, harga):
    with pytest.raises(ValueError):
        porto.catat(1, "BBCA", "BELI", lot, harga)


def test_modal_dihitung_per_lembar_bukan_per_lot(porto):
    """Satu lot = 100 lembar di BEI. Salah di sini membuat seluruh nominal
    rupiah meleset 100 kali lipat."""
    p = porto.catat(1, "BBCA", "BELI", 5, 8000)
    assert p["modal"] == 5 * 8000 * porto.LEMBAR_PER_LOT == 4_000_000


# ---------------------------------------------------------------------------
# Tampilan: perintah DAN levelnya
# ---------------------------------------------------------------------------

def _baris(kode="BBCA", lot=5, avg=8000, harga=8450, level=None, rek=None):
    untung_pct = (harga / avg - 1) * 100 if harga and avg else None
    return {"kode": kode, "lot": lot, "harga_avg": avg,
            "modal": lot * avg * 100, "harga": harga,
            "untung_pct": untung_pct,
            "untung_rp": (harga - avg) * lot * 100 if harga else None,
            "rekomendasi": rek, "wajar": None, "level": level or []}


def test_posisi_rugi_diberi_level_menambah():
    """INI syarat yang diminta penulis: "sekalian kasih tau kita entry
    dimana kan?" Tanpa baris ini, portofolio cuma kalkulator untung-rugi."""
    import web.app as app_module

    b = _baris(kode="ERAA", avg=720, harga=625,
               level=[{"label": "Support S1", "price": 600, "new_avg_price": 660},
                      {"label": "Batas bawah wajar", "price": 560}])
    teks = app_module._wa_fmt_porto([b], None)
    assert "Kalau mau menambah" in teks
    assert "Support S1 Rp600" in teks
    assert "rata-rata Rp660" in teks
    assert "TIDAK wajib" in teks, "menambah posisi tidak boleh terbaca sebagai anjuran"


def test_posisi_untung_tidak_disodori_level_menambah():
    """Menambah di posisi yang sudah untung itu keputusan yang sama sekali
    berbeda -- menambah risiko pada untung yang belum direalisasikan.
    Menyodorkannya di sini akan terbaca seperti anjuran padahal bukan."""
    import web.app as app_module

    b = _baris(level=[{"label": "Support S1", "price": 7000}])
    teks = app_module._wa_fmt_porto([b], None)
    assert "Kalau mau menambah" not in teks


def test_ihsg_lemah_disebut_saat_menyarankan_level():
    """Menambah posisi saat indeksnya sendiri rontok itu keputusan yang
    berbeda. Menyebut levelnya tanpa menyebut ini akan menyesatkan."""
    import web.app as app_module

    b = _baris(kode="ERAA", avg=720, harga=625,
               level=[{"label": "Support S1", "price": 600}])
    teks = app_module._wa_fmt_porto(
        [b], {"prediction": "BEARISH", "daily_change": -1.4,
              "bearish_score": 7, "bullish_score": 2})
    assert "IHSG sedang lemah" in teks


def test_portofolio_kosong_mengajari_cara_memakainya():
    import web.app as app_module

    teks = app_module._wa_fmt_porto([], None)
    assert "beli BBCA 8000 5" in teks
    assert "pribadi" in teks


def test_untung_dan_rugi_dipisah_serta_ada_totalnya():
    import web.app as app_module

    teks = app_module._wa_fmt_porto(
        [_baris(), _baris(kode="ERAA", avg=720, harga=625)], None)
    assert "*Untung* (1)" in teks and "*Rugi* (1)" in teks
    assert "Mengambang" in teks


def test_harga_gagal_terambil_tidak_menghilangkan_posisinya():
    """Satu harga yang gagal diambil tidak boleh membuat posisinya lenyap
    dari daftar -- orang akan mengira catatannya hilang."""
    import web.app as app_module

    b = _baris(kode="XXXX", harga=None)
    b["untung_pct"] = b["untung_rp"] = None
    teks = app_module._wa_fmt_porto([b], None)
    assert "XXXX" in teks and "belum terambil" in teks


# ---------------------------------------------------------------------------
# PRIVASI -- yang paling tidak boleh salah
# ---------------------------------------------------------------------------

def test_perintah_portofolio_ditolak_di_grup(client, wa_bersih):
    """Isinya nominal uang orang, dan grupnya berisi banyak anggota.

    Ditolak, BUKAN disensor sebagian: menyamarkan rupiah tapi tetap menyebut
    kode dan jumlah lot sama saja membocorkan posisi seseorang ke seluruh
    grup."""
    from tests.test_wa_bot import SECRET, _daftarkan_approved

    _daftarkan_approved()
    r = client.post("/api/wa/command",
                    json={"from": "6281234567890@s.whatsapp.net", "text": "porto",
                          "chat": "628999-1@g.us", "grup": True},
                    headers={"Authorization": f"Bearer {SECRET}"})
    balas = r.json()["reply"] or ""
    assert "pribadi" in balas and "japri" in balas
    assert "Rp" not in balas, "nominal bocor di grup"


def test_sidecar_membalas_ke_asal_pesan_bukan_selalu_ke_grup():
    """Pengaman KEDUA, dan yang ini di berkas lain.

    Kalau sidecar tetap mengirim balasan ke GROUP_JID, jawaban `porto` yang
    diminta lewat japri justru TERKIRIM KE GRUP -- posisi dan nominal uang
    seseorang dibacakan ke semua orang. Penolakan di sisi Python tidak
    menolong kalau jalur pengirimannya sendiri salah alamat."""
    import io
    import os

    akar = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    js = io.open(os.path.join(akar, "wa-bot", "index.js"), encoding="utf-8").read()
    # Bagian penanganan pesan masuk (bukan endpoint siaran /send, yang
    # memang selalu ke grup).
    penanganan = js.split('sock.ev.on("messages.upsert"')[1].split("startSock()")[0]
    assert "kirimTeks(asal," in penanganan, "balasan teks masih dipaksa ke grup"
    assert "sendMessage(GROUP_JID" not in penanganan, "media masih dipaksa ke grup"


def test_sidecar_lama_yang_belum_kirim_asal_dianggap_grup(client, wa_bersih):
    """GAGAL-TERTUTUP. Sidecar dan app di-deploy terpisah, jadi akan ada
    jendela waktu ketika app sudah baru tapi sidecar masih lama dan belum
    mengirim asal percakapan.

    Menolak karena salah tebak cuma merepotkan; membocorkan posisi seseorang
    ke grup karena salah tebak tidak bisa ditarik kembali."""
    from tests.test_wa_bot import SECRET, _daftarkan_approved

    _daftarkan_approved()
    r = client.post("/api/wa/command",
                    json={"from": "6281234567890@s.whatsapp.net", "text": "porto"},
                    headers={"Authorization": f"Bearer {SECRET}"})
    balas = r.json()["reply"] or ""
    assert "japri" in balas, "tanpa keterangan asal, harus dianggap grup"


def test_japri_dilayani(client, wa_bersih):
    """Dan sebaliknya: kalau jelas japri, perintahnya harus jalan."""
    from tests.test_wa_bot import SECRET, _daftarkan_approved

    _daftarkan_approved()
    r = client.post("/api/wa/command",
                    json={"from": "6281234567890@s.whatsapp.net", "text": "porto",
                          "chat": "6281234567890@s.whatsapp.net", "grup": False},
                    headers={"Authorization": f"Bearer {SECRET}"})
    balas = r.json()["reply"] or ""
    assert "Portofolio kamu" in balas
    assert "japri" not in balas


# ---------------------------------------------------------------------------
# JANGAN SAMPAI WEB IKUT LAG
# ---------------------------------------------------------------------------
# Bot dan web berbagi SATU proses dan SATU event loop. Perintah bot yang
# menahan loop membuat seluruh aplikasi tersendat -- keluhan yang sudah
# berkali-kali dibayar di proyek ini ("lag ketika mau kirim pertanyaan"
# di forum, layar login muncul sendiri, file statis ikut menggantung).

def test_porto_tidak_menahan_event_loop(porto, monkeypatch):
    """Diukur, bukan diklaim. Portofolio 20 emiten -- lebih besar daripada
    yang wajar -- dan event loop harus tetap bebas."""
    import asyncio
    import time

    import web.app as app_module

    for i in range(20):
        porto.catat(99, f"EM{i:02d}", "BELI", 5, 1000)

    async def _averagedown_palsu(kode, avg_price, lots, add_lots=1,
                                 target_price=None):
        await asyncio.sleep(0.02)          # seolah I/O jaringan
        return {"current_price": 1100, "recommendation": "BUY",
                "suggestions": [{"label": "Support S1", "price": 950}]}

    async def _ihsg_palsu():
        return {"prediction": "BEARISH", "daily_change": -0.3}

    monkeypatch.setattr(app_module, "averagedown", _averagedown_palsu)
    monkeypatch.setattr(app_module, "ihsg", _ihsg_palsu)

    async def _jalan():
        jeda = [0.0]

        async def _pantau():
            t = time.perf_counter()
            while True:
                await asyncio.sleep(0)
                kini = time.perf_counter()
                jeda[0] = max(jeda[0], kini - t)
                t = kini

        tugas = asyncio.create_task(_pantau())
        teks = await app_module._wa_porto({"id": 99}, "LIHAT", "", 0, 0)
        tugas.cancel()
        return jeda[0], teks

    jeda, teks = asyncio.run(_jalan())
    assert "EM00" in teks
    assert jeda < 0.05, (
        f"event loop tertahan {jeda*1000:.0f} ms — web ikut tersendat")


def test_pengambilan_harga_punya_tenggat():
    """Satu emiten yang lambat tidak boleh menggantung seluruh `porto`.
    Emiten yang dipegang seseorang belum tentu ada di universe yang
    dihangatkan pemanas, jadi pengambilan dingin memang mungkin terjadi."""
    import io
    import os

    akar = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sumber = io.open(os.path.join(akar, "web", "app.py"), encoding="utf-8").read()
    potongan = sumber.split("async def _porto_baris")[1][:1600]
    assert "wait_for" in potongan, "pengambilan harga tanpa tenggat"


def test_basis_data_disentuh_lewat_thread_bukan_event_loop():
    """sqlite3 itu I/O SINKRON. Memanggilnya langsung di fungsi async
    menahan seluruh proses selama tulisannya berlangsung -- dan basis data
    ini sama dengan yang dipakai web."""
    import io
    import os

    akar = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sumber = io.open(os.path.join(akar, "web", "app.py"), encoding="utf-8").read()
    fungsi = sumber.split("async def _wa_porto")[1].split("async def _porto_baris")[0]
    for nama in ("catat", "hapus_kode", "posisi_user", "posisi_kode"):
        assert f"asyncio.to_thread({nama}" in fungsi or \
               f"to_thread({nama}," in fungsi, (
            f"{nama}() dipanggil langsung di event loop")


def test_tabel_dibuat_sekali_saja_per_proses(porto):
    """ensure_porto_tables() dipanggil dari hampir setiap operasi. Kalau ia
    menyentuh basis data tiap kali, perintah portofolio menambah lalu lintas
    ke basis data yang sama dipakai web tanpa guna."""
    import core.portofolio as pf

    assert pf._tabel_siap is True, "penanda tidak terpasang"
    dipanggil = []
    asli = pf.get_db

    def _catat_panggilan(*a, **k):
        dipanggil.append(1)
        return asli(*a, **k)

    pf.get_db = _catat_panggilan
    try:
        pf.ensure_porto_tables()
        pf.ensure_porto_tables()
        assert not dipanggil, "tabel dibuat ulang padahal sudah siap"
    finally:
        pf.get_db = asli


# ---------------------------------------------------------------------------
# DIAM ITU KEGAGALAN YANG PALING MEMBINGUNGKAN
# ---------------------------------------------------------------------------
# 21 Sep 2026: penulis mengetik `beli wins 593 122`, `porto`, `port`, `porto`
# di japri dan tidak mendapat balasan apa pun. Dari luar, "bot mati", "pesan
# tidak sampai", dan "ketikan saya salah" terlihat sama persis -- padahal
# ketiganya menuntut tindakan yang sama sekali berbeda.

def _japri(client, teks):
    from tests.test_wa_bot import SECRET

    return client.post("/api/wa/command",
                       json={"from": "6281234567890@s.whatsapp.net", "text": teks,
                             "chat": "6281234567890@s.whatsapp.net", "grup": False},
                       headers={"Authorization": f"Bearer {SECRET}"}
                       ).json()["reply"] or ""


@pytest.mark.parametrize("ketikan", ["porto", "port", "portofolio", "posisi"])
def test_berbagai_cara_menulis_porto_dijawab(client, wa_bersih, ketikan):
    from tests.test_wa_bot import _daftarkan_approved

    _daftarkan_approved()
    assert "Portofolio kamu" in _japri(client, ketikan), f"{ketikan!r} tidak dijawab"


def test_perintah_setengah_jadi_dijawab_dengan_contohnya(client, wa_bersih):
    """`beli BBCA` tanpa harga dulu DIAM. Orang lalu mengulang ketikan yang
    sama berkali-kali karena mengira pesannya tidak sampai."""
    from tests.test_wa_bot import _daftarkan_approved

    _daftarkan_approved()
    balas = _japri(client, "beli BBCA")
    assert "beli BBCA 8000 5" in balas


def test_kode_asing_disebut_namanya(client, wa_bersih):
    """Menyebut kode yang ditolak jauh lebih menolong daripada contoh umum:
    yang salah ketik langsung melihat salahnya di mana."""
    from tests.test_wa_bot import _daftarkan_approved

    _daftarkan_approved()
    balas = _japri(client, "beli ZZZZ 100 5")
    assert "ZZZZ" in balas and "tidak saya kenali" in balas


def test_pembelian_sungguhan_tetap_tercatat(client, wa_bersih):
    from tests.test_wa_bot import _daftarkan_approved

    _daftarkan_approved()
    balas = _japri(client, "beli BBCA 593 122")
    assert "BELI BBCA" in balas and "122 lot" in balas
    assert "Rp593" in balas


def test_sidecar_menerima_japri_bentuk_apa_pun():
    """WhatsApp sedang berpindah ke LID: japri dari klien baru bisa datang
    sebagai "12345@lid", bukan "@s.whatsapp.net". Penyaring yang menyebut
    satu bentuk saja akan DIAM untuk bentuk yang lain -- dan diam tidak
    meninggalkan jejak apa pun untuk ditelusuri."""
    import io
    import os

    akar = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    js = io.open(os.path.join(akar, "wa-bot", "index.js"), encoding="utf-8").read()
    penanganan = js.split('sock.ev.on("messages.upsert"')[1].split("startSock()")[0]
    assert '@s.whatsapp.net"' not in penanganan.split("dariJapri")[0][-400:], (
        "penyaring japri masih terikat pada satu bentuk JID")
    assert "@broadcast" in penanganan and "@newsletter" in penanganan
    # Yang diabaikan HARUS meninggalkan jejak.
    assert "diabaikan" in penanganan and "tidak dijawab" in penanganan


def test_direktori_emiten_gagal_dimuat_tidak_menyalahkan_pengguna(client, wa_bersih,
                                                                  monkeypatch):
    """_load_ticker_directory() mengembalikan [] saat berkasnya tidak
    terbaca. Menyebut kode pengguna "tidak dikenal" karena berkas KITA tidak
    terbaca adalah menyalahkan orang atas kesalahan sendiri."""
    import web.app as app_module
    from tests.test_wa_bot import _daftarkan_approved

    _daftarkan_approved()
    monkeypatch.setattr(app_module, "_load_ticker_directory", lambda: [])
    balas = _japri(client, "beli BBCA 8000 5")
    assert "tidak saya kenali" not in balas
    assert "BELI BBCA" in balas


# ---------------------------------------------------------------------------
# MENJUAL: yang ingin diketahui orang adalah UNTUNG ATAU RUGINYA
# ---------------------------------------------------------------------------

def test_jual_menyebut_rata_rata_dan_untung_ruginya(porto):
    """Permintaan penulis 21 Sep 2026: "jualnya kasih tau juga avg brp dong
    biar tau untung rugi nya". Mencatat penjualan tanpa itu cuma pembukuan
    yang tidak menjawab apa pun."""
    import asyncio

    import web.app as app_module

    u = {"id": 601}
    asyncio.run(app_module._wa_porto(u, "BELI", "BBCA", 8000, 10))
    balas = asyncio.run(app_module._wa_porto(u, "JUAL", "BBCA", 9000, 3))

    assert "Rata-ratamu Rp8.000" in balas, "harga rata-rata tidak disebut"
    assert "Untung" in balas and "Rp300.000" in balas
    assert "+12.5%" in balas
    assert "Sisa 7 lot" in balas


def test_jual_rugi_disebut_rugi(porto):
    """Bukan "untung -Rp560.000". Kata yang salah di angka merah itu jenis
    ketidakjujuran kecil yang merusak kepercayaan pada angka yang lain."""
    import asyncio

    import web.app as app_module

    u = {"id": 602}
    asyncio.run(app_module._wa_porto(u, "BELI", "BBCA", 8000, 10))
    balas = asyncio.run(app_module._wa_porto(u, "JUAL", "BBCA", 7200, 10))
    assert "Rugi Rp800.000" in balas and "-10.0%" in balas
    assert "Untung" not in balas
    assert "ditutup seluruhnya" in balas


def test_jual_tanpa_harga_memakai_harga_pasar(porto, monkeypatch):
    """BUG NYATA 21 Sep 2026: `jual` tidak pernah meminta harga, lalu
    pencatatan menolak harga 0 -- perintahnya SELALU gagal dengan "Harga
    harus lebih dari 0", pesan yang tidak menunjuk ke mana pun."""
    import asyncio

    import web.app as app_module

    async def _harga(kode):
        return 8800.0

    monkeypatch.setattr(app_module, "_signal_entry_price_lookup", _harga)
    u = {"id": 603}
    asyncio.run(app_module._wa_porto(u, "BELI", "BBCA", 8000, 5))
    balas = asyncio.run(app_module._wa_porto(u, "JUAL", "BBCA", 0, 2))
    assert "Harga harus lebih dari 0" not in balas
    assert "Rp8.800" in balas and "Untung" in balas


def test_jual_tanpa_harga_dan_pasar_mati_menyuruh_sebutkan_harganya(porto, monkeypatch):
    """Kalau harga pasar tidak terambil, jangan gagal dengan pesan yang
    tidak menunjuk ke mana pun -- sebutkan apa yang harus diketik."""
    import asyncio

    import web.app as app_module

    async def _kosong(kode):
        return None

    monkeypatch.setattr(app_module, "_signal_entry_price_lookup", _kosong)
    u = {"id": 604}
    asyncio.run(app_module._wa_porto(u, "BELI", "BBCA", 8000, 5))
    balas = asyncio.run(app_module._wa_porto(u, "JUAL", "BBCA", 0, 2))
    assert "jual BBCA 2 8000" in balas


def test_jual_semua_tanpa_menyebut_lot(porto, monkeypatch):
    import asyncio

    import web.app as app_module

    async def _harga(kode):
        return 8800.0

    monkeypatch.setattr(app_module, "_signal_entry_price_lookup", _harga)
    u = {"id": 605}
    asyncio.run(app_module._wa_porto(u, "BELI", "BBCA", 8000, 7))
    balas = asyncio.run(app_module._wa_porto(u, "JUAL", "BBCA", 0, 0))
    assert "7 lot" in balas and "ditutup seluruhnya" in balas


def test_jual_emiten_yang_tidak_dipegang(porto):
    import asyncio

    import web.app as app_module

    balas = asyncio.run(app_module._wa_porto({"id": 606}, "JUAL", "BBCA", 9000, 3))
    assert "belum punya catatan posisi" in balas
