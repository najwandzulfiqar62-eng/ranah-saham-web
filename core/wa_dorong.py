"""Kirim otomatis ke WhatsApp begitu sesuatu muncul -- tanpa diminta.

Permintaan penulis 6 Okt 2026: tiap saham yang masuk "Siluman (quiet buy)"
dan tiap sinyal baru dikirim sendiri ke bot, bukan ditunggu sampai ada yang
mengetik perintahnya.

YANG PALING MUDAH SALAH DI FITUR SEMACAM INI BUKAN KODENYA, TAPI TAKARANNYA.
Pesan yang datang sendiri itu mengganggu secara harfiah: ia membunyikan HP
orang. Begitu ia terlalu sering, yang terjadi bukan "orang membacanya lebih
sedikit" melainkan "orang membisukan grupnya" -- dan sesudah itu peringatan
yang benar-benar penting pun ikut tidak terbaca. Mahal sekali untuk
dipulihkan, jadi empat penjaga dipasang di depan:

1. DIKUMPULKAN, BUKAN SATU PESAN PER SAHAM. Lima saham masuk Siluman =
   satu pesan berisi lima baris, bukan lima notifikasi.
2. TIDAK DIULANG. Satu emiten cuma diberitakan sekali per JEDA_ULANG_JAM.
   Tanpa ini, saham yang bertahan di Siluman akan diumumkan tiap putaran
   loop -- tiap lima menit, seharian.
3. HANYA JAM BURSA. Anomali volume cuma berubah saat pasar buka. Pesan
   pukul 3 pagi tidak menambah satu pun keputusan yang bisa diambil.
4. BERPAGU. Sebanyak apa pun yang masuk, satu pesan memuat paling banyak
   MAKS_PER_PESAN baris.

Penyimpanan "sudah pernah dikirim" MENUMPANG tabel wa_alert_kirim yang
sudah ada, dengan user_id = GRUP (0). Nol tidak akan pernah jadi id akun
sungguhan (AUTOINCREMENT SQLite mulai dari 1), jadi ia aman sebagai
penanda "ini kiriman ke grup, bukan ke orang". Menumpang berarti aturan
jeda & pembersihannya satu, bukan dua yang bisa berbeda diam-diam.
"""
from datetime import datetime, timedelta, timezone

from core.wa_alert import catat_kirim, ensure_alert_tables, sudah_pernah

WIB = timezone(timedelta(hours=7))

# Penanda "penerimanya grup, bukan satu orang". Lihat catatan modul.
GRUP = 0

# Pola yang diberitakan. None = SEMUA kategori anomali.
#
# Semula sengaja dibatasi ke "Siluman (quiet buy)" saja, dengan alasan pola
# lain sudah menonjol sendiri. Penulis memilih sebaliknya 6 Okt 2026: yang
# ia mau adalah daftar yang sama persis dengan perintah `smartmoney`, cuma
# berisi yang BARU. Itu permintaan yang masuk akal -- yang membuat pesan
# otomatis mengganggu bukan banyaknya kategori, melainkan PENGULANGAN, dan
# pengulangan sudah ditutup penjaga 2 & 4 di atas.
POLA_DIDORONG = None

# Satu emiten tidak diberitakan lagi dalam rentang ini. 24 jam, bukan 48
# seperti peringatan posisi: anomali volume itu kejadian HARIAN, dan saham
# yang masuk Siluman lagi besok memang kabar baru.
JEDA_ULANG_JAM = 24

# Pagu baris per pesan. Dinaikkan dari 12 begitu semua kategori ikut: satu
# hari penuh bisa menghasilkan ~21 anomali (terukur 6 Okt 2026), dan pagu
# yang lebih rendah dari itu akan memecah daftar hari pertama jadi dua
# pesan tanpa alasan. 25 setara ~2.000 karakter -- masih di bawah ukuran
# balasan `smartmoney` yang sudah terbukti terbaca.
MAKS_PER_PESAN = 25

# Jendela kirim (WIB). Lebih sempit dari jam bursa di kedua ujungnya --
# sengaja: yang dikirim di sini bukan hal yang menuntut tindakan dalam
# hitungan detik, jadi tidak ada gunanya menyalakan HP orang pukul 09.00
# tepat saat pembukaan masih kacau, atau menjelang penutupan saat sudah
# tidak ada waktu menindaklanjutinya.
JAM_MULAI = 9
JAM_SELESAI = 16


def sekarang_wib() -> datetime:
    """Waktu WIB, EKSPLISIT.

    Bukan datetime.now() polos. Jendela kirim yang bergantung pada zona
    waktu server akan diam-diam bergeser kalau servernya pindah atau
    disetel UTC -- dan gejalanya bukan error, melainkan pesan yang tiba
    pukul 2 pagi.
    """
    return datetime.now(WIB)


def dalam_jam_kirim(waktu: datetime | None = None) -> bool:
    """Hari bursa, di dalam jendela kirim?

    KETERBATASAN YANG DICATAT JUJUR: libur nasional yang jatuh di hari
    kerja TIDAK tertutup -- itu butuh kalender libur bursa yang tidak ada
    di aplikasi ini. Keterbatasan yang sama sudah diakui di
    core/signal_history.py (_is_bursa_weekend). Akibat terburuknya satu
    pesan sepi di hari libur, bukan angka yang salah.
    """
    w = waktu or sekarang_wib()
    if w.weekday() >= 5:
        return False
    return JAM_MULAI <= w.hour < JAM_SELESAI


