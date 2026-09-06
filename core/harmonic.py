# =========================
# POLA HARMONIC (Gartley, Bat, Butterfly, Crab, ABCD)
# =========================
# Pola harmonic adalah formasi 5 titik (X-A-B-C-D) yang tiap kakinya harus
# memenuhi rasio Fibonacci tertentu. Titik D adalah "Potential Reversal Zone"
# (PRZ) -- area tempat harga DIDUGA berbalik arah.
#
# BATAS YANG SENGAJA DIPASANG (dan alasannya):
#
# 1. Hanya 4 pola klasik + ABCD yang dideteksi: Gartley, Bat, Butterfly, Crab.
#    Shark & Cypher SENGAJA TIDAK diikutkan -- keduanya memakai titik jangkar
#    yang BERBEDA (Cypher mengukur D dari retracement XC, bukan XA; Shark
#    memakai skema O-X-A-B-C). Memaksakannya ke rumus yang sama akan
#    menghasilkan pola yang terlihat valid padahal rasionya salah, dan itu
#    lebih berbahaya daripada tidak mendeteksinya sama sekali.
#
# 2. Pivot memakai detect_swing_points() milik core/smc.py -- detektor yang
#    SUDAH dipakai fitur SMC. Kalau definisi swing berubah, SMC dan harmonic
#    ikut berubah bersama, tidak saling bertentangan.
#
# 3. Pola harmonic itu DESKRIPTIF, bukan ramalan. Sama seperti catatan yang
#    sudah dipakai bagian SMC di aplikasi ini: yang dilaporkan adalah "ada
#    formasi dengan rasio sekian", BUKAN "harga akan berbalik". Deteksi pola
#    di data historis selalu terlihat meyakinkan; yang menentukan tetap apa
#    yang terjadi SESUDAH titik D terbentuk.

from __future__ import annotations

import pandas as pd

from core.smc import detect_swing_points

# Rentang rasio tiap pola. Angkanya rentang, bukan titik tunggal: harga nyata
# nyaris tidak pernah kena persis 0,618 -- menuntut kecocokan persis berarti
# tidak ada pola yang pernah terdeteksi.
#
# ab = AB/XA, bc = BC/AB, cd = CD/BC, ad = AD/XA (semuanya nilai mutlak).
POLA = {
    "Gartley": {"ab": (0.55, 0.68), "bc": (0.38, 0.89), "cd": (1.13, 1.68), "ad": (0.74, 0.83)},
    "Bat": {"ab": (0.36, 0.52), "bc": (0.38, 0.89), "cd": (1.60, 2.65), "ad": (0.84, 0.93)},
    "Butterfly": {"ab": (0.74, 0.83), "bc": (0.38, 0.89), "cd": (1.60, 2.30), "ad": (1.20, 1.65)},
    "Crab": {"ab": (0.36, 0.65), "bc": (0.38, 0.89), "cd": (2.55, 3.70), "ad": (1.55, 1.70)},
}

# ABCD tidak punya titik X. Diperiksa terpisah: CD kira-kira sepanjang AB, dan
# BC retracement wajar dari AB.
ABCD_BC = (0.38, 0.89)
ABCD_CD = (0.80, 1.30)

# CYPHER -- titik jangkarnya BEDA, karena itu tidak bisa ikut tabel POLA di
# atas. Aturannya (diverifikasi dari sumber publik, lihat catatan modul):
#   AB = 0,382-0,618 dari XA
#   BC = 1,272-1,414 dari XA   <-- diukur ke XA, BUKAN ke AB; C melewati A
#   CD = 0,786 dari XC          <-- diukur ke XC, BUKAN ke BC
CYPHER_AB = (0.382, 0.618)
CYPHER_BC_XA = (1.272, 1.414)
CYPHER_CD_XC = (0.75, 0.82)

# SHARK -- memakai penamaan 0-X-A-B-C (bukan X-A-B-C-D), jadi titik
# penyelesaiannya adalah C. Aturannya:
#   AB = 1,13-1,618 dari XA     (B melewati X)
#   BC = 1,618-2,24 dari AB
#   C  = 0,886-1,13 dari leg 0X <-- inilah rasio 88,6%/113% yang jadi ciri
#                                    khasnya; diukur ke 0X, bukan ke 0B
SHARK_AB_XA = (1.13, 1.618)
SHARK_BC_AB = (1.618, 2.24)
SHARK_C_OX = (0.886, 1.13)


