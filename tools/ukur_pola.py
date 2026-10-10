"""Ukur keunggulan tiap pola chart. Jalan maju, tanpa mengintip masa depan.

TIGA JEBAKAN YANG DIHINDARI, ketiganya sudah pernah menggigit proyek ini:

1. HITUNG PER SETUP, BUKAN PER BAR. Satu pola yang bertahan dua minggu
   akan terhitung sepuluh kejadian kalau tiap bar dihitung -- itu
   menggelembungkan n DAN mengorelasikan hasilnya, sehingga selang
   kepercayaan yang dilaporkan jauh lebih sempit daripada yang pantas.
   Sudah terjadi tiga kali (divergence 10->80, falling wedge 3.808/tahun,
   bull flag). Di sini: tiap setup_id dicatat SEKALI, pada bar pertama
   ia terlihat.

2. TIDAK MENGINTIP MASA DEPAN. Deteksi pada bar t cuma melihat data
   sampai t. Hasilnya diukur dari t+1 ke t+1+HORIZON.

3. DIBANDINGKAN DENGAN DASAR YANG SETANGGAL. Pola yang kebetulan banyak
   muncul di bulan yang bagus akan terlihat hebat kalau dibandingkan
   dengan rata-rata seluruh periode. Dasarnya dihitung per TANGGAL:
   rata-rata return 20 hari SEMUA emiten yang mulai di tanggal itu.
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

from core.pola_katalog import deteksi  # noqa: E402
from core.stock_data import load_tickers  # noqa: E402

HORIZON = 20          # hari bursa, sama dengan horizon vonis & Pemulihan
EKOR = 220            # bar yang dikirim ke deteksi
# 220, bukan 200: Inverse H&S boleh membentang MAKS_JARAK_BAHU x 2 = 120
# bar ditambah umur 30 bar, dan bahu kirinya harus MASIH ada di dalam
# potongan. Potongan yang terlalu pendek akan memotong bahu kiri dan
# polanya berhenti terdeteksi -- diam-diam, tanpa error.
MIN_BAR = 160
KELUARAN = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "hasil_ukur_pola.json")


def main():
    tk = load_tickers()
    print(f"universe: {len(tk)} emiten", flush=True)

    t0 = time.time()
    raw = yf.download(tk, period="2y", interval="1d", progress=False,
                      auto_adjust=False, threads=True, group_by="ticker")
    print(f"unduh: {time.time() - t0:.0f}s", flush=True)

    # --- kumpulkan deret per emiten ---
    deret = {}
    for t in tk:
        try:
            df = raw[t].dropna()
        except Exception:
            continue
        if len(df) < MIN_BAR + HORIZON:
            continue
        deret[t.replace(".JK", "")] = (
            [str(x)[:10] for x in df.index],
            df["High"].tolist(), df["Low"].tolist(), df["Close"].tolist())
    print(f"emiten terpakai: {len(deret)}", flush=True)

    # --- dasar per tanggal: return 20 hari rata-rata SEMUA emiten ---
    per_tgl = defaultdict(list)
    for kode, (tgl, _h, _l, c) in deret.items():
        for i in range(len(c) - HORIZON):
            if c[i] > 0:
                per_tgl[tgl[i]].append((c[i + HORIZON] - c[i]) / c[i] * 100)
    dasar = {d: sum(v) / len(v) for d, v in per_tgl.items() if len(v) >= 30}
    print(f"tanggal dgn dasar: {len(dasar)}", flush=True)

    # --- jalan maju ---
    # (nama, fase) -> list of (unggul_pct, return_pct)
    hasil = defaultdict(list)
    terlihat = {}          # (setup_id, fase) -> sudah dicatat
    # JEDA ANTAR-SAMPEL, dan ini penjagaan KEDUA di atas setup_id.
    #
    # setup_id menjamin satu pola tidak terhitung tiap hari. Tapi ia
    # TIDAK menjamin sampelnya tidak tumpang-tindih: wedge yang mendapat
    # pivot baru jadi setup_id baru, padahal jendela 20 harinya hampir
    # seluruhnya bertindihan dengan yang sebelumnya. Hasil yang
    # bertindihan itu berkorelasi, dan n yang dilaporkan jadi lebih
    # besar daripada jumlah pengamatan yang benar-benar bebas.
    #
    # Jadi untuk tiap (emiten, pola, fase), sampel berikutnya baru
    # dihitung sesudah HORIZON bar berlalu. Ini memangkas n, dan itu
    # memang maksudnya: n yang kecil tapi jujur lebih berguna daripada
    # n besar yang separuhnya salinan.
    jeda_sampai = {}       # (kode, nama, fase) -> indeks bar
    t0 = time.time()
    n_emiten = 0
    for kode, (tgl, H, L, C) in deret.items():
        n_emiten += 1
        if n_emiten % 50 == 0:
            print(f"  {n_emiten}/{len(deret)} emiten, "
                  f"{time.time() - t0:.0f}s", flush=True)
        n = len(C)
        for i in range(MIN_BAR, n - HORIZON):
            a = max(0, i - EKOR + 1)
            try:
                pol = deteksi(kode, tgl[a:i + 1], H[a:i + 1], L[a:i + 1],
                              C[a:i + 1])
            except Exception:
                continue
            if not pol:
                continue
            d = dasar.get(tgl[i])
            if d is None or C[i] <= 0:
                continue
            ret = (C[i + HORIZON] - C[i]) / C[i] * 100
            for p in pol:
                # Tiap setup dicatat SEKALI per fase. Fase TERBENTUK dan
                # TEMBUS dicatat terpisah karena memang pertanyaan yang
                # berbeda: "bentuknya ada" vs "sudah terkonfirmasi".
                kunci = (p.setup_id, p.fase)
                if kunci in terlihat:
                    continue
                terlihat[kunci] = True
                jk = (kode, p.nama, p.fase)
                if i < jeda_sampai.get(jk, -1):
                    continue
                jeda_sampai[jk] = i + HORIZON
                hasil[(p.nama, p.arah, p.fase)].append((ret - d, ret))

    print(f"pindai selesai: {time.time() - t0:.0f}s", flush=True)

    ringkas = []
    for (nama, arah, fase), v in hasil.items():
        n = len(v)
        if n < 15:          # terlalu sedikit untuk dilaporkan sbg angka
            unggul = None
        else:
            unggul = sum(x[0] for x in v) / n
        ringkas.append({
            "nama": nama, "arah": arah, "fase": fase, "n": n,
            "unggul_pct": None if unggul is None else round(unggul, 2),
            "return_pct": round(sum(x[1] for x in v) / n, 2),
            "pct_positif": round(sum(1 for x in v if x[1] > 0) / n * 100, 1),
        })
    ringkas.sort(key=lambda r: (r["nama"], r["fase"]))

    dasar_rata = sum(dasar.values()) / len(dasar)
    out = {"horizon_hari": HORIZON, "n_emiten": len(deret),
           "dasar_pct": round(dasar_rata, 2), "pola": ringkas}
    with open(KELUARAN, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    print(f"\ndasar pasar {HORIZON} hari: {dasar_rata:+.2f}%\n")
    print(f"{'POLA':26} {'ARAH':6} {'FASE':10} {'n':>6} "
          f"{'UNGGUL':>8} {'RETURN':>8} {'%+':>6}")
    for r in ringkas:
        u = "  n/a" if r["unggul_pct"] is None else f"{r['unggul_pct']:+8.2f}"
        print(f"{r['nama']:26} {r['arah']:6} {r['fase']:10} {r['n']:6d} "
              f"{u} {r['return_pct']:+8.2f} {r['pct_positif']:5.1f}%")
    print(f"\ntersimpan: {KELUARAN}")


if __name__ == "__main__":
    main()
