# Paket chart. File ini sengaja dieksekusi sekali saat modul chart
# pertama di-import (mis. core.charts.advanced_chart), jadi tempat yang
# tepat untuk konfigurasi matplotlib lintas-chart.
#
# Menyenyapkan SATU peringatan kosmetik yang spesifik: beberapa chart
# memakai layout (suptitle + multi-axes / twinx) yang membuat
# plt.tight_layout() memunculkan UserWarning "Axes that are not
# compatible with tight_layout". Output gambar TIDAK terpengaruh
# (savefig sudah pakai bbox_inches='tight'); warning ini cuma bikin log
# berisik. Difilter di sini secara TERTARGET (hanya pesan ini) supaya
# tidak menyembunyikan warning lain yang mungkin penting.
import warnings

# Dua phrasing warning tight_layout dari matplotlib, dua-duanya kosmetik:
#  - "...Axes that are not compatible with tight_layout..."
#  - "Tight layout not applied. The bottom and top margins cannot..."
# Difilter spesifik ke keluarga tight_layout saja (case-insensitive),
# bukan semua UserWarning, supaya warning lain yang mungkin penting
# tetap muncul.
warnings.filterwarnings(
    "ignore",
    message=r"(?i).*tight[_ ]?layout.*",
    category=UserWarning,
)
