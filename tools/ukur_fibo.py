"""Ukur apakah harga benar-benar BEREAKSI di level Fibonacci.

Fibonacci dipasang karena ia metode baku di buku rujukan penulis --
alasan yang SAMA yang dipakai untuk garis tren Dow, dan garis tren
itu ternyata separuhnya salah saat diukur. Jadi level Fibonacci pun
tidak boleh dipajang sbg sesuatu yang berarti sebelum diperiksa.

Yang diuji: harga menyentuh (dalam 2%) tiap level retracement, lalu
apa yang terjadi 20 hari berikutnya -- dipisah per rasio DAN per arah
ayunan, karena 61,8% pada ayunan naik dan pada ayunan turun adalah
dua keadaan yang sama sekali berbeda.
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

from core.fibo import hitung as fibo_hitung  # noqa: E402
from core.stock_data import load_tickers  # noqa: E402


HORIZON = 20
SCAN_BAR = 220
EKOR = 320
AMBANG_PCT = 2.0      # "menyentuh" = dalam jarak ini dari levelnya
KELUARAN = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "hasil_ukur_fibo.json")


def main():
    tk = load_tickers()
    print(f"universe: {len(tk)}", flush=True)
    raw = yf.download(tk, period="2y", interval="1d", progress=False,
                      auto_adjust=False, threads=True, group_by="ticker")

    deret = {}
    for t in tk:
        try:
            df = raw[t].dropna()
        except Exception:
            continue
        if len(df) >= SCAN_BAR + HORIZON + 60:
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
        if n_e % 100 == 0:
            sisa = (time.time() - t0) / n_e * (len(deret) - n_e)
            print(f"  {n_e}/{len(deret)}  {time.time()-t0:.0f}s "
                  f"(sisa ~{sisa/60:.0f} mnt)", flush=True)
        c = df["Close"].tolist()
        hi = df["High"].tolist()
        lo = df["Low"].tolist()
        tg = [str(x)[:10] for x in df.index]
        n = len(c)
        jeda = defaultdict(lambda: -999)
        for i in range(max(70, n - SCAN_BAR - HORIZON), n - HORIZON):
            a = max(0, i - EKOR + 1)
            try:
                fb = fibo_hitung(tg[a:i + 1], hi[a:i + 1], lo[a:i + 1],
                                 c[a:i + 1])
            except Exception:
                continue
            if not fb:
                continue
            d = dasar.get(tg[i])
            if d is None or not c[i]:
                continue
            ret = (c[i + HORIZON] - c[i]) / c[i] * 100

            aturan = []
            for L in fb.level:
                if L["jenis"] != "retracement":
                    continue
                jarak = abs(c[i] - L["harga"]) / c[i] * 100
                if jarak <= AMBANG_PCT:
                    aturan.append(f"{L['nama']} ayunan {fb.arah}")
                    aturan.append(f"{L['nama']} (gabungan arah)")
            for nama in aturan:
                if i < jeda[nama]:
                    continue
                jeda[nama] = i + HORIZON
                hasil[nama].append((ret - d, ret))

    ringkas = []
    for nama, v in hasil.items():
        n_ = len(v)
        if n_ < 100:
            continue
        ringkas.append({
            "aturan": nama, "n": n_,
            "unggul_pct": round(sum(x[0] for x in v) / n_, 2),
            "return_pct": round(sum(x[1] for x in v) / n_, 2),
            "pct_positif": round(sum(1 for x in v if x[1] > 0) / n_ * 100, 1),
        })
    ringkas.sort(key=lambda r: -r["unggul_pct"])
    dasar_rata = sum(dasar.values()) / len(dasar)
    json.dump({"horizon_hari": HORIZON, "n_emiten": len(deret),
               "ambang_pct": AMBANG_PCT, "dasar_pct": round(dasar_rata, 2),
               "aturan": ringkas},
              open(KELUARAN, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print(f"\ndasar pasar {HORIZON} hari: {dasar_rata:+.2f}%  "
          f"({len(deret)} emiten)\n")
    print(f"{'ATURAN':42} {'n':>7} {'UNGGUL':>9} {'RETURN':>9} {'%+':>7}")
    for r in ringkas:
        print(f"{r['aturan']:42} {r['n']:7d} {r['unggul_pct']:+9.2f} "
              f"{r['return_pct']:+9.2f} {r['pct_positif']:6.1f}%")
    print(f"\ntersimpan: {KELUARAN}")


if __name__ == "__main__":
    main()
