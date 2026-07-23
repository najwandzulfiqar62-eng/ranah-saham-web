# Test utk build_portfolio (core/risk_management.py) -- fitur "Racik
# Portofolio" (usulan 2026-07-23: "dikasih modal 10jt, web-nya kira-kira
# milih emiten apa sama berapa lot").
# Keputusan user: sizing BERBASIS RISIKO + saham dipilih sendiri oleh user.
# Fokus test: DUA batasan yang harus dipegang bersamaan (risiko per posisi
# DAN modal yang tersedia) serta kejujuran melaporkan saham yang dilewati.
import math

from core.risk_management import build_portfolio, LOT_SIZE


def _c(kode, entry, sl):
    return {"kode": kode, "entry": entry, "stop_loss": sl}


def test_sizing_berbasis_risiko_sl_sempit_dapat_porsi_lebih_besar():
    """Inti metode terpilih: risiko rupiah tiap posisi ~sama, sehingga saham
    ber-SL sempit otomatis dapat lot lebih banyak. Sengaja dipilih angka yang
    TIDAK menyentuh batas konsentrasi, supaya yang diuji di sini murni sifat
    penyamaan risikonya (batas konsentrasi diuji terpisah di bawah)."""
    r = build_portfolio(100_000_000, [
        _c("AAAA", 1000, 980),   # SL 2%
        _c("BBBB", 1000, 900),   # SL 10%
    ], risk_pct=0.5)
    a, b = r["posisi"][0], r["posisi"][1]
    assert not a["dibatasi_konsentrasi"] and not b["dibatasi_konsentrasi"]
    assert a["lot"] > b["lot"]                      # SL sempit -> lot lebih banyak
    # risiko rupiah keduanya mendekati 0,5% modal (500.000), beda < 1 lot risiko
    assert abs(a["risiko_rp"] - b["risiko_rp"]) <= LOT_SIZE * 100
    assert a["risiko_pct_modal"] <= 0.5 and b["risiko_pct_modal"] <= 0.5


def test_risiko_per_posisi_tidak_pernah_melebihi_risk_pct():
    """Pembulatan ke BAWAH: risiko sesungguhnya wajib <= yang diminta."""
    r = build_portfolio(10_000_000, [_c("AAAA", 1337, 1201)], risk_pct=1.0)
    p = r["posisi"][0]
    assert p["risiko_pct_modal"] <= 1.0


def test_total_nilai_tidak_pernah_melebihi_modal():
    """BATASAN KEDUA: sizing berbasis risiko sendiri TIDAK menghormati modal.
    Beberapa saham ber-SL sangat sempit bisa meminta total belanja jauh di
    atas uang yang ada -- harus dipangkas, bukan mengarang uang."""
    # SL 1% + risk 2% -> tiap posisi "minta" ~2x modal kalau tidak dibatasi
    cands = [_c("AAAA", 1000, 990), _c("BBBB", 1000, 990), _c("CCCC", 1000, 990)]
    r = build_portfolio(10_000_000, cands, risk_pct=2.0)
    assert r["total_nilai"] <= r["modal"]
    assert r["sisa_modal"] >= 0
    assert any(p["dipangkas_modal"] for p in r["posisi"])  # ditandai jujur


def test_batas_konsentrasi_cegah_satu_saham_sedot_seluruh_modal():
    """BATASAN KETIGA. Kasus NYATA yang memicu penambahan ini: BBCA ber-SL
    hanya 0,62% -> sizing berbasis risiko murni memberi 15 lot = 97% modal.
    Risiko '1%' itu cuma berlaku kalau SL benar-benar kena di harganya; kalau
    harga LOMPAT melewati stop serapat itu, ruginya jauh lebih besar."""
    r = build_portfolio(10_000_000, [_c("BBCA", 6450, 6410)], risk_pct=1.0, max_pos_pct=40)
    p = r["posisi"][0]
    assert p["nilai"] <= 10_000_000 * 0.40
    assert p["dibatasi_konsentrasi"] is True


