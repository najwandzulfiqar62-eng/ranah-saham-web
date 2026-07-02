# Ranah Saham — Web

Aplikasi web analisis teknikal saham Bursa Efek Indonesia (BEI). Sistem mengambil
data OHLCV publik dari Yahoo Finance, menghitung indikator teknikal, melakukan
screening dan penilaian sinyal, menyusun rencana trading otomatis, lalu menyajikan
semuanya melalui antarmuka web satu halaman.

> Versi ini **web-only**. Komponen bot Telegram dan fitur personal (login,
> watchlist, alert) dari versi lama sudah dihapus agar sistem fokus sebagai
> perangkat analisis.

## Struktur Folder

```
requirements.txt          # Dependency Python
data/saham.xlsx           # Daftar emiten IDX (≈957 baris; "Pemantauan Khusus" dikecualikan)

core/                     # Mesin analisis murni (tanpa kode antarmuka)
├── config.py             # Path data & parameter batching Yahoo Finance
├── database.py           # SQLite — khusus cache data fundamental
├── stock_data.py         # load_tickers(), normalisasi kolom yfinance
├── async_yf.py           # Pembungkus async untuk yfinance (anti-blocking)
├── indicators.py         # RSI, MACD, Bollinger, ATR, StochRSI, Support/Resistance
├── screener.py           # Screening sinyal/breakout
├── screening_pro.py      # Screening multi-filter lanjutan
├── ai_score.py           # Penilaian sinyal rule-based (Strong Buy/Buy/Hold/Sell)
├── trading_plan.py       # Entry, stop loss, target profit, RRR, position sizing
├── risk_management.py    # RR ratio, target, cutloss (ATR), position sizing (lot IDX)
├── compare.py            # Pembandingan beberapa saham
├── market.py             # Filter pasar, top gainer/volume, ringkasan harian
├── backtest.py           # Validasi statistik historis untuk kondisi sinyal
├── relative_strength.py  # Kekuatan relatif vs IHSG/sektor
├── sector_rotation.py    # Beta, peringkat & rotasi sektor
├── volume_patterns.py    # Volume spike, Accumulation/Distribution Line
├── smc.py                # Smart Money Concepts: BOS/CHoCH, Order Block, FVG, Liquidity
├── wyckoff.py            # Deteksi fase Wyckoff
├── fundamental.py        # Fundamental ringkas (PE/PBV/ROE/DER/dividen/EPS)
├── insight.py            # Narasi analisis otomatis
├── news*.py              # Pengambil & penyaring berita + sinyal teknikal
├── report.py             # Penyusun data laporan
├── charts/               # Generator grafik (matplotlib) + laporan PDF
└── ihsg/                 # Analisis IHSG (analisis, strategi, chart)

web/                      # Lapisan web (FastAPI) di atas core/
├── app.py                # HTTP API — membungkus fungsi core/, tanpa logika analisis baru
└── static/index.html     # SPA satu file (tanpa framework) + service worker

tests/                    # pytest + FastAPI TestClient (endpoint inti, yfinance di-mock)
Dockerfile, docker-compose.yml  # Image app + service Redis untuk deployment/dev
```

## Cara Menjalankan (lokal)

```bash
pip install -r requirements.txt
uvicorn web.app:app --host 0.0.0.0 --port 8000
```

Lalu buka http://localhost:8000

Redis bersifat opsional untuk pengembangan lokal: tanpa Redis berjalan,
aplikasi tetap bisa dipakai (cache & rate-limit fail-open ke "nonaktif"),
hanya lebih lambat karena setiap request ke Yahoo Finance tidak di-cache.
Untuk mengaktifkan cache/rate-limit, jalankan Redis dan set `REDIS_URL`
(lihat `.env.example`).

## Testing

```bash
pip install pytest
pytest
```

Suite tes (`tests/`) memakai `TestClient` FastAPI dan me-mock yfinance
supaya tidak menyentuh jaringan asli. Cakupannya sengaja dibatasi ke
endpoint inti (`/api/analyze`, `/api/ohlc`, `/api/compare`, `/api/chart`,
`/api/smc`, `/api/macro`) — bukan seluruh 40+ endpoint di `web/app.py`.

## Menjalankan dengan Docker

```bash
docker compose up --build
```

Ini menjalankan app + Redis sekaligus (lihat `docker-compose.yml`), dengan
cache fundamental SQLite disimpan di named volume `fundamental_cache` agar
tidak hilang saat container di-restart. Lalu buka http://localhost:8000.

## Catatan

- Semua data & perhitungan berjalan di server; frontend hanya menampilkan.
- Cache TTL (analisis 5 menit, harga real-time 1 menit) dan rate limit
  per-IP (120 request/menit) memakai Redis, dengan fallback fail-open
  (nonaktif, bukan error) kalau Redis tidak terjangkau — lihat `web/app.py`.
- Analisis bersifat edukatif, **bukan rekomendasi atau nasihat keuangan**.

## Belum Termasuk (untuk publikasi nyata)

Versi ini fondasi, bukan produk publik final. Sebelum dibuka ke banyak
pengguna: hosting 24/7 + domain, HTTPS (reverse proxy), serta pemeriksaan
lisensi/ToS data sebelum redistribusi.
