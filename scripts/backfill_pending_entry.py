"""One-off corrective backfill (BUKAN migrasi permanen -- pola sama dgn
scripts/backfill_open_entry_price.py & backfill_open_sl_tp.py): sinyal
PENDING_ENTRY yang SUDAH kadung tercatat pakai entry_price dari formula
pullback LAMA (S1 pivot -> MA20 -> 1x ATR, semuanya 3-10%+ di bawah
harga -- lihat catatan lengkap di core/trading_plan.py::_determine_entry_
points) dikoreksi ke formula BARU (PULLBACK_DISCOUNT_PCT, diskon kecil
0,5% dari harga) -- permintaan user langsung setelah lihat data nyata:
"nih kaya gini kejauhan keburu org pada tp saya mintanya entry pada hari
itu bukan nunggu lama kaya gitu", lalu eksplisit minta baris yang SUDAH
kadung tercatat ikut dikoreksi juga: "koreksi ke harga pada hari itu
dengan logika entry skrg biar keliatan profitnya pada hari ini".

BEDA dari backfill_open_entry_price.py: baris PENDING_ENTRY belum pernah
"kena" apa pun (belum ada posisi aktif), jadi TIDAK PERLU cek skenario
mana yang historically hit (get_hit_scenarios/_pick_chosen_scenario) --
cukup hitung ULANG persis seperti confidence() akan hitung hari itu
(recommended_scenario: pullback ATAU breakout, SAMA logic yg dipakai
live), pakai data HANYA sampai recorded_date (tidak lookahead -- SAMA
disiplin dgn backfill lain). entry_price, tp_pct, tp2_pct, tp3_pct,
sl_pct SEMUA direkomputasi bersamaan (bukan cuma entry_price sendirian)
supaya baris tetap konsisten secara internal -- beda dgn backfill OPEN
yang sengaja parsial krn entry lama sudah terverifikasi benar.

HANYA menyentuh baris status='PENDING_ENTRY' (source TOP_PICK, arah BUY --
SATU-SATUNYA kombinasi yang bisa PENDING_ENTRY saat ini, lihat catatan di
core/signal_history.py::record_top_picks). Baris OPEN/resolved TIDAK
PERNAH disentuh skrip ini.

Default DRY-RUN -- pakai --apply utk benar-benar menulis. Aman dijalankan
berulang: baris yang sudah dekat/optimal dilaporkan 'no_change_needed'.

Cara pakai:
    py scripts/backfill_pending_entry.py            # dry-run, cuma laporan
    py scripts/backfill_pending_entry.py --apply     # eksekusi UPDATE sungguhan
"""
import argparse
import asyncio
from datetime import datetime

from core.database import get_db
from core.trading_plan import calculate_fixed_entry_levels_from_df
from scripts.backfill_open_entry_price import _as_of, _fetch_history

# Kalau selisih entry_price lama vs baru di bawah ini, anggap sudah cukup
# dekat (tidak perlu UPDATE) -- menghindari noise pembulatan/idempotency.
MIN_CHANGE_PCT = 0.2


def _fetch_pending_entry_rows() -> list[dict]:
    with get_db() as conn:
        rows = conn.execute('''
            SELECT id, kode, recorded_at, entry_price, tp_pct, tp2_pct, tp3_pct, sl_pct
            FROM signal_history
            WHERE status = 'PENDING_ENTRY' AND source = 'TOP_PICK' AND direction = 'BUY'
        ''').fetchall()
        return [dict(r) for r in rows]


