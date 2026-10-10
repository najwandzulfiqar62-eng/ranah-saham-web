"""Tulis hasil tools/ukur_pola.py ke core/pola_ukur.py.

DIBUAT SKRIP, BUKAN DISALIN TANGAN: tabel 30-an baris angka yang disalin
manual akan punya satu angka yang salah, dan satu angka salah di tabel
yang dipakai layar lebih buruk daripada tabel kosong -- ia terlihat
persis sebenar yang lain.

BISA DIJALANKAN BERULANG. Versi pertama mencari penampung kosong
`UNGGUL_POLA ... = {}` dan karena itu cuma cocok sekali; begitu tabelnya
terisi, pembaruan berikutnya terpaksa manual. Yang ini menimpa dari
penanda METODENYA sampai akhir berkas.
"""
import io
import json
import os

AKAR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HASIL = os.path.join(AKAR, "tools", "hasil_ukur_pola.json")
TARGET = os.path.join(AKAR, "core", "pola_ukur.py")
PENANDA = "# METODENYA"

# n minimum agar sebuah angka LAYAK DIPAJANG.
#
# Dinaikkan dari 15 ke 100 sesudah detektor wedge diperbaiki. Dengan
# ambang lama, "Rising Wedge TERBENTUK +18,06%" dari 23 kejadian akan
# dipajang -- dan keunggulan 18% dalam 20 hari bursa itu tidak kredibel,
# ia derau dari sampel kecil. Tiga puluh sel diuji sekaligus; dengan
# sampel sekecil itu, satu di antaranya hampir pasti terlihat luar biasa
# karena kebetulan.
#
# Yang terlewat tidak dibuang, cuma tidak diberi angka: layar menulis
# "belum diukur", dan itu pernyataan yang benar.
MIN_N = 100


def main():
    d = json.load(io.open(HASIL, encoding="utf-8"))
    pola = sorted(d["pola"], key=lambda x: (x["nama"], x["fase"]))
    masuk = [r for r in pola if r["n"] >= MIN_N]
    lewat = [r for r in pola if r["n"] < MIN_N]

    baris = []
    for r in masuk:
        baris.append(
            f'    ("{r["nama"]}", "{r["fase"]}"): '
            f'{{"unggul_pct": {r["unggul_pct"]}, "n": {r["n"]}, '
            f'"pct_positif": {r["pct_positif"]}}},')
    for r in lewat:
        baris.append(f'    # {r["nama"]} / {r["fase"]}: n={r["n"]} '
                     f'-- di bawah MIN_N, sengaja tanpa angka')

    blok = f'''# METODENYA, dan tiap butir menutup satu jebakan yang sudah pernah
# menggigit proyek ini:
#
#   - JALAN MAJU. Deteksi pada bar t hanya melihat data sampai t;
#     hasilnya diukur dari t ke t+{d["horizon_hari"]} bar.
#   - PER POLA, BUKAN PER HARI. Satu pola yang bertahan dua minggu
#     dihitung SEKALI. Tanpa ini n menggelembung dan hasilnya saling
#     berkorelasi -- sudah terjadi tiga kali di proyek ini.
#   - JEDA ANTAR-SAMPEL sepanjang horizon, supaya jendelanya tidak
#     bertindihan.
#   - DASAR SETANGGAL: dibandingkan rata-rata return {d["horizon_hari"]} hari SELURUH
#     emiten yang mulai di tanggal yang sama, bukan rata-rata seluruh
#     periode.
#
# n < {MIN_N} SENGAJA TIDAK DIPAJANG. Tiga puluh sel diuji sekaligus; dari
# sampel kecil, satu di antaranya hampir pasti terlihat luar biasa
# karena kebetulan. Wedge contohnya: sesudah detektornya diperbaiki,
# "Rising Wedge TERBENTUK +18,06%" datang dari 23 kejadian saja, dan
# keunggulan 18% dalam {d["horizon_hari"]} hari bursa tidak kredibel.
UNGGUL_POLA: dict[tuple[str, str], dict] = {{
{chr(10).join(baris)}
}}

# Dasar pembanding: rata-rata return {d["horizon_hari"]} hari bursa SELURUH emiten
# pada tanggal yang sama.
DASAR_PCT: float | None = {d["dasar_pct"]}
HORIZON_HARI = {d["horizon_hari"]}
N_EMITEN_UKUR: int | None = {d["n_emiten"]}
TANGGAL_UKUR: str | None = "2026-10-12"
'''

    s = io.open(TARGET, encoding="utf-8").read()
    awal = s.index(PENANDA)
    io.open(TARGET, "w", encoding="utf-8", newline="\n").write(s[:awal] + blok)
    print(f"core/pola_ukur.py: {len(masuk)} baris berangka, "
          f"{len(lewat)} dilewati (n < {MIN_N})")


if __name__ == "__main__":
    main()
