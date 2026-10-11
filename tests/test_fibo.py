"""Penjaga Fibonacci berarah.

Yang dijaga di sini satu hal, dan ia yang membuat seluruh fitur ini
berarti: ARAH AYUNANNYA. Diukur, dua arah memberi hasil yang
BERLAWANAN, sehingga menggabungkannya saling meniadakan -- dan
implementasi lama persis menghasilkan kasus gabungan itu.
"""
import inspect
import json
import pathlib

from core import fibo


def _ukur():
    f = pathlib.Path(__file__).resolve().parent.parent / "tools" / "hasil_ukur_fibo.json"
    return {r["aturan"]: r for r in json.loads(f.read_text(encoding="utf-8"))["aturan"]}


def _ayun(naik=True, n=160, besar=0.30):
    """Ayunan buatan: mendatar, lalu bergerak besar satu arah, lalu
    mundur sedikit. Pivotnya jelas dan urutannya pasti."""
    harga = []
    for i in range(n):
        if i < 60:
            v = 1000 + (i % 4)                      # mendatar
        elif i < 100:
            laju = besar * (i - 60) / 40
            v = 1000 * (1 + laju if naik else 1 - laju)
        else:
            puncak = 1000 * (1 + besar if naik else 1 - besar)
            mundur = 0.25 * besar * (i - 100) / 60
            v = puncak * (1 - mundur if naik else 1 + mundur)
        harga.append(v)
    tgl = [f"2025-{1 + i // 28:02d}-{1 + i % 28:02d}" for i in range(n)]
    return tgl, [h * 1.004 for h in harga], [h * 0.996 for h in harga], harga


# ---------------------------------------------------------------------------
# Arah
# ---------------------------------------------------------------------------

def test_arah_dari_URUTAN_WAKTU_bukan_dari_yang_paling_ekstrem():
    """CACAT YANG DIPERBAIKI. calculate_fibonacci_levels() yang lama
    mengambil High.max() dan Low.min() dari 90 bar TANPA memedulikan
    mana yang lebih dulu. Kalau puncaknya terjadi sebelum lembahnya,
    level "61,8% dari low ke high" mengukur gerakan yang tidak pernah
    terjadi ke arah itu."""
    src = inspect.getsource(fibo.hitung)
    # Kandidat ayunan dibangun dari URUTAN: pasangan "naik" selalu
    # lembah-dulu-lalu-puncak (l < ip), "turun" sebaliknya. Yang dikunci
    # adalah adanya penyaringan posisi itu, bukan satu baris tertentu.
    assert "l for l in lembah if l < ip" in src,         "ayunan naik tidak menuntut lembah mendahului puncak"
    assert "p for p in puncak if p < il" in src,         "ayunan turun tidak menuntut puncak mendahului lembah"
    f_naik = fibo.hitung(*_ayun(naik=True))
    f_turun = fibo.hitung(*_ayun(naik=False))
    assert f_naik and f_naik.arah == "naik"
    assert f_turun and f_turun.arah == "turun"


def test_retracement_ayunan_naik_ada_DI_BAWAH_ujung_ayunan():
    """Pada ayunan naik, retracement adalah calon LANTAI saat harga
    mundur -- jadi ia harus di bawah puncaknya."""
    f = fibo.hitung(*_ayun(naik=True))
    ret = [x for x in f.level if x["jenis"] == "retracement"]
    assert ret and all(x["harga"] < f.akhir_harga for x in ret)


def test_retracement_ayunan_turun_ada_DI_ATAS_ujung_ayunan():
    f = fibo.hitung(*_ayun(naik=False))
    ret = [x for x in f.level if x["jenis"] == "retracement"]
    assert ret and all(x["harga"] > f.akhir_harga for x in ret)


def test_fibonacci_TIDAK_diklaim_punya_keunggulan():
    """TEMUAN YANG MEMBATALKAN TEMUAN SEBELUMNYA.

    Pengukuran pertama -- waktu ayunannya masih diambil dari pivot
    TERAKHIR -- memberi 38,2% naik +0,67% dan turun -1,24%, dan selisih
    1,91 poin itu sempat disebut salah satu yang terbesar di proyek ini.

    Sesudah penjangkarannya diperbaiki ke ayunan DOMINAN (perbaikan yang
    benar: itu yang ditarik manusia, dan tanpanya Fibonacci hilang di
    saham yang ayunan besarnya paling jelas), selisih itu LENYAP --
    kedua arah kini negatif, dan tandanya berganti-ganti antar-rasio
    tanpa urutan yang masuk akal.

    Jadi selisihnya artefak penjangkaran, bukan sifat pasar. Uji ini
    menjaga agar tidak ada yang menyajikan Fibonacci sbg sesuatu yang
    terukur menguntungkan hanya karena satu sel kebetulan positif.
    """
    m = _ukur()
    nilai = [r["unggul_pct"] for r in m.values()
             if "gabungan" not in r["aturan"] and r["n"] >= fibo.MIN_N_FIBO]
    assert nilai, "tidak ada sel bersampel memadai"
    # Tandanya campur aduk -- itu yang membuktikan tidak ada struktur.
    assert any(v > 0 for v in nilai) and any(v < 0 for v in nilai), nilai
    # Dan rata-ratanya tidak positif berarti.
    assert sum(nilai) / len(nilai) < 0.5, sum(nilai) / len(nilai)


