import asyncio
import json
import aiohttp
import time
from datetime import datetime
from firebase_admin import credentials, db, initialize_app

# Initialize Firebase
cred = credentials.Certificate("serviceAccountKey.json")
initialize_app(cred, {
    'databaseURL': "https://vix75-f6684-default-rtdb.firebaseio.com/"
})

# Deriv Symbols to Subscribe
SYMBOLS = {
    "R_10": "Volatility 10 Index",
    "R_25": "Volatility 25 Index",
    "R_75": "Volatility 75 Index",
    "R_100": "Volatility 100 Index",
    "1HZ10V": "Volatility 10 (1s)",
    "1HZ75V": "Volatility 75 (1s)",
    "1HZ100V": "Volatility 100 (1s)",
    "1HZ150V": "Volatility 150 (1s)"
}

# Firebase Paths
def tick_path(symbol): return f"/ticks/{symbol}"
def candle_path(symbol, tf): return f"/{tf}min{symbol}"

# Utility: Create OHLC
def create_candle(data):
    quotes = [tick['quote'] for tick in data]
    return {
        "epoch": data[0]['epoch'] - data[0]['epoch'] % 60,
        "open": quotes[0],
        "high": max(quotes),
        "low": min(quotes),
        "close": quotes[-1],
    }

# Store tick in Firebase and prune
async def store_tick(symbol, tick):
    path = tick_path(symbol)
    ref = db.reference(path)
    ref.push(tick)
    all_ticks = ref.get()
    if all_ticks and len(all_ticks) > 900:
        keys = sorted(all_ticks.keys(), key=lambda k: all_ticks[k]['epoch'])[:-900]
        for k in keys:
            ref.child(k).delete()

# Generate and store OHLC
def generate_ohlc(symbol, tf):
    path = tick_path(symbol)
    ticks = db.reference(path).get()
    if not ticks:
        return

    # Group ticks by tf-minute
    ohlc_data = {}
    for tick in ticks.values():
        group = int(tick['epoch'] / (60 * tf))
        ohlc_data.setdefault(group, []).append(tick)

    for group, group_ticks in ohlc_data.items():
        if len(group_ticks) < 2:
            continue
        candle = create_candle(sorted(group_ticks, key=lambda x: x['epoch']))
        db.reference(candle_path(symbol, tf)).child(str(candle['epoch'])).set(candle)

# Main WebSocket Handler
async def handle_symbol(session, symbol):
    url = "wss://ws.binaryws.com/websockets/v3?app_id=1089"
    async with session.ws_connect(url) as ws:
        await ws.send_json({
            "ticks": symbol,
            "subscribe": 1
        })

        async for msg in ws:
            data = json.loads(msg.data)
            if "tick" in data:
                tick = {
                    "epoch": data["tick"]["epoch"],
                    "quote": data["tick"]["quote"],
                    "symbol": symbol
                }
                await store_tick(symbol, tick)
                generate_ohlc(symbol, 1)
                generate_ohlc(symbol, 5)

# Runner
async def run():
    async with aiohttp.ClientSession() as session:
        tasks = [handle_symbol(session, sym) for sym in SYMBOLS]
        await asyncio.gather(*tasks)

# Entry Point
if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("Stopped.")
