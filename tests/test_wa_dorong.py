"""Kiriman otomatis ke WhatsApp: Siluman + sinyal baru.

Permintaan penulis 6 Okt 2026. Fitur yang mengirim sendiri punya satu mode
gagal yang jauh lebih mahal daripada bug biasa: ia membunyikan HP orang.
Terlalu sering, dan yang terjadi bukan "orang membacanya lebih sedikit"
melainkan "orang membisukan grupnya" -- sesudah itu peringatan yang
benar-benar penting pun ikut tidak terbaca, dan itu tidak mudah dipulihkan.

Karena itu takarannya diuji lebih ketat daripada isinya.
"""
import pytest

from core.database import get_db


@pytest.fixture
def dorong_bersih():
    """Tabel catatan kirim kosong + cursor sinyal direset."""
    from core.wa_alert import ensure_alert_tables

    ensure_alert_tables()
    with get_db() as conn:
        conn.execute("DELETE FROM wa_alert_kirim")
    yield
    with get_db() as conn:
        conn.execute("DELETE FROM wa_alert_kirim")


def _config_palsu(monkeypatch, awal=None):
    """app_config palsu, terpisah per uji.

    Tanpa ini, penanda "pemindaian sebelumnya" bocor antar-uji lewat SQLite
    sungguhan: uji yang jalan belakangan mewarisi pembanding milik uji
    sebelumnya, dan hasilnya berubah menurut URUTAN jalannya.
    """
    import core.whatsapp_notify as wn

    simpan = dict(awal or {})
    monkeypatch.setattr(wn, "_get_config", lambda k: simpan.get(k))
    monkeypatch.setattr(wn, "_set_config", lambda k, v: simpan.__setitem__(k, v))
    return simpan


def _sm(kode, pola="Siluman (quiet buy)", **ubah):
    dasar = {"kode": kode, "pola": pola, "harga": 1000, "chg1": 2.5,
             "chg5": 6.0, "vol_ratio": 0.9, "rsi": 58.0,
             "likuiditas": "Likuid", "grup": "Independen", "hari_lalu": 0}
    dasar.update(ubah)
    return dasar


# ---------------------------------------------------------------------------
# Jendela kirim
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("hari,jam,harap", [
    (0, 10, True),    # Senin siang
    (4, 15, True),    # Jumat sore, masih di dalam
    (0, 3, False),    # Senin dini hari
    (0, 8, False),    # sebelum jendela
    (0, 16, False),   # tepat di batas atas -- sudah di luar
    (5, 11, False),   # Sabtu
    (6, 11, False),   # Minggu
])
def test_jendela_kirim(hari, jam, harap):
    """Pesan pukul 3 pagi tidak menambah satu pun keputusan yang bisa
    diambil, tapi tetap membunyikan HP orang."""
    from datetime import datetime

    from core.wa_dorong import WIB, dalam_jam_kirim

    # 5 Okt 2026 = Senin, jadi tanggal 5+hari memberi hari yang dimaksud.
    waktu = datetime(2026, 10, 5 + hari, jam, 30, tzinfo=WIB)
    assert waktu.weekday() == hari, "prasyarat ujinya sendiri"
    assert dalam_jam_kirim(waktu) is harap


def test_waktu_dibaca_sebagai_WIB_bukan_waktu_server():
    """Jendela yang bergantung zona waktu server akan diam-diam bergeser
    kalau servernya disetel UTC -- dan gejalanya bukan error, melainkan
    pesan yang tiba pukul 2 pagi."""
    from core.wa_dorong import WIB, sekarang_wib

    assert sekarang_wib().tzinfo is WIB


# ---------------------------------------------------------------------------
# Tidak mengulang
# ---------------------------------------------------------------------------

def test_saham_yang_sama_tidak_diberitakan_dua_kali(dorong_bersih):
    """Saham yang BERTAHAN di Siluman akan muncul di tiap putaran loop.
    Tanpa penjaga ini, ia diumumkan tiap lima menit, seharian."""
    from core.wa_dorong import catat_terkirim, pilih_belum_dikirim

    items = [_sm("BBCA"), _sm("UNTR")]
    assert [x["kode"] for x in pilih_belum_dikirim(items)] == ["BBCA", "UNTR"]

    catat_terkirim(items)
    assert pilih_belum_dikirim(items) == []


