"""Pelayan browser untuk idx.co.id: satu Chrome, banyak permintaan.

KENAPA ADA: memutar ulang cf_clearance lewat klien HTTP sudah tidak bisa
diandalkan. Terbukti 18 Sep 2026 -- Chrome yang memanen cookie itu membuka
URL API dan mendapat JSON, sedangkan curl_cffi dengan cookie yang sama,
sidik jari chrome150, dan header yang sudah dibuat konsisten tetap dibalas
`cf-mitigated: challenge`. Cloudflare mengikat cookienya lebih dalam daripada
yang bisa ditiru klien HTTP.

Jalan yang PASTI bekerja: ambil datanya di dalam browser itu sendiri.

Yang membuat ini layak dipakai (bukan cuma bisa): SATU browser melayani
BANYAK URL. Menyalakan Chrome per permintaan akan memakan ~10 detik setiap
kali, dan riwayat 90 hari berarti 90 kali -- tidak masuk akal. Di sini Chrome
dinyalakan sekali, challenge diselesaikan sekali, lalu URL dibaca dari stdin
satu per baris dan jawabannya ditulis ke stdout satu per baris.

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
MAX_WAIT_S = 45
WAIT_API_S = 20


async def _tunggu_bersih(page, batas: int) -> str:
    """Tunggu sampai judul halaman bukan lagi halaman challenge."""
    judul = ""
    for _ in range(batas):
        await asyncio.sleep(1)
        try:
            judul = (await page.evaluate("document.title")) or ""
        except Exception:
            judul = ""
        t = judul.lower()
        if t.strip() and not any(c in t for c in CHALLENGE):
            return judul
        # Halaman JSON tidak punya judul sama sekali -- itu justru tanda
        # berhasil, jadi periksa isinya juga alih-alih menunggu sia-sia.
        try:
            isi = (await page.evaluate(
                "document.body ? document.body.innerText.slice(0,1) : ''")) or ""
        except Exception:
            isi = ""
        if isi in ("{", "["):
            return judul
    return judul


async def main() -> int:
    import nodriver as uc

    browser = await uc.start(
        headless=False,
        browser_args=["--no-sandbox", "--disable-dev-shm-usage",
                      "--window-size=1366,768"],
    )
    try:
        page = await browser.get(MAIN)
        judul = await _tunggu_bersih(page, MAX_WAIT_S)
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
                p = await browser.get(url)
                await _tunggu_bersih(p, WAIT_API_S)
                teks = (await p.evaluate(
                    "document.body ? document.body.innerText : ''")) or ""
                judul_p = (await p.evaluate("document.title")) or ""
                # Halaman challenge -> laporkan 403 supaya pemanggil bisa
                # membedakannya dari balasan kosong yang sah.
                status = 403 if any(c in judul_p.lower() for c in CHALLENGE) else 200
                print(json.dumps({"status": status, "text": teks}), flush=True)
            except Exception as e:
                print(json.dumps({"status": 0,
                                  "error": f"{type(e).__name__}: {e}"}), flush=True)
    finally:
        try:
            browser.stop()
        except Exception:
            pass


if __name__ == "__main__":
    import nodriver as uc
    sys.exit(uc.loop().run_until_complete(main()))
