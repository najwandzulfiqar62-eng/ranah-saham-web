"""Pemeriksaan statis app.js -- pengganti seadanya untuk `node --check`.

Kenapa perlu: seluruh logika aplikasi ada di satu berkas 400 KB tanpa linter,
dan satu kesalahan sintaks di sana membuat halaman tampil tapi MATI TOTAL --
persis yang pernah terjadi pada bug "tabel Audit Sinyal kosong" (`ml` dipakai
sebelum dideklarasikan). Node tidak tersedia di lingkungan pengembangan ini,
jadi yang bisa dilakukan adalah memeriksa hal-hal yang masih mungkin diperiksa
tanpa mesin JavaScript: keseimbangan kurung, dan invarian struktural yang
kalau dilanggar berarti aturan bisnisnya sudah bercabang dua lagi.

Pemeriksa ini SENGAJA konservatif. Ia tidak berpura-pura jadi parser: kalau
suatu bentuk sintaks tidak bisa dikenali dengan yakin, ia melewatinya alih-alih
menuduh. Alat yang sering salah tuduh akan diabaikan, dan alat yang diabaikan
tidak menjaga apa pun.
"""
import io
import os
import re

import pytest

APP_JS = os.path.join(os.path.dirname(__file__), "..", "web", "static", "app.js")


def _baca():
    return io.open(APP_JS, encoding="utf-8").read()


BUKA, TUTUP = "([{", ")]}"
PASANGAN = {")": "(", "]": "[", "}": "{"}


def _buang_teks_dan_komentar(t: str) -> str:
    """Ganti isi string/komentar dengan spasi, pertahankan kurung yang NYATA.

    Template literal ditangani khusus: isi teksnya dibuang, tapi bagian
    ${...} adalah kode sungguhan, jadi kurungnya tetap dihitung.
    """
    keluar = []
    i, n = 0, len(t)
    # tumpukan template literal: tiap kali masuk ${...} kita catat kedalamannya
    tpl_depth = []
    mode = None

    def _sebelumnya_menandakan_regex() -> bool:
        """Apakah '/' di posisi i memulai REGEX, bukan pembagian?

        JavaScript tidak bisa membedakan keduanya tanpa tahu token sebelumnya
        (masalah lama yang bahkan menyulitkan parser sungguhan). Heuristik
        yang dipakai di sini standar: sesudah operator/pembuka, '/' pasti
        regex; sesudah nilai (angka, pengenal, kurung tutup), ia pembagian.
        Tanpa ini, `/[&<>"']/g` di escHtml() terbaca sebagai kurung siku yang
        tidak pernah ditutup -- persis positif palsu yang membuat alat
        semacam ini ditinggalkan orang.
        """
        j = len(keluar) - 1
        while j >= 0 and keluar[j].isspace():
            j -= 1
        if j < 0:
            return True
        c = keluar[j]
        if c in "(,=:[!&|?{};+-*%~^<>":
            return True
        # kata kunci yang selalu diikuti ekspresi
        potong = "".join(keluar[max(0, j - 9):j + 1])
        return any(potong.endswith(k) for k in ("return", "typeof", "case", "in", "of", "=>"))

    while i < n:
        c = t[i]
        nx = t[i + 1] if i + 1 < n else ""
        if mode is None:
            if c == "/" and nx == "/":
                mode = "//"
                i += 2
                continue
            if c == "/" and nx == "*":
                mode = "/*"
                i += 2
                continue
            if c == "'":
                mode = "'"
                i += 1
                continue
            if c == '"':
                mode = '"'
                i += 1
                continue
            if c == "`":
                mode = "`"
                i += 1
                continue
            if c == "/" and _sebelumnya_menandakan_regex():
                mode = "re"
                i += 1
                continue
            if c == "}" and tpl_depth and tpl_depth[-1] == 0:
                # penutup ${...}: kembali ke dalam template literal
                tpl_depth.pop()
                mode = "`"
                keluar.append(" ")
                i += 1
                continue
            if tpl_depth:
                if c in BUKA:
                    tpl_depth[-1] += 1
                elif c in TUTUP:
                    tpl_depth[-1] -= 1
            keluar.append(c)
            i += 1
            continue

        if mode == "//":
            if c == "\n":
                mode = None
                keluar.append(c)
            i += 1
            continue
        if mode == "/*":
            if c == "*" and nx == "/":
                mode = None
                i += 2
                continue
            if c == "\n":
                keluar.append(c)
            i += 1
            continue

        if mode == "re":
            # Kelas karakter [...] boleh memuat '/' tanpa mengakhiri regex.
            if c == "\\":
                i += 2
                continue
            if c == "[":
                mode = "re["
            elif c == "/":
                mode = None
            i += 1
            continue
        if mode == "re[":
            if c == "\\":
                i += 2
                continue
            if c == "]":
                mode = "re"
            i += 1
            continue

        # di dalam string / template literal
        if c == "\\":
            i += 2
            continue
        if mode == "`" and c == "$" and nx == "{":
            tpl_depth.append(0)
            mode = None
            keluar.append(" ")
            i += 2
            continue
        if c == mode:
            mode = None
            i += 1
            continue
        if c == "\n":
            keluar.append(c)
        i += 1
    return "".join(keluar)


