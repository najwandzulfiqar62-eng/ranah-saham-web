"""Ukur aturan AREA BELI yang sedang dipakai aplikasi.

CELAH YANG DITUTUP DI SINI. Kemarin aturan "beli di garis tren naik"
diukur dan ternyata merugi (-1,22%), lalu dicabut -- dan area beli
dikembalikan ke "support teruji terdekat". Tapi aturan PENGGANTI itu
TIDAK PERNAH DIUKUR juga. Menukar aturan yang terbukti salah dengan
aturan yang belum diperiksa bukan perbaikan; ia cuma memindahkan
ketidaktahuan.

YANG DIUJI, dan sengaja dipisah-pisah supaya kelihatan bagian mana yang
bekerja:

  1. harga MENYENTUH support teruji (dalam 2%)        <- yang dipakai
  2. ...dan supportnya KUAT (>=3 sentuhan)
  3. ...dan trennya TIDAK turun                        <- gabungan penuh
  4. harga menyentuh support SATU-SENTUHAN             <- pembanding
  5. harga MENEMBUS support teruji ke bawah            <- kebalikannya

Pembanding ke-4 dan ke-5 ada supaya hasilnya bisa dibaca: kalau (1)
bagus tapi (4) sama bagusnya, maka "teruji" tidak menambah apa pun; dan
kalau (5) jauh lebih buruk, itu bukti levelnya memang berarti.

Metodenya sama dengan pengukuran lain di proyek ini: jalan maju, per
kejadian dengan jeda sepanjang horizon, dasar pembanding per TANGGAL.
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

from core.level_sr import cari_level  # noqa: E402
from core.stock_data import load_tickers  # noqa: E402
from core.tren import arah_tren  # noqa: E402

HORIZON = 20
SCAN_BAR = 220
EKOR = 320
AMBANG_PCT = 2.0      # "menyentuh" = dalam jarak ini dari levelnya
KELUARAN = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "hasil_ukur_entry.json")


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
                lv = cari_level(tg[a:i + 1], hi[a:i + 1], lo[a:i + 1],
                                c[a:i + 1])
            except Exception:
                continue
            if not lv:
                continue
            d = dasar.get(tg[i])
            if d is None or not c[i]:
                continue
            ret = (c[i + HORIZON] - c[i]) / c[i] * 100

            bawah = [x for x in lv if x.tipe == "support"]
            s1 = bawah[-1] if bawah else None
            aturan = []
            if s1:
                jarak = (c[i] - s1.harga) / c[i] * 100
                dekat = 0 <= jarak <= AMBANG_PCT
                if dekat and s1.sentuh > 1:
                    aturan.append("sentuh support TERUJI")
                    if s1.kuat:
                        aturan.append("sentuh support KUAT (>=3x)")
                    try:
                        tr = arah_tren(tg[a:i + 1], hi[a:i + 1], lo[a:i + 1],
                                       c[a:i + 1])
                        if tr.arah != "turun":
                            aturan.append("sentuh support TERUJI + tren tidak turun")
                    except Exception:
                        pass
                if dekat and s1.sentuh == 1:
                    aturan.append("sentuh support SATU-SENTUHAN")
            # Menembus ke bawah: level teruji terdekat kini DI ATAS harga
            # berarti harga sudah melewatinya.
            atas = [x for x in lv if x.tipe == "resistance" and x.sentuh > 1]
            if atas:
                r1 = atas[0]
                if 0 <= (r1.harga - c[i]) / c[i] * 100 <= AMBANG_PCT:
                    aturan.append("di bawah resistance teruji")

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
