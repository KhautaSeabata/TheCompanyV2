from flask import Flask, jsonify, request
from flask_cors import CORS
import time
import random
import math
from datetime import datetime

app = Flask(__name__)
CORS(app)

# Hardcoded XAUUSD base price and current price
XAUUSD_BASE_PRICE = 2650.00
current_price = XAUUSD_BASE_PRICE

# Hardcoded realistic price data - this ensures we always have data
HARDCODED_1M_DATA = [
    {"epoch": int(time.time()) - 3600, "open": 2648.50, "high": 2651.20, "low": 2647.80, "close": 2650.10},
    {"epoch": int(time.time()) - 3540, "open": 2650.10, "high": 2652.40, "low": 2649.60, "close": 2651.75},
    {"epoch": int(time.time()) - 3480, "open": 2651.75, "high": 2653.90, "low": 2650.20, "close": 2652.30},
    {"epoch": int(time.time()) - 3420, "open": 2652.30, "high": 2654.15, "low": 2651.45, "close": 2653.80},
    {"epoch": int(time.time()) - 3360, "open": 2653.80, "high": 2655.60, "low": 2652.90, "close": 2654.25},
    {"epoch": int(time.time()) - 3300, "open": 2654.25, "high": 2656.40, "low": 2653.10, "close": 2655.90},
    {"epoch": int(time.time()) - 3240, "open": 2655.90, "high": 2657.75, "low": 2654.80, "close": 2656.45},
    {"epoch": int(time.time()) - 3180, "open": 2656.45, "high": 2658.20, "low": 2655.30, "close": 2657.10},
    {"epoch": int(time.time()) - 3120, "open": 2657.10, "high": 2659.85, "low": 2656.25, "close": 2658.75},
    {"epoch": int(time.time()) - 3060, "open": 2658.75, "high": 2660.90, "low": 2657.40, "close": 2659.20},
    {"epoch": int(time.time()) - 3000, "open": 2659.20, "high": 2661.45, "low": 2658.10, "close": 2660.85},
    {"epoch": int(time.time()) - 2940, "open": 2660.85, "high": 2662.70, "low": 2659.95, "close": 2661.40},
    {"epoch": int(time.time()) - 2880, "open": 2661.40, "high": 2663.25, "low": 2660.50, "close": 2662.15},
    {"epoch": int(time.time()) - 2820, "open": 2662.15, "high": 2664.80, "low": 2661.30, "close": 2663.95},
    {"epoch": int(time.time()) - 2760, "open": 2663.95, "high": 2665.40, "low": 2662.85, "close": 2664.70},
    {"epoch": int(time.time()) - 2700, "open": 2664.70, "high": 2666.90, "low": 2663.55, "close": 2665.25},
    {"epoch": int(time.time()) - 2640, "open": 2665.25, "high": 2667.15, "low": 2664.40, "close": 2666.80},
    {"epoch": int(time.time()) - 2580, "open": 2666.80, "high": 2668.95, "low": 2665.70, "close": 2667.45},
    {"epoch": int(time.time()) - 2520, "open": 2667.45, "high": 2669.30, "low": 2666.20, "close": 2668.10},
    {"epoch": int(time.time()) - 2460, "open": 2668.10, "high": 2670.75, "low": 2667.25, "close": 2669.90},
    {"epoch": int(time.time()) - 2400, "open": 2669.90, "high": 2671.40, "low": 2668.80, "close": 2670.55},
    {"epoch": int(time.time()) - 2340, "open": 2670.55, "high": 2672.85, "low": 2669.70, "close": 2671.20},
    {"epoch": int(time.time()) - 2280, "open": 2671.20, "high": 2673.60, "low": 2670.35, "close": 2672.95},
    {"epoch": int(time.time()) - 2220, "open": 2672.95, "high": 2674.20, "low": 2671.80, "close": 2673.45},
    {"epoch": int(time.time()) - 2160, "open": 2673.45, "high": 2675.90, "low": 2672.60, "close": 2674.75},
    {"epoch": int(time.time()) - 2100, "open": 2674.75, "high": 2676.30, "low": 2673.90, "close": 2675.15},
    {"epoch": int(time.time()) - 2040, "open": 2675.15, "high": 2677.80, "low": 2674.25, "close": 2676.90},
    {"epoch": int(time.time()) - 1980, "open": 2676.90, "high": 2678.45, "low": 2675.70, "close": 2677.25},
    {"epoch": int(time.time()) - 1920, "open": 2677.25, "high": 2679.60, "low": 2676.40, "close": 2678.80},
    {"epoch": int(time.time()) - 1860, "open": 2678.80, "high": 2680.15, "low": 2677.95, "close": 2679.35},
    {"epoch": int(time.time()) - 1800, "open": 2679.35, "high": 2681.70, "low": 2678.50, "close": 2680.95},
    {"epoch": int(time.time()) - 1740, "open": 2680.95, "high": 2682.40, "low": 2679.80, "close": 2681.60},
    {"epoch": int(time.time()) - 1680, "open": 2681.60, "high": 2683.85, "low": 2680.75, "close": 2682.30},
    {"epoch": int(time.time()) - 1620, "open": 2682.30, "high": 2684.50, "low": 2681.45, "close": 2683.95},
    {"epoch": int(time.time()) - 1560, "open": 2683.95, "high": 2685.20, "low": 2682.80, "close": 2684.40},
    {"epoch": int(time.time()) - 1500, "open": 2684.40, "high": 2686.75, "low": 2683.55, "close": 2685.60},
    {"epoch": int(time.time()) - 1440, "open": 2685.60, "high": 2687.30, "low": 2684.45, "close": 2686.15},
    {"epoch": int(time.time()) - 1380, "open": 2686.15, "high": 2688.90, "low": 2685.30, "close": 2687.75},
    {"epoch": int(time.time()) - 1320, "open": 2687.75, "high": 2689.40, "low": 2686.90, "close": 2688.20},
    {"epoch": int(time.time()) - 1260, "open": 2688.20, "high": 2690.85, "low": 2687.35, "close": 2689.95},
    {"epoch": int(time.time()) - 1200, "open": 2689.95, "high": 2691.50, "low": 2688.80, "close": 2690.25},
    {"epoch": int(time.time()) - 1140, "open": 2690.25, "high": 2692.70, "low": 2689.40, "close": 2691.85},
    {"epoch": int(time.time()) - 1080, "open": 2691.85, "high": 2693.20, "low": 2690.95, "close": 2692.40},
    {"epoch": int(time.time()) - 1020, "open": 2692.40, "high": 2694.95, "low": 2691.55, "close": 2693.75},
    {"epoch": int(time.time()) - 960, "open": 2693.75, "high": 2695.60, "low": 2692.90, "close": 2694.30},
    {"epoch": int(time.time()) - 900, "open": 2694.30, "high": 2696.85, "low": 2693.45, "close": 2695.90},
    {"epoch": int(time.time()) - 840, "open": 2695.90, "high": 2697.40, "low": 2694.75, "close": 2696.55},
    {"epoch": int(time.time()) - 780, "open": 2696.55, "high": 2699.10, "low": 2695.70, "close": 2698.20},
    {"epoch": int(time.time()) - 720, "open": 2698.20, "high": 2699.85, "low": 2697.35, "close": 2698.90},
    {"epoch": int(time.time()) - 660, "open": 2698.90, "high": 2701.45, "low": 2698.05, "close": 2700.75},
    {"epoch": int(time.time()) - 600, "open": 2700.75, "high": 2702.30, "low": 2699.90, "close": 2701.40},
    {"epoch": int(time.time()) - 540, "open": 2701.40, "high": 2703.95, "low": 2700.55, "close": 2702.85},
    {"epoch": int(time.time()) - 480, "open": 2702.85, "high": 2704.50, "low": 2701.70, "close": 2703.25},
    {"epoch": int(time.time()) - 420, "open": 2703.25, "high": 2706.10, "low": 2702.40, "close": 2705.60},
    {"epoch": int(time.time()) - 360, "open": 2705.60, "high": 2707.85, "low": 2704.75, "close": 2706.95},
    {"epoch": int(time.time()) - 300, "open": 2706.95, "high": 2708.40, "low": 2705.80, "close": 2707.70},
    {"epoch": int(time.time()) - 240, "open": 2707.70, "high": 2710.25, "low": 2706.85, "close": 2709.15},
    {"epoch": int(time.time()) - 180, "open": 2709.15, "high": 2711.90, "low": 2708.30, "close": 2710.45},
    {"epoch": int(time.time()) - 120, "open": 2710.45, "high": 2712.60, "low": 2709.60, "close": 2711.80},
    {"epoch": int(time.time()) - 60, "open": 2711.80, "high": 2714.35, "low": 2710.95, "close": 2713.20},
    {"epoch": int(time.time()), "open": 2713.20, "high": 2715.70, "low": 2712.35, "close": 2714.85}
]

