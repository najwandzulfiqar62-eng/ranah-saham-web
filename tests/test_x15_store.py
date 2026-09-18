"""Riwayat filing X-15 harus BERTAHAN, bukan sekadar ter-cache.

Keluhan yang melahirkan berkas ini: "kok riwayat pemegang saham hilang,
kemarin banyak". Tidak ada yang menghapusnya -- riwayat itu memang tidak
pernah disimpan. Seluruhnya hidup di cache Redis `x15raw:{n}` berumur 24
jam; selama idx.co.id bisa dihubungi tiap hari ia terus terisi ulang dan
TERLIHAT seperti arsip, lalu menguap begitu sumbernya menolak.

Cache menjawab "supaya tidak mengambil ulang", bukan "supaya tidak hilang".
"""
import pytest


@pytest.fixture
def store():
    from core.database import get_db

    import core.x15_store as st
    st.ensure_x15_tables()
    with get_db() as conn:
        conn.execute("DELETE FROM x15_filing")
    yield st
    with get_db() as conn:
        conn.execute("DELETE FROM x15_filing")


def _filing(pdf, kode="BBCA", tanggal="2026-09-10", pct=6.0):
    return {"kode": kode, "tanggal": tanggal, "nama": "Budi Santoso",
            "perusahaan": None, "jabatan": "Direktur Utama",
            "pct_sebelum": 5.0, "pct_setelah": pct, "perubahan": pct - 5.0,
            "jenis": "beli", "pengendali": True, "pdf_url": pdf}


def test_filing_tersimpan_dan_terbaca_lagi(store):
    assert store.simpan_filing([_filing("http://idx/a.pdf")]) == 1
    hasil = store.ambil_untuk_kode("bbca", "2026-01-01")
    assert len(hasil) == 1
    assert hasil[0]["kode"] == "BBCA"
    assert hasil[0]["pengendali"] is True, "boolean tidak pulih dari SQLite"


def test_filing_yang_sama_tidak_menumpuk(store):
    """Riwayat 90 hari diambil ulang tiap kali ada yang membuka halamannya.
    Kalau tiap pengambilan menambah baris, angka perubahan kepemilikan akan
    terhitung berlipat -- rusaknya diam-diam, bukan berupa error."""
    for _ in range(5):
        store.simpan_filing([_filing("http://idx/a.pdf")])
    assert len(store.ambil_untuk_kode("BBCA", "2026-01-01")) == 1


def test_satu_orang_boleh_melapor_dua_kali_di_hari_yang_sama(store):
    """Yang membuat sebuah filing unik adalah PDF-nya, bukan isinya. Dua
    laporan di hari yang sama dengan angka yang kebetulan sama itu dua
    filing, bukan satu yang terduplikasi."""
    store.simpan_filing([_filing("http://idx/a.pdf"), _filing("http://idx/b.pdf")])
    assert len(store.ambil_untuk_kode("BBCA", "2026-01-01")) == 2


def test_hanya_yang_punya_pdf_dan_kode_disimpan(store):
    """Tanpa URL PDF tidak ada yang menjamin keunikannya, dan barisnya akan
    menumpuk tiap pengambilan."""
    assert store.simpan_filing([
        {"kode": "BBCA", "tanggal": "2026-09-10"},          # tanpa pdf_url
        {"pdf_url": "http://idx/c.pdf", "tanggal": "2026-09-10"},  # tanpa kode
    ]) == 0


def test_rentang_tanggal_dihormati(store):
    store.simpan_filing([_filing("http://idx/lama.pdf", tanggal="2026-01-05"),
                         _filing("http://idx/baru.pdf", tanggal="2026-09-10")])
    hasil = store.ambil_untuk_kode("BBCA", "2026-06-01")
    assert [h["tanggal"] for h in hasil] == ["2026-09-10"]


def test_menyimpan_tidak_pernah_menjatuhkan_pemanggilnya(store, monkeypatch):
    """Menyimpan itu TAMBAHAN, bukan syarat. Kalau ia bisa menjatuhkan
    pengambilan data, satu masalah ditukar dengan yang lebih buruk: fitur
    yang tadinya jalan ikut mati gara-gara lapisan yang seharusnya menolong."""
    import core.x15_store as st

    def _meledak(*a, **k):
        raise RuntimeError("disk penuh")

    monkeypatch.setattr(st, "get_db", _meledak)
    assert st.simpan_filing([_filing("http://idx/z.pdf")]) == 0


def test_ringkasan_menyebut_rentang_yang_dimiliki(store):
    store.simpan_filing([_filing("http://idx/1.pdf", tanggal="2026-07-01"),
                         _filing("http://idx/2.pdf", kode="TLKM", tanggal="2026-09-10")])
    r = store.ringkas()
    assert r["n"] == 2 and r["emiten"] == 2
    assert r["awal"] == "2026-07-01" and r["akhir"] == "2026-09-10"


def test_kunci_cache_x15_memakai_tanggal_bukan_hitungan_hari():
    """x15raw:{days_back} dengan umur 24 jam salah melintasi tengah malam:
    kunci yang ditulis pukul 23.00 masih dianggap sah pukul 01.00 esoknya,
    padahal "5 hari lalu" sudah menunjuk hari kalender yang berbeda. Bukan
    sekadar basi -- filing hari yang KELIRU disajikan sebagai hari yang
    diminta, tanpa ada yang error."""
    import io
    import os

    # Dibaca dari BERKAS, bukan lewat inspect.getsource(app.__fetch...):
    # uji lain menambal fungsi itu dengan tiruan, dan tambalan yang bocor
    # membuat uji ini memeriksa kode tiruan alih-alih kode sungguhan --
    # lalu gagal karena alasan yang sama sekali tidak ada hubungannya.
    akar = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sumber = io.open(os.path.join(akar, "web", "app.py"), encoding="utf-8").read()
    assert 'x15raw:tgl:' in sumber, "kunci cache tidak berbasis tanggal"
    assert 'f"x15raw:{days_back}"' not in sumber, (
        "kunci lama berbasis hitungan hari masih dipakai")
