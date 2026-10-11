"""Gabungkan pengukuran pola 2 tahun & 5 tahun jadi satu tabel berstatus.

KENAPA DUA PERIODE. Sepanjang hari ini enam hal yang "kelihatan
meyakinkan" tidak bertahan saat metodenya diperbaiki, dan satu pelajaran
berulang: keunggulan yang terukur di proyek ini KECIL dibanding
sebarannya. Satu angka dari satu periode tidak cukup untuk membedakan
temuan dari kebetulan.

Uji kestabilannya sederhana dan keras:

    STABIL  = tandanya SAMA di kedua periode, dan sampel keduanya
              memadai. Hanya yang ini boleh dipajang sbg angka.
    GOYAH   = tandanya berbalik antar-periode. Dipajang dengan
              peringatan, bukan disembunyikan -- pembaca berhak tahu
              bahwa aplikasinya sendiri belum yakin.
    SEPIHAK = cuma terukur di satu periode (sampel kurang di satunya).

Pola yang tandanya berbalik antar-periode TIDAK layak dipercaya, berapa
pun besar angkanya di salah satu periode. Justru angka besar dari satu
periode yang paling berbahaya: ia paling meyakinkan dan paling mudah
kebetulan.
"""
import io
import json
import os

AKAR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
F2 = os.path.join(AKAR, "tools", "hasil_ukur_pola.json")
F5 = os.path.join(AKAR, "tools", "hasil_ukur_pola_5y.json")
TARGET = os.path.join(AKAR, "core", "pola_ukur.py")
PENANDA = "# METODENYA"
MIN_N = 100
# Ambang kedua, lebih rendah: sampel segini belum cukup untuk MEMPERCAYAI
# angkanya, tapi cukup untuk menyatakan ARAHNYA kalau tanda itu sama di
# dua periode yang berbeda.
#
# Wedge contohnya. Sesudah detektornya dibetulkan, bahkan 5 tahun cuma
# memberi n=80 dan n=86 -- di bawah MIN_N. Tapi Falling Wedge positif di
# KEDUA periode dan Rising Wedge tembus negatif di KEDUA periode, yaitu
# arah yang memang seharusnya. Mengosongkannya sama sekali membuang
# kabar itu; pembaca berhak tahu "detektornya bekerja secara arah, cuma
# kejadiannya terlalu jarang untuk diberi angka".
MIN_N_ARAH = 30


def _muat(f):
    d = json.load(io.open(f, encoding="utf-8"))
    return d, {(r["nama"], r["fase"]): r for r in d["pola"]}


