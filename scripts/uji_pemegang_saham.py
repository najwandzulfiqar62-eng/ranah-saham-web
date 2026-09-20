"""Bukti bahwa Pemegang Saham benar-benar jalan -- atau bukti persis di mana ia patah.

Beda dengan diag_pemegang_saham.py (yang memeriksa rantainya mata per mata),
skrip ini menjalankan JALUR YANG SAMA PERSIS dengan yang dipakai halaman
webnya, lalu menyebut jalur mana yang melayani tiap permintaan.

Dibuat 20 Sep 2026 karena perbaikan demi perbaikan dinyatakan selesai lalu
ternyata masih gagal di layar. Yang kurang bukan perbaikannya, tapi cara
MEMBUKTIKANNYA sebelum menyatakan selesai.

Pakai (dari akar proyek, TANPA xvfb-run -- begitu service menjalankannya):
    python3 scripts/uji_pemegang_saham.py            # BBCA
    python3 scripts/uji_pemegang_saham.py BBRI TLKM
"""
import asyncio
import os
import sys
import time

AKAR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, AKAR)
os.chdir(AKAR)


def _interpreter_service():
    for kandidat in (os.path.join(AKAR, "venv", "bin", "python"),
                     os.path.join(AKAR, "venv", "bin", "python3"),
                     os.path.join(AKAR, ".venv", "bin", "python")):
        if os.path.exists(kandidat):
            return kandidat
    return None


def _pastikan_interpreter_produksi():
    """Alasannya sama dengan di diag_pemegang_saham.py: dijalankan dengan
    interpreter yang salah, skrip ini tetap mencetak kesimpulan yang rapi --
    tentang mesin yang lain."""
    if "--apa-adanya" in sys.argv:
        return
    venv = _interpreter_service()
    if not venv:
        return
    try:
        if os.path.samefile(venv, sys.executable):
            return
    except OSError:
        if os.path.realpath(venv) == os.path.realpath(sys.executable):
            return
    print(f"(pindah ke interpreter service: {venv})\n")
    sys.stdout.flush()
    os.execv(venv, [venv, os.path.abspath(__file__)] + sys.argv[1:])


_pastikan_interpreter_produksi()

KODE = [k.upper() for k in sys.argv[1:] if not k.startswith("-")] or ["BBCA"]


async def utama():
    import web.app as app
    from core.idx_cf import idx_get_json, jalur_balasan
    from core.x15_store import ringkas

    print("=" * 66)
    print("1. SATU PERMINTAAN MENTAH -- jalur mana yang melayani?")
    print("=" * 66)
    import datetime as _dt
    hari = _dt.datetime.now().strftime("%Y%m%d")
    url = ("https://www.idx.co.id/primary/ListedCompany/GetAnnouncement"
           f"?emitenType=*&indexFrom=0&pageSize=5&dateFrom={hari}&dateTo={hari}"
           "&lang=id&keyword=kepemilikan")
    t0 = time.perf_counter()
    try:
        status, data, jalur = await idx_get_json(url, timeout=40)
        lama = time.perf_counter() - t0
        print(f"   status : {status}")
        print(f"   jalur  : {jalur}")
        print(f"   lama   : {lama:.1f} detik")
        if status != 200:
            print("\n   >> MASIH DITOLAK. Yang perlu dibaca: 'jalur' di atas.")
            print("      browser/fetch    -> XHR ditolak, cadangan navigasi juga gagal")
            print("      browser/navigasi -> navigasi dipakai (lebih lambat, TIDAK apa-apa)")
            print("      curl_cffi        -> jalur murah; browser belum sempat dicoba")
            return 1
        n = len((data or {}).get("Replies", []) or [])
        print(f"   isi    : {n} pengumuman hari ini")
    except Exception as e:
        print(f"   GAGAL  : {type(e).__name__}: {e}")
        return 1

    print("\n" + "=" * 66)
    print("2. JALUR PENUH -- persis yang dipakai halaman webnya")
    print("=" * 66)
    gagal = 0
    for kode in KODE:
        t0 = time.perf_counter()
        try:
            hasil = await app.api_pemegang_saham(kode)
            lama = time.perf_counter() - t0
            n = hasil.get("total", 0)
            tanda = "dari simpanan" if hasil.get("dari_simpanan") else "dari idx.co.id"
            print(f"   {kode}: {n} pemegang  ({lama:.1f} detik, {tanda})")
            for h in (hasil.get("holders") or [])[:3]:
                print(f"      - {h.get('nama_tampil')} · {h.get('jabatan') or '-'} "
                      f"· {h.get('pct_setelah')}%")
            if not n:
                print("      (kosong -- bisa jadi emiten ini memang tidak punya")
                print("       filing X-15 dalam 90 hari, BUKAN berarti gagal)")
        except Exception as e:
            gagal += 1
            print(f"   {kode}: GAGAL -- {type(e).__name__}: "
                  f"{str(e)[:160]}")

    print("\n" + "=" * 66)
    print("3. SIMPANAN -- apakah riwayatnya mulai menumpuk?")
    print("=" * 66)
    r = ringkas()
    print(f"   {r['n']} filing tersimpan, {r['emiten']} emiten")
    if r["awal"]:
        print(f"   rentang: {r['awal']} .. {r['akhir']}")
    else:
        print("   (masih kosong -- akan terisi tiap kali pengambilan berhasil)")

    print("\n" + "=" * 66)
    print("BERHASIL" if not gagal else f"{gagal} dari {len(KODE)} emiten GAGAL")
    print("=" * 66)
    return 1 if gagal else 0


sys.exit(asyncio.run(utama()))
