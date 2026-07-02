# =========================
# SMART MONEY CONCEPT (SMC) ANALYSIS
# =========================
# FITUR BARU. Implementasi konsep Smart Money Concept (BOS, CHOCH, Order
# Block, Fair Value Gap, Liquidity Pool) berdasarkan riset definisi
# formal yang dipakai komunitas SMC/ICT (bukan tebak-tebakan implementasi).
#
# PENTING -- BATASAN JUJUR SOAL KLAIM "SMART MONEY":
# SMC mengklaim mendeteksi "jejak institusional" dari price action. Tapi
# yang BENAR-BENAR bisa diverifikasi secara obyektif cuma STRUKTUR HARGA
# itu sendiri (swing point, breakout, gap, candle pattern) -- bukan
# fakta bahwa ada institusi tertentu yang benar-benar bertransaksi di
# sana. Narasi "institutional orders menunggu di order block" itu TIDAK
# TERBUKTIKAN secara langsung dari data candle (dikonfirmasi dari riset:
# beberapa praktisi SMC eksplisit memperingatkan ini adalah "marketing
# narrative" di atas konsep supply/demand zone yang sudah ada sejak
# lama -- lihat AlgoStorm). Implementasi di modul ini mengikuti DEFINISI
# TEKNIKAL price-action-nya dengan akurat (swing structure, displacement,
# gap 3-candle), TANPA mengklaim ini benar-benar terbukti sebagai
# aktivitas institusi tertentu. Setiap handler yang memakai modul ini
# WAJIB menyertakan disclaimer ini ke user.
#
# PARAMETER SWING DETECTION:
# Memakai fractal-style pivot: titik i dianggap swing high kalau dia
# adalah titik TERTINGGI dalam window [i-left_bars, i+right_bars], dan
# swing low sebaliknya (left_bars=right_bars=5 secara default, sesuai
# konvensi umum di indikator SMC/ICT seperti dikonfirmasi dari riset).
# Implikasi PENTING: swing point di index i baru bisa DIKONFIRMASI
# setelah right_bars bar berikutnya tersedia -- jadi right_bars bar
# PALING BARU di data tidak akan punya swing point terdeteksi sama
# sekali (belum cukup data untuk konfirmasi). Ini BUKAN bug, ini
# konsisten dengan cara swing detection bekerja di seluruh industri
# (disebut "non-repainting" -- swing point tidak berubah-ubah begitu
# sudah dikonfirmasi, beda dari pendekatan naif yang "curang" melihat
# ke depan tanpa batas).

import pandas as pd


def detect_swing_points(df: pd.DataFrame, left_bars: int = 5, right_bars: int = 5) -> pd.DataFrame:
    """Deteksi swing high & swing low pakai fractal-style pivot.

    Returns df asli + 2 kolom boolean baru: 'swing_high' dan 'swing_low'.
    Index PALING BARU (sebanyak right_bars terakhir) TIDAK akan punya
    swing point terdeteksi (butuh bar setelahnya untuk konfirmasi -- ini
    desain yang benar, bukan kekurangan)."""
    df = df.copy()
    n = len(df)
    swing_high = [False] * n
    swing_low = [False] * n

    for i in range(left_bars, n - right_bars):
        window_high = df["High"].iloc[i - left_bars: i + right_bars + 1]
        window_low = df["Low"].iloc[i - left_bars: i + right_bars + 1]

        if df["High"].iloc[i] == window_high.max():
            swing_high[i] = True
        if df["Low"].iloc[i] == window_low.min():
            swing_low[i] = True

    df["swing_high"] = swing_high
    df["swing_low"] = swing_low
    return df


