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

# Pola Smart Money yang layak diberitakan sendiri. Sengaja SATU, bukan
# semuanya: "Siluman (quiet buy)" adalah pola yang paling mudah terlewat
# kalau tidak diberitahukan -- harga naik pelan dengan volume yang justru
# di BAWAH rata-rata, jadi ia tidak muncul di layar mana pun yang diurut
# berdasarkan lonjakan. Pola lain (Breakout Volume, Akumulasi Agresif)
# sudah menonjol dengan sendirinya; mengirimkannya juga cuma menambah
# kebisingan tanpa menambah yang tidak terlihat.
POLA_DIDORONG = {"Siluman (quiet buy)"}

# Satu emiten tidak diberitakan lagi dalam rentang ini. 24 jam, bukan 48
# seperti peringatan posisi: anomali volume itu kejadian HARIAN, dan saham
# yang masuk Siluman lagi besok memang kabar baru.
JEDA_ULANG_JAM = 24

MAKS_PER_PESAN = 12

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


def _kunci_siluman(kode: str, pola: str) -> str:
    return f"dorong:sm:{(kode or '').upper()}:{pola}"


def pilih_belum_dikirim(items: list[dict],
                        pola_didorong: set | None = None) -> list[dict]:
    """Saham berpola terpantau yang BELUM diberitakan belakangan.

    Urutannya dipertahankan apa adanya dari pemanggil (sudah terurut
    peringkat volume), dan dipotong di MAKS_PER_PESAN -- bukan dibuang
    diam-diam: yang terpotong tidak dicatat sebagai terkirim, jadi ia ikut
    di putaran berikutnya.
    """
    pola_didorong = POLA_DIDORONG if pola_didorong is None else pola_didorong
    ensure_alert_tables()
    keluar = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        kode, pola = it.get("kode"), it.get("pola")
        if not kode or pola not in pola_didorong:
            continue
        if sudah_pernah(GRUP, _kunci_siluman(kode, pola), jam=JEDA_ULANG_JAM):
            continue
        keluar.append(it)
        if len(keluar) >= MAKS_PER_PESAN:
            break
    return keluar


def catat_terkirim(items: list[dict]) -> None:
    """Dipanggil HANYA sesudah pengirimannya benar-benar berhasil.

    Mencatat lebih dulu akan membuat kabar hilang selamanya kalau WhatsApp
    sedang menolak -- ia dianggap sudah dikirim padahal tidak pernah
    sampai. Pola yang sama dipakai cursor digest harian.
    """
    for it in items or []:
        kode, pola = it.get("kode"), it.get("pola")
        if kode and pola:
            catat_kirim(GRUP, kode, "sm_siluman", _kunci_siluman(kode, pola))
