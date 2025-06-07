import json
import time
import asyncio
import websockets
import threading
from datetime import datetime, timedelta
from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
import requests
from collections import defaultdict, deque

app = Flask(__name__)
CORS(app)

# Firebase Realtime Database URL
FIREBASE_URL = "https://vix25-486b9-default-rtdb.firebaseio.com"

# Deriv WebSocket URL
DERIV_WS_URL = "wss://ws.binaryws.com/websockets/v3"

# Volatility indices configuration
VOLATILITY_INDICES = {
    'R_10': {'name': 'Volatility 10 Index', 'symbol': 'R_10'},
    'R_25': {'name': 'Volatility 25 Index', 'symbol': 'R_25'},
    'R_75': {'name': 'Volatility 75 Index', 'symbol': 'R_75'},
    'R_100': {'name': 'Volatility 100 Index', 'symbol': 'R_100'},
    '1HZ10V': {'name': 'Volatility 10(1s)', 'symbol': '1HZ10V'},
    '1HZ75V': {'name': 'Volatility 75(1s)', 'symbol': '1HZ75V'},
    '1HZ100V': {'name': 'Volatility 100(1s)', 'symbol': '1HZ100V'},
    '1HZ150V': {'name': 'Volatility 150(1s)', 'symbol': '1HZ150V'}
}

# Data storage limits
MAX_DATA_POINTS = 900

class VolatilityDataManager:
    def __init__(self):
        self.live_ticks = defaultdict(lambda: deque(maxlen=MAX_DATA_POINTS))
        self.candles_1min = defaultdict(lambda: deque(maxlen=MAX_DATA_POINTS))
        self.candles_5min = defaultdict(lambda: deque(maxlen=MAX_DATA_POINTS))
        self.current_prices = {}
        self.last_updates = {}
        self.websocket_connection = None
        self.subscribed_symbols = set()
        
    def add_tick(self, symbol, price, timestamp):
        """Add a new tick for a specific symbol"""
        tick_data = {
            'price': float(price),
            'timestamp': timestamp,
            'symbol': symbol
        }
        
        self.live_ticks[symbol].append(tick_data)
        self.current_prices[symbol] = float(price)
        self.last_updates[symbol] = timestamp
        
        # Update candles
        self.update_candles(symbol, float(price), datetime.fromisoformat(timestamp.replace('Z', '+00:00')))
        
    def update_candles(self, symbol, price, timestamp):
        """Update 1min and 5min candles for a symbol"""
        self.update_1min_candle(symbol, price, timestamp)
        self.update_5min_candle(symbol, price, timestamp)
        
    def update_1min_candle(self, symbol, price, timestamp):
        """Update 1-minute candles"""
        minute_key = timestamp.replace(second=0, microsecond=0)
        minute_key_iso = minute_key.isoformat()
        
        # Find existing candle or create new one
        candles = list(self.candles_1min[symbol])
        current_candle = None
        
        for i, candle in enumerate(candles):
            if candle['timestamp'] == minute_key_iso:
                current_candle = candle
                break
                
        if current_candle is None:
            current_candle = {
                'timestamp': minute_key_iso,
                'open': price,
                'high': price,
                'low': price,
                'close': price,
                'volume': 1,
                'symbol': symbol
            }
            self.candles_1min[symbol].append(current_candle)
        else:
            # Update existing candle
            current_candle['high'] = max(current_candle['high'], price)
            current_candle['low'] = min(current_candle['low'], price)
            current_candle['close'] = price
            current_candle['volume'] += 1
            
    def update_5min_candle(self, symbol, price, timestamp):
        """Update 5-minute candles"""
        # Round to 5-minute intervals
        minute = timestamp.minute - (timestamp.minute % 5)
        five_min_key = timestamp.replace(minute=minute, second=0, microsecond=0)
        five_min_key_iso = five_min_key.isoformat()
        
        # Find existing candle or create new one
        candles = list(self.candles_5min[symbol])
        current_candle = None
        
        for candle in candles:
            if candle['timestamp'] == five_min_key_iso:
                current_candle = candle
                break
                
        if current_candle is None:
            current_candle = {
                'timestamp': five_min_key_iso,
                'open': price,
                'high': price,
                'low': price,
                'close': price,
                'volume': 1,
                'symbol': symbol
            }
            self.candles_5min[symbol].append(current_candle)
        else:
            # Update existing candle
            current_candle['high'] = max(current_candle['high'], price)
            current_candle['low'] = min(current_candle['low'], price)
            current_candle['close'] = price
            current_candle['volume'] += 1

    def get_symbol_data(self, symbol):
        """Get all data for a specific symbol"""
        return {
            'live_ticks': list(self.live_ticks[symbol])[-100:],  # Last 100 ticks
            'candles_1min': list(self.candles_1min[symbol])[-50:],  # Last 50 candles
            'candles_5min': list(self.candles_5min[symbol])[-50:],  # Last 50 candles
            'current_price': self.current_prices.get(symbol, 0),
            'last_update': self.last_updates.get(symbol, ''),
            'total_ticks': len(self.live_ticks[symbol]),
            'total_1min_candles': len(self.candles_1min[symbol]),
            'total_5min_candles': len(self.candles_5min[symbol])
        }

# Initialize data manager
data_manager = VolatilityDataManager()

