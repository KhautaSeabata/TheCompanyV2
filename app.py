from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import requests
import time

app = Flask(__name__)
CORS(app)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/data")
def get_data():
    symbol = request.args.get("symbol", "R_75")
    dtype = request.args.get("type", "ticks")

    # Define granularity
    if dtype == "ticks":
        granularity = 0
    elif dtype == "1m":
        granularity = 60
    elif dtype == "5m":
        granularity = 300
    else:
        return jsonify([])

    end_time = int(time.time())
    start_time = end_time - (60 * 100)  # last ~100 minutes or ticks

    payload = {
        "ticks_history": symbol,
        "start": start_time,
        "end": end_time,
        "style": "ticks" if granularity == 0 else "candles",
        "granularity": granularity,
        "count": 100
    }

    try:
        res = requests.get("https://api.deriv.com/api/explorer/ticks_history", params=payload)
        res.raise_for_status()
        data = res.json()

        if granularity == 0:  # ticks
            if "history" in data and "prices" in data["history"]:
                prices = data["history"]["prices"]
                times = data["history"]["times"]
                return jsonify([{"epoch": t, "price": p} for t, p in zip(times, prices)])
        else:  # candles
            if "candles" in data:
                return jsonify([{"epoch": c["epoch"], "price": c["close"]} for c in data["candles"]])

        return jsonify([])

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
