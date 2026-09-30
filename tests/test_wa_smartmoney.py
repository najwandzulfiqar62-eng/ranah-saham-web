"""Perintah `smartmoney` di bot WhatsApp.

Fitur ini punya satu risiko yang lebih besar daripada bug teknis: NAMANYA
MENJANJIKAN LEBIH BANYAK DARIPADA YANG DIUKUR DATANYA. Yang dihitung adalah
volume yang tidak biasa dibandingkan rata-rata 20 harinya. Siapa yang membeli
-- asing, institusi, atau satu orang kaya yang sedang iseng -- tidak ada di
satu pun sumber data yang dipakai aplikasi ini.

Orang bertaruh uang atas pesan bot ini, dan pesannya tiba di WhatsApp tanpa
konteks layar, tanpa legenda, tanpa tooltip. Karena itu syarat dan
keterbatasannya diuji di sini sama ketatnya dengan angkanya.
"""
import pytest

# Fixture `wa_bersih` (DB akses kosong + secret bot + jeda per-nomor direset)
# tinggal di test_wa_bot.py, bukan conftest. Diimpor supaya pytest melihatnya
# di modul ini juga -- menyalinnya akan membuat dua penyiapan yang bisa
# berbeda diam-diam.
from tests.test_wa_bot import wa_bersih  # noqa: F401

SECRET = "rahasia-wa-bot-khusus-pytest"


def _contoh(**ubah) -> dict:
    dasar = {
        "total_scan": 250, "net_score": 1,
        "akumulasi": [{"kode": "UNTR", "pola": "Akumulasi", "harga": 26500,
                       "chg1": 4.27, "chg5": 6.1, "vol_ratio": 3.2, "rsi": 61.2,
                       "likuiditas": "Sangat Likuid", "grup": "Astra",
                       "hari_lalu": 0, "vol_ratio_percentile": 100.0}],
        "distribusi": [{"kode": "CARE", "pola": "Distribusi", "harga": 129,
                        "chg1": -3.06, "chg5": -8.2, "vol_ratio": 8.67,
                        "rsi": 31.0, "likuiditas": "Likuid",
                        "grup": "Independen", "hari_lalu": 4,
                        "vol_ratio_percentile": 100.0}],
    }
    dasar.update(ubah)
    return dasar


# ---------------------------------------------------------------------------
# Kejujuran isi pesannya
# ---------------------------------------------------------------------------

def test_pesan_menyangkal_klaim_yang_ada_di_namanya():
    """"Smart Money" terdengar seperti bot tahu siapa yang membeli. Ia tidak
    tahu, dan pesannya harus mengatakan itu -- di WhatsApp tidak ada legenda
    atau tooltip yang bisa meluruskannya belakangan."""
    from web.app import _wa_fmt_smartmoney

    teks = _wa_fmt_smartmoney(_contoh())
    assert "bukan aliran dana asing" in teks
    assert "siapa yang membeli tidak ada di data ini" in teks


def test_arah_disebut_sebagai_kesimpulan_bukan_pengetahuan():
    """Volume besar sendiri tidak berarah. Yang membedakan "terkumpul" dari
    "dilepas" cuma gerak harganya -- itu kesimpulan, dan harus terbaca
    sebagai kesimpulan."""
    from web.app import _wa_fmt_smartmoney

    teks = _wa_fmt_smartmoney(_contoh())
    assert "bisa juga berarti dilepas" in teks
    assert "bukan diketahui" in teks


# ---------------------------------------------------------------------------
# Umur anomali -- yang basi tidak boleh terbaca seperti yang baru
# ---------------------------------------------------------------------------

def test_anomali_lama_diberi_tanda_umur():
    """Anomali empat hari lalu dan anomali hari ini menuntut tindakan yang
    berbeda, tapi keduanya muncul di daftar yang sama. Tanpa penanda umur,
    yang basi terbaca seperti yang baru.

    Penanda ini SENGAJA selamat dari pemadatan baris. Waktu tiap saham
    diringkas dari tiga baris jadi satu, kolom lain memang dibuang -- tapi
    yang ini tidak, karena ia mengubah keputusan, bukan cuma menambah
    keterangan."""
    from web.app import _wa_fmt_smartmoney

    teks = _wa_fmt_smartmoney(_contoh())
    assert "4h lalu" in teks


