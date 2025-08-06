import json
import threading
import time
import requests
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import websocket
import os

app = Flask(__name__)
CORS(app)

FIREBASE_BASE_URL = "https://company-bdb78-default-rtdb.firebaseio.com"
MAX_CANDLES = 950

# Store candles by symbol and granularity (interval)
CANDLES = {}
WS_STATUS = {}

# Deriv API parameters for granularity in seconds
VALID_GRANULARITIES = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "1d": 86400,
    "1w": 604800
}

def store_to_firebase(path, data):
    try:
        requests.put(f"{FIREBASE_BASE_URL}/{path}.json", json=data)
    except Exception as e:
        print(f"[Firebase Error] {path}: {e}")

def make_ws_on_message(symbol, granularity):
    def on_message(ws, message):
        data = json.loads(message)
        if "candles" in data:
            key = f"{symbol}_{granularity}"
            candles = data["candles"]

            # We keep only MAX_CANDLES
            if len(candles) > MAX_CANDLES:
                candles = candles[-MAX_CANDLES:]

            CANDLES[key] = candles
            store_to_firebase(f"candles/{symbol}/{granularity}", candles)
    return on_message

def make_ws_on_open(symbol, granularity):
    def on_open(ws):
        WS_STATUS[f"{symbol}_{granularity}"] = True
        subscribe_msg = {
            "ticks_history": symbol,
            "style": "candles",
            "granularity": VALID_GRANULARITIES[granularity],
            "subscribe": 1,
            "end": "latest"
        }
        ws.send(json.dumps(subscribe_msg))
    return on_open

def make_ws_on_close(symbol, granularity):
    def on_close(ws, close_status_code, close_msg):
        WS_STATUS[f"{symbol}_{granularity}"] = False
    return on_close

def run_ws(symbol, granularity):
    while True:
        try:
            ws = websocket.WebSocketApp(
                "wss://ws.derivws.com/websockets/v3?app_id=1089",
                on_message=make_ws_on_message(symbol, granularity),
                on_open=make_ws_on_open(symbol, granularity),
                on_close=make_ws_on_close(symbol, granularity),
            )
            ws.run_forever(ping_interval=30, ping_timeout=10)
        except Exception as e:
            print(f"[WebSocket Error] {symbol} {granularity}: {e}")
        WS_STATUS[f"{symbol}_{granularity}"] = False
        time.sleep(5)

@app.route("/")
def index():
    # Show default chart with Volatility 75, 1m
    return render_template("index.html")

@app.route("/api/candles")
def api_candles():
    symbol = request.args.get("symbol", "R_75")
    granularity = request.args.get("interval", "1m")
    if granularity not in VALID_GRANULARITIES:
        return jsonify({"error": "Invalid interval"}), 400

    key = f"{symbol}_{granularity}"
    data = CANDLES.get(key, [])
    return jsonify(data)

@app.route("/api/status")
def api_status():
    # Return websocket status for all running streams
    return jsonify(WS_STATUS)

if __name__ == "__main__":
    # Start WebSocket threads for each symbol and interval you want
    symbols = ["R_25", "R_75"]
    intervals = ["1m", "5m", "15m", "1d", "1w"]

    for symbol in symbols:
        for interval in intervals:
            threading.Thread(target=run_ws, args=(symbol, interval), daemon=True).start()

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
