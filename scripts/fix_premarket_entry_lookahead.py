"""One-off corrective backfill (BUKAN migrasi permanen): root-cause fix utk
bug lookahead YANG DITEMUKAN lewat laporan user langsung ("elsa ama pgeo
aja kmrn harusnya hari ini udah profit bukan kena sl").

BUG: scripts/backfill_pending_entry.py (dan replay_pending_entry_progress.py
yang jalan sesudahnya) memotong histori harga pakai `date <= recorded_date`
SAJA -- TIDAK peduli JAM recorded_at. Untuk sinyal yang direkam SEBELUM
bursa buka (00:00-08:59 WIB, mis. batch 02:43 WIB tanggal 2026-07-10),
"date <= recorded_date" tetap MENYERTAKAN bar HARI ITU SENDIRI -- padahal
bar itu closing-nya baru terbentuk jam 16:00 WIB, JAM-JAM SETELAH sinyal
direkam. Entry yang dihasilkan jadi memakai info yang BELUM ADA saat
sinyal itu sendiri dicatat -- lookahead bias nyata, KELAS BUG YANG SAMA
dgn bug ARTO 00:01 WIB yang sudah pernah ditemukan+diperbaiki di
_is_bursa_trading_hours() (lihat core/signal_history.py), cuma di jalur
kode yang berbeda (backfill, bukan audit live).

DAMPAK TERVERIFIKASI (ELSA/PGEO, dicek manual thd data asli sebelum skrip
ini ditulis): entry yang di-backfill SALAH memilih skenario 'breakout'
(krn rally hari itu, yang BELUM TERJADI saat sinyal direkam, membuatnya
KELIHATAN seolah sudah breakout) -- padahal skenario yang BENAR (dihitung
cuma dari data SEBELUM sinyal direkam) adalah 'pullback', dgn entry yang
JAUH LEBIH RENDAH. Utk PGEO ini artinya entry yang benar TETAP kena DAN
TP1 tercapai hari yang sama (user BENAR, seharusnya profit) -- utk ELSA
entry yang benar TERNYATA TIDAK PERNAH kena sama sekali (saham gap naik
melewati level pullback yang realistis, tidak pernah turun ke situ) --
BUKAN profit, BUKAN rugi, tetap PENDING_ENTRY yang jujur. Skrip ini
TIDAK memaksa hasil jadi "profit" utk menyenangkan siapa pun -- angka
mengikuti data apa adanya, sama prinsip SL_HIT ditampilkan setransparan
TP_HIT di seluruh proyek ini.

CARA KERJA:
1. Cari SEMUA baris source=TOP_PICK/BUY yang recorded_at JAMNYA sebelum
   09:00 WIB DAN tanggalnya >= 2026-07-09 (hari fitur PENDING_ENTRY ini
   mulai jalan -- scope dibatasi supaya TIDAK PERNAH menyentuh histori
   organik yang lebih lama, dari sebelum bug/fitur ini bahkan ada),
   TIDAK PEDULI status SAAT INI (PENDING_ENTRY/OPEN/SL_HIT/TP_HIT/
   EXPIRED/EXPIRED_NO_ENTRY) -- SEMUANYA berpotensi tercemar backfill/
   replay yang salah hari ini.
2. Hitung ULANG entry_price/tp_pct/tp2_pct/tp3_pct/sl_pct pakai cutoff
   yang BENAR: kalau recorded_at jamnya < 09:00 WIB, cutoff-nya HARI
   SEBELUMNYA (bukan hari itu sendiri) -- baru pakai recommended_scenario
   (pullback/breakout) dari data yang BENAR-BENAR sudah ada saat itu.
3. RESET baris ke baseline PENDING_ENTRY bersih (entry/tp/sl baru,
   status/entry_filled_at/resolved_at/dst dikosongkan) -- fill/resolve
   sebelumnya dihitung dari entry yang salah, jadi TIDAK bisa dipertahankan.
4. Replay MAJU dari cutoff yang benar (reuse _replay_row dari
   replay_pending_entry_progress.py, TIDAK diubah -- logic replay-nya
   sendiri sudah benar, cuma titik AWAL-nya yang perlu dikoreksi).

Default DRY-RUN -- pakai --apply utk benar-benar menulis.

Cara pakai:
    py -m scripts.fix_premarket_entry_lookahead            # dry-run
    py -m scripts.fix_premarket_entry_lookahead --apply     # eksekusi UPDATE sungguhan
"""
import argparse
import asyncio
from datetime import datetime, timedelta

from core.database import get_db
from core.trading_plan import calculate_fixed_entry_levels_from_df
from scripts.backfill_open_entry_price import _fetch_history
from scripts.replay_pending_entry_progress import _replay_row

MARKET_OPEN_HOUR = 9  # 09:00 WIB, sama konstanta dgn _is_bursa_trading_hours()

# Tanggal fitur PENDING_ENTRY ini mulai jalan -- scope pencarian baris
# TIDAK PERNAH mundur sebelum ini, supaya tidak pernah menyentuh histori
# organik dari sebelum bug ini bahkan mungkin ada.
FEATURE_START_DATE = "2026-07-09"

