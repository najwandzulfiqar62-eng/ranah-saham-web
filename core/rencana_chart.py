"""Rencana yang dibaca dari chart: beli di mana, jual di mana, batal kapan.

DIBANGUN DARI FAKTA YANG BISA DITELUSURI, bukan dari kalimat yang
terdengar meyakinkan. Tiap angka di sini berasal dari salah satu dari
tiga sumber, dan semuanya bisa diperiksa sendiri oleh pembaca di chart:

  - level S/R  -> core/level_sr.py (harga tempat pasar berulang berbalik)
  - pola chart -> core/pola_katalog.py (level kunci yang harus ditembus)
  - ATR        -> core/atr_stop.py (jarak stop yang sudah diukur)

TIDAK ADA ANGKA KEYAKINAN YANG DIKARANG. Aplikasi pembanding menampilkan
"75% confidence" tanpa menyebut dari mana angkanya; di sini yang
ditampilkan adalah `pct_positif` pola itu dari pengukuran nyata (berapa
persen kejadian berakhir naik dalam 20 hari, dari n kejadian), dan kalau
polanya belum diukur, tidak ada angka sama sekali. Angka keyakinan yang
dikarang adalah kebohongan yang paling sulit dibantah pembaca, karena ia
terlihat persis seperti hasil perhitungan.

BIAS BOLEH "NETRAL". Memaksa tiap saham punya arah berarti memberi
sinyal pada saham yang memang sedang tidak mengatakan apa-apa -- dan
itulah sebagian besar saham, sebagian besar waktu.
"""
from core.atr_stop import jarak_stop


def _lv(level: list, tipe: str) -> list:
    """Level satu sisi, diurutkan dari yang TERDEKAT ke harga."""
    x = [l for l in (level or []) if l.get("tipe") == tipe]
    return sorted(x, key=lambda l: l["harga"]) if tipe == "resistance" \
        else sorted(x, key=lambda l: -l["harga"])


def _pct(a: float, b: float) -> float | None:
    return None if not b else round((a - b) / b * 100, 2)


