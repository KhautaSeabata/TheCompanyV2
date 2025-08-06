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
CANDLES = {}
WS_STATUS = {}

VALID_GRANULARITIES = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
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
        try:
            data = json.loads(message)
            print(f"[WebSocket] Received data for {symbol}_{granularity}: {data}")
            
            if "candles" in data:
                key = f"{symbol}_{granularity}"
                candles = data["candles"]
                
                # Always limit to MAX_CANDLES (950)
                if len(candles) > MAX_CANDLES:
                    candles = candles[-MAX_CANDLES:]
                
                CANDLES[key] = candles
                store_to_firebase(f"candles/{symbol}/{granularity}", candles)
                print(f"[WebSocket] Stored {len(candles)} candles for {key} (max: {MAX_CANDLES})")
            elif "error" in data:
                print(f"[WebSocket Error] {symbol}_{granularity}: {data['error']}")
        except Exception as e:
            print(f"[WebSocket Message Error] {symbol}_{granularity}: {e}")
    return on_message

def make_ws_on_open(symbol, granularity):
    def on_open(ws):
        print(f"[WebSocket] Connected for {symbol}_{granularity}")
        WS_STATUS[f"{symbol}_{granularity}"] = True
        subscribe_msg = {
            "ticks_history": symbol,
            "style": "candles",
            "granularity": VALID_GRANULARITIES[granularity],
            "subscribe": 1,
            "end": "latest"
        }
        print(f"[WebSocket] Sending subscribe message: {subscribe_msg}")
        ws.send(json.dumps(subscribe_msg))
    return on_open

def make_ws_on_close(symbol, granularity):
    def on_close(ws, close_status_code, close_msg):
        print(f"[WebSocket] Closed for {symbol}_{granularity}: {close_status_code} - {close_msg}")
        WS_STATUS[f"{symbol}_{granularity}"] = False
    return on_close

def make_ws_on_error(symbol, granularity):
    def on_error(ws, error):
        print(f"[WebSocket Error] {symbol}_{granularity}: {error}")
    return on_error

def run_ws(symbol, granularity):
    while True:
        try:
            print(f"[WebSocket] Starting connection for {symbol}_{granularity}")
            ws = websocket.WebSocketApp(
                "wss://ws.derivws.com/websockets/v3?app_id=1089",
                on_message=make_ws_on_message(symbol, granularity),
                on_open=make_ws_on_open(symbol, granularity),
                on_close=make_ws_on_close(symbol, granularity),
                on_error=make_ws_on_error(symbol, granularity),
            )
            ws.run_forever(ping_interval=30, ping_timeout=10)
        except Exception as e:
            print(f"[WebSocket Connection Error] {symbol} {granularity}: {e}")
        
        WS_STATUS[f"{symbol}_{granularity}"] = False
        print(f"[WebSocket] Reconnecting in 5 seconds for {symbol}_{granularity}")
        time.sleep(5)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/candles")
def api_candles():
    symbol = request.args.get("symbol", "R_75")
    granularity = request.args.get("interval", "1m")
    
    if granularity not in VALID_GRANULARITIES:
        return jsonify({"error": "Invalid interval"}), 400
    
    key = f"{symbol}_{granularity}"
    data = CANDLES.get(key, [])
    
    # Ensure we never return more than MAX_CANDLES
    if len(data) > MAX_CANDLES:
        data = data[-MAX_CANDLES:]
        # Update the stored data to keep it trimmed
        CANDLES[key] = data
    
    print(f"[API] Returning {len(data)} candles for {key} (max: {MAX_CANDLES})")
    return jsonify(data)

@app.route("/api/status")
def api_status():
    return jsonify(WS_STATUS)

if __name__ == "__main__":
    # Start WebSocket connections
    symbols = ["R_25", "R_75"]
    intervals = ["1m", "5m", "15m", "1d", "1w"]
    
    print("[App] Starting WebSocket connections...")
    for symbol in symbols:
        for interval in intervals:
            print(f"[App] Starting thread for {symbol}_{interval}")
            threading.Thread(target=run_ws, args=(symbol, interval), daemon=True).start()
    
    # Give WebSockets some time to connect
    time.sleep(2)
    
    port = int(os.environ.get("PORT", 5000))
    print(f"[App] Starting Flask server on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