def detect_bos_choch(df: pd.DataFrame, left_bars: int = 5, right_bars: int = 5) -> list[dict]:
    """Deteksi Break of Structure (BOS) & Change of Character (CHOCH).

    Definisi (dari riset SMC/ICT, lihat catatan di atas file ini):
    - Trend ditentukan dari sequence swing high/low (higher high +
      higher low = uptrend, lower low + lower high = downtrend).
    - BOS: candle body CLOSE (bukan wick) melewati swing high
      sebelumnya SAAT trend sedang uptrend (atau swing low SAAT trend
      downtrend) -- konfirmasi KONTINUASI trend.
    - CHOCH: candle body CLOSE melewati swing low sebelumnya SAAT
      trend sedang uptrend (atau swing high SAAT trend downtrend) --
      sinyal AWAL kemungkinan REVERSAL (bukan garansi).

    Returns list of dict, urut kronologis, masing-masing:
    {'index': int, 'date': ..., 'type': 'BOS'|'CHOCH', 'direction':
     'bullish'|'bearish', 'price': float, 'broken_level': float}
    """
    df_swing = detect_swing_points(df, left_bars, right_bars)
    events = []

    # Track swing high/low terakhir yang TERKONFIRMASI, dan trend saat ini
    last_swing_high = None
    last_swing_low = None
    trend = None  # 'up' | 'down' | None (belum ada cukup data)

    # Track level mana yang SUDAH di-break, supaya tidak mendeteksi BOS/CHOCH
    # berulang-ulang di level yang sama akibat harga naik terus di atasnya
    last_broken_high_level = None
    last_broken_low_level = None

    for i in range(len(df_swing)):
        close = df_swing["Close"].iloc[i]

        # Cek breakout dulu (pakai swing yang TERKONFIRMASI SEBELUM index i)
        if last_swing_high is not None and close > last_swing_high and last_broken_high_level != last_swing_high:
            direction_type = "BOS" if trend == "up" else "CHOCH"
            events.append({
                "index": i, "date": df_swing.index[i], "type": direction_type,
                "direction": "bullish", "price": round(float(close), 2),
                "broken_level": round(float(last_swing_high), 2),
            })
            last_broken_high_level = last_swing_high
            trend = "up"

        if last_swing_low is not None and close < last_swing_low and last_broken_low_level != last_swing_low:
            direction_type = "BOS" if trend == "down" else "CHOCH"
            events.append({
                "index": i, "date": df_swing.index[i], "type": direction_type,
                "direction": "bearish", "price": round(float(close), 2),
                "broken_level": round(float(last_swing_low), 2),
            })
            last_broken_low_level = last_swing_low
            trend = "down"

        # Update swing high/low TERKONFIRMASI (kalau index i ini swing point)
        if df_swing["swing_high"].iloc[i]:
            last_swing_high = df_swing["High"].iloc[i]
        if df_swing["swing_low"].iloc[i]:
            last_swing_low = df_swing["Low"].iloc[i]

    return events


