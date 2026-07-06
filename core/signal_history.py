# =========================
# SIGNAL HISTORY + AUTO AUDIT
# =========================
# FITUR BARU. Permintaan eksplisit user: "fitur paling bernilai untuk
# kredibilitas" -- setiap sinyal Top Pick yang pernah ditampilkan ke user
# DICATAT, lalu diaudit otomatis terhadap harga riil untuk lihat apakah
# target (TP) atau stop loss (SL) tercapai. Tanpa ini, klaim "AI Score
# bagus" tidak pernah bisa dibuktikan/dibantah dengan data -- cuma janji.
#
# PRINSIP JUJUR yang WAJIB dipegang (ditegaskan berulang oleh user):
# - JANGAN PERNAH mengarang win rate/return kalau belum ada sinyal yang
#   benar-benar selesai diaudit (status TP_HIT/SL_HIT/EXPIRED). Kalau
#   kosong, bilang jujur "belum cukup data", BUKAN tampilkan 0% atau
#   angka acak yang kelihatan meyakinkan.
# - Sinyal DICATAT OTOMATIS dari hasil /api/confidence (Top Pick) yang
#   SUDAH ditampilkan ke user -- BUKAN dipilih manual/cherry-picked
#   sesudah tahu hasilnya. Ini penting: track record cuma kredibel kalau
#   sinyalnya dicatat SEBELUM tahu benar/salahnya.
# - TP/SL dipakai di sini SAMA PERSIS dengan yang sudah dihitung buat
#   badge Ringkasan Cepat (potensi_naik_pct/risiko_turun_pct dari
#   calculate_snr_levels) -- bukan angka baru yang beda dari yang dilihat
#   user saat sinyal itu pertama ditampilkan.
#
# REVISI (Juli 2026): audit SEKARANG juga jalan otomatis via background
# task periodik di web/app.py (_signal_auto_loop), TIDAK LAGI cuma
# on-demand saat /api/signals dipanggil -- permintaan eksplisit user
# supaya status sinyal & notifikasi Telegram ter-update walau tidak ada
# yang sedang membuka halaman. record_top_picks() & audit_open_signals()
# sekarang mengembalikan LIST sinyal yang baru dicatat/diselesaikan
# (bukan cuma jumlah/None) supaya caller bisa mengirim notifikasi berisi
# detail sinyalnya -- fungsi ini SENDIRI tetap tidak melakukan I/O
# jaringan (kirim notifikasi jadi tanggung jawab caller di web/app.py),
# supaya tetap mudah ditest tanpa mock network/Telegram.
#
# REVISI KEDUA (Juli 2026): ditambah kolom 'source' -- signal_history
# sekarang punya DUA sumber entry point independen: 'TOP_PICK' (skor
# gabungan harian, seperti sebelumnya) dan 'MACD_CROSS' (permintaan
# eksplisit user: histogram MACD yang baru saja berbalik positif dipakai
# SENDIRI sebagai teori entry point, TANPA disaring skor gabungan lain --
# supaya validitas teori itu bisa diuji apa adanya lewat data real, bukan
# tercampur/ketutupan Top Pick). Kedua sumber diaudit dengan cara yang
# SAMA PERSIS (audit_open_signals tidak peduli source), dan get_signal_
# report() menghitung win rate/return TERPISAH per source (stats_by_source)
# selain angka gabungan -- supaya user bisa benar-benar bandingkan mana
# yang lebih valid, bukan cuma klaim.

from datetime import datetime, timedelta

from core.database import get_db

# Sinyal yang tidak tercapai TP maupun SL dalam MAX_HOLD_DAYS dianggap
# "kadaluarsa" (EXPIRED) -- horison realistis untuk sinyal teknikal
# swing/menengah (bukan scalping harian, bukan juga investasi tahunan).
MAX_HOLD_DAYS = 20

# Ambang minimum confidence_score supaya masuk daftar yang diaudit --
# JANGAN catat SEMUA 45 saham tiap hari (terlalu bising, dan sinyal yang
# skornya biasa-biasa saja bukan "yang ditampilkan sebagai Top Pick").
MIN_SCORE_TO_RECORD = 55.0
# Maksimum berapa saham teratas per hari yang dicatat -- konsisten dengan
# semangat "Top Pick" (peringkat TERATAS), bukan seluruh universe.
MAX_RECORDED_PER_DAY = 10


def _is_bursa_weekend() -> bool:
    """True kalau HARI INI Sabtu/Minggu -- BEI tidak buka, jadi closing
    price yfinance yang dipakai utk hitung confidence_score/entry masih
    PERSIS closing hari bursa terakhir (Jumat), bukan data baru.

    BUG NYATA ditemukan lewat inspeksi data produksi: siklus auto-audit
    (jalan tiap 600 detik, 24/7, tidak peduli akhir pekan) tetap mencatat
    "sinyal Top Pick baru" di hari Sabtu & Minggu dengan entry_price/tp_pct/
    sl_pct yang IDENTIK dengan sinyal Jumat -- karena memang belum ada
    pergerakan harga sungguhan. Akibatnya satu pergerakan pasar bisa
    tercatat sebagai 2-3 sinyal terpisah (Jumat, Sabtu, Minggu semua dgn
    angka sama), yang MENGGANDAKAN statistik win-rate secara palsu kalau
    nanti sinyal itu kena TP/SL -- justru bertentangan dengan prinsip
    kredibilitas "jangan mengarang win rate" yang jadi alasan fitur ini
    dibuat.

    KETERBATASAN YANG JUJUR DICATAT: ini cuma cek akhir pekan, BELUM
    menutup hari libur nasional Indonesia yang jatuh di hari kerja (mis.
    Idul Fitri, Natal) -- itu butuh kalender libur bursa eksternal yang di
    luar cakupan perbaikan ini. Tetap perbaikan nyata utk kasus dominan
    (2 dari 7 hari), bukan solusi lengkap."""
    return datetime.now().weekday() >= 5  # 5=Sabtu, 6=Minggu


# CATATAN TIMEZONE PENTING: semua SQL di modul ini yang butuh "tanggal hari
# ini" HARUS pakai `datetime('now', 'localtime')`/`date('now', 'localtime')`,
# BUKAN `datetime('now')`/`date('now')` polos. SQLite's `datetime('now')`
# SELALU UTC, sedangkan BEI beroperasi WIB (UTC+7) dan _is_bursa_weekend()
# di atas pakai Python `datetime.now()` (local/WIB). BUG NYATA ditemukan
# lewat inspeksi live: jam 00:00-06:59 WIB, tanggal UTC MASIH "kemarin" --
# tanpa 'localtime', satu hari bursa WIB yang sama bisa terbagi jadi 2
# "tanggal UTC" berbeda, membuat dedup check (`date(recorded_at) =
# date('now')`) gagal mendeteksi duplikat yang sebenarnya sama hari bursa
# -- kelas bug yang SAMA dengan race condition/weekend duplication di atas,
# lewat celah timezone yang berbeda.
_ensured = False


