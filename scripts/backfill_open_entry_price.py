"""One-off corrective backfill (BUKAN migrasi permanen -- lihat catatan di
bawah): sebagian sinyal OPEN di signal_history direkam SEBELUM perbaikan
"entry_price = level skenario Trading Plan yang beneran kena hari itu"
(sebelumnya entry_price selalu memakai harga sekarang/live, terlepas dari
skenario apa yang sebenarnya dipakai utk menghitung tp_pct/sl_pct).

Script ini merekonstruksi ULANG skenario mana yang kena PERSIS pada hari
sinyal itu direkam (pakai data historis, DIPOTONG supaya tidak ada
lookahead -- cuma pakai data sampai HARI ITU, sama seperti confidence()
akan lihat kalau dijalankan hari itu), lalu mengoreksi entry_price HANYA
kalau confidence check-nya lolos (tp_pct/sl_pct yang tersimpan cocok
dengan skenario yang direkonstruksi, dalam toleransi kecil) -- baris yang
tidak cocok (kemungkinan direkam kode lama sebelum skenario ada sama
sekali) SENGAJA dilewati, tidak ditebak.

HANYA menyentuh baris status='OPEN' (source TOP_PICK/SMART_MONEY, arah
BUY) -- baris yang SUDAH resolved (TP_HIT/SL_HIT/EXPIRED) TIDAK PERNAH
disentuh: return_pct/resolved_price-nya sudah dihitung dari entry_price
LAMA, mengubah entry_price sekarang akan membuat hasilnya tidak lagi
konsisten dengan angkanya sendiri -- sama saja menulis ulang hasil track
record yang sudah terjadi, yang project ini sengaja tidak pernah lakukan.

Default DRY-RUN (tidak menulis apa pun ke DB) -- pakai --apply utk
benar-benar menjalankan UPDATE. Aman dijalankan berulang (idempotent):
baris yang entry_price-nya sudah benar dilaporkan "no_change_needed" dan
dilewati, TIDAK di-UPDATE ulang.

Cara pakai:
    py scripts/backfill_open_entry_price.py            # dry-run, cuma laporan
    py scripts/backfill_open_entry_price.py --apply     # eksekusi UPDATE sungguhan
"""
import argparse
import asyncio
from datetime import datetime

import pandas as pd

from core.async_yf import async_download_many
from core.database import get_db
from core.stock_data import fix_yf_columns
from core.trading_plan import calculate_fixed_entry_levels_from_df, get_hit_scenarios

# Toleransi selisih tp_pct/sl_pct saat mencocokkan skenario yang
# direkonstruksi dgn yang tersimpan (poin persentase absolut) -- dipakai
# sbg confidence check, BUKAN cara utama menentukan skenario (skenario
# ditentukan deterministik dari get_hit_scenarios, ini cuma verifikasi).
# 0.3 (bukan 0.15) -- dilonggarkan sedikit dari draft awal krn data pasar
# sungguhan terus maju selama sesi berjalan (lingkungan ini pakai jam
# fiktif utk recorded_at, terpisah dari kalender data historis asli),
# jadi hasil hitung ulang bisa bergeser beberapa desimal dibanding saat
# sinyal PERTAMA dicatat -- 0.3 tetap menolak baris yang selisihnya besar
# (>=0.5, ciri direkam pakai logic lama sebelum skenario ada) tapi tidak
# menolak baris yang cuma kena floating-point/pergeseran window kecil
# (permintaan user langsung, contoh RAJA: selisih cuma 0.2).
TOLERANCE_PCT = 0.3

# Kalau selisih entry_price lama vs baru di bawah ini, anggap sudah benar
# (tidak perlu UPDATE) -- menghindari noise dari pembulatan/floating point.
MIN_CHANGE_PCT = 0.5

SCENARIO_PRIORITY = ("deep", "pullback", "normal", "breakout")


def _pick_chosen_scenario(scenarios: dict, low: float, high: float):
    """SAMA PERSIS dgn logic confidence() di web/app.py -- pilih skenario
    paling konservatif yang beneran kena (deep > pullback > normal >
    breakout), fallback ke normal kalau tidak ada yang match sama sekali."""
    hit = {h["key"] for h in get_hit_scenarios(scenarios, low, high)}
    for key in SCENARIO_PRIORITY:
        if key in hit:
            return scenarios[key]
    return scenarios.get("normal")


async def _fetch_history(kodes: list[str]) -> dict[str, pd.DataFrame]:
    tickers = [k + ".JK" for k in kodes]
    data = await async_download_many(tickers, period="1y", interval="1d")
    out = {}
    for ticker, df_raw in data.items():
        kode = ticker.replace(".JK", "")
        try:
            df = fix_yf_columns(df_raw).apply(pd.to_numeric, errors="coerce").dropna()
        except Exception:
            continue
        if df is None or len(df) < 50:
            continue
        out[kode] = df
    return out


