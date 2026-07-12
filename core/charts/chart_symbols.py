# =========================
# SIMBOL CHART (PENGGANTI EMOJI)
# =========================
# Font emoji standar (Noto Color Emoji, dkk) adalah font BERWARNA berbasis
# bitmap. Matplotlib merender teks secara vektor, dan secara struktural
# tidak bisa menampilkan font emoji warna dengan baik -- hasilnya kotak
# kosong di gambar PNG. Ini bukan masalah konfigurasi yang bisa diperbaiki
# dengan mengganti font path; ini keterbatasan teknis matplotlib yang
# sudah dikenal luas.
#
# Modul ini menyediakan pengganti simbol Unicode MONOKROM (bukan emoji
# warna) yang didukung oleh font vektor standar seperti DejaVu Sans, jadi
# tetap terlihat sebagai ikon di chart, bukan kotak kosong.
#
# CATATAN: mapping ini HANYA dipakai untuk CHART (gambar PNG/matplotlib).
# Teks lain (web UI, PDF) TIDAK terpengaruh -- browser/PDF renderer punya
# font emoji sendiri yang berfungsi normal, jadi emoji di teks biasa
# TETAP memakai emoji asli, tidak diubah.

CHART_SYMBOLS = {
    "📊": "■",   # bar chart -> filled square
    "📈": "▲",   # chart naik -> triangle atas
    "📉": "▼",   # chart turun -> triangle bawah
    "🔻": "▼",   # red triangle down -> triangle bawah
    "🚀": "↗",   # rocket -> arrow naik
    "💰": "$",   # money bag -> dollar sign
    "🎯": "◎",   # target -> circle dengan titik
    "📐": "∟",   # triangular ruler -> angle symbol
    "💡": "*",   # light bulb -> asterisk
    "🟢": "●",   # green circle -> filled circle
    "🟡": "●",   # yellow circle -> filled circle
    "🔴": "●",   # red circle -> filled circle
    "✅": "✓",   # check mark emoji -> check mark teks (lebih kompatibel)
    "❌": "✗",   # cross mark emoji -> cross mark teks
    "⚠️": "!",   # warning -> exclamation
    "🔥": "▲",   # fire -> triangle (representasi "panas/naik")
}


def to_chart_safe(text: str) -> str:
    """Ganti semua emoji yang dikenal dalam teks dengan simbol monokrom
    yang aman dirender matplotlib. Dipakai HANYA untuk teks yang akan
    ditempelkan ke chart (ax.text, suptitle, table, dll) -- BUKAN untuk
    teks biasa (web UI, PDF)."""
    result = text
    for emoji, symbol in CHART_SYMBOLS.items():
        result = result.replace(emoji, symbol)
    return result
