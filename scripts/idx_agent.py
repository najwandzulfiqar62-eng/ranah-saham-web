"""Pelayan browser untuk idx.co.id: satu Chrome, banyak permintaan.

KENAPA ADA: memutar ulang cf_clearance lewat klien HTTP sudah tidak bisa
diandalkan. Terbukti 18 Sep 2026 -- Chrome yang memanen cookie itu membuka
URL API dan mendapat JSON, sedangkan curl_cffi dengan cookie yang sama,
sidik jari chrome150, dan header yang sudah dibuat konsisten tetap dibalas
`cf-mitigated: challenge`. Cloudflare mengikat cookienya lebih dalam daripada
yang bisa ditiru klien HTTP.

Jalan yang PASTI bekerja: ambil datanya di dalam browser itu sendiri.

DUA CARA MENGAMBIL, dan keduanya diperlukan
===========================================

1. fetch() di dalam halaman -- MURAH (~0,2 detik).
2. NAVIGASI sungguhan ke URL-nya -- MAHAL (~2 detik), tapi lebih tahan.

Awalnya cuma navigasi. Lalu diganti fetch() demi kecepatan, dan 20 Sep 2026
fitur Pemegang Saham mati lagi dengan "HTTP 403 (lewat browser)": halamannya
terbuka normal, tapi fetch()-nya ditolak.

Sebabnya fetch() default dikirim TELANJANG -- tanpa Accept, tanpa
X-Requested-With, dengan `Sec-Fetch-Dest: empty`. Permintaan yang tadi lolos
challenge adalah permintaan DOKUMEN (`Sec-Fetch-Dest: document`). Dua bentuk
permintaan yang sangat berbeda dari sudut pandang Cloudflare, dari halaman
yang sama, dengan cookie yang sama.

Jadi sekarang: fetch() dengan header yang menyerupai XHR situsnya sendiri,
dan kalau ia TIDAK mengembalikan 200, permintaannya diulang lewat NAVIGASI.
Yang murah dicoba dulu karena hampir selalu cukup; yang mahal ada supaya
kegagalannya tidak pernah menjadi kegagalan fitur. Jalur mana yang dipakai
ikut dilaporkan, supaya lain kali tidak perlu ditebak lagi.

Protokol (baris demi baris, JSON):
    <- READY                                  (siap menerima)
    -> https://...                            (satu URL per baris)
    <- {"status": 200, "text": …, "metode": …} (satu jawaban per baris)
    -> (EOF)                                  (browser ditutup)

Prasyarat: Google Chrome stable + DISPLAY (Xvfb) aktif. DISPLAY tidak perlu
diatur manual -- core/idx_cf.py membungkus proses ini dengan xvfb-run saat
DISPLAY kosong.
"""
import asyncio
import json
import sys

MAIN = "https://www.idx.co.id/id"
CHALLENGE = ("just a moment", "tunggu sebentar", "attention required",
             "checking your browser")
CHALLENGE_TIMEOUT_S = 45
# Anggaran waktu SATU permintaan, dan jumlahnya penting.
#
# BUG NYATA 20 Sep 2026: fetch 30 detik + navigasi 40 detik = 70 detik untuk
# satu permintaan yang gagal, sementara pemanggil di core/idx_cf.py cuma
# sabar 40 detik (_AGENT_REQ_TIMEOUT). Jadi tiap kali cadangan navigasi
# dipakai, pemanggil membunuh pelayannya di tengah kerja lalu menyalakan
# Chrome baru -- sekitar 15 detik, berkali-kali. Di log terlihat sebagai
# "pelayan browser siap" yang muncul enam kali untuk satu permintaan
# riwayat, dan satu emiten butuh 249 detik.
#
# Anggaran di sini (20 + 25 = 45) sekarang JAUH di bawah kesabaran pemanggil
# (90). Angka dua tempat yang harus sepakat memang rapuh; ada uji yang
# membandingkan keduanya supaya tidak bisa lagi berselisih diam-diam.
FETCH_TIMEOUT_S = 20
NAV_TIMEOUT_S = 25
POLL_S = 0.1

# Header yang dikirim situs IDX sendiri saat memanggil API-nya. fetch() tanpa
# ini terlihat seperti skrip asing yang kebetulan berjalan di halaman mereka.
HEADER_XHR = {
    "Accept": "application/json, text/plain, */*",
    "X-Requested-With": "XMLHttpRequest",
}


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