def _ensure_table():
    global _ensured
    if _ensured:
        return
    with get_db() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS signal_history (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                kode             TEXT NOT NULL,
                recorded_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                entry_price      REAL NOT NULL,
                tp_pct           REAL NOT NULL,
                sl_pct           REAL NOT NULL,
                confidence_score REAL,
                ai_score         REAL,
                recommendation   TEXT,
                status           TEXT NOT NULL DEFAULT 'OPEN',
                resolved_at      TEXT,
                resolved_price   REAL,
                return_pct       REAL,
                days_to_resolve  INTEGER
            )
        ''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_signal_status ON signal_history(status)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_signal_kode_date ON signal_history(kode, recorded_at)')
        # Migrasi ringan: kolom 'pattern' (nama pola chart rule-based dari
        # detect_patterns(), mis. "DOUBLE BOTTOM") ditambahkan belakangan --
        # ALTER TABLE ADD COLUMN aman di SQLite utk row yang sudah ada
        # (otomatis NULL), tidak perlu drop/recreate tabel produksi.
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(signal_history)").fetchall()}
        if "pattern" not in cols:
            conn.execute("ALTER TABLE signal_history ADD COLUMN pattern TEXT")
        # Migrasi ringan kedua: kolom 'source' membedakan entry point dari
        # Top Pick (skor gabungan) vs MACD Cross (momentum, teori berdiri
        # sendiri) -- default 'TOP_PICK' utk baris lama (semuanya memang
        # dari Top Pick sebelum fitur MACD Cross ada), aman tanpa migrasi data manual.
        if "source" not in cols:
            conn.execute("ALTER TABLE signal_history ADD COLUMN source TEXT NOT NULL DEFAULT 'TOP_PICK'")
        # Migrasi keempat: kolom 'direction' (BUY/SELL) -- SEMUA sinyal
        # lama (TOP_PICK/MACD_CROSS, dan SMART_MONEY kategori akumulasi)
        # murni long-only, default 'BUY' aman tanpa migrasi data manual.
        # Ditambahkan supaya kategori Distribusi/Distribusi Agresif Smart
        # Money bisa direkam sbg entry SELL (untung kalau harga TURUN
        # sejumlah tp_pct, rugi kalau NAIK sejumlah sl_pct) -- lihat
        # audit_open_signals()/get_signal_report() utk matematika
        # bidirectional-nya.
        if "direction" not in cols:
            conn.execute("ALTER TABLE signal_history ADD COLUMN direction TEXT NOT NULL DEFAULT 'BUY'")
        # Migrasi ketiga: BUG NYATA ditemukan lewat inspeksi data produksi --
        # record_top_picks()/record_macd_cross_signals() dulu cek duplikat
        # via SELECT lalu INSERT terpisah (bukan atomic), dengan sebuah
        # `await price_lookup(...)` (network call) di ANTARA keduanya. Kalau
        # dua panggilan confidence() tumpang tindih (mis. siklus auto-audit
        # 600 detik vs request /api/confidence manual yang bersamaan), event
        # loop bisa berpindah task tepat di celah itu -- kedua task lolos
        # SELECT "belum ada" sebelum salah satu sempat INSERT, hasilnya
        # baris duplikat persis (kode+tanggal+source sama, selisih detik).
        # Dibuktikan nyata: /api/signals produksi berisi ~12 kode tercatat
        # 2x dengan recorded_at berselisih ~1 detik.
        #
        # Bersihkan duplikat lama SEBELUM index unique dibuat (kalau
        # tidak, CREATE UNIQUE INDEX gagal karena data existing sudah
        # melanggar constraint-nya) -- baris ber-id TERKECIL per grup
        # dipertahankan (yang pertama tercatat).
        conn.execute('''
            DELETE FROM signal_history
            WHERE id NOT IN (
                SELECT MIN(id) FROM signal_history
                GROUP BY kode, date(recorded_at), source
            )
        ''')
        conn.execute('''
            CREATE UNIQUE INDEX IF NOT EXISTS idx_signal_unique_daily
            ON signal_history(kode, date(recorded_at), source)
        ''')
        # Migrasi keempat: kelas duplikasi TERPISAH dari race condition di
        # atas -- sebelum _is_bursa_weekend() ada, siklus auto-audit tetap
        # mencatat "sinyal baru" di hari Sabtu/Minggu dengan entry_price/
        # tp_pct/sl_pct IDENTIK dengan sinyal hari sebelumnya (BEI tutup,
        # closing price belum berubah) -- baris-baris ini LOLOS index unique
        # di atas karena tanggalnya beda (Sabtu vs Jumat), padahal secara
        # substansi itu sinyal yang SAMA persis, cuma dicatat ulang tanpa
        # informasi baru. Kalau dibiarkan, satu pergerakan pasar bisa
        # dihitung sebagai 2+ kemenangan/kekalahan terpisah begitu kena TP/
        # SL. Hapus baris yang PERSIS sama (kode+source+entry_price+tp_pct+
        # sl_pct) selain yang PALING AWAL tercatat (id terkecil) -- dijalankan
        # tiap startup, idempotent, aman diulang (kalau sudah bersih tidak
        # menghapus apa-apa). _is_bursa_weekend() sudah mencegah kasus BARU,
        # ini cuma membersihkan sisa data historis dari sebelum fix itu ada.
        conn.execute('''
            DELETE FROM signal_history
            WHERE id NOT IN (
                SELECT MIN(id) FROM signal_history
                GROUP BY kode, source, entry_price, tp_pct, sl_pct
            )
        ''')
        # Migrasi kelima: idx_signal_unique_daily (kode, date(recorded_at),
        # source) DIGANTI oleh index PARTIAL di bawah -- permintaan user
        # ("entrynya jangan kebanyakan double") membuat dedup pindah dari
        # "sudah dicatat hari ini?" (tanggal) ke "masih ada yang OPEN?"
        # (status, lihat _has_open_signal). BUG NYATA ketemu lewat test:
        # index lama TETAP menghalangi kode+source yang sama direkam ulang
        # kalau sinyal sebelumnya SUDAH resolved TAPI masih di HARI YANG
        # SAMA (mis. kena TP paginya, jadi kandidat lagi sore harinya) --
        # padahal itu seharusnya boleh, posisi lamanya sudah selesai.
        # Index unique PARTIAL (cuma mencakup baris status='OPEN') pas
        # merepresentasikan aturan yang benar: maksimal SATU baris OPEN per
        # (kode, source) pada satu waktu, tapi boleh banyak baris RESOLVED
        # historis kapan pun -- sekaligus tetap jadi pengaman ATOMIC
        # terakhir thd race condition, sama seperti index lama.
        #
        # Bersihkan dulu baris OPEN duplikat SEBELUM index baru dibuat
        # (kalau tidak, CREATE UNIQUE INDEX gagal karena data existing dari
        # sebelum fix ini melanggar constraint-nya) -- HANYA menyentuh
        # baris berstatus OPEN (baris RESOLVED/statistik win-rate historis
        # tidak pernah disentuh), menyisakan id TERKECIL (paling awal
        # direkam) per (kode, source): baris OPEN yang lebih baru utk
        # kode+source yang sama secara substansi cuma snapshot ulang dari
        # peluang yang sama yang masih berlangsung, bukan sinyal baru.
        conn.execute('''
            DELETE FROM signal_history
            WHERE status = 'OPEN' AND id NOT IN (
                SELECT MIN(id) FROM signal_history WHERE status = 'OPEN' GROUP BY kode, source
            )
        ''')
        conn.execute('DROP INDEX IF EXISTS idx_signal_unique_daily')
        conn.execute('''
            CREATE UNIQUE INDEX IF NOT EXISTS idx_signal_unique_open
            ON signal_history(kode, source)
            WHERE status = 'OPEN'
        ''')
        # Migrasi keenam: user langsung melihat di UI produksi bahwa satu
        # saham yang SAMA masih tampil 2x di hari yang sama (mis. RAJA/BBCA/
        # ICBP sbg TOP_PICK DAN SMART_MONEY sekaligus, dgn entry/TP/SL
        # nyaris identik krn keduanya reuse potensi_naik_pct/risiko_turun_
        # pct dari confidence() yang SAMA) -- kelihatan persis seperti
        # "double" yang justru mau dihilangkan, walau secara teknis beda
        # source. Dedup DIPERKETAT jadi per-KODE SAJA (bukan per kode+
        # source lagi, lihat _has_open_signal): maksimal SATU sinyal OPEN
        # per saham pada satu waktu, dari sumber mana pun. Ini SENGAJA
        # mengorbankan kemampuan "bandingkan Top Pick vs Smart Money utk
        # saham yang sama" (desain awal fitur ini) demi kejelasan -- user
        # eksplisit bilang lebih pusing lihat dobel drpd dapat perbandingan
        # antar teori utk saham yang kebetulan sama.
        #
        # Bersihkan dulu baris OPEN duplikat lintas-source SEBELUM index
        # baru dibuat (pola sama dgn migrasi kelima), menyisakan id
        # TERKECIL (paling awal direkam, source mana pun) per kode.
        conn.execute('''
            DELETE FROM signal_history
            WHERE status = 'OPEN' AND id NOT IN (
                SELECT MIN(id) FROM signal_history WHERE status = 'OPEN' GROUP BY kode
            )
        ''')
        conn.execute('DROP INDEX IF EXISTS idx_signal_unique_open')
        conn.execute('''
            CREATE UNIQUE INDEX IF NOT EXISTS idx_signal_unique_open_kode
            ON signal_history(kode)
            WHERE status = 'OPEN'
        ''')
        # Migrasi ketujuh: MACD_CROSS sudah dihapus dari confidence() (tidak
        # ada baris baru lagi sejak migrasi keenam), tapi baris LAMA yang
        # kadung tercatat SEBELUM penghapusan itu masih nongol di laporan
        # -- user melapor "macd cross masih ada" walau sudah tidak direkam
        # lagi. Daripada nunggu ~MAX_HOLD_DAYS hari bursa buat resolve
        # sendiri (rencana awal), hapus langsung: source ini sudah
        # sepenuhnya nonaktif & tidak akan pernah ada baris baru lagi,
        # jadi DELETE ini aman dijalankan ulang tiap startup (no-op
        # sesudah pembersihan pertama, konsisten dgn migrasi lain di sini).
        conn.execute("DELETE FROM signal_history WHERE source = 'MACD_CROSS'")
        # Migrasi kedelapan: dedup silang-source utk baris yang SUDAH
        # RESOLVED (migrasi keenam cuma menyentuh baris status='OPEN').
        # BUG NYATA ketemu lewat screenshot user: MDKA tercatat 2x tanggal
        # SAMA (dulu satu dari SMART_MONEY, satu dari MACD_CROSS, direkam
        # SEBELUM migrasi keenam ada) dgn entry/TP/SL IDENTIK -- keduanya
        # KEBETULAN sudah sama-sama resolve (SL_HIT) sebelum migrasi
        # keenam sempat jalan, jadi lolos dari cleanup itu. Kriteria beda
        # dari migrasi ke-4 (yang mensyaratkan source SAMA): di sini kode+
        # tanggal+entry_price+tp_pct+sl_pct sama persis SUDAH cukup buat
        # dianggap sinyal yang sama, source APA PUN -- sisakan id
        # TERKECIL (paling awal direkam).
        conn.execute('''
            DELETE FROM signal_history
            WHERE id NOT IN (
                SELECT MIN(id) FROM signal_history
                GROUP BY kode, date(recorded_at), entry_price, tp_pct, sl_pct
            )
        ''')
        # Migrasi kesembilan: permintaan user langsung ("yg di smart money
        # saya mau nya yg secara teknikal dia nyuruh buy aja biar lebih
        # valid") -- _record_smart_money_cycle() di web/app.py SUDAH
        # menyaring kandidat baru supaya cuma direkam kalau teknikal JUGA
        # bilang BELI, TAPI baris SMART_MONEY yang kadung tercatat SEBELUM
        # filter itu ada masih nongol di laporan dgn recommendation NETRAL/
        # CUKUP/BURUK -- sama seperti kasus MACD_CROSS di atas, sekadar
        # menghentikan perekaman baru tidak cukup, riwayat lama yg tidak
        # lagi memenuhi standar validitas SAAT INI harus ikut dibersihkan.
        # HANYA menyentuh source='SMART_MONEY' -- TOP_PICK sengaja TIDAK
        # disyaratkan ini (metodologinya beda, lihat confidence()).
        #
        # REVISI: gerbang konfirmasi awalnya pakai ai_rating (SANGAT
        # BAGUS/BAGUS), lalu diganti user jadi "Ringkasan Sinyal Teknikal"
        # (BELI KUAT/BELI -- lihat _ringkasan_sinyal_teknikal &
        # _RINGKASAN_TEKNIKAL_BUY di web/app.py). `recommendation` kolom
        # dulu menyimpan ai_rating, SEKARANG menyimpan verdict Ringkasan
        # Sinyal Teknikal (nilai domain BEDA -- lihat _record_smart_money_
        # cycle) -- kriteria di bawah SENGAJA menerima KEDUA domain nilai
        # ("lama": SANGAT BAGUS/BAGUS; "baru": BELI KUAT/BELI) supaya baris
        # lama yang legitimately tercatat di bawah kriteria lama TIDAK ikut
        # kehapus cuma krn kriterianya berganti, SEKALIGUS baris baru yang
        # direkam di bawah kriteria baru juga tidak salah kehapus. NULL
        # (belum pernah diisi) tetap dihapus krn tidak bisa dipastikan
        # memenuhi kriteria apa pun.
        conn.execute('''
            DELETE FROM signal_history
            WHERE source = 'SMART_MONEY'
              AND (recommendation IS NULL
                   OR recommendation NOT IN ('SANGAT BAGUS', 'BAGUS', 'BELI KUAT', 'BELI'))
        ''')
        # Migrasi kesepuluh: BUG NYATA ditemukan lewat laporan user --
        # ANTM kelihatan "kena TP lalu kena SL" (sebenarnya 2 baris BEDA:
        # SMART_MONEY resolve TP_HIT, dihapus migrasi kesembilan krn
        # recommendation-nya NETRAL, menyisakan cuma TOP_PICK yang resolve
        # SL_HIT -- dari sudut pandang user yang cuma lihat nama tiker,
        # itu kelihatan seperti satu posisi berbalik dari untung ke rugi).
        # RAJA juga: TOP_PICK OPEN dan SMART_MONEY TP_HIT tercatat di
        # TANGGAL YANG SAMA -- bukan "salah" secara teknis (dua teori
        # entry independen), tapi user melihatnya sbg "kok ada dua".
        # audit_open_signals() SENDIRI tidak punya bug (SELECT selalu
        # WHERE status='OPEN', baris yang sudah resolve TIDAK PERNAH
        # disentuh/dievaluasi ulang -- diverifikasi baca kode) -- akar
        # masalahnya di LAPISAN PEREKAMAN: kode yang sama boleh dapat
        # sinyal BARU dari source lain di HARI YANG SAMA persis saat
        # sinyal sebelumnya utk kode itu sudah/sedang resolve, membuat 2+
        # baris kode+tanggal yang sama muncul berdampingan.
        #
        # Bersihkan riwayat yang SUDAH kadung begini: utk tiap grup (kode,
        # tanggal) yang py >1 baris, PRIORITASKAN baris yang masih OPEN
        # (itu "cerita aktif" saat ini utk kode itu); kalau tidak ada yang
        # OPEN (semua sudah resolved), sisakan id TERKECIL (paling awal
        # direkam). Dua langkah supaya logikanya gampang diverifikasi:
        # (1) hapus semua baris NON-OPEN dalam grup yang py baris OPEN,
        # (2) utk grup yang tersisa (semua resolved), sisakan MIN(id).
        conn.execute('''
            DELETE FROM signal_history
            WHERE status != 'OPEN'
              AND EXISTS (
                  SELECT 1 FROM signal_history s2
                  WHERE s2.kode = signal_history.kode
                    AND date(s2.recorded_at) = date(signal_history.recorded_at)
                    AND s2.status = 'OPEN'
              )
        ''')
        # `AND status != 'OPEN'` di bawah ini SECARA LOGIKA seharusnya
        # tidak pernah menyaring apa pun pada titik ini (migrasi keenam +
        # idx_signal_unique_open_kode sudah menjamin maksimal 1 baris OPEN
        # per kode SEBELUM migrasi ini jalan, dan tidak ada baris di file
        # ini yang pernah mengembalikan status ke OPEN) -- ditambahkan
        # sbg pengaman eksplisit (bukan cuma implisit lewat urutan
        # migrasi) setelah verifikasi adversarial menunjukkan: TANPA guard
        # ini, kalau invarian itu PERNAH rusak di masa depan (mis. urutan
        # migrasi diubah), langkah ini akan diam-diam menghapus salah satu
        # dari dua baris OPEN yang sah -- bukan cuma riwayat, tapi POSISI
        # AKTIF yang sedang dipantau. Step A di atas sudah punya guard yang
        # sama (`status != 'OPEN'`); ini menyamakan Step B supaya konsisten.
        conn.execute('''
            DELETE FROM signal_history
            WHERE status != 'OPEN' AND id NOT IN (
                SELECT MIN(id) FROM signal_history GROUP BY kode, date(recorded_at)
            )
        ''')
        # Migrasi kesebelas: permintaan user langsung (menunjuk ANTM/ACES
        # kena SL padahal SL-nya kedeketan -- "selagi masih oke bisa di
        # hold"): floor MIN_SL_PCT di _calc_entry_levels() (core/
        # trading_plan.py) cuma berlaku utk sinyal yang dihitung SETELAH
        # floor itu ada -- sinyal yang SUDAH kadung tercatat sebelumnya
        # (dgn sl_pct asli, kadang <1%) tidak ikut lebar walau rumusnya
        # sudah diperbaiki. Pola yang SAMA dgn migrasi 7/9 (perbaiki aturan
        # tidak cukup, riwayat lama yang tidak lagi memenuhi standar juga
        # harus dibenahi).
        #
        # HANYA baris status='OPEN' yang dilebarkan -- baris yang SUDAH
        # resolved (mis. ANTM/ACES kena SL di sl_pct lama) TIDAK disentuh:
        # hasilnya sudah terjadi apa adanya di bawah aturan lama saat itu,
        # mengubahnya sekarang sama dengan mengarang ulang track record
        # (lihat prinsip "jangan pernah mengarang win rate" di catatan
        # atas modul ini). tp_pct TIDAK disentuh -- floor TP1 (max(3.0,
        # risk_pct)) sudah ada SEBELUM floor SL ini, jadi baris lama sudah
        # benar utk TP, cuma SL yang perlu dilebarkan.
        from core.trading_plan import MIN_SL_PCT as _MIN_SL_PCT
        conn.execute(
            "UPDATE signal_history SET sl_pct = ? WHERE status = 'OPEN' AND sl_pct < ?",
            (_MIN_SL_PCT, _MIN_SL_PCT),
        )
        # Migrasi kedua belas: BUG NYATA ditemukan lewat verifikasi
        # adversarial (workflow terpisah) -- klausul (b) _has_open_signal
        # SEBELUM perbaikan ini memakai date(recorded_at), bukan date(
        # resolved_at) (lihat catatan panjang di _has_open_signal). Selama
        # bug itu aktif, sinyal yang butuh >1 hari utk resolve (kasus
        # PALING UMUM, bukan edge case) gagal terdeteksi "baru resolve
        # hari ini" -- dibuktikan nyata di data produksi: AKRA & RAJA
        # sama-sama direkam 2026-07-04, resolve TP_HIT 2026-07-06, LALU
        # dapat baris OPEN baru di hari yang sama (2026-07-06) -- migrasi
        # kesepuluh (yang mengelompokkan per date(recorded_at)) tidak
        # menangkap ini karena baris lama & baris baru py recorded_at
        # BEDA tanggal (07-04 vs 07-06), padahal resolved_at-nya (kalau
        # baris baru itu nanti resolve) bisa jadi tanggal yang SAMA --
        # persis pola ANTM yang migrasi kesepuluh coba tutup.
        #
        # Bersihkan: utk tiap kode yang py baris resolved (bukan OPEN)
        # HARI INI ATAU KEMARIN* dan JUGA py baris OPEN, PRIORITASKAN yang
        # OPEN (pola sama dgn migrasi kesepuluh Step A) -- hapus baris
        # resolved yang "menabrak" cerita aktif yang sedang berjalan.
        # (*dicek s.d. kemarin, bukan cuma hari ini, supaya migrasi ini
        # idempotent aman dijalankan kapan pun server restart, bukan cuma
        # persis di hari kejadian.)
        conn.execute('''
            DELETE FROM signal_history
            WHERE status != 'OPEN'
              AND resolved_at IS NOT NULL
              AND EXISTS (
                  SELECT 1 FROM signal_history s2
                  WHERE s2.kode = signal_history.kode AND s2.status = 'OPEN'
              )
        ''')
        # Sisi lain: kalau TIDAK ada yang OPEN, tapi >1 baris resolved utk
        # kode yang sama kebetulan resolve di TANGGAL YANG SAMA (resolved_
        # at), itu juga "dua cerita, satu hari" yang membingungkan -- sisakan
        # id TERKECIL (paling awal direkam).
        conn.execute('''
            DELETE FROM signal_history
            WHERE resolved_at IS NOT NULL AND id NOT IN (
                SELECT MIN(id) FROM signal_history
                WHERE resolved_at IS NOT NULL
                GROUP BY kode, date(resolved_at)
            )
        ''')
        # Migrasi ketiga belas: permintaan user langsung, menunjuk ANTM &
        # ACES ("masih sama belom berubah sl masih kedeketan tolong
        # perbaiki semua") -- migrasi kesebelas SENGAJA tidak menyentuh
        # baris yang SUDAH resolved (SL_HIT) dgn alasan "hasilnya sudah
        # terjadi, jangan mengarang ulang track record". User menegaskan
        # itu KURANG TEPAT utk kasus spesifik ini: SL_HIT-nya BUKAN hasil
        # pasar yang sah, itu ARTEFAK dari sl_pct yang KETERLALU KETAT
        # (bug yang migrasi kesebelas perbaiki) -- diverifikasi lewat data
        # ANTM/ACES sendiri: resolved_price (2960 utk ANTM, 334 utk ACES)
        # keduanya MASIH DI ATAS harga yang seharusnya jadi SL kalau floor
        # 3.0% sudah benar sejak awal (entry*0.97 = 2919.7 utk ANTM, 327.86
        # utk ACES) -- artinya kalau floor-nya sudah benar SAAT ITU, posisi
        # ini TIDAK akan resolve SL_HIT di titik itu sama sekali. Menyimpan
        # SL_HIT itu sbg "riwayat" justru MELESTARIKAN kesalahan ukur, bukan
        # menjaga kejujuran data.
        #
        # Kriteria (general, bukan spesifik ANTM/ACES sby id) -- HARUS
        # SEMUA benar: (1) status SL_HIT, (2) sl_pct ASLI di bawah floor
        # (direkam sebelum migrasi kesebelas ada), (3) resolved_price MASIH
        # DI ATAS floor yang benar (entry*(1-floor/100)) -- kalau harga
        # SUNGGUHAN sudah turun MELEWATI floor yang benar juga, SL_HIT
        # tetap sah, TIDAK disentuh. TP_HIT TIDAK PERNAH kena kriteria ini
        # (SL lebih lebar cuma bikin LEBIH SULIT kena SL, tidak pernah
        # mengubah status TP_HIT yang sudah tercapai jadi tidak tercapai).
        #
        # Baris yang cocok kriteria DIKEMBALIKAN ke OPEN dgn sl_pct
        # dilebarkan ke floor (recorded_at, entry_price, tp_pct TIDAK
        # disentuh sama sekali -- persis permintaan user "entrynya jgn
        # diubah-ubah") -- siklus audit normal yang akan menentukan ulang
        # nasibnya memakai harga LIVE saat ini, bukan dikarang manual.
        from core.trading_plan import MIN_SL_PCT as _MIN_SL_PCT2
        conn.execute('''
            UPDATE signal_history
            SET status = 'OPEN', sl_pct = ?, resolved_at = NULL,
                resolved_price = NULL, return_pct = NULL, days_to_resolve = NULL
            WHERE status = 'SL_HIT'
              AND sl_pct < ?
              AND resolved_price > entry_price * (1 - ? / 100.0)
        ''', (_MIN_SL_PCT2, _MIN_SL_PCT2, _MIN_SL_PCT2))
        # Migrasi keempat belas: permintaan user langsung ("misalkan kena
        # area tp1 tandai juga lanjut ke area tp selanjutnya") -- TP
        # SEKARANG bertingkat 3 level (TP1/TP2/TP3, angka SUDAH ADA &
        # dihitung _calc_entry_levels di core/trading_plan.py sbg
        # tp1_pct/tp2_pct/tp3_pct = risk%/2x/3x, cuma SEBELUM ini yang
        # dipakai & disimpan cuma TP1). Begitu TP1/TP2 tercapai, posisi
        # TIDAK langsung ditutup (status TETAP 'OPEN') -- cuma `tp_level_
        # hit` yang naik, terus dipantau sampai TP3 (baru benar-benar
        # closed) ATAU SL tersentuh ATAU EXPIRED. Lihat audit_open_signals
        # utk logika lengkapnya.
        cols2 = {r["name"] for r in conn.execute("PRAGMA table_info(signal_history)").fetchall()}
        if "tp2_pct" not in cols2:
            conn.execute("ALTER TABLE signal_history ADD COLUMN tp2_pct REAL")
        if "tp3_pct" not in cols2:
            conn.execute("ALTER TABLE signal_history ADD COLUMN tp3_pct REAL")
        if "tp_level_hit" not in cols2:
            conn.execute("ALTER TABLE signal_history ADD COLUMN tp_level_hit INTEGER NOT NULL DEFAULT 0")
        # Backfill baris LAMA (direkam sebelum kolom ini ada): tp2/tp3
        # pakai relasi yang SAMA dgn _calc_entry_levels (tp2=tp1x2,
        # tp3=tp1x3) -- konsisten dgn cara tp1_pct itu sendiri dihitung,
        # bukan angka baru yang beda basis.
        conn.execute("UPDATE signal_history SET tp2_pct = tp_pct * 2 WHERE tp2_pct IS NULL")
        conn.execute("UPDATE signal_history SET tp3_pct = tp_pct * 3 WHERE tp3_pct IS NULL")
        # Baris LAMA yang statusnya SUDAH TP_HIT (di bawah sistem lama,
        # menutup posisi begitu TP1-setara tercapai) -- HARUS dianggap
        # baru mencapai level 1, BUKAN level 3/full target, krn sistem
        # lama memang tidak pernah punya kesempatan mengejar TP2/TP3.
        # Jujur merepresentasikan apa yang SUNGGUHAN terjadi, bukan
        # mengarang seolah sudah sampai TP3.
        conn.execute("UPDATE signal_history SET tp_level_hit = 1 WHERE status = 'TP_HIT' AND tp_level_hit = 0")
    _ensured = True


