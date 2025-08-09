from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import requests
import time

app = Flask(__name__)
CORS(app)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/candles")
def get_candles():
    symbol = request.args.get("symbol", "R_75")
    interval = request.args.get("interval", "1m")
    
    # Define granularity based on interval
    granularity_map = {
        "1m": 60,
        "5m": 300,
        "15m": 900,
        "1d": 86400,
        "1w": 604800
    }
    
    granularity = granularity_map.get(interval, 60)
    
    # Get more data points for better chart display
    end_time = int(time.time())
    start_time = end_time - (granularity * 100)  # Get last 100 candles
    
    payload = {
        "ticks_history": symbol,
        "start": start_time,
        "end": end_time,
        "style": "candles",
        "granularity": granularity,
        "count": 100
    }
    
    try:
        print(f"Fetching candles for {symbol} with interval {interval} (granularity: {granularity})")
        res = requests.get("https://api.deriv.com/api/explorer/ticks_history", params=payload)
        res.raise_for_status()
        data = res.json()
        
        print(f"API Response keys: {data.keys()}")
        
        if "candles" in data and data["candles"]:
            candles = []
            for candle in data["candles"]:
                candles.append({
                    "epoch": candle["epoch"],
                    "open": float(candle["open"]),
                    "high": float(candle["high"]),
                    "low": float(candle["low"]),
                    "close": float(candle["close"])
                })
            
            print(f"Returning {len(candles)} candles")
            return jsonify(candles)
        
        # If no candles, try to get ticks and convert to simple line data
        elif "history" in data and "prices" in data["history"]:
            prices = data["history"]["prices"]
            times = data["history"]["times"]
            
            # Convert ticks to simple candle format (OHLC will be same as close price)
            candles = []
            for t, p in zip(times, prices):
                price = float(p)
                candles.append({
                    "epoch": t,
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price
                })
            
            print(f"Converted {len(candles)} ticks to candle format")
            return jsonify(candles)
        
        print("No data found in API response")
        return jsonify([])
        
    except Exception as e:
        print(f"Error fetching data: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/data")
def get_data():
    # Keep the old endpoint for backward compatibility
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
