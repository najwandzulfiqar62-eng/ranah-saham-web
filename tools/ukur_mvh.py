"""Ukur "Minervini x Harmonic" -- dan terutama: apakah harmonic MENAMBAH.

KENAPA ALAT INI ADA. MVH adalah sumber sinyal ke-5 di aplikasi ini: ia
menulis ke signal_history dengan direction BUY, diaudit, dan ikut
membentuk win rate. Syaratnya harmonic BULLISH, dan sisi bullish itu
yang terukur paling lemah dari seluruh tabel harmonic:

    SEMUA bearish   +0,20%  (n=458)   <- tidak dipakai teori ini
    SEMUA bullish   -0,12%  (n=414)   <- yang dipakai
    ABCD  bullish   +0,09%  (n=327)

Pencatatannya dijeda 12 Okt 2026 (MVH_CATAT_AKTIF=0 di web/app.py)
sampai ada angka. Ini alat yang memberi angkanya.

PERTANYAANNYA BUKAN "APAKAH MVH UNTUNG"
=======================================
MVH menuntut DUA syarat. Kalau diukur sendirian lalu hasilnya positif,
itu belum berarti apa pun -- bisa jadi seluruh angkanya datang dari
Minervini, dan harmonic cuma mengurangi jumlah sinyal tanpa menambah
kualitas. Pengurangan jumlah sinyal selalu terlihat seperti
"penyaringan yang ketat", padahal yang terjadi mungkin cuma membuang
sinyal secara acak.

Jadi yang diukur TIGA sel pada SAMPEL YANG SAMA:

    A. Minervini >= 7/8 saja                 (seluruh bar yang lolos)
    B. Minervini >= 7/8 DAN harmonic bullish (persilangannya = MVH)
    C. Minervini >= 7/8 TANPA harmonic       (pelengkap B)

Yang menentukan adalah B vs C, bukan B vs nol. Kalau B <= C, harmonic
TIDAK menambah apa pun -- ia cuma membuang sebagian sinyal Minervini,
dan kebetulan membuang yang mana. Kalau B > C dengan selisih yang
bertahan di dua periode, barulah persilangan itu punya alasan.

METODENYA, sama dengan pengukuran lain di proyek ini:
  - JALAN MAJU. Pada bar t cuma data sampai t yang dilihat.
  - PER SETUP, bukan per hari. Jeda antar-sampel sepanjang horizon,
    supaya satu keadaan yang bertahan dua minggu tidak dihitung
    sepuluh kali. Ini jebakan yang sudah menggigit proyek ini
    berkali-kali, dan ia selalu melebih-lebihkan.
  - DASAR SETANGGAL, bukan rata-rata seluruh periode.
  - DUA PERIODE sebagai uji kestabilan (UKUR_PERIODE=2y lalu 5y).

MAHAL, dan karena itu disusun begini: detect_harmonic dipanggil HANYA
pada bar yang sudah lolos Minervini. Minervini dihitung vektor (rolling
MA & 52 minggu) jadi nyaris gratis; harmonic yang berat. Memanggilnya
di tiap bar tiap emiten akan memakan jam, dan tidak ada gunanya --
persilangannya memang cuma perlu tahu harmonic pada bar yang lolos.

Jalankan:
  UKUR_PERIODE=2y python tools/ukur_mvh.py
  UKUR_PERIODE=5y UKUR_KELUARAN=hasil_ukur_mvh_5y.json python tools/ukur_mvh.py
"""
import json
import os
import sys
import time
import warnings
from collections import defaultdict

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.abspath("."))

import pandas as pd  # noqa: E402
import yfinance as yf  # noqa: E402

from core.harmonic import detect_harmonic  # noqa: E402
from core.stock_data import load_tickers  # noqa: E402

HORIZON = 20
PERIODE = os.getenv("UKUR_PERIODE", "2y")
KELUARAN = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        os.getenv("UKUR_KELUARAN", "hasil_ukur_mvh.json"))
MIN_N = 100

# Ambang Minervini yang SAMA dengan produksi (core/screening_pro.py).
# Dibaca dari env dengan bawaan yang sama supaya pengukurannya tidak
# diam-diam mengukur saringan yang berbeda dari yang dipajang.
MIN_KRITERIA = int(os.getenv("MINERVINI_MIN_KRITERIA", "7"))

# Umur maksimum pola harmonic, SAMA dengan cache yang dipakai MVH di
# produksi (screener_harmonic:v3:luas:bullish:10). Pola tua bukan titik
# masuk, dan kalau angka ini berbeda dari produksinya maka yang diukur
# bukan teori yang dijalankan.
MAKS_UMUR_D = 10

# Bar minimum sebelum sebuah bar boleh dinilai: 252 (52 minggu) + 21
# (MA200 sebulan lalu) + bantalan. Di bawah ini kriteria Minervini tidak
# terdefinisi, dan memaksanya menghasilkan "lolos" yang palsu.
MIN_RIWAYAT = 285

