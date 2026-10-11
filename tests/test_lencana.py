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
    # NR7 belum diukur terpisah -> None, dan itu pernyataan yang benar.
    assert per["nr7"]["unggul_pct"] is None


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
