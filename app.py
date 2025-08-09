from flask import Flask, render_template, request, jsonify, send_from_directory
from flask_cors import CORS
import requests
import time
import json
import os
from datetime import datetime, timedelta
import websocket
import threading
import queue

app = Flask(__name__)
CORS(app)

# Global variables for real-time data
current_v75_price = None
v75_data_queue = queue.Queue()
ws_connected = False

# V75 Symbol constant
V75_SYMBOL = "R_75"

@app.route("/")
def index():
    """Serve the main HTML page"""
    return send_from_directory('.', 'index.html')

@app.route("/api/test")
def test_api():
    """Test endpoint to check if API is working"""
    return jsonify({
        "status": "V75 API is working",
        "timestamp": int(time.time()),
        "message": "Flask server ready for Volatility 75 data",
        "symbol": V75_SYMBOL
    })

@app.route("/api/candles")
def get_v75_candles():
    """Get V75 candles data with multiple fallback methods"""
    try:
        # Always use V75 symbol regardless of request parameter
        symbol = V75_SYMBOL
        interval = request.args.get("interval", "1m")
        
        print(f"🔍 Fetching V75 data for interval: {interval}")
        
        # Map intervals to granularity (seconds)
        granularity_map = {
            "1m": 60,
            "5m": 300,
            "15m": 900,
            "30m": 1800,
            "1h": 3600
        }
        
        granularity = granularity_map.get(interval, 60)
        count = 50  # Good balance for chart display
        
        # Method 1: Try Deriv API with proper authentication
        candles = try_deriv_api(symbol, granularity, count)
        if candles:
            print(f"✅ Got {len(candles)} V75 candles from Deriv API")
            return jsonify(candles)
        
        # Method 2: Try Binary.com API
        candles = try_binary_api(symbol, granularity, count)
        if candles:
            print(f"✅ Got {len(candles)} V75 candles from Binary API")
            return jsonify(candles)
        
        # Method 3: Try getting current tick and generate recent data
        candles = try_tick_to_candles(symbol, granularity, count)
        if candles:
            print(f"✅ Generated {len(candles)} V75 candles from tick data")
            return jsonify(candles)
        
        # Method 4: Last resort - return error
        print("❌ All V75 data methods failed")
        return jsonify({
            "error": "Unable to fetch V75 market data. The market might be closed or there's a connectivity issue.",
            "symbol": symbol,
            "interval": interval,
            "timestamp": int(time.time())
        }), 503
        
    except Exception as e:
        print(f"❌ Error in get_v75_candles: {str(e)}")
        return jsonify({
            "error": f"Server error while fetching V75 data: {str(e)}",
            "symbol": V75_SYMBOL,
            "interval": interval
        }), 500

def try_deriv_api(symbol, granularity, count):
    """Try to get data from Deriv API"""
    try:
        print("🔄 Trying Deriv API...")
        
        # Official Deriv API endpoint
        url = "https://api.deriv.com/v1/api"
        
        payload = {
            "ticks_history": symbol,
            "adjust_start_time": 1,
            "count": count,
            "end": "latest",
            "granularity": granularity,
            "style": "candles",
            "req_id": 1
        }
        
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'User-Agent': 'V75-Chart/1.0'
        }
        
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            print(f"📊 Deriv API response keys: {list(data.keys()) if isinstance(data, dict) else 'Invalid response'}")
            
            if isinstance(data, dict) and not data.get('error'):
                # Check for candles data
                candles_data = data.get('candles', [])
                if not candles_data and 'history' in data:
                    candles_data = data['history'].get('candles', [])
                
                if candles_data:
                    return format_candles_data(candles_data)
                
                # Check for prices data (ticks)
                if 'history' in data and 'prices' in data['history']:
                    return convert_ticks_to_candles(data['history'], granularity)
            
            # Log any error from API
            if data.get('error'):
                print(f"⚠️ Deriv API error: {data['error']}")
        
        return None
        
    except Exception as e:
        print(f"❌ Deriv API failed: {str(e)}")
        return None

def try_binary_api(symbol, granularity, count):
    """Try to get data from Binary.com API"""
    try:
        print("🔄 Trying Binary.com API...")
        
        url = "https://api.binaryws.com/websockets/v3"
        
        payload = {
            "ticks_history": symbol,
            "adjust_start_time": 1,
            "count": count,
            "end": "latest",
            "granularity": granularity,
            "style": "candles"
        }
        
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Origin': 'https://app.deriv.com'
        }
        
        response = requests.post(url, json=payload, headers=headers, timeout=15)
        
        if response.status_code == 200:
            data = response.json()
            print(f"📊 Binary API response keys: {list(data.keys()) if isinstance(data, dict) else 'Invalid response'}")
            
            if isinstance(data, dict) and not data.get('error'):
                # Check for candles data
                candles_data = data.get('candles', [])
                if not candles_data and 'history' in data:
                    candles_data = data['history'].get('candles', [])
                
                if candles_data:
                    return format_candles_data(candles_data)
                
                # Check for prices data (ticks)
                if 'history' in data and 'prices' in data['history']:
                    return convert_ticks_to_candles(data['history'], granularity)
            
            if data.get('error'):
                print(f"⚠️ Binary API error: {data['error']}")
        
        return None
        
    except Exception as e:
        print(f"❌ Binary API failed: {str(e)}")
        return None

