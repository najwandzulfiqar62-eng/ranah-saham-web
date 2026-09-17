"""Akses idx.co.id yang dilindungi Cloudflare dari IP datacenter (VPS).

RINGKAS (bukti uji 2026-07-22, VPS Biznet Gio):
  - idx.co.id di belakang Cloudflare. IP rumah -> 200 tanpa challenge. IP
    datacenter/VPS -> challenge "Just a moment...". curl/cloudscraper/httpx
    -> 403. Playwright/stealth (headless & headed) -> challenge macet
    (Cloudflare mendeteksi CDP). `nodriver` headed di bawah Xvfb -> selesai
    ~6-7 dtk (lihat scripts/idx_solve.py).
  - cf_clearance TERIKAT TLS/JA3 Chrome. httpx pakai cookie itu -> 403.
    `curl_cffi` impersonate="chrome" meniru JA3 Chrome -> cookie diterima
    -> 200. Jadi browser dipakai HANYA memanen cookie (mahal, sesekali);
    semua fetch nyata pakai curl_cffi murah.

Alur: get_session() -> kalau cache basi, jalankan scripts/idx_solve.py
sebagai subprocess (Chrome tereklaim bersih tiap kali), simpan cookie+UA.
idx_get_json / idx_get_bytes -> curl_cffi dgn cookie; sekali 403 -> paksa
refresh cookie & ulang.

Prasyarat runtime di server: Google Chrome stable + Xvfb (DISPLAY di-set di
environment service). Import berat (curl_cffi) dilakukan di dalam fungsi
supaya modul ini AMAN diimpor di mesin dev/test tanpa dependensi itu.
"""
import asyncio
import json
import os
import sys
import time

_SOLVE_SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "scripts", "idx_solve.py")
_SESSION_TTL = int(os.getenv("IDX_CF_SESSION_TTL", "900"))   # 15 menit
_SOLVE_TIMEOUT = int(os.getenv("IDX_CF_SOLVE_TIMEOUT", "120"))

_lock = asyncio.Lock()
_cache = {"cookies": None, "ua": None, "ch": None, "ts": 0.0}


class IdxCfError(RuntimeError):
    """Gagal menembus Cloudflare idx.co.id (solve gagal / tetap 403).

    SENGAJA exception sendiri -- konsumen (mis. _fetch_x15_today) harus
    membedakan ini dari 'tidak ada filing' (list kosong). Jangan pernah
    menyulap kegagalan jadi list kosong."""


async def _run_solver() -> tuple[dict, str, dict | None]:
    """Jalankan scripts/idx_solve.py sbg subprocess -> (cookies, ua, client-hints)."""
    proc = await asyncio.create_subprocess_exec(
        sys.executable, _SOLVE_SCRIPT,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=_SOLVE_TIMEOUT)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        raise IdxCfError(f"solve Cloudflare idx.co.id timeout (>{_SOLVE_TIMEOUT}s)")

    for line in out.decode("utf-8", "replace").splitlines():
        if line.startswith("RESULT_JSON:"):
            data = json.loads(line[len("RESULT_JSON:"):])
            return data["cookies"], data["ua"], data.get("ch")
    tail = err.decode("utf-8", "replace").strip()[-300:]
    raise IdxCfError(f"solve Cloudflare idx.co.id gagal (rc={proc.returncode}): {tail}")


async def get_session(force: bool = False) -> tuple[dict, str]:
    """(cookies, user_agent) untuk idx.co.id; refresh via browser bila perlu.

    Client-hints ikut disimpan di _cache["ch"] -- lihat _header_permintaan().
    """
    now = time.time()
    if not force and _cache["cookies"] and (now - _cache["ts"] < _SESSION_TTL):
        return _cache["cookies"], _cache["ua"]
    async with _lock:
        now = time.time()
        if not force and _cache["cookies"] and (now - _cache["ts"] < _SESSION_TTL):
            return _cache["cookies"], _cache["ua"]
        cookies, ua, ch = await _run_solver()
        _cache.update(cookies=cookies, ua=ua, ch=ch, ts=time.time())
        return cookies, ua


_impersonate_cache = None


def _chrome_major() -> int | None:
    """Versi mayor Chrome yang terpasang di server, dari `--version`."""
    import re
    import shutil
    import subprocess

    for nama in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        jalur = shutil.which(nama)
        if not jalur:
            continue
        try:
            keluar = subprocess.run([jalur, "--version"], capture_output=True,
                                    text=True, timeout=10).stdout
        except Exception:
            continue
        m = re.search(r"(\d+)\.\d+\.\d+", keluar or "")
        if m:
            return int(m.group(1))
    return None


