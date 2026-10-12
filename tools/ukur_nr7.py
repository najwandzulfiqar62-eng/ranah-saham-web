"""Ukur NR7 + 52W High -- dan apakah syarat "dekat puncak" MENAMBAH.

KENAPA ALAT INI ADA. NR7_52W adalah sumber sinyal ke-4 di aplikasi ini:
ia menulis ke signal_history dengan direction BUY, diaudit, dan ikut
membentuk win rate. Lencananya menyandang "HIGH RISK". Dan ia TIDAK
punya satu pun angka terukur -- core/lencana.py mengirim unggul_pct=None
untuknya, yang memang pernyataan yang benar, tapi bukan keadaan yang
boleh dibiarkan pada teori yang menerbitkan rekomendasi.

PELAJARAN DARI MVH DIPAKAI DI SINI SEJAK AWAL. Teori ini persilangan
DUA syarat:

    NR7      : range hari ini TERSEMPIT dari 7 hari terakhir (Crabel 1990)
    52W High : close >= 98% dari tertinggi 52 minggu

Mengukurnya sebagai satu kesatuan lalu mendapat angka positif tidak
membuktikan apa pun tentang persilangannya -- bisa jadi seluruh
angkanya datang dari satu kaki, dan kaki lainnya cuma mengurangi jumlah
sinyal. Pengurangan jumlah sinyal SELALU terlihat seperti penyaringan
yang ketat.

Jadi empat sel pada sampel yang sama:

    A. NR7 saja                     (kaki pertama, tanpa syarat 52W)
    B. NR7 + 52W >= 98%  KETAT      (= teori yang dicatat)
    C. NR7 + 52W <  98%             (pelengkap B)
    D. NR7 + 52W >= 90%  LONGGAR    (ambang tampilan saringan)

B vs C menjawab "apakah dekat-puncak menambah". B vs D menjawab
"apakah ambang 98% layak lebih ketat dari 90%" -- pertanyaan yang
nyata, karena ambang longgar itu memang dipajang di tab saringan dan
pembaca boleh memilihnya.

BAR BERJALAN DIBUANG, dan ini bukan detail. Cacat nyata 19 Sep 2026:
pemanggil produksi menempelkan bar hari ini yang dirakit dari candle
per-jam. Bar yang belum tutup hampir SELALU tersempit, jadi syarat NR7
menyala untuk hampir semua saham tiap pagi -- bukan kontraksi
volatilitas, cuma jam yang belum habis. Separuh sinyal NR7 adalah
artefak itu. Di sini seluruh bar historis sudah tutup, jadi masalahnya
tidak ada -- tapi dicatat supaya pembaca hasilnya tahu bahwa angka ini
mengukur NR7 yang SEBENARNYA.

ENTRY DI SESI BERIKUTNYA, bukan di bar NR7-nya. Begitulah teorinya
(Crabel: bar NR7 dikenali sesudah tutup, ekspansinya ditradingkan sesi
berikutnya) dan begitu pula yang dilakukan pencatat sinyal: entry di
harga pasar hari berikutnya. Mengukur dari close bar NR7 akan memberi
teori ini satu hari gerakan yang tidak pernah bisa didapat siapa pun.

Metodenya sama dengan pengukuran lain: jalan maju, per setup dengan
jeda sepanjang horizon, dasar pembanding per TANGGAL (tanggal ENTRY,
bukan tanggal deteksi), dua periode sebagai uji kestabilan.

MURAH, berbeda dari harmonic: detect_nr7_52w cuma membandingkan range
dan satu maksimum bergulir -- tidak ada penelusuran kombinasi. Jadi
universe penuh bisa dipindai.

Jalankan:
  UKUR_PERIODE=2y python tools/ukur_nr7.py
  UKUR_PERIODE=5y UKUR_KELUARAN=hasil_ukur_nr7_5y.json python tools/ukur_nr7.py
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

from core.screening_pro import (NR7_52W_LONGGAR_PCT, NR7_52W_MIN_BARS,  # noqa: E402
                                NR7_52W_NEAR_PCT, NR7_52W_WINDOW,
                                detect_nr7_52w)
from core.stock_data import load_tickers  # noqa: E402

HORIZON = 20
PERIODE = os.getenv("UKUR_PERIODE", "2y")
KELUARAN = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        os.getenv("UKUR_KELUARAN", "hasil_ukur_nr7.json"))
MIN_N = 100

# Bar minimum: detect_nr7_52w sendiri menuntut NR7_52W_MIN_BARS (240) utk
# 52W high yang sah. Ditambah satu bar entry dan horizonnya.
MIN_RIWAYAT = NR7_52W_MIN_BARS + 1


def main():
    tk = load_tickers()
    print(f"universe: {len(tk)} | periode {PERIODE} | "
          f"ketat >= {NR7_52W_NEAR_PCT:.0%}, longgar >= "
          f"{NR7_52W_LONGGAR_PCT:.0%} dari 52W high", flush=True)

    raw = yf.download(tk, period=PERIODE, interval="1d", progress=False,
                      auto_adjust=False, threads=True, group_by="ticker")

    deret = {}
    for t in tk:
        try:
            df = raw[t].dropna()
        except Exception:
            continue
        if len(df) >= MIN_RIWAYAT + HORIZON + 1:
            deret[t.replace(".JK", "")] = df
    print(f"terpakai: {len(deret)} emiten", flush=True)
    if not deret:
        print("GAGAL: tidak ada emiten dengan riwayat cukup "
              f"({MIN_RIWAYAT + HORIZON + 1} bar). Periode terlalu pendek?")
        sys.exit(1)

    # Dasar pembanding PER TANGGAL ENTRY. Dasar tunggal untuk seluruh
    # periode melebih-lebihkan teori yang kebetulan menyala di bulan bagus
    # -- itu sudah membatalkan satu temuan di proyek ini.
    per_tgl = defaultdict(list)
    for kode, df in deret.items():
        cl = df["Close"].tolist()
        tg = [str(x)[:10] for x in df.index]
        for i in range(len(cl) - HORIZON):
            if cl[i] > 0:
                per_tgl[tg[i]].append((cl[i + HORIZON] - cl[i]) / cl[i] * 100)
    dasar = {d: sum(v) / len(v) for d, v in per_tgl.items() if len(v) >= 30}

    hasil = defaultdict(list)
    t0 = time.time()
    for n_e, (kode, df) in enumerate(deret.items(), 1):
        if n_e % 100 == 0:
            sisa = (time.time() - t0) / n_e * (len(deret) - n_e)
            print(f"  {n_e}/{len(deret)}  {time.time()-t0:.0f}s "
                  f"(sisa ~{sisa/60:.0f} mnt)", flush=True)

        cl = df["Close"].tolist()
        hi = df["High"].tolist()
        tg = [str(x)[:10] for x in df.index]
        n = len(cl)
        jeda = defaultdict(lambda: -999)

        # KEDEKATAN 52W untuk SETIAP bar, lepas dari NR7. Dipakai mengukur
        # kaki yang tidak bisa didapat dari detect_nr7_52w: fungsi itu
        # mengembalikan None pada hari yang bukan NR7, jadi "dekat puncak
        # TANPA NR7" tidak mungkin terbaca darinya.
        #
        # Jendelanya NR7_52W_WINDOW supaya definisinya sama dengan
        # detektornya; min_periods=1 meniru tail(252).max() yang mengambil
        # apa adanya kalau barisnya kurang dari 252.
        hi52 = (df["High"].rolling(NR7_52W_WINDOW, min_periods=1)
                .max().tolist())

        # i = bar NR7 (sudah tutup). Entry di bar i+1, jadi batasnya
        # dikurangi satu lagi.
        for i in range(MIN_RIWAYAT, n - HORIZON - 1):
            # KAKI KEDUA diukur lebih dulu, karena ia TIDAK menuntut NR7.
            # Tanpa sel ini, "NR7 + 52W" bisa terbaca sebagai temuan
            # tentang NR7 padahal seluruh angkanya milik kedekatan 52W.
            if hi52[i] > 0 and cl[i] >= hi52[i] * NR7_52W_NEAR_PCT:
                j2 = i + 1
                d2 = dasar.get(tg[j2])
                if d2 is not None and cl[j2]:
                    nm = "H. 52W >=98% SAJA (tanpa syarat NR7)"
                    if i >= jeda[nm]:
                        jeda[nm] = i + HORIZON
                        r2 = (cl[j2 + HORIZON] - cl[j2]) / cl[j2] * 100
                        hasil[nm].append((r2 - d2, r2))

            # abaikan_bar_terakhir=False: bar i di data historis SUDAH
            # tutup. Memakai True di sini akan menilai bar i-1 dan
            # menggeser seluruh pengukurannya satu hari.
            # dekat_pct=0.0 -> detektor TIDAK menyaring kedekatan 52W
            # sama sekali, jadi sel "NR7 saja" benar-benar tanpa syarat itu.
            #
            # CACAT YANG DITUTUP: harness ini sempat memanggilnya dengan
            # NR7_52W_LONGGAR_PCT (0,90), dan detect_nr7_52w MENOLAK bar di
            # bawah ambang itu. Jadi "NR7 saja" sebenarnya "NR7 DAN >=90%",
            # dan pertanyaan "apakah syarat 52W menambah apa pun" tidak
            # pernah terjawab. Terlihat dari hasilnya: sel A dan sel D
            # memberi angka IDENTIK (+1,36%, n=594) -- dua sel yang
            # seharusnya berbeda mengukur himpunan yang sama.
            try:
                r = detect_nr7_52w(df.iloc[:i + 1], dekat_pct=0.0,
                                   abaikan_bar_terakhir=False)
            except Exception:
                continue
            if not r:
                continue

            # ENTRY DI SESI BERIKUTNYA, dan dasar pembandingnya ikut
            # tanggal entry -- bukan tanggal deteksi.
            j = i + 1
            if not cl[j]:
                continue
            d = dasar.get(tg[j])
            if d is None:
                continue
            ret = (cl[j + HORIZON] - cl[j]) / cl[j] * 100
            lebih = ret - d

            # KETAT dibaca dari medan yang disediakan detektornya sendiri
            # -- definisinya miliknya, dan menghitungnya ulang di sini
            # berarti dua definisi untuk satu aturan.
            ketat = bool(r.get("nr7_ketat"))
            # LONGGAR dihitung dari jarak yang juga sudah dikembalikannya.
            # pct_from_52w_high = (close/high52w - 1) * 100, jadi ">= 90%
            # dari 52W high" berarti jaraknya >= -10 persen.
            jarak = r.get("pct_from_52w_high")
            longgar = (jarak is not None
                       and jarak >= (NR7_52W_LONGGAR_PCT - 1) * 100)

            sel = ["A. NR7 saja (tanpa syarat 52W)"]
            sel.append("B. NR7 + 52W >=98% (KETAT, yang dicatat)" if ketat
                       else "C. NR7 + 52W <98%")
            if longgar:
                sel.append("D. NR7 + 52W >=90% (longgar, tampilan)")
            else:
                sel.append("G. NR7 + 52W <90% (jauh dari puncak)")
            # Lebar stop teorinya ikut dicatat: premis NR7 adalah "stop
            # ketat", dan kalau yang untung justru yang stopnya lebar maka
            # premisnya yang keliru, bukan angkanya.
            slp = r.get("nr7_sl_pct") or 0
            sel.append("E. KETAT, stop <=4%" if ketat and slp <= 4
                       else ("F. KETAT, stop >4%" if ketat else None))

            for nama in sel:
                if not nama or i < jeda[nama]:
                    continue
                jeda[nama] = i + HORIZON
                hasil[nama].append((lebih, ret))

    ringkas = []
    for nama, v in hasil.items():
        n_ = len(v)
        ringkas.append({
            "aturan": nama, "n": n_,
            "unggul_pct": round(sum(x[0] for x in v) / n_, 2),
            "return_pct": round(sum(x[1] for x in v) / n_, 2),
            "pct_positif": round(sum(1 for x in v if x[1] > 0) / n_ * 100, 1),
            "cukup_sampel": n_ >= MIN_N,
        })
    ringkas.sort(key=lambda r: r["aturan"])
    dasar_rata = sum(dasar.values()) / len(dasar) if dasar else 0.0

    with open(KELUARAN, "w", encoding="utf-8") as f:
        json.dump({"horizon_hari": HORIZON, "periode": PERIODE,
                   "n_emiten": len(deret),
                   "ketat_pct": NR7_52W_NEAR_PCT,
                   "longgar_pct": NR7_52W_LONGGAR_PCT,
                   "entry": "close sesi BERIKUTNYA sesudah bar NR7",
                   "dasar_pct": round(dasar_rata, 2),
                   "aturan": ringkas}, f, ensure_ascii=False, indent=1)

    print(f"\ndasar pasar {HORIZON} hari: {dasar_rata:+.2f}%  "
          f"({len(deret)} emiten, periode {PERIODE})\n")
    print(f"{'ATURAN':42} {'n':>7} {'UNGGUL':>9} {'RETURN':>9} {'%+':>7}")
    for r in ringkas:
        tanda = "" if r["cukup_sampel"] else "  (sampel kurang)"
        print(f"{r['aturan']:42} {r['n']:7d} {r['unggul_pct']:+9.2f} "
              f"{r['return_pct']:+9.2f} {r['pct_positif']:6.1f}%{tanda}")

    def _ambil(awalan):
        return next((r for r in ringkas if r["aturan"].startswith(awalan)), None)

    print()
    a, b, c, d = _ambil("A."), _ambil("B."), _ambil("C."), _ambil("D.")
    h = _ambil("H.")
    if a and b and a["cukup_sampel"] and b["cukup_sampel"]:
        print(f"SYARAT 52W MENAMBAH PADA NR7: "
              f"{b['unggul_pct'] - a['unggul_pct']:+.2f} poin "
              f"(B {b['unggul_pct']:+.2f} vs A-tanpa-syarat "
              f"{a['unggul_pct']:+.2f})")
    if h and b and h["cukup_sampel"] and b["cukup_sampel"]:
        beda = b["unggul_pct"] - h["unggul_pct"]
        print(f"NR7 MENAMBAH PADA 52W: {beda:+.2f} poin "
              f"(B {b['unggul_pct']:+.2f} vs H-tanpa-NR7 "
              f"{h['unggul_pct']:+.2f})")
        if beda <= 0:
            print("  -> NR7 TIDAK menambah apa pun. Teori ini sebenarnya")
            print("     'beli yang dekat puncak 52 minggu', dan NR7 cuma")
            print("     mengurangi jumlah sinyalnya.")
    elif h and not h["cukup_sampel"]:
        print("H sampelnya kurang; sumbangan NR7 belum bisa dinilai.")
    if b and c and b["cukup_sampel"] and c["cukup_sampel"]:
        beda = b["unggul_pct"] - c["unggul_pct"]
        print(f"SYARAT 'DEKAT PUNCAK' MENAMBAH: {beda:+.2f} poin "
              f"(B {b['unggul_pct']:+.2f} vs C {c['unggul_pct']:+.2f})")
        if beda <= 0:
            print("  -> tidak menambah apa pun; ia cuma membuang sebagian")
            print("     setup NR7, dan kebetulan yang mana.")
    else:
        print("B atau C sampelnya kurang; persilangannya belum bisa dinilai.")
    if b and d and b["cukup_sampel"] and d["cukup_sampel"]:
        print(f"AMBANG 98% vs 90%: {b['unggul_pct'] - d['unggul_pct']:+.2f} "
              f"poin. Kalau <= 0, ketatnya tidak berbayar.")
    print("\nIngat: ini unggul 20 hari, BUKAN win rate TP/SL. Audit Sinyal")
    print("yang mengukur yang kedua, dan keduanya menjawab hal berbeda.")
    print(f"\ntersimpan: {KELUARAN}")


if __name__ == "__main__":
    main()
