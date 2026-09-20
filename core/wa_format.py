"""Gaya penulisan pesan WhatsApp -- satu tempat, dipakai semua jawaban bot.

KENAPA ADA (permintaan penulis 20 Sep 2026: "penulisan bot wa bisa lebih
rapih ga biar orang bacanya ga bingung kebanyakan teks gitu dimana pun ya").

WhatsApp bukan halaman web, dan menulis untuknya punya batasan yang tidak
bisa disiasati:

  - TIDAK ADA tabel dan kolom. Apa pun yang disejajarkan dengan spasi akan
    patah di layar HP, dan yang tersisa lebih sulit dibaca daripada kalimat
    biasa.
  - Pesan panjang DILIPAT di balik "Baca selengkapnya". Jadi yang menentukan
    bukan seberapa lengkap isinya, melainkan apa yang ada di lima baris
    pertama. Bagian terpenting harus di atas, selalu.
  - Tebal (*...*) hanya bekerja kalau jarang. Kalau semua tebal, tidak ada
    yang menonjol -- dan itu yang terjadi kalau tiap bagian dan tiap angka
    ikut ditebalkan.

Yang dikerjakan di sini dua hal yang berbeda:

  1. MEMBANGUN -- `bagian()`, `padat()`, `potong()` membantu menyusun isi
     yang sudah pendek sejak awal.
  2. MERAPIKAN -- `rapikan()` membereskan hasilnya: baris kosong berlebih,
     judul bagian yang ternyata tidak berisi apa-apa, spasi menggantung.

Yang kedua dipasang di SATU titik keluar, jadi seluruh jawaban bot ikut rapi
tanpa perlu tiap penyusun pesan mengingatnya. Aturan gaya yang harus diingat
orang di dua belas tempat adalah aturan yang cepat atau lambat berbeda-beda.
"""
import os
import re

# Jaring pengaman, BUKAN alat utama.
#
# Versi pertama memasang batas 3000 karakter dengan alasan "di atas ini
# WhatsApp melipat isinya". Alasannya benar, tindakannya salah: 21 Sep 2026
# pesan `sinyal` terpotong sampai TIDAK ADA satu pun sinyal yang tersisa --
# pembaca cuma menerima ringkasan pencapaian, tepat kebalikan dari guna
# perintah itu. Penulis menolaknya dengan benar: "yg lengkap dong jangan
# selengkapnya di web".
#
# Rapi bukan berarti dipotong. Yang membuat pesan enak dibaca adalah kalimat
# yang padat dan urutan yang benar -- bukan isi yang diamputasi. Angka ini
# sekarang dipasang mendekati batas teknis WhatsApp, jadi ia cuma menahan
# keluaran yang benar-benar liar (bug, perulangan tak berujung), bukan pesan
# panjang yang memang panjang.
BATAS_PESAN = int(os.getenv("WA_BATAS_PESAN", "60000"))

# Berapa butir yang ditampilkan sebelum sisanya diringkas. Sepuluh butir
# berturut-turut sudah berhenti terbaca sebagai daftar; ia jadi dinding.
MAKS_BUTIR = 6

_JUDUL = re.compile(r"^\*[^*]+\*$")


def judul_bagian(baris: str) -> bool:
    """True kalau baris ini judul bagian (seluruhnya tebal)."""
    return bool(_JUDUL.match(baris.strip()))


def potong(teks, batas: int = 160) -> str:
    """Pendekkan teks bebas di batas KATA, bukan di tengah kata.

    Dipakai untuk kalimat yang datang dari analisis otomatis: kadang ia
    beberapa kalimat panjang, dan di WhatsApp itu langsung jadi paragraf
    yang dilewati orang.
    """
    t = " ".join(str(teks or "").split())
    if len(t) <= batas:
        return t
    potongan = t[:batas].rsplit(" ", 1)[0].rstrip(" ,.;:-")
    return potongan + "…"


def padat(pasangan, pemisah: str = " · ") -> str:
    """Gabungkan nilai-nilai pendek jadi SATU baris.

    `pasangan` boleh berupa (nama, nilai) atau string jadi. Yang nilainya
    None dibuang.

    Enam baris "• RSI: 62", "• MACD: bullish", ... menghabiskan enam baris
    layar untuk enam kata. Digabung jadi satu baris, ia terbaca sekali lihat
    dan menyisakan ruang untuk yang benar-benar perlu baris sendiri.
    """
    isi = []
    for p in pasangan or []:
        if p is None:
            continue
        if isinstance(p, (tuple, list)):
            nama, nilai = (list(p) + [None, None])[:2]
            if nilai is None or nilai == "":
                continue
            isi.append(f"{nama} {nilai}" if nama else str(nilai))
        elif str(p).strip():
            isi.append(str(p).strip())
    return pemisah.join(isi)