def test_batas_konsentrasi_bisa_diatur():
    ketat = build_portfolio(10_000_000, [_c("AAAA", 1000, 995)], risk_pct=1.0, max_pos_pct=20)
    longgar = build_portfolio(10_000_000, [_c("AAAA", 1000, 995)], risk_pct=1.0, max_pos_pct=60)
    assert ketat["posisi"][0]["lot"] < longgar["posisi"][0]["lot"]
    assert ketat["posisi"][0]["nilai"] <= 10_000_000 * 0.20


def test_konsentrasi_tidak_menghukum_posisi_yang_memang_kecil():
    """Posisi yang sudah di bawah batas TIDAK boleh ditandai dibatasi."""
    r = build_portfolio(100_000_000, [_c("AAAA", 1000, 900)], risk_pct=1.0)
    p = r["posisi"][0]
    assert p["dibatasi_konsentrasi"] is False
    assert p["nilai"] < 100_000_000 * 0.40


def test_saham_yang_tidak_kebagian_dilaporkan_dengan_alasan():
    """Saham yang tak muat TIDAK boleh hilang diam-diam."""
    r = build_portfolio(1_000_000, [
        _c("MURAH", 100, 95),
        _c("MAHAL", 90_000, 85_000),   # 1 lot = Rp9jt, modal cuma 1jt
    ], risk_pct=1.0)
    kode_dilewati = [d["kode"] for d in r["dilewati"]]
    assert "MAHAL" in kode_dilewati
    assert "tidak cukup" in next(d["alasan"] for d in r["dilewati"] if d["kode"] == "MAHAL").lower()


def test_tolak_stop_loss_tidak_wajar():
    """SL >= harga (support di atas harga) bukan stop loss beli yang sah."""
    r = build_portfolio(10_000_000, [
        _c("AAAA", 1000, 1000),   # sama dgn harga
        _c("BBBB", 1000, 1200),   # di ATAS harga
        _c("CCCC", 1000, 0),      # tidak ada level
    ], risk_pct=1.0)
    assert r["posisi"] == []
    assert len(r["dilewati"]) == 3
    assert all("stop loss" in d["alasan"].lower() for d in r["dilewati"])


def test_lot_selalu_bulat_dan_lembar_kelipatan_lot():
    r = build_portfolio(50_000_000, [_c("AAAA", 3175, 2950), _c("BBBB", 777, 700)], risk_pct=1.5)
    for p in r["posisi"]:
        assert isinstance(p["lot"], int) and p["lot"] >= 1
        assert p["lembar"] == p["lot"] * LOT_SIZE
        assert math.isclose(p["nilai"], p["lembar"] * p["harga"], rel_tol=1e-6)


def test_ringkasan_total_konsisten():
    r = build_portfolio(20_000_000, [_c("AAAA", 1000, 950), _c("BBBB", 2000, 1900)], risk_pct=1.0)
    assert r["total_nilai"] == sum(p["nilai"] for p in r["posisi"])
    assert r["sisa_modal"] == r["modal"] - r["total_nilai"]
    assert r["total_risiko_rp"] == sum(p["risiko_rp"] for p in r["posisi"])
    assert abs(sum(p["porsi_pct"] for p in r["posisi"]) - 100.0) < 0.5


def test_modal_kecil_tetap_menghasilkan_sesuatu_atau_alasan_jelas():
    """Modal 10jt (contoh persis dari usulan) harus menghasilkan portofolio,
    bukan gagal diam-diam."""
    r = build_portfolio(10_000_000, [
        _c("BBCA", 6525, 6330), _c("TLKM", 2700, 2580), _c("ASII", 5150, 4900),
    ], risk_pct=1.0)
    assert len(r["posisi"]) >= 1
    assert r["total_nilai"] <= 10_000_000
    assert r["terpakai_pct"] <= 100.0


