"""Support & resistance dari titik balik yang BERULANG, bukan dari rumus.

KENAPA BUKAN PIVOT FIBONACCI. Aplikasi ini sudah punya
calculate_support_resistance_deep (pivot Fibonacci dari bar terakhir),
dan level itu berguna untuk rencana harian. Tapi untuk DIGAMBAR di chart
berbulan-bulan ia keliru: diukur pada BBCA, R1 dan S1 cuma berjarak 1,3%
-- sembilan garis bertumpuk di sekitar harga sekarang, yang menutupi
candle alih-alih menjelaskannya.

Yang digambar trader di chart adalah hal lain: harga tempat pasar
BERKALI-KALI berbalik. Itu yang dihitung di sini.

CARANYA, dan tiap langkah ada alasannya:

  1. Kumpulkan titik balik (pivot high & low) di jendela yang dilihat.
  2. Kelompokkan yang berdekatan jadi satu level -- dua puncak di Rp1.000
     dan Rp1.005 itu SATU level, bukan dua. Lebar kelompoknya mengikuti
     volatilitas saham itu sendiri (ATR), bukan persentase tetap: 1,5%
     itu longgar untuk BBCA dan sempit untuk saham gocap.
  3. Nilai tiap level dari BANYAK sentuhan dan BARU-nya sentuhan itu.
     Level yang disentuh empat kali lebih berarti daripada sekali, dan
     yang disentuh bulan lalu lebih berarti daripada dua tahun lalu.

TIDAK ADA YANG MENGINTIP MASA DEPAN: pivot baru sah sesudah JEDA_KANAN
bar berikutnya terbukti berbalik -- sama dengan seluruh modul pola.

LEVEL YANG SUDAH DITEMBUS BERGANTI PERAN. Resistance yang ditembus jadi
support, dan sebaliknya. Itu bukan tambahan teori, itu konsekuensi dari
cara level diberi nama: ia dinamai dari posisinya terhadap harga
SEKARANG, bukan dari kejadian waktu ia terbentuk.
"""
from dataclasses import dataclass

from core.divergence import JEDA_KANAN, JEDA_KIRI, pivot_low
from core.pola_chart import pivot_high

# Jendela yang dipertimbangkan. Lebih panjang dari ini, levelnya berasal
# dari keadaan pasar yang sudah berganti.
JENDELA = 260

# Lebar kelompok, sebagai kelipatan ATR%. 0,8 x ATR dipilih karena itu
# kira-kira jarak yang masih terasa "harga yang sama" bagi pelaku pasar:
# di bawahnya satu level pecah jadi beberapa, di atasnya level yang
# berbeda ikut melebur.
PENGALI_ATR = 0.8
# Batas bawah & atas, untuk saham yang ATR-nya ekstrem.
MIN_LEBAR_PCT = 0.8
MAKS_LEBAR_PCT = 6.0

MIN_SENTUH = 2          # satu titik balik bukan level, itu kebetulan
MAKS_LEVEL = 4          # per sisi; lebih dari ini chartnya penuh garis

# Bobot kebaruan: sentuhan paling lama dihargai separuh dari yang
# terbaru. Bukan nol -- level lama yang masih terlihat tetap diingat
# pasar, cuma tidak sekuat yang baru.
BOBOT_TERTUA = 0.5


@dataclass(frozen=True)
class Level:
    harga: float
    sentuh: int
    terakhir: str        # tanggal sentuhan terakhir
    pertama: str
    skor: float
    tipe: str            # "resistance" | "support"
    kuat: bool           # >= 3 sentuhan
    nama: str = ""       # peran level ini, diisi _beri_nama()

    def dict(self) -> dict:
        return {"harga": round(self.harga, 2), "sentuh": self.sentuh,
                "terakhir": self.terakhir, "pertama": self.pertama,
                "skor": round(self.skor, 2), "tipe": self.tipe,
                "kuat": self.kuat, "nama": self.nama}


# Nama per JENJANG, bukan per level. Level pertama di atas harga bukan
# jenis yang sama dengan level ketiga di atasnya: yang pertama menentukan
# apa yang terjadi minggu ini, yang ketiga menentukan sampai mana kalau
# semuanya berjalan. Menamai semuanya "Resistance" membuang perbedaan itu
# -- dan perbedaan itulah yang dicari orang ketika melihat chart.
_NAMA_RESISTANCE = ["Resistance Terdekat", "Resistance Swing",
                    "Resistance Struktural", "Puncak Mayor"]
_NAMA_SUPPORT = ["Support Terdekat", "Support Swing",
                 "Support Struktural", "Dasar Mayor"]


