"""Ukur arah tren Dow dan aturan garis trennya.

KENAPA PERLU. core/tren.py dipasang karena ia metode baku di buku
rujukan penulis, BUKAN karena angkanya sudah diperiksa -- dan hari ini
empat hal yang "kelihatan meyakinkan" ternyata meleset saat diukur
(harmonic terbalik arah, 95% wedge bukan wedge, BELI KUAT lebih lemah
dari BELI, +4,59% ternyata +1,47%). Memasang aturan kelima tanpa
mengukurnya berarti mengulang pola itu dengan sengaja.

TIGA PERTANYAAN yang dijawab terpisah, karena ketiganya bisa berbeda
jawabannya:

  1. Apakah ARAH TREN-nya sendiri berarti? (saham di tren naik lebih
     unggul daripada yang di tren turun?)
  2. Apakah MENYENTUH GARIS TREN NAIK itu titik beli? (harga turun
     mendekati garis, lalu apa?)
  3. Apakah MENYENTUH GARIS TREN TURUN itu titik jual? (harga naik
     mendekati garis, lalu apa?)

Metodenya sama dengan tools/ukur_pola.py: jalan maju, per kejadian
(dengan jeda antar-sampel sepanjang horizon), dasar pembanding per
TANGGAL.
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

from core.stock_data import load_tickers  # noqa: E402
from core.tren import arah_tren  # noqa: E402

HORIZON = 20
SCAN_BAR = 250
EKOR = 200
# "Menyentuh garis tren" = dalam jarak ini dari garisnya. Dipilih longgar
# (2%) karena harga jarang menyentuh garis persis, dan ambang yang terlalu
# ketat akan menghasilkan sampel yang terlalu kecil untuk disimpulkan.
AMBANG_SENTUH_PCT = 2.0
KELUARAN = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "hasil_ukur_tren.json")


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
        if len(df) >= SCAN_BAR + HORIZON + 40:
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
            print(f"  {n_e}/{len(deret)}  {time.time()-t0:.0f}s", flush=True)
        c = df["Close"].tolist()
        hi = df["High"].tolist()
        lo = df["Low"].tolist()
        tg = [str(x)[:10] for x in df.index]
        n = len(c)
        jeda = defaultdict(lambda: -999)
        for i in range(max(60, n - SCAN_BAR - HORIZON), n - HORIZON):
            a = max(0, i - EKOR + 1)
            try:
                tr = arah_tren(tg[a:i + 1], hi[a:i + 1], lo[a:i + 1],
                               c[a:i + 1])
            except Exception:
                continue
            d = dasar.get(tg[i])
            if d is None or not c[i]:
                continue
            ret = (c[i + HORIZON] - c[i]) / c[i] * 100

            aturan = [f"arah {tr.arah}"]
            if tr.garis_kini and not tr.tembus:
                jarak = (c[i] - tr.garis_kini) / c[i] * 100
                if tr.arah == "naik" and 0 <= jarak <= AMBANG_SENTUH_PCT:
                    aturan.append("sentuh garis tren NAIK (calon beli)")
                if tr.arah == "turun" and -AMBANG_SENTUH_PCT <= jarak <= 0:
                    aturan.append("sentuh garis tren TURUN (calon jual)")
            if tr.garis_kini and tr.tembus:
                aturan.append(f"garis tren {tr.arah} DITEMBUS")

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
               "ambang_sentuh_pct": AMBANG_SENTUH_PCT,
               "dasar_pct": round(dasar_rata, 2), "aturan": ringkas},
              open(KELUARAN, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print(f"\ndasar pasar {HORIZON} hari: {dasar_rata:+.2f}%  "
          f"({len(deret)} emiten)\n")
    print(f"{'ATURAN':38} {'n':>7} {'UNGGUL':>9} {'RETURN':>9} {'%+':>7}")
    for r in ringkas:
        print(f"{r['aturan']:38} {r['n']:7d} {r['unggul_pct']:+9.2f} "
              f"{r['return_pct']:+9.2f} {r['pct_positif']:6.1f}%")
    print(f"\ntersimpan: {KELUARAN}")


if __name__ == "__main__":
    main()
