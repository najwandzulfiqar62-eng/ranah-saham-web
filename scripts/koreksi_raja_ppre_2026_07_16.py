# =========================
# KOREKSI SEKALI-JALAN: RAJA & PPRE 2026-07-16
# =========================
# Dua baris rusak yang DIBUAT oleh bug lama pada pagi 2026-07-16 SEBELUM
# guard anomali/zona-fill/validasi-entry di-deploy (lihat commit yang sama
# dgn skrip ini). Koreksi DI TEMPAT, bukan hapus -- aturan tetap proyek
# (lihat preseden scripts/revert_arto_false_resolution.py).
#
# 1) RAJA (id=199): resolusi SL_HIT PALSU jam 09:14 -- resolved_price=920
#    padahal entry 4328 (-79%: skala harga split ~1:5, BUKAN pergerakan
#    pasar). Guard baru (audit_open_signals is_anomaly) tidak akan pernah
#    me-resolve ini. Koreksi: kembalikan ke OPEN (resolusinya di-void);
#    selanjutnya guard baru menjaga -- tetap OPEN sampai EXPIRED berbasis
#    waktu dgn return NULL kalau feed tidak kembali ke skala lama.
#
# 2) PPRE (id=248): sinyal lahir dgn entry >= harga pasar (fill terjadi 10
#    DETIK setelah dicatat -- bukti harga sudah di bawah entry saat lahir).
#    Validasi baru di record_top_picks menolak kelahiran spt ini. Koreksi:
#    EXPIRED_NO_ENTRY (rekomendasi tidak valid sejak lahir, TIDAK pernah
#    ada trade jujur), entry_filled_at di-void (klaim fill-nya keliru).
#
# Idempotent: hanya menyentuh baris yang MASIH dalam kondisi rusak persis.
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.database import get_db  # noqa: E402


def main():
    with get_db() as conn:
        cur = conn.execute('''
            UPDATE signal_history
            SET status='OPEN', resolved_at=NULL, resolved_price=NULL,
                return_pct=NULL, days_to_resolve=NULL
            WHERE id=199 AND kode='RAJA' AND status='SL_HIT'
              AND resolved_price IS NOT NULL AND resolved_price < entry_price * 0.6
        ''')
        print(f"RAJA id=199: {'di-void kembali ke OPEN' if cur.rowcount else 'tidak tersentuh (sudah benar/beda kondisi)'}")

        cur = conn.execute('''
            UPDATE signal_history
            SET status='EXPIRED_NO_ENTRY', resolved_at=datetime('now','localtime'),
                entry_filled_at=NULL, resolved_price=NULL, return_pct=NULL
            WHERE id=248 AND kode='PPRE' AND status='OPEN'
        ''')
        print(f"PPRE id=248: {'diinvalidasi EXPIRED_NO_ENTRY' if cur.rowcount else 'tidak tersentuh (sudah benar/beda kondisi)'}")


if __name__ == "__main__":
    main()
