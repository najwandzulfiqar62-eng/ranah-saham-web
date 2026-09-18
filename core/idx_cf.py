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

Prasyarat runtime di server: Google Chrome stable + paket xvfb. DISPLAY
TIDAK perlu di-set di unit systemd -- proses browsernya membungkus dirinya
sendiri dengan xvfb-run saat DISPLAY kosong (lihat _perintah_browser).
Syarat yang harus diingat orang dan tidak ikut ter-`git pull` adalah syarat
yang cepat atau lambat terlupa, dan itulah yang membuat fitur ini jalan saat
diuji dari shell tapi mati di service.

Import berat (curl_cffi) dilakukan di dalam fungsi supaya modul ini AMAN
diimpor di mesin dev/test tanpa dependensi itu.
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


def _perintah_browser(script: str) -> list[str]:
    """Perintah untuk menjalankan skrip yang butuh Chrome BERJENDELA.

    KENAPA ADA -- ini sebab "jalan waktu dicoba manual, mati di server".
    Chrome headed perlu DISPLAY. Di shell perintahnya selalu diawali
    `xvfb-run -a`, jadi DISPLAY ada dan semuanya bekerja. Tapi unit systemd
    memanggil uvicorn langsung: tidak ada xvfb-run, tidak ada DISPLAY, dan
    Chrome mati sebelum sempat membuka apa pun. Dua cara menjalankan yang
    sama sekali berbeda, dan yang dipakai saat menguji justru bukan yang
    dipakai di produksi.

    Ketimbang menitipkan syarat itu ke berkas unit (yang harus diingat orang
    dan tidak ikut ter-`git pull`), prosesnya membungkus dirinya sendiri:
    kalau DISPLAY kosong dan xvfb-run ada, ia dipakai. Kalau DISPLAY sudah
    ada -- misalnya sudah dijalankan di bawah xvfb-run dari shell -- tidak
    dibungkus dua kali.
    """
    import shutil

    dasar = [sys.executable, script]
    if os.environ.get("DISPLAY"):
        return dasar
    xvfb = shutil.which("xvfb-run")
    if not xvfb:
        # Biarkan gagal di Chrome, bukan di sini: pesan dari Chrome jauh
        # lebih menunjuk daripada tebakan kita tentang sebabnya.
        return dasar
    return [xvfb, "-a", "--server-args=-screen 0 1366x768x24"] + dasar


def _opsi_sesi_baru() -> dict:
    """Jalankan subprocess di grup proses sendiri, supaya bisa dibunuh utuh.

    Perlu karena pembungkus xvfb-run bukan Chrome-nya: membunuh xvfb-run saja
    meninggalkan Chrome dan Xvfb hidup sebagai yatim. Beberapa kali gagal dan
    coba lagi akan menumpuk Chrome yang tak terpakai sampai memori server
    habis -- kegagalan yang muncul jauh dari sebabnya.
    """
    if os.name == "posix":
        return {"start_new_session": True}
    return {}


def _bunuh_pohon(proc) -> None:
    """Bunuh subprocess BESERTA anak-anaknya (xvfb-run -> Xvfb -> Chrome)."""
    if proc is None:
        return
    try:
        if os.name == "posix":
            import signal
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        else:
            proc.kill()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


async def _ekor_stderr(proc, batas: int = 1200) -> str:
    """Baca sisa stderr subprocess tanpa menggantung kalau ia masih hidup.

    Sebelum ini ada, kegagalan start terbaca sebagai "pelayan browser idx
    gagal start:" -- titik, tanpa apa pun sesudahnya. Sebabnya: kalau Chrome
    mati, stdout langsung EOF (baris kosong), sedangkan alasan sebenarnya
    ada di stderr yang tidak pernah dibaca. Pesan kosong itu membuat
    penelusuran berangkat dari nol padahal jawabannya sudah tercetak.

    DIBACA SAMPAI HABIS, bukan sekali ambil. Versi pertama memakai satu
    `read(8192)`, dan itu mengembalikan apa yang KEBETULAN sudah sampai di
    pipa saat itu -- untuk sebuah traceback Python yang berarti cuma
    "Traceback (most recent call last):", persis baris yang paling tidak
    memberi tahu apa-apa. Terbukti 18 Sep 2026 di server: pesannya berhenti
    di situ dan penelusuran tetap buntu walau alasannya sudah dicetak dua
    baris di bawahnya.

    Potongan terakhir yang disimpan (bukan yang pertama), karena baris
    penutup traceback-lah yang menyebut jenis dan pesan galatnya.
    """
    if proc.stderr is None:
        return ""
    potongan = []
    tenggat = time.monotonic() + 3.0
    while True:
        sisa = tenggat - time.monotonic()
        if sisa <= 0:
            break
        try:
            data = await asyncio.wait_for(proc.stderr.read(4096), timeout=sisa)
        except Exception:
            break
        if not data:
            break   # EOF: prosesnya sudah menutup stderr
        potongan.append(data)
    teks = b"".join(potongan).decode("utf-8", "replace")
    return " ".join(teks.split())[-batas:]