def test_anomali_hari_ini_TIDAK_diberi_tanda_umur():
    """"0 hari lalu" di tiap baris cuma menambah teks tanpa menambah arti,
    dan justru membuat penanda yang sungguhan jadi kurang menonjol."""
    from web.app import _wa_fmt_smartmoney

    teks = _wa_fmt_smartmoney(_contoh())
    assert "0 hari lalu" not in teks


# ---------------------------------------------------------------------------
# Satu angka, satu kata -- bot dan layar tidak boleh bercerita beda
# ---------------------------------------------------------------------------

def test_daftar_penuh_tetap_muat_tanpa_jadi_dinding_teks():
    """DUA SYARAT YANG TARIK-MENARIK, dan keduanya harus dipenuhi sekaligus.

    Syarat pertama: tidak satu pun saham boleh hilang. Memangkas daftar
    pernah membuat saham yang justru dicari orang lenyap dari balasan.

    Syarat kedua: balasannya harus terbaca di WhatsApp. Versi tiga-baris
    menghasilkan 76 baris / 4.215 karakter untuk 22 saham -- enam kali lipat
    batas "Baca selengkapnya", yang artinya orang melihat lima nama pertama
    lalu menutupnya.

    Jalan keluarnya bukan memangkas DAFTAR, melainkan memangkas KOLOM: chg5,
    RSI, likuiditas, grup, dan peringkat persentil pindah ke balasan `KODE`.
    Batas 2.500 di sini bukan angka keramat -- ia cuma jauh di bawah 4.215
    dan jauh di atas bentuk sekarang (1.738), jadi ia menangkap kemunduran
    tanpa mengunci tata letaknya."""
    from web.app import _wa_fmt_smartmoney

    banyak = [{"kode": f"AA{i:02d}", "pola": "Akumulasi Agresif", "harga": 26500,
               "chg1": 12.34, "chg5": 20.0, "vol_ratio": 4.56, "rsi": 71.0,
               "likuiditas": "Sangat Likuid", "grup": "Barito Pacific",
               "hari_lalu": 0, "vol_ratio_percentile": 92.0} for i in range(20)]
    teks = _wa_fmt_smartmoney(_contoh(akumulasi=banyak))

    for i in range(20):
        assert f"AA{i:02d}" in teks, "saham hilang dari daftar"
    assert "CARE" in teks, "distribusi ikut hilang"
    assert len(teks) < 2500, f"kembali jadi dinding teks ({len(teks)} karakter)"


def test_kolom_yang_dipadatkan_disebutkan_perginya_ke_mana():
    """Kolom yang hilang tanpa penjelasan terbaca seperti fitur yang rusak.
    Penutupnya harus menyebut bahwa RSI dkk masih ada, satu ketikan jauhnya."""
    from web.app import _wa_fmt_smartmoney

    teks = _wa_fmt_smartmoney(_contoh())
    assert "RSI" in teks and "Ketik kode emitennya" in teks


# ---------------------------------------------------------------------------
# Tahan data cacat -- pelajaran 24 Sep 2026
# ---------------------------------------------------------------------------

def test_tidak_ada_anomali_dijawab_jujur_bukan_error():
    """Hari sepi itu hasil yang sah, bukan kerusakan. Menjawabnya dengan
    error membuat orang mengira botnya rusak lalu mengulang terus."""
    from web.app import _wa_fmt_smartmoney

    teks = _wa_fmt_smartmoney({"total_scan": 250, "akumulasi": [], "distribusi": []})
    assert "Tidak ada anomali" in teks
    assert "wajar" in teks


@pytest.mark.parametrize("rusak", [None, [], "bukan dict", 0])
def test_payload_rusak_tidak_meledak(rusak):
    """Perintah bot tidak boleh melempar. Yang dilempar di sini berubah jadi
    diam di WhatsApp, dan diam adalah kegagalan yang paling membingungkan."""
    from web.app import _wa_fmt_smartmoney

    assert isinstance(_wa_fmt_smartmoney(rusak), str)


