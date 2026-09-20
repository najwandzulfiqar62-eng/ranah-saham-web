"""Rapor kebiasaan: menilai CARAMU, bukan sahamnya.

KENAPA ADA. Aplikasi sekuritas punya semua data ini -- kapan kamu beli,
kapan kamu jual, untung atau rugi -- dan tidak satu pun memberitahumu apa
POLANYA. Mereka menunjukkan hasil per transaksi, bukan kebiasaan yang
menghasilkannya.

Padahal yang paling menentukan hasil jangka panjang bukan saham yang
dipilih, melainkan pola yang berulang tanpa disadari. Yang paling terkenal:

  EFEK DISPOSISI -- memotong yang untung cepat-cepat, memeluk yang rugi
  lama-lama. Shefrin & Statman (1985), lalu Odean (1998) atas 10.000 akun
  ritel: saham yang untung dijual 1,7 kali lebih sering daripada yang rugi,
  dan justru yang ditahan itu yang berkinerja lebih buruk sesudahnya.

Pola seperti itu TIDAK TERASA dari dalam. Ia cuma kelihatan kalau dihitung.

YANG DIJAGA DI SINI
===================
1. Cuma menyebut pola yang BISA DIHITUNG dari catatannya sendiri. Tidak ada
   tafsiran psikologis, tidak ada tebakan soal perasaan.
2. Diam kalau sampelnya terlalu sedikit. "Kamu selalu rugi kalau beli hari
   Senin" dari tiga transaksi itu mengarang, dan mengarang di sini lebih
   berbahaya daripada tidak berkata apa-apa -- orang akan mengubah caranya
   berdasarkan pola yang tidak ada.
3. Menyebut yang BAIK juga. Rapor yang hanya berisi kesalahan berhenti
   dibaca, dan yang berhenti dibaca tidak mengubah apa pun.
"""
from datetime import datetime

# Di bawah ini, sebuah pola tidak disebut sama sekali. Angkanya kecil, tapi
# bukan sembarang kecil: dengan kurang dari ini, satu transaksi saja sudah
# menggeser kesimpulannya -- dan kesimpulan yang bisa digeser satu kejadian
# bukan pola.
MIN_SAMPEL = 5
MIN_PER_KELOMPOK = 3


def _tanggal(teks):
    if not teks:
        return None
    try:
        return datetime.fromisoformat(str(teks).replace("Z", "").split(".")[0])
    except ValueError:
        return None


def pasangkan_transaksi(transaksi: list[dict]) -> list[dict]:
    """Rangkai BELI dan JUAL jadi perdagangan yang SELESAI, per emiten.

    Metode FIFO: penjualan menutup pembelian terlama lebih dulu. Itu cara
    yang paling mudah dijelaskan kalau suatu saat ada yang bertanya "kok
    angkanya segitu", dan bisa dijelaskan itu lebih penting daripada
    optimal secara pajak.

    Yang dikembalikan hanya perdagangan yang sudah DITUTUP -- posisi
    berjalan tidak punya hasil, dan menganggapnya untung/rugi sekarang
    membuat rapornya berubah tiap hari tanpa ada yang terjadi.
    """
    antrean: dict = {}
    selesai = []
    for t in sorted(transaksi or [], key=lambda x: (x.get("kode") or "",
                                                    x.get("id") or 0)):
        kode = (t.get("kode") or "").upper()
        lot, harga = float(t.get("lot") or 0), float(t.get("harga") or 0)
        waktu = _tanggal(t.get("dicatat_at"))
        if not (kode and lot > 0 and harga > 0):
            continue
        if (t.get("arah") or "").upper() == "BELI":
            antrean.setdefault(kode, []).append({"lot": lot, "harga": harga,
                                                 "waktu": waktu})
            continue
        sisa = lot
        while sisa > 1e-9 and antrean.get(kode):
            beli = antrean[kode][0]
            pakai = min(sisa, beli["lot"])
            hari = None
            if beli["waktu"] and waktu:
                hari = max(0, (waktu - beli["waktu"]).days)
            selesai.append({
                "kode": kode, "lot": pakai,
                "harga_beli": beli["harga"], "harga_jual": harga,
                "hasil_pct": (harga / beli["harga"] - 1) * 100,
                "hasil_rp": (harga - beli["harga"]) * pakai * 100,
                "hari": hari,
                "beli_at": beli["waktu"], "jual_at": waktu,
            })
            beli["lot"] -= pakai
            sisa -= pakai
            if beli["lot"] <= 1e-9:
                antrean[kode].pop(0)
    return selesai


