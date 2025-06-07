import json
import time
import asyncio
import threading
from datetime import datetime, timedelta
from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
import requests
import websocket
import rel

app = Flask(__name__)
CORS(app)

# Firebase Realtime Database URL
FIREBASE_URL = "https://vix25-486b9-default-rtdb.firebaseio.com"

# Deriv WebSocket URL
DERIV_WS_URL = "wss://ws.derivws.com/websockets/v3?app_id=1089"

# Deriv Volatility Indices
VOLATILITY_INDICES = {
    'R_10': {'name': 'Volatility 10 Index', 'symbol': 'R_10'},
    'R_25': {'name': 'Volatility 25 Index', 'symbol': 'R_25'},
    'R_75': {'name': 'Volatility 75 Index', 'symbol': 'R_75'},
    'R_100': {'name': 'Volatility 100 Index', 'symbol': 'R_100'},
    '1HZ10V': {'name': 'Volatility 10 (1s)', 'symbol': '1HZ10V'},
    '1HZ75V': {'name': 'Volatility 75 (1s)', 'symbol': '1HZ75V'},
    '1HZ100V': {'name': 'Volatility 100 (1s)', 'symbol': '1HZ100V'},
    '1HZ150V': {'name': 'Volatility 150 (1s)', 'symbol': '1HZ150V'}
}

# Data storage limits
MAX_DATA_POINTS = 900

class VolatilityDataManager:
    def __init__(self):
        self.data = {}
        self.websocket_connections = {}
        self.active_subscriptions = set()
        
        # Initialize data storage for each index
        for symbol in VOLATILITY_INDICES:
            self.data[symbol] = {
                'live_ticks': [],
                'candles_1min': [],
                'candles_5min': [],
                'current_price': 0,
                'last_update': None
            }
    
    def add_tick(self, symbol, price, timestamp):
        """Add a new tick for a specific symbol"""
        if symbol not in self.data:
            return
            
        tick_data = {
            'price': float(price),
            'timestamp': timestamp,
            'epoch': int(time.time())
        }
        
        self.data[symbol]['live_ticks'].append(tick_data)
        self.data[symbol]['current_price'] = float(price)
        self.data[symbol]['last_update'] = timestamp
        
        # Limit live ticks to MAX_DATA_POINTS
        if len(self.data[symbol]['live_ticks']) > MAX_DATA_POINTS:
            self.data[symbol]['live_ticks'] = self.data[symbol]['live_ticks'][-MAX_DATA_POINTS:]
            
        # Update candles
        self.update_candles(symbol, float(price), datetime.fromisoformat(timestamp.replace('Z', '+00:00')))
        
        print(f"{symbol}: {price} at {timestamp}")
        
    def update_candles(self, symbol, price, timestamp):
        """Update 1min and 5min candles for a symbol"""
        self.update_1min_candle(symbol, price, timestamp)
        self.update_5min_candle(symbol, price, timestamp)
        
    def update_1min_candle(self, symbol, price, timestamp):
        """Update 1-minute candles"""
        minute_key = timestamp.replace(second=0, microsecond=0)
        
        # Find existing candle or create new one
        current_candle = None
        for candle in self.data[symbol]['candles_1min']:
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
                'volume': 1
            }
            self.data[symbol]['candles_1min'].append(current_candle)
        else:
            # Update existing candle
            current_candle['high'] = max(current_candle['high'], price)
            current_candle['low'] = min(current_candle['low'], price)
            current_candle['close'] = price
            current_candle['volume'] += 1
            
        # Limit to MAX_DATA_POINTS candles
        if len(self.data[symbol]['candles_1min']) > MAX_DATA_POINTS:
            self.data[symbol]['candles_1min'] = self.data[symbol]['candles_1min'][-MAX_DATA_POINTS:]
            
    def update_5min_candle(self, symbol, price, timestamp):
        """Update 5-minute candles"""
        # Round to 5-minute intervals
        minute = timestamp.minute - (timestamp.minute % 5)
        five_min_key = timestamp.replace(minute=minute, second=0, microsecond=0)
        
        # Find existing candle or create new one
        current_candle = None
        for candle in self.data[symbol]['candles_5min']:
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
                'volume': 1
            }
            self.data[symbol]['candles_5min'].append(current_candle)
        else:
            # Update existing candle
            current_candle['high'] = max(current_candle['high'], price)
            current_candle['low'] = min(current_candle['low'], price)
            current_candle['close'] = price
            current_candle['volume'] += 1
            
        # Limit to MAX_DATA_POINTS candles
        if len(self.data[symbol]['candles_5min']) > MAX_DATA_POINTS:
            self.data[symbol]['candles_5min'] = self.data[symbol]['candles_5min'][-MAX_DATA_POINTS:]

    def get_symbol_data(self, symbol):
        """Get data for a specific symbol"""
        if symbol not in self.data:
            return None
            
        return {
            'symbol': symbol,
            'name': VOLATILITY_INDICES.get(symbol, {}).get('name', symbol),
            'live_ticks': self.data[symbol]['live_ticks'][-100:],  # Last 100 ticks
            'candles_1min': self.data[symbol]['candles_1min'][-50:],  # Last 50 candles
            'candles_5min': self.data[symbol]['candles_5min'][-50:],  # Last 50 candles
            'current_price': self.data[symbol]['current_price'],
            'last_update': self.data[symbol]['last_update'],
            'total_ticks': len(self.data[symbol]['live_ticks']),
            'total_1min_candles': len(self.data[symbol]['candles_1min']),
            'total_5min_candles': len(self.data[symbol]['candles_5min'])
        }