def _beri_nama(atas: list, bawah: list) -> tuple[list, list]:
    """Beri peran tiap level menurut jaraknya dari harga sekarang.

    `atas` sudah terurut menaik dari harga, `bawah` menurun dari harga.
    """
    atas = [Level(**{**x.__dict__, "nama": _NAMA_RESISTANCE[min(i, 3)]})
            for i, x in enumerate(atas)]
    bawah = [Level(**{**x.__dict__, "nama": _NAMA_SUPPORT[min(i, 3)]})
             for i, x in enumerate(bawah)]
    return atas, bawah


def _atr_pct(tinggi: list, rendah: list, tutup: list, n: int = 14) -> float:
    """ATR sebagai persen harga. Dipakai menentukan lebar kelompok."""
    if len(tutup) < n + 1:
        return 2.0
    tr = []
    for i in range(len(tutup) - n, len(tutup)):
        h, l, pc = float(tinggi[i]), float(rendah[i]), float(tutup[i - 1])
        tr.append(max(h - l, abs(h - pc), abs(l - pc)))
    harga = float(tutup[-1]) or 1.0
    return max(0.1, sum(tr) / len(tr) / harga * 100)


def cari_level(tanggal: list, tinggi: list, rendah: list, tutup: list,
               maks_per_sisi: int = MAKS_LEVEL) -> list[Level]:
    """Level support & resistance yang berlaku pada bar terakhir."""
    n = len(tutup)
    if n < 60 or not (len(tanggal) == len(tinggi) == len(rendah) == n):
        return []
    akhir = n - 1
    awal = max(0, akhir - JENDELA)

    # Titik balik: puncak DAN lembah masuk kolam yang sama. Sengaja --
    # level yang dulu jadi puncak sering kemudian jadi dasar, dan
    # memisahkan kolamnya akan menghitung satu level yang sama dua kali
    # dengan sentuhan yang terbagi dua.
    titik = []
    for i in pivot_high(tinggi, JEDA_KIRI, JEDA_KANAN):
        if awal <= i <= akhir - JEDA_KANAN:
            titik.append((i, float(tinggi[i])))
    for i in pivot_low(rendah, JEDA_KIRI, JEDA_KANAN):
        if awal <= i <= akhir - JEDA_KANAN:
            titik.append((i, float(rendah[i])))
    if len(titik) < MIN_SENTUH:
        return []
    titik.sort(key=lambda x: x[1])

    harga_kini = float(tutup[akhir])
    if harga_kini <= 0:
        return []
    lebar_pct = min(MAKS_LEBAR_PCT,
                    max(MIN_LEBAR_PCT,
                        _atr_pct(tinggi, rendah, tutup) * PENGALI_ATR))

    # KEPADATAN, BUKAN KOTAK BERURUTAN.
    #
    # Versi pertama membagi titik menjadi kelompok berurutan selebar
    # `lebar_pct`. Hasilnya diperiksa pada BBCA: empat "level" berjarak
    # hampir rata, masing-masing tepat 4 sentuhan. Itu bukan level, itu
    # bekas potongan -- sebaran pivot yang menerus dipotong jadi kotak
    # selebar sama, dan tiap kotak kebetulan berisi jumlah yang mirip.
    # Levelnya akan bergeser hanya karena titik PERTAMA kebetulan
    # berbeda, dan tidak ada yang akan menyadarinya: empat garis rapi
    # terlihat persis seperti analisis yang benar.
    #
    # Yang benar: cari harga tempat titik baliknya BERDESAKAN. Untuk tiap
    # calon harga, jumlahkan bobot titik dalam jarak +-lebar, lalu ambil
    # puncak-puncak kepadatannya dengan jarak minimal satu lebar
    # (penekanan non-maksimum). Level yang keluar adalah tempat pasar
    # benar-benar berulang kali berbalik, bukan tepi kotak.
    rentang = max(1, akhir - awal)
    lebar_abs = lebar_pct / 100 * harga_kini

    def _bobot(i):
        return BOBOT_TERTUA + (1 - BOBOT_TERTUA) * ((i - awal) / rentang)

    calon = []
    for i, h in titik:
        anggota = [(j, hj) for j, hj in titik if abs(hj - h) <= lebar_abs]
        if len(anggota) < MIN_SENTUH:
            continue
        calon.append((sum(_bobot(j) for j, _ in anggota), h, anggota))
    if not calon:
        return []
    calon.sort(key=lambda x: -x[0])

    kelompok, dipakai = [], []
    for skor, h, anggota in calon:
        # Pusat kelompok = rata-rata TERBOBOT anggotanya, bukan harga
        # calonnya sendiri -- calonnya kebetulan salah satu titik, dan
        # memakainya akan menggeser level ke titik yang kebetulan dipilih.
        tot = sum(_bobot(j) for j, _ in anggota)
        pusat = sum(_bobot(j) * hj for j, hj in anggota) / tot
        if any(abs(pusat - p) <= lebar_abs for p in dipakai):
            continue
        dipakai.append(pusat)
        kelompok.append(anggota)

    keluar = []
    for g in kelompok:
        if len(g) < MIN_SENTUH:
            continue
        # Harga level = rata-rata TERBOBOT kebaruan, bukan rata-rata
        # biasa: kalau harga merayap, level yang relevan adalah tempat
        # ia berbalik BELAKANGAN ini.
        bobot = [BOBOT_TERTUA + (1 - BOBOT_TERTUA) * ((i - awal) / rentang)
                 for i, _h in g]
        total = sum(bobot)
        harga = sum(b * h for b, (_i, h) in zip(bobot, g)) / total
        idx = [i for i, _h in g]
        keluar.append(Level(
            harga=harga, sentuh=len(g),
            terakhir=str(tanggal[max(idx)]), pertama=str(tanggal[min(idx)]),
            skor=total,
            tipe="resistance" if harga > harga_kini else "support",
            kuat=len(g) >= 3,
        ))

    # Yang terdekat dengan harga lebih dulu -- level jauh di atas sana
    # benar, tapi tidak menolong keputusan hari ini.
    atas = sorted([x for x in keluar if x.tipe == "resistance"],
                  key=lambda x: x.harga)[:maks_per_sisi]
    bawah = sorted([x for x in keluar if x.tipe == "support"],
                   key=lambda x: -x.harga)[:maks_per_sisi]

    # TITIK BALIK TUNGGAL ikut ditandai kalau satu sisi masih sepi.
    #
    # KENAPA. Diperiksa pada BBCA: cuma 3 pivot low di bawah harga
    # (4.786, 5.529, 5.759) dan tak satu pun berpasangan, sehingga
    # aturan "minimal dua sentuhan" melaporkan TIDAK ADA support sama
    # sekali. Secara definisi itu benar -- level yang disentuh sekali
    # memang belum teruji. Tapi bagi yang melihat chartnya, dasar di
    # 5.529 itu jelas ada, dan panel yang bilang "tidak ada apa-apa di
    # bawah" terbaca seperti panel yang rusak.
    #
    # Jadi keduanya ditampilkan, dengan perbedaan yang DIJAGA: level
    # teruji punya sentuh >= 2, titik balik tunggal punya sentuh == 1
    # dan kuat == False. Layar menuliskan bedanya. Yang dihindari bukan
    # menampilkannya, melainkan menampilkannya SEOLAH sama kuat.
    def _isi(sisi, kandidat, naik: bool):
        if len(sisi) >= maks_per_sisi:
            return sisi
        dipakai_h = [x.harga for x in sisi]
        urut = sorted(kandidat, key=lambda p: p[1] if naik else -p[1])
        for i, h in urut:
            if len(sisi) >= maks_per_sisi:
                break
            if any(abs(h - d) <= lebar_abs for d in dipakai_h):
                continue
            dipakai_h.append(h)
            sisi.append(Level(
                harga=h, sentuh=1, terakhir=str(tanggal[i]),
                pertama=str(tanggal[i]), skor=_bobot(i),
                tipe="resistance" if naik else "support", kuat=False))
        return sorted(sisi, key=lambda x: x.harga if naik else -x.harga)

    atas = _isi(atas, [(i, h) for i, h in titik if h > harga_kini], True)
    bawah = _isi(bawah, [(i, h) for i, h in titik if h < harga_kini], False)

    atas, bawah = _beri_nama(atas, bawah)
    # Yang paling dalam / paling tinggi diberi nama ekstrem kalau ia
    # memang titik ekstrem jendelanya -- itu yang dicari orang ketika
    # bertanya "sampai mana kalau jebol".
    if bawah and abs(bawah[-1].harga - min(h for _i, h in titik)) <= lebar_abs:
        bawah[-1] = Level(**{**bawah[-1].__dict__, "nama": "Dasar Mayor"})
    if atas and abs(atas[-1].harga - max(h for _i, h in titik)) <= lebar_abs:
        atas[-1] = Level(**{**atas[-1].__dict__, "nama": "Puncak Mayor"})

    return sorted(atas + bawah, key=lambda x: x.harga)


def ringkas(level: list[Level], harga_kini: float) -> dict:
    """Resistance & support TERDEKAT, plus jaraknya dalam persen.

    Jarak ikut dihitung di sini supaya layar dan bot memakai angka yang
    sama -- menghitungnya dua kali adalah cara mereka jadi berbeda.
    """
    atas = [x for x in level if x.tipe == "resistance"]
    bawah = [x for x in level if x.tipe == "support"]
    r = atas[0] if atas else None
    s = bawah[-1] if bawah else None
    return {
        "resistance_terdekat": r.dict() if r else None,
        "support_terdekat": s.dict() if s else None,
        "jarak_resistance_pct": (None if not (r and harga_kini) else
                                 round((r.harga - harga_kini) / harga_kini * 100, 2)),
        "jarak_support_pct": (None if not (s and harga_kini) else
                              round((harga_kini - s.harga) / harga_kini * 100, 2)),
    }