def test_field_yang_hilang_tidak_meledak():
    """Persis kelas bug yang menjatuhkan halaman Pemegang Saham 24 Sep 2026:
    satu field bernilai None, seluruh panel mati. Baris seadanya jauh lebih
    baik daripada perintah yang tidak menjawab."""
    from web.app import _wa_fmt_smartmoney

    teks = _wa_fmt_smartmoney({
        "total_scan": 250,
        "akumulasi": [{"kode": "BBCA", "pola": "Akumulasi", "harga": 9000,
                       "vol_ratio": 2.1}],   # chg1/chg5/rsi/likuiditas TIDAK ADA
        "distribusi": [],
    })
    assert "BBCA" in teks


# ---------------------------------------------------------------------------
# Ujung ke ujung lewat endpoint bot
# ---------------------------------------------------------------------------

def _kirim(client, teks, nomor="6281234567890"):
    return client.post("/api/wa/command",
                       json={"from": f"{nomor}@s.whatsapp.net", "text": teks},
                       headers={"Authorization": f"Bearer {SECRET}"})


def _cache_palsu(monkeypatch, isi=None, stale=None):
    """Ganti cache HANYA untuk kunci foreign_flow:all.

    Mengganti _cache_get seluruhnya akan ikut mengubah jalur lain di dalam
    satu request (batas laju, sesi), sehingga ujinya lulus/gagal karena
    sebab yang tidak sedang diuji.
    """
    import web.app as app_module

    monkeypatch.setattr(app_module, "_cache_get",
                        lambda k: isi if k == "foreign_flow:all" else None)
    monkeypatch.setattr(app_module, "_cache_get_stale",
                        lambda k: stale if k == "foreign_flow:all" else None)


@pytest.mark.parametrize("perintah", ["smartmoney", "sm", "bandar", "akumulasi"])
def test_semua_sebutan_menjawab(client, wa_bersih, monkeypatch, perintah):
    """`bandar` itu kata yang benar-benar dipakai orang untuk konsep ini.
    Perintah yang hampir benar dijawab dengan diam adalah bentuk kegagalan
    yang paling membingungkan -- orang tidak tahu botnya mati, pesannya tidak
    sampai, atau ketikannya salah, dan ketiganya menuntut tindakan berbeda."""
    import web.app as app_module
    from tests.test_wa_bot import _daftarkan_approved

    _cache_palsu(monkeypatch, isi=_contoh())
    _daftarkan_approved()
    app_module._wa_last_reply.clear()

    balasan = _kirim(client, perintah).json()["reply"]
    assert "UNTR" in balasan and "CARE" in balasan


def test_memindai_SELURUH_idx_bukan_yang_likuid_saja(client, wa_bersih, monkeypatch):
    """Keluhan nyata 30 Sep 2026: bot melaporkan 2 anomali sementara layar
    menunjukkan 22. Sebabnya bot memakai scope 'medium' -- yang ternyata
    berisi 178 emiten, bukan 250 seperti nama konstantanya (LIQUID_250).

    Yang dikunci di sini KUNCI CACHE-nya, karena itulah yang menentukan
    universe mana yang dibaca. Memeriksa jumlah hasil tidak akan menangkap
    ini: 2 anomali juga jawaban yang sah untuk hari yang sepi."""
    import web.app as app_module
    from tests.test_wa_bot import _daftarkan_approved

    diminta = []
    monkeypatch.setattr(app_module, "_cache_get",
                        lambda k: (diminta.append(k), _contoh())[1]
                        if k == "foreign_flow:all" else None)
    monkeypatch.setattr(app_module, "_cache_get_stale", lambda k: None)
    _daftarkan_approved()
    app_module._wa_last_reply.clear()

    _kirim(client, "smartmoney")
    assert "foreign_flow:all" in diminta, "bot masih membaca universe sempit"


# ---------------------------------------------------------------------------
# Cache dingin -- 69 detik diam di WhatsApp terbaca sebagai "botnya mati"
# ---------------------------------------------------------------------------

def test_cache_dingin_dijawab_seketika_bukan_ditunggu(client, wa_bersih, monkeypatch):
    """Sekali pindai 793 emiten makan 69 detik (diukur 30 Sep 2026). Menahan
    balasan selama itu membuat orang mengira botnya mati lalu mengirim ulang
    berkali-kali -- persis kebiasaan yang sudah terlihat di sesi sebelumnya."""
    import web.app as app_module
    from tests.test_wa_bot import _daftarkan_approved

    dipanggil = []

    async def _bangun_palsu(scope, cache_key):
        dipanggil.append(scope)
        return _contoh()

    _cache_palsu(monkeypatch)                      # dingin, tanpa salinan basi
    monkeypatch.setattr(app_module, "_build_foreign_flow", _bangun_palsu)
    _daftarkan_approved()
    app_module._wa_last_reply.clear()

    balasan = _kirim(client, "smartmoney").json()["reply"]
    assert "sedang disiapkan" in balasan
    assert "sebentar" in balasan


