from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import requests
import time
import json

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
            "30m": 1800,
            "1h": 3600,
            "4h": 14400,
            "1d": 86400,
            "1w": 604800
        }
        
        granularity = granularity_map.get(interval, 60)
        print(f"Using granularity: {granularity}")
        
        # Get more data points for better chart display  
        count = 100  # Increased for better chart visualization
        
        # Try the WebSocket API over HTTP first (this is the correct approach for Deriv)
        ws_api_url = "https://ws.derivws.com/websockets/v3"
        
        # Create proper payload for Deriv API
        ws_payload = {
            "ticks_history": symbol,
            "end": "latest",
            "count": count,
            "granularity": granularity,
            "style": "candles",
            "req_id": 1
        }
        
        print(f"WebSocket API payload: {ws_payload}")
        
        # First try: WebSocket API endpoint
        try:
            headers = {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'Origin': 'https://app.deriv.com'
            }
            
            # Use the binary.com API endpoint which is more reliable
            binary_api_url = "https://api.binaryws.com/websockets/v3"
            
            response = requests.post(binary_api_url, json=ws_payload, headers=headers, timeout=15)
            print(f"Binary API response status: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                print(f"Binary API Response keys: {list(data.keys()) if isinstance(data, dict) else 'Not a dict'}")
                
                if isinstance(data, dict) and not data.get('error'):
                    candles_data = data.get('candles') or data.get('history', {}).get('candles', [])
                    
                    if candles_data:
                        candles = []
                        for candle in candles_data:
                            # Handle both list format [epoch, open, high, low, close] and dict format
                            if isinstance(candle, list) and len(candle) >= 5:
                                candles.append({
                                    "epoch": int(candle[0]),
                                    "open": float(candle[1]),
                                    "high": float(candle[2]),
                                    "low": float(candle[3]),
                                    "close": float(candle[4])
                                })
                            elif isinstance(candle, dict):
                                candles.append({
                                    "epoch": int(candle.get("epoch", 0)),
                                    "open": float(candle.get("open", 0)),
                                    "high": float(candle.get("high", 0)),
                                    "low": float(candle.get("low", 0)),
                                    "close": float(candle.get("close", 0))
                                })
                        
                        if candles:
                            print(f"Successfully got {len(candles)} real candles from Binary API")
                            return jsonify(candles)
                
                # If no candles but we have tick data, convert it
                if 'history' in data and 'prices' in data['history']:
                    print("Converting tick data to candles...")
                    prices = data['history']['prices']
                    times = data['history']['times']
                    
                    if len(prices) > 0 and len(times) > 0:
                        candles = []
                        for i, (timestamp, price) in enumerate(zip(times, prices)):
                            price = float(price)
                            candles.append({
                                "epoch": int(timestamp),
                                "open": price,
                                "high": price,
                                "low": price,
                                "close": price
                            })
                        
                        print(f"Converted {len(candles)} ticks to candles")
                        return jsonify(candles)
        
        except Exception as e:
            print(f"Binary API failed: {str(e)}")
        
        # Second try: Alternative API approach with different payload structure
        try:
            print("Trying alternative API structure...")
            alt_payload = {
                "ticks_history": symbol,
                "adjust_start_time": 1,
                "count": count,
                "granularity": granularity,
                "end": "latest",
                "style": "candles"
            }
            
            # Try with query parameters instead
            params_url = f"https://api.binaryws.com/websockets/v3?app_id=1089&l=en&brand=deriv"
            
            alt_response = requests.post(params_url, json=alt_payload, headers=headers, timeout=15)
            print(f"Alternative API response status: {alt_response.status_code}")
            
            if alt_response.status_code == 200:
                alt_data = alt_response.json()
                print(f"Alternative API keys: {list(alt_data.keys()) if isinstance(alt_data, dict) else 'Not a dict'}")
                
                # Process the alternative response
                if isinstance(alt_data, dict):
                    candles_data = alt_data.get('candles') or alt_data.get('history', {}).get('candles', [])
                    
                    if candles_data:
                        candles = []
                        for candle in candles_data:
                            if isinstance(candle, list) and len(candle) >= 5:
                                candles.append({
                                    "epoch": int(candle[0]),
                                    "open": float(candle[1]),
                                    "high": float(candle[2]),
                                    "low": float(candle[3]),
                                    "close": float(candle[4])
                                })
                            elif isinstance(candle, dict):
                                candles.append({
                                    "epoch": int(candle.get("epoch", 0)),
                                    "open": float(candle.get("open", 0)),
                                    "high": float(candle.get("high", 0)),
                                    "low": float(candle.get("low", 0)),
                                    "close": float(candle.get("close", 0))
                                })
                        
                        if candles:
                            print(f"Got {len(candles)} candles from alternative API")
                            return jsonify(candles)
        
        except Exception as e:
            print(f"Alternative API failed: {str(e)}")
        
        # Third try: Get current tick data to show something real
        try:
            print("Trying to get current tick data...")
            tick_payload = {
                "ticks": symbol,
                "subscribe": 0
            }
            
            tick_response = requests.post("https://api.binaryws.com/websockets/v3", 
                                        json=tick_payload, headers=headers, timeout=10)
            
            if tick_response.status_code == 200:
                tick_data = tick_response.json()
                if 'tick' in tick_data and 'quote' in tick_data['tick']:
                    current_price = float(tick_data['tick']['quote'])
                    current_time = int(time.time())
                    
                    # Create a single candle with current data
                    print(f"Got current price: {current_price}")
                    return jsonify([{
                        "epoch": current_time,
                        "open": current_price,
                        "high": current_price,
                        "low": current_price,
                        "close": current_price
                    }])
        
        except Exception as e:
            print(f"Tick API failed: {str(e)}")
        
        # If all real APIs fail, return an error instead of fake data
        print("All API attempts failed - no real data available")
        return jsonify({
            "error": "Unable to fetch real market data. Please check your internet connection and try again.",
            "symbol": symbol,
            "interval": interval
        }), 503
        
    except Exception as e:
        print(f"Unexpected error in get_candles: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "error": f"Server error: {str(e)}",
            "symbol": request.args.get("symbol", "R_75"),
            "interval": request.args.get("interval", "1m")
        }), 500

