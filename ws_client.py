"""
WebSocket client untuk melihat data real-time IHSG/order book dari relay
/ws/ihsg (yang meneruskan feed ShadowStream lewat Redis pub/sub -- lihat
_ihsg_stream_pump di web/app.py). Client ini MENAMPILKAN saja, tidak
menghasilkan data.

Jalankan:
    pip install websockets python-dotenv
    # lokal:
    WS_HOST=localhost WS_PORT=8000 python ws_client.py
    # via ngrok (wss://):
    WS_HOST=<subdomain>.ngrok-free.app WS_SECURE=true python ws_client.py
"""

import asyncio
import json
import os
from datetime import datetime
from dotenv import load_dotenv
import websockets

load_dotenv()

WS_HOST = os.getenv("WS_HOST", "localhost")
WS_PORT = os.getenv("WS_PORT", "8000")
WS_SECURE = os.getenv("WS_SECURE", "false").lower() == "true"


def print_ticker(ticker_data):
    ticker = ticker_data.get("ticker", "?")
    price = ticker_data.get("price", 0)
    change = ticker_data.get("change", 0)
    pct = ticker_data.get("change_percent", 0)
    ts = ticker_data.get("timestamp", 0)

    waktu = datetime.fromtimestamp(ts).strftime("%H:%M:%S") if ts else "??:??:??"
    arrow = "+" if change >= 0 else "-"

    bid_5 = ticker_data.get("bid_5", [])
    offer_5 = ticker_data.get("offer_5", [])

    bid_str = f"{bid_5[0]['price']:,.0f}/{bid_5[0]['volume']:,.0f}" if bid_5 else "0/0"
    offer_str = f"{offer_5[0]['price']:,.0f}/{offer_5[0]['volume']:,.0f}" if offer_5 else "0/0"

    print(f"{waktu} {ticker:<6} {price:>10,.2f} {arrow}{abs(change):>8,.2f} ({pct:>+6.2f}%) "
          f"B:{bid_str} A:{offer_str}")


def print_order_book(ticker_data):
    bid_5 = ticker_data.get("bid_5", [])
    offer_5 = ticker_data.get("offer_5", [])

    if not bid_5 and not offer_5:
        return

    print(f"\n  {'BID':>20}  |  {'OFFER':<20}")
    print(f"  {'Price':>10} {'Vol':>10} {'Freq':>6}  |  {'Freq':<6} {'Vol':<10} {'Price':<10}")
    print(f"  {'-'*20}  |  {'-'*20}")

    for i in range(max(len(bid_5), len(offer_5))):
        bid_part = ""
        if i < len(bid_5):
            b = bid_5[i]
            bid_part = f"{b['price']:>10,.0f} {b['volume']:>10,.0f} {b['freq']:>6,.0f}"

        offer_part = ""
        if i < len(offer_5):
            o = offer_5[i]
            offer_part = f"{o['freq']:<6,.0f} {o['volume']:<10,.0f} {o['price']:<10,.0f}"

        print(f"  {bid_part}  |  {offer_part}")


async def listen():
    protocol = "wss" if WS_SECURE else "ws"
    uri = f"{protocol}://{WS_HOST}:{WS_PORT}/ws/ihsg"
    async with websockets.connect(uri) as ws:
        print(f"Connected ke {uri}\n")

        while True:
            msg = await ws.recv()
            data = json.loads(msg)

            if data.get("type") == "snapshot":
                print("=" * 70)
                print(f"SNAPSHOT {datetime.now().strftime('%H:%M:%S')}")
                print("=" * 70)
                for ticker, ticker_data in data.get("data", {}).items():
                    print_ticker(ticker_data)
                    print_order_book(ticker_data)
                print()

            elif "ticker" in data:
                print_ticker(data)
                if data.get("bid_5") or data.get("offer_5"):
                    print_order_book(data)


if __name__ == "__main__":
    asyncio.run(listen())
