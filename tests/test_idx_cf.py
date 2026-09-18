"""Pemilihan sidik jari TLS untuk menembus Cloudflare idx.co.id.

cf_clearance TERIKAT pada sidik jari TLS browser yang memecahkan challenge.
Kalau curl_cffi meniru Chrome versi LAIN, idx.co.id membalas 403 walau
cookienya sah dan baru saja didapat -- dan itu kegagalan yang menyesatkan,
karena semua yang kelihatan (solver jalan, cookie ada) justru tampak benar.

Terjadi nyata 18 Sep 2026: `pip install -r requirements.txt` memutakhirkan
curl_cffi 0.7 -> 0.16.3, alias "chrome" melompat ke sidik jari jauh lebih
baru daripada Chrome di server, dan fitur Pemegang Saham mati.
"""
import pytest


@pytest.fixture
def idx(monkeypatch):
    """Modul idx_cf dengan cache pilihan target dikosongkan."""
    import core.idx_cf as m

    monkeypatch.setattr(m, "_impersonate_cache", None, raising=False)
    monkeypatch.delenv("IDX_IMPERSONATE", raising=False)
    return m


DIDUKUNG = {"chrome", "chrome99", "chrome110", "chrome120", "chrome131",
            "chrome136", "chrome142", "chrome146", "chrome131_android",
            "chrome133a", "chrome_android", "safari180", "firefox135"}


def _pasang(monkeypatch, idx, major, tersedia=DIDUKUNG):
    monkeypatch.setattr(idx, "_chrome_major", lambda: major)
    import typing
    palsu = type("M", (), {"BrowserTypeLiteral": typing.Literal[tuple(tersedia)]})
    monkeypatch.setitem(__import__("sys").modules,
                        "curl_cffi.requests.impersonate", palsu)


def test_memilih_target_tertinggi_yang_tidak_melebihi_chrome_terpasang(idx, monkeypatch):
    _pasang(monkeypatch, idx, 140)
    assert idx._target_impersonate() == "chrome136"


def test_tidak_pernah_meniru_chrome_yang_lebih_baru_dari_yang_terpasang(idx, monkeypatch):
    """INI bug-nya. Meniru versi yang lebih baru dari browser yang memecahkan
    challenge membuat sidik jarinya tidak sepadan dengan cf_clearance, dan
    idx.co.id menolaknya."""
    import re

    for major in (110, 125, 140, 200):
        monkeypatch.setattr(idx, "_impersonate_cache", None, raising=False)
        _pasang(monkeypatch, idx, major)
        dipilih = idx._target_impersonate()
        m = re.fullmatch(r"chrome(\d+)[a-z]?", dipilih)
        assert m, f"target tidak berbentuk chromeNNN: {dipilih!r}"
        assert int(m.group(1)) <= major, (
            f"Chrome {major} tapi meniru {dipilih} -- lebih baru dari yang terpasang")


def test_varian_android_tidak_ikut_terpilih(idx, monkeypatch):
    """chrome131_android punya sidik jari yang berbeda dari Chrome desktop;
    ia tidak akan pernah cocok dengan cookie yang dipanen Chrome di Xvfb."""
    _pasang(monkeypatch, idx, 132)
    assert "android" not in idx._target_impersonate()


def test_variabel_lingkungan_menang(idx, monkeypatch):
    """Jalan keluar saat menelusuri masalah: paksa satu nilai tanpa menyunting kode."""
    _pasang(monkeypatch, idx, 140)
    monkeypatch.setenv("IDX_IMPERSONATE", "chrome120")
    assert idx._target_impersonate() == "chrome120"


def test_gagal_mendeteksi_chrome_jatuh_ke_perilaku_lama(idx, monkeypatch):
    """Di mesin tanpa Chrome (dev/test), jangan sampai fungsi ini melempar --
    ia harus diam-diam kembali ke alias lama, bukan menjatuhkan fitur lain."""
    monkeypatch.setattr(idx, "_chrome_major", lambda: None)
    assert idx._target_impersonate() == "chrome"