def _has_open_signal(kode: str) -> bool:
    """True kalau `kode` TIDAK BOLEH dapat sinyal baru sekarang -- karena
    (a) masih ada sinyal OPEN utk kode itu (source mana pun), ATAU (b)
    sinyal utk kode itu SUDAH resolve (TP_HIT/SL_HIT/EXPIRED) TAPI masih
    di HARI YANG SAMA (hari ini).

    Dipakai record_top_picks()/record_smart_money_signals() SEBAGAI GANTI
    dedup "sudah dicatat hari ini" yang lama -- dedup per-hari itu cuma
    mencegah duplikat di HARI YANG SAMA, tapi kalau satu saham tetap jadi
    kandidat (mis. Top Pick) 4-5 hari berturut-turut, tiap hari tetap
    dicatat sbg entry BARU yang terpisah -- user melapor ini bikin Audit
    Sinyal penuh "banyak yg double" utk saham yang sama, membingungkan
    (tidak jelas mana yang harus diikuti).

    AWALNYA scoped per (kode, source) supaya TOP_PICK dan SMART_MONEY bisa
    "membandingkan teori entry" utk saham yang sama secara independen --
    tapi user langsung melihat di UI produksi bahwa itu KELIHATAN persis
    seperti "double" yang sama yang justru mau dihilangkan (mis. RAJA
    tampil sbg TOP_PICK *dan* SMART_MONEY hari yang sama, entry/TP/SL
    nyaris identik karena keduanya reuse angka confidence() yang sama).
    Diperketat jadi per-KODE SAJA: maksimal SATU sinyal OPEN per saham
    pada satu waktu, dari sumber mana pun -- lihat migrasi keenam di
    _ensure_table utk index unique DB yang menegakkan aturan yang sama.

    KLAUSUL (b) ditambahkan setelah user melapor kasus ANTM: satu sumber
    (SMART_MONEY) resolve TP_HIT hari ini, lalu source LAIN (TOP_PICK)
    merekam sinyal BARU utk ANTM di hari yang SAMA yang kemudian resolve
    SL_HIT -- dari sudut pandang user yang cuma lihat nama tiker, itu
    kelihatan seperti satu posisi "berbalik dari untung ke rugi" (BUKAN
    bug di audit_open_signals -- baris yang sudah resolve tidak PERNAH
    dievaluasi ulang, sudah diverifikasi baca kode -- ini murni soal
    perekaman sinyal BARU yang kebetulan terlalu cepat utk kode yang sama).
    Klausul (b) memastikan begitu SATU cerita utk kode itu selesai hari
    ini (menang ATAU kalah), tidak ada cerita KEDUA yang dibuka sampai
    besok -- konsisten dgn semangat "satu saham = satu cerita per hari".

    BUG NYATA ditemukan lewat verifikasi adversarial (workflow terpisah)
    SEHARI setelah klausul (b) di atas ditulis: kondisi awalnya memakai
    `date(recorded_at) = date('now')` -- yaitu tanggal SAAT BARIS ITU
    PERTAMA DICATAT, bukan tanggal SAAT BARIS ITU RESOLVE. Sinyal nyata
    hampir selalu butuh >1 hari sebelum kena TP/SL (AKRA & RAJA di data
    produksi butuh 2 hari) -- begitu baris itu resolve HARI INI, `date
    (recorded_at)`-nya masih tanggal beberapa hari LALU (kapan dicatat),
    BUKAN hari ini, jadi klausul (b) versi lama SELALU gagal mendeteksi
    "baru saja resolve hari ini" utk kasus yang justru paling umum --
    persis KEBALIKAN dari yang dimaksudkan. Akibatnya AKRA/RAJA yang
    resolve TP_HIT hari ini tetap lolos merekam entry BARU jam-jam
    berikutnya di hari yang sama, mereproduksi ulang bug ANTM yang
    seharusnya sudah ditutup klausul ini. Diperbaiki: pakai `date(
    resolved_at)`, bukan `date(recorded_at)` -- resolved_at TEPAT
    mencatat kapan baris itu BENAR-BENAR selesai (NULL selama masih OPEN,
    jadi tidak pernah salah cocok utk baris yang belum resolve)."""
    with get_db() as conn:
        row = conn.execute('''
            SELECT 1 FROM signal_history
            WHERE kode = ? AND (status = 'OPEN' OR date(resolved_at) = date('now', 'localtime'))
            LIMIT 1
        ''', (kode,)).fetchone()
    return row is not None


