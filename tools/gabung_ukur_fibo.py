"""Gabungkan pengukuran Fibonacci 2 tahun & 5 tahun jadi satu tabel berstatus.

KENAPA FIBONACCI YANG TERAKHIR DIURUS. Pola chart dan SMC sudah lulus uji
dua periode; Fibonacci tidak. Ia satu-satunya angka di aplikasi ini yang
masih berdiri di atas SATU pengukuran -- dan justru Fibonacci yang punya
riwayat paling buruk soal itu.

Pengukuran Fibonacci yang PERTAMA, waktu ayunannya masih diambil dari pivot
terakhir, memberi 38,2% naik +0,67% dan turun -1,24%. Selisih 1,91 poin itu
sempat disebut salah satu temuan terbesar di proyek ini. Sesudah
penjangkarannya dibetulkan ke ayunan DOMINAN, selisih itu LENYAP --
keduanya jadi negatif. Satu perbaikan metode menghapus seluruh temuan.

Itu pelajaran tentang satu pengukuran, bukan tentang Fibonacci. Angka yang
cuma punya satu periode tidak bisa dibedakan dari kebetulan, dan angka
BESAR dari satu periode yang paling berbahaya: ia paling meyakinkan.

Aturan statusnya sama persis dengan pola chart dan SMC:

    STABIL  = tandanya SAMA di kedua periode, sampel keduanya memadai.
              Hanya ini yang boleh dipajang sebagai angka.
    GOYAH   = tandanya BERBALIK antar-periode. Dipajang dengan peringatan,
              bukan disembunyikan -- pembaca berhak tahu bahwa aplikasinya
              sendiri belum yakin.
    SEPIHAK = cuma cukup sampel di satu periode.

CATATAN TENTANG TUMPANG TINDIH PERIODE, supaya tidak dibaca lebih kuat
daripada semestinya: 5 tahun MEMUAT 2 tahun. Jadi ini bukan dua sampel
yang saling bebas, dan "tandanya sama" di sini berarti "tambahan tiga
tahun data tidak membalikkannya" -- lebih lemah daripada dua periode
terpisah, tapi tetap menyingkirkan temuan yang hidup hanya karena satu
rentang pendek tertentu. Pola chart dan SMC diukur dengan tumpang tindih
yang sama, jadi ketiganya setara cara bacanya.
"""
import io
import json
import os

AKAR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
F2 = os.path.join(AKAR, "tools", "hasil_ukur_fibo.json")
F5 = os.path.join(AKAR, "tools", "hasil_ukur_fibo_5y.json")
TARGET = os.path.join(AKAR, "core", "fibo.py")
PENANDA = "UNGGUL_FIBO: dict[tuple[float, str], dict] = {"
AKHIR = "def unggul(rasio: float, arah: str) -> dict | None:"

# Ambang sampel SENGAJA tinggi. Lima rasio x tiga arah = lima belas sel
# diuji sekaligus; dari sebanyak itu, satu sel yang terlihat luar biasa
# memang DIHARAPKAN muncul karena kebetulan. "78,6% turun +3,58%" cuma
# 135 kejadian -- itu persis sel seperti itu.
MIN_N = 500

RASIO = {"23.6": 0.236, "38.2": 0.382, "50": 0.500,
         "61.8": 0.618, "78.6": 0.786}


def _muat(f):
    """-> (meta, {(rasio, arah): baris}). Baris 'gabungan arah' dibuang:
    dua arah terukur BERLAWANAN, jadi menggabungkannya saling meniadakan
    dan angkanya tidak mengukur apa pun."""
    d = json.load(io.open(f, encoding="utf-8"))
    per = {}
    for r in d["aturan"]:
        nama = r["aturan"]
        if "gabungan" in nama:
            continue
        # "Fibo 61.8% ayunan naik" -> (0.618, "naik")
        try:
            tengah = nama.split("Fibo ")[1].split("%")[0]
            arah = nama.rsplit(" ", 1)[1]
        except (IndexError, ValueError):
            continue
        if tengah not in RASIO or arah not in ("naik", "turun"):
            continue
        per[(RASIO[tengah], arah)] = r
    return d, per


