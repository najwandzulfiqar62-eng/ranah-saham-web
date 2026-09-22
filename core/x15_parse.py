"""Urai laporan X-15 KSEI, dan PASTIKAN emitennya tidak tertukar.

KENAPA ADA (22 Sep 2026). Penulis melihat di layarnya:

    TRUK  · PT PUKUL RATA KANAN     +15,00%
    AKPI  · HAKIMSON GROWTH CAPITAL  +5,00%

Nama dan persentasenya BENAR -- keduanya perusahaan sungguhan, dan
angkanya cocok dengan pemberitaan. Yang salah EMITENNYA: Hakimson Growth
Capital membeli 5% saham TRUK, bukan AKPI. Keduanya membeli TRUK pada hari
yang sama, menggantikan Catur Dharma Anugerah Surya yang melepas.

Kesalahan seperti ini yang paling berbahaya: tiap bagiannya terlihat benar,
jadi tidak ada yang mencurigainya. Yang salah cuma PASANGANNYA.

SEBABNYA. Kode emiten diambil dari METADATA pengumuman (`Kode_Emiten`),
sedangkan nama dan angkanya diurai dari PDF lampirannya -- dan cuma
lampiran PERTAMA yang dibaca. Kalau satu pengumuman memuat beberapa
lampiran, atau kode di metadata tidak sama dengan emiten di dalam PDF-nya,
tidak ada apa pun yang memeriksa keduanya cocok.

PERBAIKANNYA. PDF X-15 memuat nama emitennya sendiri ("Nama Perusahaan
Tbk"). Nama itu sekarang DICOCOKKAN dengan nama emiten pemilik kode. Kalau
keduanya jelas berbeda, barisnya TIDAK ditampilkan -- baris yang salah
pasangan lebih buruk daripada baris yang hilang, karena orang bertindak
atas dasarnya.
"""
import re

# Nilai yang memang berarti "kosong" di laporan IDX. Daftar ini SENGAJA
# pendek dan cuma berisi penanda kosong -- bukan tebakan tentang nama yang
# "terdengar aneh".
#
# Pelajaran 22 Sep 2026: saya sempat menyaring "PUKUL RATA KANAN" karena
# mengira itu serpihan tata letak. Ternyata PT Pukul Rata Kanan perusahaan
# sungguhan yang membeli 15% TRUK. Penyaring yang menebak-nebak nama mana
# yang "masuk akal" akan membuang data yang benar, dan itu kesalahan yang
# lebih sulit disadari daripada nama aneh yang lolos.
_PENANDA_KOSONG = {"null", "none", "-", "", "n/a", "na",
                   "tidak ditampilkan", "not displayed"}

_MAKS_NAMA = 120


def bersih_nama(s: str) -> str:
    """Rapikan nama; kosongkan HANYA kalau ia penanda kosong."""
    t = " ".join(str(s or "").split())
    if t.lower().strip(" :.") in _PENANDA_KOSONG:
        return ""
    return t[:_MAKS_NAMA]


def baca_persen(s: str):
    """Angka persen, atau None kalau tidak terbaca.

    None, BUKAN 0.0. Nilai yang tidak terbaca dan nilai yang benar-benar
    nol adalah dua hal yang sangat berbeda: menyamakannya membuat "hak
    suara sebelum" yang gagal dibaca dilaporkan sebagai kenaikan penuh.
    """
    t = str(s or "").replace("%", "").replace(",", ".").strip().strip(":").strip()
    if not t:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", t)
    if not m:
        return None
    try:
        nilai = float(m.group(0))
    except ValueError:
        return None
    if not (0 <= nilai <= 100):
        return None      # di luar 0-100 berarti yang terbaca bukan persentase
    return nilai


def _kata_penting(nama: str) -> set:
    """Kata-kata yang membedakan satu nama emiten dari yang lain.

    Bentuk badan usaha dan kata umum dibuang: hampir semua emiten BEI
    mengandung "PT" dan "Tbk", jadi mencocokkan lewat kata itu akan
    menyatakan semua emiten cocok dengan semua emiten.
    """
    buang = {"pt", "tbk", "persero", "indonesia", "industry", "industri",
             "international", "internasional", "group", "grup", "and", "dan"}
    kata = re.findall(r"[a-z]+", (nama or "").lower())
    return {k for k in kata if len(k) >= 3 and k not in buang}