async def record_top_picks(items: list[dict], price_lookup=None) -> list[dict]:
    """Catat sinyal baru dari hasil /api/confidence (items sudah diurut
    confidence_score menurun). Hanya MAX_RECORDED_PER_DAY teratas yang skornya
    >= MIN_SCORE_TO_RECORD, dan SATU kode SAHAM cuma boleh punya SATU sinyal
    OPEN pada satu waktu (lihat _has_open_signal) -- kalau kode itu masih
    jadi Top Pick besok/lusa, TIDAK dicatat lagi sbg entry baru selama yang
    sebelumnya belum resolved, supaya Audit Sinyal tidak menumpuk banyak
    entry konkuren utk saham yang sama.

    Melewati saham tanpa potensi_naik_pct/risiko_turun_pct valid (mis. GOTO
    yang sedang flat di harga floor -- lihat catatan di core/charts/
    snr_chart.py) karena TP/SL tidak bisa didefinisikan dengan wajar.

    price_lookup (opsional): async callable(kode) -> float | None utk ambil
    harga REAL-TIME (reuse _realtime_price yang sudah ada di web/app.py)
    sebagai entry_price, BUKAN it['harga'] (closing harian yang bisa basi
    sampai 1 hari bursa -- entry yang dicatat dari harga penutupan yang SAMA
    dipakai buat menghitung sinyalnya sendiri secara teknis tidak pernah
    benar-benar bisa dieksekusi user, ini bentuk lookahead bias kecil).
    Kalau price_lookup None atau gagal/return None utk suatu kode, fallback
    jujur ke it['harga'] (closing harian) -- tetap lebih baik daripada
    tidak mencatat entry sama sekali.

    'pattern' (opsional, dari core/screening_pro.py::detect_patterns) ikut
    disimpan kalau ada di item -- konteks tambahan "kenapa sinyal ini
    muncul", ditampilkan di Audit Sinyal/kartu Signal Confirmed.

    Returns LIST sinyal yang baru disimpan (bukan cuma jumlah) -- caller
    (web/app.py) pakai ini utk kirim notifikasi Telegram berisi detail
    entry/TP/SL, bukan sekadar angka."""
    _ensure_table()
    if _is_bursa_weekend():
        return []  # lihat _is_bursa_weekend() -- jangan catat sinyal "baru" dgn harga basi
    candidates = [
        it for it in items
        if it.get("confidence_score", 0) >= MIN_SCORE_TO_RECORD
        and it.get("potensi_naik_pct") is not None
        and it.get("risiko_turun_pct") is not None
        and it.get("risiko_turun_pct") > 0
        and it.get("harga")
    ][:MAX_RECORDED_PER_DAY]

    if not candidates:
        return []

    saved = []
    for it in candidates:
        if _has_open_signal(it["kode"]):
            continue

        # Prioritas: entry_price dari SKENARIO Trading Plan yang BENERAN
        # kena hari itu (confidence() di web/app.py -- normal/pullback/deep/
        # breakout) -- ini FAKTA harga yang sudah terjadi hari itu, BUKAN
        # prediksi, jadi TIDAK BOLEH ditimpa harga real-time yang mungkin
        # sudah bergerak jauh dari level itu (bug NYATA: sebelumnya entry
        # SELALU ditimpa harga real-time sesaat sinyal dicatat, membuat
        # TP/SL yang dihitung dari skenario jadi tidak nyambung dgn entry
        # yang benar-benar tersimpan -- laporan user: "raja low nya 3960
        # kena area pullback ... udh kena area tp"). price_lookup (real-
        # time) HANYA dipakai sbg fallback kalau caller tidak menyediakan
        # entry_price skenario sama sekali (mis. item lama/pemanggil lain).
        entry_price = it.get("entry_price")
        if entry_price is None:
            entry_price = it["harga"]
            if price_lookup is not None:
                try:
                    live_price = await price_lookup(it["kode"])
                    if live_price:
                        entry_price = live_price
                except Exception:
                    pass  # fail-open: tetap pakai closing harian, jangan gagalkan pencatatan

        tp_pct, sl_pct = it["potensi_naik_pct"], it["risiko_turun_pct"]
        # TP2/TP3 (permintaan user: "kena tp1 tandai, lanjut ke tp
        # selanjutnya") -- ikut disimpan kalau caller sudah menyediakan
        # (confidence() sekarang menyertakan tp2_pct/tp3_pct dari skenario
        # trading plan yang sama dgn tp1_pct/tp_pct), fallback ke relasi
        # tp1x2/tp1x3 (SAMA dgn yang dipakai _calc_entry_levels) kalau
        # caller lama belum menyediakannya -- supaya backward-compatible
        # tanpa memaksa SEMUA pemanggil diperbarui sekaligus.
        tp2_pct = it.get("tp2_pct") or (tp_pct * 2)
        tp3_pct = it.get("tp3_pct") or (tp_pct * 3)
        pattern = it.get("pattern")
        # Re-cek TEPAT sebelum INSERT, TANPA `await` lagi di antaranya --
        # menutup celah race yang ditemukan lewat verifikasi adversarial:
        # klausul (b) _has_open_signal (resolved HARI INI) TIDAK dijamin
        # index unik manapun (beda dgn klausul OPEN yang dijamin
        # idx_signal_unique_open_kode) -- kalau `await price_lookup(...)`
        # di atas kebetulan berbarengan dgn task LAIN yang me-resolve
        # sinyal kode ini hari ini (mis. audit_open_signals via siklus
        # background), pengecekan PERTAMA di atas bisa sudah basi.
        # Karena tidak ada `await` antara baris ini dan INSERT OR IGNORE
        # di bawah, event loop tidak bisa berpindah task di celah ini --
        # secara efektif atomic thd race yang sama persis.
        if _has_open_signal(it["kode"]):
            continue
        with get_db() as conn:
            cur = conn.execute('''
                INSERT OR IGNORE INTO signal_history
                    (kode, entry_price, tp_pct, tp2_pct, tp3_pct, sl_pct, confidence_score, ai_score, recommendation, pattern, source, recorded_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'TOP_PICK', datetime('now', 'localtime'))
            ''', (
                it["kode"], entry_price, tp_pct, tp2_pct, tp3_pct, sl_pct,
                it.get("confidence_score"), it.get("ai_score"), it.get("ai_rating"), pattern,
            ))
            # OR IGNORE: kalau baris ini SEBENARNYA sudah tercatat proses/
            # task lain di celah antara SELECT di atas dan INSERT ini
            # (race utk klausul OPEN, lihat idx_signal_unique_open_kode di
            # _ensure_table), constraint UNIQUE membuat SQLite diam-diam
            # skip insert ini -- rowcount jadi 0, bukan exception. Jangan
            # masukkan ke `saved` (bukan baris baru, caller tidak perlu
            # kirim notifikasi lagi).
            if cur.rowcount == 0:
                continue
            new_id = cur.lastrowid
        saved.append({
            "id": new_id, "kode": it["kode"], "entry_price": entry_price,
            "tp_pct": tp_pct, "tp2_pct": tp2_pct, "tp3_pct": tp3_pct, "sl_pct": sl_pct,
            "tp_price": round(entry_price * (1 + tp_pct / 100), 2),
            "sl_price": round(entry_price * (1 - sl_pct / 100), 2),
            "confidence_score": it.get("confidence_score"), "pattern": pattern,
            "source": "TOP_PICK", "direction": "BUY",
        })
    return saved