def main():
    d2, m2 = _muat(F2)
    d5, m5 = _muat(F5)
    kunci = sorted(set(m2) | set(m5))

    baris, ringkas = [], {"stabil": 0, "goyah": 0, "sepihak": 0, "kurang": 0}
    for k in kunci:
        a, b = m2.get(k), m5.get(k)
        ok2 = bool(a and a["n"] >= MIN_N)
        ok5 = bool(b and b["n"] >= MIN_N)
        if not ok2 and not ok5:
            # Sampel di bawah MIN_N -- tapi kalau keduanya >= MIN_N_ARAH
            # dan tandanya SAMA, arahnya tetap layak disebut.
            cukup_arah = (a and b and a["n"] >= MIN_N_ARAH
                          and b["n"] >= MIN_N_ARAH
                          and (a["unggul_pct"] > 0) == (b["unggul_pct"] > 0))
            if cukup_arah:
                ringkas["arah"] = ringkas.get("arah", 0) + 1
                baris.append(
                    f'    ("{k[0]}", "{k[1]}"): {{'
                    f'"unggul_pct": None, "n": {a["n"]}, '
                    f'"pct_positif": {a["pct_positif"]}, '
                    f'"status": "arah_saja", '
                    f'"arah_terukur": "{"naik" if a["unggul_pct"] > 0 else "turun"}", '
                    f'"unggul_5y": {b["unggul_pct"]}, "n_5y": {b["n"]}}},')
                continue
            ringkas["kurang"] += 1
            baris.append(f'    # {k[0]} / {k[1]}: sampel kurang di kedua '
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
            f'    ("{k[0]}", "{k[1]}"): {{'
            f'"unggul_pct": {pakai["unggul_pct"]}, "n": {pakai["n"]}, '
            f'"pct_positif": {pakai["pct_positif"]}, "status": "{status}", '
            f'"unggul_5y": {b["unggul_pct"] if ok5 else None}, '
            f'"n_5y": {b["n"] if ok5 else None}}},')

    blok = f'''# METODENYA, dan tiap butir menutup satu jebakan yang sudah pernah
# menggigit proyek ini:
#
#   - JALAN MAJU. Deteksi pada bar t hanya melihat data sampai t;
#     hasilnya diukur dari t ke t+{d2["horizon_hari"]} bar.
#   - PER POLA, BUKAN PER HARI. Satu pola yang bertahan dua minggu
#     dihitung SEKALI.
#   - JEDA ANTAR-SAMPEL sepanjang horizon.
#   - DASAR SETANGGAL, bukan rata-rata seluruh periode.
#   - DUA PERIODE sebagai UJI KESTABILAN (lihat `status` di tiap baris).
#
# STATUS tiap baris:
#     "stabil"  tandanya SAMA di 2 tahun ({d2["n_emiten"]} emiten) dan 5 tahun
#               ({d5["n_emiten"]} emiten). Hanya ini yang layak dibaca sbg angka.
#     "goyah"   tandanya BERBALIK antar-periode. Dipajang dengan
#               peringatan, bukan disembunyikan -- pembaca berhak tahu
#               bahwa aplikasinya sendiri belum yakin.
#     "sepihak"   cuma cukup sampel di satu periode.
#     "arah_saja" sampelnya di bawah ambang angka, TAPI tandanya sama
#                 di dua periode. unggul_pct sengaja None -- yang
#                 disampaikan cuma ARAHNYA, bukan besarnya. Wedge ada
#                 di golongan ini: bahkan 5 tahun cuma memberi n=80.
#
# Angka utamanya dari periode 2 TAHUN (lebih mencerminkan pasar
# sekarang); angka 5 tahun ikut disimpan sbg pembanding.
#
# Pola yang tandanya berbalik TIDAK layak dipercaya, berapa pun besar
# angkanya di salah satu periode. Justru angka besar dari satu periode
# yang paling berbahaya: ia paling meyakinkan dan paling mudah
# kebetulan.
UNGGUL_POLA: dict[tuple[str, str], dict] = {{
{chr(10).join(baris)}
}}

DASAR_PCT: float | None = {d2["dasar_pct"]}
DASAR_5Y_PCT: float | None = {d5["dasar_pct"]}
HORIZON_HARI = {d2["horizon_hari"]}
N_EMITEN_UKUR: int | None = {d2["n_emiten"]}
TANGGAL_UKUR: str | None = "2026-10-12"
'''

    s = io.open(TARGET, encoding="utf-8").read()
    io.open(TARGET, "w", encoding="utf-8", newline="\n").write(
        s[:s.index(PENANDA)] + blok)
    print(f"core/pola_ukur.py: stabil {ringkas['stabil']}, "
          f"goyah {ringkas['goyah']}, sepihak {ringkas['sepihak']}, "
          f"arah saja {ringkas.get('arah', 0)}, "
          f"sampel kurang {ringkas['kurang']}")
    print()
    print(f"{'POLA':26} {'FASE':10} {'2 THN':>8} {'5 THN':>8}  STATUS")
    for k in kunci:
        a, b = m2.get(k), m5.get(k)
        v2 = f"{a['unggul_pct']:+.2f}" if a and a["n"] >= MIN_N else "   -"
        v5 = f"{b['unggul_pct']:+.2f}" if b and b["n"] >= MIN_N else "   -"
        st = ""
        if a and b and a["n"] >= MIN_N and b["n"] >= MIN_N:
            st = "stabil" if (a["unggul_pct"] > 0) == (b["unggul_pct"] > 0) else "GOYAH"
        print(f"{k[0]:26} {k[1]:10} {v2:>8} {v5:>8}  {st}")


if __name__ == "__main__":
    main()