def _pivot_bergantian(df: pd.DataFrame, left: int, right: int) -> list[dict]:
    """Daftar pivot yang SELALU bergantian high-low-high-low.

    Dua swing sejenis berturut-turut (mis. dua high tanpa low di antaranya)
    tidak bisa jadi kaki pola, jadi yang dipertahankan cuma yang paling
    ekstrem -- high tertinggi atau low terendah.
    """
    ditandai = detect_swing_points(df, left, right)
    mentah = []
    for i in range(len(ditandai)):
        if ditandai["swing_high"].iloc[i]:
            mentah.append({"i": i, "harga": float(ditandai["High"].iloc[i]), "jenis": "high"})
        elif ditandai["swing_low"].iloc[i]:
            mentah.append({"i": i, "harga": float(ditandai["Low"].iloc[i]), "jenis": "low"})

    bersih: list[dict] = []
    for p in mentah:
        if not bersih or bersih[-1]["jenis"] != p["jenis"]:
            bersih.append(p)
            continue
        akhir = bersih[-1]
        lebih_ekstrem = (p["harga"] > akhir["harga"]) if p["jenis"] == "high" else (p["harga"] < akhir["harga"])
        if lebih_ekstrem:
            bersih[-1] = p
    return bersih


def _dalam(nilai: float, rentang: tuple[float, float], toleransi: float) -> bool:
    lo, hi = rentang
    return lo * (1 - toleransi) <= nilai <= hi * (1 + toleransi)


def _cocokkan(ab: float, bc: float, cd: float, ad: float, toleransi: float) -> tuple[str, float] | None:
    """Nama pola + seberapa pas rasionya (0-100). None kalau tidak ada yang cocok."""
    terbaik = None
    for nama, r in POLA.items():
        if not (_dalam(ab, r["ab"], toleransi) and _dalam(bc, r["bc"], toleransi)
                and _dalam(cd, r["cd"], toleransi) and _dalam(ad, r["ad"], toleransi)):
            continue
        # Skor = seberapa dekat ke TENGAH tiap rentang. Pola yang rasionya
        # pas di tengah lebih meyakinkan daripada yang mepet batas toleransi.
        meleset = 0.0
        for kunci, nilai in (("ab", ab), ("bc", bc), ("cd", cd), ("ad", ad)):
            lo, hi = r[kunci]
            tengah = (lo + hi) / 2
            lebar = max((hi - lo) / 2, 1e-9)
            meleset += min(abs(nilai - tengah) / lebar, 2.0)
        skor = max(0.0, 100.0 - (meleset / 4) * 40)
        if terbaik is None or skor > terbaik[1]:
            terbaik = (nama, round(skor, 1))
    return terbaik


def _cocokkan_cypher(p: list[dict], arah: str, toleransi: float) -> tuple[str, float] | None:
    """Cypher: X-A-B-C-D, tapi BC diukur ke XA dan CD diukur ke XC.

    Bentuknya berbeda dari pola klasik: C harus MELEWATI A (bukan retracement
    di bawahnya), lalu D turun 78,6% dari leg X-C.
    """
    X, A, B, C, D = p
    xa = abs(A["harga"] - X["harga"])
    ab = abs(B["harga"] - A["harga"])
    bc = abs(C["harga"] - B["harga"])
    xc = abs(C["harga"] - X["harga"])
    cd = abs(D["harga"] - C["harga"])
    if min(xa, ab, bc, xc) <= 0:
        return None
    # C wajib melewati A -- ciri utama Cypher.
    if arah == "bullish" and not C["harga"] > A["harga"]:
        return None
    if arah == "bearish" and not C["harga"] < A["harga"]:
        return None
    if not (_dalam(ab / xa, CYPHER_AB, toleransi)
            and _dalam(bc / xa, CYPHER_BC_XA, toleransi)
            and _dalam(cd / xc, CYPHER_CD_XC, toleransi)):
        return None
    meleset = abs(cd / xc - 0.786) / 0.786
    return "Cypher", round(max(0.0, 100.0 - meleset * 300), 1)


