"""Pelayan browser untuk idx.co.id: satu Chrome, banyak permintaan.

KENAPA ADA: memutar ulang cf_clearance lewat klien HTTP sudah tidak bisa
diandalkan. Terbukti 18 Sep 2026 -- Chrome yang memanen cookie itu membuka
URL API dan mendapat JSON, sedangkan curl_cffi dengan cookie yang sama,
sidik jari chrome150, dan header yang sudah dibuat konsisten tetap dibalas
`cf-mitigated: challenge`. Cloudflare mengikat cookienya lebih dalam daripada
yang bisa ditiru klien HTTP.

Jalan yang PASTI bekerja: ambil datanya di dalam browser itu sendiri.

DUA HAL YANG MEMBUATNYA LAYAK DIPAKAI, bukan cuma bisa:

1. SATU browser melayani BANYAK URL. Menyalakan Chrome per permintaan memakan
   ~10 detik setiap kali; riwayat 90 hari berarti 90 kali.

2. Tiap URL diambil dengan fetch() DI DALAM halaman, bukan dengan berpindah
   halaman. Versi pertama memakai navigasi dan itu ~2 detik per URL -- untuk
   90 hari jadi bermenit-menit, cukup lambat untuk membuat fiturnya tidak
   terpakai. fetch() memakai koneksi, cookie, dan sesi TLS yang sama persis
   dengan halaman yang sudah lolos challenge, jadi Cloudflare menerimanya,
   tapi biayanya tinggal ~0,2 detik.

Protokol (baris demi baris, JSON):
    <- READY                       (siap menerima)
    -> https://...                 (satu URL per baris)
    <- {"status": 200, "text": …}  (satu jawaban per baris)
    -> (EOF)                       (browser ditutup)

Prasyarat: Google Chrome stable + DISPLAY (Xvfb) aktif.
"""
import asyncio
import json
import sys

MAIN = "https://www.idx.co.id/id"
CHALLENGE = ("just a moment", "tunggu sebentar", "attention required",
             "checking your browser")
CHALLENGE_TIMEOUT_S = 45
FETCH_TIMEOUT_S = 30
POLL_S = 0.1


async def _lolos_challenge(page) -> str:
    """Tunggu halaman utama lolos challenge. Kembalikan judul terakhir."""
    judul = ""
    langkah = int(CHALLENGE_TIMEOUT_S / 0.5)
    for _ in range(langkah):
        try:
            judul = (await page.evaluate("document.title")) or ""
        except Exception:
            judul = ""
        t = judul.lower()
        if t.strip() and not any(c in t for c in CHALLENGE):
            return judul
        await asyncio.sleep(0.5)
    return judul


async def _ambil(page, url: str) -> dict:
    """fetch() di dalam halaman, hasilnya dijemput dengan polling.

    Sengaja TIDAK memakai await_promise: bentuk dukungannya berbeda-beda antar
    versi nodriver, dan kegagalan di situ akan terbaca seperti masalah
    Cloudflare padahal bukan. Pola "titipkan ke window lalu jemput" cuma
    memakai evaluate sinkron biasa, yang perilakunya sama di semua versi.
    """
    kunci = "__idx_hasil"
    pasang = (
        f"(() => {{ window.{kunci} = null;"
        f" fetch({json.dumps(url)}, {{credentials: 'include'}})"
        f"  .then(r => r.text().then(t => {{ window.{kunci} ="
        f"      JSON.stringify({{status: r.status, text: t}}); }}))"
        f"  .catch(e => {{ window.{kunci} ="
        f"      JSON.stringify({{status: 0, error: String(e)}}); }});"
        f" return 1; }})()"
    )
    await page.evaluate(pasang)

    for _ in range(int(FETCH_TIMEOUT_S / POLL_S)):
        await asyncio.sleep(POLL_S)
        try:
            hasil = await page.evaluate(f"window.{kunci}")
        except Exception:
            hasil = None
        if isinstance(hasil, str) and hasil.strip():
            try:
                return json.loads(hasil)
            except Exception:
                return {"status": 0, "error": "jawaban fetch tidak terbaca"}
    return {"status": 0, "error": f"fetch tidak selesai dalam {FETCH_TIMEOUT_S}s"}


async def main() -> int:
    import nodriver as uc

    browser = await uc.start(
        headless=False,
        browser_args=["--no-sandbox", "--disable-dev-shm-usage",
                      "--window-size=1366,768"],
    )
    try:
        page = await browser.get(MAIN)
        judul = await _lolos_challenge(page)
        if any(c in judul.lower() for c in CHALLENGE):
            print(json.dumps({"fatal": f"challenge tidak selesai (judul: {judul!r})"}),
                  flush=True)
            return 2

        print("READY", flush=True)

        loop = asyncio.get_event_loop()
        while True:
            baris = await loop.run_in_executor(None, sys.stdin.readline)
            if not baris:
                return 0
            url = baris.strip()
            if not url:
                continue
            try:
                jawaban = await _ambil(page, url)
            except Exception as e:
                jawaban = {"status": 0, "error": f"{type(e).__name__}: {e}"}
            print(json.dumps(jawaban), flush=True)
    finally:
        try:
            browser.stop()
        except Exception:
            pass


if __name__ == "__main__":
    import nodriver as uc
    sys.exit(uc.loop().run_until_complete(main()))
