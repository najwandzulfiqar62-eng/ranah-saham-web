"""Ukur ulang SELURUH tabel vonis dengan dasar pembanding SETANGGAL.

KENAPA DIULANG. Tabel UNGGUL_VONIS/UNGGUL_BERTAHAN yang dipajang
aplikasi dibuat dengan dasar pembanding TETAP (+0,88%). Pengukuran
ulang dengan dasar SETANGGAL -- rata-rata return 20 hari seluruh emiten
yang mulai di tanggal yang sama -- memberi angka yang jauh berbeda untuk
aturan yang sama:

    BELI KUAT bertahan 2 hari:  dipajang +4,59%  ->  terukur +1,47%
                                                     (299 emiten, n=679)

Selisih sebesar itu bukan derau. Dasar tetap tidak bisa membedakan
"vonis ini unggul" dari "vonis ini kebetulan sering muncul di bulan yang
bagus", dan kalau vonis ekstrem memang menumpuk di pasar yang sedang
naik -- dan itu yang diharapkan dari vonis momentum -- maka seluruh
keunggulannya akan terbaca lebih besar daripada yang sebenarnya.

Dijalankan di SELURUH universe, bukan 299 emiten, supaya angka yang
menggantikan tabel lama tidak datang dari sampel yang lebih kecil
daripada yang ia ganti.

Metodenya sama dengan tools/ukur_pola.py:
  - jalan maju; vonis pada bar t cuma melihat data sampai t
  - per KEJADIAN, bukan per bar
  - jeda antar-sampel sepanjang horizon
  - dasar pembanding per TANGGAL
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

from core.ai_score import calculate_ai_score_from_df  # noqa: E402
from core.stock_data import load_tickers  # noqa: E402
from web.app import _ringkasan_sinyal_teknikal  # noqa: E402

HORIZON = 20
SCAN_BAR = 200        # bar per emiten yang dipindai
KELUARAN = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "hasil_ukur_vonis.json")
SEMUA_VONIS = ("BELI KUAT", "BELI", "CENDERUNG BELI", "NETRAL",
               "CENDERUNG JUAL", "JUAL", "JUAL KUAT")


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
    print(f"tanggal dgn dasar: {len(dasar)}", flush=True)

    hasil = defaultdict(list)
    t0 = time.time()
    for n_e, (kode, df) in enumerate(deret.items(), 1):
        if n_e % 50 == 0:
            sisa = (time.time() - t0) / n_e * (len(deret) - n_e)
            print(f"  {n_e}/{len(deret)}  {time.time()-t0:.0f}s "
                  f"(sisa ~{sisa/60:.0f} mnt)", flush=True)
        c = df["Close"].tolist()
        tg = [str(x)[:10] for x in df.index]
        n = len(c)
        mulai = max(60, n - SCAN_BAR - HORIZON)
        vonis = {}
        for i in range(mulai, n - HORIZON):
            try:
                ai = calculate_ai_score_from_df(df.iloc[:i + 1])
                vonis[i] = _ringkasan_sinyal_teknikal(ai)["overall"] if ai else None
            except Exception:
                vonis[i] = None

        jeda = defaultdict(lambda: -999)
        for i in range(mulai + 2, n - HORIZON):
            v, v1, v2 = vonis.get(i), vonis.get(i - 1), vonis.get(i - 2)
            d = dasar.get(tg[i])
            if v is None or d is None or not c[i]:
                continue
            ret = (c[i + HORIZON] - c[i]) / c[i] * 100
            aturan = []
            # MUNCUL = vonisnya baru jadi ini hari ini (satu kejadian per
            # episode, bukan per bar -- jebakan yang sudah tiga kali
            # menggelembungkan angka di proyek ini).
            if v != v1:
                aturan.append(f"{v} muncul")
            # BERTAHAN = hari kedua berturut-turut.
            if v == v1 and v != v2:
                aturan.append(f"{v} bertahan 2h")
            for a in aturan:
                if i < jeda[a]:
                    continue
                jeda[a] = i + HORIZON
                hasil[a].append((ret - d, ret))

    ringkas = []
    for a, vlist in hasil.items():
        n_ = len(vlist)
        if n_ < 30:
            continue
        ringkas.append({
            "aturan": a, "n": n_,
            "unggul_pct": round(sum(x[0] for x in vlist) / n_, 2),
            "return_pct": round(sum(x[1] for x in vlist) / n_, 2),
            "pct_positif": round(sum(1 for x in vlist if x[1] > 0) / n_ * 100, 1),
        })
    ringkas.sort(key=lambda r: -r["unggul_pct"])
    dasar_rata = sum(dasar.values()) / len(dasar)
    json.dump({"horizon_hari": HORIZON, "n_emiten": len(deret),
               "dasar_pct": round(dasar_rata, 2), "aturan": ringkas},
              open(KELUARAN, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print(f"\ndasar pasar {HORIZON} hari: {dasar_rata:+.2f}%  "
          f"({len(deret)} emiten)\n")
    print(f"{'ATURAN':28} {'n':>6} {'UNGGUL':>9} {'RETURN':>9} {'%+':>7}")
    for r in ringkas:
        print(f"{r['aturan']:28} {r['n']:6d} {r['unggul_pct']:+9.2f} "
              f"{r['return_pct']:+9.2f} {r['pct_positif']:6.1f}%")
    print(f"\ntersimpan: {KELUARAN}")


if __name__ == "__main__":
    main()
