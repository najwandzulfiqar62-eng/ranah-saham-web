"""One-off corrective backfill (BUKAN migrasi permanen): scripts/backfill_
pending_entry.py mengoreksi ANGKA entry_price/tp_pct/tp2_pct/tp3_pct/sl_pct
17 baris PENDING_ENTRY ke formula baru, TAPI tidak menyentuh STATUS-nya --
baris-baris itu tetap tercatat PENDING_ENTRY meski entry yang baru
(lebih dekat dari harga saat dicatat) SEBENARNYA sudah kena kalau dicek
pakai histori harga sungguhan sejak hari itu. Permintaan user langsung
setelah lihat BRMS masih "Menunggu Entry": "itu kan sinyal tanggal 9
harusnya udah kena tp dong nah nyesuain nya ama yg kmrn bukan hari ini
soalnya itu sinyal tanggal 9" -- perbaikan HARUS mereplay apa yang
BENERAN terjadi sejak recorded_at, bukan cuma menghitung ulang satu
angka statis.

Cara kerja: utk tiap baris PENDING_ENTRY, ambil histori HARIAN (Open/
High/Low/Close) dari recorded_date sampai HARI INI, lalu jalan MAJU hari
demi hari:
  1. Cari hari PERTAMA (>= recorded_date) yang Low <= entry_price -> itu
     hari entry "kena" (entry_filled_at). Recorded_date sendiri BOLEH jadi
     hari fill (SAMA presisi dgn get_hit_scenarios/_pick_chosen_scenario
     yang sudah dipakai backfill_open_entry_price.py -- tidak ada data
     intraday jam-menit di histori harian, jadi tidak bisa lebih presisi
     dari itu; ini keterbatasan yang SAMA diterima di seluruh backfill
     scripts lain di folder ini, bukan lookahead baru yang ditambahkan).
  2. Kalau TIDAK PERNAH kena sampai hari ini: cek umur sejak recorded_at
     -- >= MAX_ENTRY_WAIT_DAYS jadi EXPIRED_NO_ENTRY, kalau belum tetap
     PENDING_ENTRY (no_change_needed).
  3. Kalau kena di hari D: replay MAJU dari hari D (termasuk) memakai
     High/Low harian, SAMA PERSIS prioritas keputusan dgn audit_open_
     signals() di core/signal_history.py (SL_HIT diperiksa LEBIH DULU
     drpd TP per hari, tp_level_hit HANYA naik -- tidak pernah turun,
     EXPIRED dihitung dari umur recorded_at BUKAN entry_filled_at --
     detail lengkap di situ) -- berhenti di hari pertama yang mencapai
     kondisi akhir (TP_HIT/SL_HIT/EXPIRED), atau kalau sampai HARI INI
     belum ada yang final: status jadi OPEN (entry_filled_at diisi,
     tp_level_hit sesuai progres tertinggi yang benar2 tercapai).

HANYA menyentuh baris status='PENDING_ENTRY' saat ini (source TOP_PICK,
arah BUY -- satu2nya kombinasi yang bisa PENDING_ENTRY). Baris yang SUDAH
OPEN/resolved TIDAK PERNAH disentuh skrip ini.

Default DRY-RUN -- pakai --apply utk benar-benar menulis. TIDAK
sepenuhnya idempotent kalau dijalankan ulang SETELAH --apply (baris yang
sudah dikoreksi jadi OPEN/resolved tidak lagi PENDING_ENTRY, jadi
otomatis tidak terjaring lagi di query -- itu behaviour yang benar, bukan
bug).

Cara pakai:
    py -m scripts.replay_pending_entry_progress            # dry-run
    py -m scripts.replay_pending_entry_progress --apply     # eksekusi UPDATE sungguhan
"""
import argparse
import asyncio
from datetime import datetime, timedelta

from core.database import get_db
from core.signal_history import MAX_HOLD_DAYS, MAX_ENTRY_WAIT_DAYS
from scripts.backfill_open_entry_price import _fetch_history


def _fetch_pending_entry_rows() -> list[dict]:
    with get_db() as conn:
        rows = conn.execute('''
            SELECT id, kode, recorded_at, entry_price, tp_pct, tp2_pct, tp3_pct, sl_pct
            FROM signal_history
            WHERE status = 'PENDING_ENTRY' AND source = 'TOP_PICK' AND direction = 'BUY'
        ''').fetchall()
        return [dict(r) for r in rows]