def susun(harga: float, level: list, pola: list, ma20=None, ma50=None,
          atr_pct: float | None = None) -> dict:
    """Rencana lengkap untuk satu emiten (atau IHSG)."""
    if not harga or harga <= 0:
        return {}

    atas, bawah = _lv(level, "resistance"), _lv(level, "support")
    r1 = atas[0] if atas else None
    s1 = bawah[0] if bawah else None
    s2 = bawah[1] if len(bawah) > 1 else None

    # --- BIAS -------------------------------------------------------------
    # Pola yang SUDAH tembus ditimbang lebih berat daripada yang baru
    # terbentuk -- itu seluruh gunanya membedakan dua fase itu.
    skor = 0.0
    pola_utama = None
    for p in (pola or []):
        if p.get("arah") not in ("naik", "turun"):
            continue
        bobot = 2.0 if p.get("fase") == "TEMBUS" else 1.0
        # Pola yang terukur BERLAWANAN dengan artinya (mis. Inverse H&S,
        # -1,12%) tidak boleh ikut menarik bias ke arah namanya. Arah
        # ditentukan angka terukurnya kalau angkanya ada.
        u = p.get("unggul_pct")
        arah = p["arah"]
        if u is not None:
            arah = "naik" if u > 0 else ("turun" if u < 0 else arah)
        skor += bobot * (1 if arah == "naik" else -1)
        if pola_utama is None or p.get("fase") == "TEMBUS":
            pola_utama = p
    if ma20 and ma50:
        if harga > ma20 and harga > ma50:
            skor += 1
        elif harga < ma20 and harga < ma50:
            skor -= 1

    bias = "bullish" if skor >= 2 else ("bearish" if skor <= -2 else "netral")

    # --- BELI / JUAL ------------------------------------------------------
    # Beli di SUPPORT, bukan di harga sekarang. Diukur di aplikasi ini
    # (panel Harga Beli): menunggu diskon membuat lebih sering benar,
    # walau harapannya lebih kecil. Yang dipakai di sini support TERUJI,
    # supaya titiknya bisa diperiksa pembaca di chart.
    def _alasan(lv, cadangan):
        # "teruji 1x" itu kontradiksi: satu sentuhan justru BELUM
        # teruji. Membiarkannya akan membuat level satu-sentuhan
        # terbaca sekuat level yang bertahan delapan kali -- padahal
        # seluruh gunanya memisahkan keduanya adalah supaya bedanya
        # terlihat.
        n = lv.get("sentuh") or 0
        bukti = (f"teruji {n}×" if n > 1
                 else "titik balik tunggal, belum teruji ulang")
        return (f"{lv.get('nama') or cadangan} — {bukti}, "
                f"terakhir {lv['terakhir']}")

    beli = jual = None
    if s1:
        beli = {"harga": s1["harga"], "alasan": _alasan(s1, "Support"),
                "teruji": (s1.get("sentuh") or 0) > 1,
                "jarak_pct": _pct(s1["harga"], harga)}

    # AREA JUAL = TEMPAT TEKANAN BELI TERBUKTI MELEMAH, bukan sekadar
    # atap terdekat.
    #
    # KENAPA DIUBAH. Versi pertama selalu memakai resistance terdekat.
    # Di tren yang sedang naik itu keliru: atap terdekat justru yang
    # paling sering tertembus, dan menyuruh jual di situ berarti
    # menyuruh keluar dari tren yang masih berjalan. Penulis
    # menyebutnya tepat -- "untuk area jual cari area pucuk/tekanan beli
    # melemah; kalau masih potensi naik ya cari area buy lagi".
    #
    # Yang dicari: level dengan BUKTI PENOLAKAN terkuat, yaitu yang
    # paling sering memantulkan harga. Level yang menolak lima kali
    # adalah tempat penjual benar-benar menunggu; level yang disentuh
    # sekali cuma harga yang kebetulan pernah dilewati.
    kandidat = atas[:3]
    puncak = None
    if kandidat:
        # Terbanyak sentuhannya; kalau seri, yang TERDEKAT -- yang jauh
        # benar tapi tidak menolong keputusan minggu ini.
        puncak = max(kandidat,
                     key=lambda x: ((x.get("sentuh") or 0), -x["harga"]))

    if bias == "bullish":
        # Di tren naik, atap terdekat diperlakukan sbg TARGET, bukan
        # tempat jual. Jual hanya kalau ada bukti penolakan sungguhan
        # (>=3 kali ditolak) di atas sana.
        if puncak and (puncak.get("sentuh") or 0) >= 3:
            jual = {"harga": puncak["harga"],
                    "alasan": _alasan(puncak, "Resistance")
                              + " — di sinilah tekanan beli berulang kali kalah",
                    "teruji": True, "jarak_pct": _pct(puncak["harga"], harga)}
        else:
            # TIDAK ADA area jual, dan itu jawaban yang benar: belum ada
            # tanda tekanan belinya melemah. Memaksa satu angka di sini
            # berarti mengarang titik keluar hanya supaya kolomnya
            # terisi.
            jual = None
    elif puncak:
        jual = {"harga": puncak["harga"], "alasan": _alasan(puncak, "Resistance"),
                "teruji": (puncak.get("sentuh") or 0) > 1,
                "jarak_pct": _pct(puncak["harga"], harga)}

    # --- INVALIDASI -------------------------------------------------------
    # Di bawah support KEDUA kalau ada; kalau tidak, pakai jarak ATR yang
    # sudah diukur (core/atr_stop.py) -- bukan persentase bulat, karena
    # stop 3% pada saham yang bergerak 3,6%/hari terukur kena 53,8% dari
    # waktu oleh hari biasa, bukan oleh analisis yang salah.
    dasar_inval = (s1 or {}).get("harga") or harga
    if s2:
        invalidasi = s2["harga"]
        alasan_inval = (f"di bawah {s2.get('nama') or 'support berikutnya'} "
                        f"({s2['sentuh']}× teruji)")
    else:
        sr_pct = abs(_pct(dasar_inval, harga) or 3.0)
        # jarak_stop boleh mengembalikan None (masukan tak lengkap).
        # Cadangannya 5% disebut di sini, bukan dibiarkan meledak -- dan
        # BUKAN 3%: 3% terukur kena 53,8% dari waktu oleh gerak harian
        # biasa, jadi memakainya sbg cadangan akan menanam ulang persis
        # kesalahan yang modul ATR itu dibuat untuk memperbaiki.
        j = jarak_stop(sr_pct, atr_pct or 3.0) or 5.0
        invalidasi = round(dasar_inval * (1 - j / 100), 2)
        alasan_inval = (f"{j:.1f}% di bawahnya — jarak dari ATR, "
                        "karena tidak ada support teruji lebih dalam")

    # --- KONFIRMASI -------------------------------------------------------
    if pola_utama and pola_utama.get("level_kunci"):
        konfirmasi = pola_utama["level_kunci"]
        alasan_konf = (f"level kunci {pola_utama['nama']} "
                       f"({'sudah ditembus' if pola_utama.get('fase') == 'TEMBUS' else 'belum ditembus'})")
    elif r1:
        konfirmasi = r1["harga"]
        alasan_konf = f"tembus {r1.get('nama') or 'resistance terdekat'}"
    else:
        konfirmasi = None
        alasan_konf = ""

    target = [x["harga"] for x in atas[:3]] if bias != "bearish" \
        else [x["harga"] for x in bawah[:3]]

    # --- IMBALAN vs RISIKO ------------------------------------------------
    # PENOLAKAN PENULIS YANG MELAHIRKAN INI: "area buy dan sell
    # kedeketan". Benar, dan sebabnya bukan selera melainkan cacat:
    # ketika harga terjepit di antara support dan resistance yang
    # berdekatan, dua garis itu nyaris menempel. Diukur pada IHSG saat
    # itu, beli -1,7% dan jual +2,1% -- jarak 3,8% yang sudah habis oleh
    # biaya transaksi dan selisih harga.
    #
    # Yang salah bukan angkanya, melainkan menyebut dua garis berdempetan
    # sebagai "rencana". Jadi imbalan/risiko dihitung, dan kalau ia di
    # bawah 1 rencananya DITANDAI TIDAK LAYAK, bukan disembunyikan --
    # pembaca tetap berhak melihat levelnya, cuma tidak boleh dibiarkan
    # mengira itu peluang.
    rr = None
    sempit = False
    if beli and jual and invalidasi:
        risiko = beli["harga"] - invalidasi
        imbalan = jual["harga"] - beli["harga"]
        if risiko > 0:
            rr = round(imbalan / risiko, 2)
            sempit = rr < 1.0

    return {
        "bias": bias, "skor_bias": round(skor, 1),
        "beli": beli, "jual": jual,
        "imbal_risiko": rr, "terlalu_sempit": sempit,
        "konfirmasi": konfirmasi, "alasan_konfirmasi": alasan_konf,
        "invalidasi": invalidasi, "alasan_invalidasi": alasan_inval,
        "target": target,
        "pola_utama": (pola_utama or {}).get("nama"),
        "narasi": _narasi(harga, bias, pola_utama, jual, s1, s2, ma20, ma50),
    }