def test_auto_berhenti_di_kuota_saham():
    """Mode otomatis: sistem memilih sendiri, jadi WAJIB ada aturan berhenti --
    tanpa maks_posisi modal terpecah ke belasan posisi mini."""
    cands = [_c(f"S{i:02d}", 1000, 950) for i in range(12)]
    r = build_portfolio(500_000_000, cands, risk_pct=1.0, maks_posisi=5)
    assert len(r["posisi"]) == 5
    sisa_alasan = [d["alasan"] for d in r["dilewati"]]
    assert any("Kuota 5 saham" in a for a in sisa_alasan)


def test_auto_hormati_jatah_risiko_total():
    """Risiko per posisi yang kelihatan kecil tetap MENUMPUK. Dengan jatah
    total 3% dan 1% per posisi, maksimal ~3 posisi yang boleh masuk."""
    cands = [_c(f"S{i:02d}", 1000, 950) for i in range(10)]
    r = build_portfolio(500_000_000, cands, risk_pct=1.0, maks_total_risk_pct=3.0)
    assert r["total_risiko_pct"] <= 3.0
    assert len(r["posisi"]) <= 3
    assert any("risiko total" in d["alasan"] for d in r["dilewati"])


def test_auto_kedua_batas_bekerja_bersama():
    cands = [_c(f"S{i:02d}", 1000, 950) for i in range(20)]
    r = build_portfolio(500_000_000, cands, risk_pct=0.5, maks_posisi=4, maks_total_risk_pct=10.0)
    assert len(r["posisi"]) == 4              # kuota lebih dulu tercapai
    assert r["total_risiko_pct"] <= 10.0


def test_batas_auto_default_mati_untuk_mode_manual():
    """Tanpa argumen batas, perilaku mode pilih-sendiri TIDAK berubah: tak ada
    yang ditolak karena kuota/jatah risiko total. risk_pct 0,5% + SL 5% =>
    tiap posisi ~10% modal, jadi kedelapan-delapannya memang muat (batas MODAL
    tidak ikut campur, supaya yang diuji murni matinya batas otomatis)."""
    cands = [_c(f"S{i:02d}", 1000, 950) for i in range(8)]
    r = build_portfolio(500_000_000, cands, risk_pct=0.5)
    assert len(r["posisi"]) == 8
    assert not any("Kuota" in d["alasan"] or "risiko total" in d["alasan"] for d in r["dilewati"])


def _ct(kode, entry, sl, target):
    return {"kode": kode, "entry": entry, "stop_loss": sl, "target": target}


def test_imbalan_dan_rrr_dihitung_per_posisi():
    """Risiko saja tidak cukup menilai kelayakan -- yang menentukan justru
    perbandingannya dgn potensi untung."""
    r = build_portfolio(100_000_000, [_ct("AAAA", 1000, 950, 1150)], risk_pct=1.0)
    p = r["posisi"][0]
    assert p["target"] == 1150
    assert p["tp_pct"] == 15.0                       # (1150-1000)/1000
    assert p["rrr"] == 3.0                           # 150 untung : 50 rugi
    assert p["untung_rp"] == p["lembar"] * 150
    # konsisten: untung/rugi per lembar sesuai rrr
    assert abs(p["untung_rp"] / p["risiko_rp"] - p["rrr"]) < 0.01


def test_total_imbalan_dan_rrr_portofolio():
    r = build_portfolio(100_000_000, [
        _ct("AAAA", 1000, 950, 1150), _ct("BBBB", 2000, 1900, 2200),
    ], risk_pct=1.0)
    assert r["total_untung_rp"] == sum(p["untung_rp"] for p in r["posisi"])
    assert r["rrr_portofolio"] == round(r["total_untung_rp"] / r["total_risiko_rp"], 2)
    assert r["total_untung_pct"] > 0


def test_tanpa_target_imbalan_none_bukan_dikarang():
    """Kalau tidak ada level target, JANGAN mengarang angka untung."""
    r = build_portfolio(100_000_000, [_c("AAAA", 1000, 950)], risk_pct=1.0)
    p = r["posisi"][0]
    assert p["untung_rp"] is None and p["tp_pct"] is None and p["rrr"] is None
    assert r["total_untung_rp"] is None and r["rrr_portofolio"] is None


