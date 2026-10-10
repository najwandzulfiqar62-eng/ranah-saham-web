"""Ukur keunggulan pola harmonic (XABCD). Jalan maju, per pola.

KENAPA PERLU. Detektornya sudah lama ada dan sudah dipakai sbg sumber
sinyal (MINERVINI_HARMONIC), tapi keunggulan pola harmonic SENDIRI --
terlepas dari saringan Minervini yang menyertainya -- belum pernah
diukur terpisah. Begitu polanya digambar di chart, pengguna akan
membacanya sebagai anjuran; menggambarnya tanpa angka berarti
menyerahkan kesimpulan pada bentuk yang terlihat meyakinkan.

ASAL-USULNYA disebut terus terang di layar: harmonic BUKAN dari buku
rujukan penulis (Edianto Ong) melainkan dari H.M. Gartley (1935) lalu
disistematiskan Scott Carney. Yang ada di buku itu Fibonacci retracement
& extension -- bahan dasarnya, bukan polanya.

Metodenya sama dengan tools/ukur_pola.py:
  - jalan maju; deteksi pada bar t hanya melihat data sampai t
  - per POLA, bukan per bar (dedup lewat pola+tanggal D)
  - jeda antar-sampel sepanjang horizon, supaya tidak bertindihan
  - dasar pembanding dihitung per TANGGAL
"""
import json
import os
import sys
import time
import warnings
from collections import defaultdict

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.abspath("."))

import yfinance as yf  # noqa: E402

from core.harmonic import detect_harmonic  # noqa: E402
from core.stock_data import load_tickers  # noqa: E402

HORIZON = 20
MIN_BAR = 120
EKOR = 260
# CAKUPAN DIBATASI, dan batasnya disebut di hasilnya.
#
# detect_harmonic memakan 117 ms per bar -- ia menelusuri kombinasi lima
# pivot, bukan menghitung satu rumus. Universe penuh x 250 bar = enam
# jam. Dibatasi ke 250 emiten paling likuid x 150 bar (~70 menit), dan
# angka yang dihasilkan HANYA berlaku untuk emiten likuid. Menyebutnya
# berlaku umum akan menjanjikan yang tidak diuji -- saham sepi punya
# harga penutupan yang tidak mencerminkan harga yang bisa didapat.
N_EMITEN = 250
SCAN_BAR = 150
KELUARAN = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "hasil_ukur_harmonic.json")


def main():
    tk = load_tickers()[:N_EMITEN]
    print(f"universe: {len(tk)} (dibatasi, lihat catatan modul)", flush=True)
    raw = yf.download(tk, period="2y", interval="1d", progress=False,
                      auto_adjust=False, threads=True, group_by="ticker")

    deret = {}
    for t in tk:
        try:
            df = raw[t].dropna()
        except Exception:
            continue
        if len(df) >= MIN_BAR + HORIZON + 40:
            deret[t.replace(".JK", "")] = df
    print(f"terpakai: {len(deret)}", flush=True)

    per_tgl = defaultdict(list)
    for kode, df in deret.items():
        c = df["Close"].tolist()
        tg = [str(x)[:10] for x in df.index]
        for i in range(len(c) - HORIZON):
            if c[i] > 0:
                per_tgl[tg[i]].append((c[i + HORIZON] - c[i]) / c[i] * 100)
    dasar = {d: sum(v) / len(v) for d, v in per_tgl.items() if len(v) >= 30}

    hasil = defaultdict(list)
    t0 = time.time()
    for n_e, (kode, df) in enumerate(deret.items(), 1):
        if n_e % 25 == 0:
            sisa = (time.time() - t0) / n_e * (len(deret) - n_e)
            print(f"  {n_e}/{len(deret)}  {time.time()-t0:.0f}s "
                  f"(sisa ~{sisa/60:.0f} mnt)", flush=True)
        c = df["Close"].tolist()
        tg = [str(x)[:10] for x in df.index]
        n = len(c)
        terlihat = set()
        jeda = defaultdict(lambda: -999)
        for i in range(max(MIN_BAR, n - SCAN_BAR - HORIZON), n - HORIZON):
            a = max(0, i - EKOR + 1)
            try:
                pol = detect_harmonic(df.iloc[a:i + 1], maks=2) or []
            except Exception:
                continue
            if not pol:
                continue
            d = dasar.get(tg[i])
            if d is None or not c[i]:
                continue
            ret = (c[i + HORIZON] - c[i]) / c[i] * 100
            for p in pol:
                # Penanda dari POLA + tanggal D: tetap selama polanya
                # sama, jadi satu pola tidak terhitung tiap hari.
                sid = f"{kode}:{p.get('pola')}:{p.get('arah')}:{p.get('tanggal_d')}"
                if sid in terlihat:
                    continue
                terlihat.add(sid)
                kunci = (p.get("pola"), p.get("arah"))
                if i < jeda[kunci]:
                    continue
                jeda[kunci] = i + HORIZON
                hasil[kunci].append((ret - d, ret))
                hasil[("SEMUA", p.get("arah"))].append((ret - d, ret))

    ringkas = []
    for (nama, arah), v in hasil.items():
        n_ = len(v)
        if n_ < 15:
            continue
        ringkas.append({
            "pola": nama, "arah": arah, "n": n_,
            "unggul_pct": round(sum(x[0] for x in v) / n_, 2),
            "return_pct": round(sum(x[1] for x in v) / n_, 2),
            "pct_positif": round(sum(1 for x in v if x[1] > 0) / n_ * 100, 1),
        })
    ringkas.sort(key=lambda r: (r["pola"], r["arah"]))
    dasar_rata = sum(dasar.values()) / len(dasar)
    json.dump({"horizon_hari": HORIZON, "n_emiten": len(deret),
               "dasar_pct": round(dasar_rata, 2), "pola": ringkas},
              open(KELUARAN, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print(f"\ndasar pasar {HORIZON} hari: {dasar_rata:+.2f}%\n")
    print(f"{'POLA':14} {'ARAH':9} {'n':>6} {'UNGGUL':>9} {'RETURN':>9} {'%+':>7}")
    for r in ringkas:
        print(f"{r['pola']:14} {r['arah']:9} {r['n']:6d} {r['unggul_pct']:+9.2f} "
              f"{r['return_pct']:+9.2f} {r['pct_positif']:6.1f}%")
    print(f"\ntersimpan: {KELUARAN}")


if __name__ == "__main__":
    main()
