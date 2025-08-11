from flask import Flask, render_template, request, jsonify, send_from_directory
from flask_cors import CORS
import requests
import time
import json
import os
from datetime import datetime, timedelta
import random
import math
import threading
from collections import deque

app = Flask(__name__)
CORS(app)

# Global variables for XAUUSD data
current_xauusd_price = None
xauusd_base_price = 2650.00  # Approximate current XAUUSD price
price_history = deque(maxlen=1000)  # Keep last 1000 price points

@app.route("/")
def index():
    """Serve the main HTML page"""
    return send_from_directory('.', 'index.html')

@app.route("/api/test")
def test_api():
    """Test endpoint to check if API is working"""
    return jsonify({
        "status": "XAUUSD API Server Online",
        "timestamp": int(time.time()),
        "message": "Flask server ready for Gold/USD market data",
        "symbol": "XAUUSD",
        "market": "FOREX/Commodities",
        "base_price": xauusd_base_price,
        "data_sources": ["Yahoo Finance", "Alpha Vantage", "Twelve Data", "Realistic Simulation"]
    })

@app.route("/api/candles")
def get_xauusd_candles():
    """Get XAUUSD candles data with multiple data sources"""
    try:
        interval = request.args.get("interval", "1m")
        
        print(f"🔍 Fetching XAUUSD data for interval: {interval}")
        
        # Map intervals to parameters
        interval_config = {
            "1m": {"granularity": 60, "count": 60},
            "5m": {"granularity": 300, "count": 50},
            "15m": {"granularity": 900, "count": 40},
            "30m": {"granularity": 1800, "count": 48},
            "1h": {"granularity": 3600, "count": 24},
            "4h": {"granularity": 14400, "count": 24}
        }
        
        config = interval_config.get(interval, {"granularity": 60, "count": 60})
        granularity = config["granularity"]
        count = config["count"]
        
        # Try multiple methods to get XAUUSD data
        
        # Method 1: Try Yahoo Finance (most reliable for XAUUSD)
        candles = try_yahoo_finance(interval, count)
        if candles:
            print(f"✅ Got {len(candles)} XAUUSD candles from Yahoo Finance")
            return jsonify(candles)
        
        # Method 2: Try Alpha Vantage (if you have API key)
        candles = try_alpha_vantage(interval, count)
        if candles:
            print(f"✅ Got {len(candles)} XAUUSD candles from Alpha Vantage")
            return jsonify(candles)
        
        # Method 3: Try Financial APIs
        candles = try_financial_apis(interval, count)
        if candles:
            print(f"✅ Got {len(candles)} XAUUSD candles from Financial APIs")
            return jsonify(candles)
        
        # Method 4: Generate realistic XAUUSD data (fallback)
        print("📊 Generating realistic XAUUSD market data")
        candles = generate_realistic_xauusd_candles(granularity, count)
        print(f"✅ Generated {len(candles)} realistic XAUUSD candles")
        return jsonify(candles)
        
    except Exception as e:
        print(f"❌ Error in get_xauusd_candles: {str(e)}")
        # Always return realistic data as fallback
        candles = generate_realistic_xauusd_candles(60, 50)
        return jsonify(candles)

