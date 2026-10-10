#!/usr/bin/env bash
# Tiga hal yang tidak bisa diperiksa dari laptop, cuma dari server.
#
# KENAPA JADI SKRIP. Ketiganya sudah lama menggantung ("japri jalan
# tidak?", "peringatan posisi pernah bunyi?", "server mati karena apa?")
# dan tiap kali jawabannya "nanti dicek" karena perintahnya harus
# diingat satu per satu. Sekarang tinggal dijalankan.
#
#   cd ~/ranah-saham-web && bash tools/cek_server.sh
#
# Tidak mengubah apa pun -- cuma membaca.
set -u
DB="${DB:-$HOME/ranah-saham-web/ranah_saham.db}"
echo "============================================================"
echo "1. PERINGATAN POSISI -- pernah berbunyi?"
echo "============================================================"
if [ ! -f "$DB" ]; then
  echo "  basis data tidak ketemu di $DB"
  echo "  (atur lewat: DB=/jalur/lain bash tools/cek_server.sh)"
else
  ADA=$(sqlite3 "$DB" "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='wa_alert_kirim';" 2>/dev/null)
  if [ "${ADA:-0}" = "0" ]; then
    echo "  TABEL wa_alert_kirim BELUM ADA."
    echo "  Artinya jalur peringatan BELUM PERNAH jalan sekali pun --"
    echo "  tabelnya dibuat saat pertama kali dipakai (ensure_alert_tables)."
  else
    echo "  total terkirim : $(sqlite3 "$DB" 'SELECT COUNT(*) FROM wa_alert_kirim;')"
    echo "  per jenis:"
    sqlite3 -column "$DB" "SELECT jenis, COUNT(*) n, MAX(dikirim_at) terakhir
                           FROM wa_alert_kirim GROUP BY jenis ORDER BY n DESC;" |
      sed 's/^/    /'
    echo "  lima terakhir:"
    sqlite3 -column "$DB" "SELECT dikirim_at, user_id, kode, jenis
                           FROM wa_alert_kirim ORDER BY id DESC LIMIT 5;" |
      sed 's/^/    /'
  fi
fi

echo
echo "============================================================"
echo "2. JAPRI (pesan pribadi bot) -- jalan atau tidak?"
echo "============================================================"
echo "  Ini TIDAK bisa dijawab dari log saja; ia perlu dicoba."
echo "  Langkahnya, dari HP-mu sendiri:"
echo "    a. chat bot-nya LANGSUNG (bukan di grup), kirim: portofolio"
echo "    b. kalau balasannya datang, japri jalan"
echo "    c. kalau diam, jejaknya ada di sini:"
echo
echo "  -- jejak pesan masuk & keluar 2 jam terakhir --"
sudo journalctl -u wa-bot --since '2 hours ago' --no-pager 2>/dev/null |
  grep -iE "dm|japri|private|message|send" | tail -15 | sed 's/^/    /'
echo "  -- galat wa-bot 24 jam terakhir --"
sudo journalctl -u wa-bot --since '24 hours ago' --no-pager -p err 2>/dev/null |
  tail -10 | sed 's/^/    /'

echo
echo "============================================================"
echo "3. SERVER PERNAH MATI -- karena kehabisan memori?"
echo "============================================================"
N=$(sudo journalctl -k --since '30 days ago' --no-pager 2>/dev/null |
    grep -ciE "out of memory|oom-kill|killed process")
echo "  baris OOM di log kernel (30 hari): ${N:-0}"
if [ "${N:-0}" != "0" ]; then
  echo "  lima terakhir:"
  sudo journalctl -k --since '30 days ago' --no-pager 2>/dev/null |
    grep -iE "out of memory|oom-kill|killed process" | tail -5 | sed 's/^/    /'
fi
echo "  -- layanan pernah mati mendadak? --"
sudo journalctl -u ranahsaham --since '30 days ago' --no-pager 2>/dev/null |
  grep -iE "killed|failed|core-dump|Main process exited" | tail -8 | sed 's/^/    /'
echo
echo "  memori sekarang:"
free -h 2>/dev/null | sed 's/^/    /'
echo "  pemakai memori terbesar:"
ps -eo pid,rss,comm --sort=-rss 2>/dev/null | head -6 | sed 's/^/    /'
echo
echo "selesai."
