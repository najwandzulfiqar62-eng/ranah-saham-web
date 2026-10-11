"""Sistem mana saja di aplikasi ini yang sedang menandai satu emiten.

GAGASANNYA dari penulis: saat membuka sebuah saham, langsung terlihat
"saham ini sudah masuk Audit Sinyal dan juga Smart Money". Itu berguna
-- aplikasi ini punya enam sumber penanda, dan sebelumnya orang harus
membuka enam halaman untuk tahu.

TAPI ADA JEBAKAN YANG HARUS DITUTUP SEJAK AWAL, dan ia bukan soal
tampilan.

    Lencana yang ditumpuk terbaca sebagai KONFIRMASI BERLAPIS.
    "Empat sistem setuju" terdengar jauh lebih kuat daripada satu.

Padahal sumber-sumber itu TIDAK saling bebas. Yang paling jelas:
Smart Money hanya direkam kalau vonis Ringkasan Sinyal SUDAH bilang
BELI/BELI KUAT (lihat _record_smart_money_cycle di web/app.py).
Jadi "Smart Money + Vonis BELI" bukan dua pendapat yang kebetulan
sepakat -- yang satu syarat bagi yang lain. Menghitungnya dua kali
persis seperti menanyakan hal yang sama pada orang yang sama dua kali
lalu menyebutnya konsensus.

Karena itu tiap lencana membawa:
  - angka TERUKUR-nya sendiri (kalau sudah diukur; None kalau belum)
  - daftar lencana lain yang ia TUMPANG TINDIH dengannya

dan layar diwajibkan menyebut tumpang tindihnya. Lebih banyak lencana
TIDAK berarti lebih kuat, dan itu harus terbaca sebelum orang
menyimpulkan sebaliknya.

MURAH. Seluruh sumbernya sudah dihitung di tempat lain dan tersedia di
cache atau lewat kueri ber-indeks per kode; modul ini tidak menghitung
ulang apa pun dan tidak mengunduh apa pun.
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Lencana:
    kunci: str
    nama: str
    aktif: bool
    arah: str                      # "naik" | "turun" | "netral"
    catatan: str = ""
    unggul_pct: float | None = None
    n_ukur: int | None = None
    # Lencana lain yang MENCAKUP atau DICAKUP lencana ini. Bukan hiasan:
    # ia yang mencegah pembaca menghitung satu pendapat dua kali.
    tumpang_tindih: tuple = ()

    def dict(self) -> dict:
        return {"kunci": self.kunci, "nama": self.nama, "aktif": self.aktif,
                "arah": self.arah, "catatan": self.catatan,
                "unggul_pct": self.unggul_pct, "n_ukur": self.n_ukur,
                "tumpang_tindih": list(self.tumpang_tindih)}


# Tumpang tindih yang SUDAH diketahui dari kodenya, bukan ditaksir.
#
#   smart_money -> vonis : _record_smart_money_cycle menolak mencatat
#                          kalau vonisnya bukan BELI/BELI KUAT
#   audit       -> keduanya di atas: Audit Sinyal adalah tempat sinyal
#                          Top Pick DAN Smart Money dicatat, jadi
#                          "masuk Audit" sebagian besar berarti salah
#                          satu dari keduanya sudah menyala
TUMPANG_TINDIH = {
    "smart_money": ("vonis",),
    "vonis": ("smart_money",),
    "audit": ("smart_money", "vonis"),
}

KETERANGAN_TUMPANG = (
    "Smart Money hanya dicatat kalau vonis Ringkasan Sinyal sudah "
    "BELI atau BELI KUAT. Jadi keduanya BUKAN dua pendapat yang "
    "kebetulan sepakat — yang satu syarat bagi yang lain. Lebih "
    "banyak lencana tidak berarti lebih kuat."
)


def susun(kode: str, *, audit_aktif: bool = False, audit_sumber: tuple = (),
          vonis: str | None = None, vonis_unggul: float | None = None,
          vonis_n: int | None = None,
          smart_money_pola: str | None = None,
          pemulihan_kuat: bool | None = None,
          pemulihan_unggul: float | None = None,
          smc_jenis: str | None = None, smc_arah: str | None = None,
          nr7_aktif: bool = False,
          minervini_harmonic_aktif: bool = False) -> dict:
    """Rangkai lencana dari data yang SUDAH dihitung pemanggil.

    Sengaja tidak mengambil datanya sendiri: tiap sumber punya cache dan
    aturan "jangan memindai atas permintaan pengunjung" sendiri-sendiri,
    dan modul ini tidak boleh jadi pintu belakang yang melewatinya.
    """
    out: list[Lencana] = []

    if audit_aktif:
        src = ", ".join(audit_sumber) if audit_sumber else "sinyal aktif"
        out.append(Lencana(
            "audit", "Audit Sinyal", True, "netral",
            f"punya sinyal yang sedang diaudit ({src})",
            tumpang_tindih=TUMPANG_TINDIH["audit"]))

    if vonis in ("BELI KUAT", "BELI", "JUAL", "JUAL KUAT"):
        naik = vonis.startswith("BELI")
        out.append(Lencana(
            "vonis", f"Vonis {vonis}", True, "naik" if naik else "turun",
            "dari 7 indikator Ringkasan Sinyal",
            unggul_pct=vonis_unggul, n_ukur=vonis_n,
            tumpang_tindih=TUMPANG_TINDIH["vonis"]))

    if smart_money_pola:
        out.append(Lencana(
            "smart_money", "Smart Money", True, "naik",
            f"anomali volume: {smart_money_pola}",
            tumpang_tindih=TUMPANG_TINDIH["smart_money"]))

    if pemulihan_kuat is not None:
        out.append(Lencana(
            "pemulihan", "Pemulihan" + (" KUAT" if pemulihan_kuat else ""),
            True, "naik", "divergence RSI sesudah jatuh",
            unggul_pct=pemulihan_unggul if pemulihan_kuat else None,
            n_ukur=222 if pemulihan_kuat else None))

    if smc_jenis and smc_arah:
        # SATU-SATUNYA lencana yang angkanya lulus uji dua periode.
        # Semua yang lain di aplikasi ini diukur sekali; SMC diukur di
        # 2 tahun DAN 5 tahun, dan keempat tandanya cocok.
        try:
            from core.smc import unggul_smc
            u = unggul_smc(smc_jenis, smc_arah)
        except Exception:
            u = None
        naik = smc_arah == "bullish"
        out.append(Lencana(
            "smc", f"SMC {smc_jenis}", True, "naik" if naik else "turun",
            (f"struktur {smc_arah}"
             + (" · stabil di 2 & 5 tahun" if (u or {}).get("stabil") else "")),
            unggul_pct=(u or {}).get("unggul_pct"),
            n_ukur=(u or {}).get("n")))

    if nr7_aktif:
        out.append(Lencana(
            "nr7", "NR7 + 52W", True, "naik",
            "kontraksi volatilitas di area tertinggi 52 minggu — "
            "stop ketat, breakout bisa gagal"))

    if minervini_harmonic_aktif:
        # "dijeda" DISEBUT, dan itu bukan basa-basi. Lencana ini muncul
        # dari sinyal MVH yang masih terbuka, dan sejak 12 Okt 2026 teori
        # itu BERHENTI menerbitkan sinyal baru -- syaratnya harmonic
        # bullish, sisi yang terukur -0,12% (di bawah pasar), sementara
        # persilangannya dengan Minervini belum pernah diukur.
        #
        # Tanpa kalimat ini, pembaca melihat lencana yang terlihat
        # seaktual lencana lain dan wajar mengira teorinya masih berjalan.
        # Yang sedang ia lihat adalah sisa sinyal lama yang masih diaudit
        # sampai selesai.
        out.append(Lencana(
            "minervini_harmonic", "Minervini × Harmonic", True, "naik",
            "lolos saringan tren Minervini DAN pola harmonic — "
            "teori ini DIJEDA sejak 12 Okt 2026, belum terukur; "
            "ini sinyal lama yang masih diaudit"))

    # Pasangan yang benar-benar MUNCUL BERSAMA di emiten ini -- bukan
    # seluruh daftar teori, cuma yang relevan sekarang.
    ada = {x.kunci for x in out}
    pasangan = sorted({
        tuple(sorted((x.kunci, y)))
        for x in out for y in x.tumpang_tindih if y in ada
    })
    return {
        "lencana": [x.dict() for x in out],
        "jumlah": len(out),
        "tumpang_tindih_aktif": [list(p) for p in pasangan],
        "keterangan_tumpang": KETERANGAN_TUMPANG if pasangan else None,
    }