def test_hanya_pola_yang_dipantau_yang_dikirim(dorong_bersih):
    """Breakout Volume & Akumulasi Agresif sudah menonjol dengan
    sendirinya di layar mana pun. Mengirimkannya juga cuma menambah
    kebisingan tanpa menambah satu pun hal yang tidak terlihat."""
    from core.wa_dorong import pilih_belum_dikirim

    items = [_sm("AAAA", "Breakout Volume"), _sm("BBBB", "Akumulasi Agresif"),
             _sm("CCCC", "Distribusi"), _sm("DDDD")]
    assert [x["kode"] for x in pilih_belum_dikirim(items)] == ["DDDD"]


def test_dibatasi_jumlahnya_per_pesan(dorong_bersih):
    """Berapa pun yang masuk, satu pesan tetap terbaca."""
    from core.wa_dorong import MAKS_PER_PESAN, pilih_belum_dikirim

    banyak = [_sm(f"AA{i:02d}") for i in range(MAKS_PER_PESAN + 8)]
    assert len(pilih_belum_dikirim(banyak)) == MAKS_PER_PESAN


def test_yang_terpotong_pagu_ikut_putaran_berikutnya(dorong_bersih):
    """Dipotong BUKAN dibuang. Yang tidak muat tidak dicatat sebagai
    terkirim, jadi ia masih dianggap baru di putaran berikutnya."""
    from core.wa_dorong import MAKS_PER_PESAN, catat_terkirim, pilih_belum_dikirim

    banyak = [_sm(f"AA{i:02d}") for i in range(MAKS_PER_PESAN + 3)]
    gelombang1 = pilih_belum_dikirim(banyak)
    catat_terkirim(gelombang1)

    gelombang2 = pilih_belum_dikirim(banyak)
    assert len(gelombang2) == 3
    assert not ({x["kode"] for x in gelombang2} & {x["kode"] for x in gelombang1})


def test_baris_cacat_tidak_menjatuhkan_sisanya(dorong_bersih):
    from core.wa_dorong import pilih_belum_dikirim

    items = [None, "bukan dict", {}, {"kode": "", "pola": "Siluman (quiet buy)"},
             _sm("BBCA")]
    assert [x["kode"] for x in pilih_belum_dikirim(items)] == ["BBCA"]


# ---------------------------------------------------------------------------
# Dicatat hanya kalau benar-benar terkirim
# ---------------------------------------------------------------------------

def test_kirim_gagal_maka_tidak_dicatat_sudah_terkirim(dorong_bersih, monkeypatch):
    """Mencatat lebih dulu akan membuat kabarnya HILANG SELAMANYA kalau
    WhatsApp sedang menolak: ia dianggap sudah dikirim padahal tidak pernah
    sampai, dan jeda 24 jam menutupinya sampai besok."""
    import core.wa_dorong as wd
    import core.whatsapp_notify as wn
    import web.app as app_module

    monkeypatch.setattr(wd, "dalam_jam_kirim", lambda waktu=None: True)
    # Acuan sudah terisi supaya ujinya sampai ke tahap KIRIM, bukan berhenti
    # di penyaring kedipan -- yang diuji di sini perilaku saat kirim gagal.
    _config_palsu(monkeypatch, {app_module._DORONG_SM_SEBELUMNYA_KEY: "BBCA"})
    monkeypatch.setattr(app_module, "_cache_get",
                        lambda k: {"total_scan": 793, "akumulasi": [_sm("BBCA")],
                                   "distribusi": []}
                        if k == "foreign_flow:all" else None)

    async def _gagal(text, to=None):
        return False

    monkeypatch.setattr(wn, "send_wa_text", _gagal)

    import asyncio
    assert asyncio.run(app_module._dorong_siluman()) is False
    # Masih dianggap belum terkirim -> ikut lagi di putaran berikutnya.
    assert [x["kode"] for x in wd.pilih_belum_dikirim([_sm("BBCA")])] == ["BBCA"]