def test_chrome_major_membaca_versi_dari_keluaran_perintah(idx, monkeypatch):
    import subprocess

    monkeypatch.setattr(idx.__dict__.get("shutil", __import__("shutil")),
                        "which", lambda nama: "/usr/bin/google-chrome"
                        if nama == "google-chrome" else None)

    def _jalankan(*a, **k):
        return type("R", (), {"stdout": "Google Chrome 140.0.7339.207 \n"})()

    monkeypatch.setattr(subprocess, "run", _jalankan)
    assert idx._chrome_major() == 140


# =========================
# SATU PERMINTAAN, SATU IDENTITAS
# =========================
# Kode lama cuma menimpa User-Agent, sementara curl_cffi tetap mengirim
# sec-ch-ua bawaannya sendiri. Hasilnya satu permintaan membawa DUA identitas:
#     User-Agent        : Mozilla/5.0 (X11; Linux x86_64) Chrome/150
#     Sec-Ch-Ua         : "Google Chrome";v="146"
#     Sec-Ch-Ua-Platform: "macOS"
# Pertentangan itu tanda bot yang paling gampang dikenali, dan Cloudflare
# membalasnya dengan challenge baru (cf-mitigated: challenge) walau
# cf_clearance-nya sah -- sementara Chrome yang memanen cookie itu membuka
# URL yang sama dan mendapat JSON tanpa hambatan.

UA_LINUX = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36")


def test_client_hints_diambil_dari_chrome_yang_memanen_cookie(idx, monkeypatch):
    """Nilainya datang dari navigator.userAgentData Chrome ITU SENDIRI, bukan
    dikarang -- jadi saat Chrome di server diperbarui, header ikut berubah
    tanpa ada yang perlu menyunting kode."""
    monkeypatch.setitem(idx._cache, "ch", {
        "brands": '"Chromium";v="150", "Google Chrome";v="150"',
        "mobile": "?0", "platform": '"Linux"'})
    h = idx._header_permintaan(UA_LINUX, "application/json")
    assert h["sec-ch-ua"] == '"Chromium";v="150", "Google Chrome";v="150"'
    assert h["sec-ch-ua-platform"] == '"Linux"'
    assert h["sec-ch-ua-mobile"] == "?0"


def test_platform_tidak_pernah_bertentangan_dengan_user_agent(idx, monkeypatch):
    """INI bug-nya. Tanpa client hints pun, platform WAJIB mengikuti UA --
    membiarkan bawaan curl_cffi ('macOS') melawan UA Linux adalah persis
    kontradiksi yang membuat Cloudflare menolak."""
    monkeypatch.setitem(idx._cache, "ch", None)
    for ua, harus in (
        (UA_LINUX, '"Linux"'),
        ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/150.0.0.0", '"Windows"'),
        ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/150.0.0.0", '"macOS"'),
    ):
        h = idx._header_permintaan(ua, "application/json")
        assert h["sec-ch-ua-platform"] == harus, f"UA {ua[:40]!r} -> {h['sec-ch-ua-platform']}"


def test_referer_disertakan(idx, monkeypatch):
    """Permintaan ke API ini di browser selalu berasal dari situsnya sendiri;
    tanpa Referer ia terlihat datang entah dari mana."""
    monkeypatch.setitem(idx._cache, "ch", None)
    h = idx._header_permintaan(UA_LINUX, "application/json")
    assert "idx.co.id" in h["Referer"]
    assert h["User-Agent"] == UA_LINUX


def test_user_agent_selalu_yang_memanen_cookie_bukan_bawaan(idx, monkeypatch):
    """cf_clearance dinilai bersama identitas pemintanya. UA yang dikirim
    HARUS milik Chrome yang memecahkan challenge, bukan UA bawaan curl_cffi."""
    monkeypatch.setitem(idx._cache, "ch", {"brands": 'x', "mobile": "?0",
                                           "platform": '"Linux"'})
    h = idx._header_permintaan(UA_LINUX, "*/*")
    assert h["User-Agent"] == UA_LINUX
    assert h["Accept"] == "*/*"