# BUG NYATA ditemukan lewat dry-run PERTAMA skrip ini sendiri (sebelum
# apply): kondisi "direkam sebelum jam bursa" SAJA (tanpa syarat lain)
# TERNYATA JUGA menangkap ARTO id=193 -- baris yang SUDAH resolved TP_HIT
# SUNGGUHAN (resolved_at 2026-07-09 15:51:26, jam bursa asli, entry_
# filled_at NULL krn baris itu direkam SEBELUM fitur PENDING_ENTRY ini
# bahkan ada, jadi lewat jalur OPEN langsung yang lama) -- kalau sampai
# ke-apply, itu akan MENGHAPUS/MENULIS ULANG hasil track record sungguhan
# yang sudah terjadi, melanggar prinsip inti proyek ini (tidak pernah
# menulis ulang sinyal yang sudah resolved). Query DIPERKETAT: HANYA
# baris yang punya "jejak" nyata pernah disentuh backfill_pending_entry.py
# / replay_pending_entry_progress.py HARI INI -- entry_filled_at/
# resolved_at dgn stempel jam '16:00:00' PERSIS (pola unik yang skrip2 itu
# pakai, TIDAK PERNAH dihasilkan audit_pending_entries()/audit_open_
# signals() sungguhan yang selalu pakai datetime.now() -- nyaris mustahil
# pas ':00:00' sampai ke detik), ATAU masih PENDING_ENTRY murni (belum
# sempat di-replay krn belum kena entry) DAN direkam pre-market baru2 ini.
def _fetch_affected_rows() -> list[dict]:
    with get_db() as conn:
        rows = conn.execute('''
            SELECT id, kode, recorded_at, entry_price, tp_pct, tp2_pct, tp3_pct, sl_pct, status
            FROM signal_history
            WHERE source = 'TOP_PICK' AND direction = 'BUY'
              AND (
                    entry_filled_at LIKE '%16:00:00'
                    OR resolved_at LIKE '%16:00:00'
                    OR (
                        status = 'PENDING_ENTRY'
                        AND date(recorded_at) >= ?
                        AND CAST(strftime('%H', recorded_at) AS INTEGER) < ?
                    )
              )
        ''', (FEATURE_START_DATE, MARKET_OPEN_HOUR)).fetchall()
        return [dict(r) for r in rows]


def _correct_as_of_cutoff(df, recorded_at: datetime):
    """SAMA seperti _as_of() di backfill_open_entry_price.py, TAPI sadar
    JAM -- kalau recorded_at sebelum bursa buka, bar HARI ITU SENDIRI
    belum ada sama sekali saat itu, cutoff mundur ke hari sebelumnya."""
    recorded_date = recorded_at.date()
    if recorded_at.hour < MARKET_OPEN_HOUR:
        cutoff_date = recorded_date - timedelta(days=1)
    else:
        cutoff_date = recorded_date
    truncated = df[df.index.date <= cutoff_date]
    if truncated.empty:
        return None
    return truncated


def _recompute_row(row: dict, df) -> dict:
    recorded_at = datetime.fromisoformat(row["recorded_at"])

    if df is None:
        return {**row, "action": "skip_no_data", "detail": "data historis tidak tersedia"}

    df_asof = _correct_as_of_cutoff(df, recorded_at)
    if df_asof is None:
        return {**row, "action": "skip_no_history_before_date",
                "detail": f"tidak ada data historis sebelum {recorded_at.date()} (pre-market)"}

    plan = calculate_fixed_entry_levels_from_df(df_asof, "")
    scenarios = (plan or {}).get("scenarios") or {}
    if not scenarios:
        return {**row, "action": "skip_no_scenario", "detail": "gagal hitung skenario"}

    recommended_key = plan.get("recommended_scenario", "pullback")
    chosen = scenarios.get(recommended_key) or scenarios.get("pullback") or scenarios.get("normal")
    if chosen is None:
        return {**row, "action": "skip_no_scenario", "detail": "tidak ada skenario yang bisa dipilih"}

    new_entry = chosen["entry"]
    old_entry = row["entry_price"]
    pct_change = abs(new_entry - old_entry) / old_entry * 100 if old_entry else 999

    corrected_row = {
        "id": row["id"], "kode": row["kode"], "recorded_at": row["recorded_at"],
        "entry_price": new_entry, "tp_pct": chosen["tp1_pct"], "tp2_pct": chosen["tp2_pct"],
        "tp3_pct": chosen["tp3_pct"], "sl_pct": chosen["risk_pct"],
    }
    return {**row, "action": "recompute", "new_entry": new_entry, "corrected_row": corrected_row,
            "old_status": row["status"], "pct_change": pct_change,
            "detail": f"skenario {chosen['key']} (as-of {df_asof.index[-1].date()}): "
                      f"entry {old_entry} -> {new_entry} ({pct_change:.1f}% berbeda), "
                      f"status lama={row['status']}"}