class IdxCfError(RuntimeError):
    """Gagal menembus Cloudflare idx.co.id (solve gagal / tetap 403).

    SENGAJA exception sendiri -- konsumen (mis. _fetch_x15_today) harus
    membedakan ini dari 'tidak ada filing' (list kosong). Jangan pernah
    menyulap kegagalan jadi list kosong."""


async def _run_solver() -> tuple[dict, str, dict | None]:
    """Jalankan scripts/idx_solve.py sbg subprocess -> (cookies, ua, client-hints)."""
    proc = await asyncio.create_subprocess_exec(
        *_perintah_browser(_SOLVE_SCRIPT),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        **_opsi_sesi_baru(),
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=_SOLVE_TIMEOUT)
    except asyncio.TimeoutError:
        _bunuh_pohon(proc)
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
    # SENGAJA defensif: kehilangan client hints cuma membuat permintaan
    # kurang meyakinkan, sedangkan meledak di sini menjatuhkan SELURUH
    # pengambilan data kepemilikan. Terjadi nyata 18 Sep 2026 -- nilainya
    # kembali sebagai list, dan `ch.get(...)` melempar AttributeError yang
    # merobohkan jalur yang justru sedang diperbaiki.
    ch = _cache.get("ch")
    if not isinstance(ch, dict):
        ch = {}
    if ch.get("brands"):
        h["sec-ch-ua"] = ch["brands"]
        h["sec-ch-ua-mobile"] = ch.get("mobile") or "?0"
        h["sec-ch-ua-platform"] = ch.get("platform") or _platform_dari_ua(ua)
    else:
        # Chrome lama tanpa userAgentData: setidaknya samakan platformnya
        # dengan UA, jangan biarkan bawaan curl_cffi bertentangan.
        h["sec-ch-ua-platform"] = _platform_dari_ua(ua)
    return h


# Berapa lama jalur curl_cffi diistirahatkan sesudah ia ditolak. Selama
# jendela ini, permintaan langsung dilayani pelayan browser.
_CFFI_ISTIRAHAT = int(os.getenv("IDX_CFFI_ISTIRAHAT", "1800"))   # 30 menit
_cffi_istirahat_sampai = 0.0


async def _idx_get(url: str, *, timeout: int, accept: str):
    """GET url idx.co.id. Coba curl_cffi (murah); kalau ditolak, lewat browser.

    PENTING -- JANGAN MENCOBA ULANG YANG SEDANG PASTI GAGAL. Versi sebelumnya
    memanggil get_session(force=True) pada SETIAP 403, dan itu bukan sekadar
    sia-sia: satu solve berarti menyalakan Chrome dan menyelesaikan challenge,
    sekitar 15 detik. Karena curl_cffi saat ini selalu ditolak, menyapu
    riwayat 90 hari berarti 90 kali solve penuh -- bermenit-menit, sekaligus
    menembaki Cloudflare berulang kali (yang justru menaikkan penjagaannya).

    Sekarang: begitu ditolak SEKALI, jalur curl_cffi diistirahatkan selama
    _CFFI_ISTIRAHAT dan permintaan berikutnya langsung ke pelayan browser --
    yang sudah memegang satu sesi hidup, jadi biayanya ~0,2 detik per URL.
    Sesudah jendela itu lewat, curl_cffi dicoba lagi sekali; kalau Cloudflare
    sudah melonggar, jalur murah dipakai lagi dengan sendirinya.
    """
    global _cffi_istirahat_sampai

    # Sedang istirahat: jangan sentuh curl_cffi, dan JANGAN memanggil
    # get_session -- pelayan browser memegang sesinya sendiri, jadi solve di
    # sini cuma menambah satu Chrome lagi tanpa guna.
    if time.time() < _cffi_istirahat_sampai:
        return await _agent_get(url)

    from curl_cffi import requests as _cffi

    loop = asyncio.get_event_loop()
    cookies, ua = await get_session()

    def _do(_cookies, _ua):
        return _cffi.get(url, headers=_header_permintaan(_ua, accept),
                         cookies=_cookies, impersonate=_target_impersonate(),
                         timeout=timeout)

    resp = await loop.run_in_executor(None, _do, cookies, ua)
    if resp.status_code != 403:
        return resp

    _cffi_istirahat_sampai = time.time() + _CFFI_ISTIRAHAT
    print(f"\u2139\ufe0f idx_cf: curl_cffi ditolak ({resp.status_code}); "
          f"pakai pelayan browser selama {_CFFI_ISTIRAHAT // 60} menit", flush=True)
    return await _agent_get(url)


