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

        cocok = _cocokkan(ab / xa, bc / ab, cd / bc, ad / xa, toleransi)
        nama, skor = cocok if cocok else (None, 0.0)
        if nama is None:
            # ABCD: tanpa titik X, jadi diuji pakai A-B-C-D saja.
            if _dalam(bc / ab, ABCD_BC, toleransi) and _dalam(cd / ab, ABCD_CD, toleransi):
                nama, skor = "ABCD", 60.0
            else:
                continue

        hasil.append({
            "pola": nama,
            "arah": arah,
            "skor": skor,
            "prz": round(D["harga"], 2),          # titik D = area pembalikan yang diduga
            "tanggal_d": tanggal[D["i"]],
            "bar_sejak_d": len(df) - 1 - D["i"],  # 0 = D baru saja terbentuk
            "titik": [
                {"label": nama_titik, "tanggal": tanggal[p["i"]], "harga": round(p["harga"], 2)}
                for nama_titik, p in (("X", X), ("A", A), ("B", B), ("C", C), ("D", D))
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