def generate_dynamic_candles(interval, count):
    """Generate realistic XAUUSD candles based on hardcoded data with variations"""
    global current_price
    
    # Base intervals in seconds
    intervals = {
        "1m": 60,
        "5m": 300,
        "15m": 900,
        "30m": 1800,
        "1h": 3600,
        "4h": 14400
    }
    
    granularity = intervals.get(interval, 60)
    now = int(time.time())
    
    candles = []
    base_price = XAUUSD_BASE_PRICE
    
    for i in range(count):
        # Calculate timestamp going backwards from now
        timestamp = now - (granularity * (count - i - 1))
        
        # Create realistic price movement
        time_factor = i / count
        
        # Add market cycles
        daily_cycle = math.sin(time_factor * 2 * math.pi) * 8
        weekly_trend = math.cos(time_factor * 0.5 * math.pi) * 15
        
        # Add controlled randomness
        random_movement = random.uniform(-5, 5)
        volatility = random.uniform(-10, 10) if random.random() < 0.15 else 0
        
        # Calculate base price for this candle
        price_movement = daily_cycle + weekly_trend + random_movement + volatility
        base_price += price_movement * 0.1
        
        # Keep within realistic bounds
        if base_price < XAUUSD_BASE_PRICE * 0.96:
            base_price = XAUUSD_BASE_PRICE * 0.96
        elif base_price > XAUUSD_BASE_PRICE * 1.04:
            base_price = XAUUSD_BASE_PRICE * 1.04
        
        # Generate OHLC with realistic spreads
        spread = random.uniform(1.5, 4.0)
        
        if i == 0:
            open_price = base_price
        else:
            # Small gap from previous close
            gap = random.uniform(-0.8, 0.8)
            open_price = candles[-1]["close"] + gap
        
        # Create high and low with realistic movement
        high_move = random.uniform(0.5, spread)
        low_move = random.uniform(0.5, spread)
        
        high_price = max(open_price, base_price) + high_move
        low_price = min(open_price, base_price) - low_move
        
        # Close price within the range
        close_range = high_price - low_price
        close_offset = random.uniform(0.2, 0.8)
        close_price = low_price + (close_range * close_offset)
        
        # Ensure OHLC relationships
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
        current_price = close_price
    
    return candles

