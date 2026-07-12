# =========================
# MESSAGE FORMATTING HELPERS
# =========================
# Sisa dari modul format-pesan bot Telegram lama (dihapus -- lihat
# penghapusan core/telegram_notify.py). sanitize_for_markdown() TIDAK ikut
# dihapus krn direpurpose oleh core/insight.py (tidak ada hubungan dgn
# Telegram lagi, murni sanitasi teks sebelum dirangkai jadi narasi web).


def sanitize_for_markdown(text: str | None) -> str:
    """Bersihkan teks dari karakter spesial Markdown-like SEBELUM
    dirangkai ke narasi insight -- teks dari sumber EKSTERNAL yang tidak
    dikontrol app ini (judul berita RSS, nama perusahaan dari Yahoo
    Finance) bisa mengandung underscore/asterisk/backtick yang mengganggu
    pembacaan kalau ikut ditampilkan mentah.

    PENDEKATAN: ganti karakter spesial dengan karakter visual serupa yang
    aman (bukan escape dengan backslash). Cukup aman untuk teks yang cuma
    perlu DIBACA, bukan teks yang butuh mempertahankan formatting aslinya.

    Dipakai di: core/insight.py (judul berita di narasi insight pasar)."""
    if not text:
        return text or ""
    return (
        text.replace("_", "-")
            .replace("*", "")
            .replace("`", "'")
            .replace("[", "(")
            .replace("]", ")")
    )
