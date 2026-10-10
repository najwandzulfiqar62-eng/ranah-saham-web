"""Penjaga screener Vonis + kiriman otomatisnya ke WhatsApp.

Berkas ini mengunci kelas-kelas bug yang SUDAH pernah terjadi di proyek
ini, bukan sekadar "endpointnya jalan":

  - permintaan pengunjung memicu pemindaian dingin (scaling #1)
  - loop sinkron membekukan event loop
  - kunci cache tidak berversi -> kolom diam-diam kosong sesudah deploy
  - sumber gagal -> halaman kosong, padahal hasil lama masih ada
  - vonis dari bar sesi berjalan yang masih berkedip ikut diberitakan
  - dua pendorong berbagi kunci dedup -> saling membungkam tanpa jejak
  - angka di panduan menyimpang dari angka di kodenya
"""
import asyncio
import inspect

import pytest

import web.app as app_module

UKURAN = {"beli_kuat_pct": 1.11, "beli_pct": 0.38, "jual_kuat_pct": -0.95,
          "bertahan_pct": 4.59, "horizon_hari": 20, "n_episode": 23755,
          "diukur": "2026-10-11", "diukur_pada": "emiten likuid"}


def _it(kode="BBCA", vonis="BELI KUAT", setara=False, likuid=True, **ubah):
    d = {"kode": kode, "vonis": vonis, "beli": 6, "jual": 1, "netral": 0,
         "harga": 9250, "rsi": 61.2, "chg1": 1.4, "chg5": 3.8, "skor": 72,
         "bertahan": setara, "unggul_pct": 4.59 if setara else 1.11,
         "setara_kuat": setara, "nilai_harian": 4_200_000_000 if likuid else 8_000_000,
         "likuid": likuid}
    d.update(ubah)
    return d


def _payload(items=None):
    items = items if items is not None else [_it()]
    return {
        "items": items, "universe": 793,
        "beli_kuat": sum(1 for x in items if x["vonis"] == "BELI KUAT"),
        "beli": sum(1 for x in items if x["vonis"] == "BELI"),
        "jual_kuat": sum(1 for x in items if x["vonis"] == "JUAL KUAT"),
        "bertahan": sum(1 for x in items if x["setara_kuat"]),
        "ukuran": UKURAN,
    }


# ---------------------------------------------------------------------------
# Permintaan pengunjung tidak boleh memicu pemindaian
# ---------------------------------------------------------------------------

def test_cache_dingin_dijawab_SEKETIKA_bukan_memindai(monkeypatch):
    """Scaling #1. Screener ini lebih berat daripada panel mana pun yang
    sudah ada -- DUA panggilan skor AI per emiten (hari ini + kemarin,
    untuk aturan dua hari) di 793 emiten. Memindainya atas permintaan satu
    pengunjung membuat SELURUH aplikasi tersendat, bukan cuma halamannya.
    """
    monkeypatch.setattr(app_module, "_cache_get", lambda k: None)
    monkeypatch.setattr(app_module, "_cache_get_stale", lambda k: None)

    def _jangan(*a, **k):
        raise AssertionError("endpoint memindai sendiri saat cache dingin")

    monkeypatch.setattr(app_module, "_build_screener_vonis", _jangan)
    r = asyncio.run(app_module.api_screener_vonis())
    assert r["menyiapkan"] is True
    assert r["items"] == []


def test_hasil_basi_disajikan_bukan_halaman_kosong(monkeypatch):
    """Yahoo gagal sekali bukan alasan menampilkan halaman kosong kalau
    hasil kemarin masih ada. Yang WAJIB ada: penanda `basi`, supaya
    pengguna tahu angkanya belum segar."""
    monkeypatch.setattr(app_module, "_cache_get", lambda k: None)
    monkeypatch.setattr(app_module, "_cache_get_stale", lambda k: _payload())
    r = asyncio.run(app_module.api_screener_vonis())
    assert r["basi"] is True
    assert r["items"][0]["kode"] == "BBCA"
    assert "menyiapkan" not in r


def test_cache_hangat_tidak_ditandai_basi(monkeypatch):
    monkeypatch.setattr(app_module, "_cache_get", lambda k: _payload())
    r = asyncio.run(app_module.api_screener_vonis())
    assert not r.get("basi")
    assert not r.get("menyiapkan")


