import json
import threading
import time
import requests
from flask import Flask, render_template
from flask_cors import CORS
import websocket
import os
from datetime import datetime

app = Flask(__name__)
CORS(app)

FIREBASE_BASE_URL = "https://company-bdb78-default-rtdb.firebaseio.com"
MAX_TICKS = 900
MAX_CANDLES = 950

TICKS = {
    "R_25": [],
    "R_75": []
}
CANDLES = {
    "R_25": [],
    "R_75": []
}
WS_STATUS = {
    "R_25": False,
    "R_75": False
}


def floor_minute(epoch):
    return epoch - (epoch % 60)


def store_to_firebase(path, data):
    try:
        requests.put(f"{FIREBASE_BASE_URL}/{path}.json", json=data)
    except Exception as e:
        print(f"[Firebase Error] {path}: {e}")


def update_candles(symbol, tick):
    epoch_minute = floor_minute(tick["epoch"])

    if not CANDLES[symbol] or CANDLES[symbol][-1]["epoch"] != epoch_minute:
        # Start a new candle
        candle = {
            "epoch": epoch_minute,
            "open": tick["quote"],
            "high": tick["quote"],
            "low": tick["quote"],
            "close": tick["quote"]
        }
        CANDLES[symbol].append(candle)
        if len(CANDLES[symbol]) > MAX_CANDLES:
            CANDLES[symbol].pop(0)
    else:
        # Update current candle
        candle = CANDLES[symbol][-1]
        candle["high"] = max(candle["high"], tick["quote"])
        candle["low"] = min(candle["low"], tick["quote"])
        candle["close"] = tick["quote"]

    store_to_firebase(f"candles/{symbol}", CANDLES[symbol])


def on_message(symbol):
    def inner(ws, message):
        data = json.loads(message)
        if "tick" in data:
            tick = {
                "epoch": data["tick"]["epoch"],
                "quote": data["tick"]["quote"],
                "symbol": data["tick"]["symbol"]
            }

            # Store ticks
            TICKS[symbol].append(tick)
            if len(TICKS[symbol]) > MAX_TICKS:
                TICKS[symbol].pop(0)
            store_to_firebase(f"ticks/{symbol}", TICKS[symbol])

            # Update 1-minute candle
            update_candles(symbol, tick)

    return inner


def on_open(symbol):
    def inner(ws):
        WS_STATUS[symbol] = True
        ws.send(json.dumps({
            "ticks": symbol,
            "subscribe": 1
        }))
    return inner


def on_close(symbol):
    def inner(ws, close_status_code, close_msg):
        WS_STATUS[symbol] = False
    return inner


def run_ws(symbol):
    while True:
        try:
            ws = websocket.WebSocketApp(
                "wss://ws.derivws.com/websockets/v3?app_id=1089",
                on_message=on_message(symbol),
                on_open=on_open(symbol),
                on_close=on_close(symbol)
            )
            ws.run_forever(ping_interval=30, ping_timeout=10)
        except Exception as e:
            print(f"[WebSocket Error] {symbol}: {e}")
        WS_STATUS[symbol] = False
        time.sleep(5)


@app.route("/")
def index():
    return render_template("index.html",
                           status_25=WS_STATUS["R_25"],
                           status_75=WS_STATUS["R_75"])


if __name__ == "__main__":
    threading.Thread(target=run_ws, args=("R_25",), daemon=True).start()
    threading.Thread(target=run_ws, args=("R_75",), daemon=True).start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
