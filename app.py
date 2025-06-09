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
from collections import defaultdict

app = Flask(__name__)
CORS(app)

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Firebase Realtime Database URL
FIREBASE_URL = "https://company-bdb78-default-rtdb.firebaseio.com"

# Deriv WebSocket URL
DERIV_WS_URL = "wss://ws.derivws.com/websockets/v3?app_id=1089"

# Focus on R_25 (Volatility 25) only
VOLATILITY_SYMBOL = 'R_25'
VOLATILITY_NAME = 'Volatility 25'

# Data storage limits - exactly 950 as requested
MAX_DATA_POINTS = 950

class EnhancedVolatilityDataManager:
    def __init__(self):
        self.data = {
            'live_ticks': [],
            'candles_1min': [],
            'candles_5min': [],
            'current_price': 0,
            'last_update': None
        }
        self.lock = threading.Lock()  # Thread safety
        self.last_firebase_sync = 0
        self.sync_interval = 10  # Sync every 10 seconds
        
    def add_tick(self, price, timestamp):
        """Add a new tick and update candlesticks"""
        with self.lock:
            try:
                tick_data = {
                    'price': float(price),
                    'timestamp': timestamp,
                    'epoch': int(time.time())
                }
                
                self.data['live_ticks'].append(tick_data)
                self.data['current_price'] = float(price)
                self.data['last_update'] = timestamp
                
                # Prune ticks to keep only MAX_DATA_POINTS (950)
                if len(self.data['live_ticks']) > MAX_DATA_POINTS:
                    self.data['live_ticks'] = self.data['live_ticks'][-MAX_DATA_POINTS:]
                
                # Convert timestamp to datetime for candle processing
                if timestamp.endswith('Z'):
                    dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                else:
                    dt = datetime.fromisoformat(timestamp)
                
                # Update candles
                self.update_candles(float(price), dt)
                
                logger.info(f"{VOLATILITY_SYMBOL}: {price} at {timestamp}")
                
                # Auto-sync to Firebase periodically
                current_time = time.time()
                if current_time - self.last_firebase_sync > self.sync_interval:
                    self.last_firebase_sync = current_time
                    threading.Thread(target=self.sync_to_firebase, daemon=True).start()
                    
            except Exception as e:
                logger.error(f"Error adding tick: {e}")
        
    def update_candles(self, price, timestamp):
        """Update both 1min and 5min candles"""
        self.update_1min_candle(price, timestamp)
        self.update_5min_candle(price, timestamp)
        
    def update_1min_candle(self, price, timestamp):
        """Update 1-minute OHLC candles"""
        try:
            # Round to 1-minute intervals
            minute_key = timestamp.replace(second=0, microsecond=0)
            minute_key_iso = minute_key.isoformat()
            
            # Find existing candle or create new one
            current_candle = None
            candle_index = -1
            
            for i, candle in enumerate(self.data['candles_1min']):
                if candle['timestamp'] == minute_key_iso:
                    current_candle = candle
                    candle_index = i
                    break
                    
            if current_candle is None:
                # Create new candle
                current_candle = {
                    'timestamp': minute_key_iso,
                    'open': price,
                    'high': price,
                    'low': price,
                    'close': price,
                    'volume': 1,
                    'tick_count': 1
                }
                self.data['candles_1min'].append(current_candle)
                
                # Sort candles by timestamp to maintain order
                self.data['candles_1min'].sort(key=lambda x: x['timestamp'])
            else:
                # Update existing candle
                current_candle['high'] = max(current_candle['high'], price)
                current_candle['low'] = min(current_candle['low'], price)
                current_candle['close'] = price
                current_candle['volume'] += 1
                current_candle['tick_count'] = current_candle.get('tick_count', 0) + 1
                
            # Prune to keep only MAX_DATA_POINTS (950) candles
            if len(self.data['candles_1min']) > MAX_DATA_POINTS:
                self.data['candles_1min'] = self.data['candles_1min'][-MAX_DATA_POINTS:]
                
        except Exception as e:
            logger.error(f"Error updating 1min candle: {e}")
            
    def update_5min_candle(self, price, timestamp):
        """Update 5-minute OHLC candles"""
        try:
            # Round to 5-minute intervals
            minute = timestamp.minute - (timestamp.minute % 5)
            five_min_key = timestamp.replace(minute=minute, second=0, microsecond=0)
            five_min_key_iso = five_min_key.isoformat()
            
            # Find existing candle or create new one
            current_candle = None
            candle_index = -1
            
            for i, candle in enumerate(self.data['candles_5min']):
                if candle['timestamp'] == five_min_key_iso:
                    current_candle = candle
                    candle_index = i
                    break
                    
            if current_candle is None:
                # Create new candle
                current_candle = {
                    'timestamp': five_min_key_iso,
                    'open': price,
                    'high': price,
                    'low': price,
                    'close': price,
                    'volume': 1,
                    'tick_count': 1
                }
                self.data['candles_5min'].append(current_candle)
                
                # Sort candles by timestamp to maintain order
                self.data['candles_5min'].sort(key=lambda x: x['timestamp'])
            else:
                # Update existing candle
                current_candle['high'] = max(current_candle['high'], price)
                current_candle['low'] = min(current_candle['low'], price)
                current_candle['close'] = price
                current_candle['volume'] += 1
                current_candle['tick_count'] = current_candle.get('tick_count', 0) + 1
                
            # Prune to keep only MAX_DATA_POINTS (950) candles
            if len(self.data['candles_5min']) > MAX_DATA_POINTS:
                self.data['candles_5min'] = self.data['candles_5min'][-MAX_DATA_POINTS:]
                
        except Exception as e:
            logger.error(f"Error updating 5min candle: {e}")

    def get_data(self):
        """Get all data with thread safety"""
        with self.lock:
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
        """Enhanced Firebase sync with better error handling and data structure"""
        try:
            with self.lock:
                # Prepare data for Firebase with pruning to exactly 950 items
                firebase_data = {
                    'metadata': {
                        'symbol': VOLATILITY_SYMBOL,
                        'name': VOLATILITY_NAME,
                        'current_price': self.data['current_price'],
                        'last_update': self.data['last_update'],
                        'updated_at': datetime.now().isoformat(),
                        'total_ticks': len(self.data['live_ticks']),
                        'total_1min_candles': len(self.data['candles_1min']),
                        'total_5min_candles': len(self.data['candles_5min'])
                    },
                    'ticks': self.data['live_ticks'][-MAX_DATA_POINTS:],
                    'candles_1min': self.data['candles_1min'][-MAX_DATA_POINTS:],
                    'candles_5min': self.data['candles_5min'][-MAX_DATA_POINTS:]
                }
            
            # Send to Firebase - store under r25_volatility node
            url = f"{FIREBASE_URL}/r25_volatility.json"
            response = requests.put(url, json=firebase_data, timeout=15)
            
            if response.status_code == 200:
                logger.info(f"✅ Firebase sync successful - Ticks: {len(firebase_data['ticks'])}, "
                           f"1min candles: {len(firebase_data['candles_1min'])}, "
                           f"5min candles: {len(firebase_data['candles_5min'])}")
                
                # Also store latest candle data separately for quick access
                self.sync_latest_candles_to_firebase(firebase_data)
                return True
            else:
                logger.error(f"❌ Firebase sync failed: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Firebase sync error: {e}")
            return False
    
    def sync_latest_candles_to_firebase(self, firebase_data):
        """Store latest candles separately for quick access"""
        try:
            latest_data = {
                'latest_1min_candles': firebase_data['candles_1min'][-10:],  # Last 10 1min candles
                'latest_5min_candles': firebase_data['candles_5min'][-10:],  # Last 10 5min candles
                'latest_ticks': firebase_data['ticks'][-20:],  # Last 20 ticks
                'updated_at': datetime.now().isoformat()
            }
            
            url = f"{FIREBASE_URL}/r25_latest.json"
            response = requests.put(url, json=latest_data, timeout=10)
            
            if response.status_code == 200:
                logger.info("📊 Latest candles synced to Firebase")
            
        except Exception as e:
            logger.error(f"Error syncing latest candles: {e}")

    def load_from_firebase(self):
        """Load existing data from Firebase on startup"""
        try:
            url = f"{FIREBASE_URL}/r25_volatility.json"
            response = requests.get(url, timeout=15)
            
            if response.status_code == 200:
                firebase_data = response.json()
                if firebase_data and isinstance(firebase_data, dict):
                    with self.lock:
                        # Load data from Firebase
                        self.data['live_ticks'] = firebase_data.get('ticks', [])
                        self.data['candles_1min'] = firebase_data.get('candles_1min', [])
                        self.data['candles_5min'] = firebase_data.get('candles_5min', [])
                        
                        if 'metadata' in firebase_data:
                            metadata = firebase_data['metadata']
                            self.data['current_price'] = metadata.get('current_price', 0)
                            self.data['last_update'] = metadata.get('last_update')
                        
                        logger.info(f"📥 Loaded from Firebase - Ticks: {len(self.data['live_ticks'])}, "
                                   f"1min: {len(self.data['candles_1min'])}, "
                                   f"5min: {len(self.data['candles_5min'])}")
                        return True
            
            logger.info("No existing data found in Firebase, starting fresh")
            return False
            
        except Exception as e:
            logger.error(f"Error loading from Firebase: {e}")
            return False