# Jendela yang diberikan ke detect_harmonic. 245 ~ satu tahun bursa,
# SAMA dengan yang dilihat produksi (api_screener_harmonic mengunduh
# period="1y").
#
# Versi pertama mengirim SELURUH riwayat sampai bar i -- pada periode 2
# tahun itu ~490 bar. Akibatnya bukan cuma lambat: pola yang butuh 400
# bar untuk terbentuk tidak akan PERNAH terlihat produksi, tapi
# terhitung di pengukuran. Yang terukur jadi bukan teori yang
# dijalankan.
EKOR = 245

# Universe dibatasi, dan batasnya disebut di hasilnya. detect_harmonic
# memakan ~117 ms per bar karena ia menelusuri kombinasi lima pivot,
# bukan menghitung satu rumus. Batas yang SAMA dengan
# tools/ukur_harmonic.py, supaya angkanya bisa dibandingkan dengan tabel
# harmonic yang sudah ada.
#
# Angkanya HANYA berlaku untuk emiten likuid. Saham sepi punya harga
# penutupan yang tidak mencerminkan harga yang bisa didapat, dan
# menyebut hasilnya berlaku umum akan menjanjikan yang tidak diuji.
N_EMITEN = int(os.getenv("UKUR_N_EMITEN", "250"))


def _minervini_vektor(df: pd.DataFrame, pasar: pd.Series) -> pd.Series:
    """criteria_met (0-8) untuk SETIAP bar, dihitung vektor.

    Replikasi _score_minervini di core/screening_pro.py, kriteria per
    kriteria. Kalau yang di sana berubah, yang di sini WAJIB menyusul --
    kalau tidak, yang diukur bukan saringan yang dipajang.
    """
    c = df["Close"]
    ma50 = c.rolling(50).mean()
    ma150 = c.rolling(150).mean()
    ma200 = c.rolling(200).mean()
    ma200_lalu = ma200.shift(21)
    hi52 = c.rolling(252).max()
    lo52 = c.rolling(252).min()

    # RS vs pasar: selisih return 63 bar, dinormalkan sigmoid sederhana
    # (rs = 50 + diff * 1.75, dipotong 0..100) -- persis seperti
    # _calculate_rs_vs_market.
    sejajar = pd.concat([c.rename("s"), pasar.rename("m")], axis=1,
                        join="inner").reindex(c.index).ffill()
    ret_s = (sejajar["s"] / sejajar["s"].shift(63) - 1) * 100
    ret_m = (sejajar["m"] / sejajar["m"].shift(63) - 1) * 100
    rs = (50 + (ret_s - ret_m) * 1.75).clip(0, 100).fillna(50.0)

    return (
        (c > ma50).astype(int)
        + (c > ma150).astype(int)
        + (c > ma200).astype(int)
        + ((ma50 > ma150) & (ma150 > ma200)).astype(int)
        + (ma200 > ma200_lalu).astype(int)
        + (c >= lo52 * 1.30).astype(int)
        + (c >= hi52 * 0.75).astype(int)
        + (rs >= 70).astype(int)
    )