# Initialize data manager
data_manager = VolatilityDataManager()

class DerivWebSocket:
    def __init__(self):
        self.ws = None
        self.connected = False
        
    def on_open(self, ws):
        """WebSocket connection opened"""
        print("Deriv WebSocket connected")
        self.connected = True
        
        # Subscribe to all volatility indices
        for symbol in VOLATILITY_INDICES:
            self.subscribe_to_ticks(symbol)
            
    def on_message(self, ws, message):
        """Handle incoming WebSocket messages"""
        try:
            data = json.loads(message)
            
            # Handle tick data
            if 'tick' in data:
                tick_data = data['tick']
                symbol = tick_data.get('symbol')
                price = tick_data.get('quote')
                timestamp = tick_data.get('timestamp')
                
                if symbol and price and timestamp:
                    # Convert timestamp to ISO format
                    dt = datetime.fromtimestamp(timestamp)
                    iso_timestamp = dt.isoformat()
                    
                    # Add tick to data manager
                    data_manager.add_tick(symbol, price, iso_timestamp)
                    
                    # Send to Firebase periodically
                    if int(timestamp) % 10 == 0:  # Every 10 seconds
                        self.sync_to_firebase(symbol)
                        
        except json.JSONDecodeError:
            print(f"Invalid JSON received: {message}")
        except Exception as e:
            print(f"Error processing message: {e}")
            
    def on_error(self, ws, error):
        """Handle WebSocket errors"""
        print(f"Deriv WebSocket error: {error}")
        self.connected = False
        
    def on_close(self, ws, close_status_code, close_msg):
        """Handle WebSocket close"""
        print("Deriv WebSocket connection closed")
        self.connected = False
        
    def subscribe_to_ticks(self, symbol):
        """Subscribe to tick data for a symbol"""
        if self.ws and self.connected:
            subscribe_message = {
                "ticks": symbol,
                "subscribe": 1
            }
            self.ws.send(json.dumps(subscribe_message))
            print(f"Subscribed to {symbol}")
            
    def sync_to_firebase(self, symbol):
        """Sync symbol data to Firebase"""
        try:
            symbol_data = data_manager.get_symbol_data(symbol)
            if symbol_data:
                firebase_data = {
                    f'{symbol}_data': symbol_data,
                    'last_sync': datetime.now().isoformat()
                }
                send_to_firebase(f'volatility_indices/{symbol}', symbol_data)
        except Exception as e:
            print(f"Firebase sync error for {symbol}: {e}")
            
    def connect(self):
        """Connect to Deriv WebSocket"""
        try:
            self.ws = websocket.WebSocketApp(
                DERIV_WS_URL,
                on_open=self.on_open,
                on_message=self.on_message,
                on_error=self.on_error,
                on_close=self.on_close
            )
            
            # Run WebSocket in a separate thread
            def run_websocket():
                self.ws.run_forever(dispatcher=rel, reconnect=5)
                rel.signal(2, rel.abort)
                rel.dispatch()
                
            ws_thread = threading.Thread(target=run_websocket)
            ws_thread.daemon = True
            ws_thread.start()
            
        except Exception as e:
            print(f"WebSocket connection error: {e}")