@pytest.mark.parametrize("nilai_aneh", [
    [("brands", "x")],          # list pasangan -- bentuk yang benar-benar terjadi
    ["brands", "x"],
    "bukan dict",
    42,
])
def test_client_hints_berbentuk_aneh_tidak_menjatuhkan_pengambilan(idx, monkeypatch,
                                                                   nilai_aneh):
    """page.evaluate() nodriver tidak menjamin objek JS kembali sebagai dict.
    Terjadi nyata 18 Sep 2026: nilainya kembali sebagai LIST, `ch.get(...)`
    melempar AttributeError, dan seluruh pengambilan data kepemilikan roboh --
    di jalur yang justru sedang diperbaiki.

    Kehilangan client hints cuma membuat permintaan kurang meyakinkan;
    meledak di sini menjatuhkan semuanya. Perbandingan itu yang menentukan
    fungsi ini harus memaafkan, bukan menuntut."""
    monkeypatch.setitem(idx._cache, "ch", nilai_aneh)
    h = idx._header_permintaan(UA_LINUX, "application/json")
    assert h["User-Agent"] == UA_LINUX
    # Platform tetap wajib sepakat dengan UA walau client hints tak terpakai.
    assert h["sec-ch-ua-platform"] == '"Linux"'


# =========================
# JALUR CADANGAN: AMBIL DI DALAM BROWSER
# =========================
# Memutar ulang cf_clearance lewat klien HTTP terbukti tidak lagi bisa
# diandalkan (18 Sep 2026): sidik jari chrome150 + header konsisten + cookie
# segar tetap dibalas `cf-mitigated: challenge`, sementara Chrome yang
# memanen cookie itu membuka URL yang sama dan mendapat JSON.

def test_balasan_browser_menyerupai_response_curl_cffi(idx):
    """Pemanggil TIDAK BOLEH peduli jalur mana yang dipakai. Kalau bentuknya
    berbeda, tiap pemanggil harus menangani dua kasus -- dan yang terlupa
    akan gagal justru saat jalur cadangan sedang dibutuhkan."""
    b = idx._BalasanBrowser(200, '{"Replies": [1, 2]}')
    assert b.status_code == 200
    assert b.json()["Replies"] == [1, 2]
    assert b.content == b'{"Replies": [1, 2]}'
    assert isinstance(b.headers, dict)


def test_curl_cffi_dicoba_dulu_browser_hanya_saat_ditolak(idx, monkeypatch):
    """Jalur browser jauh lebih mahal (navigasi sungguhan). Ia cadangan, bukan
    pengganti -- dan kalau Cloudflare melonggar, jalur murah dipakai lagi
    dengan sendirinya tanpa ada yang perlu menyunting apa pun."""
    import asyncio

    dipakai = []

    class _Resp:
        def __init__(self, kode):
            self.status_code = kode
            self.text = "{}"
            self.headers = {}

    async def _sesi(force=False):
        return {"cf_clearance": "x"}, UA_LINUX

    async def _agent(url):
        dipakai.append("browser")
        return idx._BalasanBrowser(200, '{"ok": true}')

    monkeypatch.setattr(idx, "get_session", _sesi)
    monkeypatch.setattr(idx, "_agent_get", _agent)
    monkeypatch.setattr(idx, "_target_impersonate", lambda: "chrome150")

    # (a) curl_cffi langsung 200 -> browser TIDAK disentuh
    palsu = type("M", (), {"get": staticmethod(lambda *a, **k: _Resp(200))})
    monkeypatch.setitem(__import__("sys").modules, "curl_cffi",
                        type("P", (), {"requests": palsu}))
    r = asyncio.run(idx._idx_get("https://x", timeout=5, accept="application/json"))
    assert r.status_code == 200 and dipakai == []

    # (b) 403 terus-menerus -> baru jatuh ke browser
    palsu2 = type("M", (), {"get": staticmethod(lambda *a, **k: _Resp(403))})
    monkeypatch.setitem(__import__("sys").modules, "curl_cffi",
                        type("P", (), {"requests": palsu2}))
    r = asyncio.run(idx._idx_get("https://x", timeout=5, accept="application/json"))
    assert dipakai == ["browser"], "tidak jatuh ke jalur cadangan saat ditolak"
    assert r.json()["ok"] is True