def test_dikumpulkan_jadi_SATU_pesan_bukan_satu_per_saham(dorong_bersih, monkeypatch):
    """Lima saham masuk Siluman = satu pesan berisi lima baris. Lima
    notifikasi terpisah adalah cara tercepat membuat grupnya dibisukan."""
    import asyncio

    import core.wa_dorong as wd
    import core.whatsapp_notify as wn
    import web.app as app_module

    terkirim = []

    async def _rekam(text, to=None):
        terkirim.append(text)
        return True

    monkeypatch.setattr(wd, "dalam_jam_kirim", lambda waktu=None: True)
    monkeypatch.setattr(wn, "send_wa_text", _rekam)
    _config_palsu(monkeypatch)
    monkeypatch.setattr(app_module, "_cache_get",
                        lambda k: {"total_scan": 793,
                                   "akumulasi": [_sm(f"AA{i:02d}") for i in range(5)],
                                   "distribusi": []}
                        if k == "foreign_flow:all" else None)

    # Putaran pertama cuma mencatat acuan (lihat saring_stabil); yang diuji
    # di sini bentuk pesannya, jadi dijalankan dua kali.
    asyncio.run(app_module._dorong_siluman())
    assert asyncio.run(app_module._dorong_siluman()) is True
    assert len(terkirim) == 1, "satu pesan per saham = grup dibisukan"
    for i in range(5):
        assert f"AA{i:02d}" in terkirim[0]


def test_memindai_SELURUH_idx_bukan_yang_likuid_saja(dorong_bersih, monkeypatch):
    """Permintaan penulis yang ditegaskan dua kali: "pastikan yg scan semua
    saham idx yaa".

    Yang dikunci di sini KUNCI CACHE-nya, karena itulah yang menentukan
    universe mana yang dibaca. Memeriksa jumlah hasil tidak akan menangkap
    kesalahan ini: dua saham juga jawaban yang sah untuk hari yang sepi,
    jadi universe yang salah terbaca persis seperti hari yang sepi.

    Kesalahan yang sama pernah terjadi di perintah `smartmoney` -- bot
    melaporkan 2 anomali sementara layar menunjukkan 22, karena bot membaca
    universe 178 emiten sementara layar membaca 793.
    """
    import asyncio

    import core.wa_dorong as wd
    import core.whatsapp_notify as wn
    import web.app as app_module

    diminta = []

    def _cache(k):
        diminta.append(k)
        if k == "foreign_flow:all":
            return {"total_scan": 793, "akumulasi": [_sm("BBCA")], "distribusi": []}
        return None

    async def _ok(text, to=None):
        return True

    monkeypatch.setattr(wd, "dalam_jam_kirim", lambda waktu=None: True)
    monkeypatch.setattr(wn, "send_wa_text", _ok)
    _config_palsu(monkeypatch)
    monkeypatch.setattr(app_module, "_cache_get", _cache)

    asyncio.run(app_module._dorong_siluman())      # putaran acuan
    assert asyncio.run(app_module._dorong_siluman()) is True
    assert "foreign_flow:all" in diminta, "membaca universe sempit, bukan seluruh IDX"
    assert not [k for k in diminta if k in ("foreign_flow:core", "foreign_flow:medium")]


def test_jumlah_saham_yang_dipindai_disebut_di_pesannya(dorong_bersih):
    """Penerima harus bisa melihat sendiri bahwa pemindaiannya seluruh IDX,
    tanpa perlu percaya pada kode. Angkanya datang dari payload, jadi kalau
    suatu hari universe-nya menyempit, pesannya ikut mengaku."""
    from web.app import _wa_fmt_dorong_siluman

    assert "793 saham IDX" in _wa_fmt_dorong_siluman([_sm("BBCA")], 793)


def test_cache_dingin_dilewati_bukan_memicu_pemindaian(dorong_bersih, monkeypatch):
    """Memaksa pemindaian 69 detik dari dalam loop pengirim cuma menambah
    satu tempat baru yang bisa menahan server. Pemanas akan mengisinya
    sendiri dalam hitungan menit."""
    import asyncio

    import core.wa_dorong as wd
    import web.app as app_module

    monkeypatch.setattr(wd, "dalam_jam_kirim", lambda waktu=None: True)
    monkeypatch.setattr(app_module, "_cache_get", lambda k: None)
    assert asyncio.run(app_module._dorong_siluman()) is False