def _as_of(df: pd.DataFrame, recorded_date) -> pd.DataFrame | None:
    """Potong df supaya HANYA berisi baris sampai (termasuk) recorded_date --
    mencegah lookahead bias (tidak boleh pakai data SETELAH hari itu utk
    merekonstruksi apa yang seharusnya terlihat PADA hari itu).

    SENGAJA TIDAK mensyaratkan baris terakhir persis == recorded_date --
    kalau recorded_date bukan hari bursa (weekend/libur) ATAU sinyal
    dicatat pagi hari SEBELUM bar hari itu tersedia di yfinance (recorded_
    at pakai jam-menit sungguhan, sementara bar harian baru final setelah
    market tutup), bar TERAKHIR yang tersedia SEBELUM/PADA recorded_date
    adalah data yang SAMA PERSIS yang akan dilihat confidence() kalau
    dijalankan saat itu -- itu justru benar, bukan kasus gagal. Return
    None HANYA kalau truncated benar-benar kosong (tidak ada data historis
    sama sekali sebelum/pada tanggal itu)."""
    truncated = df[df.index.date <= recorded_date]
    if truncated.empty:
        return None
    return truncated


def _evaluate_row(row: dict, df: pd.DataFrame | None) -> dict:
    """Evaluasi SATU baris OPEN, murni fungsi (tidak I/O, tidak akses DB) --
    supaya gampang ditest dgn df sintetis/mock. Returns dict beranotasi
    dgn key 'action' (update/no_change_needed/skip_low_confidence/
    skip_no_history_before_date/skip_no_data/skip_no_scenario) dan
    'new_entry'/'detail' utk laporan."""
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

    low_today = float(df_asof["Low"].iloc[-1])
    high_today = float(df_asof["High"].iloc[-1])
    chosen = _pick_chosen_scenario(scenarios, low_today, high_today)
    if chosen is None:
        return {**row, "action": "skip_no_scenario", "new_entry": None,
                "detail": "tidak ada skenario yang bisa dipilih"}

    tp_diff = abs(chosen["tp1_pct"] - row["tp_pct"])
    sl_diff = abs(chosen["risk_pct"] - row["sl_pct"])
    if tp_diff > TOLERANCE_PCT or sl_diff > TOLERANCE_PCT:
        return {**row, "action": "skip_low_confidence", "new_entry": chosen["entry"],
                "detail": f"stored tp/sl={row['tp_pct']}/{row['sl_pct']} vs recomputed "
                          f"{chosen['key']} tp1/risk={chosen['tp1_pct']}/{chosen['risk_pct']} "
                          f"(selisih {tp_diff:.2f}/{sl_diff:.2f})"}

    new_entry = chosen["entry"]
    old_entry = row["entry_price"]
    pct_change = abs(new_entry - old_entry) / old_entry * 100 if old_entry else 0
    if pct_change < MIN_CHANGE_PCT:
        return {**row, "action": "no_change_needed", "new_entry": new_entry,
                "detail": f"skenario {chosen['key']}, selisih cuma {pct_change:.2f}%"}

    return {**row, "action": "update", "new_entry": new_entry,
            "detail": f"skenario {chosen['key']} (low={low_today}, high={high_today})"}


def _fetch_open_rows() -> list[dict]:
    with get_db() as conn:
        rows = conn.execute('''
            SELECT id, kode, recorded_at, entry_price, tp_pct, sl_pct
            FROM signal_history
            WHERE status = 'OPEN' AND source IN ('TOP_PICK', 'SMART_MONEY') AND direction = 'BUY'
        ''').fetchall()
        return [dict(r) for r in rows]


def _print_report(results: list[dict]) -> None:
    print()
    print(f"{'KODE':6} {'OLD_ENTRY':>10} {'NEW_ENTRY':>10} {'ACTION':20} DETAIL")
    for r in results:
        new_e = f"{r['new_entry']:.0f}" if r["new_entry"] is not None else "-"
        print(f"{r['kode']:6} {r['entry_price']:>10.0f} {new_e:>10} {r['action']:20} {r['detail']}")

    counts = {}
    for r in results:
        counts[r["action"]] = counts.get(r["action"], 0) + 1
    print()
    print("Ringkasan: " + ", ".join(f"{v} {k}" for k, v in sorted(counts.items())))


def apply_updates(results: list[dict]) -> int:
    """Tulis entry_price BARU ke DB utk baris ber-action 'update' saja --
    HANYA kolom entry_price yang disentuh, tidak ada kolom lain (tp_pct,
    sl_pct, status, dst tetap apa adanya)."""
    to_update = [r for r in results if r["action"] == "update"]
    with get_db() as conn:
        for r in to_update:
            conn.execute("UPDATE signal_history SET entry_price = ? WHERE id = ?",
                         (r["new_entry"], r["id"]))
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
    print(f"\n[APPLIED] {n} baris entry_price sudah diupdate.")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Benar-benar menulis UPDATE ke database (default: dry-run)")
    args = parser.parse_args()
    asyncio.run(run(apply=args.apply))