def _print_report(recomputed: list[dict], replayed: list[dict]) -> None:
    print()
    print("=== TAHAP 1: entry_price dikoreksi (cutoff sadar jam bursa) ===")
    print(f"{'KODE':6} {'OLD_ENTRY':>10} {'NEW_ENTRY':>10} {'OLD_STATUS':14} DETAIL")
    for r in recomputed:
        new_e = f"{r['new_entry']:.0f}" if r.get("new_entry") is not None else "-"
        print(f"{r['kode']:6} {r['entry_price']:>10.0f} {new_e:>10} {r.get('old_status',''):14} {r['detail']}")

    print()
    print("=== TAHAP 2: status di-replay ulang dari entry yang sudah benar ===")
    print(f"{'KODE':6} {'ACTION':20} DETAIL")
    for r in replayed:
        print(f"{r['kode']:6} {r['action']:20} {r['detail']}")

    counts = {}
    for r in replayed:
        counts[r["action"]] = counts.get(r["action"], 0) + 1
    print()
    print("Ringkasan status akhir: " + ", ".join(f"{v} {k}" for k, v in sorted(counts.items())))


def apply_updates(recomputed: list[dict], replayed: list[dict]) -> int:
    n = 0
    with get_db() as conn:
        for r in recomputed:
            if r["action"] != "recompute":
                continue
            cr = r["corrected_row"]
            # RESET penuh ke baseline PENDING_ENTRY bersih -- fill/resolve
            # SEBELUMNYA dihitung dari entry yang salah (lookahead), tidak
            # bisa dipertahankan sebagian pun.
            conn.execute('''
                UPDATE signal_history
                SET entry_price = ?, tp_pct = ?, tp2_pct = ?, tp3_pct = ?, sl_pct = ?,
                    status = 'PENDING_ENTRY', entry_filled_at = NULL,
                    resolved_at = NULL, resolved_price = NULL, return_pct = NULL,
                    days_to_resolve = NULL, tp_level_hit = 0
                WHERE id = ?
            ''', (cr["entry_price"], cr["tp_pct"], cr["tp2_pct"], cr["tp3_pct"], cr["sl_pct"], r["id"]))
            n += 1

        for r in replayed:
            if r["action"] == "fill_and_open":
                conn.execute(
                    "UPDATE signal_history SET status = 'OPEN', entry_filled_at = ?, tp_level_hit = ? "
                    "WHERE id = ? AND status = 'PENDING_ENTRY'",
                    (f"{r['fill_date']} 16:00:00", r["tp_level_hit"], r["id"]),
                )
            elif r["action"] == "fill_and_resolve":
                conn.execute('''
                    UPDATE signal_history
                    SET status = ?, entry_filled_at = ?, resolved_at = ?, resolved_price = ?,
                        return_pct = ?, days_to_resolve = ?, tp_level_hit = ?
                    WHERE id = ? AND status = 'PENDING_ENTRY'
                ''', (r["new_status"], f"{r['fill_date']} 16:00:00", f"{r['resolve_date']} 16:00:00",
                      r["resolved_price"], r["return_pct"], r["days_to_resolve"], r["tp_level_hit"], r["id"]))
            elif r["action"] == "expire_no_entry":
                conn.execute(
                    "UPDATE signal_history SET status = 'EXPIRED_NO_ENTRY', resolved_at = ? "
                    "WHERE id = ? AND status = 'PENDING_ENTRY'",
                    (f"{r['expire_date']} 16:00:00", r["id"]),
                )
            # no_change_needed -- baris SUDAH direset ke PENDING_ENTRY di
            # atas, itu SUDAH final utk kasus ini, tidak ada lagi yg ditulis.
    return n


async def run(apply: bool) -> tuple[list[dict], list[dict]]:
    rows = _fetch_affected_rows()
    if not rows:
        print("Tidak ada baris pre-market (TOP_PICK, BUY, sebelum jam bursa) yang perlu dicek.")
        return [], []

    kodes = sorted({r["kode"] for r in rows})
    print(f"Ditemukan {len(rows)} baris direkam sebelum jam bursa buka. Mengambil data historis utk {len(kodes)} kode...")
    history = await _fetch_history(kodes)

    recomputed = [_recompute_row(row, history.get(row["kode"])) for row in rows]

    today = datetime.now().date()
    replayed = []
    for r in recomputed:
        if r["action"] != "recompute":
            continue
        replay_row_input = {**r["corrected_row"]}
        result = _replay_row(replay_row_input, history.get(r["kode"]), today)
        replayed.append(result)

    _print_report(recomputed, replayed)

    if not apply:
        print("\n[DRY RUN] Tidak ada perubahan ditulis ke database. Jalankan dgn --apply utk menerapkan.")
        return recomputed, replayed

    n = apply_updates(recomputed, replayed)
    print(f"\n[APPLIED] {n} baris pre-market sudah dikoreksi (entry + status direplay ulang).")
    return recomputed, replayed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Benar-benar menulis UPDATE ke database (default: dry-run)")
    args = parser.parse_args()
    asyncio.run(run(apply=args.apply))