def main():
    tk = load_tickers()[:N_EMITEN]
    print(f"universe: {len(tk)} (dibatasi; HANYA emiten likuid) | "
          f"periode {PERIODE} | "
          f"Minervini >= {MIN_KRITERIA}/8 | harmonic <= {MAKS_UMUR_D} bar",
          flush=True)

    raw = yf.download(tk + ["^JKSE"], period=PERIODE, interval="1d",
                      progress=False, auto_adjust=False, threads=True,
                      group_by="ticker")
    try:
        pasar = raw["^JKSE"]["Close"].dropna()
    except Exception:
        print("GAGAL: data IHSG tidak terambil; RS tidak bisa dihitung.")
        sys.exit(1)

    deret = {}
    for t in tk:
        try:
            df = raw[t].dropna()
        except Exception:
            continue
        if len(df) >= MIN_RIWAYAT + HORIZON:
            deret[t.replace(".JK", "")] = df
    print(f"terpakai: {len(deret)} emiten", flush=True)
    if not deret:
        print("GAGAL: tidak ada emiten dengan riwayat cukup.")
        sys.exit(1)

    # Dasar pembanding PER TANGGAL. Dasar tunggal untuk seluruh periode
    # akan melebih-lebihkan teori yang kebetulan menyala di bulan-bulan
    # bagus -- jebakan yang sudah membatalkan satu temuan di proyek ini.
    per_tgl = defaultdict(list)
    for kode, df in deret.items():
        cl = df["Close"].tolist()
        tg = [str(x)[:10] for x in df.index]
        for i in range(len(cl) - HORIZON):
            if cl[i] > 0:
                per_tgl[tg[i]].append((cl[i + HORIZON] - cl[i]) / cl[i] * 100)
    dasar = {d: sum(v) / len(v) for d, v in per_tgl.items() if len(v) >= 30}

    hasil = defaultdict(list)
    n_panggil_harmonic = 0
    t0 = time.time()
    for n_e, (kode, df) in enumerate(deret.items(), 1):
        if n_e % 50 == 0:
            sisa = (time.time() - t0) / n_e * (len(deret) - n_e)
            print(f"  {n_e}/{len(deret)}  {time.time()-t0:.0f}s "
                  f"(sisa ~{sisa/60:.0f} mnt, {n_panggil_harmonic} panggilan "
                  f"harmonic)", flush=True)

        try:
            kriteria = _minervini_vektor(df, pasar)
        except Exception:
            continue
        cl = df["Close"].tolist()
        tg = [str(x)[:10] for x in df.index]
        km = kriteria.tolist()
        n = len(cl)

        # SATU jeda, dipakai bersama seluruh sel -- bukan satu jeda per
        # sel. Versi pertama menyimpannya per sel, sehingga satu gerakan
        # harga bisa menyumbang sampel B pada bar 100 dan sampel C pada
        # bar 105: return 20 hari yang SEBAGIAN BESAR SAMA, dihitung di
        # kedua sisi perbandingan yang justru sedang diuji. Itu merusak
        # tepat angka yang dicari.
        jeda = -999
        for i in range(MIN_RIWAYAT, n - HORIZON):
            if i < jeda:
                continue
            if km[i] < MIN_KRITERIA:
                continue
            d = dasar.get(tg[i])
            if d is None or not cl[i]:
                continue
            ret = (cl[i + HORIZON] - cl[i]) / cl[i] * 100
            lebih = ret - d
            jeda = i + HORIZON

            # HARMONIC hanya dihitung di sini -- pada bar yang sudah lolos
            # Minervini DAN sudah lewat jedanya. Potongannya berhenti di
            # i: tidak ada satu bar masa depan yang terlihat. Awalnya
            # dipotong EKOR bar ke belakang, jendela yang sama dengan
            # yang dilihat produksi.
            awal = max(0, i - EKOR + 1)
            n_panggil_harmonic += 1
            try:
                pola = detect_harmonic(df.iloc[awal:i + 1]) or []
            except Exception:
                pola = []
            hm = next((p for p in pola
                       if p.get("arah") == "bullish"
                       and (p.get("bar_sejak_d") or 99) <= MAKS_UMUR_D), None)

            sel = ["A. Minervini saja"]
            sel.append("B. Minervini x Harmonic bullish" if hm
                       else "C. Minervini TANPA harmonic")
            if hm:
                # Per pola, supaya terlihat apakah salah satu bentuk yang
                # menanggung seluruh angkanya.
                sel.append(f"B/{hm.get('pola')}")

            for nama in sel:
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
    ringkas.sort(key=lambda r: (r["aturan"][0], -r["unggul_pct"]))
    dasar_rata = sum(dasar.values()) / len(dasar) if dasar else 0.0

    with open(KELUARAN, "w", encoding="utf-8") as f:
        json.dump({"horizon_hari": HORIZON, "periode": PERIODE,
                   "n_emiten": len(deret), "min_kriteria": MIN_KRITERIA,
                   "maks_umur_d": MAKS_UMUR_D, "ekor_bar": EKOR,
                   "hanya_likuid": True,
                   "dasar_pct": round(dasar_rata, 2),
                   "aturan": ringkas}, f, ensure_ascii=False, indent=1)

    print(f"\ndasar pasar {HORIZON} hari: {dasar_rata:+.2f}%  "
          f"({len(deret)} emiten, periode {PERIODE})\n")
    print(f"{'ATURAN':34} {'n':>7} {'UNGGUL':>9} {'RETURN':>9} {'%+':>7}")
    for r in ringkas:
        tanda = "" if r["cukup_sampel"] else "  (sampel kurang)"
        print(f"{r['aturan']:34} {r['n']:7d} {r['unggul_pct']:+9.2f} "
              f"{r['return_pct']:+9.2f} {r['pct_positif']:6.1f}%{tanda}")

    # YANG MENENTUKAN: B vs C, bukan B vs nol.
    b = next((r for r in ringkas if r["aturan"].startswith("B. ")), None)
    c = next((r for r in ringkas if r["aturan"].startswith("C. ")), None)
    print()
    if b and c and b["cukup_sampel"] and c["cukup_sampel"]:
        beda = b["unggul_pct"] - c["unggul_pct"]
        print(f"HARMONIC MENAMBAH: {beda:+.2f} poin "
              f"(B {b['unggul_pct']:+.2f} vs C {c['unggul_pct']:+.2f})")
        if beda <= 0:
            print("  -> harmonic TIDAK menambah apa pun. Ia cuma membuang")
            print("     sebagian sinyal Minervini, dan kebetulan yang mana.")
        else:
            print("  -> ada selisih. BELUM berarti temuan: ulangi dengan")
            print("     UKUR_PERIODE=5y; tanda yang berbalik antar-periode")
            print("     tidak layak dipercaya berapa pun besarnya.")
    else:
        print("B atau C sampelnya kurang; persilangannya belum bisa dinilai.")
    print(f"\ntersimpan: {KELUARAN}")


if __name__ == "__main__":
    main()
