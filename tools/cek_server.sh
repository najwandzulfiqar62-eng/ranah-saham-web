#!/usr/bin/env bash
# Tiga hal yang tidak bisa diperiksa dari laptop, cuma dari server.
#
#   cd ~/ranah-saham-web && bash tools/cek_server.sh
#
# Tidak mengubah apa pun -- cuma membaca.
#
# ---------------------------------------------------------------------------
# TIGA CACAT DI VERSI PERTAMA, DIPERBAIKI 11 OKT 2026
#
# Versi pertama dijalankan di server dan jawabannya MENYESATKAN di ketiga
# bagiannya sekaligus. Dicatat di sini supaya tidak terulang:
#
#   1. MENYIMPULKAN LEBIH JAUH DARIPADA BUKTINYA. Dari "tabel
#      wa_alert_kirim belum ada" ia menyimpulkan "jalur peringatan belum
#      pernah jalan sekali pun". Itu tidak mengikuti: tabel itu dibuat
#      saat peringatan pertama DIKIRIM, jadi kosongnya juga konsisten
#      dengan "jalan terus, cuma belum ada yang layak dikirim". Sekarang
#      tabel nadi (wa_alert_nadi) yang menjawabnya, dan ia mencatat tiap
#      putaran -- terkirim atau tidak.
#
#   2. MEMFILTER GALAT DENGAN CARA YANG TIDAK MUNGKIN KENA. `journalctl
#      -p err` menyaring berdasarkan prioritas syslog, sementara wa-bot
#      menulis JSON pino ke STDOUT -- yang oleh journald selalu diberi
#      prioritas "info". Tingkat galatnya ada DI DALAM JSON ("level":50),
#      tidak terlihat oleh -p. Jadi bagian itu akan berbunyi "No entries"
#      berapa pun banyak galatnya. Terbukti di layar: jejak 2 jam di
#      atasnya memuat dua "level":50, sementara "galat 24 jam" di
#      bawahnya bilang tidak ada apa-apa. Skrip yang membantah dirinya
#      sendiri dalam satu tampilan.
#
#   3. MENCARI KEMATIAN LAYANAN PAKAI KATA "failed". Yang kena justru
#      "3 Failed downloads:" dari yfinance -- pesan rutin, bukan
#      kematian. Di bawah judul "layanan pernah mati mendadak?", delapan
#      baris itu terbaca sebagai YA. Sekarang cuma baris systemd sendiri
#      yang dibaca.
# ---------------------------------------------------------------------------
set -u
DB="${DB:-$HOME/ranah-saham-web/ranah_saham.db}"
Q() { sqlite3 "$DB" "$1" 2>/dev/null; }

echo "============================================================"
echo "1. PERINGATAN POSISI -- pernah berbunyi?"
echo "============================================================"
if [ ! -f "$DB" ]; then
  echo "  basis data tidak ketemu di $DB"
  echo "  (atur lewat: DB=/jalur/lain bash tools/cek_server.sh)"