def _replay_row(row: dict, df, today: "datetime.date") -> dict:
    """Murni fungsi (tidak I/O) -- gampang ditest dgn df sintetis. Returns
    dict beranotasi dgn 'action' (fill_and_open/fill_and_resolve/
    expire_no_entry/no_change_needed/skip_no_data/skip_no_history_before_
    date) dan field2 baru yang relevan."""
    recorded_at = datetime.fromisoformat(row["recorded_at"])
    recorded_date = recorded_at.date()

    if df is None:
        return {**row, "action": "skip_no_data", "detail": "data historis tidak tersedia"}

    df_since = df[(df.index.date >= recorded_date) & (df.index.date <= today)]
    if df_since.empty:
        return {**row, "action": "skip_no_history_before_date",
                "detail": f"tidak ada data historis sejak {recorded_date}"}

    entry = row["entry_price"]
    fill_date = None
    for dt, bar in df_since.iterrows():
        if float(bar["Low"]) <= entry:
            fill_date = dt.date()
            break

    if fill_date is None:
        # SAMA PERSIS dgn audit_pending_entries() live: age_days pakai
        # datetime.now() SUNGGUHAN (bukan tengah malam hari ini) -- kalau
        # tidak, sinyal yang direkam SETELAH tengah malam hari yang SAMA
        # (recorded_at jam-nya > 00:00) menghasilkan age_days NEGATIF
        # (bug NYATA ditemukan: PTRO/AGII, recorded_at '02:43:33' hari
        # ini, midnight-hari-ini dikurangi itu jadi -1 hari, bukan 0).
        age_days = (datetime.now() - recorded_at).days
        if age_days >= MAX_ENTRY_WAIT_DAYS:
            return {**row, "action": "expire_no_entry", "expire_date": today,
                    "detail": f"tidak pernah kena entry dalam {age_days} hari (>= {MAX_ENTRY_WAIT_DAYS})"}
        return {**row, "action": "no_change_needed",
                "detail": f"belum kena entry, baru {age_days} hari (< {MAX_ENTRY_WAIT_DAYS})"}

    tp1_price = entry * (1 + row["tp_pct"] / 100) if row["tp_pct"] is not None else None
    tp2_price = entry * (1 + row["tp2_pct"] / 100) if row["tp2_pct"] is not None else None
    tp3_price = entry * (1 + row["tp3_pct"] / 100) if row["tp3_pct"] is not None else None
    sl_price = entry * (1 - row["sl_pct"] / 100)

    if tp3_price is not None:
        configured_max, final_pct = 3, row["tp3_pct"]
    elif tp2_price is not None:
        configured_max, final_pct = 2, row["tp2_pct"]
    else:
        configured_max, final_pct = 1, row["tp_pct"]

    df_after_fill = df_since[df_since.index.date >= fill_date]
    tp_level_hit = 0
    for dt, bar in df_after_fill.iterrows():
        day = dt.date()
        low, high, close = float(bar["Low"]), float(bar["High"]), float(bar["Close"])
        # Jam 16:00 (perkiraan akhir sesi bursa WIB) -- BUKAN tengah malam
        # hari itu -- supaya hari yang SAMA dgn recorded_at (mis. entry
        # kena di hari sinyal itu sendiri direkam siang hari) tidak salah
        # dihitung age_days negatif (lihat catatan sama di atas).
        age_days = (datetime.combine(day, datetime.min.time()) + timedelta(hours=16) - recorded_at).days

        sl_hit = low <= sl_price
        reached_level = 3 if (tp3_price and high >= tp3_price) else \
            2 if (tp2_price and high >= tp2_price) else \
            1 if (tp1_price and high >= tp1_price) else 0

        if sl_hit:
            return {**row, "action": "fill_and_resolve", "fill_date": fill_date,
                    "resolve_date": day, "new_status": "SL_HIT",
                    "return_pct": -row["sl_pct"], "resolved_price": round(sl_price, 2),
                    "days_to_resolve": age_days, "tp_level_hit": tp_level_hit,
                    "detail": f"SL kena {day} (Low={low} <= sl={sl_price:.1f})"}
        if reached_level >= configured_max and reached_level > 0:
            return {**row, "action": "fill_and_resolve", "fill_date": fill_date,
                    "resolve_date": day, "new_status": "TP_HIT",
                    "return_pct": final_pct, "resolved_price": round(tp3_price or tp2_price or tp1_price, 2),
                    "days_to_resolve": age_days, "tp_level_hit": reached_level,
                    "detail": f"TP final kena {day} (High={high} >= {tp3_price or tp2_price or tp1_price:.1f})"}
        if reached_level > tp_level_hit:
            tp_level_hit = reached_level
        elif age_days >= MAX_HOLD_DAYS:
            return {**row, "action": "fill_and_resolve", "fill_date": fill_date,
                    "resolve_date": day, "new_status": "EXPIRED",
                    "return_pct": round((close / entry - 1) * 100, 2), "resolved_price": close,
                    "days_to_resolve": age_days, "tp_level_hit": tp_level_hit,
                    "detail": f"EXPIRED {day} (umur {age_days} hari >= {MAX_HOLD_DAYS})"}

    return {**row, "action": "fill_and_open", "fill_date": fill_date,
            "tp_level_hit": tp_level_hit,
            "detail": f"kena entry {fill_date}, masih OPEN sampai {today}"
                       + (f", tp_level_hit={tp_level_hit}" if tp_level_hit else "")}