def test_kunci_cache_berversi():
    """Kunci tanpa versi = bentuk payload berubah, kolom diam-diam kosong
    sesudah deploy, dan TIDAK ada error yang muncul di mana pun."""
    import re
    # ADANYA versi yang dikunci, bukan angkanya -- mengunci "v1" membuat
    # tes gagal tepat ketika versinya dinaikkan dengan BENAR.
    assert re.fullmatch(r"screener_vonis:v\d+", app_module._SCREENER_VONIS_KEY)


def test_pemanas_cache_menghangatkan_screener_vonis():
    """Tanpa ini halamannya selamanya menjawab "sedang disiapkan":
    pengunjung tidak pernah memindai sendiri (lihat tes di atas), jadi
    satu-satunya yang mengisi cache-nya adalah pemanas."""
    src = inspect.getsource(app_module._warm_shared_caches)
    assert "_SCREENER_VONIS_KEY" in src
    assert "_build_screener_vonis" in src
    assert "_single_flight" in src


def test_loop_pemindaian_dijalankan_di_worker_thread():
    """Loop sinkron 793 emiten tanpa `await` membekukan event loop --
    artinya SEMUA permintaan lain ikut menggantung, bukan cuma ini."""
    src = inspect.getsource(app_module._build_screener_vonis)
    assert "asyncio.to_thread" in src
    assert "_pindai_vonis" in src


def test_pindai_vonis_sinkron_bukan_coroutine():
    """Kalau ia jadi async, `asyncio.to_thread` akan mengembalikan
    coroutine yang tidak pernah ditunggu -- items jadi kosong TANPA error."""
    assert not inspect.iscoroutinefunction(app_module._pindai_vonis)


# ---------------------------------------------------------------------------
# Isi screener: hanya vonis yang terukur berarti
# ---------------------------------------------------------------------------

def test_hanya_tiga_keranjang_vonis_yang_ditampilkan():
    """Empat vonis tengah terukur berada dalam rentang +-0,25% dari pasar.
    Menyaringnya tetap boleh secara teknis, tapi menyajikannya sebagai
    "hasil saringan" berarti memberi daftar yang tidak membedakan apa pun
    dari memilih acak -- dan daftar itu lebih berbahaya daripada daftar
    kosong, karena terlihat seperti pekerjaan yang sudah dilakukan."""
    src = inspect.getsource(app_module._pindai_vonis)
    assert '("BELI KUAT", "BELI", "JUAL KUAT")' in src
    for tengah in ("CENDERUNG BELI", "CENDERUNG JUAL", "NETRAL"):
        assert tengah not in src


def test_vonis_tengah_tidak_pernah_lolos_saringan(monkeypatch):
    """Dikunci lewat PERILAKU, bukan cuma lewat sumber kodenya -- tes yang
    membaca teks kode akan tetap hijau kalau ambangnya dipindah ke tempat
    lain."""
    import pandas as pd

    df = pd.DataFrame({"Open": [100.0] * 80, "High": [101.0] * 80,
                       "Low": [99.0] * 80, "Close": [100.0] * 80,
                       "Volume": [1_000_000] * 80})
    monkeypatch.setattr(app_module, "fix_yf_columns", lambda d: d)
    monkeypatch.setattr(app_module, "_ringkasan_kemarin", lambda d: "NETRAL")

    import core.ai_score as ai_mod
    monkeypatch.setattr(ai_mod, "calculate_ai_score_from_df",
                        lambda d: {"price": 100, "rsi": 50, "score": 50,
                                   "change_1d": 0.0, "change_5d": 0.0,
                                   "ma50": 100, "ma200": 100})
    monkeypatch.setattr(app_module, "_ringkasan_sinyal_teknikal",
                        lambda ai: {"overall": "NETRAL", "beli": 2,
                                    "jual": 2, "netral": 3})
    assert app_module._pindai_vonis(["AAAA.JK"], {"AAAA.JK": df}) == []