# record_macd_cross_signals() DIHAPUS (sebelumnya sengaja dibiarkan ada
# tapi tidak dipanggil, "in case direvive") -- verifikasi adversarial
# menemukan ini jadi LANDMINE nyata: fungsi ini masih pakai dedup date-
# based lamanya sendiri (bukan _has_open_signal), jadi kalau PERNAH
# di-wire ulang tanpa ikut memperbarui dedup-nya, bug ANTM/RAJA (kode
# yang sama dapat sinyal baru di hari yang sama saat sinyal lain utk
# kode itu resolve) akan muncul lagi lewat jalur ini -- padahal source
# MACD_CROSS sendiri sudah permanen nonaktif (migrasi ketujuh menghapus
# SEMUA baris source ini tiap startup, komentarnya sendiri bilang "tidak
# akan pernah ada baris baru lagi"). Kode mati yang bertentangan dgn
# invarian saat ini lebih berbahaya drpd tidak ada kode sama sekali.

# Maksimum berapa anomali volume "Smart Money" per hari yang dicatat --
# alasan sama dengan MACD_CROSS_MAX_PER_DAY (jangan bising).
SMART_MONEY_MAX_PER_DAY = 10

# Kategori _sm_classify() (web/app.py) yang dipetakan ke arah BUY --
# audit_open_signals()/get_signal_report() baru mendukung matematika
# long-only (TP di atas entry, SL di bawah), jadi Distribusi/Distribusi
# Agresif SENGAJA TIDAK dipetakan dulu (butuh kolom `direction` + logic
# bidirectional baru utk direkam sbg sinyal SELL/short -- keputusan
# terbuka utk fase 2, lihat memory smart_money_scanner_audit_fix.md).
SMART_MONEY_BUY_POLA = {"Akumulasi", "Akumulasi Agresif", "Siluman (quiet buy)", "Breakout Volume"}