def _evaluate_row(row: dict, df) -> dict:
    recorded_date = datetime.fromisoformat(row["recorded_at"]).date()

    if df is None:
        return {**row, "action": "skip_no_data", "new_entry": None,
                "detail": "data historis tidak tersedia"}

    df_asof = _as_of(df, recorded_date)
    if df_asof is None:
        return {**row, "action": "skip_no_history_before_date", "new_entry": None,
                "detail": f"tidak ada data historis sebelum/pada {recorded_date}"}

    plan = calculate_fixed_entry_levels_from_df(df_asof, "")
    scenarios = (plan or {}).get("scenarios") or {}
    if not scenarios:
        return {**row, "action": "skip_no_scenario", "new_entry": None,
                "detail": "gagal hitung skenario (data < 50 baris as-of tanggal itu)"}

    # SAMA PERSIS dgn logic _confidence_raw_signals() di web/app.py --
    # pilih recommended_scenario (pullback/breakout), fallback pullback
    # lalu normal kalau entah kenapa tidak ada.
    recommended_key = plan.get("recommended_scenario", "pullback")
    chosen = scenarios.get(recommended_key) or scenarios.get("pullback") or scenarios.get("normal")
    if chosen is None:
        return {**row, "action": "skip_no_scenario", "new_entry": None,
                "detail": "tidak ada skenario yang bisa dipilih"}

    new_entry = chosen["entry"]
    old_entry = row["entry_price"]
    pct_change = abs(new_entry - old_entry) / old_entry * 100 if old_entry else 999
    if pct_change < MIN_CHANGE_PCT:
        return {**row, "action": "no_change_needed", "new_entry": new_entry,
                "detail": f"skenario {chosen['key']}, selisih cuma {pct_change:.2f}%"}

    return {**row, "action": "update", "new_entry": new_entry,
            "new_tp_pct": chosen["tp1_pct"], "new_tp2_pct": chosen["tp2_pct"], "new_tp3_pct": chosen["tp3_pct"],
            "new_sl_pct": chosen["risk_pct"],
            "detail": f"skenario {chosen['key']}: entry {old_entry} -> {new_entry} "
                      f"({pct_change:.1f}% berbeda)"}


def _print_report(results: list[dict]) -> None:
    print()
    print(f"{'KODE':6} {'OLD_ENTRY':>10} {'NEW_ENTRY':>10} {'ACTION':24} DETAIL")
    for r in results:
        new_e = f"{r['new_entry']:.0f}" if r["new_entry"] is not None else "-"
        print(f"{r['kode']:6} {r['entry_price']:>10.0f} {new_e:>10} {r['action']:24} {r['detail']}")

    counts = {}
    for r in results:
        counts[r["action"]] = counts.get(r["action"], 0) + 1
    print()
    print("Ringkasan: " + ", ".join(f"{v} {k}" for k, v in sorted(counts.items())))


def apply_updates(results: list[dict]) -> int:
    """Tulis entry_price/tp_pct/tp2_pct/tp3_pct/sl_pct BARU ke DB utk
    baris ber-action 'update' saja -- status/recorded_at/dst tidak
    disentuh, dan baris yang BUKAN PENDING_ENTRY tidak pernah masuk sini
    sama sekali (sudah difilter di _fetch_pending_entry_rows)."""
    to_update = [r for r in results if r["action"] == "update"]
    with get_db() as conn:
        for r in to_update:
            conn.execute(
                "UPDATE signal_history SET entry_price = ?, tp_pct = ?, tp2_pct = ?, tp3_pct = ?, sl_pct = ? "
                "WHERE id = ? AND status = 'PENDING_ENTRY'",
                (r["new_entry"], r["new_tp_pct"], r["new_tp2_pct"], r["new_tp3_pct"], r["new_sl_pct"], r["id"]),
            )
    return len(to_update)


async def run(apply: bool) -> list[dict]:
    rows = _fetch_pending_entry_rows()
    if not rows:
        print("Tidak ada baris PENDING_ENTRY (TOP_PICK, BUY) yang perlu dicek.")
        return []

    kodes = sorted({r["kode"] for r in rows})
    print(f"Mengambil data historis utk {len(kodes)} kode...")
    history = await _fetch_history(kodes)

    results = [_evaluate_row(row, history.get(row["kode"])) for row in rows]
    _print_report(results)

    if not apply:
        print("\n[DRY RUN] Tidak ada perubahan ditulis ke database. Jalankan dgn --apply utk menerapkan.")
        return results

    n = apply_updates(results)
    print(f"\n[APPLIED] {n} baris PENDING_ENTRY sudah dikoreksi ke formula entry baru.")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Benar-benar menulis UPDATE ke database (default: dry-run)")
    args = parser.parse_args()
    asyncio.run(run(apply=args.apply))