def test_yang_bertahan_dua_hari_diurut_paling_atas():
    """+4,59% itu keunggulan terbesar yang pernah diukur di proyek ini.
    Menaruhnya di tengah daftar menyembunyikan hal terbaik yang punya
    halaman ini."""
    items = [_it("AAAA", "BELI KUAT", setara=False),
             _it("BBBB", "BELI", setara=True),
             _it("CCCC", "JUAL KUAT", setara=False)]
    urut = {"BELI": 0, "BELI KUAT": 1, "JUAL KUAT": 2}
    hasil = sorted(items, key=lambda x: (not x["setara_kuat"],
                                         urut.get(x["vonis"], 9),
                                         not x["likuid"],
                                         -(x["skor"] or 0)))
    assert hasil[0]["kode"] == "BBBB"


def test_saham_sepi_ditandai_bukan_dibuang_diam_diam():
    """Angka keunggulan DIUKUR pada emiten likuid. Saham sepi boleh ikut
    terlihat, tapi WAJIB bertanda -- memajangnya tanpa tanda berarti
    menjanjikan angka yang tidak pernah diuji di sana."""
    src = inspect.getsource(app_module._pindai_vonis)
    assert '"likuid"' in src
    js = open("web/static/app.js", encoding="utf-8").read()
    assert "SEPI" in js and "belum diuji di sini" in js


def test_angka_terukur_dikirim_dari_satu_sumber():
    """Layar dan bot harus memakai angka yang SAMA. Menuliskannya dua kali
    adalah cara mereka jadi berbeda tanpa ada yang sadar."""
    src = inspect.getsource(app_module._build_screener_vonis)
    assert 'UNGGUL_VONIS["BELI KUAT"]' in src
    # Keranjang terkuat kini BELI yang bertahan, bukan BELI KUAT --
    # yang dikunci adalah ia MENGAMBIL dari tabel terukur, bukan
    # menuliskan angkanya sendiri.
    assert 'UNGGUL_BERTAHAN[' in src


# ---------------------------------------------------------------------------
# Kiriman otomatis ke WhatsApp
# ---------------------------------------------------------------------------

def test_kunci_dedup_pendorong_TIDAK_berbagi_ruang():
    """BUG YANG DICEGAH: sebelum parameter `ruang` ada, kuncinya
    "dorong:sm:BBCA" untuk SEMUA pemakai. Begitu pendorong kedua memakai
    fungsi yang sama, BBCA yang baru diumumkan Smart Money akan diam-diam
    dibungkam di pendorong vonis selama 24 jam, dan sebaliknya -- dua
    kabar berbeda tentang saham yang sama saling menelan, tanpa jejak di
    log mana pun."""
    from core.wa_dorong import _kunci_dorong
    assert _kunci_dorong("BBCA") != _kunci_dorong("BBCA", "vonis")
    assert _kunci_dorong("BBCA") == "dorong:sm:BBCA"
    assert _kunci_dorong("bbca", "vonis") == "dorong:vonis:BBCA"


def test_default_ruang_sm_dipertahankan():
    """Catatan "sudah dikirim" yang sudah ada di basis data memakai kunci
    lama. Mengubah defaultnya akan membuat seluruh riwayat itu tidak
    terbaca, dan saham yang sudah diumumkan kemarin diumumkan lagi."""
    from core.wa_dorong import _kunci_dorong, catat_terkirim, pilih_belum_dikirim
    assert inspect.signature(_kunci_dorong).parameters["ruang"].default == "sm"
    assert inspect.signature(pilih_belum_dikirim).parameters["ruang"].default == "sm"
    assert inspect.signature(catat_terkirim).parameters["ruang"].default == "sm"


def test_dorong_vonis_memakai_ruang_vonis():
    src = inspect.getsource(app_module._dorong_vonis)
    assert 'ruang="vonis"' in src
    assert src.count('ruang="vonis"') >= 2  # pilih + catat


def test_dorong_vonis_hanya_dua_tingkat_teratas():
    """Mengirim pemberitahuan ke HP orang untuk vonis yang terukur tidak
    membedakan apa pun adalah cara tercepat membuat SELURUH pemberitahuan
    diabaikan."""
    assert app_module._DORONG_VONIS_TINGKAT == ("BELI KUAT", "BELI")