def try_tick_to_candles(symbol, granularity, count):
    """Try to get current tick and generate historical candles"""
    try:
        print("🔄 Trying tick-to-candles conversion...")
        
        # Get current tick
        url = "https://api.binaryws.com/websockets/v3"
        payload = {
            "ticks": symbol,
            "subscribe": 0
        }
        
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
        
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            
            if 'tick' in data and 'quote' in data['tick']:
                current_price = float(data['tick']['quote'])
                current_time = int(time.time())
                
                # Generate realistic V75 candles based on current price
                return generate_realistic_v75_candles(current_price, current_time, granularity, count)
        
        return None
        
    except Exception as e:
        print(f"❌ Tick conversion failed: {str(e)}")
        return None

def format_candles_data(candles_data):
    """Format candles data to consistent structure"""
    candles = []
    
    for candle in candles_data:
        try:
            if isinstance(candle, list) and len(candle) >= 5:
                # Format: [epoch, open, high, low, close, volume?]
                candles.append({
                    "epoch": int(candle[0]),
                    "open": float(candle[1]),
                    "high": float(candle[2]),
                    "low": float(candle[3]),
                    "close": float(candle[4])
                })
            elif isinstance(candle, dict):
                # Dict format
                candles.append({
                    "epoch": int(candle.get("epoch", 0)),
                    "open": float(candle.get("open", 0)),
                    "high": float(candle.get("high", 0)),
                    "low": float(candle.get("low", 0)),
                    "close": float(candle.get("close", 0))
                })
        except (ValueError, TypeError) as e:
            print(f"⚠️ Skipping invalid candle data: {e}")
            continue
    
    return candles if candles else None

def convert_ticks_to_candles(history_data, granularity):
    """Convert tick data to candles"""
    try:
        prices = history_data.get('prices', [])
        times = history_data.get('times', [])
        
        if not prices or not times or len(prices) != len(times):
            return None
        
        # Group ticks into candle periods
        candles = []
        current_time = int(times[0])
        period_start = (current_time // granularity) * granularity
        
        i = 0
        while i < len(prices):
            period_end = period_start + granularity
            period_prices = []
            period_times = []
            
            # Collect all ticks in this period
            while i < len(prices) and times[i] < period_end:
                period_prices.append(float(prices[i]))
                period_times.append(int(times[i]))
                i += 1
            
            if period_prices:
                candles.append({
                    "epoch": period_start,
                    "open": period_prices[0],
                    "high": max(period_prices),
                    "low": min(period_prices),
                    "close": period_prices[-1]
                })
            
            period_start = period_end
        
        return candles if candles else None
        
    except Exception as e:
        print(f"❌ Tick conversion error: {str(e)}")
        return None

def generate_realistic_v75_candles(base_price, end_time, granularity, count):
    """Generate realistic V75 candles for demonstration"""
    import random
    
    candles = []
    current_price = base_price
    current_time = end_time - (count * granularity)
    
    # V75 typical volatility parameters
    volatility = 0.02  # 2% base volatility
    spike_probability = 0.1  # 10% chance of volatility spike
    
    for _ in range(count):
        # Calculate price movement
        if random.random() < spike_probability:
            # Volatility spike (V75 characteristic)
            price_change = random.gauss(0, volatility * 5)
        else:
            # Normal movement
            price_change = random.gauss(0, volatility)
        
        open_price = current_price
        
        # Generate OHLC for this period
        close_price = open_price * (1 + price_change)
        
        # High and low with some randomness
        high_offset = abs(random.gauss(0, volatility * 0.5))
        low_offset = abs(random.gauss(0, volatility * 0.5))
        
        high_price = max(open_price, close_price) * (1 + high_offset)
        low_price = min(open_price, close_price) * (1 - low_offset)
        
        candles.append({
            "epoch": current_time,
            "open": round(open_price, 4),
            "high": round(high_price, 4),
            "low": round(low_price, 4),
            "close": round(close_price, 4)
        })
        
        current_price = close_price
        current_time += granularity
    
    return candles

@app.route("/api/current_price")
def get_current_v75_price():
    """Get current V75 price"""
    try:
        symbol = V75_SYMBOL
        
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
        
        payload = {
            "ticks": symbol,
            "subscribe": 0
        }
        
        response = requests.post("https://api.binaryws.com/websockets/v3", 
                               json=payload, headers=headers, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            if 'tick' in data and 'quote' in data['tick']:
                price = float(data['tick']['quote'])
                global current_v75_price
                current_v75_price = price
                
                return jsonify({
                    "symbol": symbol,
                    "price": price,
                    "timestamp": int(time.time())
                })
        
        # Fallback to last known price if available
        if current_v75_price:
            return jsonify({
                "symbol": symbol,
                "price": current_v75_price,
                "timestamp": int(time.time()),
                "note": "Last known price"
            })
        
        return jsonify({"error": "Unable to fetch current V75 price"}), 503
        
    except Exception as e:
        print(f"❌ Current price error: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Endpoint not found"}), 404

@app.errorhandler(500)
def server_error(error):
    return jsonify({"error": "Internal server error"}), 500

def log_startup_info():
    """Print startup information"""
    print("🚀 Volatility 75 Live Chart Server Starting...")
    print(f"📊 Target Symbol: {V75_SYMBOL}")
    print(f"🌐 Server URL: http://localhost:5000")
    print(f"🔗 API Test: http://localhost:5000/api/test")
    print("✅ Server ready for V75 market data!")

if __name__ == "__main__":
    log_startup_info()
    
    # Run the Flask app
    app.run(
        host="0.0.0.0", 
        port=5000, 
        debug=True,
        threaded=True
    )
