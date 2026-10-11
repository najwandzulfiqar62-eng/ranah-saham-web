#!/usr/bin/env bash
# Berapa sinyal per SUMBER, dan bagaimana hasilnya -- dibaca dari server.
#
#   cd ~/ranah-saham-web && bash tools/cek_sinyal.sh
#
# Tidak mengubah apa pun -- cuma membaca.
#
# PAKAI PYTHON, BUKAN sqlite3. Perintah sqlite3 tidak terpasang di server
# ini (12 Okt 2026), dan memasangnya cuma untuk membaca satu tabel adalah
# apt install yang tidak perlu -- Python yang menjalankan aplikasinya
# sudah membawa modul sqlite3 di pustaka bakunya.
#
# KENAPA JADI SKRIP. Pertanyaan "sumber X sudah berbunyi berapa kali, dan
# hasilnya bagaimana" akan berulang tiap kali ada teori baru atau teori
# yang dijeda. Menulis ulang kuerinya tiap kali berarti menulis ulang
# kesempatan salah tulisnya.
set -u
DB="${DB:-$HOME/ranah-saham-web/ranah_saham.db}"
PY="${PY:-python3}"

echo "============================================================"
echo "VERSI YANG JALAN DI SERVER"
echo "============================================================"
git -C "$(dirname "$0")/.." log --oneline -1 2>/dev/null | sed 's/^/  /'
echo -n "  MVH mencatat sinyal : "
grep -oE 'MVH_CATAT_AKTIF = os.getenv\("MVH_CATAT_AKTIF", "[01]"\)' \
  "$(dirname "$0")/../web/app.py" 2>/dev/null |
  grep -qE '"1"\)' && echo "YA (nyala)" || echo "tidak (dijeda) -- sesuai keputusan 12 Okt 2026"

echo
echo "============================================================"
echo "SINYAL PER SUMBER"
echo "============================================================"
if [ ! -f "$DB" ]; then
  echo "  basis data tidak ketemu di $DB"
  echo "  (atur lewat: DB=/jalur/lain bash tools/cek_sinyal.sh)"
  exit 0
fi

DB="$DB" "$PY" - <<'PYEOF'
import os
import sqlite3
from collections import defaultdict

db = os.environ["DB"]
c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
c.row_factory = sqlite3.Row

rows = c.execute("""
    SELECT source, status, COUNT(*) n,
           ROUND(AVG(return_pct), 2) rata,
           MIN(date(recorded_at)) dari, MAX(date(recorded_at)) sampai
    FROM signal_history GROUP BY source, status
""").fetchall()

if not rows:
    print("  tabel signal_history kosong.")
    raise SystemExit

per = defaultdict(list)
for r in rows:
    per[r["source"]].append(r)

for src in sorted(per):
    baris = per[src]
    total = sum(r["n"] for r in baris)
    tgl = [r["dari"] for r in baris if r["dari"]] + \
          [r["sampai"] for r in baris if r["sampai"]]
    rentang = f"{min(tgl)} .. {max(tgl)}" if tgl else "-"
    print(f"\n  {src}   total {total}   ({rentang})")
    for r in sorted(baris, key=lambda x: -x["n"]):
        rata = "" if r["rata"] is None else f"   rata {r['rata']:+.2f}%"
        print(f"      {r['status']:18} {r['n']:4d}{rata}")

    # WIN RATE hanya dari yang SUDAH selesai. Memasukkan OPEN membuatnya
    # bergantung pada kapan kebetulan dibaca -- posisi yang sedang untung
    # belum tentu berakhir untung, dan angka yang berubah tiap hari tanpa
    # ada sinyal baru bukan win rate.
    tp = sum(r["n"] for r in baris if r["status"] == "TP_HIT")
    sl = sum(r["n"] for r in baris if r["status"] == "SL_HIT")
    if tp + sl:
        print(f"      -> selesai {tp + sl}: menang {tp}, kalah {sl} "
              f"({tp / (tp + sl) * 100:.1f}%)")
    else:
        print("      -> belum ada yang selesai; belum bisa dinilai")

print("\n  CATATAN: 'EXPIRED_NO_ENTRY' = harga entry-nya tidak pernah")
print("  tersentuh, jadi tidak ada posisi. Ia bukan kalah dan bukan")
print("  menang; memasukkannya ke win rate akan mengaburkan keduanya.")
PYEOF

echo
echo "selesai."