def test_target_tidak_wajar_diabaikan():
    """Target di bawah/sama dengan harga beli bukan take profit yang sah."""
    for bad in (900, 1000):
        r = build_portfolio(100_000_000, [_ct("AAAA", 1000, 950, bad)], risk_pct=1.0)
        assert r["posisi"][0]["untung_rp"] is None
        assert r["posisi"][0]["rrr"] is None


def test_total_imbalan_none_kalau_sebagian_saja_punya_target():
    """Menjumlahkan untung sebagian posisi TAPI risiko semua posisi itu
    menyesatkan -- lebih baik None."""
    r = build_portfolio(100_000_000, [
        _ct("AAAA", 1000, 950, 1150), _c("BBBB", 2000, 1900),
    ], risk_pct=1.0)
    assert r["posisi"][0]["untung_rp"] is not None
    assert r["posisi"][1]["untung_rp"] is None
    assert r["total_untung_rp"] is None
    assert r["rrr_portofolio"] is None


def test_auto_tolak_imbal_risiko_di_bawah_ambang():
    """Kasus NYATA dari data produksi: sinyal yang harganya sudah lari
    mendekati target menyisakan untung tipis tapi jarak stop tetap penuh
    (ADRO 0,02x, BBNI 0,38x). Peringkat skor keyakinan tidak menangkap ini,
    jadi mode otomatis harus menyaringnya sendiri."""
    r = build_portfolio(100_000_000, [
        _ct("BAGUS", 1000, 950, 1200),   # rrr 4.0
        _ct("TIPIS", 1000, 950, 1005),   # rrr 0.1 -> ditolak
    ], risk_pct=1.0, min_rrr=1.0)
    assert [p["kode"] for p in r["posisi"]] == ["BAGUS"]
    assert any("Imbal-risiko" in d["alasan"] for d in r["dilewati"])


def test_auto_tolak_yang_sudah_lewat_target():
    r = build_portfolio(100_000_000, [_ct("LEWAT", 1000, 950, 980)], risk_pct=1.0, min_rrr=1.0)
    assert r["posisi"] == []
    assert "melewati target" in r["dilewati"][0]["alasan"]


def test_auto_tolak_tanpa_target_saat_ambang_aktif():
    """Tanpa level target, kesepadanannya tak bisa dinilai -- saat sistem yang
    memilih, itu alasan cukup untuk tidak mengambilnya."""
    r = build_portfolio(100_000_000, [_c("NOTGT", 1000, 950)], risk_pct=1.0, min_rrr=1.0)
    assert r["posisi"] == []


def test_ambang_imbal_risiko_mati_untuk_mode_pilih_sendiri():
    """User yang memilih sendiri tetap boleh membeli apa pun -- rasionya
    ditampilkan supaya dia menilai, bukan disaring diam-diam."""
    r = build_portfolio(100_000_000, [_ct("TIPIS", 1000, 950, 1005)], risk_pct=1.0)
    assert len(r["posisi"]) == 1
    assert r["posisi"][0]["rrr"] == 0.1


def test_input_tidak_valid():
    assert build_portfolio(0, [_c("A", 100, 90)]) is None
    assert build_portfolio(1_000_000, []) is None
    assert build_portfolio(1_000_000, [_c("A", 100, 90)], risk_pct=0) is None


def test_field_tambahan_diteruskan():
    """Field bebas dari caller (mis. nama/likuiditas/skor) ikut terbawa ke
    hasil supaya endpoint tidak perlu menggabungkan ulang."""
    r = build_portfolio(10_000_000, [
        {"kode": "AAAA", "entry": 1000, "stop_loss": 950, "likuiditas": "Likuid", "grade": "A"},
    ], risk_pct=1.0)
    p = r["posisi"][0]
    assert p["likuiditas"] == "Likuid" and p["grade"] == "A"
