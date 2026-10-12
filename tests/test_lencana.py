"""Penjaga lencana lintas-sistem.

Gagasannya dari penulis: saat membuka sebuah saham, langsung terlihat
"sudah masuk Audit Sinyal dan juga Smart Money". Yang dijaga di sini
BUKAN "lencananya muncul", melainkan satu hal yang membuat fitur ini
bisa menyesatkan kalau lepas:

    Lencana yang ditumpuk terbaca sebagai KONFIRMASI BERLAPIS, padahal
    sumbernya tidak saling bebas.
"""
import inspect

from core import lencana as lc
import web.app as app_module


def test_tumpang_tindih_smart_money_dan_vonis_disebut():
    """FAKTA DI KODE, bukan taksiran: _record_smart_money_cycle menolak
    mencatat kalau vonis Ringkasan Sinyal bukan BELI/BELI KUAT. Jadi
    "Smart Money + Vonis BELI" bukan dua pendapat yang kebetulan
    sepakat -- yang satu SYARAT bagi yang lain.

    Menghitungnya dua kali persis seperti menanyakan hal yang sama pada
    orang yang sama dua kali lalu menyebutnya konsensus."""
    src = inspect.getsource(app_module._record_smart_money_cycle)
    assert "_RINGKASAN_TEKNIKAL_BUY" in src, (
        "ketergantungan Smart Money pada vonis berubah; tinjau ulang "
        "TUMPANG_TINDIH di core/lencana.py")
    r = lc.susun("X", vonis="BELI", smart_money_pola="Siluman")
    pasangan = [sorted(p) for p in r["tumpang_tindih_aktif"]]
    assert ["smart_money", "vonis"] in pasangan
    assert r["keterangan_tumpang"]


def test_keterangan_tumpang_hanya_muncul_kalau_memang_bertindih():
    """Peringatan yang selalu muncul berhenti dibaca. Ia hanya tampil
    kalau pasangan yang bertindih benar-benar ada di emiten itu."""
    r = lc.susun("X", vonis="BELI")          # sendirian
    assert r["tumpang_tindih_aktif"] == []
    assert r["keterangan_tumpang"] is None


def test_lencana_membawa_angka_terukurnya():
    """Empat lencana tanpa angka terbaca sama kuat. Yang punya angka
    wajib menunjukkannya; yang belum diukur mengirim None -- bukan nol."""
    r = lc.susun("X", vonis="BELI", vonis_unggul=0.8,
                 pemulihan_kuat=True, pemulihan_unggul=4.01,
                 nr7_aktif=True)
    per = {x["kunci"]: x for x in r["lencana"]}
    assert per["vonis"]["unggul_pct"] == 0.8
    assert per["pemulihan"]["unggul_pct"] == 4.01
    # NR7 SUDAH diukur sejak 12 Okt 2026. Baris ini sebelumnya menuntut
    # None, dan itu benar SAAT ITU -- yang berubah buktinya, bukan
    # prinsipnya. Sekarang angkanya wajib cocok dengan tabelnya.
    from core.screening_pro import unggul_nr7_52w
    assert per["nr7"]["unggul_pct"] == unggul_nr7_52w()["unggul_pct"]
    assert per["nr7"]["n_ukur"] == unggul_nr7_52w()["n"]


def test_vonis_tengah_tidak_dapat_lencana():
    """Empat vonis tengah terukur tak membedakan apa pun. Memberi mereka
    lencana berarti menandai saham yang sedang tidak mengatakan apa-apa."""
    for v in ("CENDERUNG BELI", "NETRAL", "CENDERUNG JUAL", None):
        r = lc.susun("X", vonis=v)
        assert not any(x["kunci"] == "vonis" for x in r["lencana"]), v


def test_arah_lencana_vonis_mengikuti_sisinya():
    assert lc.susun("X", vonis="JUAL KUAT")["lencana"][0]["arah"] == "turun"
    assert lc.susun("X", vonis="BELI KUAT")["lencana"][0]["arah"] == "naik"


def test_pembangun_payload_tidak_memindai_apa_pun():
    """Satu halaman saham TIDAK boleh memicu pemindaian 793 emiten.
    Kalau cache-nya dingin, lencananya cuma tidak muncul -- dan itu
    jauh lebih baik daripada menahan pengunjung."""
    src = inspect.getsource(app_module._lencana_payload)
    for terlarang in ("_build_", "async_download", "download(", "await"):
        assert terlarang not in src, terlarang
    assert "_cache_get(" in src


