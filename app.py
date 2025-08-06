import json
import threading
import time
import requests
from flask import Flask, render_template
from flask_cors import CORS
import websocket

app = Flask(__name__)
CORS(app)

# Firebase Realtime Database URL
FIREBASE_URL = "https://company-bdb78-default-rtdb.firebaseio.com/ticks.json"
MAX_TICKS = 900
TICKS = []
ws_status = {"connected": False}


def on_message(ws, message):
    data = json.loads(message)
    if "tick" in data:
        tick = {
            "epoch": data["tick"]["epoch"],
            "quote": data["tick"]["quote"],
            "symbol": data["tick"]["symbol"]
        }
        TICKS.append(tick)
        if len(TICKS) > MAX_TICKS:
            TICKS.pop(0)
        requests.put(FIREBASE_URL, json=TICKS)


def on_open(ws):
    ws_status["connected"] = True
    ws.send(json.dumps({
        "ticks": "R_75",
        "subscribe": 1
    }))


def on_close(ws, close_status_code, close_msg):
    ws_status["connected"] = False


def run_websocket():
    while True:
        try:
            ws = websocket.WebSocketApp(
                "wss://ws.derivws.com/websockets/v3?app_id=1089",
                on_message=on_message,
                on_open=on_open,
                on_close=on_close
            )
            ws.run_forever()
        except Exception as e:
            print("WebSocket error:", e)
            ws_status["connected"] = False
            time.sleep(5)


@app.route("/")
def index():
    return render_template("index.html", status=ws_status["connected"])


if __name__ == "__main__":
    threading.Thread(target=run_websocket, daemon=True).start()
    app.run(host="0.0.0.0", port=5000)
