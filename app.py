import json
import time
import random
import threading
from datetime import datetime, timedelta
from flask import Flask, render_template, jsonify
from flask_cors import CORS
import requests
import schedule

app = Flask(__name__)
CORS(app)

# Firebase Realtime Database URL
FIREBASE_URL = "https://vix25-486b9-default-rtdb.firebaseio.com"

# VIX price levels and probabilities
VIX_LEVELS = {
    10: 0.1,      # 10% probability
    10: 0.1,      # 1s intervals
    25.75: 0.3,   # 30% probability
    75: 0.1,      # 1s intervals
    100: 0.1,     # 10% probability
    100: 0.1,     # 1s intervals
    150: 0.1      # 1s intervals
}

# Current VIX price
current_vix = 25.75
last_update = datetime.now()

# Data storage limits
MAX_DATA_POINTS = 900

class VIXDataManager:
    def __init__(self):
        self.live_ticks = []
        self.candles_1min = []
        self.candles_5min = []
        
    def add_tick(self, price, timestamp):
        """Add a new tick and manage data limits"""
        tick_data = {
            'price': price,
            'timestamp': timestamp.isoformat(),
            'volume': random.randint(1000, 10000)
        }
        
        self.live_ticks.append(tick_data)
        
        # Limit live ticks to 900
        if len(self.live_ticks) > MAX_DATA_POINTS:
            self.live_ticks = self.live_ticks[-MAX_DATA_POINTS:]
            
        # Update candles
        self.update_candles(price, timestamp)
        
    def update_candles(self, price, timestamp):
        """Update 1min and 5min candles"""
        self.update_1min_candle(price, timestamp)
        self.update_5min_candle(price, timestamp)
        
    def update_1min_candle(self, price, timestamp):
        """Update 1-minute candles"""
        minute_key = timestamp.replace(second=0, microsecond=0)
        
        # Find existing candle or create new one
        current_candle = None
        for candle in self.candles_1min:
            if candle['timestamp'] == minute_key.isoformat():
                current_candle = candle
                break
                
        if current_candle is None:
            current_candle = {
                'timestamp': minute_key.isoformat(),
                'open': price,
                'high': price,
                'low': price,
                'close': price,
                'volume': 0
            }
            self.candles_1min.append(current_candle)
            
        # Update candle
        current_candle['high'] = max(current_candle['high'], price)
        current_candle['low'] = min(current_candle['low'], price)
        current_candle['close'] = price
        current_candle['volume'] += random.randint(100, 1000)
        
        # Limit to 900 candles
        if len(self.candles_1min) > MAX_DATA_POINTS:
            self.candles_1min = self.candles_1min[-MAX_DATA_POINTS:]
            
    def update_5min_candle(self, price, timestamp):
        """Update 5-minute candles"""
        # Round to 5-minute intervals
        minute = timestamp.minute - (timestamp.minute % 5)
        five_min_key = timestamp.replace(minute=minute, second=0, microsecond=0)
        
        # Find existing candle or create new one
        current_candle = None
        for candle in self.candles_5min:
            if candle['timestamp'] == five_min_key.isoformat():
                current_candle = candle
                break
                
        if current_candle is None:
            current_candle = {
                'timestamp': five_min_key.isoformat(),
                'open': price,
                'high': price,
                'low': price,
                'close': price,
                'volume': 0
            }
            self.candles_5min.append(current_candle)
            
        # Update candle
        current_candle['high'] = max(current_candle['high'], price)
        current_candle['low'] = min(current_candle['low'], price)
        current_candle['close'] = price
        current_candle['volume'] += random.randint(500, 5000)
        
        # Limit to 900 candles
        if len(self.candles_5min) > MAX_DATA_POINTS:
            self.candles_5min = self.candles_5min[-MAX_DATA_POINTS:]

# Initialize data manager
data_manager = VIXDataManager()