# Initialize WebSocket connection
deriv_ws = DerivWebSocket()

def send_to_firebase(path, data):
    """Send data to Firebase Realtime Database"""
    try:
        url = f"{FIREBASE_URL}/{path}.json"
        response = requests.put(url, json=data, timeout=5)
        return response.status_code == 200
    except Exception as e:
        print(f"Firebase error: {e}")
        return False

@app.route('/')
def index():
    """Serve the main HTML page"""
    return render_template('index.html')

@app.route('/api/indices')
def get_indices():
    """Get list of available volatility indices"""
    return jsonify({
        'indices': [
            {
                'symbol': symbol,
                'name': info['name'],
                'has_data': len(data_manager.data[symbol]['live_ticks']) > 0
            }
            for symbol, info in VOLATILITY_INDICES.items()
        ]
    })

@app.route('/api/data/<symbol>')
def get_symbol_data(symbol):
    """Get data for a specific symbol"""
    if symbol not in VOLATILITY_INDICES:
        return jsonify({'error': 'Invalid symbol'}), 400
        
    symbol_data = data_manager.get_symbol_data(symbol)
    if symbol_data is None:
        return jsonify({'error': 'No data available'}), 404
        
    return jsonify(symbol_data)

@app.route('/api/data')
def get_all_data():
    """Get data for all symbols"""
    all_data = {}
    for symbol in VOLATILITY_INDICES:
        all_data[symbol] = data_manager.get_symbol_data(symbol)
    
    return jsonify({
        'indices': all_data,
        'websocket_connected': deriv_ws.connected,
        'last_sync': datetime.now().isoformat()
    })

@app.route('/api/firebase-sync/<symbol>')
def sync_symbol_firebase(symbol):
    """Manually sync specific symbol to Firebase"""
    if symbol not in VOLATILITY_INDICES:
        return jsonify({'error': 'Invalid symbol'}), 400
        
    try:
        symbol_data = data_manager.get_symbol_data(symbol)
        if symbol_data:
            success = send_to_firebase(f'volatility_indices/{symbol}', symbol_data)
            return jsonify({
                'success': success,
                'symbol': symbol,
                'synced_at': datetime.now().isoformat()
            })
        else:
            return jsonify({'error': 'No data to sync'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/firebase-sync-all')
def sync_all_firebase():
    """Manually sync all symbols to Firebase"""
    try:
        results = {}
        for symbol in VOLATILITY_INDICES:
            symbol_data = data_manager.get_symbol_data(symbol)
            if symbol_data:
                success = send_to_firebase(f'volatility_indices/{symbol}', symbol_data)
                results[symbol] = success
                
        return jsonify({
            'results': results,
            'synced_at': datetime.now().isoformat(),
            'total_synced': sum(results.values())
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/websocket-status')
def websocket_status():
    """Get WebSocket connection status"""
    return jsonify({
        'connected': deriv_ws.connected,
        'active_subscriptions': len(VOLATILITY_INDICES),
        'indices': list(VOLATILITY_INDICES.keys())
    })

if __name__ == '__main__':
    print("Starting Deriv Volatility Indices Data Server...")
    print(f"Firebase URL: {FIREBASE_URL}")
    print(f"Deriv WebSocket URL: {DERIV_WS_URL}")
    print("Available Indices:")
    for symbol, info in VOLATILITY_INDICES.items():
        print(f"  - {symbol}: {info['name']}")
    
    # Connect to Deriv WebSocket
    deriv_ws.connect()
    
    # Wait a moment for WebSocket to connect
    time.sleep(2)
    
    print("Server starting on port 5000...")
    app.run(host='0.0.0.0', port=5000, debug=False)