# Initialize enhanced data manager
data_manager = EnhancedVolatilityDataManager()

class DerivWebSocket:
    def __init__(self):
        self.ws = None
        self.connected = False
        self.connection_thread = None
        self.should_reconnect = True
        self.reconnect_delay = 5
        self.max_reconnect_delay = 60
        self.ping_thread = None
        
    def on_open(self, ws):
        """WebSocket connection opened"""
        logger.info("🟢 Deriv WebSocket connected successfully")
        self.connected = True
        self.reconnect_delay = 5  # Reset reconnect delay on successful connection
        
        # Subscribe to R_25 (Volatility 25)
        self.subscribe_to_ticks()
        
        # Start ping thread to keep connection alive
        self.start_ping_thread()
            
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
                    iso_timestamp = dt.isoformat() + 'Z'
                    
                    # Add tick to data manager (this will auto-update candles)
                    data_manager.add_tick(price, iso_timestamp)
            
            # Handle subscription confirmation
            elif 'subscription' in data:
                logger.info(f"✅ Subscription confirmed: {data.get('subscription', {}).get('id', 'Unknown')}")
                
            # Handle ping/pong
            elif 'ping' in data:
                self.send_pong()
                
            # Handle error messages
            elif 'error' in data:
                logger.error(f"❌ WebSocket error: {data['error']}")
                
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON received: {message[:100]}...")
        except Exception as e:
            logger.error(f"Error processing message: {e}")
            
    def on_error(self, ws, error):
        """Handle WebSocket errors"""
        logger.error(f"🔴 Deriv WebSocket error: {error}")
        self.connected = False
        
    def on_close(self, ws, close_status_code, close_msg):
        """Handle WebSocket close"""
        logger.warning(f"🟡 Deriv WebSocket connection closed: {close_status_code} - {close_msg}")
        self.connected = False
        
        # Stop ping thread
        if self.ping_thread:
            self.ping_thread = None
        
        # Attempt to reconnect if should_reconnect is True
        if self.should_reconnect:
            logger.info(f"🔄 Attempting to reconnect in {self.reconnect_delay} seconds...")
            time.sleep(self.reconnect_delay)
            
            # Exponential backoff for reconnection attempts
            self.reconnect_delay = min(self.reconnect_delay * 2, self.max_reconnect_delay)
            
            # Reconnect in a separate thread to avoid blocking
            threading.Thread(target=self.connect, daemon=True).start()
            
    def subscribe_to_ticks(self):
        """Subscribe to tick data for R_25 (Volatility 25)"""
        if self.ws and self.connected:
            try:
                subscribe_message = {
                    "ticks": VOLATILITY_SYMBOL,
                    "subscribe": 1
                }
                self.ws.send(json.dumps(subscribe_message))
                logger.info(f"📡 Subscribed to {VOLATILITY_SYMBOL} - {VOLATILITY_NAME}")
            except Exception as e:
                logger.error(f"Error subscribing to {VOLATILITY_SYMBOL}: {e}")
    
    def send_pong(self):
        """Send pong response to ping"""
        if self.ws and self.connected:
            try:
                pong_message = {"pong": 1}
                self.ws.send(json.dumps(pong_message))
                logger.debug("🏓 Pong sent")
            except Exception as e:
                logger.error(f"Error sending pong: {e}")
    
    def start_ping_thread(self):
        """Start a thread to send periodic pings"""
        def ping_worker():
            while self.connected and self.ws:
                try:
                    time.sleep(30)  # Send ping every 30 seconds
                    if self.connected and self.ws:
                        ping_message = {"ping": 1}
                        self.ws.send(json.dumps(ping_message))
                        logger.debug("🏓 Ping sent")
                except Exception as e:
                    logger.error(f"Error in ping thread: {e}")
                    break
        
        if not self.ping_thread or not self.ping_thread.is_alive():
            self.ping_thread = threading.Thread(target=ping_worker, daemon=True)
            self.ping_thread.start()
                
    def connect(self):
        """Connect to Deriv WebSocket"""
        try:
            logger.info(f"🔌 Connecting to Deriv WebSocket: {DERIV_WS_URL}")
            
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
                ping_interval=None,  # We handle pings manually
                ping_timeout=None
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
            logger.info("🚀 WebSocket connection thread started")
    
    def stop_connection(self):
        """Stop WebSocket connection"""
        self.should_reconnect = False
        if self.ws:
            self.ws.close()
        self.connected = False
        if self.ping_thread:
            self.ping_thread = None
        logger.info("🛑 WebSocket connection stopped")

