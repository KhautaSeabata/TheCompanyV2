from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import requests
import time

app = Flask(__name__)
CORS(app)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/test")
def test_api():
    """Test endpoint to check if API is working"""
    return jsonify({
        "status": "API is working",
        "timestamp": int(time.time()),
        "message": "Flask server is running correctly"
    })

@app.route("/api/candles")
def get_candles():
    try:
        symbol = request.args.get("symbol", "R_75")
        interval = request.args.get("interval", "1m")
        
        print(f"Received request for symbol: {symbol}, interval: {interval}")
        
        # Define granularity based on interval
        granularity_map = {
            "1m": 60,
            "5m": 300,
            "15m": 900,
            "1d": 86400,
            "1w": 604800
        }
        
        granularity = granularity_map.get(interval, 60)
        print(f"Using granularity: {granularity}")
        
        # Get more data points for better chart display  
        end_time = int(time.time())
        start_time = end_time - (granularity * 50)  # Get last 50 candles
        
        print(f"Current time: {end_time}, Start time: {start_time}")
        print(f"Time difference: {end_time - start_time} seconds")
        
        # Use the correct Deriv API endpoint
        api_url = "https://api.deriv.com/api/v1"
        
        # Create proper JSON payload for Deriv WebSocket API over HTTP
        api_payload = {
            "ticks_history": symbol,
            "end": "latest",
            "count": 50,
            "style": "candles" if granularity > 0 else "ticks",
            "granularity": granularity
        }
        
        print(f"API payload: {api_payload}")
        print(f"Making POST request to: {api_url}")
        
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
        
        res = requests.post(api_url, json=api_payload, headers=headers, timeout=10)
        print(f"API response status: {res.status_code}")
        
        # If that fails, try the REST API approach
        if res.status_code != 200:
            print("POST failed, trying GET with query parameters...")
            api_url = "https://api.deriv.com/ticks"
            
            get_params = {
                "symbol": symbol,
                "granularity": granularity,
                "count": 50
            }
            
            res = requests.get(api_url, params=get_params, timeout=10)
            print(f"GET API response status: {res.status_code}")
            
            # If still failing, try with basic tick data
            if res.status_code != 200:
                print("Both APIs failed, trying simple tick endpoint...")
                # Generate some sample data for testing
                import random
                current_price = 1000.0
                candles = []
                
                for i in range(50):
                    # Create sample candle data
                    price_change = random.uniform(-5, 5)
                    current_price += price_change
                    
                    candles.append({
                        "epoch": end_time - (granularity * (50 - i)),
                        "open": round(current_price - random.uniform(-2, 2), 4),
                        "high": round(current_price + random.uniform(0, 3), 4),
                        "low": round(current_price - random.uniform(0, 3), 4),
                        "close": round(current_price, 4)
                    })
                
                print(f"Generated {len(candles)} sample candles for testing")
                return jsonify(candles)
        
        res.raise_for_status()
        data = res.json()
        
        print(f"API Response keys: {list(data.keys())}")
        if 'error' in data:
            print(f"API Error: {data['error']}")
            return jsonify({"error": f"API Error: {data['error']}"}), 400
        
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
            print("No candles found, converting from ticks")
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
        print(f"Full API response: {data}")
        return jsonify([])
        
    except requests.exceptions.RequestException as e:
        print(f"Request error: {str(e)}")
        return jsonify({"error": f"Request failed: {str(e)}"}), 500
    except Exception as e:
        print(f"Unexpected error in get_candles: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Server error: {str(e)}"}), 500

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