def _target_impersonate() -> str:
    """Target JA3 curl_cffi yang COCOK dengan Chrome di server ini.

    KENAPA BUKAN "chrome" SAJA: alias itu MENGAMBANG -- ia menunjuk Chrome
    terbaru yang didukung versi curl_cffi yang sedang terpasang. Saat
    curl_cffi dimutakhirkan (18 Sep 2026: 0.7 -> 0.16.3), alias itu melompat
    ke sidik jari yang jauh lebih baru daripada Chrome yang BENAR-BENAR
    memecahkan challenge di server.

    Dan cf_clearance TERIKAT pada sidik jari itu. Begitu keduanya tidak lagi
    sepadan, idx.co.id membalas 403 walau cookienya sah dan baru saja didapat
    -- kegagalan yang menyesatkan, karena semua yang kelihatan (solver jalan,
    cookie ada) justru tampak benar.

    Jadi targetnya diturunkan dari versi Chrome yang terpasang: dipilih
    `chromeNNN` tertinggi yang TIDAK melebihi Chrome asli. Kalau Chrome
    diperbarui suatu hari, fungsi ini ikut menyesuaikan sendiri.
    IDX_IMPERSONATE bisa dipakai memaksa nilai tertentu saat menelusuri.
    """
    global _impersonate_cache
    if _impersonate_cache:
        return _impersonate_cache

    paksa = os.getenv("IDX_IMPERSONATE")
    if paksa:
        _impersonate_cache = paksa
        return paksa

    tersedia = set()
    try:
        import typing

        from curl_cffi.requests.impersonate import BrowserTypeLiteral
        tersedia = set(typing.get_args(BrowserTypeLiteral))
    except Exception:
        try:
            from curl_cffi.requests import BrowserType
            tersedia = {b.value for b in BrowserType}
        except Exception:
            tersedia = set()

    major = _chrome_major()
    if major and tersedia:
        import re
        kandidat = []
        for t in tersedia:
            m = re.fullmatch(r"chrome(\d+)[a-z]?", t)   # buang varian _android
            if m:
                kandidat.append((int(m.group(1)), t))
        # Yang TIDAK melebihi Chrome asli. Meniru versi yang lebih BARU dari
        # browser yang memecahkan challenge itu persis kesalahan yang sedang
        # diperbaiki di sini.
        cocok = sorted((v, t) for v, t in kandidat if v <= major)
        if cocok:
            _impersonate_cache = cocok[-1][1]
            print(f"\u2139\ufe0f idx_cf: Chrome {major} -> impersonate={_impersonate_cache}",
                  flush=True)
            return _impersonate_cache

    _impersonate_cache = "chrome"
    return _impersonate_cache


def _platform_dari_ua(ua: str) -> str:
    """Cadangan kalau Chrome tidak memberi userAgentData."""
    u = (ua or "").lower()
    if "windows" in u:
        return '"Windows"'
    if "mac os" in u or "macintosh" in u:
        return '"macOS"'
    if "android" in u:
        return '"Android"'
    return '"Linux"'


def _header_permintaan(ua: str, accept: str) -> dict:
    """Header yang SELURUHNYA sepakat tentang siapa peminta ini.

    MASALAH YANG DITUTUP DI SINI (terukur 18 Sep 2026): kode lama cuma
    menimpa User-Agent. curl_cffi tetap mengirim sec-ch-ua bawaannya sendiri,
    jadi satu permintaan membawa DUA identitas yang bertentangan --

        User-Agent        : Mozilla/5.0 (X11; Linux x86_64) Chrome/150
        Sec-Ch-Ua         : "Google Chrome";v="146"
        Sec-Ch-Ua-Platform: "macOS"

    -- dan pertentangan itu justru tanda bot yang paling gampang dikenali.
    Cloudflare membalasnya dengan challenge baru (cf-mitigated: challenge)
    walau cf_clearance-nya sah, sementara Chrome yang memanen cookie itu
    membuka URL yang sama dan mendapat JSON tanpa hambatan.

    Client-hints diambil dari Chrome ITU SENDIRI (navigator.userAgentData),
    bukan dikarang di sini -- kalau Chrome di server diperbarui, nilainya
    ikut berubah tanpa ada yang perlu menyuntingnya.
    """
    h = {
        "User-Agent": ua,
        "Accept": accept,
        "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
        # Permintaan ke API ini di browser selalu berasal dari situsnya
        # sendiri; tanpa Referer ia terlihat datang entah dari mana.
        "Referer": "https://www.idx.co.id/id",
    }
    ch = _cache.get("ch") or {}
    if ch.get("brands"):
        h["sec-ch-ua"] = ch["brands"]
        h["sec-ch-ua-mobile"] = ch.get("mobile") or "?0"
        h["sec-ch-ua-platform"] = ch.get("platform") or _platform_dari_ua(ua)
    else:
        # Chrome lama tanpa userAgentData: setidaknya samakan platformnya
        # dengan UA, jangan biarkan bawaan curl_cffi bertentangan.
        h["sec-ch-ua-platform"] = _platform_dari_ua(ua)
    return h


async def _idx_get(url: str, *, timeout: int, accept: str):
    """GET url idx.co.id via curl_cffi (JA3 Chrome) + cookie cf_clearance.
    Sekali kena 403 -> paksa refresh cookie & ulang. Return curl_cffi Response."""
    from curl_cffi import requests as _cffi

    loop = asyncio.get_event_loop()
    cookies, ua = await get_session()

    def _do(_cookies, _ua):
        return _cffi.get(url, headers=_header_permintaan(_ua, accept),
                         cookies=_cookies, impersonate=_target_impersonate(),
                         timeout=timeout)

    resp = await loop.run_in_executor(None, _do, cookies, ua)
    if resp.status_code == 403:
        cookies, ua = await get_session(force=True)
        resp = await loop.run_in_executor(None, _do, cookies, ua)
    return resp


async def idx_get_json(url: str, *, timeout: int = 20):
    """Return (status_code, parsed_json_or_None). None kalau body bukan JSON."""
    resp = await _idx_get(url, timeout=timeout, accept="application/json")
    try:
        return resp.status_code, resp.json()
    except Exception:
        return resp.status_code, None


async def idx_get_bytes(url: str, *, timeout: int = 20) -> tuple[int, bytes]:
    """Return (status_code, content) -- untuk unduh PDF KSEI."""
    resp = await _idx_get(url, timeout=timeout, accept="*/*")
    return resp.status_code, resp.content