# Initialize WebSocket connection
deriv_ws = DerivWebSocket()

# Flask Routes
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
        url = f"{FIREBASE_URL}/r25_volatility.json"
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            firebase_data = response.json()
            if firebase_data:
                metadata = firebase_data.get('metadata', {})
                return jsonify({
                    'symbol': VOLATILITY_SYMBOL,
                    'name': VOLATILITY_NAME,
                    'live_ticks': firebase_data.get('ticks', [])[-100:],
                    'candles_1min': firebase_data.get('candles_1min', [])[-50:],
                    'candles_5min': firebase_data.get('candles_5min', [])[-50:],
                    'current_price': metadata.get('current_price', 0),
                    'last_update': metadata.get('last_update'),
                    'updated_at': metadata.get('updated_at'),
                    'total_ticks': len(firebase_data.get('ticks', [])),
                    'total_1min_candles': len(firebase_data.get('candles_1min', [])),
                    'total_5min_candles': len(firebase_data.get('candles_5min', [])),
                    'source': 'firebase'
                })
            else:
                return jsonify({'error': 'No R_25 data in Firebase'}), 404
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
            'synced_at': datetime.now().isoformat(),
            'symbol': VOLATILITY_SYMBOL,
            'name': VOLATILITY_NAME
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
        'connection_url': DERIV_WS_URL,
        'firebase_url': FIREBASE_URL
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
            'message': f'WebSocket reconnection initiated for {VOLATILITY_SYMBOL}',
            'initiated_at': datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/stats')