_AGENT_SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "scripts", "idx_agent.py")
_AGENT_START_TIMEOUT = int(os.getenv("IDX_AGENT_START_TIMEOUT", "90"))
_AGENT_REQ_TIMEOUT = int(os.getenv("IDX_AGENT_REQ_TIMEOUT", "40"))
_agent = {"proc": None}
_agent_lock = asyncio.Lock()


class _BalasanBrowser:
    """Menyerupai Response curl_cffi seperlunya, supaya pemanggil tidak peduli
    jalur mana yang dipakai."""

    def __init__(self, status: int, teks: str):
        self.status_code = status
        self.text = teks
        self.headers = {}

    @property
    def content(self) -> bytes:
        return (self.text or "").encode("utf-8", "replace")

    def json(self):
        return json.loads(self.text)


async def _agent_mati():
    _bunuh_pohon(_agent.get("proc"))
    _agent["proc"] = None


async def _agent_hidup():
    """Nyalakan pelayan browser bila belum ada, tunggu sampai ia berkata READY."""
    p = _agent.get("proc")
    if p is not None and p.returncode is None:
        return p

    proc = await asyncio.create_subprocess_exec(
        *_perintah_browser(_AGENT_SCRIPT),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, **_opsi_sesi_baru(),
    )
    try:
        baris = await asyncio.wait_for(proc.stdout.readline(),
                                       timeout=_AGENT_START_TIMEOUT)
    except asyncio.TimeoutError:
        sebab = await _ekor_stderr(proc)
        _bunuh_pohon(proc)
        raise IdxCfError(
            f"pelayan browser idx tidak siap dalam {_AGENT_START_TIMEOUT}s"
            + (f" -- {sebab}" if sebab else ""))

    pesan = baris.decode("utf-8", "replace").strip()
    if pesan != "READY":
        # Stderr DULU, baru stdout. Kalau Chrome tidak bisa membuka display,
        # stdout langsung EOF dan `pesan` kosong -- alasannya cuma ada di
        # stderr, dan tanpa ini pesannya berhenti di titik dua.
        sebab = await _ekor_stderr(proc) or pesan[:200] or "berhenti tanpa pesan"
        _bunuh_pohon(proc)
        if "DISPLAY" in sebab or "display" in sebab:
            sebab += (" | DISPLAY tidak ada dan xvfb-run tidak ditemukan: "
                      "pasang paket xvfb di server")
        raise IdxCfError(f"pelayan browser idx gagal start: {sebab}")

    _agent["proc"] = proc
    print("\u2139\ufe0f idx_cf: pelayan browser siap", flush=True)
    return proc


async def _agent_get(url: str) -> _BalasanBrowser:
    """Ambil URL DI DALAM browser yang memecahkan challenge.

    Dipakai saat curl_cffi ditolak. Lebih lambat (navigasi sungguhan), tapi
    inilah satu-satunya jalur yang terbukti diterima Cloudflare -- lihat
    catatan di scripts/idx_agent.py.
    """
    async with _agent_lock:
        proc = await _agent_hidup()
        try:
            proc.stdin.write((url + "\n").encode())
            await proc.stdin.drain()
            baris = await asyncio.wait_for(proc.stdout.readline(),
                                           timeout=_AGENT_REQ_TIMEOUT)
        except Exception as e:
            await _agent_mati()
            raise IdxCfError(f"pelayan browser idx putus: {type(e).__name__}: {e}")

    if not baris:
        await _agent_mati()
        raise IdxCfError("pelayan browser idx berhenti tanpa menjawab")
    try:
        data = json.loads(baris.decode("utf-8", "replace"))
    except Exception:
        raise IdxCfError("jawaban pelayan browser idx tidak terbaca")
    if data.get("error"):
        raise IdxCfError(f"pelayan browser idx: {data['error'][:200]}")
    return _BalasanBrowser(int(data.get("status") or 0), data.get("text") or "")


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