def test_dorong_vonis_memakai_penyaring_kestabilan():
    """Vonis dihitung dari bar HARI INI yang belum selesai: RSI, %1 hari,
    dan rasio volume masih bergerak, jadi saham bisa menyeberangi ambang
    6-dari-7 lalu kembali lagi dalam hitungan menit. Pelajaran yang sudah
    mahal dua kali di proyek ini (NR7 dari bar berjalan, label Smart Money
    yang berkedip) -- dan di sini paling sulit dibatalkan, pesannya sudah
    ada di HP orang."""
    src = inspect.getsource(app_module._dorong_vonis)
    assert "saring_stabil" in src
    assert "dalam_jam_kirim" in src


def test_pembanding_ditulis_sebelum_pengiriman():
    """Pembanding putaran berikutnya harus mencerminkan apa yang
    benar-benar terlihat sekarang -- berhasil atau tidak pengirimannya.
    Yang bergantung pada keberhasilan kirim cuma catatan "sudah
    diberitakan"."""
    src = inspect.getsource(app_module._dorong_vonis)
    i_set = src.index("_set_config(_DORONG_VONIS_SEBELUMNYA_KEY")
    # Titik PANGGILnya, bukan baris impornya -- "send_wa_text" muncul
    # lebih dulu di `from core.whatsapp_notify import ...`.
    i_kirim = src.index("await send_wa_text(")
    i_catat = src.index("catat_terkirim(baru")
    assert i_set < i_kirim < i_catat


def test_dorong_vonis_tidak_memindai_sendiri():
    """Alasannya persis sama dengan _dorong_anomali: memaksa pemindaian
    793 emiten dari dalam loop pengirim cuma menambah satu tempat baru
    yang bisa menahan server."""
    src = inspect.getsource(app_module._dorong_vonis)
    assert "_cache_get" in src
    assert "_build_screener_vonis" not in src
    assert "async_download_many" not in src


def test_dorong_vonis_terpasang_di_loop_siaran():
    """Pendorong yang tidak pernah dipanggil adalah fitur yang tidak ada.
    Sudah pernah terjadi di proyek ini: komentar mengklaim penjagaan yang
    tak pernah dipasang."""
    src = inspect.getsource(app_module._wa_broadcast_loop)
    assert "_dorong_vonis()" in src
    # Dibungkus try sendiri -- satu yang gagal tidak boleh ikut
    # membatalkan pendorong lain di loop yang sama.
    assert "dorong vonis" in src


def test_dorong_vonis_menyaring_saham_sepi():
    """Kabar tentang saham bernilai transaksi puluhan juta sehari tidak
    bisa ditindaklanjuti -- pembacanya akan menggerakkan harganya
    sendiri. Dan angka yang dikutip di pesannya diukur pada saham
    likuid."""
    src = inspect.getsource(app_module._dorong_vonis)
    assert "WA_DORONG_VONIS_LIKUID" in src
    assert 'x.get("likuid")' in src


def test_pesan_dorong_vonis_menyebut_yang_bertahan_terpisah():
    items = [_it("AAAA", "BELI KUAT", setara=True),
             _it("BBBB", "BELI", setara=False)]
    teks = app_module._wa_fmt_dorong_vonis(items, UKURAN)
    assert "AAAA" in teks and "BBBB" in teks
    assert "Bertahan 2 hari" in teks
    # Desimal KOMA, bukan titik -- longgar ("titik atau koma") akan
    # membiarkan satu pesan menulis angka bergaya sistem lain.
    assert "+4,59%" in teks
    assert "4.59" not in teks
    assert "Bukan nasihat keuangan" in teks
    # Hanya saham yang DIBERIKAN yang muncul -- bukan seluruh payload.
    assert "CCCC" not in teks


def test_pesan_dorong_vonis_menyebut_batas_likuiditas():
    """Penyaring yang tidak terlihat itu penyaring yang menyesatkan:
    pembaca akan menyimpulkan tidak ada sinyal, padahal ada yang disaring."""
    teks = app_module._wa_fmt_dorong_vonis([_it()], UKURAN)
    if app_module.WA_DORONG_VONIS_LIKUID:
        assert "likuid" in teks.lower()


# ---------------------------------------------------------------------------
# Panduan Audit Sinyal: angkanya harus sama dengan kodenya
# ---------------------------------------------------------------------------

def _panduan_audit() -> str:
    js = open("web/static/app.js", encoding="utf-8").read()
    i = js.index("{id:'audit',judul:'Membaca Audit Sinyal'")
    j = js.index("{id:'percaya'", i)
    return js[i:j]