def test_di_luar_jam_tidak_mengirim_apa_pun(dorong_bersih, monkeypatch):
    import asyncio

    import core.wa_dorong as wd
    import web.app as app_module

    monkeypatch.setattr(wd, "dalam_jam_kirim", lambda waktu=None: False)
    monkeypatch.setattr(app_module, "_cache_get",
                        lambda k: {"total_scan": 793, "akumulasi": [_sm("BBCA")],
                                   "distribusi": []})
    assert asyncio.run(app_module._dorong_siluman()) is False


# ---------------------------------------------------------------------------
# Kedipan sesaat -- pola dihitung dari bar yang BELUM SELESAI
# ---------------------------------------------------------------------------

def test_hanya_yang_bertahan_dua_pemindaian_yang_dikirim():
    """Pola dihitung dari bar HARI INI yang belum selesai, jadi saham bisa
    masuk-keluar kategori sepanjang sesi."""
    from core.wa_dorong import saring_stabil

    items = [_sm("PTBA"), _sm("DEWA"), _sm("SGER")]
    stabil = saring_stabil(items, {"PTBA", "DEWA"})
    assert [x["kode"] for x in stabil] == ["PTBA", "DEWA"]


def test_kasus_nyata_SGER_berpindah_kategori_di_tengah_sesi():
    """KEJADIAN SUNGGUHAN 6 Okt 2026, terlihat penulis di layarnya sendiri.

    Pukul 14.33 perintah `smartmoney` menyebut SGER "Breakout Volume":
    chg1 +3,31%, lolos ambang `chg1 > 3` di _sm_classify.
    Pukul 14.58 kiriman otomatis menyebutnya "Siluman (quiet buy)":
    chg1 +2,65%, jatuh ke bawah ambang yang sama.

    Saham yang sama, hari yang sama, label yang berbeda -- semata karena
    bursa belum tutup. Tanpa penyaring ini, ia diumumkan sebagai akumulasi
    diam-diam berdasarkan keadaan yang bertahan beberapa menit."""
    from core.wa_dorong import saring_stabil

    # Putaran 1: SGER masih Breakout Volume, jadi tidak ikut daftar Siluman.
    sebelumnya = {"PTBA", "DEWA"}
    # Putaran 2: SGER baru masuk Siluman.
    sekarang = [_sm("PTBA"), _sm("DEWA"), _sm("SGER")]

    stabil = saring_stabil(sekarang, sebelumnya)
    assert "SGER" not in [x["kode"] for x in stabil], (
        "kedipan sesaat diumumkan sebagai akumulasi diam-diam")


def test_pemindaian_pertama_tidak_mengirim_apa_pun(dorong_bersih, monkeypatch):
    """Tidak ada pembanding = tidak ada yang bisa disebut bertahan. Putaran
    pertama sesudah restart mencatat acuan, bukan mengirim."""
    import asyncio

    import core.wa_dorong as wd
    import core.whatsapp_notify as wn
    import web.app as app_module

    simpan = {}
    terkirim = []

    async def _rekam(text, to=None):
        terkirim.append(text)
        return True

    monkeypatch.setattr(wd, "dalam_jam_kirim", lambda waktu=None: True)
    monkeypatch.setattr(wn, "send_wa_text", _rekam)
    monkeypatch.setattr(wn, "_get_config", lambda k: simpan.get(k))
    monkeypatch.setattr(wn, "_set_config", lambda k, v: simpan.__setitem__(k, v))
    monkeypatch.setattr(app_module, "_cache_get",
                        lambda k: {"total_scan": 793,
                                   "akumulasi": [_sm("PTBA"), _sm("DEWA")],
                                   "distribusi": []}
                        if k == "foreign_flow:all" else None)

    assert asyncio.run(app_module._dorong_siluman()) is False
    assert terkirim == []
    assert simpan[app_module._DORONG_SM_SEBELUMNYA_KEY] == "DEWA,PTBA"

    # Putaran kedua: keduanya masih di sana -> baru dikirim.
    assert asyncio.run(app_module._dorong_siluman()) is True
    assert len(terkirim) == 1
    assert "PTBA" in terkirim[0] and "DEWA" in terkirim[0]