def try_yahoo_finance(interval, count):
    """Try Yahoo Finance for XAUUSD data"""
    try:
        print("🔄 Trying Yahoo Finance API for XAUUSD...")
        
        # Yahoo Finance symbols for Gold
        symbols = ["GC=F", "XAUUSD=X"]  # Gold futures and XAUUSD
        
        for symbol in symbols:
            try:
                # Note: This requires yfinance package
                # Install with: pip install yfinance
                import yfinance as yf
                
                ticker = yf.Ticker(symbol)
                
                # Map intervals
                yf_interval_map = {
                    "1m": "1m",
                    "5m": "5m", 
                    "15m": "15m",
                    "30m": "30m",
                    "1h": "1h",
                    "4h": "4h"
                }
                
                period_map = {
                    "1m": "1d",    # 1 minute data for 1 day
                    "5m": "5d",    # 5 minute data for 5 days
                    "15m": "5d",   # 15 minute data for 5 days
                    "30m": "5d",   # 30 minute data for 5 days
                    "1h": "5d",    # 1 hour data for 5 days
                    "4h": "30d"    # 4 hour data for 30 days
                }
                
                yf_interval = yf_interval_map.get(interval, "1m")
                period = period_map.get(interval, "1d")
                
                print(f"📊 Fetching {symbol} data: period={period}, interval={yf_interval}")
                hist = ticker.history(period=period, interval=yf_interval)
                
                if not hist.empty and len(hist) > 0:
                    candles = []
                    for index, row in hist.tail(count).iterrows():
                        # Convert to XAUUSD if needed
                        price_multiplier = 1.0
                        if symbol == "GC=F":
                            # Gold futures are typically quoted per troy ounce
                            price_multiplier = 1.0
                        
                        candles.append({
                            "epoch": int(index.timestamp()),
                            "open": float(row['Open']) * price_multiplier,
                            "high": float(row['High']) * price_multiplier,
                            "low": float(row['Low']) * price_multiplier,
                            "close": float(row['Close']) * price_multiplier
                        })
                    
                    if candles:
                        print(f"✅ Got {len(candles)} candles from Yahoo Finance ({symbol})")
                        return candles
                        
            except Exception as e:
                print(f"❌ Yahoo Finance ({symbol}) failed: {e}")
                continue
        
        return None
        
    except ImportError:
        print("⚠️ yfinance not installed. Install with: pip install yfinance")
        return None
    except Exception as e:
        print(f"❌ Yahoo Finance failed: {str(e)}")
        return None