async def _ambil_fetch(page, url: str) -> dict:
    """fetch() di dalam halaman, hasilnya dijemput dengan polling.

    Sengaja TIDAK memakai await_promise: bentuk dukungannya berbeda-beda antar
    versi nodriver, dan kegagalan di situ akan terbaca seperti masalah
    Cloudflare padahal bukan. Pola "titipkan ke window lalu jemput" cuma
    memakai evaluate sinkron biasa, yang perilakunya sama di semua versi.
    """
    kunci = "__idx_hasil"
    opsi = json.dumps({"credentials": "include", "headers": HEADER_XHR})
    # DIBACA SEBAGAI BINER, bukan teks.
    #
    # BUG NYATA 20 Sep 2026 -- ini sebab "berhasil tapi 0 pemegang". Jalur
    # ini juga dipakai mengunduh PDF laporan X-15 (idx_get_bytes). Dengan
    # r.text(), isi PDF dipaksa jadi string UTF-8, lalu di sisi Python
    # di-encode balik jadi bytes: byte yang bukan UTF-8 sah sudah diganti
    # U+FFFD dan TIDAK BISA dipulihkan. PDF-nya rusak, penguraiannya tidak
    # menemukan apa-apa, dan hasilnya nol pemegang saham -- tanpa satu pun
    # pesan error, karena setiap langkahnya "berhasil".
    #
    # arrayBuffer + base64 mengantar byte apa adanya, dan JSON tetap terbaca
    # karena ia cuma kasus khusus dari byte.
    pasang = (
        f"(() => {{ window.{kunci} = null;"
        f" const b64 = (buf) => {{ let s = '';"
        f"   const a = new Uint8Array(buf), N = 0x8000;"
        f"   for (let i = 0; i < a.length; i += N)"
        f"     s += String.fromCharCode.apply(null, a.subarray(i, i + N));"
        f"   return btoa(s); }};"
        f" fetch({json.dumps(url)}, {opsi})"
        f"  .then(r => r.arrayBuffer().then(b => {{ window.{kunci} ="
        f"      JSON.stringify({{status: r.status, b64: b64(b)}}); }}))"
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


async def _ambil_navigasi(browser, url: str) -> dict:
    """Buka URL-nya sebagai HALAMAN, lalu baca isinya.

    Lebih lambat, tapi inilah bentuk permintaan yang sama dengan yang lolos
    challenge: permintaan dokumen, bukan XHR. Chrome menampilkan JSON sebagai
    teks biasa, jadi innerText sudah berisi badan jawabannya.

    Statusnya tidak bisa dibaca langsung dari DOM, jadi disimpulkan dari
    isinya: badan yang terurai sebagai JSON berarti berhasil. Menyimpulkan
    dari isi memang kasar, tapi jauh lebih berguna daripada melaporkan 0
    untuk jawaban yang sebenarnya baik-baik saja.
    """
    try:
        page = await browser.get(url)
    except Exception as e:
        return {"status": 0, "error": f"navigasi gagal: {type(e).__name__}: {e}",
                "metode": "navigasi"}

    teks = ""
    for _ in range(int(NAV_TIMEOUT_S / 0.5)):
        await asyncio.sleep(0.5)
        try:
            teks = (await page.evaluate("document.body ? document.body.innerText : ''")) or ""
        except Exception:
            teks = ""
        t = teks.strip()
        if not t:
            continue
        if any(c in t.lower()[:400] for c in CHALLENGE):
            continue      # masih di layar challenge, tunggu
        break

    t = (teks or "").strip()
    if not t:
        return {"status": 0, "error": f"halaman kosong setelah {NAV_TIMEOUT_S}s",
                "metode": "navigasi"}
    try:
        json.loads(t)
        status = 200
    except Exception:
        status = 403 if any(c in t.lower()[:400] for c in CHALLENGE) else 0
    return {"status": status, "text": t, "metode": "navigasi"}


async def _ambil(browser, page, url: str) -> dict:
    """Yang murah dulu; yang mahal kalau yang murah ditolak."""
    hasil = await _ambil_fetch(page, url)
    if hasil.get("status") == 200:
        hasil["metode"] = "fetch"
        return hasil

    kabar = hasil.get("status") or hasil.get("error")
    lewat = await _ambil_navigasi(browser, url)
    if lewat.get("status") == 200:
        # Dicetak ke stderr, bukan stdout: stdout itu saluran protokol.
        print(f"idx_agent: fetch ditolak ({kabar}), navigasi berhasil",
              file=sys.stderr, flush=True)
        return lewat

    # Dua-duanya gagal. Laporkan yang fetch, karena itu yang dicoba lebih
    # dulu dan pesannya biasanya lebih menunjuk.
    hasil["metode"] = "fetch+navigasi"
    hasil.setdefault("error", f"fetch {kabar}, navigasi {lewat.get('status')}")
    return hasil


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
                jawaban = await _ambil(browser, page, url)
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