def generate_vix_price():
    """Generate realistic VIX price based on levels and probabilities"""
    global current_vix
    
    # Determine which level to gravitate towards
    levels = [10, 25.75, 75, 100, 150]
    probabilities = [0.15, 0.4, 0.2, 0.15, 0.1]
    
    target_level = random.choices(levels, weights=probabilities)[0]
    
    # Move towards target level with some randomness
    if current_vix < target_level:
        change = random.uniform(0.05, 0.5)
    elif current_vix > target_level:
        change = random.uniform(-0.5, -0.05)
    else:
        change = random.uniform(-0.2, 0.2)
    
    # Add some random volatility
    volatility = random.uniform(-0.3, 0.3)
    current_vix += change + volatility
    
    # Ensure VIX stays within reasonable bounds
    current_vix = max(8, min(200, current_vix))
    
    return round(current_vix, 2)

def send_to_firebase(path, data):
    """Send data to Firebase Realtime Database"""
    try:
        url = f"{FIREBASE_URL}/{path}.json"
        response = requests.put(url, json=data, timeout=5)
        return response.status_code == 200
    except Exception as e:
        print(f"Firebase error: {e}")
        return False

def generate_tick():
    """Generate a single tick and store it"""
    global last_update
    
    price = generate_vix_price()
    timestamp = datetime.now()
    
    # Add tick to data manager
    data_manager.add_tick(price, timestamp)
    
    # Send to Firebase
    firebase_data = {
        'live_ticks': data_manager.live_ticks[-100:],  # Send last 100 ticks
        'candles_1min': data_manager.candles_1min[-50:],  # Send last 50 candles
        'candles_5min': data_manager.candles_5min[-50:],  # Send last 50 candles
        'last_update': timestamp.isoformat(),
        'current_price': price
    }
    
    send_to_firebase('vix_data', firebase_data)
    last_update = timestamp
    
    print(f"VIX Tick: {price} at {timestamp.strftime('%H:%M:%S')}")

def continuous_tick_generation():
    """Generate ticks continuously"""
    while True:
        generate_tick()
        
        # Variable intervals based on VIX level
        if current_vix >= 75:
            time.sleep(1)  # 1 second intervals for high VIX
        elif current_vix >= 50:
            time.sleep(2)  # 2 second intervals for medium-high VIX
        else:
            time.sleep(5)  # 5 second intervals for normal VIX

@app.route('/')
def index():
    """Serve the main HTML page"""
    return render_template('index.html')

@app.route('/api/data')
def get_data():
    """API endpoint to get current data"""
    return jsonify({
        'live_ticks': data_manager.live_ticks[-100:],
        'candles_1min': data_manager.candles_1min[-50:],
        'candles_5min': data_manager.candles_5min[-50:],
        'current_price': current_vix,
        'last_update': last_update.isoformat(),
        'total_ticks': len(data_manager.live_ticks),
        'total_1min_candles': len(data_manager.candles_1min),
        'total_5min_candles': len(data_manager.candles_5min)
    })

@app.route('/api/firebase-sync')
def sync_firebase():
    """Manually sync all data to Firebase"""
    try:
        firebase_data = {
            'live_ticks': data_manager.live_ticks,
            'candles_1min': data_manager.candles_1min,
            'candles_5min': data_manager.candles_5min,
            'last_update': datetime.now().isoformat(),
            'current_price': current_vix,
            'data_counts': {
                'ticks': len(data_manager.live_ticks),
                'candles_1min': len(data_manager.candles_1min),
                'candles_5min': len(data_manager.candles_5min)
            }
        }
        
        success = send_to_firebase('vix_data', firebase_data)
        
        return jsonify({
            'success': success,
            'synced_at': datetime.now().isoformat(),
            'data_counts': firebase_data['data_counts']
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    # Start tick generation in background thread
    tick_thread = threading.Thread(target=continuous_tick_generation)
    tick_thread.daemon = True
    tick_thread.start()
    
    # Generate some initial data
    for _ in range(10):
        generate_tick()
        time.sleep(1)
    
    print("VIX Live Data Server starting...")
    print(f"Firebase URL: {FIREBASE_URL}")
    print("Generating live VIX data with the following characteristics:")
    print("- Live ticks with variable intervals")
    print("- 1-minute and 5-minute candles")
    print("- Maximum 900 data points per timeframe")
    print("- VIX levels: 10, 25.75, 75, 100, 150")
    
    app.run(host='0.0.0.0', port=5000, debug=False)