def test_kurung_app_js_seimbang():
    """Kurung yang tidak seimbang = seluruh aplikasi mati, bukan satu fitur."""
    bersih = _buang_teks_dan_komentar(_baca())
    tumpuk = []
    for baris_ke, baris in enumerate(bersih.split("\n"), start=1):
        for ch in baris:
            if ch in BUKA:
                tumpuk.append((ch, baris_ke))
            elif ch in TUTUP:
                assert tumpuk, f"kurung penutup {ch!r} berlebih di baris {baris_ke}"
                buka, buka_baris = tumpuk.pop()
                assert buka == PASANGAN[ch], (
                    f"baris {baris_ke}: {ch!r} tidak cocok dengan {buka!r} "
                    f"yang dibuka di baris {buka_baris}")
    assert not tumpuk, f"kurung belum ditutup, dibuka di baris {[b for _, b in tumpuk[-5:]]}"


def test_web_tidak_menghitung_ulang_anjuran_sinyal():
    """Aturan HOLD/JUAL/FULL TP hidup di backend (_anjuran_sinyal). Saat web
    menyalinnya ke JavaScript, salinan itu MENYIMPANG: ia menulis "HOLD"
    bahkan ketika harga sudah jatuh di bawah stop -- menyuruh menahan posisi
    yang menurut aturannya sendiri semestinya sudah dilepas. Pengujian ini
    menjaga agar salinan kedua itu tidak tumbuh lagi."""
    src = _baca()
    assert "_anjuranHtml(s.anjuran)" in src, "web tidak lagi memakai anjuran dari backend"
    # Jejak khas salinan lama: menyusun kalimat anjurannya sendiri.
    for jejak in ("anjuran=`HOLD", "stop ke titik impas Rp", "stop naik ke TP1 Rp"):
        assert jejak not in src, f"aturan anjuran tumbuh lagi di JavaScript: {jejak!r}"


def test_anjuran_html_membersihkan_html_dari_teks_backend():
    """Teks anjuran disisipkan ke innerHTML. Ia datang dari backend, bukan dari
    pengguna, jadi ini bukan lubang XSS hari ini -- tapi lolosnya tag mentah
    tetap akan merusak tata letak begitu ada kalimat mengandung '<'."""
    src = _baca()
    awal = src.index("function _anjuranHtml(")
    badan = src[awal:awal + 1200]
    assert "replace(/&/g" in badan and "replace(/</g" in badan, \
        "_anjuranHtml menyisipkan teks tanpa meng-escape HTML"


@pytest.mark.parametrize("contoh,seimbang", [
    ("const a = `teks ${b({c:1})} lagi`;", True),
    ("const a = 'kurung ( dalam string';", True),
    ("// komentar ) menyesatkan\nconst a = (1);", True),
    ("/* blok ( komentar */ const a = [1];", True),
    ("const a = (1;", False),
    ("const a = `${(1}`;", False),
    # Regex literal: isinya BUKAN kode, kurungnya tidak boleh ikut dihitung.
    ("const a = s.replace(/[&<>\"']/g, x);", True),
    ("const a = s.split(/[(]/);", True),
    ("const a = (b) / c / d;", True),
])
def test_pemeriksa_kurung_bisa_dipercaya(contoh, seimbang):
    """Pemeriksa yang belum pernah diuji tidak boleh dipakai menjaga apa pun:
    ia bisa saja lulus karena buta, bukan karena berkasnya benar."""
    bersih = _buang_teks_dan_komentar(contoh)
    tumpuk = []
    ok = True
    for ch in bersih:
        if ch in BUKA:
            tumpuk.append(ch)
        elif ch in TUTUP:
            if not tumpuk or tumpuk.pop() != PASANGAN[ch]:
                ok = False
                break
    assert (ok and not tumpuk) is seimbang


