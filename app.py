from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import requests
import time

app = Flask(__name__)
CORS(app)

# Deriv API endpoint for candles
DERIV_API_URL = "https://api.deriv.com/api/explorer/api/v1"

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/candles")
def get_candles():
    symbol = request.args.get("symbol", "R_75")
    interval = request.args.get("interval", "1m")

    # Map UI intervals to Deriv API durations
    interval_map = {
        "1m": 60,
        "5m": 300,
        "15m": 900,
        "1d": 86400,
        "1w": 604800
    }

    if interval not in interval_map:
        return jsonify({"error": "Invalid interval"}), 400

    end_time = int(time.time())
    start_time = end_time - (100 * interval_map[interval])  # last 100 candles

    payload = {
        "ticks_history": symbol,
        "start": start_time,
        "end": end_time,
        "style": "candles",
        "granularity": interval_map[interval],
        "adjust_start_time": 1,
        "count": 100
    }

    try:
        res = requests.get("https://api.deriv.com/api/explorer/ticks_history", params=payload)
        res.raise_for_status()
        data = res.json()

        if "candles" not in data:
            return jsonify([])

        candles = [
            {
                "epoch": c["epoch"],
                "open": c["open"],
                "high": c["high"],
                "low": c["low"],
                "close": c["close"]
            }
            for c in data["candles"]
        ]

        return jsonify(candles)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
