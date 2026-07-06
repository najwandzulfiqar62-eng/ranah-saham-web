"""One-off corrective backfill (BUKAN migrasi permanen -- lihat catatan di
bawah): sinyal OPEN yang SL-nya masih pakai floor MIN_SL_PCT generik,
padahal skenario Trading Plan yang direkonstruksi ulang SEKARANG (setelah
core/trading_plan.py::_calc_entry_levels() diperbaiki utk turun ke support
S2/S3/S4 kalau S1 kedeketan, bukan langsung lompat ke floor persentase --
permintaan user: "sl nya kedeketan, kalo bisa sl nya di support") ternyata
punya support SUNGGUHAN yang lebih lebar dari floor -- SL/TP1/TP2/TP3
dikoreksi mengikuti support asli itu.

HANYA memperlebar (TIDAK PERNAH mempersempit): kalau risk_pct hasil
rekonstruksi ternyata tidak lebih lebar dari yang tersimpan, baris itu
dilewati (dianggap sudah optimal, JANGAN dipersempit).

Beda dari scripts/backfill_open_entry_price.py: entry_price di sini TIDAK
diubah sama sekali (sudah benar, dari backfill sebelumnya atau rekaman
baru) -- jadi verifikasi "skenario mana yang dipakai" dilakukan dengan
mencocokkan entry SKENARIO YANG DIREKONSTRUKSI terhadap entry_price yang
SUDAH TERSIMPAN (bukan mencocokkan persentase lama, karena persentase itu
sendiri yang mau diperbaiki -- mencocokkan ke situ akan menolak SEMUA
baris yang justru butuh dikoreksi).

HANYA menyentuh baris status='OPEN' (source TOP_PICK/SMART_MONEY, arah
BUY) -- sama seperti backfill entry_price, baris resolved TIDAK PERNAH
disentuh (return_pct/resolved_price sudah final, mengubah sl_pct sekarang
akan membuatnya tidak konsisten dgn hasil yang sudah tercatat).

Default DRY-RUN -- pakai --apply utk benar-benar menulis. Aman dijalankan
berulang: baris yang sudah optimal dilaporkan 'no_change_needed'.

Cara pakai:
    py scripts/backfill_open_sl_tp.py            # dry-run, cuma laporan
    py scripts/backfill_open_sl_tp.py --apply     # eksekusi UPDATE sungguhan
"""
import argparse
import asyncio
from datetime import datetime

from core.database import get_db
from core.trading_plan import calculate_fixed_entry_levels_from_df
from scripts.backfill_open_entry_price import _as_of, _fetch_history, _pick_chosen_scenario

# Toleransi selisih entry_price tersimpan vs entry skenario yang
# direkonstruksi (dalam %) -- dipakai utk MENGENALI skenario mana yang
# dipakai baris ini (bukan mencocokkan sl_pct/tp_pct lama, krn itu justru
# yang mau dikoreksi).
ENTRY_MATCH_TOLERANCE_PCT = 0.5

# risk_pct baru harus lebih lebar minimal ini (poin persentase) drpd yang
# tersimpan supaya dianggap perlu di-update -- menghindari noise
# pembulatan/idempotency saat dijalankan berulang.
MIN_WIDEN_PCT = 0.1


def _fetch_open_rows() -> list[dict]:
    with get_db() as conn:
        rows = conn.execute('''
            SELECT id, kode, recorded_at, entry_price, tp_pct, tp2_pct, tp3_pct, sl_pct
            FROM signal_history
            WHERE status = 'OPEN' AND source IN ('TOP_PICK', 'SMART_MONEY') AND direction = 'BUY'
        ''').fetchall()
        return [dict(r) for r in rows]