# =========================
# IDENTIFIER DIPAKAI TAPI TIDAK PERNAH DIDEKLARASIKAN
# =========================
# Kelas bug yang paling mahal di berkas ini, dan sudah terjadi TIGA kali:
#   1. `ml` dipakai sebelum dideklarasikan -> seluruh tabel Audit Sinyal kosong
#   2. `anjuran` masih dipakai kartu HP sesudah variabelnya dihapus -> halaman
#      Audit Sinyal KOSONG TOTAL di mobile (desktop selamat karena memakai
#      tampilan tabel, jadi bugnya lolos sampai user memotret layarnya)
#   3. `analisis()` & `escapeHtml()` yang tidak pernah ada sama sekali
# Semuanya melempar ReferenceError saat render, dan gejalanya BUKAN pesan
# error melainkan bagian halaman yang diam-diam hilang.

GLOBAL_JS = set("""
window document console navigator location history localStorage sessionStorage
setTimeout clearTimeout setInterval clearInterval requestAnimationFrame fetch
Math JSON Object Array String Number Boolean Date RegExp Map Set Promise Error
parseInt parseFloat isNaN isFinite encodeURIComponent decodeURIComponent
alert confirm prompt Intl URL URLSearchParams FormData Blob AbortController
undefined null true false NaN Infinity globalThis performance CustomEvent
Event MutationObserver IntersectionObserver ResizeObserver TextDecoder
structuredClone queueMicrotask crypto atob btoa Notification caches
this arguments super new typeof instanceof in of void delete return if else
for while do switch case break continue function const let var class extends
try catch finally throw async await yield default export import from as
""".split())

# Nama yang SUDAH diperiksa manual dan memang tidak apa-apa: global browser
# yang tidak masuk daftar di atas, plus beberapa celah parser sederhana ini
# (destructuring bersarang, parameter di posisi yang tidak dikenali). Daftar
# ini SENGAJA eksplisit -- setiap nama baru yang muncul harus diperiksa
# manusia, bukan diam-diam ikut lolos.
DIMAAFKAN = {
    "matchMedia", "getComputedStyle", "LightweightCharts", "Image", "File",
    "Uint8Array", "innerHeight",          # global browser
    "toast",                              # dipasang sbg window.toast
    "bar", "Discount", "pos", "isR", "isP", "im",   # celah parser
}


def _nama_dideklarasikan(kode: str) -> set:
    n = set()
    for m in re.finditer(r"\b(?:const|let|var)\s+([^;\n]*)", kode):
        potongan, dalam, kini = [], 0, ""
        for ch in m.group(1):
            if ch in "([{":
                dalam += 1
            elif ch in ")]}":
                dalam -= 1
            if ch == "," and dalam == 0:
                potongan.append(kini)
                kini = ""
            else:
                kini += ch
        potongan.append(kini)
        for p in potongan:
            p = p.split("=")[0].strip()
            if re.fullmatch(r"[A-Za-z_$][\w$]*", p):
                n.add(p)
    # Destructuring: `const [a,b]=...` dan `const {a,b}=...`. Tanpa ini,
    # SELURUH nama di dalamnya terlihat tidak pernah dideklarasikan -- dan
    # pemeriksa yang salah tuduh akan diabaikan orang.
    for pembungkus in (r"\b(?:const|let|var)\s*\[([^\]]*)\]",
                       r"\b(?:const|let|var)\s*\{([^}]*)\}"):
        for m in re.finditer(pembungkus, kode):
            for bagian in m.group(1).split(","):
                bagian = bagian.split(":")[-1].split("=")[0].strip()
                if re.fullmatch(r"[A-Za-z_$][\w$]*", bagian):
                    n.add(bagian)
    for pola in (r"\bfunction\s+([A-Za-z_$][\w$]*)", r"\bclass\s+([A-Za-z_$][\w$]*)",
                 r"\bcatch\s*\(\s*([A-Za-z_$][\w$]*)", r"\b([A-Za-z_$][\w$]*)\s*=>"):
        n |= {m.group(1) for m in re.finditer(pola, kode)}
    # parameter fungsi
    for m in re.finditer(r"\(([^()]*)\)\s*(?:=>|\{)", kode):
        for bagian in m.group(1).split(","):
            bagian = bagian.split("=")[0].split(":")[0].strip().lstrip(".").strip("{}[] ")
            for kecil in re.split(r"[,\s]+", bagian):
                if re.fullmatch(r"[A-Za-z_$][\w$]*", kecil):
                    n.add(kecil)
    return n


