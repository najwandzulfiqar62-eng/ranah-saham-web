"""Peringatan posisi: bot menyahut duluan, bukan menunggu ditanya.

Seluruh perintah bot bersifat TARIK -- orang harus bertanya dulu. Yang
membedakan asisten dari mesin pencari adalah ia bicara saat ada yang perlu
dibicarakan: "ERAA menyentuh 600, level yang kemarin disebutkan", "ANTM kena
target pertamamu".

YANG PALING SULIT DI SINI BUKAN MENDETEKSI, TAPI DIAM
=====================================================
Bot yang terlalu cerewet akan di-mute. Dan sesudah di-mute, peringatan
PENTING tidak sampai ke siapa pun -- jadi mengirim terlalu banyak bukan
sekadar mengganggu, ia merusak gunanya sendiri.

Tiga penjaga, dan ketiganya diperlukan:

  1. JATAH HARIAN. Paling banyak beberapa pesan per orang per hari.
     Kejadian penting (sentuh target/stop) dikecualikan -- itu memang yang
     ditunggu orang, dan menahannya karena jatah habis justru kegagalan.
  2. TIDAK MENGULANG. Satu keadaan cuma diberitahukan sekali. Harga yang
     bergoyang di sekitar sebuah level tidak boleh menghasilkan sepuluh
     pesan yang sama.
  3. JEDA PENDINGINAN per keadaan. Sesudah keadaan itu berlalu dan kembali
     lagi berhari-hari kemudian, barulah ia layak disebut lagi.

Semua dicatat di basis data, bukan di memori: proses bisa di-restart
kapan saja, dan penjaga yang lupa sesudah restart bukan penjaga.
"""
from datetime import datetime, timedelta, timezone

from core.database import get_db

WIB = timezone(timedelta(hours=7))

# Jatah pesan per orang per hari untuk peringatan BIASA. Kejadian penting
# tidak dihitung di sini -- lihat PENTING.
JATAH_HARIAN = 3

# Berapa lama satu keadaan yang sama tidak diulang, walau ia terjadi lagi.
JEDA_ULANG_JAM = 48

# Jenis yang TIDAK terkena jatah harian: ini yang justru ditunggu orang.
PENTING = {"tp", "sl"}

_tabel_siap = False


