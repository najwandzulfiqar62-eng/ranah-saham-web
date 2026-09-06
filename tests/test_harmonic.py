"""Deteksi pola harmonic.

Diuji dengan pola yang SENGAJA dibangun dari rasio Fibonacci-nya, bukan data
acak yang kebetulan lolos: kalau detektornya benar, Gartley buatan harus
dikenali sebagai Gartley, dan bentuk yang rasionya salah tidak boleh lolos
hanya karena zig-zagnya mirip.
"""

import numpy as np
import pandas as pd
import pytest

from core.harmonic import detect_harmonic, ringkas_harmonic


def _df_dari_titik(titik: list[float], bar_per_kaki: int = 12) -> pd.DataFrame:
    """Bangun OHLC yang bergerak lurus dari satu titik ke titik berikutnya.

    Tiap kaki diberi cukup bar supaya pivotnya terdeteksi detect_swing_points
    (butuh 5 bar kiri & kanan).
    """
    # Kaki AWALAN menuju X. Tanpa ini X berada di bar pertama dan TIDAK
    # pernah terdeteksi sebagai pivot -- detect_swing_points butuh 5 bar di
    # kiri. Arahnya otomatis benar untuk bullish maupun bearish: titiknya
    # ditaruh di seberang A, jadi X selalu jadi puncak/lembah sungguhan.
    awalan = titik[0] + 0.3 * (titik[1] - titik[0])
    titik = [awalan] + list(titik)

    harga = []
    for i in range(len(titik) - 1):
        harga += list(np.linspace(titik[i], titik[i + 1], bar_per_kaki, endpoint=False))
    harga.append(titik[-1])
    # Ekor datar supaya pivot terakhir punya bar kanan yang cukup.
    harga += [titik[-1]] * 8
    h = np.array(harga, dtype=float)
    return pd.DataFrame({
        "Open": h, "High": h + 0.5, "Low": h - 0.5, "Close": h,
        "Volume": np.full(len(h), 1_000_000),
    }, index=pd.bdate_range(end=pd.Timestamp("2026-09-04"), periods=len(h)))


def _gartley_bullish() -> list[float]:
    """X-A-B-C-D dengan rasio Gartley: AB=0.618 XA, BC=0.5 AB, CD=1.4 BC,
    dan AD = 0.786 XA."""
    X, A = 100.0, 200.0
    xa = A - X
    B = A - 0.618 * xa                    # 138.2
    ab = A - B
    C = B + 0.5 * ab                      # 169.1
    D = A - 0.786 * xa                    # 121.4
    return [X, A, B, C, D]


def test_gartley_bullish_dikenali_dengan_titik_dan_rasionya():
    df = _df_dari_titik(_gartley_bullish())
    hasil = detect_harmonic(df)
    assert hasil, "pola Gartley yang dibangun dari rasionya sendiri harus terdeteksi"
    p = hasil[0]
    assert p["pola"] == "Gartley"
    assert p["arah"] == "bullish"
    # Titik D = area pembalikan, harus dekat 0.786 dari XA.
    assert p["prz"] == pytest.approx(121.4, abs=3)
    assert [t["label"] for t in p["titik"]] == ["X", "A", "B", "C", "D"]
    assert p["rasio"]["AB/XA"] == pytest.approx(0.618, abs=0.06)
    assert p["rasio"]["AD/XA"] == pytest.approx(0.786, abs=0.06)


def test_bentuk_zigzag_dengan_rasio_salah_tidak_diklaim_sebagai_pola():
    """Zig-zag saja tidak cukup. Kalau rasionya jauh dari pola mana pun,
    mengklaimnya sebagai harmonic lebih berbahaya daripada diam."""
    # AB cuma 15% dari XA, CD nyaris rata -- tidak cocok pola mana pun.
    df = _df_dari_titik([100.0, 200.0, 185.0, 190.0, 187.0])
    assert detect_harmonic(df) == []


def test_arah_bearish_terbaca_saat_pola_terbalik():
    X, A = 200.0, 100.0
    xa = X - A
    B = A + 0.618 * xa
    ab = B - A
    C = B - 0.5 * ab
    D = A + 0.786 * xa
    hasil = detect_harmonic(_df_dari_titik([X, A, B, C, D]))
    assert hasil and hasil[0]["arah"] == "bearish"
    assert hasil[0]["pola"] == "Gartley"


def test_data_terlalu_pendek_menghasilkan_kosong_bukan_error():
    df = _df_dari_titik([100.0, 120.0], bar_per_kaki=5)
    assert detect_harmonic(df) == []
    assert detect_harmonic(None) == []