def _print_report(results: list[dict]) -> None:
    print()
    print(f"{'KODE':6} {'ACTION':20} DETAIL")
    for r in results:
        print(f"{r['kode']:6} {r['action']:20} {r['detail']}")

    counts = {}
    for r in results:
        counts[r["action"]] = counts.get(r["action"], 0) + 1
    print()
    print("Ringkasan: " + ", ".join(f"{v} {k}" for k, v in sorted(counts.items())))


def apply_updates(results: list[dict]) -> int:
    n = 0
    with get_db() as conn:
        for r in results:
            if r["action"] == "fill_and_open":
                conn.execute(
                    "UPDATE signal_history SET status = 'OPEN', entry_filled_at = ?, tp_level_hit = ? "
                    "WHERE id = ? AND status = 'PENDING_ENTRY'",
                    (f"{r['fill_date']} 16:00:00", r["tp_level_hit"], r["id"]),
                )
                n += 1
            elif r["action"] == "fill_and_resolve":
                conn.execute('''
                    UPDATE signal_history
                    SET status = ?, entry_filled_at = ?, resolved_at = ?, resolved_price = ?,
                        return_pct = ?, days_to_resolve = ?, tp_level_hit = ?
                    WHERE id = ? AND status = 'PENDING_ENTRY'
                ''', (r["new_status"], f"{r['fill_date']} 16:00:00", f"{r['resolve_date']} 16:00:00",
                      r["resolved_price"], r["return_pct"], r["days_to_resolve"], r["tp_level_hit"], r["id"]))
                n += 1
            elif r["action"] == "expire_no_entry":
                conn.execute(
                    "UPDATE signal_history SET status = 'EXPIRED_NO_ENTRY', resolved_at = ? "
                    "WHERE id = ? AND status = 'PENDING_ENTRY'",
                    (f"{r['expire_date']} 16:00:00", r["id"]),
                )
                n += 1
    return n


async def run(apply: bool) -> list[dict]:
    rows = _fetch_pending_entry_rows()
    if not rows:
        print("Tidak ada baris PENDING_ENTRY (TOP_PICK, BUY) yang perlu dicek.")
        return []

    kodes = sorted({r["kode"] for r in rows})
    print(f"Mengambil data historis utk {len(kodes)} kode...")
    history = await _fetch_history(kodes)

    today = datetime.now().date()
    results = [_replay_row(row, history.get(row["kode"]), today) for row in rows]
    _print_report(results)

    if not apply:
        print("\n[DRY RUN] Tidak ada perubahan ditulis ke database. Jalankan dgn --apply utk menerapkan.")
        return results

    n = apply_updates(results)
    print(f"\n[APPLIED] {n} baris PENDING_ENTRY sudah di-replay ke status sebenarnya.")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Benar-benar menulis UPDATE ke database (default: dry-run)")
    args = parser.parse_args()
    asyncio.run(run(apply=args.apply))