# ---------------------------------------------------------------------------
# Jumlah level mengikuti besar ayunan
# ---------------------------------------------------------------------------

def test_ayunan_kecil_dapat_lebih_sedikit_garis():
    """Syaratnya bisa dihitung: jarak antar-level harus melebihi derau
    harian. Lima level menuntut ayunan > 8,5x ATR; dua level > 4,2x.
    Memaksakan lima pada ayunan kecil menggambar garis yang lebih rapat
    daripada gerak sehari."""
    assert fibo.MIN_AYUNAN_ATR_PENUH > fibo.MIN_AYUNAN_ATR_RINGKAS
    assert len(fibo.RETRACEMENT_RINGKAS) < len(fibo.RETRACEMENT)
    besar = fibo.hitung(*_ayun(naik=True, besar=0.60))
    kecil = fibo.hitung(*_ayun(naik=True, besar=0.10))
    n_besar = len([x for x in besar.level if x["jenis"] == "retracement"])
    if kecil:
        n_kecil = len([x for x in kecil.level if x["jenis"] == "retracement"])
        assert n_besar >= n_kecil


def test_ayunan_terlalu_kecil_tidak_menghasilkan_apa_pun():
    assert fibo.hitung(*_ayun(naik=True, besar=0.01)) is None


# ---------------------------------------------------------------------------
# Angka terukur
# ---------------------------------------------------------------------------

def test_kunci_tabel_memakai_rasio_pecahan():
    """BUG NYATA: kuncinya sempat tersimpan 38.2 sementara level memakai
    0.382 -- pencariannya tidak pernah cocok, dan layar diam-diam
    menulis "belum diukur" untuk level yang SUDAH diukur. Diam, tanpa
    error."""
    for (r, arah) in fibo.UNGGUL_FIBO:
        assert 0 < r < 1, r
        assert arah in ("naik", "turun")
    # Tabelnya BOLEH kosong -- ia memang dikosongkan sesudah
    # penjangkaran ayunan diganti, sampai pengukuran ulang selesai.
    # Yang dilarang bukan kosong, melainkan BERISI ANGKA LAMA.
    assert fibo.unggul(0.382, "naik") in (None,) or         fibo.UNGGUL_FIBO[(0.382, "naik")]["unggul_pct"] != 0.67,         "angka dari penjangkaran lama muncul kembali tanpa pengukuran ulang"


def test_level_membawa_angkanya_atau_None():
    f = fibo.hitung(*_ayun(naik=True, besar=0.60))
    for x in f.level:
        if x["jenis"] != "retracement":
            continue
        assert "unggul_pct" in x
        # None sah ("belum cukup sampel"); nol TIDAK -- nol itu klaim.
        assert x["unggul_pct"] is None or isinstance(x["unggul_pct"], float)


def test_rasio_bersampel_kecil_tidak_diberi_angka():
    """50% pada ayunan turun cuma 109 kejadian. Angka dari sampel
    sekecil itu tidak bisa dibedakan dari kebetulan."""
    m = _ukur()
    kecil = m.get("Fibo 50% ayunan turun")
    if kecil and kecil["n"] < fibo.MIN_N_FIBO:
        assert fibo.unggul(0.5, "turun") is None


def test_tidak_mengintip_masa_depan():
    """Pivot baru sah hanya sesudah JEDA_KANAN bar berikutnya terbukti
    berbalik -- sama dengan seluruh modul pola."""
    src = inspect.getsource(fibo.hitung)
    assert "JEDA_KANAN" in src


def test_data_cacat_tidak_meledak():
    assert fibo.hitung([], [], [], []) is None
    assert fibo.hitung(["2025-01-01"], [1.0], [1.0], [1.0]) is None


def test_angka_lama_tidak_boleh_kembali_tanpa_diukur_ulang():
    """Penjangkaran ayunan diganti dari "pivot terakhir" ke "ayunan
    dominan" -- aturan yang BERBEDA, pada saham yang sebagian besar
    berbeda pula (dulu 37% emiten dapat level, sekarang hampir
    semuanya).

    Memajang angka lama di atas aturan baru persis kesalahan yang sudah
    terjadi pada wedge: pembaca tidak punya cara tahu bahwa angka di
    depannya mengukur hal yang lain."""
    lama = {(0.382, "naik"): 0.67, (0.382, "turun"): -1.24,
            (0.618, "naik"): -0.28, (0.618, "turun"): 0.10}
    for k, v in lama.items():
        if k in fibo.UNGGUL_FIBO:
            assert fibo.UNGGUL_FIBO[k].get("unggul_pct") != v, k