# Kategori Distribusi SEKARANG direkam sbg entry SELL (untung kalau harga
# TURUN) -- audit_open_signals()/get_signal_report() sudah mendukung
# matematika bidirectional lewat kolom `direction`.
SMART_MONEY_SELL_POLA = {"Distribusi", "Distribusi Agresif"}


async def record_smart_money_signals(items: list[dict], price_lookup=None) -> list[dict]:
    """Catat entry point dari anomali volume Smart Money (_process_sm_df,
    web/app.py) sebagai source ketiga yang independen. Kategori akumulasi
    (SMART_MONEY_BUY_POLA) direkam sbg direction='BUY'; kategori distribusi
    (SMART_MONEY_SELL_POLA) direkam sbg direction='SELL' (untung kalau
    harga TURUN -- lihat audit_open_signals utk matematika bidirectional).

    Beda dari record_top_picks()/record_macd_cross_signals(): item di
    sini adalah hasil SCAN VOLUME (kode, pola, chg1/chg5/vol_ratio/rsi),
    BUKAN item confidence() -- caller (web/app.py) WAJIB sudah meng-
    enrich tiap item dgn potensi_naik_pct/risiko_turun_pct/likuiditas/
    confidence_score/ai_score dari hasil confidence() yang SAMA (join by
    kode), supaya TP/SL yang dicatat identik dgn yang sudah dihitung utk
    Top Pick -- BUKAN dihitung ulang terpisah.

    PENTING soal arah tp_pct/sl_pct: potensi_naik_pct/risiko_turun_pct dari
    confidence() dihitung dgn asumsi POSISI BUY (target=R1/naik, stop=
    S1/turun) -- level S1/R1-nya sendiri OBJEKTIF (tidak tergantung arah
    posisi), tapi makna "target" vs "stop" HARUS ditukar utk SELL: target
    profit SELL = harga turun ke S1 (=risiko_turun_pct BUY), stop loss
    SELL = harga naik ke R1 (=potensi_naik_pct BUY). Salah tukar di sini
    akan membuat SELL "untung" ketika harga naik -- kebalikan dari makna
    Distribusi itu sendiri.

    Kriteria PENAPISAN: saham likuid & TP/SL valid supaya sinyal bisa
    dieksekusi secara wajar.

    Dedup via _has_open_signal SEKARANG per-KODE SAJA (lintas semua
    source) -- kalau kode itu SUDAH punya sinyal OPEN dari TOP_PICK (atau
    sebaliknya), TIDAK direkam lagi sbg SMART_MONEY terpisah. Awalnya
    dedup di sini cuma scoped ke source='SMART_MONEY' sendiri (boleh
    tumpang tindih dgn TOP_PICK utk "membandingkan teori entry"), tapi
    user melihat langsung di UI itu kelihatan persis seperti "double" yang
    membingungkan -- lihat migrasi keenam di _ensure_table.

    price_lookup/pattern/return: lihat docstring record_top_picks(), pola
    yang sama persis dipakai di sini."""
    _ensure_table()
    if _is_bursa_weekend():
        return []  # lihat _is_bursa_weekend() -- jangan catat sinyal "baru" dgn harga basi
    candidates = [
        it for it in items
        if it.get("pola") in SMART_MONEY_BUY_POLA | SMART_MONEY_SELL_POLA
        and it.get("likuiditas") in ("Sangat Likuid", "Likuid")
        and it.get("potensi_naik_pct") is not None
        and it.get("risiko_turun_pct") is not None
        and it.get("risiko_turun_pct") > 0
        and it.get("harga")
    ][:SMART_MONEY_MAX_PER_DAY]

    if not candidates:
        return []

    saved = []
    for it in candidates:
        if _has_open_signal(it["kode"]):
            continue

        # Prioritas: entry_price dari SKENARIO Trading Plan yang BENERAN
        # kena hari itu (confidence() di web/app.py -- normal/pullback/deep/
        # breakout) -- ini FAKTA harga yang sudah terjadi hari itu, BUKAN
        # prediksi, jadi TIDAK BOLEH ditimpa harga real-time yang mungkin
        # sudah bergerak jauh dari level itu (bug NYATA: sebelumnya entry
        # SELALU ditimpa harga real-time sesaat sinyal dicatat, membuat
        # TP/SL yang dihitung dari skenario jadi tidak nyambung dgn entry
        # yang benar-benar tersimpan -- laporan user: "raja low nya 3960
        # kena area pullback ... udh kena area tp"). price_lookup (real-
        # time) HANYA dipakai sbg fallback kalau caller tidak menyediakan
        # entry_price skenario sama sekali (mis. item lama/pemanggil lain).
        entry_price = it.get("entry_price")
        if entry_price is None:
            entry_price = it["harga"]
            if price_lookup is not None:
                try:
                    live_price = await price_lookup(it["kode"])
                    if live_price:
                        entry_price = live_price
                except Exception:
                    pass  # fail-open: tetap pakai closing harian, jangan gagalkan pencatatan

        is_sell = it.get("pola") in SMART_MONEY_SELL_POLA
        direction = "SELL" if is_sell else "BUY"
        # Lihat catatan di docstring: utk SELL, tp_pct/sl_pct DITUKAR dari
        # potensi_naik_pct/risiko_turun_pct (yang dihitung dgn asumsi BUY).
        if is_sell:
            tp_pct, sl_pct = it["risiko_turun_pct"], it["potensi_naik_pct"]
        else:
            tp_pct, sl_pct = it["potensi_naik_pct"], it["risiko_turun_pct"]
        # TP2/TP3 (lihat catatan sama di record_top_picks()) -- utk SELL
        # (jalur ini SAAT INI TIDAK PERNAH tercapai lagi krn gerbang
        # Ringkasan Sinyal Teknikal cuma meloloskan BELI, lihat
        # _record_smart_money_cycle, tapi tetap disediakan simetris utk
        # konsistensi kalau SELL direvive) pakai relasi tp1x2/tp1x3 dari
        # tp_pct yang SUDAH ditukar di atas.
        tp2_pct = it.get("tp2_pct") if not is_sell else None
        tp3_pct = it.get("tp3_pct") if not is_sell else None
        tp2_pct = tp2_pct or (tp_pct * 2)
        tp3_pct = tp3_pct or (tp_pct * 3)
        pattern = it.get("pola")
        # Re-cek TEPAT sebelum INSERT, TANPA `await` lagi di antaranya --
        # lihat catatan sama di record_top_picks() soal race klausul (b).
        if _has_open_signal(it["kode"]):
            continue
        with get_db() as conn:
            cur = conn.execute('''
                INSERT OR IGNORE INTO signal_history
                    (kode, entry_price, tp_pct, tp2_pct, tp3_pct, sl_pct, confidence_score, ai_score, recommendation, pattern, source, recorded_at, direction)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'SMART_MONEY', datetime('now', 'localtime'), ?)
            ''', (
                it["kode"], entry_price, tp_pct, tp2_pct, tp3_pct, sl_pct,
                it.get("confidence_score"), it.get("ai_score"), it.get("ai_rating"), pattern, direction,
            ))
            # Lihat catatan sama di record_top_picks(): OR IGNORE + index
            # unique adalah pengaman ATOMIC terakhir terhadap race antara
            # SELECT dedup di atas dan INSERT ini.
            if cur.rowcount == 0:
                continue
            new_id = cur.lastrowid
        if is_sell:
            tp_price = round(entry_price * (1 - tp_pct / 100), 2)
            sl_price = round(entry_price * (1 + sl_pct / 100), 2)
        else:
            tp_price = round(entry_price * (1 + tp_pct / 100), 2)
            sl_price = round(entry_price * (1 - sl_pct / 100), 2)
        saved.append({
            "id": new_id, "kode": it["kode"], "entry_price": entry_price,
            "tp_pct": tp_pct, "tp2_pct": tp2_pct, "tp3_pct": tp3_pct, "sl_pct": sl_pct,
            "tp_price": tp_price, "sl_price": sl_price,
            "confidence_score": it.get("confidence_score"), "pattern": pattern,
            "source": "SMART_MONEY", "direction": direction,
        })
    return saved


