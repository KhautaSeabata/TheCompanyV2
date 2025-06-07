import json
import time
import asyncio
import threading
from datetime import datetime, timedelta
from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
import requests
import websocket
import logging

app = Flask(__name__)
CORS(app)

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Firebase Realtime Database URL
FIREBASE_URL = "https://vix25-486b9-default-rtdb.firebaseio.com"

# Deriv WebSocket URL
DERIV_WS_URL = "wss://ws.derivws.com/websockets/v3?app_id=1089"

# Focus on Volatility 150 (1s) only
VOLATILITY_SYMBOL = '1HZ150V'
VOLATILITY_NAME = 'Volatility 150 (1s)'

# Data storage limits
MAX_DATA_POINTS = 900

class VolatilityDataManager:
    def __init__(self):
        self.data = {
            'live_ticks': [],
            'candles_1min': [],
            'candles_5min': [],
            'current_price': 0,
            'last_update': None
        }
        
    def add_tick(self, price, timestamp):
        """Add a new tick"""
        tick_data = {
            'price': float(price),
            'timestamp': timestamp,
            'epoch': int(time.time())
        }
        
        self.data['live_ticks'].append(tick_data)
        self.data['current_price'] = float(price)
        self.data['last_update'] = timestamp
        
        # Prune to keep only MAX_DATA_POINTS
        if len(self.data['live_ticks']) > MAX_DATA_POINTS:
            self.data['live_ticks'] = self.data['live_ticks'][-MAX_DATA_POINTS:]
            
        # Update candles
        self.update_candles(float(price), datetime.fromisoformat(timestamp.replace('Z', '+00:00')))
        
        logger.info(f"{VOLATILITY_SYMBOL}: {price} at {timestamp}")
        
    def update_candles(self, price, timestamp):
        """Update 1min and 5min candles"""
        self.update_1min_candle(price, timestamp)
        self.update_5min_candle(price, timestamp)
        
    def update_1min_candle(self, price, timestamp):
        """Update 1-minute candles"""
        minute_key = timestamp.replace(second=0, microsecond=0)
        
        # Find existing candle or create new one
        current_candle = None
        for i, candle in enumerate(self.data['candles_1min']):
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
            self.data['candles_1min'].append(current_candle)
        else:
            # Update existing candle
            current_candle['high'] = max(current_candle['high'], price)
            current_candle['low'] = min(current_candle['low'], price)
            current_candle['close'] = price
            current_candle['volume'] += 1
            
        # Prune to keep only MAX_DATA_POINTS candles
        if len(self.data['candles_1min']) > MAX_DATA_POINTS:
            self.data['candles_1min'] = self.data['candles_1min'][-MAX_DATA_POINTS:]
            
    def update_5min_candle(self, price, timestamp):
        """Update 5-minute candles"""
        # Round to 5-minute intervals
        minute = timestamp.minute - (timestamp.minute % 5)
        five_min_key = timestamp.replace(minute=minute, second=0, microsecond=0)
        
        # Find existing candle or create new one
        current_candle = None
        for i, candle in enumerate(self.data['candles_5min']):
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
            self.data['candles_5min'].append(current_candle)
        else:
            # Update existing candle
            current_candle['high'] = max(current_candle['high'], price)
            current_candle['low'] = min(current_candle['low'], price)
            current_candle['close'] = price
            current_candle['volume'] += 1
            
        # Prune to keep only MAX_DATA_POINTS candles
        if len(self.data['candles_5min']) > MAX_DATA_POINTS:
            self.data['candles_5min'] = self.data['candles_5min'][-MAX_DATA_POINTS:]

    def get_data(self):
        """Get all data"""
        return {
            'symbol': VOLATILITY_SYMBOL,
            'name': VOLATILITY_NAME,
            'live_ticks': self.data['live_ticks'][-100:],  # Last 100 ticks for display
            'candles_1min': self.data['candles_1min'][-50:],  # Last 50 candles for display
            'candles_5min': self.data['candles_5min'][-50:],  # Last 50 candles for display
            'current_price': self.data['current_price'],
            'last_update': self.data['last_update'],
            'total_ticks': len(self.data['live_ticks']),
            'total_1min_candles': len(self.data['candles_1min']),
            'total_5min_candles': len(self.data['candles_5min'])
        }

    def sync_to_firebase(self):
        """Sync data to Firebase with pruning"""
        try:
            # Prepare data for Firebase with pruning
            firebase_data = {
                'live_ticks': self.data['live_ticks'][-MAX_DATA_POINTS:],
                'candles_1min': self.data['candles_1min'][-MAX_DATA_POINTS:],
                'candles_5min': self.data['candles_5min'][-MAX_DATA_POINTS:],
                'current_price': self.data['current_price'],
                'last_update': self.data['last_update'],
                'updated_at': datetime.now().isoformat()
            }
            
            # Send to Firebase
            url = f"{FIREBASE_URL}/volatility_150.json"
            response = requests.put(url, json=firebase_data, timeout=10)
            
            if response.status_code == 200:
                logger.info("Firebase sync successful")
                return True
            else:
                logger.error(f"Firebase sync failed: {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"Firebase sync error: {e}")
            return False

# Initialize data manager
data_manager = VolatilityDataManager()

class DerivWebSocket:
    def __init__(self):
        self.ws = None
        self.connected = False
        self.connection_thread = None
        self.should_reconnect = True
        self.reconnect_delay = 5
        self.max_reconnect_delay = 60
        self.sync_counter = 0
        
    def on_open(self, ws):
        """WebSocket connection opened"""
        logger.info("Deriv WebSocket connected successfully")
        self.connected = True
        self.reconnect_delay = 5  # Reset reconnect delay on successful connection
        
        # Subscribe to Volatility 150 (1s)
        self.subscribe_to_ticks()
            
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
                
                if symbol == VOLATILITY_SYMBOL and price and timestamp:
                    # Convert timestamp to ISO format
                    dt = datetime.fromtimestamp(timestamp)
                    iso_timestamp = dt.isoformat()
                    
                    # Add tick to data manager
                    data_manager.add_tick(price, iso_timestamp)
                    
                    # Sync to Firebase every 10 ticks to reduce load
                    self.sync_counter += 1
                    if self.sync_counter >= 10:
                        self.sync_counter = 0
                        threading.Thread(target=data_manager.sync_to_firebase, daemon=True).start()
            
            # Handle subscription confirmation
            elif 'subscription' in data:
                logger.info(f"Subscription confirmed: {data}")
                
            # Handle ping/pong
            elif 'ping' in data:
                self.send_pong()
                
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON received: {message}")
        except Exception as e:
            logger.error(f"Error processing message: {e}")
            
    def on_error(self, ws, error):
        """Handle WebSocket errors"""
        logger.error(f"Deriv WebSocket error: {error}")
        self.connected = False
        
    def on_close(self, ws, close_status_code, close_msg):
        """Handle WebSocket close"""
        logger.warning(f"Deriv WebSocket connection closed: {close_status_code} - {close_msg}")
        self.connected = False
        
        # Attempt to reconnect if should_reconnect is True
        if self.should_reconnect:
            logger.info(f"Attempting to reconnect in {self.reconnect_delay} seconds...")
            time.sleep(self.reconnect_delay)
            
            # Exponential backoff for reconnection attempts
            self.reconnect_delay = min(self.reconnect_delay * 2, self.max_reconnect_delay)
            
            # Reconnect in a separate thread to avoid blocking
            threading.Thread(target=self.connect, daemon=True).start()
            
    def subscribe_to_ticks(self):
        """Subscribe to tick data for Volatility 150 (1s)"""
        if self.ws and self.connected:
            try:
                subscribe_message = {
                    "ticks": VOLATILITY_SYMBOL,
                    "subscribe": 1
                }
                self.ws.send(json.dumps(subscribe_message))
                logger.info(f"Subscribed to {VOLATILITY_SYMBOL}")
            except Exception as e:
                logger.error(f"Error subscribing to {VOLATILITY_SYMBOL}: {e}")
    
    def send_pong(self):
        """Send pong response to ping"""
        if self.ws and self.connected:
            try:
                pong_message = {"pong": 1}
                self.ws.send(json.dumps(pong_message))
            except Exception as e:
                logger.error(f"Error sending pong: {e}")
                
    def connect(self):
        """Connect to Deriv WebSocket"""
        try:
            logger.info(f"Connecting to Deriv WebSocket: {DERIV_WS_URL}")
            
            # Close existing connection if any
            if self.ws:
                self.ws.close()
                
            self.ws = websocket.WebSocketApp(
                DERIV_WS_URL,
                on_open=self.on_open,
                on_message=self.on_message,
                on_error=self.on_error,
                on_close=self.on_close
            )
            
            # Run WebSocket connection
            self.ws.run_forever(
                ping_interval=30,  # Send ping every 30 seconds
                ping_timeout=10    # Wait 10 seconds for pong response
            )
            
        except Exception as e:
            logger.error(f"WebSocket connection error: {e}")
            self.connected = False
            
            # Attempt to reconnect after delay
            if self.should_reconnect:
                time.sleep(self.reconnect_delay)
                threading.Thread(target=self.connect, daemon=True).start()
    
    def start_connection(self):
        """Start WebSocket connection in a separate thread"""
        if self.connection_thread is None or not self.connection_thread.is_alive():
            self.connection_thread = threading.Thread(target=self.connect, daemon=True)
            self.connection_thread.start()
            logger.info("WebSocket connection thread started")
    
    def stop_connection(self):
        """Stop WebSocket connection"""
        self.should_reconnect = False
        if self.ws:
            self.ws.close()
        self.connected = False
        logger.info("WebSocket connection stopped")

# Initialize WebSocket connection
deriv_ws = DerivWebSocket()

@app.route('/')
def index():
    """Serve the main HTML page"""
    return render_template('index.html')

@app.route('/api/data')
def get_data():
    """Get current data from memory"""
    return jsonify(data_manager.get_data())

@app.route('/api/firebase-data')
def get_firebase_data():
    """Get data from Firebase"""
    try:
        url = f"{FIREBASE_URL}/volatility_150.json"
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            firebase_data = response.json()
            if firebase_data:
                return jsonify({
                    'symbol': VOLATILITY_SYMBOL,
                    'name': VOLATILITY_NAME,
                    'live_ticks': firebase_data.get('live_ticks', [])[-100:],
                    'candles_1min': firebase_data.get('candles_1min', [])[-50:],
                    'candles_5min': firebase_data.get('candles_5min', [])[-50:],
                    'current_price': firebase_data.get('current_price', 0),
                    'last_update': firebase_data.get('last_update'),
                    'total_ticks': len(firebase_data.get('live_ticks', [])),
                    'total_1min_candles': len(firebase_data.get('candles_1min', [])),
                    'total_5min_candles': len(firebase_data.get('candles_5min', [])),
                    'source': 'firebase'
                })
            else:
                return jsonify({'error': 'No data in Firebase'}), 404
        else:
            return jsonify({'error': 'Firebase request failed'}), 500
            
    except Exception as e:
        logger.error(f"Firebase fetch error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/firebase-sync')
def sync_firebase():
    """Manually sync to Firebase"""
    try:
        success = data_manager.sync_to_firebase()
        return jsonify({
            'success': success,
            'synced_at': datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/websocket-status')
def websocket_status():
    """Get WebSocket connection status"""
    return jsonify({
        'connected': deriv_ws.connected,
        'symbol': VOLATILITY_SYMBOL,
        'name': VOLATILITY_NAME,
        'connection_url': DERIV_WS_URL
    })

@app.route('/api/websocket-reconnect')
def websocket_reconnect():
    """Manually trigger WebSocket reconnection"""
    try:
        deriv_ws.stop_connection()
        time.sleep(2)
        deriv_ws.should_reconnect = True
        deriv_ws.start_connection()
        
        return jsonify({
            'success': True,
            'message': 'WebSocket reconnection initiated',
            'initiated_at': datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

if __name__ == '__main__':
    logger.info("Starting Volatility 150 (1s) Data Server...")
    logger.info(f"Firebase URL: {FIREBASE_URL}")
    logger.info(f"Deriv WebSocket URL: {DERIV_WS_URL}")
    logger.info(f"Tracking: {VOLATILITY_SYMBOL} - {VOLATILITY_NAME}")
    
    # Start WebSocket connection
    deriv_ws.start_connection()
    
    # Wait a moment for WebSocket to attempt connection
    time.sleep(3)
    
    logger.info("Server starting on port 5000...")
    app.run(host='0.0.0.0', port=5000, debug=False)