# ---------------------------------------------------------------------------
# Uji kestabilan dua periode
# ---------------------------------------------------------------------------
# Fibonacci adalah yang TERAKHIR di aplikasi ini yang angkanya masih
# berdiri di atas satu pengukuran. Pola chart dan SMC sudah lulus uji dua
# periode sejak 11 Okt 2026; Fibonacci menyusul di sini.
#
# Dan justru Fibonacci yang punya riwayat paling buruk soal itu:
# pengukuran pertamanya memberi selisih arah 1,91 poin yang LENYAP
# seluruhnya begitu penjangkaran ayunannya dibetulkan (lihat
# test_fibonacci_TIDAK_diklaim_punya_keunggulan di atas). Satu perbaikan
# metode menghapus seluruh temuan. Uji di bawah ini menjaga agar angka
# yang dipajang selalu menyatakan sendiri seberapa jauh ia bisa dipercaya.


def test_tiap_baris_menyatakan_statusnya():
    """Angka tanpa status terbaca sama kuat dengan angka yang bertahan di
    dua periode. Itu perbedaan yang paling penting dan paling tidak
    terlihat -- di layar keduanya cuma selisih beberapa persen."""
    assert fibo.UNGGUL_FIBO, "tabel kosong; pengukuran belum digabung"
    for k, v in fibo.UNGGUL_FIBO.items():
        assert v.get("status") in ("stabil", "goyah", "sepihak"), (k, v)


def test_stabil_berarti_tandanya_memang_sama():
    """Bukan label yang ditempel tangan: "stabil" harus bisa dibuktikan
    dari dua angka yang ada di baris itu sendiri."""
    for k, v in fibo.UNGGUL_FIBO.items():
        if v["status"] != "stabil":
            continue
        assert v["unggul_5y"] is not None, k
        assert (v["unggul_pct"] > 0) == (v["unggul_5y"] > 0), k


def test_goyah_berarti_tandanya_memang_berbalik():
    for k, v in fibo.UNGGUL_FIBO.items():
        if v["status"] != "goyah":
            continue
        assert v["unggul_5y"] is not None, k
        assert (v["unggul_pct"] > 0) != (v["unggul_5y"] > 0), k


def test_sampel_di_bawah_ambang_tidak_diberi_angka():
    """Lima rasio x dua arah diuji sekaligus. Dari sepuluh sel, satu yang
    terlihat luar biasa memang DIHARAPKAN muncul karena kebetulan --
    "78,6% turun +3,58%" dengan n=135 adalah sel seperti itu."""
    for k, v in fibo.UNGGUL_FIBO.items():
        assert v["n"] >= fibo.MIN_N_FIBO, (k, v["n"])


def test_level_membawa_status_ke_layar():
    """Tanpa ini layar tidak punya cara membedakan keduanya, dan penandanya
    tidak akan pernah muncul -- diam-diam, tanpa error."""
    f = fibo.hitung(*_ayun(naik=True, besar=0.60))
    ret = [x for x in f.level if x["jenis"] == "retracement"]
    assert ret
    for x in ret:
        assert "status" in x


def test_layar_menandai_angka_yang_goyah_DAN_yang_sepihak():
    """Garis chart tidak bisa membawa tooltip, jadi penandanya harus ada
    di TEKSNYA sendiri. Lencana yang sama dipakai panel pola:

        ⚠ = tandanya BERBALIK antara 2 dan 5 tahun
        · = cuma cukup sampel di SATU periode

    Sepihak ikut ditandai. Tanpa itu baris yang cuma punya satu periode
    terbaca sama dengan baris yang bertahan di dua periode -- kebalikan
    dari yang seharusnya, karena buktinya paling tipis. Cacat yang sama
    baru ditutup di panel pola hari ini."""
    js = open("web/static/app.js", encoding="utf-8").read()
    i = js.index("function _gambarFibo(")
    # Sampai fungsi BERIKUTNYA, bukan sampai pemanggilan pertama
    # _renderPolaChips: pemanggilan itu ada di jalur pulang-awal yang
    # berdiri SEBELUM loop levelnya, jadi potongannya berhenti tepat
    # sebelum bagian yang dijaga. Dan anggaran karakter tetap bukan
    # gantinya -- itu kerapuhan yang sudah pecah di test_wa_alert.py.
    blok = js[i:js.index("\nfunction ", i + 1)]
    assert "status==='goyah'" in blok
    assert "status==='sepihak'" in blok