def _cocokkan_shark(p: list[dict], arah: str, toleransi: float) -> tuple[str, float] | None:
    """Shark: penamaan 0-X-A-B-C, titik penyelesaiannya C (bukan D).

    Ciri khasnya rasio 88,6%/113% terhadap leg 0-X. Untuk versi bullish:
    0(low) -> X(high) -> A(low) -> B(high, melewati X) -> C(low, dekat/di
    bawah 0). Titik belinya C.
    """
    O, X, A, B, C = p
    ox = abs(X["harga"] - O["harga"])
    xa = abs(A["harga"] - X["harga"])
    ab = abs(B["harga"] - A["harga"])
    bc = abs(C["harga"] - B["harga"])
    # 88,6%-113% itu RETRACEMENT leg 0X yang diukur DARI X, bukan jarak C ke
    # titik 0. Salah menaruhnya membuat pola yang benar tidak pernah cocok:
    # pada Shark yang sah C berhenti dekat 0, sehingga |C-0| justru ~0.
    c_ox = abs(C["harga"] - X["harga"])
    if min(ox, xa, ab, bc) <= 0:
        return None
    # B wajib melewati X (impuls), C wajib kembali ke area 0.
    if arah == "bullish" and not B["harga"] > X["harga"]:
        return None
    if arah == "bearish" and not B["harga"] < X["harga"]:
        return None
    if not (_dalam(ab / xa, SHARK_AB_XA, toleransi)
            and _dalam(bc / ab, SHARK_BC_AB, toleransi)
            and _dalam(c_ox / ox, SHARK_C_OX, toleransi)):
        return None
    meleset = abs(c_ox / ox - 0.886) / 0.886
    return "Shark", round(max(0.0, 100.0 - meleset * 200), 1)


def detect_harmonic(df: pd.DataFrame, left_bars: int = 5, right_bars: int = 5,
                    toleransi: float = 0.06, maks: int = 3) -> list[dict]:
    """Pola harmonic terbaru pada df OHLC. Terbaru lebih dulu.

    toleransi: kelonggaran rasio (0.06 = 6%). Makin longgar makin banyak pola
    terdeteksi, tapi makin sering yang terdeteksi bukan pola sungguhan.
    """
    if df is None or len(df) < 40:
        return []
    try:
        pivot = _pivot_bergantian(df, left_bars, right_bars)
    except Exception:
        return []
    if len(pivot) < 5:
        return []

    tanggal = [str(x)[:10] for x in df.index]
    hasil: list[dict] = []

    # Ditelusuri dari yang PALING BARU supaya pola terkini muncul lebih dulu.
    for akhir in range(len(pivot) - 1, 3, -1):
        X, A, B, C, D = pivot[akhir - 4:akhir + 1]
        xa = abs(A["harga"] - X["harga"])
        ab = abs(B["harga"] - A["harga"])
        bc = abs(C["harga"] - B["harga"])
        cd = abs(D["harga"] - C["harga"])
        ad = abs(D["harga"] - A["harga"])
        if min(xa, ab, bc, cd) <= 0:
            continue

        arah = "bullish" if X["jenis"] == "low" else "bearish"
        # Bentuk zig-zag wajib benar: pada pola bullish, D harus di BAWAH C
        # dan B di bawah A. Tanpa cek ini, rasio bisa saja cocok pada bentuk
        # yang sama sekali bukan pola harmonic.
        if arah == "bullish":
            bentuk_benar = (A["harga"] > X["harga"] and B["harga"] < A["harga"]
                            and C["harga"] > B["harga"] and D["harga"] < C["harga"])
        else:
            bentuk_benar = (A["harga"] < X["harga"] and B["harga"] > A["harga"]
                            and C["harga"] < B["harga"] and D["harga"] > C["harga"])
        if not bentuk_benar:
            continue

        jendela = [X, A, B, C, D]
        cocok = (_cocokkan(ab / xa, bc / ab, cd / bc, ad / xa, toleransi)
                 or _cocokkan_cypher(jendela, arah, toleransi)
                 or _cocokkan_shark(jendela, arah, toleransi))
        nama, skor = cocok if cocok else (None, 0.0)
        if nama is None:
            # ABCD: tanpa titik X, jadi diuji pakai A-B-C-D saja.
            if _dalam(bc / ab, ABCD_BC, toleransi) and _dalam(cd / ab, ABCD_CD, toleransi):
                nama, skor = "ABCD", 60.0
            else:
                continue
        # Shark memakai penamaan 0-X-A-B-C: titik penyelesaiannya tetap pivot
        # terakhir, tapi labelnya berbeda supaya tidak menyesatkan pembaca
        # yang mengecek ke sumber aslinya.
        label = ("0", "X", "A", "B", "C") if nama == "Shark" else ("X", "A", "B", "C", "D")

        # POTENSI NAIK dari titik penyelesaian ke puncak pola. Untuk pola
        # bullish inilah "kalau memantul dari titik terbawah, sejauh apa
        # ruangnya" -- diukur ke titik tertinggi pola, bukan target karangan.
        harga_titik = [t["harga"] for t in jendela]
        if arah == "bullish":
            potensi = (max(harga_titik) / D["harga"] - 1) * 100 if D["harga"] else 0.0
        else:
            potensi = (1 - min(harga_titik) / D["harga"]) * 100 if D["harga"] else 0.0

        hasil.append({
            "pola": nama,
            "arah": arah,
            "skor": skor,
            "prz": round(D["harga"], 2),          # titik penyelesaian = area pembalikan
            "titik_akhir": label[4],              # "D" pada umumnya, "C" untuk Shark
            "potensi_pct": round(potensi, 1),
            "tanggal_d": tanggal[D["i"]],
            "bar_sejak_d": len(df) - 1 - D["i"],  # 0 = baru saja terbentuk
            "titik": [
                {"label": nama_titik, "tanggal": tanggal[p["i"]], "harga": round(p["harga"], 2)}
                for nama_titik, p in zip(label, jendela)
            ],
            "rasio": {
                "AB/XA": round(ab / xa, 3), "BC/AB": round(bc / ab, 3),
                "CD/BC": round(cd / bc, 3), "AD/XA": round(ad / xa, 3),
            },
        })
        if len(hasil) >= maks:
            break
    return hasil


