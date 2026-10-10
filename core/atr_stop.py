"""Jarak stop & target yang menyesuaikan derau tiap saham.

MASALAH YANG DITUTUP. Stop dihitung dari jarak ke S1 (pivot support), dan
hasilnya rata-rata 3%. Diukur 7 Okt 2026 pada 658 sinyal sungguhan
(Jul-Okt, termasuk September saat IHSG turun 8%):

    ATR harian saham yang disinyalkan, median : 3,60%
    Stop yang dipasang                        : 3,00%  = 0,8x ATR
    Kena stop                                 : 53,8%

Stop itu berada DI DALAM derau satu hari. Ia tidak kena karena analisisnya
salah -- ia kena karena harinya hari biasa.

YANG DIUKUR SEBAGAI GANTINYA (658 sinyal, maks 20 hari bursa):

    TP6%/SL3%  (sekarang)       untung 43,5%   ekspektasi +0,79%
    TP10%/SL7% tetap            untung 52,5%   ekspektasi +1,55%
    TP20%/SL10% tetap           untung 52,8%   ekspektasi +2,44%
    SL 2,5xATR / TP 5xATR       untung 52,2%   ekspektasi +2,61%  <-- dipakai

ATR menang karena stop 3% untuk BBCA dan untuk saham gorengan adalah dua
hal yang sangat berbeda; ATR membuat keduanya sepadan dengan deraunya
masing-masing. Bentuknya konsisten di pengali 1,5x / 2x / 2,5x / 3x --
bukan satu titik beruntung dari mengulik angka.

DIKUATKAN SUMBER LAIN. Edwards & Magee (buku yang jadi rujukan skripsi
penulis lewat Edianto Ong) menyarankan penetrasi 6% -- bukan 3% --
khusus bila stop dititipkan ke broker, dengan alasan yang persis sama:
jarak yang lebih lebar mengurangi kemungkinan stop tersentuh lonjakan
intraday yang tidak berarti. Teori 1948 dan pengukuran 2026 sampai ke
kesimpulan yang sama.

YANG HARUS DIINGAT PEMAKAINYA: stop yang lebih lebar = rugi lebih besar
saat salah. Yang menjaga rupiah tetap sama adalah UKURAN POSISI, dan
core/risk_management.py sudah menghitung lot dari jarak stop -- jadi lot
mengecil sendiri. Kalau suatu hari ada jalur yang menentukan lot TANPA
membaca sl_pct, jalur itu akan melipatgandakan risiko tanpa satu pun
tanda.
"""

# Pengali ATR. 2,5x dipilih dari grid; 2,0x memberi +2,15% (masih 2,7x
# lipat dari keadaan sekarang) kalau suatu hari dirasa terlalu lebar.
PENGALI_SL = 2.5

# Target = dua kali jarak stop. Itu rasio yang diukur (TP 5xATR terhadap
# SL 2,5xATR), bukan angka yang dipilih karena terdengar enak.
RASIO_TP = 2.0

# Pagar kewarasan. ATR bisa kacau pada saham yang baru IPO, baru lepas
# suspensi, atau datanya rusak -- tanpa pagar, satu angka aneh menghasilkan
# stop 60% yang akan diterima begitu saja oleh seluruh rantai di hilirnya.
MIN_SL_PCT = 2.0
MAKS_SL_PCT = 15.0


def jarak_stop(sr_pct: float | None, atr_pct: float | None) -> float | None:
    """Jarak stop (%), yang terlebar antara level teknikal dan derau.

    `sr_pct` = jarak ke support terdekat, `atr_pct` = ATR harian sebagai
    persen harga.

    DIAMBIL YANG TERBESAR, bukan diganti begitu saja. Level support punya
    arti yang tidak dimiliki ATR -- di situlah harga pernah berhenti. Yang
    ditolak di sini cuma satu keadaan: support yang kebetulan berada di
    dalam derau harian sahamnya sendiri. Support semacam itu bukan support,
    ia cuma titik yang akan tersentuh besok apa pun yang terjadi.

    None kalau tidak ada satu pun masukan yang sah -- JANGAN dikarang jadi
    angka bawaan: stop yang dikarang lebih berbahaya daripada sinyal yang
    tidak jadi dicatat.
    """
    calon = []
    if sr_pct is not None and sr_pct > 0:
        calon.append(float(sr_pct))
    if atr_pct is not None and atr_pct > 0:
        calon.append(float(atr_pct) * PENGALI_SL)
    if not calon:
        return None
    return round(max(MIN_SL_PCT, min(MAKS_SL_PCT, max(calon))), 2)


def jarak_target(sl_pct: float | None, sr_pct: float | None = None) -> float | None:
    """Jarak target (%) -- minimal dua kali jarak stop.

    `sr_pct` = jarak ke resistance terdekat, kalau ada. Diambil yang
    TERBESAR juga: resistance yang lebih jauh berarti ruangnya memang lebih
    lebar, dan memotongnya di 2x stop akan membuang bagian yang justru
    menghasilkan.

    Yang TIDAK boleh terjadi adalah sebaliknya -- target lebih dekat
    daripada dua kali stop. Dengan stop yang kini lebih lebar, target lama
    yang dihitung dari R1 bisa jatuh di bawah stop-nya sendiri, dan itu
    menghasilkan rencana yang rugi bahkan ketika benar.
    """
    if sl_pct is None or sl_pct <= 0:
        return None
    dasar = sl_pct * RASIO_TP
    if sr_pct is not None and sr_pct > dasar:
        dasar = float(sr_pct)
    return round(dasar, 2)


def sesuaikan(potensi_naik_pct: float | None, risiko_turun_pct: float | None,
              atr_pct: float | None) -> tuple[float | None, float | None]:
    """(target, stop) yang sudah disesuaikan derau. None kalau tak terhitung."""
    sl = jarak_stop(risiko_turun_pct, atr_pct)
    return jarak_target(sl, potensi_naik_pct), sl
