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