def detect_order_blocks(df: pd.DataFrame, left_bars: int = 5, right_bars: int = 5,
                          displacement_multiplier: float = 1.5, max_blocks: int = 5) -> list[dict]:
    """Deteksi Order Block: candle TERAKHIR berlawanan arah sebelum
    displacement (gerakan kuat) yang menghasilkan BOS/CHOCH.

    Definisi gabungan dari riset (lihat catatan di atas file ini):
    - Displacement: candle body (|close-open|) > displacement_multiplier
      x rata-rata body 20 candle sebelumnya, DAN candle ini menembus
      (close lewat) swing high/low terdekat sebelumnya.
    - Bullish OB: candle BEARISH terakhir sebelum displacement bullish.
      Validasi tambahan (dari definisi Alchemy Markets): candle ini
      juga harus punya LOW terendah di antara beberapa candle sebelum
      displacement -- bukan cuma "candle merah terakhir" sembarangan.
    - Bearish OB: kebalikannya (candle BULLISH terakhir, dengan HIGH
      tertinggi, sebelum displacement bearish).

    Returns list of dict (max max_blocks, PALING BARU duluan):
    {'type': 'BULLISH'|'BEARISH', 'ob_index', 'displacement_index',
     'zone_low', 'zone_high', 'is_fresh'}
    is_fresh = True kalau harga SETELAH displacement belum pernah
    balik menyentuh zona OB ini lagi (sesuai prinsip: OB paling valid
    di kunjungan PERTAMA, kehilangan kekuatan setelah disentuh)."""
    df_swing = detect_swing_points(df, left_bars, right_bars)
    body_size = (df["Close"] - df["Open"]).abs()
    avg_body_20 = body_size.rolling(20).mean()
    n = len(df)

    confirmed_swing_highs = [i for i in range(n) if df_swing["swing_high"].iloc[i]]
    confirmed_swing_lows = [i for i in range(n) if df_swing["swing_low"].iloc[i]]

    order_blocks = []
    seen_ob_indices = set()  # DEDUP: satu OB index hanya dicatat SEKALI,
    # walau beberapa candle displacement berurutan dalam leg yang sama
    # semuanya menembus swing level yang sama (mencegah satu order block
    # asli terhitung berulang seolah-olah beberapa OB berbeda)

    for i in range(20, n):
        candle_body = body_size.iloc[i]
        avg_body = avg_body_20.iloc[i]
        if pd.isna(avg_body) or avg_body == 0:
            continue

        is_displacement = candle_body > displacement_multiplier * avg_body
        if not is_displacement:
            continue

        is_bullish_candle = df["Close"].iloc[i] > df["Open"].iloc[i]
        relevant_highs = [s for s in confirmed_swing_highs if s < i]
        relevant_lows = [s for s in confirmed_swing_lows if s < i]

        if is_bullish_candle and relevant_highs:
            nearest_high = df["High"].iloc[relevant_highs[-1]]
            if df["Close"].iloc[i] <= nearest_high:
                continue  # bukan displacement yang menembus structure (bukan BOS)

            window_start = max(i - 10, 0)
            candidates = [j for j in range(window_start, i) if df["Close"].iloc[j] < df["Open"].iloc[j]]
            if not candidates:
                continue
            ob_idx = min(candidates, key=lambda j: df["Low"].iloc[j])
            if ob_idx in seen_ob_indices:
                continue
            seen_ob_indices.add(ob_idx)

            zone_low = df["Low"].iloc[ob_idx]
            zone_high = df["High"].iloc[ob_idx]
            is_fresh = not (df["Low"].iloc[i + 1:] <= zone_high).any() if i + 1 < n else True

            order_blocks.append({
                "type": "BULLISH", "ob_index": ob_idx, "displacement_index": i,
                "zone_low": round(float(zone_low), 2), "zone_high": round(float(zone_high), 2),
                "is_fresh": bool(is_fresh),
            })

        elif not is_bullish_candle and relevant_lows:
            nearest_low = df["Low"].iloc[relevant_lows[-1]]
            if df["Close"].iloc[i] >= nearest_low:
                continue

            window_start = max(i - 10, 0)
            candidates = [j for j in range(window_start, i) if df["Close"].iloc[j] > df["Open"].iloc[j]]
            if not candidates:
                continue
            ob_idx = max(candidates, key=lambda j: df["High"].iloc[j])
            if ob_idx in seen_ob_indices:
                continue
            seen_ob_indices.add(ob_idx)

            zone_low = df["Low"].iloc[ob_idx]
            zone_high = df["High"].iloc[ob_idx]
            is_fresh = not (df["High"].iloc[i + 1:] >= zone_low).any() if i + 1 < n else True

            order_blocks.append({
                "type": "BEARISH", "ob_index": ob_idx, "displacement_index": i,
                "zone_low": round(float(zone_low), 2), "zone_high": round(float(zone_high), 2),
                "is_fresh": bool(is_fresh),
            })

    return order_blocks[-max_blocks:][::-1]


def detect_fvg(df: pd.DataFrame, max_gaps: int = 5, only_unfilled: bool = True) -> list[dict]:
    """Deteksi Fair Value Gap (FVG): pola 3 candle berurutan.

    Definisi (dikonfirmasi dari riset, lihat catatan di atas file ini):
    - Bullish FVG: High candle[i] < Low candle[i+2] -- gap di antaranya
      adalah zona FVG (candle[i+1] di tengah adalah candle displacement
      besar yang menyebabkan gap ini).
    - Bearish FVG: Low candle[i] > High candle[i+2].

    only_unfilled: kalau True, hanya kembalikan FVG yang belum
    "terisi" sepenuhnya oleh harga setelahnya (price belum
    rebalance/fill gap ini).

    Returns list of dict (max max_gaps, PALING BARU duluan):
    {'type', 'index' (candle tengah/displacement), 'zone_low',
     'zone_high', 'filled'}."""
    n = len(df)
    fvgs = []

    for i in range(n - 2):
        high_1 = df["High"].iloc[i]
        low_1 = df["Low"].iloc[i]
        high_3 = df["High"].iloc[i + 2]
        low_3 = df["Low"].iloc[i + 2]

        if high_1 < low_3:
            zone_low, zone_high = float(high_1), float(low_3)
            filled = bool((df["Low"].iloc[i + 3:] <= zone_low).any()) if i + 3 < n else False
            if not only_unfilled or not filled:
                fvgs.append({"type": "BULLISH", "index": i + 1, "zone_low": round(zone_low, 2),
                              "zone_high": round(zone_high, 2), "filled": filled})

        elif low_1 > high_3:
            zone_low, zone_high = float(high_3), float(low_1)
            filled = bool((df["High"].iloc[i + 3:] >= zone_high).any()) if i + 3 < n else False
            if not only_unfilled or not filled:
                fvgs.append({"type": "BEARISH", "index": i + 1, "zone_low": round(zone_low, 2),
                              "zone_high": round(zone_high, 2), "filled": filled})

    return fvgs[-max_gaps:][::-1]