def test_pembanding_dicatat_walau_kirimnya_gagal(dorong_bersih, monkeypatch):
    """Pembanding putaran berikutnya harus mencerminkan apa yang BENAR-BENAR
    terlihat, bukan apa yang berhasil dikirim. Kalau ia ikut gagal dicatat,
    saham yang stabil akan selamanya terlihat 'baru muncul'."""
    import asyncio

    import core.wa_dorong as wd
    import core.whatsapp_notify as wn
    import web.app as app_module

    simpan = {app_module._DORONG_SM_SEBELUMNYA_KEY: "PTBA"}

    async def _gagal(text, to=None):
        return False

    monkeypatch.setattr(wd, "dalam_jam_kirim", lambda waktu=None: True)
    monkeypatch.setattr(wn, "send_wa_text", _gagal)
    monkeypatch.setattr(wn, "_get_config", lambda k: simpan.get(k))
    monkeypatch.setattr(wn, "_set_config", lambda k, v: simpan.__setitem__(k, v))
    monkeypatch.setattr(app_module, "_cache_get",
                        lambda k: {"total_scan": 793, "akumulasi": [_sm("PTBA")],
                                   "distribusi": []}
                        if k == "foreign_flow:all" else None)

    assert asyncio.run(app_module._dorong_siluman()) is False
    assert simpan[app_module._DORONG_SM_SEBELUMNYA_KEY] == "PTBA"


def test_pesan_mengaku_bahwa_bursa_belum_tutup():
    """Penerima berhak tahu bahwa angkanya masih bergerak. Menyajikannya
    seolah final adalah janji yang tidak bisa ditepati sebelum penutupan."""
    from web.app import _wa_fmt_dorong_siluman

    teks = _wa_fmt_dorong_siluman([_sm("PTBA")], 793)
    assert "belum selesai" in teks
    assert "dua pemindaian" in teks


# ---------------------------------------------------------------------------
# Sinyal baru -- dan cursor yang TIDAK BOLEH dipakai bersama
# ---------------------------------------------------------------------------

def test_cursor_dorong_TERPISAH_dari_cursor_ringkasan_harian(monkeypatch):
    """INI YANG PALING MUDAH SALAH DAN PALING SULIT DISADARI.

    Kalau kiriman otomatis memakai cursor yang sama dengan digest harian,
    ia akan "memakan" sinyal yang belum sempat masuk ringkasan: begitu ia
    memajukan cursor, ringkasan pagi berikutnya melaporkan "tidak ada
    sinyal baru" untuk sinyal yang justru baru saja terjadi.

    Tidak ada yang error. Yang hilang cuma isi laporan, dan hilangnya
    diam-diam."""
    import asyncio

    import core.signal_history as sh
    import core.wa_dorong as wd
    import core.whatsapp_notify as wn
    import web.app as app_module

    digest_dimajukan = []
    monkeypatch.setattr(wn, "set_last_signal_id",
                        lambda i: digest_dimajukan.append(i))

    simpan = {app_module._DORONG_SINYAL_KEY: "10"}
    monkeypatch.setattr(wn, "_get_config", lambda k: simpan.get(k))
    monkeypatch.setattr(wn, "_set_config",
                        lambda k, v: simpan.__setitem__(k, v))
    monkeypatch.setattr(sh, "get_signal_notifications",
                        lambda since_id=0, limit=20: {
                            "items": [{"id": 11, "kode": "BBCA", "source": "TOP_PICK",
                                       "status": "OPEN", "direction": "LONG",
                                       "entry_price": 9000, "tp_pct": 12.0}],
                            "latest_id": 11, "n_new": 1})

    async def _ok(text, to=None):
        return True

    monkeypatch.setattr(wn, "send_wa_text", _ok)
    monkeypatch.setattr(wd, "dalam_jam_kirim", lambda waktu=None: True)

    assert asyncio.run(app_module._dorong_sinyal_baru()) is True
    assert simpan[app_module._DORONG_SINYAL_KEY] == "11", "cursor sendiri tidak maju"
    assert digest_dimajukan == [], "kiriman otomatis memakan sinyal milik ringkasan harian"