@app.route("/api/current_price")
def get_current_price():
    """Get current price for a symbol"""
    try:
        symbol = request.args.get("symbol", "R_75")
        
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Origin': 'https://app.deriv.com'
        }
        
        # Get current tick
        payload = {
            "ticks": symbol,
            "subscribe": 0
        }
        
        response = requests.post("https://api.binaryws.com/websockets/v3", 
                               json=payload, headers=headers, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            if 'tick' in data and 'quote' in data['tick']:
                return jsonify({
                    "symbol": symbol,
                    "price": float(data['tick']['quote']),
                    "timestamp": int(time.time())
                })
        
        return jsonify({"error": "Unable to fetch current price"}), 503
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/data")
def get_data():
    """Legacy endpoint for backward compatibility"""
    symbol = request.args.get("symbol", "R_75")
    dtype = request.args.get("type", "ticks")
    
    # Redirect to the new candles endpoint
    if dtype in ["1m", "5m", "15m"]:
        interval = dtype
    else:
        interval = "1m"
    
    # Make internal request to candles endpoint
    try:
        candles_response = get_candles()
        if hasattr(candles_response, 'get_json'):
            candles = candles_response.get_json()
            if isinstance(candles, list):
                # Convert to legacy format
                legacy_data = []
                for candle in candles:
                    legacy_data.append({
                        "epoch": candle["epoch"],
                        "price": candle["close"]
                    })
                return jsonify(legacy_data)
        
        return jsonify([])
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