def main():
    for f in (F2, F5):
        if not os.path.exists(f):
            raise SystemExit(
                f"belum ada: {f}\n"
                "jalankan dulu:\n"
                "  UKUR_PERIODE=2y UKUR_SCAN_BAR=220 python tools/ukur_fibo.py\n"
                "  UKUR_PERIODE=5y UKUR_SCAN_BAR=900 "
                "UKUR_KELUARAN=hasil_ukur_fibo_5y.json python tools/ukur_fibo.py")

    d2, m2 = _muat(F2)
    d5, m5 = _muat(F5)
    kunci = sorted(set(m2) | set(m5))

    baris, ringkas = [], {"stabil": 0, "goyah": 0, "sepihak": 0, "kurang": 0}
    for k in kunci:
        a, b = m2.get(k), m5.get(k)
        ok2 = bool(a and a["n"] >= MIN_N)
        ok5 = bool(b and b["n"] >= MIN_N)
        if not ok2 and not ok5:
            ringkas["kurang"] += 1
            baris.append(f'    # {k[0]} {k[1]}: sampel kurang di kedua '
                         f'periode -- sengaja tanpa angka')
            continue
        if ok2 and ok5:
            sama = (a["unggul_pct"] > 0) == (b["unggul_pct"] > 0)
            status = "stabil" if sama else "goyah"
        else:
            status = "sepihak"
        ringkas[status] += 1
        pakai = a if ok2 else b          # 2 tahun lebih mencerminkan pasar kini
        baris.append(
            f'    ({k[0]}, "{k[1]}"): {{'
            f'"unggul_pct": {pakai["unggul_pct"]}, "n": {pakai["n"]}, '
            f'"pct_positif": {pakai["pct_positif"]}, "status": "{status}", '
            f'"unggul_5y": {b["unggul_pct"] if ok5 else None}, '
            f'"n_5y": {b["n"] if ok5 else None}}},')

    blok = f'''UNGGUL_FIBO: dict[tuple[float, str], dict] = {{
{chr(10).join(baris)}
}}
# Sampel di bawah ini tidak diberi angka. Lima rasio x dua arah diuji
# sekaligus; dari sebanyak itu, satu sel yang terlihat luar biasa memang
# DIHARAPKAN muncul karena kebetulan.
MIN_N_FIBO = {MIN_N}
TANGGAL_UKUR_FIBO = "2026-10-11"
# Uji kestabilan: {d2["periode"]} ({d2["n_emiten"]} emiten, {d2["scan_bar"]} bar)
# vs {d5["periode"]} ({d5["n_emiten"]} emiten, {d5["scan_bar"]} bar).
# Dasar pasar {d2["horizon_hari"]} hari: {d2["dasar_pct"]:+.2f}% (2 thn),
# {d5["dasar_pct"]:+.2f}% (5 thn).
#
# `status` tiap baris: "stabil" tandanya sama di kedua periode (satu-satunya
# yang layak dibaca sebagai angka), "goyah" tandanya BERBALIK, "sepihak"
# cuma cukup sampel di satu periode. 5 tahun MEMUAT 2 tahun, jadi "sama"
# di sini berarti "tambahan tiga tahun tidak membalikkannya" -- bukan dua
# sampel yang saling bebas.


'''

    s = io.open(TARGET, encoding="utf-8").read()
    i, j = s.index(PENANDA), s.index(AKHIR)
    io.open(TARGET, "w", encoding="utf-8", newline="\n").write(
        s[:i] + blok + s[j:])

    print(f"core/fibo.py: stabil {ringkas['stabil']}, goyah {ringkas['goyah']}, "
          f"sepihak {ringkas['sepihak']}, sampel kurang {ringkas['kurang']}")
    print()
    print(f"{'RASIO':8} {'ARAH':7} {'2 THN':>9} {'n':>7} {'5 THN':>9} {'n':>7}  STATUS")
    for k in kunci:
        a, b = m2.get(k), m5.get(k)
        v2 = f"{a['unggul_pct']:+.2f}" if a and a["n"] >= MIN_N else "-"
        v5 = f"{b['unggul_pct']:+.2f}" if b and b["n"] >= MIN_N else "-"
        n2 = a["n"] if a else 0
        n5 = b["n"] if b else 0
        st = ""
        if a and b and a["n"] >= MIN_N and b["n"] >= MIN_N:
            st = "stabil" if (a["unggul_pct"] > 0) == (b["unggul_pct"] > 0) else "GOYAH"
        print(f"{k[0]:<8} {k[1]:7} {v2:>9} {n2:7d} {v5:>9} {n5:7d}  {st}")


if __name__ == "__main__":
    main()