def saring_stabil(items: list[dict], kode_sebelumnya: set) -> list[dict]:
    """Hanya saham yang berpola sama di DUA pemindaian berurutan.

    KENAPA ADA (6 Okt 2026). Penulis melihat perintah `smartmoney` pukul
    14.33 menyebut empat saham Siluman, sementara kiriman otomatis pukul
    14.58 menyebut tiga -- dan dua di antaranya bukan yang sama.

    Sebabnya bukan bug, melainkan sesuatu yang lebih halus: pola dihitung
    dari bar HARI INI yang BELUM SELESAI. Selama sesi berjalan, chg1 dan
    chg5 masih bergerak, dan ambang di _sm_classify itu keras. SGER pukul
    14.33 bernilai chg1 +3,31% sehingga lolos `chg1 > 3` dan dilabeli
    "Breakout Volume"; pukul 14.58 ia +2,65%, jatuh ke bawah ambang yang
    sama, lalu memenuhi syarat "Siluman". Saham yang sama, hari yang sama,
    label yang berbeda -- semata karena bursa belum tutup.

    Ini pengulangan pelajaran yang sudah pernah mahal di proyek ini: sinyal
    NR7 dulu menyala dari bar sesi berjalan, dan separuhnya ternyata
    artefak. Bedanya, di sini akibatnya lebih sulit dibatalkan -- pesannya
    sudah terkirim ke HP orang, dan jeda 24 jam membuat saham yang terlanjur
    diumumkan dalam keadaan sesaat TIDAK bisa diumumkan lagi ketika polanya
    sungguhan di penutupan.

    Penyaring ini tidak membuat polanya jadi final -- tidak ada yang bisa,
    sebelum bursa tutup. Ia cuma menuntut pola itu BERTAHAN satu putaran
    (sekitar lima menit) sebelum diberitakan, yang membuang kedipan sesaat
    dengan ongkos satu putaran keterlambatan.
    """
    sebelumnya = {str(k).upper() for k in (kode_sebelumnya or set())}
    return [it for it in items
            if str(it.get("kode") or "").upper() in sebelumnya]


def kode_dari(items: list[dict]) -> set:
    """Himpunan kode dari daftar hasil pindai, untuk dibandingkan putaran
    berikutnya."""
    return {str(it.get("kode")).upper() for it in (items or [])
            if isinstance(it, dict) and it.get("kode")}


def _kunci_dorong(kode: str, ruang: str = "sm") -> str:
    """Kunci dedup per EMITEN, bukan per emiten+pola.

    `ruang` memisahkan ANTAR-PENDORONG, dan itu bukan hiasan. Sebelum
    parameter ini ada, kuncinya "dorong:sm:BBCA" untuk semua pemakai --
    sehingga begitu pendorong kedua (vonis Ringkasan Sinyal) memakai
    fungsi yang sama, BBCA yang baru diumumkan Smart Money akan DIAM-DIAM
    dibungkam di pendorong vonis selama 24 jam, dan sebaliknya. Dua kabar
    yang berbeda tentang saham yang sama saling menelan tanpa jejak di
    log mana pun.

    Yang ingin dijawab penjaga ini adalah "apakah orang sudah diberi
    tahu tentang HAL INI untuk saham ini hari ini" -- dan "hal ini"
    berbeda per pendorong. Default "sm" dipertahankan supaya perilaku
    dan catatan lama tidak bergeser.

    Sempat memuat polanya juga, dan itu salah begitu semua kategori ikut
    dikirim: SGER yang berpindah dari "Breakout Volume" ke "Siluman" dalam
    satu sesi (kejadian nyata 6 Okt 2026) akan menghasilkan dua kunci
    berbeda, sehingga saham yang SAMA diumumkan dua kali di hari yang sama.

    Yang ingin dijawab penjaga ini adalah "apakah orang sudah diberi tahu
    tentang saham ini hari ini", dan jawabannya tidak berubah karena
    labelnya bergeser.
    """
    return f"dorong:{ruang}:{(kode or '').upper()}"


def pilih_belum_dikirim(items: list[dict],
                        pola_didorong: set | None = None,
                        ruang: str = "sm") -> list[dict]:
    """Saham berpola terpantau yang BELUM diberitakan belakangan.

    Urutannya dipertahankan apa adanya dari pemanggil (sudah terurut
    peringkat volume), dan dipotong di MAKS_PER_PESAN -- bukan dibuang
    diam-diam: yang terpotong tidak dicatat sebagai terkirim, jadi ia ikut
    di putaran berikutnya.
    """
    if pola_didorong is None:
        pola_didorong = POLA_DIDORONG
    ensure_alert_tables()
    keluar = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        kode, pola = it.get("kode"), it.get("pola")
        if not kode or not pola:
            continue
        # pola_didorong None = semua kategori anomali ikut.
        if pola_didorong is not None and pola not in pola_didorong:
            continue
        if sudah_pernah(GRUP, _kunci_dorong(kode, ruang), jam=JEDA_ULANG_JAM):
            continue
        keluar.append(it)
        if len(keluar) >= MAKS_PER_PESAN:
            break
    return keluar


def catat_terkirim(items: list[dict], ruang: str = "sm",
                   jenis: str = "sm_anomali") -> None:
    """Dipanggil HANYA sesudah pengirimannya benar-benar berhasil.

    Mencatat lebih dulu akan membuat kabar hilang selamanya kalau WhatsApp
    sedang menolak -- ia dianggap sudah dikirim padahal tidak pernah
    sampai. Pola yang sama dipakai cursor digest harian.
    """
    for it in items or []:
        kode, pola = it.get("kode"), it.get("pola")
        if kode and pola:
            catat_kirim(GRUP, kode, jenis, _kunci_dorong(kode, ruang))
