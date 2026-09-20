"""Putar ulang sinyal yang SUDAH tercatat dengan TP/SL pilihanmu.

KENAPA ADA. Pertanyaan "sebaiknya TP di berapa" selalu dijawab dengan
perasaan, padahal aplikasi ini memegang bahan untuk menjawabnya dengan
angka: 587 sinyal beraudit, masing-masing dengan harga masuk, tanggal, dan
riwayat bar harian sesudahnya.

Jadi yang dikerjakan di sini bukan backtest strategi baru, melainkan
pertanyaan yang jauh lebih menarik dan jauh lebih jujur:

  "Kalau SEMUA sinyal yang aplikasi ini pernah berikan dijual di +8% atau
   dipotong di -3%, hasilnya akan seperti apa?"

Bedanya penting. Backtest strategi bisa dibuat indah dengan memilih periode
dan aturan yang kebetulan cocok. Ini memakai sinyal yang BENAR-BENAR pernah
dikeluarkan, termasuk yang buruk -- tidak ada yang bisa dipilih belakangan.

DUA KEPUTUSAN YANG MENENTUKAN KEJUJURANNYA
==========================================
1. Kalau TP dan SL sama-sama tersentuh DI HARI YANG SAMA, yang dihitung
   SL. Dari bar harian tidak mungkin tahu mana yang lebih dulu, dan
   menganggap TP duluan membuat seluruh angkanya berbohong ke arah yang
   menyenangkan. Asumsi yang merugikan diri sendiri adalah satu-satunya
   asumsi yang aman di sini.
2. Sinyal yang belum menyentuh keduanya sampai bar terakhir dihitung
   sebagai "belum selesai" dengan hasil apa adanya pada bar terakhir --
   bukan dibuang. Membuangnya akan menghapus justru yang bergerak lambat,
   dan itu memiringkan hasilnya.
"""


def putar_ulang(entry: float, bars: list, tp_pct: float, sl_pct: float,
                maks_hari: int | None = None) -> dict | None:
    """Satu sinyal, satu aturan. Return hasilnya, atau None kalau tak layak.

    `bars` = [(tanggal, high, close, low), ...] SESUDAH tanggal masuk,
    urut dari yang paling awal.
    """
    if not entry or entry <= 0 or not bars:
        return None
    if tp_pct <= 0 or sl_pct <= 0:
        return None
    harga_tp = entry * (1 + tp_pct / 100)
    harga_sl = entry * (1 - sl_pct / 100)

    for i, b in enumerate(bars):
        if maks_hari is not None and i >= maks_hari:
            break
        try:
            tinggi, tutup, rendah = float(b[1]), float(b[2]), float(b[3])
        except (TypeError, ValueError, IndexError):
            continue
        kena_sl = rendah <= harga_sl
        kena_tp = tinggi >= harga_tp
        # SL DULU kalau dua-duanya kena di hari yang sama -- lihat catatan
        # di atas. Ini yang membedakan angka yang bisa dipercaya dari angka
        # yang enak dibaca.
        if kena_sl:
            return {"status": "SL", "hasil_pct": -sl_pct, "hari": i + 1}
        if kena_tp:
            return {"status": "TP", "hasil_pct": tp_pct, "hari": i + 1}
    b = bars[min(len(bars), maks_hari) - 1] if maks_hari else bars[-1]
    try:
        tutup = float(b[2])
    except (TypeError, ValueError, IndexError):
        return None
    return {"status": "BELUM", "hasil_pct": (tutup / entry - 1) * 100,
            "hari": min(len(bars), maks_hari) if maks_hari else len(bars)}


def uji(sinyal: list[dict], bar_per_kode: dict, tp_pct: float, sl_pct: float,
        maks_hari: int | None = None, sumber: str | None = None) -> dict:
    """Putar ulang SEMUA sinyal dengan satu aturan.

    `sinyal` = baris dari signal_history (butuh kode, entry_price,
    recorded_at/entry_filled_at, source).
    """
    hasil = []
    dilewati = 0
    for s in sinyal or []:
        if sumber and (s.get("source") or "") != sumber:
            continue
        kode = (s.get("kode") or "").upper()
        entry = s.get("entry_price")
        mulai = str(s.get("entry_filled_at") or s.get("recorded_at") or "")[:10]
        bars = bar_per_kode.get(kode) or []
        # HANYA bar SESUDAH tanggal masuk. Memakai bar hari masuk itu sendiri
        # berarti memakai pergerakan yang sebagian sudah terjadi sebelum
        # sinyalnya lahir -- bias ke depan yang membuat hasilnya terlalu
        # bagus tanpa ketahuan.
        sesudah = [b for b in bars if str(b[0])[:10] > mulai]
        r = putar_ulang(entry, sesudah, tp_pct, sl_pct, maks_hari)
        if not r:
            dilewati += 1
            continue
        r["kode"] = kode
        r["source"] = s.get("source")
        hasil.append(r)

    if not hasil:
        return {"n": 0, "dilewati": dilewati, "tp_pct": tp_pct, "sl_pct": sl_pct}

    tp = [r for r in hasil if r["status"] == "TP"]
    sl = [r for r in hasil if r["status"] == "SL"]
    belum = [r for r in hasil if r["status"] == "BELUM"]
    dinilai = len(tp) + len(sl)
    return {
        "n": len(hasil), "dilewati": dilewati,
        "tp_pct": tp_pct, "sl_pct": sl_pct, "maks_hari": maks_hari,
        "n_tp": len(tp), "n_sl": len(sl), "n_belum": len(belum),
        "menang_pct": round(len(tp) / dinilai * 100, 1) if dinilai else None,
        "hasil_rata_pct": round(sum(r["hasil_pct"] for r in hasil) / len(hasil), 2),
        "hari_rata": round(sum(r["hari"] for r in hasil) / len(hasil), 1),
        "rrr": round(tp_pct / sl_pct, 2),
    }


def bandingkan(sinyal: list[dict], bar_per_kode: dict, pilihan: list[tuple],
               maks_hari: int | None = None, sumber: str | None = None) -> list[dict]:
    """Beberapa aturan sekaligus, supaya bisa dilihat mana yang lebih baik.

    Satu angka sendirian tidak memberi tahu apa pun -- "menang 58%" baru
    berarti kalau ada pembandingnya.
    """
    keluar = []
    for tp, sl in pilihan:
        r = uji(sinyal, bar_per_kode, tp, sl, maks_hari, sumber)
        if r.get("n"):
            keluar.append(r)
    return keluar