def detect_liquidity_pools(df: pd.DataFrame, left_bars: int = 5, right_bars: int = 5,
                              equal_threshold_pct: float = 0.3, max_pools: int = 5) -> list[dict]:
    """Deteksi Liquidity Pool: zona di sekitar swing high/low (atau
    BEBERAPA swing point yang harganya sangat berdekatan -- "equal
    highs/lows" -- menandakan stop-loss menumpuk tebal di level itu).

    equal_threshold_pct: dua swing point dianggap "equal" kalau
    selisihnya < X% dari harga -- mengelompokkan swing-swing yang
    berdekatan jadi satu pool yang lebih kuat (makin banyak swing
    berkumpul = makin banyak stop-loss diperkirakan menumpuk di sana).

    Returns list of dict (max max_pools, pool TERKUAT/dengan paling
    banyak swing duluan): {'type': 'HIGH'|'LOW' (liquidity di atas/
    bawah harga), 'price_level', 'n_swings', 'swept' (sudah pernah
    disapu harga atau belum), 'distance_pct' (jarak dari harga
    sekarang)}."""
    df_swing = detect_swing_points(df, left_bars, right_bars)
    n = len(df)
    swing_high_idx = [i for i in range(n) if df_swing["swing_high"].iloc[i]]
    swing_low_idx = [i for i in range(n) if df_swing["swing_low"].iloc[i]]

    def _group_into_pools(indices, price_col):
        if not indices:
            return []
        prices = sorted([(idx, float(df[price_col].iloc[idx])) for idx in indices], key=lambda x: x[1])

        groups = [[prices[0]]]
        for idx, price in prices[1:]:
            ref_price = groups[-1][-1][1]
            if abs(price - ref_price) / ref_price * 100 <= equal_threshold_pct:
                groups[-1].append((idx, price))
            else:
                groups.append([(idx, price)])
        return groups

    high_groups = _group_into_pools(swing_high_idx, "High")
    low_groups = _group_into_pools(swing_low_idx, "Low")

    last_close = float(df["Close"].iloc[-1])
    pools = []

    for group in high_groups:
        avg_price = sum(p for _, p in group) / len(group)
        max_idx = max(idx for idx, _ in group)
        swept = bool((df["High"].iloc[max_idx + 1:] > avg_price).any()) if max_idx + 1 < n else False
        pools.append({"type": "HIGH", "price_level": round(avg_price, 2), "n_swings": len(group),
                       "swept": swept, "distance_pct": round((avg_price / last_close - 1) * 100, 2)})

    for group in low_groups:
        avg_price = sum(p for _, p in group) / len(group)
        max_idx = max(idx for idx, _ in group)
        swept = bool((df["Low"].iloc[max_idx + 1:] < avg_price).any()) if max_idx + 1 < n else False
        pools.append({"type": "LOW", "price_level": round(avg_price, 2), "n_swings": len(group),
                       "swept": swept, "distance_pct": round((avg_price / last_close - 1) * 100, 2)})

    # Pool TERKUAT dulu (paling banyak swing berkumpul), lalu yang belum disapu dulu
    pools.sort(key=lambda x: (-x["n_swings"], x["swept"]))
    return pools[:max_pools]