def test_payload_lencana_sinkron():
    """Dipanggil dari dalam _hitung yang sinkron; kalau ia jadi async,
    hasilnya coroutine yang tidak pernah ditunggu -- lencananya kosong
    TANPA error."""
    assert not inspect.iscoroutinefunction(app_module._lencana_payload)


def test_kunci_cache_analyze_dinaikkan():
    """Payload bertambah medan `lencana`. Tanpa versi baru, server yang
    masih memegang cache lama menyajikan payload tanpa medan itu sampai
    TTL habis -- panelnya kosong untuk sebagian pengunjung saja."""
    import re
    src = inspect.getsource(app_module._analyze_payload)
    assert re.search(r'f"analyze:v\d+:\{kode\}"', src)


def test_layar_menampilkan_peringatan_tumpang_tindih():
    """Keterangannya TIDAK boleh disembunyikan di balik ketukan: ia
    justru yang mencegah kesimpulan yang salah, dan kesimpulan itu
    terbentuk dalam sedetik pertama melihat empat lencana."""
    js = open("web/static/app.js", encoding="utf-8").read()
    i = js.index("function _buildLencana(")
    blok = js[i:js.index("/* ---------- RENCANA DARI CHART", i)]
    assert "keterangan_tumpang" in blok
    assert "infoNote(" not in blok, "peringatan tidak boleh disembunyikan"


# ---------------------------------------------------------------------------
# SMC: satu-satunya yang lulus uji dua periode
# ---------------------------------------------------------------------------

def test_smc_angkanya_stabil_di_dua_periode():
    """SMC diukur di 2 tahun DAN 5 tahun, dan keempat tandanya cocok.
    Itu yang membedakannya dari hampir semua yang lain di proyek ini:
    harmonic terbalik arah, 95% wedge bukan wedge, selisih Fibonacci
    lenyap saat penjangkarannya dibetulkan, BELI KUAT ternyata lebih
    lemah dari BELI.

    Uji ini gagal kalau pengukuran ulang suatu hari membuat salah satu
    tandanya berbalik -- dan kalau itu terjadi, lencananya tidak boleh
    lagi menyandang kalimat 'stabil'."""
    from core.smc import UNGGUL_SMC
    assert len(UNGGUL_SMC) == 4
    for k, v in UNGGUL_SMC.items():
        assert (v["unggul_pct"] > 0) == (v["unggul_5y"] > 0), k
        assert v["stabil"] is True, k


def test_BOS_lebih_kuat_daripada_CHOCH_di_kedua_sisi():
    """Masuk akal secara teori: BOS penerusan tren yang sudah
    terkonfirmasi, CHOCH baru DUGAAN pembalikan. Terukur begitu di
    kedua periode, dan konsistensi itu yang membuatnya dipercaya."""
    from core.smc import UNGGUL_SMC as U
    assert U[("BOS", "bullish")]["unggul_pct"] > U[("CHOCH", "bullish")]["unggul_pct"]
    assert U[("CHOCH", "bearish")]["unggul_pct"] < U[("BOS", "bullish")]["unggul_pct"]


def test_lencana_smc_membawa_angka_dan_keterangan_stabil():
    r = lc.susun("X", smc_jenis="BOS", smc_arah="bullish")
    x = [y for y in r["lencana"] if y["kunci"] == "smc"][0]
    assert x["unggul_pct"] is not None
    assert "stabil" in x["catatan"]
    assert x["arah"] == "naik"


def test_kejadian_smc_lama_tidak_diberi_lencana():
    """Struktur yang pecah enam bulan lalu bukan keadaan sekarang, dan
    lencana yang menandainya menyesatkan justru karena terlihat
    aktual."""
    assert app_module.SMC_LENCANA_MAKS_BAR <= 30
    src = inspect.getsource(app_module._lencana_payload)
    assert "SMC_LENCANA_MAKS_BAR" in src


def test_medan_events_bukan_nama_karangan():
    """BUG YANG DICEGAH: versi pertama membaca (smc).get("terakhir"),
    medan yang TIDAK ADA di build_smc_summary -- lencana SMC tidak akan
    pernah muncul, diam-diam, tanpa error."""
    src = inspect.getsource(app_module._lencana_payload)
    assert '.get("events")' in src
    # Yang dilarang BENTUK PANGGILNYA, bukan katanya -- kata "terakhir"
    # muncul di komentar yang justru menjelaskan kenapa medan itu salah,
    # dan penjaga yang menyala karena kalimat penjelasan akan dimatikan
    # orang. (Kesalahan yang sama sudah tiga kali terjadi hari ini.)
    assert '.get("terakhir")' not in src
    assert '.get("last_event")' not in src