class DerivWebSocketClient:
    def __init__(self, data_manager):
        self.data_manager = data_manager
        self.websocket = None
        self.running = False
        
    async def connect(self):
        """Connect to Deriv WebSocket"""
        try:
            self.websocket = await websockets.connect(DERIV_WS_URL)
            self.running = True
            print("Connected to Deriv WebSocket")
            
            # Subscribe to all volatility indices
            for symbol_key, config in VOLATILITY_INDICES.items():
                await self.subscribe_to_ticks(config['symbol'])
                
            # Listen for messages
            await self.listen_for_messages()
            
        except Exception as e:
            print(f"WebSocket connection error: {e}")
            self.running = False
            
    async def subscribe_to_ticks(self, symbol):
        """Subscribe to tick stream for a symbol"""
        try:
            subscribe_message = {
                "ticks": symbol,
                "subscribe": 1
            }
            
            await self.websocket.send(json.dumps(subscribe_message))
            self.data_manager.subscribed_symbols.add(symbol)
            print(f"Subscribed to {symbol}")
            
        except Exception as e:
            print(f"Error subscribing to {symbol}: {e}")
            
    async def listen_for_messages(self):
        """Listen for incoming WebSocket messages"""
        try:
            while self.running:
                message = await self.websocket.recv()
                data = json.loads(message)
                
                # Handle tick data
                if 'tick' in data:
                    tick_data = data['tick']
                    symbol = tick_data['symbol']
                    price = tick_data['quote']
                    timestamp = datetime.fromtimestamp(tick_data['epoch']).isoformat()
                    
                    # Add tick to data manager
                    self.data_manager.add_tick(symbol, price, timestamp)
                    
                    print(f"Received tick for {symbol}: {price} at {timestamp}")
                    
                # Handle subscription confirmation
                elif 'subscription' in data:
                    print(f"Subscription confirmed: {data['subscription']}")
                    
        except websockets.exceptions.ConnectionClosed:
            print("WebSocket connection closed")
            self.running = False
        except Exception as e:
            print(f"Error listening for messages: {e}")
            self.running = False
            
    async def disconnect(self):
        """Disconnect from WebSocket"""
        self.running = False
        if self.websocket:
            await self.websocket.close()

# WebSocket client instance
ws_client = DerivWebSocketClient(data_manager)

def send_to_firebase(path, data):
    """Send data to Firebase Realtime Database"""
    try:
        url = f"{FIREBASE_URL}/{path}.json"
        response = requests.put(url, json=data, timeout=10)
        return response.status_code == 200
    except Exception as e:
        print(f"Firebase error: {e}")
        return False

def sync_to_firebase():
    """Sync all data to Firebase"""
    try:
        firebase_data = {}
        
        for symbol_key, config in VOLATILITY_INDICES.items():
            symbol = config['symbol']
            if symbol in data_manager.subscribed_symbols:
                firebase_data[symbol] = data_manager.get_symbol_data(symbol)
                
        firebase_data['last_sync'] = datetime.now().isoformat()
        firebase_data['subscribed_symbols'] = list(data_manager.subscribed_symbols)
        
        success = send_to_firebase('volatility_data', firebase_data)
        if success:
            print("Data synced to Firebase successfully")
        else:
            print("Failed to sync data to Firebase")
            
    except Exception as e:
        print(f"Firebase sync error: {e}")

def start_websocket_client():
    """Start WebSocket client in background"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    async def run_client():
        while True:
            try:
                await ws_client.connect()
            except Exception as e:
                print(f"WebSocket client error: {e}")
                await asyncio.sleep(5)  # Wait before reconnecting
                
    loop.run_until_complete(run_client())

def periodic_firebase_sync():
    """Periodically sync data to Firebase"""
    while True:
        time.sleep(30)  # Sync every 30 seconds
        sync_to_firebase()

@app.route('/')
def index():
    """Serve the main HTML page"""
    return render_template('index.html')

@app.route('/api/indices')
def get_indices():
    """Get list of available volatility indices"""
    return jsonify({
        'indices': VOLATILITY_INDICES,
        'subscribed_symbols': list(data_manager.subscribed_symbols)
    })

@app.route('/api/data/<symbol>')
def get_symbol_data(symbol):
    """Get data for a specific symbol"""
    if symbol not in VOLATILITY_INDICES:
        return jsonify({'error': 'Symbol not found'}), 404
        
    symbol_code = VOLATILITY_INDICES[symbol]['symbol']
    return jsonify(data_manager.get_symbol_data(symbol_code))

@app.route('/api/data')
def get_all_data():
    """Get data for all symbols"""
    all_data = {}
    for symbol_key, config in VOLATILITY_INDICES.items():
        symbol = config['symbol']
        if symbol in data_manager.subscribed_symbols:
            all_data[symbol_key] = data_manager.get_symbol_data(symbol)
            
    return jsonify({
        'data': all_data,
        'subscribed_symbols': list(data_manager.subscribed_symbols),
        'last_sync': datetime.now().isoformat()
    })

@app.route('/api/firebase-sync')
def manual_firebase_sync():
    """Manually trigger Firebase sync"""
    try:
        sync_to_firebase()
        return jsonify({
            'success': True,
            'synced_at': datetime.now().isoformat(),
            'subscribed_symbols': list(data_manager.subscribed_symbols)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    print("Starting Volatility Indices Live Data Server...")
    print(f"Firebase URL: {FIREBASE_URL}")
    print(f"Deriv WebSocket URL: {DERIV_WS_URL}")
    print("Available indices:")
    for key, config in VOLATILITY_INDICES.items():
        print(f"  - {key}: {config['name']} ({config['symbol']})")
    
    # Start WebSocket client in background thread
    ws_thread = threading.Thread(target=start_websocket_client)
    ws_thread.daemon = True
    ws_thread.start()
    
    # Start Firebase sync thread
    sync_thread = threading.Thread(target=periodic_firebase_sync)
    sync_thread.daemon = True
    sync_thread.start()
    
    # Give some time for initial connections
    time.sleep(5)
    
    app.run(host='0.0.0.0', port=5000, debug=False)