def emiten_cocok(nama_di_pdf: str, nama_emiten: str) -> bool | None:
    """Apakah emiten di PDF sama dengan emiten pemilik kodenya?

    True  = cocok
    False = JELAS berbeda -> barisnya tidak boleh dipakai
    None  = tidak bisa dinilai (salah satu namanya tidak ada)

    Sengaja mengembalikan None alih-alih menebak: menolak baris karena
    nama pembandingnya kebetulan tidak tersedia akan membuang data yang
    benar, dan itu kesalahan yang sama seperti menerima yang salah.
    """
    a, b = _kata_penting(nama_di_pdf), _kata_penting(nama_emiten)
    if not a or not b:
        return None
    if a & b:
        return True
    return False


def cari_nilai(strings: list, *kata_kunci: str, jangkauan: int = 6) -> str:
    """Nilai sesudah label yang memuat salah satu kata kunci.

    Potongan-potongan sesudah label DISAMBUNG, bukan diambil satu. Teks di
    PDF terpecah karena kerning: "PT SINAR MAS" bisa tersimpan sebagai
    ("PT ")("SINAR")(" MAS"), dan mengambil satu potongan menghasilkan
    potongan, bukan nama.
    """
    for i, s in enumerate(strings):
        rendah = str(s).lower()
        if not any(k.lower() in rendah for k in kata_kunci):
            continue
        sisa = str(s).split(":", 1)
        if len(sisa) == 2 and sisa[1].strip():
            return sisa[1].strip()
        kumpul = []
        for j in range(i + 1, min(i + 1 + jangkauan, len(strings))):
            t = str(strings[j]).strip()
            if not t:
                continue
            if t.startswith(":"):
                t = t[1:].strip()
                if not t:
                    continue
            if t.endswith(":") and len(t) > 2:
                break            # label berikutnya sudah mulai
            # LABEL BERIKUTNYA dikenali dari potongan SESUDAHNYA: di PDF
            # ini label selalu diikuti potongan yang diawali ":". Tanpa
            # pemeriksaan ini, penyambungnya menelan label berikutnya dan
            # menghasilkan nama seperti "null Hak Suara Sebelum Transaksi"
            # -- ditemukan oleh uji lama, bukan oleh saya.
            if (j + 1 < len(strings)
                    and str(strings[j + 1]).strip().startswith(":")):
                break
            kumpul.append(t)
            if len(" ".join(kumpul)) >= 12:
                break
        if kumpul:
            return " ".join(kumpul).strip()
    return ""


def urai(strings: list, nama_emiten: str = "") -> dict | None:
    """Potongan teks PDF -> satu baris laporan, atau None kalau tidak layak.

    `nama_emiten` = nama perusahaan pemilik kode emiten pengumumannya.
    Diberikan supaya pasangan kode-emiten bisa DIPERIKSA, bukan dipercaya.
    """
    if not strings:
        return None

    nama = bersih_nama(cari_nilai(strings, "sesuai SID", "Name (SID", "Nama (sesuai"))
    perusahaan = bersih_nama(cari_nilai(strings, "Nama Perusahaan", "Issuer"))
    jabatan = bersih_nama(cari_nilai(strings, "Jabatan", "Position"))
    sebelum = baca_persen(cari_nilai(strings, "Hak Suara Sebelum",
                                     "Voting rights before", "Sebelum Transaksi"))
    setelah = baca_persen(cari_nilai(strings, "Hak Suara Setelah",
                                     "Voting rights after", "Setelah Transaksi"))

    if setelah is None or not (nama or perusahaan):
        return None

    # PEMERIKSAAN PASANGAN. Inilah inti perbaikan 22 Sep 2026.
    cocok = emiten_cocok(perusahaan, nama_emiten) if nama_emiten else None
    if cocok is False:
        return None

    semua = " ".join(str(x) for x in strings).lower()
    if "penjualan" in semua or "divestasi" in semua:
        jenis = "jual"
    elif "pembelian" in semua or "repurchase" in semua:
        jenis = "beli"
    elif "hibah" in semua or "transfer" in semua or "waris" in semua:
        jenis = "transfer"
    else:
        jenis = "lain"

    pengendali = cari_nilai(strings, "Keterangan Pengendali",
                            "Controlling Shareholder").lower().strip(" :")

    return {
        "nama": nama,
        "perusahaan": perusahaan,
        "jabatan": jabatan,
        "pct_sebelum": sebelum,
        "pct_setelah": setelah,
        # None kalau "sebelum" tidak diketahui -- BUKAN dianggap 0 lalu
        # dilaporkan sebagai kenaikan penuh.
        "perubahan": (round(setelah - sebelum, 4) if sebelum is not None else None),
        "jenis": jenis,
        "pengendali": pengendali.startswith(("ya", "yes")),
        "emiten_terverifikasi": bool(cocok),
    }
