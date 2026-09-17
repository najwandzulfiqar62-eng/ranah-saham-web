"""Buka URL API IDX di Chrome yang SAMA dengan yang memanen cf_clearance.

Ini memisahkan dua sebab yang dari luar terlihat identik (403 + "Just a
moment...") tapi penanganannya bertolak belakang:

  Chrome dapat JSON  -> cookie & IP baik-baik saja; yang ditolak PERMINTAAN
                        KITA. Berarti sidik jari/header curl_cffi yang kurang
                        meyakinkan, dan itu bisa diperbaiki di kode.

  Chrome ikut kena   -> Cloudflare menolak di tingkat IP/aturan, bukan tingkat
  challenge             klien. Tidak ada perubahan kode yang menolong; yang
                        dibutuhkan waktu (reputasi IP pulih) atau jalur lain.

Menebak di antara keduanya sudah dua kali membuang waktu di penelusuran ini.

Pakai: xvfb-run -a python3 scripts/idx_probe_browser.py
"""
import asyncio
import datetime as dt
import sys

MAIN = "https://www.idx.co.id/id"
HARI = dt.datetime.now().strftime("%Y%m%d")
API = ("https://www.idx.co.id/primary/ListedCompany/GetAnnouncement"
       f"?emitenType=*&indexFrom=0&pageSize=5&dateFrom={HARI}&dateTo={HARI}"
       "&lang=id&keyword=kepemilikan")

CHALLENGE = ("just a moment", "tunggu sebentar", "attention required",
             "checking your browser")
MAX_WAIT_S = 45


async def main() -> int:
    import nodriver as uc

    browser = await uc.start(
        headless=False,
        browser_args=["--no-sandbox", "--disable-dev-shm-usage",
                      "--window-size=1366,768"],
    )
    try:
        # 1. Selesaikan dulu challenge di halaman utama, persis seperti solver.
        page = await browser.get(MAIN)
        judul = ""
        for _ in range(MAX_WAIT_S):
            await asyncio.sleep(1)
            try:
                judul = (await page.evaluate("document.title")) or ""
            except Exception:
                judul = ""
            t = judul.lower()
            if t.strip() and not any(c in t for c in CHALLENGE):
                break
        else:
            print(f"TAHAP 1 GAGAL: challenge halaman utama tidak selesai "
                  f"(judul: {judul!r})")
            print(">> Cloudflare menahan di tingkat IP. Bukan soal kode.")
            return 2
        print(f"halaman utama OK (judul: {judul!r})")

        # 2. Buka URL API-nya LANGSUNG di tab yang sudah bersih itu.
        #    Kalau cookie & IP baik, yang muncul JSON mentah.
        api = await browser.get(API)
        await asyncio.sleep(3)
        judul_api = (await api.evaluate("document.title")) or ""
        isi = (await api.evaluate("document.body ? document.body.innerText : ''")) or ""
        isi = " ".join(isi.split())[:400]

        print(f"\njudul API : {judul_api!r}")
        print(f"isi (400) : {isi}")

        if any(c in judul_api.lower() for c in CHALLENGE):
            print("\n>> CHROME PUN KENA CHALLENGE di URL API.")
            print("   Cloudflare menolak di tingkat IP/aturan, bukan tingkat klien.")
            print("   Tidak ada perbaikan kode yang menolong -- butuh waktu")
            print("   (reputasi IP pulih) atau jalur akses yang berbeda.")
            return 3
        if isi.lstrip().startswith(("{", "[")):
            print("\n>> CHROME DAPAT JSON. Cookie dan IP baik-baik saja;")
            print("   yang ditolak permintaan curl_cffi kita. Bisa diperbaiki")
            print("   di kode (header/sidik jari klien).")
            return 0
        print("\n>> Bukan challenge, tapi juga bukan JSON. Lihat isinya di atas.")
        return 4
    finally:
        try:
            browser.stop()
        except Exception:
            pass


if __name__ == "__main__":
    import nodriver as uc
    sys.exit(uc.loop().run_until_complete(main()))
