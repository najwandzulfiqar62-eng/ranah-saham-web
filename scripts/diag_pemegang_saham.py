"""Cari TITIK MANA dari rantai Pemegang Saham yang putus.

Rantainya empat mata, dan tiap mata gagal dengan cara yang berbeda:
  1. Chrome + Xvfb ada di server?      -> solver tidak bisa jalan sama sekali
  2. Solver menghasilkan cf_clearance? -> Cloudflare menolak / timeout
  3. curl_cffi diterima idx.co.id?     -> cookie didapat tapi JA3 ditolak
  4. Datanya terurai jadi pemegang?    -> sumbernya berubah bentuk

Menebak mata mana yang putus sudah pernah membuang waktu; skrip ini
memeriksanya berurutan dan berhenti di yang pertama gagal.
"""
import asyncio
import os
import shutil
import sys
import traceback

# Dijalankan dari AKAR proyek (tempat core/ dan web/ berada), bukan dari
# folder scripts/ -- kalau tidak, impor core.* gagal sebelum sempat
# memeriksa apa pun, dan kegagalan impor itu terbaca seperti masalah
# yang sedang dicari padahal bukan.
AKAR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, AKAR)
os.chdir(AKAR)


def tahap(n, judul):
    print(f"\n{'=' * 60}\n{n}. {judul}\n{'=' * 60}")


async def utama():
    tahap(1, "Chrome & Xvfb di server")
    for nama in ("google-chrome", "chromium", "chromium-browser",
                 "google-chrome-stable", "Xvfb", "xvfb-run"):
        jalur = shutil.which(nama)
        print(f"   {'ADA   ' if jalur else 'TIDAK '} {nama}"
              + (f"  -> {jalur}" if jalur else ""))
    print(f"   DISPLAY = {os.environ.get('DISPLAY') or '(kosong)'}")

    tahap(2, "Solver Cloudflare (ambil cf_clearance)")
    # TIDAK memaksa solve baru secara bawaan. Versi pertama skrip ini memakai
    # force=True, dan itu keliru: tiap kali dijalankan ia melewati cache 15
    # menit lalu menembak challenge Cloudflare lagi. Menjalankannya beberapa
    # kali berturut-turut saat menelusuri masalah membuat idx.co.id menaikkan
    # penjagaannya ("Just a moment..." yang tak kunjung selesai) -- alat
    # diagnosis yang MEMPERBURUK hal yang sedang didiagnosisnya.
    # Pakai `--paksa` hanya kalau solvernya sendiri yang ingin diuji.
    paksa = "--paksa" in sys.argv
    print("   mode:", "PAKSA solve baru" if paksa
          else "pakai sesi tersimpan bila masih hangat")
    try:
        from core.idx_cf import get_session
        cookies, ua = await get_session(force=paksa)
        punya_cf = "cf_clearance" in (cookies or {})
        print(f"   cookie didapat : {len(cookies or {})} buah")
        print(f"   cf_clearance   : {'ADA' if punya_cf else 'TIDAK ADA'}")
        print(f"   user-agent     : {(ua or '')[:70]}")
        if not punya_cf:
            print("\n   >> BERHENTI: cookie utama tidak didapat.")
            return
    except Exception as e:
        print(f"   GAGAL: {type(e).__name__}: {e}")
        traceback.print_exc(limit=3)
        print("\n   >> BERHENTI di tahap 2. Ini mata rantai yang putus.")
        if "tidak selesai" in str(e):
            print("\n   Judul yang menggantung di 'Just a moment...' berarti")
            print("   Cloudflare MENAHAN, bukan lambat. Penyebab tersering:")
            print("   challenge ditembak berulang kali dari IP yang sama dalam")
            print("   waktu singkat. Diamkan 15-30 menit, lalu coba lagi TANPA")
            print("   --paksa. Mencoba terus justru memperpanjang penahanannya.")
        return

    tahap("3a", "Isi balasan mentah dari idx.co.id (siapa yang menolak?)")
    # 403 saja tidak cukup untuk menyimpulkan apa pun. Cloudflare yang
    # memblokir membalas HTML dengan Ray ID dan header cf-*; IDX yang menolak
    # di lapisan aplikasinya membalas hal lain sama sekali. Sebelum baris ini
    # ada, dua sebab yang sangat berbeda itu terlihat identik -- dan sudah
    # dua kali membuat penelusuran salah arah.
    try:
        import datetime as _dt

        from core.idx_cf import _idx_get, _target_impersonate
        hari = _dt.datetime.now().strftime("%Y%m%d")
        url = ("https://www.idx.co.id/primary/ListedCompany/GetAnnouncement"
               f"?emitenType=*&indexFrom=0&pageSize=5&dateFrom={hari}&dateTo={hari}"
               "&lang=id&keyword=kepemilikan")
        print(f"   impersonate : {_target_impersonate()}")
        r = await _idx_get(url, timeout=25, accept="application/json")
        print(f"   status      : {r.status_code}")
        menarik = ("server", "cf-ray", "cf-mitigated", "cf-cache-status",
                   "content-type", "x-frame-options", "set-cookie")
        for k, v in (r.headers or {}).items():
            if k.lower() in menarik:
                print(f"   {k.lower():12s}: {str(v)[:110]}")
        badan = " ".join((r.text or "")[:600].split())
        print(f"   badan (600)  : {badan}")
        if r.status_code == 403:
            petunjuk = badan.lower()
            if "cf-ray" in str(r.headers).lower() or "cloudflare" in petunjuk:
                print("\n   >> Yang menolak CLOUDFLARE (bukan IDX).")
            else:
                print("\n   >> Tidak ada jejak Cloudflare -- kemungkinan IDX sendiri")
                print("      yang menolak (endpoint/param berubah, atau butuh Referer).")
    except Exception as e:
        print(f"   tidak bisa diperiksa: {type(e).__name__}: {e}")

    tahap(3, "Ambil data X-15 hari ini dari idx.co.id")
    try:
        import web.app as app
        mentah = await app._fetch_x15_today(days_back=0)
        print(f"   filing hari ini: {len(mentah or [])} baris")
        if not mentah:
            print("   (kosong -- bisa jadi memang tidak ada filing hari ini,")
            print("    BUKAN berarti gagal. Coba days_back lebih besar.)")
            mentah = await app._fetch_x15_today(days_back=3)
            print(f"   filing 3 hari lalu: {len(mentah or [])} baris")
    except Exception as e:
        print(f"   GAGAL: {type(e).__name__}: {e}")
        traceback.print_exc(limit=3)
        print("\n   >> BERHENTI di tahap 3.")
        return

    tahap(4, "Rakit pemegang saham untuk satu emiten (BBCA)")
    try:
        import web.app as app
        items = await app._fetch_x15_history_for_kode("BBCA", days=90)
        holders = app._latest_x15_holders_for_kode(items)
        print(f"   filing 90 hari : {len(items)} baris")
        print(f"   pemegang       : {len(holders)}")
        for h in holders[:5]:
            print(f"     - {h.get('nama') or h.get('perusahaan')} | {h.get('jabatan')}")
        print("\n   >> SELURUH RANTAI JALAN. Kalau di browser tetap error,")
        print("      masalahnya di lapisan lain (cache basi / frontend).")
    except Exception as e:
        print(f"   GAGAL: {type(e).__name__}: {e}")
        traceback.print_exc(limit=3)
        print("\n   >> BERHENTI di tahap 4.")


asyncio.run(utama())