def test_cache_dingin_menyalakan_pemindaian_di_latar(monkeypatch):
    """Menjawab "sedang disiapkan" tanpa benar-benar menyiapkan apa pun akan
    membuat perintahnya tidak pernah berhasil, berapa kali pun diulang.

    Diuji lewat _wa_smartmoney() LANGSUNG, bukan lewat TestClient. Lewat
    TestClient, tugas latarnya dijadwalkan pada event loop yang sudah
    ditutup saat request selesai, sehingga ujinya tidak bisa membedakan
    "tugasnya jalan" dari "tugasnya tidak pernah dijalankan" -- dan uji yang
    tidak bisa gagal lebih buruk daripada tidak ada uji sama sekali.
    """
    import asyncio

    import web.app as app_module

    dipanggil = []

    async def _bangun_palsu(scope, cache_key):
        dipanggil.append(scope)
        return _contoh()

    _cache_palsu(monkeypatch)
    monkeypatch.setattr(app_module, "_build_foreign_flow", _bangun_palsu)

    async def jalan():
        balasan = await app_module._wa_smartmoney()
        await asyncio.sleep(0.05)      # beri tugas latarnya giliran jalan
        return balasan

    balasan = asyncio.run(jalan())
    assert "sedang disiapkan" in balasan
    assert dipanggil == ["all"], "pemindaian latar tidak jalan atau salah universe"


def test_pemindaian_latar_yang_gagal_tidak_menjatuhkan_perintahnya(monkeypatch):
    """Yahoo menolak saat pemindaian latar berjalan tidak boleh berubah jadi
    pengecualian yang tak tertangkap -- balasannya sudah dikirim, dan
    kegagalannya harus berhenti di log."""
    import asyncio

    import web.app as app_module

    async def _bangun_gagal(scope, cache_key):
        raise RuntimeError("YFRateLimitError")

    _cache_palsu(monkeypatch)
    monkeypatch.setattr(app_module, "_build_foreign_flow", _bangun_gagal)

    async def jalan():
        balasan = await app_module._wa_smartmoney()
        await asyncio.sleep(0.05)
        return balasan

    assert "sedang disiapkan" in asyncio.run(jalan())


def test_cache_dingin_menyajikan_data_lama_kalau_ada(client, wa_bersih, monkeypatch):
    """Hasil pemindaian kemarin jauh lebih berguna daripada "sedang
    disiapkan" -- asal dikatakan bahwa ia hasil kemarin."""
    import web.app as app_module
    from tests.test_wa_bot import _daftarkan_approved

    async def _bangun_palsu(scope, cache_key):
        return _contoh()

    _cache_palsu(monkeypatch, stale=_contoh())
    monkeypatch.setattr(app_module, "_build_foreign_flow", _bangun_palsu)
    _daftarkan_approved()
    app_module._wa_last_reply.clear()

    balasan = _kirim(client, "smartmoney").json()["reply"]
    assert "UNTR" in balasan, "data lama yang berguna malah dibuang"
    assert "belum diperbarui" in balasan, "data lama disamarkan jadi data hari ini"


def test_data_basi_ditandai_di_dalam_pesannya_sendiri():
    """Di web ada lencana untuk ini. Di WhatsApp tidak ada tempat lain untuk
    mengatakannya selain di dalam pesannya."""
    from web.app import _wa_fmt_smartmoney

    teks = _wa_fmt_smartmoney({**_contoh(), "basi": True})
    assert "belum diperbarui" in teks


def test_tercantum_di_menu_bantuan():
    """Fitur yang tidak disebut di `bantuan` sama saja dengan tidak ada:
    tidak ada yang bisa menebak kata kuncinya."""
    from web.app import _WA_BANTUAN

    assert "smartmoney" in _WA_BANTUAN and "bandar" in _WA_BANTUAN
