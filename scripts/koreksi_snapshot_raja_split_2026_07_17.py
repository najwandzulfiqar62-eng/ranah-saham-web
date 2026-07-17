# =========================
# KOREKSI SEKALI-JALAN: snapshot harian RAJA 2026-07-17 (artefak split)
# =========================
# Auto-cycle pagi 2026-07-17 sempat merekam snapshot floating -79.78% utk
# RAJA (id=199) SEBELUM guard is_price_scale_anomaly() ada -- angka itu
# artefak skala harga stock split ~1:5 (entry 4.328 vs harga baru ~875),
# BUKAN pergerakan pasar, dan meracuni recap Riwayat Harian / delta
# naik-turun vs kemarin.
#
# Yang dihapus HANYA baris signal_daily_snapshot yang harganya beda skala
# dari entry (kriteria SAMA dgn is_price_scale_anomaly). signal_history
# TIDAK disentuh sama sekali (aturan tetap: riwayat sinyal tidak pernah
# dihapus). Idempotent -- jalan kedua kalinya tidak menghapus apa pun
# karena guard baru mencegah baris sejenis lahir lagi.
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.database import get_db  # noqa: E402
from core.signal_history import ENTRY_ANOMALY_RATIO, ENTRY_ANOMALY_RATIO_UP  # noqa: E402


def main():
    with get_db() as conn:
        cur = conn.execute('''
            DELETE FROM signal_daily_snapshot WHERE id IN (
                SELECT s.id FROM signal_daily_snapshot s
                JOIN signal_history h ON h.id = s.signal_id
                WHERE s.price < h.entry_price * ? OR s.price > h.entry_price * ?
            )
        ''', (ENTRY_ANOMALY_RATIO, ENTRY_ANOMALY_RATIO_UP))
        print(f"snapshot artefak skala terhapus: {cur.rowcount} baris")


if __name__ == "__main__":
    main()
