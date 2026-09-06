"""Sumber sinyal ke-5: Minervini x Harmonic.

Teorinya membagi tugas dengan tegas: SELEKSI dari Minervini (trend template),
ENTRY/SL/TP dari geometri pola harmonic. Yang diuji di sini justru pembagian
itu -- kalau salah satu sisinya bocor (mis. entry jatuh kembali ke ATR
generik, atau saham tanpa pola ikut tercatat), yang tersisa bukan teori baru
melainkan salinan teori lama dengan nama berbeda, dan win rate-nya tidak
akan berarti apa-apa saat dibandingkan.
"""
import asyncio

import pytest


@pytest.fixture
def db_bersih(monkeypatch):
    """Tabel sinyal kosong + gate jam bursa dibuka.

    _is_bursa_weekend/_is_bursa_trading_hours di-patch dengan alasan yang sama
    seperti fixture clean_signal_db yang sudah ada: tanpa itu, seluruh berkas
    ini gagal kalau `pytest` kebetulan dijalankan malam hari atau akhir pekan
    -- kegagalan yang tidak mengatakan apa pun tentang kodenya.
    """
    import core.signal_history as sh
    from core.database import get_db

    sh._ensure_table()
    with get_db() as conn:
        conn.execute("DELETE FROM signal_history")
    monkeypatch.setattr(sh, "_is_bursa_weekend", lambda: False)
    monkeypatch.setattr(sh, "_is_bursa_trading_hours", lambda: True)
    yield
    with get_db() as conn:
        conn.execute("DELETE FROM signal_history")


def _kandidat(**ubah):
    """Item siap-catat: Minervini lolos, pola harmonic punya rencana."""
    dasar = {
        "kode": "AAAA", "pola": "Bat",
        "mvh_entry": 1000.0, "mvh_sl": 940.0,
        "mvh_tp1": 1080.0, "mvh_tp2": 1150.0, "mvh_tp3": 1260.0,
        "mvh_status": "di area", "mv_skor": 78.0,
        "recommendation": "Minervini 7/8",
    }
    dasar.update(ubah)
    return dasar


def test_level_diambil_dari_pola_bukan_dihitung_ulang(db_bersih):
    """Inti teorinya. Kalau SL/TP dihitung ulang di recorder, yang diaudit
    bukan lagi garis yang digambar polanya -- dan perbandingan dengan teori
    lain jadi membandingkan sesuatu yang tidak pernah dijalankan."""
    from core.signal_history import record_minervini_harmonic_signals

    hasil = asyncio.run(record_minervini_harmonic_signals([_kandidat()]))
    assert len(hasil) == 1
    s = hasil[0]
    assert s["entry_price"] == 1000.0
    assert s["sl_price"] == pytest.approx(940.0, abs=0.5)
    assert s["tp_price"] == pytest.approx(1080.0, abs=0.5)
    assert s["source"] == "MINERVINI_HARMONIC"
    assert "Bat" in s["pattern"] and "Minervini" in s["pattern"]


def test_harga_masih_di_area_pola_langsung_open_selebihnya_menunggu(db_bersih):
    """Membuat semuanya OPEN akan mencatat entry di harga yang bukan harga
    teorinya; membuat semuanya PENDING_ENTRY akan melewatkan pola yang justru
    sedang berada tepat di titiknya."""
    from core.signal_history import record_minervini_harmonic_signals

    di_area = asyncio.run(record_minervini_harmonic_signals(
        [_kandidat(mvh_status="di area")]))
    assert di_area[0]["status"] == "OPEN"
    assert di_area[0]["entry_mode"] == "AGRESIF"

    menunggu = asyncio.run(record_minervini_harmonic_signals(
        [_kandidat(kode="BBBB", mvh_status="belum sampai")]))
    assert menunggu[0]["status"] == "PENDING_ENTRY"
    assert menunggu[0]["entry_mode"] == "AREA_AMAN"


def test_lantai_sl_tetap_berlaku_walau_entry_pasar_memepetkannya(db_bersih):
    """Entry di harga pasar bisa jatuh sangat dekat ke SL polanya. Lantai
    3% yang berlaku di seluruh aplikasi tidak boleh bocor lewat pintu ini --
    keluhan "kena SL malah terbang" lahir persis dari SL sedekat itu."""
    from core.signal_history import record_minervini_harmonic_signals
    from core.trading_plan import MIN_SL_PCT

    async def _harga_pasar(kode):
        return 955.0  # cuma 1,6% di atas SL 940

    hasil = asyncio.run(record_minervini_harmonic_signals(
        [_kandidat()], price_lookup=_harga_pasar))
    assert hasil[0]["sl_pct"] >= MIN_SL_PCT


def test_satu_kode_tidak_menumpuk_tapi_boleh_koeksis_dengan_teori_lain(db_bersih):
    """Dedup ter-scope per source. Kalau ia mengunci lintas-source, saham yang
    sudah jadi Top Pick tidak akan pernah tercatat di teori ini -- dan
    perbandingan head-to-head yang jadi alasan sumber ini dibuat langsung
    kehilangan sampelnya."""
    from core.database import get_db
    from core.signal_history import record_minervini_harmonic_signals

    with get_db() as conn:
        conn.execute("""
            INSERT INTO signal_history (kode, entry_price, tp_pct, sl_pct, source,
                                        recorded_at, status, direction)
            VALUES ('AAAA', 900, 5, 3, 'TOP_PICK', datetime('now','localtime'),
                    'OPEN', 'BUY')
        """)

    pertama = asyncio.run(record_minervini_harmonic_signals([_kandidat()]))
    assert len(pertama) == 1, "terkunci oleh sinyal Top Pick di saham yang sama"

    kedua = asyncio.run(record_minervini_harmonic_signals([_kandidat()]))
    assert kedua == [], "sinyal kedua menumpuk untuk kode yang sama"


def test_entry_yang_sudah_melewati_target_pertama_tidak_dicatat(db_bersih):
    """Kalau harga pasar sudah di atas TP1, tidak ada trade yang tersisa untuk
    dicatat. Mencatatnya akan melahirkan sinyal yang langsung 'menang' tanpa
    pernah ada peluang masuk -- win rate naik, uangnya tidak."""
    from core.signal_history import record_minervini_harmonic_signals

    async def _sudah_terbang(kode):
        return 1200.0  # di atas TP1 1080

    hasil = asyncio.run(record_minervini_harmonic_signals(
        [_kandidat()], price_lookup=_sudah_terbang))
    assert hasil == []


def test_menolak_item_yang_arah_levelnya_tidak_masuk_akal(db_bersih):
    """BUY-only: SL wajib di bawah entry, TP1 di atasnya. Item yang terbalik
    berarti ada yang salah di hulu, dan menyimpannya diam-diam akan mencemari
    statistik teori ini dengan trade yang tidak pernah bisa dijalankan."""
    from core.signal_history import record_minervini_harmonic_signals

    assert asyncio.run(record_minervini_harmonic_signals(
        [_kandidat(mvh_sl=1100.0)])) == []
    assert asyncio.run(record_minervini_harmonic_signals(
        [_kandidat(kode="CCCC", mvh_tp1=900.0)])) == []


def test_tidak_mencatat_di_luar_jam_bursa(db_bersih, monkeypatch):
    """Gate yang sama dengan seluruh recorder lain: entry yang dicatat memakai
    harga di luar jam bursa adalah harga yang tidak pernah bisa dieksekusi."""
    import core.signal_history as sh

    monkeypatch.setattr(sh, "_is_bursa_trading_hours", lambda: False)
    assert asyncio.run(sh.record_minervini_harmonic_signals([_kandidat()])) == []
