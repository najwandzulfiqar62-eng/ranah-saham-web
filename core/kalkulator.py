"""Kalkulator yang menjawab pertanyaan yang benar-benar ditanyakan orang.

Tiga hal yang sering salah dihitung di kepala, dan salahnya selalu ke arah
yang sama -- terlalu optimis:

  PEMULIHAN. "Rugi 40%, nanti naik 40% juga balik modal." Tidak. Butuh
  naik 66,7%. Kesalahan ini membesar persis saat ia paling berbahaya:
  pada kerugian yang sudah dalam.

  RIGHTS ISSUE. Menebus terasa seperti "beli murah", padahal harga
  teoretisnya memang turun karena jumlah sahamnya bertambah. Yang menolak
  menebus bukan cuma tidak dapat diskon -- porsi kepemilikannya terdilusi.

  DIVIDEN. Yield dihitung dari harga hari ini, bukan dari harga belimu.
  Dua orang yang memegang saham yang sama bisa punya yield yang sangat
  berbeda, dan yang dipajang di mana-mana adalah yield pembeli hari ini.

Semuanya murni aritmetika -- tidak ada ramalan di sini, dan itu justru
gunanya: angkanya pasti benar.
"""


def pemulihan(rugi_pct: float) -> dict | None:
    """Berapa persen harus naik untuk balik modal dari rugi sekian persen.

    Rumusnya tidak simetris, dan itu inti soalnya:

        butuh = rugi / (100 - rugi) x 100

    Rugi 10% butuh naik 11,1%. Rugi 50% butuh naik 100%. Rugi 90% butuh
    naik 900%. Perbedaan antara "naik 40%" dan "naik 66,7%" terdengar
    kecil di kepala dan sangat besar di rekening.
    """
    try:
        r = abs(float(rugi_pct))
    except (TypeError, ValueError):
        return None
    if not (0 <= r < 100):
        # Rugi 100% berarti modalnya habis; tidak ada kenaikan berhingga
        # yang memulihkannya, dan membulatkannya jadi angka besar akan
        # menyiratkan ada jalan kembali.
        return None
    butuh = r / (100 - r) * 100 if r else 0.0
    return {"rugi_pct": round(r, 2), "butuh_naik_pct": round(butuh, 2),
            "pengali": round(100 / (100 - r), 3) if r else 1.0}


def harga_balik_modal(harga_beli: float, harga_kini: float) -> dict | None:
    """Versi rupiah dari pemulihan(), untuk posisi yang sedang dipegang."""
    try:
        beli, kini = float(harga_beli), float(harga_kini)
    except (TypeError, ValueError):
        return None
    if beli <= 0 or kini <= 0:
        return None
    rugi = (1 - kini / beli) * 100
    if rugi <= 0:
        return {"sudah_untung": True, "untung_pct": round(-rugi, 2),
                "harga_balik_modal": round(beli)}
    p = pemulihan(rugi)
    if p is None:
        return None
    return {"sudah_untung": False, **p, "harga_balik_modal": round(beli),
            "harga_kini": round(kini)}


def rights_issue(harga_pasar: float, harga_tebus: float,
                 rasio_lama: float, rasio_baru: float) -> dict | None:
    """Harga teoretis setelah HMETD, dan apa artinya kalau tidak menebus.

    rasio_lama : rasio_baru, mis. 2:1 berarti tiap 2 saham lama berhak
    menebus 1 saham baru.

        TERP = (lama x harga_pasar + baru x harga_tebus) / (lama + baru)

    TERP itu harga "wajar" sesudah penambahan saham. Penurunan dari harga
    pasar ke TERP BUKAN kerugian bagi yang menebus -- nilainya pindah ke
    saham barunya. Ia kerugian bagi yang TIDAK menebus, dan itu yang jarang
    dihitung orang.
    """
    try:
        hp, ht = float(harga_pasar), float(harga_tebus)
        lama, baru = float(rasio_lama), float(rasio_baru)
    except (TypeError, ValueError):
        return None
    if hp <= 0 or ht <= 0 or lama <= 0 or baru <= 0:
        return None

    terp = (lama * hp + baru * ht) / (lama + baru)
    # Nilai haknya sendiri: selisih TERP dengan tebusan, per saham baru.
    nilai_hak = max(0.0, terp - ht)
    # Dilusi bagi yang tidak menebus: porsinya turun dari 1/lama jadi
    # 1/(lama+baru) terhadap basis yang sama.
    dilusi = baru / (lama + baru) * 100
    return {
        "terp": round(terp, 2),
        "harga_pasar": round(hp, 2), "harga_tebus": round(ht, 2),
        "rasio": f"{lama:g}:{baru:g}",
        "turun_ke_terp_pct": round((terp / hp - 1) * 100, 2),
        "nilai_hak_per_saham_baru": round(nilai_hak, 2),
        "diskon_tebus_pct": round((ht / terp - 1) * 100, 2),
        "dilusi_jika_tidak_tebus_pct": round(dilusi, 2),
        # Modal tambahan per 1 lot (100 lembar) saham LAMA yang dipegang.
        "tebus_per_lot_lama": round(100 * baru / lama * ht),
    }


def dividen(harga: float, dividen_per_saham: float,
            lot: float | None = None,
            harga_beli: float | None = None) -> dict | None:
    """Yield dividen -- dan yield terhadap HARGA BELIMU, bukan harga hari ini.

    Yang dipajang di mana-mana adalah yield bagi pembeli hari ini. Bagi
    yang sudah memegang, angka yang berarti adalah yield terhadap harga
    belinya sendiri -- dan keduanya bisa jauh berbeda. Orang yang membeli
    di harga separuh mendapat yield dua kali lipat dari yang tertulis.
    """
    try:
        h, d = float(harga), float(dividen_per_saham)
    except (TypeError, ValueError):
        return None
    if h <= 0 or d < 0:
        return None

    hasil = {"harga": round(h, 2), "dividen_per_saham": round(d, 2),
             "yield_pct": round(d / h * 100, 2)}
    if harga_beli:
        try:
            hb = float(harga_beli)
            if hb > 0:
                hasil["yield_thd_harga_beli_pct"] = round(d / hb * 100, 2)
                hasil["harga_beli"] = round(hb, 2)
        except (TypeError, ValueError):
            pass
    if lot:
        try:
            n = float(lot)
            if n > 0:
                hasil["lot"] = n
                hasil["total_rp"] = round(n * 100 * d)
        except (TypeError, ValueError):
            pass
    return hasil
