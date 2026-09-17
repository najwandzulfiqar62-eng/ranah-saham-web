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