@app.route("/")
def index():
    """Root endpoint"""
    return jsonify({
        "service": "XAUUSD Trading API",
        "status": "online",
        "message": "Gold/USD market data API is running",
        "endpoints": [
            "/api/test",
            "/api/candles?interval=1m",
            "/api/current-price",
            "/api/market-status",
            "/health"
        ]
    })

@app.route("/api/test")
def test_api():
    """Test endpoint - hardcoded response"""
    return jsonify({
        "status": "XAUUSD API Server Online",
        "timestamp": int(time.time()),
        "message": "Flask server ready for Gold/USD market data",
        "symbol": "XAUUSD",
        "market": "FOREX/Commodities",
        "base_price": XAUUSD_BASE_PRICE,
        "current_price": current_price,
        "data_sources": ["Hardcoded Realistic Data"],
        "version": "1.0.0-hardcoded"
    })

@app.route("/api/candles")
def get_candles():
    """Get XAUUSD candles - completely hardcoded"""
    try:
        interval = request.args.get("interval", "1m")
        
        # Validate interval
        valid_intervals = ["1m", "5m", "15m", "30m", "1h", "4h"]
        if interval not in valid_intervals:
            interval = "1m"
        
        # Count based on interval
        count_map = {
            "1m": 60,
            "5m": 48,
            "15m": 40,
            "30m": 48,
            "1h": 24,
            "4h": 24
        }
        
        count = count_map.get(interval, 60)
        
        print(f"📊 Generating {count} hardcoded XAUUSD candles for {interval}")
        
        # Generate dynamic but predictable data
        candles = generate_dynamic_candles(interval, count)
        
        print(f"✅ Generated {len(candles)} XAUUSD candles")
        return jsonify(candles)
        
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        # Return basic hardcoded data as absolute fallback
        fallback = [
            {
                "epoch": int(time.time()) - 300,
                "open": XAUUSD_BASE_PRICE,
                "high": XAUUSD_BASE_PRICE + 5,
                "low": XAUUSD_BASE_PRICE - 3,
                "close": XAUUSD_BASE_PRICE + 2
            },
            {
                "epoch": int(time.time()),
                "open": XAUUSD_BASE_PRICE + 2,
                "high": XAUUSD_BASE_PRICE + 7,
                "low": XAUUSD_BASE_PRICE - 1,
                "close": XAUUSD_BASE_PRICE + 4
            }
        ]
        return jsonify(fallback)