def test_ringkasan_menyebut_pola_arah_dan_area_pembalikan():
    df = _df_dari_titik(_gartley_bullish())
    teks = ringkas_harmonic(detect_harmonic(df))
    assert "Gartley" in teks and "bullish" in teks
    assert "area pembalikan" in teks
    assert ringkas_harmonic([]) == "Tidak ada pola harmonic yang terdeteksi."


def test_cypher_bullish_dikenali_dengan_jangkar_rasionya_sendiri():
    """Cypher memakai jangkar BERBEDA: BC diukur ke XA (bukan AB) dan CD
    diukur ke XC (bukan BC). Pola dibangun dari rasio itu, lalu harus
    dikenali sebagai Cypher -- bukan tersasar jadi pola lain."""
    X, A = 100.0, 200.0
    xa = A - X
    B = A - 0.50 * xa            # AB = 0.50 XA (dalam 0.382-0.618)
    C = B + 1.34 * xa            # BC = 1.34 XA -> C melewati A
    D = C - 0.786 * (C - X)      # CD = 0.786 XC
    hasil = detect_harmonic(_df_dari_titik([X, A, B, C, D]))
    assert hasil, "Cypher yang dibangun dari rasionya sendiri harus terdeteksi"
    p = hasil[0]
    assert p["pola"] == "Cypher"
    assert p["arah"] == "bullish"
    assert p["titik_akhir"] == "D"
    assert p["prz"] == pytest.approx(D, abs=4)


def test_shark_dikenali_dan_titiknya_dilabeli_0_X_A_B_C():
    """Shark memakai penamaan 0-X-A-B-C (titik akhirnya C, bukan D) dan
    rasio 88,6% terhadap leg 0X. Labelnya wajib ikut berbeda -- kalau ditulis
    X-A-B-C-D, pembaca yang mengecek ke sumber aslinya akan tersesat."""
    O, X = 100.0, 160.0
    ox = X - O
    A = X - 0.45 * ox            # turun sebagian
    xa = X - A
    B = A + 1.35 * xa            # AB = 1.35 XA -> B melewati X
    ab = B - A
    C = B - 1.9 * ab             # BC = 1.9 AB -> C jatuh ke area 0
    hasil = detect_harmonic(_df_dari_titik([O, X, A, B, C]))
    assert hasil, "Shark yang dibangun dari rasionya sendiri harus terdeteksi"
    p = hasil[0]
    assert p["pola"] == "Shark"
    assert p["titik_akhir"] == "C"
    assert [t["label"] for t in p["titik"]] == ["0", "X", "A", "B", "C"]


def test_potensi_naik_diukur_ke_puncak_pola_bukan_angka_karangan():
    df = _df_dari_titik(_gartley_bullish())
    p = detect_harmonic(df)[0]
    # Gartley bullish: puncak pola = titik A (200), penyelesaian D ~121.
    naik_seharusnya = (200.0 / p["prz"] - 1) * 100
    assert p["potensi_pct"] == pytest.approx(naik_seharusnya, abs=3)
    assert p["potensi_pct"] > 50


# =========================
# RENCANA ENTRY DARI GEOMETRI POLA
# =========================

def _pola_bullish(titik, prz, arah="bullish", pola="Gartley"):
    """Pola tiruan berbentuk keluaran detect_harmonic(), seperlunya saja."""
    label = ("X", "A", "B", "C", "D")
    return {"pola": pola, "arah": arah, "prz": prz,
            "titik": [{"label": l, "harga": h, "tanggal": "2026-01-01"}
                      for l, h in zip(label, titik)]}


def test_sl_gartley_diletakkan_di_luar_titik_x_bukan_di_titik_d():
    """Pada Gartley/Bat, D berhenti di ATAS X -- jadi yang membatalkan pola
    adalah tembusnya X, bukan tersenggolnya D. SL di titik D akan tersapu
    justru pada pola yang masih sah."""
    from core.harmonic import rencana_harmonic

    # X=100 (terendah), A=200, B=140, C=180, D=121 (0,786 XA, di atas X).
    r = rencana_harmonic(_pola_bullish([100, 200, 140, 180, 121], prz=121))
    assert r["sl"] < 100, f"SL {r['sl']} tidak berada di luar titik X"
    assert "X" in r["dasar_sl"]