# =========================
# JANGAN MENGULANG YANG SEDANG PASTI GAGAL
# =========================
# Versi sebelumnya memanggil get_session(force=True) pada SETIAP 403. Itu
# bukan sekadar sia-sia: satu solve berarti menyalakan Chrome dan
# menyelesaikan challenge, sekitar 15 detik. Karena curl_cffi saat ini selalu
# ditolak, menyapu riwayat 90 hari berarti 90 solve penuh -- bermenit-menit,
# sekaligus menembaki Cloudflare berulang kali.

def _pasang_cffi(monkeypatch, kode):
    import sys as _s
    resp = type("R", (), {"status_code": kode, "text": "{}", "headers": {}})
    palsu = type("M", (), {"get": staticmethod(lambda *a, **k: resp())})
    monkeypatch.setitem(_s.modules, "curl_cffi", type("P", (), {"requests": palsu}))


def test_curl_cffi_diistirahatkan_sesudah_sekali_ditolak(idx, monkeypatch):
    import asyncio

    jejak = []

    async def _sesi(force=False):
        jejak.append(f"solve(force={force})")
        return {"cf_clearance": "x"}, UA_LINUX

    async def _agent(url):
        jejak.append("browser")
        return idx._BalasanBrowser(200, '{"ok": true}')

    monkeypatch.setattr(idx, "_cffi_istirahat_sampai", 0.0, raising=False)
    monkeypatch.setattr(idx, "get_session", _sesi)
    monkeypatch.setattr(idx, "_agent_get", _agent)
    monkeypatch.setattr(idx, "_target_impersonate", lambda: "chrome150")
    _pasang_cffi(monkeypatch, 403)

    for _ in range(5):
        asyncio.run(idx._idx_get("https://x", timeout=5, accept="application/json"))

    # Solve HANYA sekali (percobaan pertama). Sesudah ditolak, tidak ada lagi
    # Chrome yang dinyalakan -- itu yang membuat 90 URL jadi bermenit-menit.
    assert jejak.count("solve(force=False)") == 1, jejak
    assert "solve(force=True)" not in jejak, "masih ada solve paksa per permintaan"
    assert jejak.count("browser") == 5, jejak


def test_curl_cffi_dicoba_lagi_sesudah_masa_istirahat_lewat(idx, monkeypatch):
    """Pemulihan harus OTOMATIS. Kalau Cloudflare melonggar, jalur murah wajib
    dipakai lagi tanpa ada yang perlu menyunting atau me-restart apa pun."""
    import asyncio

    async def _sesi(force=False):
        return {"cf_clearance": "x"}, UA_LINUX

    async def _agent(url):
        return idx._BalasanBrowser(200, "{}")

    monkeypatch.setattr(idx, "get_session", _sesi)
    monkeypatch.setattr(idx, "_agent_get", _agent)
    monkeypatch.setattr(idx, "_target_impersonate", lambda: "chrome150")

    # Masa istirahat sudah lewat, dan Cloudflare kini menerima.
    monkeypatch.setattr(idx, "_cffi_istirahat_sampai", 0.0, raising=False)
    _pasang_cffi(monkeypatch, 200)
    r = asyncio.run(idx._idx_get("https://x", timeout=5, accept="application/json"))
    assert r.status_code == 200
    assert idx._cffi_istirahat_sampai == 0.0, "diistirahatkan padahal tidak ditolak"


# ===========================================================================
# "Jalan di shell, mati di service" -- kelas kegagalan yang tidak pernah
# terlihat saat diuji manual, karena yang diuji bukan yang dipakai produksi.
# ===========================================================================