async def audit_open_signals(price_lookup) -> list[dict]:
    """Cek ulang semua sinyal berstatus OPEN terhadap harga TERKINI.

    price_lookup: async callable(kode: str) -> tuple[float, date] | None --
    caller (web/app.py) yang menyediakan cara ambil harga (REUSE _clean/
    harga close terakhir yang sudah ada, supaya modul ini TIDAK melakukan
    I/O jaringan sendiri dan tetap mudah ditest tanpa mock network) SEKALIGUS
    tanggal bar historis di balik harga itu.

    Tanggal bar itu WAJIB ada (bukan cuma harga) krn BUG NYATA yang
    ditemukan live: TPIA & ARTO ter-SL_HIT padahal user melihat sendiri
    harganya NAIK hari itu -- ternyata bar yfinance utk "hari ini" masih
    NaN/belum terbit, jadi setelah dropna() harga yang kepakai adalah
    closing BEBERAPA HARI SEBELUM sinyal itu bahkan direkam (data yang
    SAMA SEKALI belum berubah sejak direkam, bukan penurunan harga
    sungguhan). Kalau tanggal bar itu LEBIH LAMA dari tanggal sinyal
    direkam (price_date < recorded_date), berarti belum ada informasi
    harga BARU sama sekali sejak direkam -- sinyal itu dilewati (tetap
    OPEN, dicoba lagi siklus berikutnya), TIDAK PERNAH diresolve pakai
    data yang lebih basi dari titik awalnya sendiri.

    Target TP kini 3 level (tp_pct/tp2_pct/tp3_pct, lihat migrasi ke-14) --
    permintaan user: "misalkan kena area tp1 tandai juga lanjut ke area tp
    selanjutnya", jadi TP1/TP2 tercapai HANYA menaikkan tp_level_hit (posisi
    TETAP OPEN, tidak ditutup); hanya TP3 yang jadi status akhir TP_HIT.
    SL selalu final TIDAK PEDULI tp_level_hit sudah berapa (user tidak minta
    stop-loss dipindah ke breakeven, jadi risiko awal tetap berlaku penuh
    selama posisi masih terbuka).

    Status akhir (BUY, arah default/mayoritas -- harga diharapkan NAIK):
    - TP_HIT: harga >= entry x (1 + tp3_pct/100)
    - SL_HIT: harga <= entry x (1 - sl_pct/100)

    Utk SELL (arah baru -- Distribusi/Distribusi Agresif Smart Money,
    harga diharapkan TURUN, "untung" berarti harga jatuh sejumlah tp_pct):
    - TP_HIT: harga <= entry x (1 - tp3_pct/100)
    - SL_HIT: harga >= entry x (1 + sl_pct/100)

    - EXPIRED: belum kena TP3/SL tapi sudah lewat MAX_HOLD_DAYS sejak dicatat
    - OPEN: belum satupun kondisi di atas terpenuhi, tetap dibiarkan terbuka

    return_pct SELALU direpresentasikan sbg untung(+)/rugi(-), BUKAN
    sekadar arah pergerakan harga -- utk SELL yang untung (harga turun),
    return_pct tetap POSITIF, konsisten makna dgn BUY (supaya stats_by_
    source/win-rate bisa digabung apa adanya tanpa perlu tahu direction).

    Returns LIST kejadian yang BARU SAJA terjadi di pemanggilan ini, tiap
    dict punya key "kind": "resolved" (status akhir, sama seperti dulu)
    atau "tp_progress" (TP1/TP2 baru tercapai, posisi masih OPEN) --
    caller pakai field ini utk memilih format notifikasi Telegram yang
    sesuai (lihat format_signal_resolved vs format_signal_tp_progress di
    core/telegram_notify.py). price_lookup HANYA memberi satu titik harga
    (bukan rentang High/Low harian), jadi kalau harga loncat lewat lebih
    dari 1 level TP sekaligus (mis. gap up), level menengah yang mungkin
    "dilewati" tidak bisa dipastikan tersentuh -- diambil level TERTINGGI
    yang terbukti tercapai dari harga saat ini saja."""
    _ensure_table()
    with get_db() as conn:
        open_rows = conn.execute(
            "SELECT id, kode, recorded_at, entry_price, tp_pct, tp2_pct, tp3_pct, sl_pct, "
            "source, pattern, direction, tp_level_hit FROM signal_history WHERE status = 'OPEN'"
        ).fetchall()

    just_resolved = []
    for row in open_rows:
        result = await price_lookup(row["kode"])
        if result is None:
            continue
        price, price_date = result
        if price is None or price <= 0:
            continue

        recorded_at = datetime.fromisoformat(row["recorded_at"])
        # Harga basi (bar-nya lebih lama dari recorded_at) TIDAK BOLEH
        # dipakai utk mengklaim TP/SL tercapai (lihat catatan panjang di
        # docstring) -- TAPI EXPIRED murni berbasis WAKTU (bukan klaim
        # level harga tertentu), jadi tetap harus bisa jalan walau harga
        # basi -- kalau tidak, saham yang feed harganya macet permanen
        # (suspensi/delisting berkepanjangan) akan tersangkut OPEN
        # SELAMANYA, tidak pernah bisa expire sama sekali.
        is_stale = price_date is not None and price_date < recorded_at.date()

        entry = row["entry_price"]
        is_sell = row["direction"] == "SELL"

        def _level_price(pct):
            if pct is None:
                return None
            return entry * (1 - pct / 100) if is_sell else entry * (1 + pct / 100)

        def _reached(target):
            if target is None:
                return False
            return price <= target if is_sell else price >= target

        sl_price = entry * (1 + row["sl_pct"] / 100) if is_sell else entry * (1 - row["sl_pct"] / 100)
        tp1_price = _level_price(row["tp_pct"])
        tp2_price = _level_price(row["tp2_pct"])
        tp3_price = _level_price(row["tp3_pct"])

        age_days = (datetime.now() - recorded_at).days

        sl_hit = (price >= sl_price) if is_sell else (price <= sl_price)

        reached_level = 0
        if _reached(tp1_price):
            reached_level = 1
        if _reached(tp2_price):
            reached_level = 2
        if _reached(tp3_price):
            reached_level = 3

        # Level TERTINGGI yang benar-benar dikonfigurasi utk sinyal ini --
        # baris lama/manual (mis. test yang insert langsung via SQL tanpa
        # tp2_pct/tp3_pct) TIDAK dapat backfill migrasi ke-14 kalau
        # di-insert SETELAH _ensure_table() jalan, jadi tp2_pct/tp3_pct-nya
        # NULL: sinyal begini harus tetap berlaku SATU level lama (TP1
        # tercapai = langsung final), bukan menunggu level yang tidak
        # pernah ada.
        if row["tp3_pct"] is not None:
            configured_max, final_pct = 3, row["tp3_pct"]
        elif row["tp2_pct"] is not None:
            configured_max, final_pct = 2, row["tp2_pct"]
        else:
            configured_max, final_pct = 1, row["tp_pct"]

        prev_level = row["tp_level_hit"] or 0
        kind, status, return_pct = None, None, None

        if is_stale:
            # Harga basi -- lewati klaim TP/SL/tp_progress sepenuhnya,
            # cuma EXPIRED (berbasis waktu) yang boleh jalan.
            if age_days >= MAX_HOLD_DAYS:
                kind, status = "resolved", "EXPIRED"
                return_pct = round((entry / price - 1) * 100, 2) if is_sell else round((price / entry - 1) * 100, 2)
        elif sl_hit:
            kind, status, return_pct = "resolved", "SL_HIT", -row["sl_pct"]
        elif reached_level >= configured_max and reached_level > 0:
            kind, status, return_pct = "resolved", "TP_HIT", final_pct
        elif reached_level > prev_level:
            kind = "tp_progress"  # TP1/TP2 baru tercapai -- TETAP OPEN
        elif age_days >= MAX_HOLD_DAYS:
            kind, status = "resolved", "EXPIRED"
            return_pct = round((entry / price - 1) * 100, 2) if is_sell else round((price / entry - 1) * 100, 2)

        if kind is None:
            continue  # tetap OPEN, tidak ada perubahan

        if kind == "tp_progress":
            with get_db() as conn:
                conn.execute(
                    "UPDATE signal_history SET tp_level_hit = ? WHERE id = ?",
                    (reached_level, row["id"]),
                )
            just_resolved.append({
                "id": row["id"], "kode": row["kode"], "entry_price": entry,
                "kind": "tp_progress", "tp_level_hit": reached_level, "price": price,
                "recorded_at": row["recorded_at"], "source": row["source"],
                "pattern": row["pattern"], "direction": row["direction"],
            })
            continue

        # SL_HIT/EXPIRED mempertahankan tp_level_hit historis (TP1/TP2 yang
        # SUDAH terbukti tercapai sebelumnya tetap tercatat apa adanya,
        # bukan direset ke 0 hanya karena harga sekarang sudah turun lagi).
        final_level = reached_level if status == "TP_HIT" else prev_level
        with get_db() as conn:
            conn.execute('''
                UPDATE signal_history
                SET status = ?, resolved_at = datetime('now', 'localtime'), resolved_price = ?,
                    return_pct = ?, days_to_resolve = ?, tp_level_hit = ?
                WHERE id = ?
            ''', (status, price, return_pct, age_days, final_level, row["id"]))

        just_resolved.append({
            "id": row["id"], "kode": row["kode"], "entry_price": entry,
            "kind": "resolved", "status": status, "resolved_price": price, "return_pct": return_pct,
            "days_to_resolve": age_days, "recorded_at": row["recorded_at"],
            "source": row["source"], "pattern": row["pattern"], "direction": row["direction"],
        })

    return just_resolved