def bagian(nama: str, baris, maks: int | None = MAKS_BUTIR,
           peluru: str = "• ") -> list[str]:
    """Satu bagian bertajuk. Kembalikan [] kalau isinya kosong.

    Mengembalikan daftar kosong (bukan judul tanpa isi) itu inti gunanya:
    judul yang menggantung tanpa isi adalah baris yang menghabiskan tempat
    tanpa memberi tahu apa pun, dan ia muncul tiap kali datanya kebetulan
    tidak ada.
    """
    isi = [str(b).strip() for b in (baris or []) if str(b or "").strip()]
    if not isi:
        return []
    sisa = 0
    if maks and len(isi) > maks:
        sisa = len(isi) - maks
        isi = isi[:maks]
    keluar = [f"*{nama}*"] if nama else []
    keluar += [b if b.startswith(("•", "_", "*", " ")) else f"{peluru}{b}"
               for b in isi]
    if sisa:
        keluar.append(f"_… dan {sisa} lainnya._")
    return keluar


def rapikan(teks: str) -> str:
    """Bereskan hasil akhir: baris kosong berlebih & judul yang tidak berisi.

    Dipanggil di SATU titik keluar supaya seluruh jawaban bot ikut rapi
    tanpa tiap penyusun pesan perlu mengingatnya.

    TIDAK mengubah isi -- cuma jarak dan bagian yang memang kosong. Itu
    disengaja: perapian yang diam-diam membuang kalimat akan membuat
    kesalahan jauh lebih sulit dilacak daripada sekadar pesan yang kurang
    rapi.
    """
    if not teks:
        return ""
    baris = [b.rstrip() for b in str(teks).replace("\r\n", "\n").split("\n")]

    # Judul yang tidak diikuti isi apa pun dibuang. Dicari dari belakang
    # supaya judul terakhir (yang paling sering menggantung) ikut kena.
    simpan = [True] * len(baris)
    for i, b in enumerate(baris):
        if not judul_bagian(b):
            continue
        berisi = False
        for j in range(i + 1, len(baris)):
            if not simpan[j] or not baris[j].strip():
                continue
            berisi = not judul_bagian(baris[j])
            break
        if not berisi:
            simpan[i] = False
    baris = [b for b, ya in zip(baris, simpan) if ya]

    keluar = []
    for b in baris:
        if not b.strip():
            # Paling banyak SATU baris kosong berturut-turut, dan tidak
            # pernah tepat di bawah judul bagian.
            if not keluar or not keluar[-1].strip() or judul_bagian(keluar[-1]):
                continue
        keluar.append(b)
    while keluar and not keluar[-1].strip():
        keluar.pop()
    while keluar and not keluar[0].strip():
        keluar.pop(0)
    return "\n".join(keluar)


def batasi(teks: str, batas: int = BATAS_PESAN) -> str:
    """Jaring pengaman terakhir: tahan keluaran yang benar-benar liar.

    BUKAN alat untuk memendekkan pesan. Batas bawaannya dipasang mendekati
    batas teknis WhatsApp justru supaya fungsi ini hampir tidak pernah
    bekerja -- yang menahannya cuma bug atau perulangan tak berujung, bukan
    pesan panjang yang memang panjang. Lihat catatan di BATAS_PESAN.

    Kalau sampai bekerja, potongannya di batas BAGIAN (bukan tengah
    kalimat) supaya yang tersisa tidak terbaca seperti rusak.
    """
    t = teks or ""
    if len(t) <= batas:
        return t
    potongan = t[:batas]
    # Mundur ke batas bagian terakhir (baris kosong); kalau tidak ada,
    # mundur ke akhir baris.
    for pemisah in ("\n\n", "\n"):
        pos = potongan.rfind(pemisah)
        if pos > batas * 0.5:
            potongan = potongan[:pos]
            break
    return potongan.rstrip() + "\n\n_Pesan terlalu panjang, sisanya tidak ditampilkan._"


def siap_kirim(teks: str, batas: int = BATAS_PESAN) -> str:
    """rapikan() lalu batasi(). Inilah yang dipanggil di titik keluar."""
    return batasi(rapikan(teks), batas)
