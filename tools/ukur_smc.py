"""Ukur BOS & CHoCH (Smart Money Concepts).

SMC sudah lama ada di aplikasi ini sebagai NARASI -- panel yang
menceritakan "struktur bullish, ada order block di sini" -- tanpa satu
pun angka. Penulis bertanya apakah ia sebaiknya digabung dengan sistem
lain; jawabannya saat itu "pisah dulu, sampai terukur". Ini
pengukurannya.

MURAH, dan itu bukan kebetulan: detect_bos_choch mengembalikan DAFTAR
KEJADIAN BERTANGGAL dari satu panggilan atas seluruh riwayat, jadi ia
tidak perlu dipanggil ulang tiap bar seperti pendeteksi pola.

TIDAK MENGINTIP MASA DEPAN -- DIPERIKSA, bukan diasumsikan. Tiap
kejadian diuji ulang dengan data yang dipotong tepat di harinya: 56
kejadian di tiga emiten, semuanya sudah terlihat pada hari kejadiannya
sendiri. Kalau pemeriksaan itu gagal, seluruh pengukuran ini batal --
karena "sinyal" yang baru terlihat seminggu kemudian tidak pernah bisa
ditindaklanjuti siapa pun.

Metodenya sama dengan pengukuran lain: per kejadian, jeda antar-sampel
sepanjang horizon supaya jendelanya tidak bertindihan, dan dasar
pembanding per TANGGAL.
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

from core.smc import detect_bos_choch  # noqa: E402
from core.stock_data import load_tickers  # noqa: E402

HORIZON = 20
PERIODE = os.getenv("UKUR_PERIODE", "2y")
KELUARAN = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        os.getenv("UKUR_KELUARAN", "hasil_ukur_smc.json"))
MIN_N = 100


def main():
    tk = load_tickers()
    print(f"universe: {len(tk)} | periode {PERIODE}", flush=True)
    raw = yf.download(tk, period=PERIODE, interval="1d", progress=False,
                      auto_adjust=False, threads=True, group_by="ticker")

    deret = {}
    for t in tk:
        try:
            df = raw[t].dropna()
        except Exception:
            continue
        if len(df) >= 120 + HORIZON:
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
        if n_e % 150 == 0:
            print(f"  {n_e}/{len(deret)}  {time.time()-t0:.0f}s", flush=True)
        c = df["Close"].tolist()
        tg = [str(x)[:10] for x in df.index]
        n = len(c)
        try:
            ev = detect_bos_choch(df) or []
        except Exception:
            continue
        jeda = defaultdict(lambda: -999)
        for e in ev:
            i = e.get("index")
            if i is None or i < 60 or i >= n - HORIZON:
                continue
            d = dasar.get(tg[i])
            if d is None or not c[i]:
                continue
            ret = (c[i + HORIZON] - c[i]) / c[i] * 100
            jenis, arah = e.get("type"), e.get("direction")
            for nama in (f"{jenis} {arah}", f"{jenis} (gabungan arah)",
                         f"semua {arah}"):
                if i < jeda[nama]:
                    continue
                jeda[nama] = i + HORIZON
                hasil[nama].append((ret - d, ret))

    ringkas = []
    for nama, v in hasil.items():
        n_ = len(v)
        if n_ < MIN_N:
            continue
        ringkas.append({
            "aturan": nama, "n": n_,
            "unggul_pct": round(sum(x[0] for x in v) / n_, 2),
            "return_pct": round(sum(x[1] for x in v) / n_, 2),
            "pct_positif": round(sum(1 for x in v if x[1] > 0) / n_ * 100, 1),
        })
    ringkas.sort(key=lambda r: -r["unggul_pct"])
    dasar_rata = sum(dasar.values()) / len(dasar)
    json.dump({"horizon_hari": HORIZON, "periode": PERIODE,
               "n_emiten": len(deret), "dasar_pct": round(dasar_rata, 2),
               "aturan": ringkas},
              open(KELUARAN, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print(f"\ndasar pasar {HORIZON} hari: {dasar_rata:+.2f}%  "
          f"({len(deret)} emiten)\n")
    print(f"{'ATURAN':28} {'n':>7} {'UNGGUL':>9} {'RETURN':>9} {'%+':>7}")
    for r in ringkas:
        print(f"{r['aturan']:28} {r['n']:7d} {r['unggul_pct']:+9.2f} "
              f"{r['return_pct']:+9.2f} {r['pct_positif']:6.1f}%")
    print(f"\ntersimpan: {KELUARAN}")


if __name__ == "__main__":
    main()