def try_alpha_vantage(interval, count):
    """Try Alpha Vantage API for XAUUSD data"""
    try:
        print("🔄 Trying Alpha Vantage API...")
        
        # You need to get a free API key from: https://www.alphavantage.co/support/#api-key
        api_key = os.environ.get('ALPHA_VANTAGE_API_KEY')
        
        if not api_key:
            print("⚠️ Alpha Vantage API key not found. Set ALPHA_VANTAGE_API_KEY environment variable")
            return None
        
        # Map intervals for Alpha Vantage
        av_interval_map = {
            "1m": "1min",
            "5m": "5min",
            "15m": "15min",
            "30m": "30min",
            "1h": "60min",
            "4h": "60min"  # Use hourly and aggregate
        }
        
        av_interval = av_interval_map.get(interval, "1min")
        
        # Alpha Vantage FX endpoint for XAUUSD
        url = f"https://www.alphavantage.co/query"
        params = {
            "function": "FX_INTRADAY",
            "from_symbol": "XAU",
            "to_symbol": "USD",
            "interval": av_interval,
            "apikey": api_key,
            "outputsize": "compact"
        }
        
        response = requests.get(url, params=params, timeout=15)
        
        if response.status_code == 200:
            data = response.json()
            
            # Check for API errors
            if "Error Message" in data:
                print(f"❌ Alpha Vantage error: {data['Error Message']}")
                return None
            
            if "Note" in data:
                print(f"⚠️ Alpha Vantage note: {data['Note']}")
                return None
            
            # Extract time series data
            time_series_key = f"Time Series FX ({av_interval})"
            if time_series_key in data:
                time_series = data[time_series_key]
                
                candles = []
                for timestamp, ohlc in list(time_series.items())[:count]:
                    epoch = int(datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S").timestamp())
                    
                    candles.append({
                        "epoch": epoch,
                        "open": float(ohlc["1. open"]),
                        "high": float(ohlc["2. high"]),
                        "low": float(ohlc["3. low"]),
                        "close": float(ohlc["4. close"])
                    })
                
                # Sort by timestamp (oldest first)
                candles.sort(key=lambda x: x["epoch"])
                return candles
        
        return None
        
    except Exception as e:
        print(f"❌ Alpha Vantage failed: {str(e)}")
        return None

def try_financial_apis(interval, count):
    """Try other financial APIs for XAUUSD data"""
    try:
        print("🔄 Trying additional financial APIs...")
        
        # Method 1: Try Twelve Data (has free tier)
        api_key = os.environ.get('TWELVE_DATA_API_KEY')
        if api_key:
            try:
                url = "https://api.twelvedata.com/time_series"
                params = {
                    "symbol": "XAUUSD",
                    "interval": interval,
                    "outputsize": count,
                    "apikey": api_key
                }
                
                response = requests.get(url, params=params, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    if "values" in data:
                        candles = []
                        for item in reversed(data["values"]):  # Reverse to get chronological order
                            epoch = int(datetime.strptime(item["datetime"], "%Y-%m-%d %H:%M:%S").timestamp())
                            candles.append({
                                "epoch": epoch,
                                "open": float(item["open"]),
                                "high": float(item["high"]),
                                "low": float(item["low"]),
                                "close": float(item["close"])
                            })
                        
                        if candles:
                            return candles
            except Exception as e:
                print(f"Twelve Data failed: {e}")
        
        # Method 2: Try Financial Modeling Prep (free tier available)
        fmp_key = os.environ.get('FMP_API_KEY')
        if fmp_key:
            try:
                url = f"https://financialmodelingprep.com/api/v3/historical-chart/{interval}/XAUUSD"
                params = {"apikey": fmp_key}
                
                response = requests.get(url, params=params, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    if data and len(data) > 0:
                        candles = []
                        for item in data[:count]:
                            epoch = int(datetime.strptime(item["date"], "%Y-%m-%d %H:%M:%S").timestamp())
                            candles.append({
                                "epoch": epoch,
                                "open": float(item["open"]),
                                "high": float(item["high"]),
                                "low": float(item["low"]),
                                "close": float(item["close"])
                            })
                        
                        if candles:
                            return sorted(candles, key=lambda x: x["epoch"])
            except Exception as e:
                print(f"Financial Modeling Prep failed: {e}")
        
        # Method 3: Try a simple forex API for current rates
        try:
            url = "https://api.exchangerate-api.com/v4/latest/USD"
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                data = response.json()
                # This won't have XAU, but we can use it as a template
                # Skip this for now as it doesn't have gold data
                pass
        except Exception as e:
            print(f"Exchange rate API failed: {e}")
        
        return None
        
    except Exception as e:
        print(f"❌ Financial APIs failed: {str(e)}")
        return None

def generate_realistic_xauusd_candles(granularity, count):
    """Generate realistic XAUUSD market data based on actual market patterns"""
    global current_xauusd_price
    
    try:
        print(f"📊 Generating {count} realistic XAUUSD candles with {granularity}s granularity")
        
        # Start from current time and work backwards
        end_time = int(time.time())
        start_time = end_time - (granularity * count)
        
        # Initialize base price if not set
        if current_xauusd_price is None:
            current_xauusd_price = xauusd_base_price
        
        candles = []
        
        # Generate realistic market data
        for i in range(count):
            timestamp = start_time + (i * granularity)
            
            # Create realistic price movement
            # Gold tends to move in cycles with some volatility
            time_factor = i / count
            
            # Add daily cycle (gold often moves with Asian/European markets)
            daily_cycle = math.sin(time_factor * 2 * math.pi) * 5
            
            # Add random walk component
            random_walk = random.uniform(-8, 8)
            
            # Add trend component (slight upward bias for gold)
            trend = (time_factor - 0.5) * 2
            
            # Add volatility spikes occasionally
            volatility_spike = 0
            if random.random() < 0.1:  # 10% chance of volatility spike
                volatility_spike = random.uniform(-15, 15)
            
            # Calculate price change
            price_change = daily_cycle + random_walk + trend + volatility_spike
            
            # Update current price
            current_xauusd_price += price_change * 0.1  # Scale the movement
            
            # Keep price within realistic bounds (gold doesn't move too wildly)
            if current_xauusd_price < xauusd_base_price * 0.95:
                current_xauusd_price = xauusd_base_price * 0.95
            elif current_xauusd_price > xauusd_base_price * 1.05:
                current_xauusd_price = xauusd_base_price * 1.05
            
            # Generate OHLC based on the timeframe
            base_price = current_xauusd_price
            
            # Create intrabar movement
            tick_range = random.uniform(0.5, 3.0)  # Gold typically moves in small increments
            
            # Generate open price (close of previous candle or slight gap)
            if i == 0:
                open_price = base_price
            else:
                # Small gap up or down from previous close
                gap = random.uniform(-1, 1)
                open_price = candles[-1]["close"] + gap
            
            # Generate high and low with realistic spread
            high_offset = random.uniform(0, tick_range)
            low_offset = random.uniform(0, tick_range)
            
            high_price = max(open_price, base_price) + high_offset
            low_price = min(open_price, base_price) - low_offset
            
            # Generate close price within the range
            close_price = random.uniform(low_price, high_price)
            
            # Ensure OHLC relationships are maintained
            high_price = max(high_price, open_price, close_price)
            low_price = min(low_price, open_price, close_price)
            
            candle = {
                "epoch": timestamp,
                "open": round(open_price, 2),
                "high": round(high_price, 2),
                "low": round(low_price, 2),
                "close": round(close_price, 2)
            }
            
            candles.append(candle)
            
            # Update current price for next iteration
            current_xauusd_price = close_price
        
        print(f"✅ Generated {len(candles)} realistic XAUUSD candles")
        print(f"📈 Price range: ${candles[0]['close']:.2f} - ${candles[-1]['close']:.2f}")
        
        return candles
        
    except Exception as e:
        print(f"❌ Error generating realistic XAUUSD data: {str(e)}")
        # Return minimal fallback data
        current_time = int(time.time())
        return [{
            "epoch": current_time,
            "open": xauusd_base_price,
            "high": xauusd_base_price + 5,
            "low": xauusd_base_price - 5,
            "close": xauusd_base_price
        }]

@app.route("/api/current-price")
def get_current_price():
    """Get current XAUUSD price"""
    try:
        # Try to get real-time price first
        current_price = get_realtime_xauusd_price()
        
        if current_price is None:
            # Fallback to simulated price
            if current_xauusd_price is None:
                current_price = xauusd_base_price
            else:
                current_price = current_xauusd_price
        
        return jsonify({
            "symbol": "XAUUSD",
            "price": round(current_price, 2),
            "timestamp": int(time.time()),
            "currency": "USD"
        })
        
    except Exception as e:
        print(f"❌ Error getting current XAUUSD price: {str(e)}")
        return jsonify({
            "symbol": "XAUUSD",
            "price": xauusd_base_price,
            "timestamp": int(time.time()),
            "currency": "USD"
        }), 500

def get_realtime_xauusd_price():
    """Try to get real-time XAUUSD price from various sources"""
    try:
        # Method 1: Try Yahoo Finance for current price
        try:
            import yfinance as yf
            ticker = yf.Ticker("GC=F")
            info = ticker.history(period="1d", interval="1m").tail(1)
            if not info.empty:
                return float(info['Close'].iloc[0])
        except Exception as e:
            print(f"Yahoo Finance real-time failed: {e}")
        
        # Method 2: Try financial APIs
        api_key = os.environ.get('TWELVE_DATA_API_KEY')
        if api_key:
            try:
                url = "https://api.twelvedata.com/price"
                params = {
                    "symbol": "XAUUSD",
                    "apikey": api_key
                }
                response = requests.get(url, params=params, timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    if "price" in data:
                        return float(data["price"])
            except Exception as e:
                print(f"Twelve Data real-time failed: {e}")
        
        return None
        
    except Exception as e:
        print(f"❌ Error getting real-time XAUUSD price: {str(e)}")
        return None

@app.route("/api/market-status")
def get_market_status():
    """Get market status information"""
    try:
        # Check if it's during market hours (Forex markets are 24/5)
        now = datetime.now()
        weekday = now.weekday()  # 0 = Monday, 6 = Sunday
        
        # Forex market is closed from Friday evening to Sunday evening (EST)
        is_open = not (weekday == 5 and now.hour >= 17) and not (weekday == 6)  # Not Sat evening or Sunday
        
        return jsonify({
            "market": "FOREX",
            "symbol": "XAUUSD",
            "status": "OPEN" if is_open else "CLOSED",
            "timezone": "EST",
            "last_update": int(time.time())
        })
        
    except Exception as e:
        print(f"❌ Error getting market status: {str(e)}")
        return jsonify({
            "market": "FOREX",
            "symbol": "XAUUSD", 
            "status": "UNKNOWN",
            "error": str(e)
        }), 500

# Background price update system
def price_update_worker():
    """Background worker to update prices periodically"""
    global current_xauusd_price
    
    while True:
        try:
            # Try to get real-time price
            real_price = get_realtime_xauusd_price()
            if real_price:
                current_xauusd_price = real_price
                print(f"📈 Updated XAUUSD price: ${real_price:.2f}")
            else:
                # Simulate small price movements
                if current_xauusd_price:
                    change = random.uniform(-2, 2)
                    current_xauusd_price += change
                    print(f"📊 Simulated XAUUSD price: ${current_xauusd_price:.2f}")
            
            time.sleep(30)  # Update every 30 seconds
            
        except Exception as e:
            print(f"❌ Price update worker error: {str(e)}")
            time.sleep(60)  # Wait longer on error

# Error handlers
@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Endpoint not found", "message": "XAUUSD API endpoint not available"}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({"error": "Internal server error", "message": "XAUUSD API encountered an error"}), 500

# Health check endpoint
@app.route("/health")
def health_check():
    return jsonify({
        "status": "healthy",
        "service": "XAUUSD API",
        "timestamp": int(time.time()),
        "uptime": "running"
    })auusd_candles(granularity, count):
    """Generate realistic XAUUSD market data based on actual market patterns"""
    global current_xauusd_price
    
    try:
        print(f"📊 Generating {count} realistic XAUUSD candles with {granularity}s granularity")
        
        # Start from current time and work backwards
        end_time = int(time.time())
        start_time = end_time - (granularity * count)
        
        # Initialize base price if not set
        if current_xauusd_price is None:
            current_xauusd_price = xauusd_base_price
        
        candles = []
        
        # Generate realistic market data
        for i in range(count):
            timestamp = start_time + (i * granularity)
            
            # Create realistic price movement
            # Gold tends to move in cycles with some volatility
            time_factor = i / count
            
            # Add daily cycle (gold often moves with Asian/European markets)
            daily_cycle = math.sin(time_factor * 2 * math.pi) * 5
            
            # Add random walk component
            random_walk = random.uniform(-8, 8)
            
            # Add trend component (slight upward bias for gold)
            trend = (time_factor - 0.5) * 2
            
            # Add volatility spikes occasionally
            volatility_spike = 0
            if random.random() < 0.1:  # 10% chance of volatility spike
                volatility_spike = random.uniform(-15, 15)
            
            # Calculate price change
            price_change = daily_cycle + random_walk + trend + volatility_spike
            
            # Update current price
            current_xauusd_price += price_change * 0.1  # Scale the movement
            
            # Keep price within realistic bounds (gold doesn't move too wildly)
            if current_xauusd_price < xauusd_base_price * 0.95:
                current_xauusd_price = xauusd_base_price * 0.95
            elif current_xauusd_price > xauusd_base_price * 1.05:
                current_xauusd_price = xauusd_base_price * 1.05
            
            # Generate OHLC based on the timeframe
            base_price = current_xauusd_price
            
            # Create intrabar movement
            tick_range = random.uniform(0.5, 3.0)  # Gold typically moves in small increments
            
            # Generate open price (close of previous candle or slight gap)
            if i == 0:
                open_price = base_price
            else:
                # Small gap up or down from previous close
                gap = random.uniform(-1, 1)
                open_price = candles[-1]["close"] + gap
            
            # Generate high and low with realistic spread
            high_offset = random.uniform(0, tick_range)
            low_offset = random.uniform(0, tick_range)
            
            high_price = max(open_price, base_price) + high_offset
            low_price = min(open_price, base_price) - low_offset
            
            # Generate close price within the range
            close_price = random.uniform(low_price, high_price)
            
            # Ensure OHLC relationships are maintained
            high_price = max(high_price, open_price, close_price)
            low_price = min(low_price, open_price, close_price)
            
            candle = {
                "epoch": timestamp,
                "open": round(open_price, 2),
                "high": round(high_price, 2),
                "low": round(low_price, 2),
                "close": round(close_price, 2)
            }
            
            candles.append(candle)
            
            # Update current price for next iteration
            current_xauusd_price = close_price
        
        print(f"✅ Generated {len(candles)} realistic XAUUSD candles")
        print(f"📈 Price range: ${candles[0]['close']:.2f} - ${candles[-1]['close']:.2f}")
        
        return candles
        
    except Exception as e:
        print(f"❌ Error generating realistic XAUUSD data: {str(e)}")
        # Return minimal fallback data
        current_time = int(time.time())
        return [{
            "epoch": current_time,
            "open": xauusd_base_price,
            "high": xauusd_base_price + 5,
            "low": xauusd_base_price - 5,
            "close": xauusd_base_price
        }]

@app.route("/api/current-price")
def get_current_price():
    """Get current XAUUSD price"""
    try:
        # Try to get real-time price first
        current_price = get_realtime_xauusd_price()
        
        if current_price is None:
            # Fallback to simulated price
            if current_xauusd_price is None:
                current_price = xauusd_base_price
            else:
                current_price = current_xauusd_price
        
        return jsonify({
            "symbol": "XAUUSD",
            "price": round(current_price, 2),
            "timestamp": int(time.time()),
            "currency": "USD"
        })
        
    except Exception as e:
        print(f"❌ Error getting current XAUUSD price: {str(e)}")
        return jsonify({
            "symbol": "XAUUSD",
            "price": xauusd_base_price,
            "timestamp": int(time.time()),
            "currency": "USD"
        }), 500

def get_realtime_xauusd_price():
    """Try to get real-time XAUUSD price from various sources"""
    try:
        # Method 1: Try Yahoo Finance for current price
        try:
            import yfinance as yf
            ticker = yf.Ticker("GC=F")
            info = ticker.history(period="1d", interval="1m").tail(1)
            if not info.empty:
                return float(info['Close'].iloc[0])
        except Exception as e:
            print(f"Yahoo Finance real-time failed: {e}")
        
        # Method 2: Try financial APIs
        api_key = os.environ.get('TWELVE_DATA_API_KEY')
        if api_key:
            try:
                url = "https://api.twelvedata.com/price"
                params = {
                    "symbol": "XAUUSD",
                    "apikey": api_key
                }
                response = requests.get(url, params=params, timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    if "price" in data:
                        return float(data["price"])
            except Exception as e:
                print(f"Twelve Data real-time failed: {e}")
        
        return None
        
    except Exception as e:
        print(f"❌ Error getting real-time XAUUSD price: {str(e)}")
        return None

@app.route("/api/market-status")
def get_market_status():
    """Get market status information"""
    try:
        # Check if it's during market hours (Forex markets are 24/5)
        now = datetime.now()
        weekday = now.weekday()  # 0 = Monday, 6 = Sunday
        
        # Forex market is closed from Friday evening to Sunday evening (EST)
        is_open = not (weekday == 5 and now.hour >= 17) and not (weekday == 6)  # Not Sat evening or Sunday
        
        return jsonify({
            "market": "FOREX",
            "symbol": "XAUUSD",
            "status": "OPEN" if is_open else "CLOSED",
            "timezone": "EST",
            "last_update": int(time.time())
        })
        
    except Exception as e:
        print(f"❌ Error getting market status: {str(e)}")
        return jsonify({
            "market": "FOREX",
            "symbol": "XAUUSD", 
            "status": "UNKNOWN",
            "error": str(e)
        }), 500

# Background price update system
def price_update_worker():
    """Background worker to update prices periodically"""
    global current_xauusd_price
    
    while True:
        try:
            # Try to get real-time price
            real_price = get_realtime_xauusd_price()
            if real_price:
                current_xauusd_price = real_price
                print(f"📈 Updated XAUUSD price: ${real_price:.2f}")
            else:
                # Simulate small price movements
                if current_xauusd_price:
                    change = random.uniform(-2, 2)
                    current_xauusd_price += change
                    print(f"📊 Simulated XAUUSD price: ${current_xauusd_price:.2f}")
            
            time.sleep(30)  # Update every 30 seconds
            
        except Exception as e:
            print(f"❌ Price update worker error: {str(e)}")
            time.sleep(60)  # Wait longer on error

# Error handlers
@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Endpoint not found", "message": "XAUUSD API endpoint not available"}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({"error": "Internal server error", "message": "XAUUSD API encountered an error"}), 500

# Health check endpoint
@app.route("/health")
def health_check():
    return jsonify({
        "status": "healthy",
        "service": "XAUUSD API",
        "timestamp": int(time.time()),
        "uptime": "running"
    })

if __name__ == "__main__":
    print("🚀 Starting XAUUSD Flask API Server...")
    print("📊 Gold/USD market data server initializing...")
    
    # Get port from environment (Render sets this automatically)
    port = int(os.environ.get('PORT', 5000))
    
    # Start background price update worker
    price_thread = threading.Thread(target=price_update_worker, daemon=True)
    price_thread.start()
    
    print("✅ XAUUSD API Server ready!")
    print("📡 Available endpoints:")
    print("   GET /api/test - Test API connection")
    print("   GET /api/candles?interval=1m - Get XAUUSD candles")
    print("   GET /api/current-price - Get current XAUUSD price")
    print("   GET /api/market-status - Get market status")
    print("   GET /health - Health check")
    print()
    print(f"🌐 Server starting on port {port}")
    
    # Use different settings for production vs development
    is_production = os.environ.get('FLASK_ENV') == 'production'
    
    if is_production:
        # Production settings for Render
        app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
    else:
        # Development settings
        app.run(host="0.0.0.0", port=port, debug=True)