@app.route("/api/current-price")
def get_current_price():
    """Get current XAUUSD price - hardcoded with variation"""
    try:
        # Add small random variation to make it feel live
        price_variation = random.uniform(-2, 2)
        live_price = current_price + price_variation
        
        return jsonify({
            "symbol": "XAUUSD",
            "price": round(live_price, 2),
            "timestamp": int(time.time()),
            "currency": "USD",
            "change": round(price_variation, 2),
            "change_percent": round((price_variation / XAUUSD_BASE_PRICE) * 100, 3)
        })
        
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return jsonify({
            "symbol": "XAUUSD",
            "price": XAUUSD_BASE_PRICE,
            "timestamp": int(time.time()),
            "currency": "USD"
        })

@app.route("/api/market-status")
def get_market_status():
    """Get market status - hardcoded logic"""
    try:
        now = datetime.now()
        weekday = now.weekday()  # 0 = Monday, 6 = Sunday
        hour = now.hour
        
        # Forex market closed on weekends
        if weekday == 6:  # Sunday
            is_open = hour >= 17  # Opens Sunday 5 PM EST
        elif weekday == 5:  # Friday
            is_open = hour < 17   # Closes Friday 5 PM EST
        else:
            is_open = True  # Open Monday-Thursday
        
        return jsonify({
            "market": "FOREX",
            "symbol": "XAUUSD",
            "status": "OPEN" if is_open else "CLOSED",
            "timezone": "EST",
            "last_update": int(time.time()),
            "next_open": "Sunday 17:00 EST" if not is_open else None
        })
        
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return jsonify({
            "market": "FOREX",
            "symbol": "XAUUSD",
            "status": "OPEN",
            "timezone": "EST",
            "last_update": int(time.time())
        })

@app.route("/health")
def health_check():
    """Health check - hardcoded response"""
    return jsonify({
        "status": "healthy",
        "service": "XAUUSD Hardcoded API",
        "timestamp": int(time.time()),
        "uptime": "running",
        "version": "1.0.0-hardcoded",
        "data_source": "hardcoded"
    })

# Error handlers
@app.errorhandler(404)
def not_found(error):
    return jsonify({
        "error": "Endpoint not found", 
        "message": "Available endpoints: /api/test, /api/candles, /api/current-price, /health",
        "requested_path": request.path
    }), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({
        "error": "Internal server error",
        "message": "XAUUSD API encountered an error",
        "service": "hardcoded"
    }), 500

if __name__ == "__main__":
    print("🚀 Starting XAUUSD Hardcoded API Server...")
    print("📊 All data is hardcoded - no external dependencies!")
    
    # Get port from environment (Render)
    port = int(os.environ.get('PORT', 5000))
    
    print("✅ XAUUSD Hardcoded API Ready!")
    print("📡 Hardcoded endpoints:")
    print("   GET / - Service info")
    print("   GET /api/test - Test connection") 
    print("   GET /api/candles?interval=1m - Get candles")
    print("   GET /api/current-price - Current price")
    print("   GET /api/market-status - Market status")
    print("   GET /health - Health check")
    print(f"🌐 Server starting on port {port}")
    
    # Simple Flask run - no threading complications
    app.run(host="0.0.0.0", port=port, debug=False)
