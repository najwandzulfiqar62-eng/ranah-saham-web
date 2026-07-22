"""Selesaikan Cloudflare managed-challenge idx.co.id, cetak cookie + UA (JSON).

Dijalankan sebagai SUBPROCESS oleh core/idx_cf.py -- BUKAN diimpor ke proses
uvicorn. Alasan subprocess (bukan panggil nodriver langsung di event loop
FastAPI):
  - Chrome (~300MB) benar-benar tereklaim tiap solve saat proses ini exit;
    tidak menumpuk memori/zombie di proses server yang hidup lama.
  - Isolasi total dari event loop utama (nodriver punya loop/subprocess CDP
    sendiri) -- solve yang macet/crash tidak bisa menjatuhkan server.

KONTEKS (diuji 2026-07-22 di VPS Biznet Gio, IP datacenter):
  idx.co.id di belakang Cloudflare. Dari IP rumah: 200 langsung, tanpa
  challenge. Dari IP datacenter/VPS: Cloudflare menyajikan challenge
  "Just a moment..."/"Tunggu sebentar...". curl/cloudscraper/httpx -> 403.
  Playwright + stealth (headless MAUPUN headed) -> challenge macet, karena
  Cloudflare mendeteksi lapisan otomasi CDP. `nodriver` (headed, di bawah
  Xvfb) menghindari deteksi itu -> challenge selesai ~6-7 dtk.

  PENTING: headless TETAP kena hard-block ("Attention Required"); WAJIB
  headed + display nyata (Xvfb). cf_clearance yang dihasilkan terikat pada
  TLS/JA3 fingerprint Chrome -> lihat core/idx_cf.py yang memakainya ulang
  via curl_cffi impersonate="chrome".

Output (stdout): tepat satu baris diawali 'RESULT_JSON:' berisi
  {"cookies": {...}, "ua": "..."}. Log/nnoise lain -> stderr.
Prasyarat: Google Chrome stable + DISPLAY (Xvfb) aktif.
"""
import asyncio
import json
import sys

MAIN = "https://www.idx.co.id/id"
CHALLENGE = ("just a moment", "tunggu sebentar", "attention required",
             "checking your browser", "sebentar", "moment")
MAX_WAIT_S = 45


async def main() -> int:
    import nodriver as uc

    browser = await uc.start(
        headless=False,
        browser_args=["--no-sandbox", "--disable-dev-shm-usage",
                      "--window-size=1366,768"],
    )
    try:
        page = await browser.get(MAIN)
        title = ""
        for _ in range(MAX_WAIT_S):
            await asyncio.sleep(1)
            try:
                title = (await page.evaluate("document.title")) or ""
            except Exception:
                title = ""
            t = title.lower()
            if t.strip() and not any(c in t for c in CHALLENGE):
                break
        else:
            print(f"challenge idx.co.id tidak selesai (judul terakhir: {title!r})",
                  file=sys.stderr)
            return 2

        cookies_raw = await browser.cookies.get_all()
        ua = await page.evaluate("navigator.userAgent")
        jar = {c.name: c.value for c in cookies_raw
               if "idx.co.id" in (c.domain or "")}
        if "cf_clearance" not in jar:
            print("cf_clearance tidak ditemukan setelah solve", file=sys.stderr)
            return 3
        print("RESULT_JSON:" + json.dumps({"cookies": jar, "ua": ua}))
        return 0
    finally:
        try:
            browser.stop()
        except Exception:
            pass


if __name__ == "__main__":
    import nodriver as uc
    sys.exit(uc.loop().run_until_complete(main()))