# ---------------------------------------------------------------------------
# MVH dijeda: berhenti MENCATAT, tetap digambar
# ---------------------------------------------------------------------------
# Keputusan penulis 12 Okt 2026. Syarat MVH adalah harmonic BULLISH, dan
# sisi bullish itu yang terukur paling lemah (-0,12%, n=414 -- di bawah
# pasar), sementara sisi bearish yang justru positif (+0,20%, n=458)
# tidak dipakai teori ini. Persilangannya dengan Minervini belum pernah
# diukur; harness-nya tools/ukur_mvh.py.


def test_mvh_tidak_mencatat_sinyal_secara_bawaan():
    """Yang dijeda PENERBITAN REKOMENDASI, bukan gambarnya.

    Menggambar pola di chart adalah keterangan bentuk yang bisa diperiksa
    pembaca sendiri. Mencatat sinyal BELI adalah rekomendasi yang masuk
    signal_history, diaudit, dan ikut membentuk win rate yang dipakai
    menilai seluruh aplikasi. Dua hal yang beban buktinya berbeda."""
    assert app_module.MVH_CATAT_AKTIF is False, (
        "MVH mencatat sinyal lagi; itu butuh angka dari tools/ukur_mvh.py "
        "yang bertahan di dua periode")
    # Gerbangnya harus PERNYATAAN PERTAMA sesudah docstring, bukan di
    # tengah sesudah cache dibaca dan kandidat disusun.
    #
    # Diperiksa lewat AST, bukan pencarian teks: kata "MVH_CATAT_AKTIF"
    # juga muncul di DOCSTRING fungsi ini (yang menjelaskan jedanya), dan
    # versi pertama uji ini menangkap docstring itu lalu gagal meskipun
    # gerbangnya ada dan benar. Kesalahan yang sama sudah tujuh kali di
    # proyek ini.
    import ast
    import textwrap
    fn = ast.parse(textwrap.dedent(
        inspect.getsource(app_module._record_minervini_harmonic_cycle))).body[0]
    badan = [n for n in fn.body
             if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
    gerbang = badan[0]
    assert isinstance(gerbang, ast.If), (
        "pernyataan pertama bukan gerbang; MVH bisa mengerjakan sesuatu "
        "sebelum memeriksa apakah ia boleh")
    assert any(isinstance(n, ast.Return) for n in ast.walk(gerbang))
    assert "MVH_CATAT_AKTIF" in ast.dump(gerbang.test)


def test_sinyal_mvh_yang_sudah_terbuka_tetap_diaudit():
    """Menjeda pencatatan TIDAK boleh menelantarkan sinyal yang sudah
    terbit. Orang yang mengikutinya berhak tahu bagaimana akhirnya, dan
    win rate yang meninggalkan sinyal menggantung adalah win rate yang
    memilih sendiri sampelnya.

    audit_open_signals menyaring WHERE status='OPEN' TANPA filter source,
    jadi ia memang mencakupnya -- uji ini menjaga agar filter source
    tidak pernah ditambahkan ke sana."""
    import core.signal_history as sh
    src = inspect.getsource(sh.audit_open_signals)
    assert "WHERE status = 'OPEN'" in src
    assert "source =" not in src and "source IN" not in src


def test_lencana_mvh_menyebut_jedanya_DAN_angkanya():
    """Lencana ini muncul dari sinyal MVH yang masih terbuka. Tanpa
    keterangan jedanya, ia terlihat seaktual lencana lain dan pembaca
    wajar mengira teorinya masih berjalan -- padahal yang ia lihat sisa
    sinyal lama.

    VERSI PERTAMA UJI INI MENUNTUT unggul_pct IS NONE, dan itu benar
    SAAT ITU: persilangannya belum diukur. Yang berubah buktinya, bukan
    prinsipnya. Sejak 12 Okt 2026 angkanya ada (-0,37%, n=232, stabil di
    dua periode), dan "belum diukur" jadi pernyataan yang SALAH.

    Perbedaan keduanya penting: "belum diukur" mengundang pembaca
    menebak, "diukur, hasilnya negatif" tidak."""
    from core.harmonic import unggul_mvh
    r = lc.susun("X", minervini_harmonic_aktif=True)
    x = [y for y in r["lencana"] if y["kunci"] == "minervini_harmonic"][0]
    assert "DIJEDA" in x["catatan"]
    u = unggul_mvh()
    assert x["unggul_pct"] == u["unggul_pct"]
    assert x["n_ukur"] == u["n"]


def test_lencana_mvh_memajang_PELENGKAPNYA_bukan_cuma_angkanya():
    """-0,37% sendirian masih bisa dibaca "ya sudah, kecil".

    Dibandingkan dengan Minervini TANPA harmonic (+0,73%), yang terbaca
    adalah bahwa syarat harmonic MENGURANGI 1,10 poin -- ia bukan filter
    yang ketat, ia filter yang salah. Pembandingnya itu yang membawa
    maknanya, dan tanpa dipajang maknanya hilang."""
    r = lc.susun("X", minervini_harmonic_aktif=True)
    x = [y for y in r["lencana"] if y["kunci"] == "minervini_harmonic"][0]
    assert "TANPA harmonic" in x["catatan"]
    assert "MENGURANGI" in x["catatan"]


def test_angka_mvh_lulus_uji_dua_periode():
    """Tandanya harus SAMA di 2 dan 5 tahun, dan sel pembandingnya pun.
    Kalau pengukuran ulang suatu hari membalikkan salah satunya, klaim
    "stabil" di core/harmonic.py tidak boleh lagi disandang."""
    from core.harmonic import UNGGUL_MVH as U
    assert U["stabil"] is True
    assert (U["unggul_pct"] > 0) == (U["unggul_2y"] > 0), "tanda berbalik"
    # Persilangannya harus LEBIH BURUK dari pelengkapnya -- itu seluruh
    # temuannya, dan angkanya harus konsisten dengan selisih yang dicatat.
    assert U["unggul_pct"] < U["tanpa_harmonic_pct"]
    assert abs((U["unggul_pct"] - U["tanpa_harmonic_pct"])
               - U["selisih_poin"]) < 0.02
    # Dan kedua sel bersampel memadai di periode panjang; tanpa itu ini
    # cuma arah, bukan angka.
    from core.harmonic import MIN_N_HARMONIC
    assert U["n"] >= MIN_N_HARMONIC
    assert U["tanpa_harmonic_n"] >= MIN_N_HARMONIC


def test_harness_pengukur_mvh_ada_dan_mengukur_PELENGKAPNYA():
    """Yang menentukan bukan "apakah MVH untung", melainkan apakah
    harmonic MENAMBAH sesuatu pada Minervini.

    MVH menuntut dua syarat. Diukur sendirian lalu positif, itu belum
    berarti apa pun -- bisa jadi seluruh angkanya datang dari Minervini
    dan harmonic cuma mengurangi jumlah sinyal tanpa menambah kualitas.
    Pengurangan jumlah sinyal SELALU terlihat seperti penyaringan yang
    ketat, padahal mungkin cuma membuang sinyal secara acak.

    Karena itu harness-nya wajib mengukur PELENGKAPNYA juga: Minervini
    TANPA harmonic, pada sampel yang sama."""
    import io
    import os
    akar = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = io.open(os.path.join(akar, "tools", "ukur_mvh.py"),
                  encoding="utf-8").read()
    assert "C. Minervini TANPA harmonic" in src
    assert "B. Minervini x Harmonic bullish" in src
    # Dan ambangnya harus yang SAMA dengan produksi, kalau tidak yang
    # diukur bukan teori yang dijalankan.
    assert 'os.getenv("MINERVINI_MIN_KRITERIA", "7")' in src
    assert "MAKS_UMUR_D = 10" in src


def test_layar_saringan_minervini_memajang_angka_terukurnya():
    """Minervini SENDIRIAN adalah keunggulan terukur terbesar bersampel
    terbanyak di aplikasi ini: +0,78% (5 thn, n=2.438) dan +0,69%
    (2 thn, n=570), tandanya sama di kedua periode.

    Ia muncul dari pengukuran MVH -- sebagai sel pembanding -- dan
    hampir hilang bersama kesimpulan tentang harmonic. Angka sebesar itu
    yang tidak dipajang di layarnya sendiri adalah pengukuran yang
    terbuang."""
    import re
    js = open("web/static/app.js", encoding="utf-8").read()
    i = js.index("Trend template Minervini")
    blok = js[i:i + 2200]
    from core.harmonic import UNGGUL_MINERVINI_SAJA as U
    # Angkanya DIBACA dari blok itu lalu dibandingkan dengan tabelnya --
    # kalau pengukuran ulang menggeser angkanya, kalimat di layar ikut
    # harus berubah. Kalimat yang mengutip angka tanpa penjaga akan
    # menyimpang diam-diam; itu sudah terjadi pada "LIMA negatif" hari ini.
    assert f"+{U['unggul_pct']:.2f}".replace(".", ",") in blok
    assert f"{U['n']:,}".replace(",", ".") in blok
    assert f"+{U['unggul_2y']:.2f}".replace(".", ",") in blok
    assert re.search(r"dua periode|kedua periode", blok)