def ensure_alert_tables() -> None:
    global _tabel_siap
    if _tabel_siap:
        return
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS wa_alert_kirim (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                kode TEXT NOT NULL,
                jenis TEXT NOT NULL,
                kunci TEXT NOT NULL,
                dikirim_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_alert_user "
                     "ON wa_alert_kirim(user_id, dikirim_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_alert_kunci "
                     "ON wa_alert_kirim(user_id, kunci)")
        # NADI PUTARAN -- lihat catat_nadi() di bawah utk alasannya.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS wa_alert_nadi (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                terakhir_at TEXT NOT NULL,
                putaran INTEGER NOT NULL DEFAULT 0,
                n_user INTEGER NOT NULL DEFAULT 0,
                n_posisi INTEGER NOT NULL DEFAULT 0,
                n_berharga INTEGER NOT NULL DEFAULT 0,
                n_ber_sl INTEGER NOT NULL DEFAULT 0,
                n_kirim INTEGER NOT NULL DEFAULT 0
            )
        """)
    _tabel_siap = True


def catat_nadi(n_user: int, n_posisi: int, n_berharga: int,
               n_ber_sl: int, n_kirim: int) -> None:
    """Catat bahwa satu putaran pemeriksaan BENAR-BENAR berjalan, dan apa
    yang dilihatnya.

    KENAPA INI ADA. Tabel wa_alert_kirim cuma terisi saat ada peringatan
    yang DIKIRIM. Jadi "tabelnya kosong" tidak bisa membedakan empat
    keadaan yang sangat berbeda:

        a. loop-nya tidak pernah jalan (mati / tidak pernah jam bursa)
        b. jalan, tapi tidak ada anggota ber-nomor-HP
        c. jalan, anggota ada, tapi tidak ada yang punya posisi
        d. jalan, posisi ada, cuma memang belum ada yang layak dikirim

    Hanya (d) yang berarti "sistemnya sehat, cuma sedang diam". Tiga
    sisanya kerusakan atau kekosongan data, dan tanpa nadi ini keempatnya
    terlihat identik dari luar: tabel yang tidak ada.

    Pelajaran ini mahal: tools/cek_server.sh versi pertama MENYIMPULKAN
    "jalur peringatan belum pernah jalan sekali pun" dari tabel yang
    belum ada -- kesimpulan yang buktinya tidak sanggup menopang.
    """
    ensure_alert_tables()
    with get_db() as conn:
        conn.execute("""
            INSERT INTO wa_alert_nadi
                (id, terakhir_at, putaran, n_user, n_posisi, n_berharga,
                 n_ber_sl, n_kirim)
            VALUES (1, datetime('now'), 1, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                terakhir_at = datetime('now'),
                putaran     = wa_alert_nadi.putaran + 1,
                n_user      = excluded.n_user,
                n_posisi    = excluded.n_posisi,
                n_berharga  = excluded.n_berharga,
                n_ber_sl    = excluded.n_ber_sl,
                n_kirim     = wa_alert_nadi.n_kirim + excluded.n_kirim
        """, (int(n_user), int(n_posisi), int(n_berharga),
              int(n_ber_sl), int(n_kirim)))


def baca_nadi() -> dict | None:
    """Keadaan putaran terakhir, atau None kalau belum pernah jalan."""
    ensure_alert_tables()
    with get_db() as conn:
        r = conn.execute("SELECT * FROM wa_alert_nadi WHERE id = 1").fetchone()
    return dict(r) if r else None


def _sekarang() -> datetime:
    return datetime.now(timezone.utc)


def sudah_pernah(user_id: int, kunci: str, jam: int = JEDA_ULANG_JAM) -> bool:
    """True kalau keadaan dengan kunci ini sudah diberitahukan belakangan.

    `kunci` memuat SELURUH yang membuat keadaannya unik (emiten + jenis +
    levelnya). Harga yang bergoyang di sekitar satu level akan menghasilkan
    kunci yang sama, jadi ia cuma dikirim sekali.
    """
    ensure_alert_tables()
    batas = (_sekarang() - timedelta(hours=jam)).strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as conn:
        r = conn.execute(
            "SELECT 1 FROM wa_alert_kirim WHERE user_id = ? AND kunci = ? "
            "AND dikirim_at >= ? LIMIT 1",
            (int(user_id), kunci, batas)).fetchone()
    return r is not None


def sisa_jatah(user_id: int) -> int:
    """Berapa peringatan BIASA yang masih boleh dikirim hari ini (WIB)."""
    ensure_alert_tables()
    # Hari kalender WIB, bukan UTC: "hari ini" bagi penerimanya adalah hari
    # di Jakarta, dan jatah yang menyetel ulang pukul 07.00 pagi akan terasa
    # seperti bug.
    awal_wib = datetime.now(WIB).replace(hour=0, minute=0, second=0, microsecond=0)
    awal = awal_wib.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as conn:
        r = conn.execute(
            "SELECT COUNT(*) c FROM wa_alert_kirim WHERE user_id = ? "
            "AND dikirim_at >= ? AND jenis NOT IN ('tp', 'sl')",
            (int(user_id), awal)).fetchone()
    return max(0, JATAH_HARIAN - (r["c"] if r else 0))


def boleh_kirim(user_id: int, jenis: str, kunci: str) -> bool:
    """Gabungan ketiga penjaga. Ini SATU-SATUNYA pintu sebelum mengirim."""
    if sudah_pernah(user_id, kunci):
        return False
    if jenis in PENTING:
        return True
    return sisa_jatah(user_id) > 0


def catat_kirim(user_id: int, kode: str, jenis: str, kunci: str) -> None:
    ensure_alert_tables()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO wa_alert_kirim (user_id, kode, jenis, kunci) "
            "VALUES (?, ?, ?, ?)",
            (int(user_id), (kode or "").upper(), jenis, kunci))


def bersihkan(hari: int = 30) -> int:
    """Buang catatan lama. Tabel ini tumbuh tiap hari dan tidak ada yang
    membacanya lebih dari beberapa hari ke belakang."""
    ensure_alert_tables()
    batas = (_sekarang() - timedelta(days=hari)).strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as conn:
        cur = conn.execute("DELETE FROM wa_alert_kirim WHERE dikirim_at < ?", (batas,))
        return cur.rowcount or 0


# ---------------------------------------------------------------------------
# Aturan: keadaan apa yang layak mengganggu orang
# ---------------------------------------------------------------------------

def periksa_posisi(p: dict, harga: float, level: list[dict] | None = None,
                   sl: float | None = None) -> dict | None:
    """Satu posisi -> peringatan yang layak dikirim, atau None.

    Dipisah dari pengiriman supaya bisa diuji tanpa WhatsApp, basis data,
    maupun jaringan -- aturan seperti ini yang paling perlu bisa diperiksa
    dengan angka di tangan.

    Urutannya sengaja: yang paling mendesak menang. Satu posisi cuma
    menghasilkan SATU pesan, karena dua pesan tentang saham yang sama dalam
    satu menit terbaca seperti bot rusak.
    """
    kode = (p.get("kode") or "").upper()
    avg = p.get("harga_avg") or 0
    if not (kode and avg and harga and harga > 0):
        return None
    ubah = (harga / avg - 1) * 100

    # 1. STOP. Paling mendesak: uangnya sedang keluar.
    if sl and harga <= sl:
        return {"jenis": "sl", "kode": kode,
                "kunci": f"{kode}:sl:{round(sl)}",
                # "rencanamu" DIGANTI 11 Okt 2026. Angka stop ini datang dari
                # sinyal di Audit Sinyal (sl_rencana_kode), bukan dari sesuatu
                # yang orangnya pernah setel sendiri -- posisi portofolio tidak
                # menyimpan stop sama sekali. Menyebutnya "rencanamu" membuat
                # pembacanya mengira ia sedang diingatkan soal keputusannya
                # sendiri, lalu menindaklanjutinya dengan keyakinan yang tidak
                # pernah ia berikan.
                "teks": (f"⚠ *{kode}* menyentuh {_rp(harga)} — di bawah stop "
                         f"rencana Audit Sinyal {_rp(sl)}.\n"
                         f"Posisi {ubah:+.1f}% dari rata-rata {_rp(avg)}.\n\n"
                         f"_Keputusan tetap di kamu. Ketik `{kode}` untuk "
                         f"kondisi teknikalnya hari ini._")}

    # 2. LEVEL MENAMBAH yang pernah disebutkan bot. Inilah yang membuat
    #    peringatan terasa nyambung, bukan notifikasi acak: harganya
    #    menyentuh angka yang MEMANG sudah dibicarakan sebelumnya.
    for lv in (level or []):
        harga_lv = lv.get("price")
        if harga_lv and harga <= harga_lv and ubah < 0:
            return {"jenis": "level", "kode": kode,
                    "kunci": f"{kode}:level:{round(harga_lv)}",
                    "teks": (f"*{kode}* menyentuh {_rp(harga)} — "
                             f"{lv.get('label') or 'level'} {_rp(harga_lv)} "
                             f"yang pernah disebutkan.\n"
                             f"Posisi {ubah:+.1f}% dari rata-rata {_rp(avg)}.\n\n"
                             f"_Menambah TIDAK wajib — syaratnya ada di "
                             f"`nyangkut {kode} {avg:.0f}`._")}

    # 3. UNTUNG BESAR. Bukan perintah menjual; pengingat bahwa untung yang
    #    tidak direalisasikan bisa hilang.
    if ubah >= 20:
        tingkat = int(ubah // 10) * 10        # kuncinya per kelipatan 10%
        return {"jenis": "untung", "kode": kode,
                "kunci": f"{kode}:untung:{tingkat}",
                "teks": (f"*{kode}* {ubah:+.1f}% dari rata-ratamu "
                         f"{_rp(avg)} (sekarang {_rp(harga)}).\n\n"
                         f"_Untung yang belum direalisasikan bisa hilang. "
                         f"Ketik `porto` untuk melihat semuanya._")}
    return None


def _rp(x) -> str:
    if x is None:
        return "—"
    return "Rp" + f"{float(x):,.0f}".replace(",", ".")