def efek_disposisi(selesai: list[dict]) -> dict | None:
    """Berapa lama yang UNTUNG ditahan, dibanding yang RUGI.

    Pola paling mahal di trading ritel, dan yang paling tidak terasa dari
    dalam: yang rugi terasa "belum selesai" sehingga ditunggu, yang untung
    terasa "sudah cukup" sehingga dilepas. Hasilnya untung kecil yang sering
    dan rugi besar yang jarang -- persis kebalikan dari yang dibutuhkan.
    """
    untung = [t for t in selesai if t["hasil_pct"] > 0 and t["hari"] is not None]
    rugi = [t for t in selesai if t["hasil_pct"] <= 0 and t["hari"] is not None]
    if len(untung) < MIN_PER_KELOMPOK or len(rugi) < MIN_PER_KELOMPOK:
        return None
    hu = sum(t["hari"] for t in untung) / len(untung)
    hr = sum(t["hari"] for t in rugi) / len(rugi)
    return {"hari_untung": round(hu, 1), "hari_rugi": round(hr, 1),
            "n_untung": len(untung), "n_rugi": len(rugi),
            "rasio": round(hr / hu, 1) if hu > 0 else None}


def per_kelompok(selesai: list[dict], kunci, nama_kelompok=None) -> list[dict]:
    """Bagi perdagangan menurut sebuah ciri, lalu hitung hasilnya.

    `kunci` mengembalikan nama kelompok untuk satu perdagangan, atau None
    kalau perdagangan itu tidak masuk kelompok mana pun.
    """
    kel: dict = {}
    for t in selesai:
        k = kunci(t)
        if k is None:
            continue
        kel.setdefault(k, []).append(t)
    keluar = []
    for k, isi in kel.items():
        if len(isi) < MIN_PER_KELOMPOK:
            continue
        menang = sum(1 for t in isi if t["hasil_pct"] > 0)
        keluar.append({
            "nama": (nama_kelompok or str)(k),
            "n": len(isi), "menang": menang,
            "menang_pct": round(menang / len(isi) * 100, 1),
            "hasil_pct": round(sum(t["hasil_pct"] for t in isi) / len(isi), 2),
            "hasil_rp": round(sum(t["hasil_rp"] for t in isi), 0),
        })
    return sorted(keluar, key=lambda x: -x["n"])


def ringkas(selesai: list[dict]) -> dict | None:
    """Angka pokok: berapa perdagangan selesai, menang berapa, hasil berapa."""
    if len(selesai) < MIN_SAMPEL:
        return None
    menang = [t for t in selesai if t["hasil_pct"] > 0]
    kalah = [t for t in selesai if t["hasil_pct"] <= 0]
    return {
        "n": len(selesai),
        "menang": len(menang), "kalah": len(kalah),
        "menang_pct": round(len(menang) / len(selesai) * 100, 1),
        "hasil_rp": round(sum(t["hasil_rp"] for t in selesai), 0),
        "rata_menang_pct": round(sum(t["hasil_pct"] for t in menang) / len(menang), 2)
        if menang else None,
        "rata_kalah_pct": round(sum(t["hasil_pct"] for t in kalah) / len(kalah), 2)
        if kalah else None,
        "terbaik": max(selesai, key=lambda t: t["hasil_pct"]),
        "terburuk": min(selesai, key=lambda t: t["hasil_pct"]),
    }