def test_pertama_kali_menyala_mencatat_acuan_bukan_menumpahkan_riwayat(monkeypatch):
    """Menyalakan fitur ini tidak boleh membanjiri grup dengan seluruh
    riwayat sinyal sebagai "baru". Semantik yang sama dipakai lonceng
    notifikasi in-app dan digest harian."""
    import asyncio

    import core.signal_history as sh
    import core.wa_dorong as wd
    import core.whatsapp_notify as wn
    import web.app as app_module

    simpan = {}
    terkirim = []

    async def _rekam(text, to=None):
        terkirim.append(text)
        return True

    monkeypatch.setattr(wn, "_get_config", lambda k: simpan.get(k))
    monkeypatch.setattr(wn, "_set_config", lambda k, v: simpan.__setitem__(k, v))
    monkeypatch.setattr(wn, "send_wa_text", _rekam)
    monkeypatch.setattr(wd, "dalam_jam_kirim", lambda waktu=None: True)
    monkeypatch.setattr(sh, "get_signal_notifications",
                        lambda since_id=0, limit=20: {"items": [], "latest_id": 403,
                                                      "n_new": 0})

    assert asyncio.run(app_module._dorong_sinyal_baru()) is False
    assert terkirim == [], "riwayat lama ditumpahkan sebagai sinyal baru"
    assert simpan[app_module._DORONG_SINYAL_KEY] == "403", "acuannya tidak dicatat"


def test_kirim_sinyal_gagal_maka_cursor_tidak_maju(monkeypatch):
    """Cursor yang maju walau kirimnya gagal membuat sinyal itu hilang dari
    kiriman berikutnya -- tidak pernah diberitakan sama sekali."""
    import asyncio

    import core.signal_history as sh
    import core.wa_dorong as wd
    import core.whatsapp_notify as wn
    import web.app as app_module

    simpan = {app_module._DORONG_SINYAL_KEY: "10"}

    async def _gagal(text, to=None):
        return False

    monkeypatch.setattr(wn, "_get_config", lambda k: simpan.get(k))
    monkeypatch.setattr(wn, "_set_config", lambda k, v: simpan.__setitem__(k, v))
    monkeypatch.setattr(wn, "send_wa_text", _gagal)
    monkeypatch.setattr(wd, "dalam_jam_kirim", lambda waktu=None: True)
    monkeypatch.setattr(sh, "get_signal_notifications",
                        lambda since_id=0, limit=20: {
                            "items": [{"id": 11, "kode": "BBCA", "source": "TOP_PICK",
                                       "status": "OPEN", "direction": "LONG"}],
                            "latest_id": 11, "n_new": 1})

    assert asyncio.run(app_module._dorong_sinyal_baru()) is False
    assert simpan[app_module._DORONG_SINYAL_KEY] == "10", "sinyal hilang tanpa pernah dikirim"


# ---------------------------------------------------------------------------
# Isi pesannya
# ---------------------------------------------------------------------------

def test_pesan_siluman_menjelaskan_ARTINYA_bukan_cuma_namanya():
    """Pesan yang datang sendiri tidak punya legenda di sebelahnya.
    "Siluman (quiet buy)" tidak memberi tahu apa pun kepada orang yang
    belum pernah membaca keterangannya di web."""
    from web.app import _wa_fmt_dorong_siluman

    teks = _wa_fmt_dorong_siluman([_sm("BBCA")], 793)
    assert "volumenya justru DI BAWAH rata-rata" in teks
    assert "bukan aliran dana asing" in teks


def test_pesan_sinyal_kronologis_bukan_id_menurun():
    """Orang membaca daftar begini dari yang paling lama ke yang paling
    baru, sama seperti membaca percakapan. get_signal_notifications
    memulangkannya DESC by id."""
    from web.app import _wa_fmt_dorong_sinyal

    teks = _wa_fmt_dorong_sinyal([
        {"id": 12, "kode": "ZZZZ", "source": "TOP_PICK", "status": "OPEN"},
        {"id": 11, "kode": "AAAA", "source": "NR7_52W", "status": "OPEN"},
    ])
    assert teks.index("AAAA") < teks.index("ZZZZ")


def test_pesan_sinyal_tahan_field_yang_hilang():
    """Sinyal tanpa entry/TP tetap layak diberitakan -- yang tidak boleh
    adalah perintahnya meledak karena satu kolom kosong."""
    from web.app import _wa_fmt_dorong_sinyal

    teks = _wa_fmt_dorong_sinyal([{"kode": "BBCA"}])
    assert "BBCA" in teks