def get_stats():
    """Get detailed statistics"""
    return jsonify({
        'symbol': VOLATILITY_SYMBOL,
        'name': VOLATILITY_NAME,
        'max_data_points': MAX_DATA_POINTS,
        'current_stats': {
            'live_ticks_count': len(data_manager.data['live_ticks']),
            'candles_1min_count': len(data_manager.data['candles_1min']),
            'candles_5min_count': len(data_manager.data['candles_5min']),
            'current_price': data_manager.data['current_price'],
            'last_update': data_manager.data['last_update']
        },
        'websocket_connected': deriv_ws.connected,
        'firebase_url': f"{FIREBASE_URL}/r25_volatility.json"
    })

@app.route('/api/candles/1min')
def get_1min_candles():
    """Get 1-minute candlestick data"""
    with data_manager.lock:
        return jsonify({
            'symbol': VOLATILITY_SYMBOL,
            'timeframe': '1min',
            'candles': data_manager.data['candles_1min'][-100:],  # Last 100 candles
            'total_count': len(data_manager.data['candles_1min'])
        })

@app.route('/api/candles/5min')
def get_5min_candles():
    """Get 5-minute candlestick data"""
    with data_manager.lock:
        return jsonify({
            'symbol': VOLATILITY_SYMBOL,
            'timeframe': '5min',
            'candles': data_manager.data['candles_5min'][-100:],  # Last 100 candles
            'total_count': len(data_manager.data['candles_5min'])
        })

if __name__ == '__main__':
    logger.info("🚀 Starting Enhanced R_25 (Volatility 25) Data Server...")
    logger.info(f"📊 Firebase URL: {FIREBASE_URL}")
    logger.info(f"🔌 Deriv WebSocket URL: {DERIV_WS_URL}")
    logger.info(f"📈 Tracking: {VOLATILITY_SYMBOL} - {VOLATILITY_NAME}")
    logger.info(f"💾 Data limit per node: {MAX_DATA_POINTS} items")
    
    # Load existing data from Firebase
    logger.info("📥 Loading existing data from Firebase...")
    data_manager.load_from_firebase()
    
    # Start WebSocket connection
    deriv_ws.start_connection()
    
    # Wait a moment for WebSocket to attempt connection
    time.sleep(3)
    
    logger.info("🌐 Server starting on port 5000...")
    app.run(host='0.0.0.0', port=5000, debug=False)