def test_proses_browser_membungkus_diri_saat_display_kosong(monkeypatch):
    """Chrome headed butuh DISPLAY. Shell selalu memanggil lewat `xvfb-run -a`,
    unit systemd memanggil uvicorn langsung -- jadi fitur ini bisa lolos setiap
    pengujian manual dan tetap mati di server.

    Syaratnya tidak boleh dititipkan ke berkas unit: berkas unit tidak ikut
    ter-`git pull` dan harus diingat orang. Prosesnya membungkus dirinya."""
    import core.idx_cf as idx

    import shutil as _sh

    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setattr(_sh, "which",
                        lambda n: "/usr/bin/xvfb-run" if n == "xvfb-run" else None)

    perintah = idx._perintah_browser("/apa/saja.py")
    assert perintah[0].endswith("xvfb-run"), f"tidak dibungkus xvfb-run: {perintah}"
    assert "-a" in perintah
    assert perintah[-1] == "/apa/saja.py"


def test_tidak_membungkus_dua_kali_kalau_display_sudah_ada(monkeypatch):
    """Dijalankan dari shell di bawah xvfb-run, DISPLAY sudah ada. Membungkus
    lagi berarti Xvfb di dalam Xvfb -- pemborosan yang gagalnya tidak jelas."""
    import shutil as _sh

    import core.idx_cf as idx

    monkeypatch.setenv("DISPLAY", ":99")
    monkeypatch.setattr(_sh, "which", lambda n: "/usr/bin/xvfb-run")
    perintah = idx._perintah_browser("/apa/saja.py")
    assert "xvfb-run" not in perintah[0]
    assert perintah[-1] == "/apa/saja.py"


def test_gagal_start_menyebutkan_sebabnya_bukan_titik_dua_kosong():
    """Kalau Chrome tidak bisa membuka display, stdout langsung EOF dan baris
    pertamanya kosong -- sedangkan alasannya ada di stderr. Versi lama
    melaporkan "pelayan browser idx gagal start:" tanpa apa pun sesudahnya,
    dan penelusuran jadi berangkat dari nol padahal jawabannya sudah dicetak."""
    import asyncio

    import core.idx_cf as idx

    class _StderrPalsu:
        """Pipa yang mengantar traceback SEPOTONG-SEPOTONG, seperti aslinya."""

        def __init__(self):
            self.antrean = [b"Traceback (most recent call last):\n",
                            b'  File "scripts/idx_agent.py", line 96\n',
                            b"ModuleNotFoundError: No module named 'nodriver'\n",
                            b""]

        async def read(self, n):
            return self.antrean.pop(0) if self.antrean else b""

    class _ProcPalsu:
        stderr = _StderrPalsu()

    sebab = asyncio.run(idx._ekor_stderr(_ProcPalsu()))
    # Yang WAJIB selamat adalah baris PENUTUPnya. Versi pertama memakai satu
    # read() dan cuma mendapat "Traceback (most recent call last):" -- persis
    # baris yang tidak memberi tahu apa pun. Itu terjadi sungguhan di server
    # 18 Sep 2026: pesannya buntu padahal sebabnya sudah tercetak di bawahnya.
    assert "ModuleNotFoundError" in sebab, (
        f"sebab sebenarnya hilang, yang tersisa cuma: {sebab!r}")
    assert sebab.strip(), "ekor stderr kosong -- pesan gagal akan buntu lagi"


def test_membunuh_pelayan_ikut_membunuh_anaknya():
    """xvfb-run adalah PEMBUNGKUS, bukan Chrome-nya. Membunuh pembungkusnya
    saja meninggalkan Xvfb dan Chrome hidup; beberapa kali gagal-dan-ulang
    menumpuk Chrome yatim sampai memori server habis -- kegagalan yang
    muncul jauh dari sebabnya."""
    import os

    import core.idx_cf as idx

    opsi = idx._opsi_sesi_baru()
    if os.name == "posix":
        assert opsi.get("start_new_session") is True, (
            "tanpa sesi sendiri, grup prosesnya tidak bisa dibunuh utuh")
    else:
        assert opsi == {}