def _identifier_tak_dikenal(sumber: str) -> dict:
    kode = _buang_teks_dan_komentar(sumber)
    punya = _nama_dideklarasikan(kode) | GLOBAL_JS
    hasil = {}
    for i, baris in enumerate(kode.split("\n"), start=1):
        for m in re.finditer(r"(?<![.\w$])([A-Za-z_$][\w$]*)\b", baris):
            nama = m.group(1)
            if nama in punya or baris[m.end():m.end() + 1] == ":":
                continue
            hasil.setdefault(nama, i)
    return hasil


def test_tidak_ada_identifier_yang_tak_pernah_dideklarasikan():
    tersisa = {n: b for n, b in _identifier_tak_dikenal(_baca()).items()
               if n not in DIMAAFKAN}
    assert not tersisa, (
        "identifier dipakai tapi tidak pernah dideklarasikan (ReferenceError "
        f"saat render, bagian halaman akan hilang tanpa pesan error): {tersisa}")


def test_pemeriksa_identifier_benar_benar_menangkap_kasusnya():
    """Pemeriksa yang belum pernah dibuktikan bisa lulus karena buta, bukan
    karena berkasnya bersih. Ini menirukan persis bug yang terjadi: variabel
    dihapus tapi pemakaiannya di kartu HP tertinggal."""
    rusak = _baca().replace("${anjuranTxt}", "${anjuranTidakAda}")
    assert "anjuranTidakAda" in _identifier_tak_dikenal(rusak)


def test_versi_app_js_dan_service_worker_selalu_sama():
    """Menaikkan CACHE di sw.js tanpa menaikkan APP_VERSION (atau sebaliknya)
    membuat penanda versi di footer BERBOHONG -- dan penanda versi yang bohong
    lebih buruk daripada tidak ada, karena ia dipakai untuk memutuskan apakah
    sebuah perbaikan sudah sampai atau belum."""
    sw = io.open(os.path.join(os.path.dirname(__file__), "..", "web", "static", "sw.js"),
                 encoding="utf-8").read()
    cache = re.search(r"const CACHE\s*=\s*'ranahsaham-(v\d+)'", sw)
    app = re.search(r"const APP_VERSION\s*=\s*'(v\d+)'", _baca())
    assert cache and app, "penanda versi tidak ditemukan di salah satu berkas"
    assert cache.group(1) == app.group(1), (
        f"sw.js pakai {cache.group(1)} tapi app.js pakai {app.group(1)} -- "
        f"footer akan menampilkan versi yang salah")


def test_aplikasi_layar_utama_ikut_versi_baru():
    """Tanpa penanganan controllerchange, aplikasi yang dipasang di layar utama
    terus memakai app.js LAMA sampai benar-benar ditutup -- dan iOS menahannya
    tetap hidup, jadi versi lama bisa bertahan berhari-hari walau sudah deploy
    berkali-kali. Persis yang terjadi pada layar Audit Sinyal yang kosong."""
    src = _baca()
    assert "controllerchange" in src, "service worker baru tidak pernah diikuti halaman"
    # Instalasi PERTAMA tidak boleh ikut memicu reload (cuma bikin kedip).
    assert "navigator.serviceWorker.controller" in src, \
        "reload tidak dijaga terhadap instalasi pertama"
