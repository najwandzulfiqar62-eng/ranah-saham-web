# =========================
# Revert sinyal ARTO id=189 (TP_HIT palsu, jam 00:01 WIB)
# =========================
# Bug: audit_open_signals() dulu tidak punya gate jam bursa, jadi sinyal
# ARTO yang baru direkam jam 00:01 WIB (9 jam SEBELUM bursa buka) langsung
# ter-audit 6 detik kemudian pakai fast_info.last_price yfinance -- yang
# ternyata cuma ECHO closing price sesi SEBELUMNYA (7 Juli), bukan harga
# baru hari itu (8 Juli). Confirmed via /api/signals + laporan user
# langsung ("ngebug nih perasaan arto bukan harga segitu hari ini").
#
# Fix ke depan: core/signal_history.py::_is_bursa_trading_hours() +
# gate di audit_open_signals() (lihat commit terkait). Script ini HANYA
# membenarkan SATU baris yang SUDAH terlanjur salah tercatat SEBELUM fix
# itu ada -- dikonfirmasi via /api/signals bahwa ini SATU-SATUNYA baris
# yang resolved_at-nya jatuh di luar jam bursa (lihat scratchpad
# check_bad_resolutions.py), jadi TIDAK perlu backfill massal.
#
# User sudah eksplisit minta ini ("ya bikin open aja soalnya kan ga kena
# tp hari ini harus nunggu harga segitu") setelah penjelasan penuh soal
# root cause -- lihat memory ui_polish_icon_system_2026_07_08.md / sesi
# terkait.
#
# Dry-run by default (tanpa --apply, cuma print apa yang AKAN diubah).
import argparse
import sys

sys.path.insert(0, ".")

from core.database import get_db  # noqa: E402

TARGET_ID = 189
TARGET_KODE = "ARTO"


def main(apply: bool):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM signal_history WHERE id = ? AND kode = ?",
            (TARGET_ID, TARGET_KODE),
        ).fetchone()

        if row is None:
            print(f"Tidak ditemukan signal_history id={TARGET_ID} kode={TARGET_KODE} -- sudah diubah/dihapus sebelumnya?")
            return

        if row["status"] != "TP_HIT":
            print(f"Baris id={TARGET_ID} statusnya sekarang '{row['status']}', BUKAN 'TP_HIT' -- "
                  "kemungkinan sudah pernah dibenarkan. Tidak melakukan apa-apa.")
            return

        print("Baris SEBELUM diubah:")
        for k in ("id", "kode", "recorded_at", "entry_price", "status", "resolved_at",
                  "resolved_price", "return_pct", "days_to_resolve", "tp_level_hit"):
            print(f"  {k}: {row[k]}")

        if not apply:
            print("\n[DRY RUN] Tidak ada perubahan diterapkan. Jalankan ulang dengan --apply untuk benar-benar mengubah.")
            print("Akan diubah menjadi: status=OPEN, resolved_at=NULL, resolved_price=NULL, "
                  "return_pct=NULL, days_to_resolve=NULL, tp_level_hit=0")
            return

        conn.execute(
            """UPDATE signal_history
               SET status = 'OPEN', resolved_at = NULL, resolved_price = NULL,
                   return_pct = NULL, days_to_resolve = NULL, tp_level_hit = 0
               WHERE id = ? AND kode = ?""",
            (TARGET_ID, TARGET_KODE),
        )
        print(f"\n[APPLIED] id={TARGET_ID} ({TARGET_KODE}) dikembalikan ke status OPEN, "
              "tp_level_hit direset ke 0 (semua TP1/2/3 sebelumnya tidak valid, dari harga basi).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Benar-benar terapkan perubahan (default: dry-run)")
    args = parser.parse_args()
    main(apply=args.apply)