def _compute_stats(closed: list[dict]) -> dict | None:
    """Statistik agregat dari sinyal yang SUDAH SELESAI (TP_HIT/SL_HIT/
    EXPIRED). Returns None kalau daftar kosong -- caller/frontend WAJIB
    menampilkan ini sebagai "belum cukup data", BUKAN 0% (dipakai baik
    untuk statistik gabungan maupun per-source di get_signal_report)."""
    if not closed:
        return None
    wins = [s for s in closed if s["status"] == "TP_HIT"]
    losses = [s for s in closed if s["status"] == "SL_HIT"]
    decided = wins + losses  # EXPIRED sengaja di luar win-rate (bukan menang atau kalah jelas)
    win_rate = round(len(wins) / len(decided) * 100, 1) if decided else None
    avg_return = round(sum(s["return_pct"] for s in closed) / len(closed), 2)
    avg_days = round(sum(s["days_to_resolve"] for s in closed) / len(closed), 1)
    return {
        "n_closed": len(closed),
        "n_tp_hit": len(wins),
        "n_sl_hit": len(losses),
        "n_expired": len(closed) - len(wins) - len(losses),
        "win_rate": win_rate,
        "avg_return_pct": avg_return,
        "avg_days_to_resolve": avg_days,
    }


def get_signal_report() -> dict:
    """Ringkasan lengkap: daftar sinyal (terbaru dulu) + statistik agregat
    yang HANYA dihitung dari sinyal yang SUDAH SELESAI (TP_HIT/SL_HIT/
    EXPIRED) -- sinyal OPEN sengaja tidak ikut dihitung ke win rate karena
    belum ada hasil sungguhan (menganggapnya menang/kalah sekarang = angka
    bohong).

    Returns dict dengan 'signals' (list), 'stats' (gabungan semua source,
    bisa None kalau belum ada satupun sinyal yang selesai), dan
    'stats_by_source' (dict {source: stats-shape yang sama}, HANYA berisi
    source yang sudah punya minimal 1 sinyal selesai) -- supaya user bisa
    bandingkan validitas Top Pick vs MACD Cross sebagai teori entry
    terpisah, bukan tercampur jadi satu angka."""
    _ensure_table()
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM signal_history ORDER BY recorded_at DESC LIMIT 200"
        ).fetchall()

    signals = [dict(r) for r in rows]
    # Harga TP/SL eksplisit (Rupiah) -- dihitung dari entry_price x tp_pct/
    # sl_pct yang SAMA PERSIS dipakai audit_open_signals(), bukan angka
    # baru. Ditambahkan di sini (bukan disimpan di kolom terpisah) supaya
    # SATU sumber kebenaran: kalau formulanya berubah, tidak ada risiko
    # nilai tersimpan jadi basi/tidak sinkron dengan logic audit.
    for s in signals:
        is_sell = s.get("direction") == "SELL"
        sign = -1 if is_sell else 1
        # SELL (Distribusi Smart Money): untung kalau harga TURUN --
        # TP di BAWAH entry, SL di ATAS entry, kebalikan dari BUY.
        s["tp_price"] = round(s["entry_price"] * (1 + sign * s["tp_pct"] / 100), 2)
        s["sl_price"] = round(s["entry_price"] * (1 - sign * s["sl_pct"] / 100), 2)
        s["tp2_price"] = (round(s["entry_price"] * (1 + sign * s["tp2_pct"] / 100), 2)
                          if s.get("tp2_pct") is not None else None)
        s["tp3_price"] = (round(s["entry_price"] * (1 + sign * s["tp3_pct"] / 100), 2)
                          if s.get("tp3_pct") is not None else None)

    closed = [s for s in signals if s["status"] in ("TP_HIT", "SL_HIT", "EXPIRED")]
    stats = _compute_stats(closed)
    stats_by_source = {}
    for source in sorted({s["source"] for s in closed}):
        source_stats = _compute_stats([s for s in closed if s["source"] == source])
        if source_stats is not None:
            stats_by_source[source] = source_stats

    n_open = sum(1 for s in signals if s["status"] == "OPEN")
    return {
        "signals": signals, "stats": stats, "stats_by_source": stats_by_source,
        "n_open": n_open, "n_total": len(signals),
    }