else
  ADA_NADI=$(Q "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='wa_alert_nadi';")
  ADA_KRM=$(Q "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='wa_alert_kirim';")

  if [ "${ADA_NADI:-0}" = "0" ]; then
    echo "  TABEL NADI BELUM ADA -- server ini masih versi lama."
    echo "  Tabel nadi dibuat saat startup sejak 11 Okt 2026; kalau ia"
    echo "  tidak ada sesudah restart, deploy-nya belum masuk."
    echo "  Jalankan: git pull && sudo systemctl restart ranahsaham"
  else
    N=$(Q "SELECT COUNT(*) FROM wa_alert_nadi WHERE id=1;")
    if [ "${N:-0}" = "0" ]; then
      echo "  BELUM ADA SATU PUTARAN PUN."
      echo "  Loop-nya belum pernah selesai memeriksa. Dua sebab wajar:"
      echo "    - belum lewat jam bursa sejak restart terakhir"
      echo "      (loop ini SENGAJA diam di luar jam bursa)"
      echo "    - WA_ALERT_AKTIF=0"
      echo "  Kalau sudah lewat jam bursa dan tetap kosong, itu kerusakan."
    else
      Q "SELECT '  putaran terakhir : ' || terakhir_at || ' UTC'
              || char(10) || '  jumlah putaran  : ' || putaran
              || char(10) || '  anggota ber-HP  : ' || n_user
              || char(10) || '  posisi dipegang : ' || n_posisi
              || char(10) || '  posisi berharga : ' || n_berharga
              || char(10) || '  posisi ber-STOP : ' || n_ber_sl
              || char(10) || '  total terkirim  : ' || n_kirim
         FROM wa_alert_nadi WHERE id=1;"
      echo
      echo "  CARA MEMBACANYA -- tiap baris nol punya artinya sendiri:"
      echo "    anggota 0  -> tidak ada akun approved yang punya nomor HP."
      echo "                  Bukan kerusakan kode; datanya yang kosong."
      echo "    posisi 0   -> ada anggota, tapi belum ada yang mencatat"
      echo "                  portofolio. Tidak ada yang bisa diperingatkan."
      echo "    berharga 0 -> posisi ada tapi harganya gagal diambil."
      echo "                  INI kerusakan; lihat galat di bawah."
      echo "    ber-STOP 0 -> tidak ada posisi yang sahamnya punya sinyal"
      echo "                  OPEN di Audit Sinyal. Peringatan 'menyentuh"
      echo "                  stop' memang tidak bisa menyala tanpa itu."
      echo "    terkirim 0 -> semua di atas sehat, cuma belum ada keadaan"
      echo "                  yang layak diberitakan. Ini WAJAR."
    fi

    if [ "${ADA_KRM:-0}" != "0" ]; then
      TK=$(Q "SELECT COUNT(*) FROM wa_alert_kirim;")
      if [ "${TK:-0}" != "0" ]; then
        echo
        echo "  per jenis:"
        sqlite3 -column "$DB" "SELECT jenis, COUNT(*) n, MAX(dikirim_at) terakhir
                               FROM wa_alert_kirim GROUP BY jenis
                               ORDER BY n DESC;" 2>/dev/null | sed 's/^/    /'
        echo "  lima terakhir:"
        sqlite3 -column "$DB" "SELECT dikirim_at, user_id, kode, jenis
                               FROM wa_alert_kirim ORDER BY id DESC LIMIT 5;" \
          2>/dev/null | sed 's/^/    /'
      fi
    fi
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
echo "    c. kalau diam, jejaknya ada di bawah"
echo
echo "  -- galat wa-bot 24 jam terakhir (pino 'level':50/60) --"
# BUKAN -p err: lihat cacat #2 di kepala berkas ini.
GALAT=$(sudo journalctl -u wa-bot --since '24 hours ago' --no-pager 2>/dev/null |
        grep -cE '"level":(50|60)')
echo "    jumlah: ${GALAT:-0}"
if [ "${GALAT:-0}" != "0" ]; then
  echo "    pesannya, yang paling sering lebih dulu:"
  sudo journalctl -u wa-bot --since '24 hours ago' --no-pager 2>/dev/null |
    grep -oE '"msg":"[^"]+"' | sort | uniq -c | sort -rn | head -8 |
    sed 's/^/      /'
fi
echo
echo "  -- sambungan WhatsApp: berapa kali tersambung ulang 24 jam --"
# Sambungan yang putus-sambung membuat japri TIDAK BISA DIANDALKAN walau
# kodenya benar: pesan yang dikirim saat socket sedang mati hilang begitu
# saja. Angka besar di sini menjelaskan "kadang jalan kadang tidak".
for pola in "stream errored out" "connection closed" "Timed Out" "qr" "open"; do
  n=$(sudo journalctl -u wa-bot --since '24 hours ago' --no-pager 2>/dev/null |
      grep -ciF "$pola")
  printf "    %-22s %s\n" "$pola" "${n:-0}"
done

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
# HANYA baris systemd sendiri. Lihat cacat #3 di kepala berkas ini:
# "3 Failed downloads:" dari yfinance bukan kematian layanan.
MATI=$(sudo journalctl -u ranahsaham --since '30 days ago' --no-pager 2>/dev/null |
       grep -E "systemd\[1\]:.*(Main process exited|Failed with result)")
if [ -z "$MATI" ]; then
  echo "    tidak ada. Layanan tidak pernah mati tak wajar dalam 30 hari."
else
  echo "$MATI" | tail -8 | sed 's/^/    /'
fi
JALAN=$(sudo journalctl -u ranahsaham --since '30 days ago' --no-pager 2>/dev/null |
        grep -cE "systemd\[1\]:.*Started")
echo "    dinyalakan ${JALAN:-0}x dalam 30 hari (tiap deploy satu)"

echo
echo "  memori sekarang:"
free -h 2>/dev/null | sed 's/^/    /'
echo "  pemakai memori terbesar:"
ps -eo pid,rss,comm --sort=-rss 2>/dev/null | head -6 | sed 's/^/    /'
echo
echo "selesai."