def test_panduan_audit_ada_di_edukasi():
    p = _panduan_audit()
    assert "langkah:[" in p and "catatan:" in p


def test_batas_kadaluarsa_di_panduan_sama_dengan_kodenya():
    """Angka di panduan yang menyimpang dari kodenya lebih buruk daripada
    tidak ada panduan: pembaca memverifikasi aplikasinya memakai panduan,
    lalu menyimpulkan aplikasinya rusak."""
    from core.signal_history import MAX_HOLD_DAYS
    assert MAX_HOLD_DAYS == 20
    assert f"{MAX_HOLD_DAYS} hari bursa" in _panduan_audit()


def test_panduan_menjelaskan_tangga_stop():
    """Label "Kena SL" yang hasilnya hijau adalah hal paling mudah
    disalahbaca di halaman itu -- dan tanpa penjelasan ia terbaca seperti
    cacat data."""
    p = _panduan_audit()
    assert "Untung Terkunci" in p and "Tutup Impas" in p
    assert "impas" in p and "TP1" in p


def test_panduan_menjelaskan_status_yang_bukan_menang_kalah():
    p = _panduan_audit()
    assert "Kadaluarsa" in p and "Entry Tidak Tercapai" in p
    assert "tidak dihitung menang" in p.replace("<b>", "").replace("</b>", "")


def test_panduan_menolak_menyebut_total_return_sbg_return_portofolio():
    """Klaim ini sudah dijaga di layar; panduannya tidak boleh
    melonggarkannya kembali."""
    p = _panduan_audit()
    assert "BUKAN return portofolio" in p or "BUKAN</b> return portofolio" in p
    assert "bunga berbunga" in p or "compounding" in p


def test_panduan_menyebut_asimetri_entry_vs_tp_sl():
    """Entry dinilai dari low intraday, TP/SL dari harga penutupan.
    Asimetri ini nyata di core/signal_history.py dan mengubah arti
    seluruh angka di halaman itu."""
    p = _panduan_audit()
    assert "penutupan" in p and "intraday" in p
    src = inspect.getsource(__import__("core.signal_history",
                                       fromlist=["audit_open_signals"])
                            .audit_open_signals)
    # Yang diklaim panduan: SL dinilai dari `price`, bukan dari low harian.
    assert "price <= sl_price" in src or "price >= sl_price" in src


def test_panduan_menyebut_biaya_tidak_diikutkan():
    """Tanpa ini pembaca akan mengharapkan hasil nyatanya sama dengan
    angka di halaman itu, lalu menyimpulkan ada yang bohong."""
    p = _panduan_audit()
    assert "biaya broker" in p
    assert "aksi korporasi" in p or "stock split" in p


# ---------------------------------------------------------------------------
# Satu unduhan universe dipakai bersama
# ---------------------------------------------------------------------------

def test_dua_pemindai_tidak_mengunduh_universe_dua_kali():
    """BUG YANG DICEGAH: _build_divergence dan _build_screener_vonis
    sama-sama memanggil async_download_many(load_tickers(), period="1y")
    -- parameter identik, data identik -- dan async_download_many tidak
    punya cache. Tanpa pembagian, pemanas menembak Yahoo DUA KALI untuk
    793 emiten tiap putaran: beban dua kali lipat, nol manfaat. Dan kali
    ini sumber bebannya pemanas sendiri, bukan pengunjung."""
    for f in (app_module._build_divergence, app_module._build_screener_vonis):
        src = inspect.getsource(f)
        assert "_universe_1y()" in src, f.__name__
        assert "async_download_many" not in src, f.__name__


def test_universe_1y_memo_mencegah_unduhan_kembar(monkeypatch):
    """Dikunci lewat PERILAKU: tes yang cuma membaca sumber kode akan
    tetap hijau kalau memonya dilepas."""
    import core.async_yf as ay
    import core.stock_data as sd

    panggil = []

    async def _unduh(tickers, **kw):
        panggil.append(kw)
        return {"AAAA.JK": object()}

    monkeypatch.setattr(ay, "async_download_many", _unduh)
    monkeypatch.setattr(sd, "load_tickers", lambda *a, **k: ["AAAA.JK"])
    monkeypatch.setattr(app_module, "_UNDUH_UNIVERSE", None)

    async def _dua_kali():
        a = await app_module._universe_1y()
        b = await app_module._universe_1y()
        return a, b

    a, b = asyncio.run(_dua_kali())
    assert a is b
    assert len(panggil) == 1, f"diunduh {len(panggil)} kali, harusnya 1"
    assert panggil[0]["period"] == "1y"


