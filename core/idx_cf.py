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
_cache = {"cookies": None, "ua": None, "ts": 0.0}


class IdxCfError(RuntimeError):
    """Gagal menembus Cloudflare idx.co.id (solve gagal / tetap 403).

    SENGAJA exception sendiri -- konsumen (mis. _fetch_x15_today) harus
    membedakan ini dari 'tidak ada filing' (list kosong). Jangan pernah
    menyulap kegagalan jadi list kosong."""


async def _run_solver() -> tuple[dict, str]:
    """Jalankan scripts/idx_solve.py sbg subprocess, kembalikan (cookies, ua)."""
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
            return data["cookies"], data["ua"]
    tail = err.decode("utf-8", "replace").strip()[-300:]
    raise IdxCfError(f"solve Cloudflare idx.co.id gagal (rc={proc.returncode}): {tail}")


async def get_session(force: bool = False) -> tuple[dict, str]:
    """(cookies, user_agent) untuk idx.co.id; refresh via browser bila perlu."""
    now = time.time()
    if not force and _cache["cookies"] and (now - _cache["ts"] < _SESSION_TTL):
        return _cache["cookies"], _cache["ua"]
    async with _lock:
        now = time.time()
        if not force and _cache["cookies"] and (now - _cache["ts"] < _SESSION_TTL):
            return _cache["cookies"], _cache["ua"]
        cookies, ua = await _run_solver()
        _cache.update(cookies=cookies, ua=ua, ts=time.time())
        return cookies, ua


async def _idx_get(url: str, *, timeout: int, accept: str):
    """GET url idx.co.id via curl_cffi (JA3 Chrome) + cookie cf_clearance.
    Sekali kena 403 -> paksa refresh cookie & ulang. Return curl_cffi Response."""
    from curl_cffi import requests as _cffi

    loop = asyncio.get_event_loop()
    cookies, ua = await get_session()

    def _do(_cookies, _ua):
        return _cffi.get(url, headers={"User-Agent": _ua, "Accept": accept},
                         cookies=_cookies, impersonate="chrome", timeout=timeout)

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
