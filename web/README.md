# Web App (Ranah Saham)

Antarmuka web di atas logika `core/`. **Tidak ada logika analisis baru di sini** —
endpoint hanya membungkus fungsi `core/`. Versi web-only: tanpa Telegram, tanpa
akun/login, tanpa watchlist/alert.

## Cara jalan (lokal)

```bash
pip install -r requirements.txt
uvicorn web.app:app --host 0.0.0.0 --port 8000
```

Buka http://localhost:8000

## Endpoint utama (semua GET, kecuali disebut)

| Path | Hasil |
|---|---|
| `/api/health` | cek status |
| `/api/tickers` | daftar emiten IDX (kode+nama) untuk pencarian |
| `/api/analyze/{kode}` | AI Score, indikator, SMC, insight |
| `/api/ohlc/{kode}` · `/api/normchart` | data candle/ternormalisasi untuk chart interaktif |
| `/api/chart/{kode}` | PNG grafik (matplotlib) |
| `/api/screener` · `/api/screenerpro` · `/api/bsjp` · `/api/filter` | screening & filter |
| `/api/confidence` · `/api/confluence/{kode}` | skor keyakinan & confluence indikator |
| `/api/plan/{kode}` · `/api/rr` · `/api/target/{kode}` · `/api/cutloss/{kode}` · `/api/positionsize` | rencana trading |
| `/api/snr/{kode}` · `/api/patternscan/{kode}` · `/api/multitimeframe/{kode}` | S/R, pola, multi-timeframe |
| `/api/smc/{kode}/{kind}` · `/api/smc_data/{kode}` | Smart Money Concepts |
| `/api/backtest` · `/api/backtestpro/{kode}` | validasi historis |
| `/api/sektor` · `/api/rotasi` · `/api/rs/{kode}` · `/api/beta/{kode}` · `/api/correlation` | sektor & kekuatan relatif |
| `/api/compare` | banding beberapa saham |
| `/api/breadth` · `/api/macro` · `/api/foreign-flow` · `/api/x15` · `/api/holders/{kode}` | konteks pasar, aliran asing, pemegang |
| `/api/fundamental/{kode}` | fundamental ringkas + estimasi harga wajar |
| `/api/news` · `/api/ihsgnews` · `/api/insight/{kode}` | berita & narasi |
| `/api/ihsg` · `/api/ihsg/report` | analisis IHSG + laporan PDF |
| `/api/report/{kode}` | laporan saham (PDF) |
| `/` | frontend SPA (`web/static/index.html`) |

## Frontend (`web/static/index.html`)

SPA satu file tanpa framework dengan tab analisis: Beranda, Analisis, IHSG,
Screener, Top Pick, Heatmap, Pasar, Sektor, Banding, Risk, Makro, Asing,
Pemegang, Berita, Edukasi, Backtest. Chart candlestick interaktif memakai
TradingView lightweight-charts via CDN. Semua perhitungan di server.

## Catatan keamanan

Tidak ada token/kunci apa pun di sisi browser — semua rahasia tetap di server.
