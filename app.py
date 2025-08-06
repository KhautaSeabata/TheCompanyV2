import json
import threading
import time
import requests
from flask import Flask, render_template
from flask_cors import CORS
import websocket
import os

app = Flask(__name__)
CORS(app)

FIREBASE_BASE_URL = "https://company-bdb78-default-rtdb.firebaseio.com/ticks"
MAX_TICKS = 900

# Store live ticks for each symbol
TICKS = {
    "R_25": [],
    "R_75": []
}
WS_STATUS = {
    "R_25": False,
    "R_75": False
}

def store_to_firebase(symbol):
    """Push the latest tick list to Firebase for the given symbol."""
    url = f"{FIREBASE_BASE_URL}/{symbol}.json"
    try:
        requests.put(url, json=TICKS[symbol])
    except Exception as e:
        print(f"Error storing {symbol} to Firebase:", e)

def on_message(symbol):
    def inner(ws, message):
        data = json.loads(message)
        if "tick" in data:
            tick = {
                "epoch": data["tick"]["epoch"],
                "quote": data["tick"]["quote"],
                "symbol": data["tick"]["symbol"]
            }
            TICKS[symbol].append(tick)
            if len(TICKS[symbol]) > MAX_TICKS:
                TICKS[symbol].pop(0)
            store_to_firebase(symbol)
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
            print(f"WebSocket error for {symbol}: {e}")
        WS_STATUS[symbol] = False
        time.sleep(5)

@app.route("/")
def index():
    return render_template("index.html", status_25=WS_STATUS["R_25"], status_75=WS_STATUS["R_75"])

if __name__ == "__main__":
    threading.Thread(target=run_ws, args=("R_25",), daemon=True).start()
    threading.Thread(target=run_ws, args=("R_75",), daemon=True).start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