def test_sl_crab_memakai_titik_d_karena_d_justru_titik_terendahnya():
    """Butterfly/Crab memanjang MELEWATI X, jadi titik terendah pola adalah
    D sendiri. Aturan "SL di bawah X" yang dihafal dari Gartley akan
    menaruh stop di ATAS harga entry di sini -- terbalik total."""
    from core.harmonic import rencana_harmonic

    # D=45 berada DI BAWAH X=100.
    r = rencana_harmonic(_pola_bullish([100, 200, 140, 180, 45], prz=45, pola="Crab"))
    assert r["sl"] < 45, "SL berada di atas D -- aturan Gartley dipakai di pola yang salah"
    assert r["sl"] > 40, "SL tidak boleh terlempar jauh ke titik X"

    # Konsekuensi yang perlu diketahui: pada Crab/Butterfly entry-nya PERSIS
    # di titik terendah pola, jadi stop strukturalnya selalu rapat dan
    # lantai SL-lah yang menentukan. Bukan cacat -- justru itu gunanya
    # lantai. Yang salah adalah menyebutnya "stop struktural" seolah-olah
    # jarak itu datang dari polanya.
    assert "lantai" in r["dasar_sl"]


def test_lantai_sl_tetap_berlaku_walau_struktur_polanya_rapat():
    """Perbaikan "SL jangan kedeketan" ada di core/trading_plan.py. Jalur
    harmonic tidak boleh jadi pintu belakang yang melewatinya: pola dengan
    D pas di titik terendah menghasilkan SL cuma 1,5% -- persis jarak yang
    dulu bikin banyak posisi kena SL lalu harganya terbang."""
    from core.harmonic import rencana_harmonic
    from core.trading_plan import MIN_SL_PCT

    r = rencana_harmonic(_pola_bullish([100, 200, 140, 180, 45], prz=45))
    assert r["sl_pct"] >= MIN_SL_PCT

    # Saham bergejolak dapat ruang lebih lebar, bukan 3% yang sama.
    bergejolak = rencana_harmonic(_pola_bullish([100, 200, 140, 180, 45], prz=45), atr_pct=6.0)
    assert bergejolak["sl_pct"] > r["sl_pct"]


def test_target_diukur_dari_leg_terakhir_dan_urut_naik():
    from core.harmonic import rencana_harmonic

    # Leg terakhir C->D = 180 -> 121, panjangnya 59.
    r = rencana_harmonic(_pola_bullish([100, 200, 140, 180, 121], prz=121))
    assert r["tp"] == sorted(r["tp"]), "target tidak urut naik"
    assert r["tp"][2] == 180.0, "TP3 semestinya menutup penuh leg terakhir"
    assert r["leg_target"] == "C→D"


def test_pola_yang_invalidasinya_sudah_ditembus_ditandai_batal():
    """Ini yang paling penting dijaga: pola mati TIDAK BOLEH tampil sebagai
    kandidat beli. Menampilkannya adalah cara tercepat mengajak orang masuk
    ke pola yang sudah gagal."""
    from core.harmonic import rencana_harmonic

    p = _pola_bullish([100, 200, 140, 180, 121], prz=121)
    assert rencana_harmonic(p, harga_kini=90)["status"] == "batal"
    assert rencana_harmonic(p, harga_kini=122)["status"] == "di area"
    assert rencana_harmonic(p, harga_kini=170)["status"] == "sudah lewat"


def test_pola_bearish_membalik_arah_sl_dan_target():
    from core.harmonic import rencana_harmonic

    p = _pola_bullish([200, 100, 160, 120, 179], prz=179, arah="bearish")
    r = rencana_harmonic(p)
    assert r["sl"] > 200, "SL bearish harus di ATAS titik tertinggi pola"
    assert all(t < 179 for t in r["tp"]), "target bearish harus di bawah entry"


def test_risk_reward_dilaporkan_ke_target_pertama_dan_terakhir():
    """TP1 adalah retracement 0,382 -- target yang sengaja dekat, sehingga R/R
    terhadapnya hampir selalu terlihat buruk. Melaporkan angka itu SENDIRIAN
    membuat pola yang sebenarnya sepadan terbaca seperti pola jelek."""
    from core.harmonic import rencana_harmonic

    r = rencana_harmonic(_pola_bullish([100, 200, 140, 180, 121], prz=121))
    assert r["rr"] is not None and r["rr_akhir"] is not None
    assert r["rr_akhir"] > r["rr"], "R/R ke target terakhir harus lebih besar"


def test_pola_dengan_ruang_lebih_kecil_dari_risikonya_ditandai_tidak_sepadan():
    """Menahan diri itu bagian dari saran. Saringan yang cuma sanggup bilang
    "ada peluang" akan selalu terdengar meyakinkan, dan justru karena itu
    tidak bisa dipercaya."""
    from core.harmonic import rencana_harmonic

    # Leg terakhir sangat pendek (C=124 -> D=121) sementara invalidasi jauh
    # di titik X=100: ruangnya kecil, risikonya besar.
    r = rencana_harmonic(_pola_bullish([100, 200, 140, 124, 121], prz=121))
    assert r["rr_akhir"] < 1.5
    assert r["sepadan"] is False