def test_gabungan_arah_dibuang_dari_tabel():
    """Dua arah terukur BERLAWANAN, jadi "gabungan arah" saling
    meniadakan dan angkanya tidak mengukur apa pun. Ia berguna cuma
    sebagai pembanding di berkas hasil, bukan untuk dipajang."""
    import io
    import os
    akar = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = io.open(os.path.join(akar, "tools", "gabung_ukur_fibo.py"),
                  encoding="utf-8").read()
    assert '"gabungan" in nama' in src and "continue" in src


def test_kunci_cache_overlay_berversi():
    """Medan `status` BARU di tiap level. Tanpa versi cache yang naik,
    server yang masih memegang overlay lama menyajikan level TANPA medan
    itu sampai TTL habis -- jadi tanda "⚠" tidak muncul untuk sebagian
    pengunjung saja, tanpa error, dan selisihnya justru pada baris yang
    paling perlu peringatan.

    Ini jebakan yang sudah berulang di proyek ini: mengubah bentuk
    payload tanpa menaikkan versi kuncinya bukan menghasilkan error,
    melainkan kolom yang diam-diam kosong sesudah deploy."""
    import re

    import web.app as app_module
    src = inspect.getsource(app_module._chart_overlay_payload)
    m = re.search(r'f"chartovl:v(\d+):', src)
    assert m, "kunci overlay tidak berversi"
    assert int(m.group(1)) >= 7, (
        f"versi masih v{m.group(1)}; medan `status` ditambahkan pada v7")


def test_hitungan_di_catatan_cocok_dengan_tabelnya():
    """KESALAHAN NYATA 12 Okt 2026: catatan di core/fibo.py dan dua teks
    di layar menulis "LIMA negatif" dari tujuh baris stabil. Yang benar
    EMPAT negatif dan TIGA positif.

    Angka di kalimat penjelasan tidak punya penjaga apa pun -- ia
    dihitung tangan sekali lalu tidak pernah diperiksa lagi, sementara
    tabelnya diperbarui tiap pengukuran. Uji ini membuat kalimatnya ikut
    terikat pada datanya."""
    stabil = [v for v in fibo.UNGGUL_FIBO.values() if v["status"] == "stabil"]
    n_neg = sum(1 for v in stabil if v["unggul_pct"] < 0)
    n_pos = len(stabil) - n_neg
    src = open("core/fibo.py", encoding="utf-8").read()
    i = src.index("KESIMPULANNYA BERTAHAN")
    blok = src[i:src.index("SATU HAL YANG MEMANG BERTAHAN", i)]
    # Jumlahnya disebut dengan ANGKA atau dengan kata, keduanya diterima
    # -- yang dijaga kebenarannya, bukan ejaannya.
    kata = {4: "EMPAT", 3: "TIGA", 5: "LIMA", 2: "DUA", 6: "ENAM"}
    assert (str(n_neg) in blok or kata.get(n_neg, "~") in blok), (
        f"catatan tidak menyebut {n_neg} sel negatif")
    assert (str(n_pos) in blok or kata.get(n_pos, "~") in blok), (
        f"catatan tidak menyebut {n_pos} sel positif")
    # Dan jumlah yang SALAH tidak boleh muncul.
    assert "LIMA negatif" not in blok


def test_angka_di_layar_cocok_dengan_tabelnya():
    """Teks edukasi dan tooltip chart mengutip hasil pengukuran. Kalau
    tabelnya berubah tapi kalimatnya tidak, layarnya membohongi pembaca
    dengan angka yang dulu benar."""
    stabil = [v for v in fibo.UNGGUL_FIBO.values() if v["status"] == "stabil"]
    n_neg = sum(1 for v in stabil if v["unggul_pct"] < 0)
    n_pos = len(stabil) - n_neg
    rata = sum(v["unggul_pct"] for v in stabil) / len(stabil)
    js = open("web/static/app.js", encoding="utf-8").read()
    for penanda in ("DIUKUR DUA PERIODE", "Fibonacci Retracement"):
        i = js.index(penanda)
        blok = js[i:i + 1200]
        assert f"{n_neg} negatif" in blok, (penanda, n_neg)
        assert f"{n_pos} positif" in blok, (penanda, n_pos)
        # Rata-rata disebut dengan koma desimal gaya Indonesia. Tanda
        # minusnya dinormalkan: layar memakai minus tipografis (U+2212),
        # sementara f-string Python menghasilkan hyphen ASCII. Keduanya
        # sah, dan membedakannya cuma akan membuat penjaga ini menyala
        # karena pilihan tipografi.
        def _norm(t):
            return t.replace("−", "-").replace(",", ".")
        assert _norm(f"{rata:.2f}") in _norm(blok), (penanda, rata)