def ringkas_harmonic(pola: list[dict]) -> str:
    """Satu kalimat untuk ditempel ke laporan/bot."""
    if not pola:
        return "Tidak ada pola harmonic yang terdeteksi."
    p = pola[0]
    umur = ("baru terbentuk" if p["bar_sejak_d"] <= 2
            else f"terbentuk {p['bar_sejak_d']} bar lalu")
    return (f"Pola {p['pola']} {p['arah']} terdeteksi, titik D (area pembalikan) "
            f"di {p['prz']:.0f} — {umur}.")


# =========================
# RENCANA ENTRY DARI GEOMETRI POLA
# =========================
# Selama ini entry/SL/TP di aplikasi ini datang dari core/trading_plan.py --
# support/resistance + lantai ATR. Itu tetap jadi jalur utama. Yang di bawah
# ini alternatif KHUSUS saat polanya ada: harmonic sudah membawa titik
# invalidasinya sendiri, jadi SL-nya tidak perlu ditebak dari ATR. Kalau
# harga menembus titik terendah pola, yang batal bukan cuma posisinya --
# polanya sendiri yang batal. Itu alasan berhenti yang bisa dijelaskan.

# Target = retracement Fibonacci LEG TERAKHIR (C->D pada pola klasik, B->C
# pada Shark). Ini aturan target harmonic yang lazim dipakai; sengaja BUKAN
# diukur ke seluruh pola, karena pada Butterfly/Crab leg terakhirnya sangat
# panjang sehingga target "sampai titik A" jadi angka yang cuma enak dibaca.
HARMONIC_TP_FIB = (0.382, 0.618, 1.0)

# Jarak aman di luar titik invalidasi. Pola yang cuma tersenggol ekor candle
# belum tentu pola yang batal, dan SL yang ditaruh PERSIS di titik pola itu
# justru yang paling gampang disapu.
HARMONIC_SL_BUFFER = 0.015