def _narasi(harga, bias, pola, jual, s1, s2, ma20, ma50) -> str:
    """Paragraf yang SELURUH angkanya bisa diperiksa pembaca di chart.

    Ditulis dari fakta, bukan dari gaya. Kalimat seperti "struktur
    bearish jangka pendek" tanpa angka terdengar meyakinkan dan tidak
    bisa dibantah -- dan justru itu masalahnya.
    """
    b = []
    if ma20 and ma50:
        if harga > ma20 and harga > ma50:
            b.append(f"Harga {_rp(harga)} berada di atas MA20 ({_rp(ma20)}) "
                     f"dan MA50 ({_rp(ma50)}).")
        elif harga < ma20 and harga < ma50:
            b.append(f"Harga {_rp(harga)} berada di bawah MA20 ({_rp(ma20)}) "
                     f"dan MA50 ({_rp(ma50)}).")
        else:
            b.append(f"Harga {_rp(harga)} terjepit di antara MA20 "
                     f"({_rp(ma20)}) dan MA50 ({_rp(ma50)}).")

    if pola:
        u, n = pola.get("unggul_pct"), pola.get("n_ukur")
        kal = (f"Pola {pola['nama']} sedang berlaku dan "
               + ("SUDAH menembus" if pola.get("fase") == "TEMBUS"
                  else "BELUM menembus")
               + f" level kuncinya di {_rp(pola.get('level_kunci'))}.")
        if u is not None and n:
            # Pemisah ribuan diubah pada ANGKANYA saja. Versi pertama
            # memanggil .replace(",", ".") pada seluruh kalimat, sehingga
            # koma kalimatnya ikut jadi titik: "1.164 kejadian. pola di
            # fase ini" -- kalimat pecah, dan pembaca menyangka ada teks
            # yang hilang.
            n_teks = f"{n:,}".replace(",", ".")
            # Desimal KOMA, seperti seluruh aplikasi.
            u_teks = f"{u:+.2f}".replace(".", ",")
            kal += (f" Diukur pada {n_teks} kejadian, pola di fase ini "
                    f"berakhir {u_teks}% dibanding pasar dalam 20 hari "
                    "bursa.")
        b.append(kal)

    if s1:
        b.append(f"Pertahanan terdekat {_rp(s1['harga'])} "
                 f"({s1['sentuh']}× teruji, terakhir {s1['terakhir']})"
                 + (f"; kalau jebol, level berikutnya {_rp(s2['harga'])}."
                    if s2 else ", dan tidak ada support teruji di bawahnya."))
    else:
        b.append("Tidak ada support teruji di bawah harga sekarang — "
                 "harga berada di bawah semua level yang pernah bertahan "
                 "dalam rentang yang dipindai.")

    if jual:
        b.append(f"Tekanan beli terbukti melemah di {_rp(jual['harga'])} "
                 f"— di situ harga berulang kali ditolak.")
    elif bias == "bullish":
        # Ketiadaan area jual itu TEMUAN, bukan kolom yang gagal terisi.
        b.append("Belum ada tanda tekanan beli melemah di atas harga "
                 "sekarang, jadi belum ada area jual — yang ada di "
                 "atas cuma target, bukan tempat keluar.")

    b.append({"bullish": "Arahnya condong naik.",
              "bearish": "Arahnya condong turun.",
              "netral": "Arahnya belum jelas — dan itu keadaan yang "
                        "paling sering terjadi, bukan kegagalan analisis."}[bias])
    return " ".join(b)


def _rp(x) -> str:
    if x is None:
        return "–"
    return "Rp" + f"{round(float(x)):,}".replace(",", ".")