def test_hasil_kosong_tidak_di_memo(monkeypatch):
    """Yahoo sedang menolak bukan alasan memaksa pemindai berikutnya ikut
    kosong selama 15 menit."""
    import core.async_yf as ay
    import core.stock_data as sd

    n = []

    async def _kosong(tickers, **kw):
        n.append(1)
        return {}

    monkeypatch.setattr(ay, "async_download_many", _kosong)
    monkeypatch.setattr(sd, "load_tickers", lambda *a, **k: ["AAAA.JK"])
    monkeypatch.setattr(app_module, "_UNDUH_UNIVERSE", None)

    async def _dua_kali():
        await app_module._universe_1y()
        await app_module._universe_1y()

    asyncio.run(_dua_kali())
    assert len(n) == 2, "hasil kosong ikut di-memo"


def test_universe_1y_dikunci_terhadap_pemanggil_bersamaan():
    """Pemanas memang memanggilnya berurutan, tapi mengandalkan urutan itu
    berarti fitur ini pecah diam-diam begitu ada pemanggil ketiga."""
    src = inspect.getsource(app_module._universe_1y)
    assert "_unduh_universe_lock" in src
    assert isinstance(app_module._unduh_universe_lock, asyncio.Lock)


# ---------------------------------------------------------------------------
# Urutan pemanas
# ---------------------------------------------------------------------------

def test_panel_dihangatkan_sebelum_dataset_perintah_bot():
    """GEJALA NYATA: penulis membuka tab Vonis sesudah deploy dan cuma
    menemukan "sedang disiapkan". Bukan rusak -- antre di belakang
    foreign_flow scope 'all' yang sendirian makan 69 detik, padahal 'all'
    itu dataset untuk perintah `smartmoney` di bot, bukan panel yang
    sedang ditatap orang."""
    src = inspect.getsource(app_module._warm_shared_caches)
    assert src.index("_SCREENER_VONIS_KEY") < src.index('foreign_flow:{scope}')
    assert src.index("_DIVERGENCE_CACHE_KEY") < src.index('foreign_flow:{scope}')


def test_vonis_dan_divergence_tetap_bersebelahan():
    """Keduanya berbagi SATU unduhan universe lewat _universe_1y(), yang
    memonya cuma 15 menit. Menyelipkan pekerjaan panjang di antaranya
    membuat universe 793 emiten diunduh dua kali lagi -- persis masalah
    yang sudah diperbaiki sekali."""
    src = inspect.getsource(app_module._warm_shared_caches)
    i_v = src.index("_single_flight(_SCREENER_VONIS_KEY")
    i_d = src.index("_single_flight(_DIVERGENCE_CACHE_KEY")
    antara = src[min(i_v, i_d):max(i_v, i_d)]
    # Tidak ada pemanggilan pemanas LAIN di antara keduanya.
    for lain in ("_build_foreign_flow", "_berita_pasar", "screenerpro(",
                 "screener_harmonic(", "_build_universe"):
        assert lain not in antara, f"{lain} menyelip di antara vonis & divergence"


def test_layar_memuat_ulang_sendiri_saat_cache_dingin():
    """Pemanas berjalan berurutan, jadi sesudah server dimulai ulang panel
    ini memang kosong beberapa menit. Tanpa muat-ulang otomatis, keadaan
    yang NORMAL terasa seperti kerusakan."""
    js = open("web/static/app.js", encoding="utf-8").read()
    i = js.index("async function loadVonis(")
    blok = js[i:i + 4000]
    assert "_VONIS_COBA_MAKS" in blok
    assert "setTimeout(" in blok
    # Dibatasi, bukan memeriksa selamanya.
    assert "nyerah" in blok
    # Berhenti kalau tabnya sudah ditinggalkan.
    assert "scrMode==='vonis'" in blok
    # Timer lama dibatalkan supaya tidak menumpuk.
    assert "clearTimeout(_vonisTimer)" in blok