def _evaluate_row(row: dict, df) -> dict:
    recorded_date = datetime.fromisoformat(row["recorded_at"]).date()

    if df is None:
        return {**row, "action": "skip_no_data", "new_sl_pct": None,
                "detail": "data historis tidak tersedia"}

    df_asof = _as_of(df, recorded_date)
    if df_asof is None:
        return {**row, "action": "skip_no_history_before_date", "new_sl_pct": None,
                "detail": f"tidak ada data historis sebelum/pada {recorded_date}"}

    plan = calculate_fixed_entry_levels_from_df(df_asof, "")
    scenarios = (plan or {}).get("scenarios") or {}
    if not scenarios:
        return {**row, "action": "skip_no_scenario", "new_sl_pct": None,
                "detail": "gagal hitung skenario (data < 50 baris as-of tanggal itu)"}

    low_today = float(df_asof["Low"].iloc[-1])
    high_today = float(df_asof["High"].iloc[-1])
    chosen = _pick_chosen_scenario(scenarios, low_today, high_today)
    if chosen is None:
        return {**row, "action": "skip_no_scenario", "new_sl_pct": None,
                "detail": "tidak ada skenario yang bisa dipilih"}

    entry_price = row["entry_price"]
    entry_diff_pct = (abs(chosen["entry"] - entry_price) / entry_price * 100) if entry_price else 999
    if entry_diff_pct > ENTRY_MATCH_TOLERANCE_PCT:
        return {**row, "action": "skip_low_confidence", "new_sl_pct": chosen["risk_pct"],
                "detail": f"entry_price tersimpan {entry_price} tidak cocok dgn skenario "
                          f"{chosen['key']} (entry rekonstruksi={chosen['entry']}, selisih {entry_diff_pct:.2f}%)"}

    new_risk_pct = chosen["risk_pct"]
    if new_risk_pct <= row["sl_pct"] + MIN_WIDEN_PCT:
        return {**row, "action": "no_change_needed", "new_sl_pct": new_risk_pct,
                "detail": f"skenario {chosen['key']}, risk_pct baru ({new_risk_pct}) tidak lebih "
                          f"lebar dari yang tersimpan ({row['sl_pct']})"}

    return {**row, "action": "update", "new_sl_pct": new_risk_pct,
            "new_tp_pct": chosen["tp1_pct"], "new_tp2_pct": chosen["tp2_pct"], "new_tp3_pct": chosen["tp3_pct"],
            "detail": f"skenario {chosen['key']}: sl {row['sl_pct']}% -> {new_risk_pct}% "
                      f"(support asli, bukan floor)"}


def _print_report(results: list[dict]) -> None:
    print()
    print(f"{'KODE':6} {'OLD_SL%':>8} {'NEW_SL%':>8} {'ACTION':20} DETAIL")
    for r in results:
        new_sl = f"{r['new_sl_pct']:.1f}" if r["new_sl_pct"] is not None else "-"
        print(f"{r['kode']:6} {r['sl_pct']:>8.1f} {new_sl:>8} {r['action']:20} {r['detail']}")

    counts = {}
    for r in results:
        counts[r["action"]] = counts.get(r["action"], 0) + 1
    print()
    print("Ringkasan: " + ", ".join(f"{v} {k}" for k, v in sorted(counts.items())))


def apply_updates(results: list[dict]) -> int:
    """Tulis sl_pct/tp_pct/tp2_pct/tp3_pct BARU ke DB utk baris ber-action
    'update' saja -- entry_price/status/dst tidak disentuh."""
    to_update = [r for r in results if r["action"] == "update"]
    with get_db() as conn:
        for r in to_update:
            conn.execute(
                "UPDATE signal_history SET sl_pct = ?, tp_pct = ?, tp2_pct = ?, tp3_pct = ? WHERE id = ?",
                (r["new_sl_pct"], r["new_tp_pct"], r["new_tp2_pct"], r["new_tp3_pct"], r["id"]),
            )
    return len(to_update)


async def run(apply: bool) -> list[dict]:
    rows = _fetch_open_rows()
    if not rows:
        print("Tidak ada baris OPEN (TOP_PICK/SMART_MONEY, BUY) yang perlu dicek.")
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
    print(f"\n[APPLIED] {n} baris sl_pct/tp_pct sudah diperlebar.")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Benar-benar menulis UPDATE ke database (default: dry-run)")
    args = parser.parse_args()
    asyncio.run(run(apply=args.apply))