def rencana_harmonic(pola: dict, harga_kini: float | None = None,
                     atr_pct: float | None = None) -> dict | None:
    """Entry/SL/TP yang diturunkan dari titik-titik polanya sendiri.

    pola: satu elemen keluaran detect_harmonic().
    harga_kini: untuk menilai apakah areanya masih bisa dipakai.
    atr_pct: ATR harian dalam persen -- dipakai menegakkan lantai SL yang
        SAMA dengan core/trading_plan.py, supaya "SL kependekan lalu kena
        noise harian" tidak masuk lewat pintu belakang.

    Return None kalau titik polanya tidak lengkap.
    """
    from core.trading_plan import MIN_SL_PCT, SL_ATR_MULT

    titik = pola.get("titik") or []
    if len(titik) < 2:
        return None
    harga_titik = [t["harga"] for t in titik]
    bullish = pola.get("arah") == "bullish"

    entry = float(pola["prz"])            # titik penyelesaian pola
    asal_leg = float(titik[-2]["harga"])  # pangkal leg terakhir
    if entry <= 0:
        return None

    # INVALIDASI = titik paling ekstrem pola. Pada Gartley/Bat/Cypher itu
    # titik X (D berhenti di ATAS X), pada Butterfly/Crab/ABCD justru titik
    # D sendiri (D memanjang MELEWATI X), pada Shark titik C atau 0. Dicari
    # dengan min/max supaya benar untuk semuanya tanpa daftar khusus per
    # pola -- daftar seperti itu pasti ketinggalan saat pola baru ditambah.
    invalidasi = min(harga_titik) if bullish else max(harga_titik)
    sl = (invalidasi * (1 - HARMONIC_SL_BUFFER) if bullish
          else invalidasi * (1 + HARMONIC_SL_BUFFER))

    # Lantai yang sama dengan rencana trading biasa. Pola dengan D pas di
    # titik terendahnya bisa menghasilkan SL cuma 1,5% di bawah entry --
    # persis keluhan "kena SL malah terbang" yang sudah pernah diperbaiki
    # di trading_plan.py. Tidak ada gunanya menutup lubang itu di satu
    # tempat lalu membiarkannya terbuka di tempat lain.
    lantai_pct = max(MIN_SL_PCT, SL_ATR_MULT * atr_pct if atr_pct else 0.0)
    risiko_pct = abs(entry - sl) / entry * 100
    if risiko_pct < lantai_pct:
        sl = entry * (1 - lantai_pct / 100) if bullish else entry * (1 + lantai_pct / 100)
        risiko_pct = lantai_pct
        dasar_sl = f"lantai {lantai_pct:.1f}%, struktur polanya terlalu rapat"
    else:
        # Sebut titik mana yang jadi dasarnya. Dicari lewat indeks nilainya,
        # bukan ditebak "pasti titik pertama atau terakhir" -- tebakan itu
        # kebetulan benar untuk pola yang ada sekarang dan akan diam-diam
        # salah begitu ada pola dengan tata letak titik yang berbeda.
        dasar_sl = f"di luar titik {titik[harga_titik.index(invalidasi)]['label']}"

    leg = abs(asal_leg - entry)
    arah_tp = 1 if bullish else -1
    tp = [round(entry + arah_tp * f * leg, 2) for f in HARMONIC_TP_FIB]

    risiko = abs(entry - sl)
    # DUA angka risk/reward, bukan satu. TP1 adalah retracement 0,382 -- target
    # yang sengaja dekat, sehingga R/R terhadapnya hampir selalu terlihat
    # buruk dan gampang disalahartikan sebagai "polanya jelek". Yang menjawab
    # "sepadan atau tidak" adalah R/R ke target terakhir.
    rr = round(abs(tp[0] - entry) / risiko, 2) if risiko > 0 else None
    rr_akhir = round(abs(tp[-1] - entry) / risiko, 2) if risiko > 0 else None

    hasil = {
        "entry": round(entry, 2),
        "sl": round(sl, 2),
        "sl_pct": round(risiko_pct, 2),
        "dasar_sl": dasar_sl,
        "tp": tp,
        "tp_pct": [round(abs(x / entry - 1) * 100, 2) for x in tp],
        "rr": rr,
        "rr_akhir": rr_akhir,
        # Menahan diri itu bagian dari saran. Pola yang sah pun tidak layak
        # diambil kalau ruang ke target terakhirnya lebih kecil dari risikonya.
        "sepadan": (rr_akhir is not None and rr_akhir >= 1.5),
        "leg_target": f"{titik[-2]['label']}→{titik[-1]['label']}",
    }

    if harga_kini is not None and harga_kini > 0:
        hasil["harga_kini"] = round(float(harga_kini), 2)
        hasil["jarak_ke_entry_pct"] = round((harga_kini / entry - 1) * 100, 2)
        # Pola yang titik invalidasinya SUDAH ditembus bukan peluang yang
        # "agak lewat" -- ia sudah batal. Menampilkannya sebagai kandidat
        # beli adalah cara tercepat mengajak orang masuk ke pola mati.
        if (bullish and harga_kini < sl) or (not bullish and harga_kini > sl):
            hasil["status"] = "batal"
        elif abs(harga_kini / entry - 1) <= 0.03:
            hasil["status"] = "di area"
        elif (bullish and harga_kini > entry) or (not bullish and harga_kini < entry):
            hasil["status"] = "sudah lewat"
        else:
            hasil["status"] = "belum sampai"
    return hasil
