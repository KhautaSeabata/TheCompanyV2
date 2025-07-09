from flask import Flask, render_template, jsonify, request
import asyncio
import websockets
import json
import requests
import threading
import time
from datetime import datetime, timedelta
import uuid

# Import the trading logic components
from trading_logic import TradingAlerts, TrendlineAnalyzer, trading_alerts

app = Flask(__name__)

# Firebase configuration
FIREBASE_URL = "https://company-bdb78-default-rtdb.firebaseio.com"
FIREBASE_TICKS_PATH = "/ticks.json"
FIREBASE_1MIN_PATH = "/1minVix25.json"
FIREBASE_5MIN_PATH = "/5minVix25.json"
FIREBASE_ALERTS_PATH = "/alerts.json" # Still needed here for API endpoint to fetch alerts

# Deriv WebSocket configuration
DERIV_WS_URL = "wss://ws.derivws.com/websockets/v3?app_id=1089"

# Global variables to store latest data (maintained by the tick collector)
latest_tick = {}
current_1min_candle = {}
current_5min_candle = {}
candle_buffers = {
    '1min': [],
    '5min': []
}

class DerivTickCollector:
    """
    Connects to Deriv WebSocket, subscribes to tick data,
    processes ticks into 1-minute and 5-minute candlesticks,
    and stores data to Firebase.
    """
    def __init__(self):
        self.websocket = None
        self.running = False
        
    async def connect_and_subscribe(self):
        """
        Establishes WebSocket connection to Deriv and subscribes to Volatility 25 ticks.
        Continuously listens for messages and processes tick data.
        Includes reconnection logic on error.
        """
        try:
            self.websocket = await websockets.connect(DERIV_WS_URL)
            print("Connected to Deriv WebSocket.")
            
            # Subscribe to Volatility 25 (R_25) ticks
            subscribe_request = {
                "ticks": "R_25",
                "subscribe": 1
            }
            
            await self.websocket.send(json.dumps(subscribe_request))
            print("Subscribed to R_25 ticks.")
            
            # Listen for incoming messages indefinitely
            async for message in self.websocket:
                try:
                    data = json.loads(message)
                    if 'tick' in data:
                        await self.process_tick(data['tick'])
                except json.JSONDecodeError:
                    print(f"Failed to decode message: {message}")
                except Exception as e:
                    print(f"Error processing message: {e}")
                    
        except Exception as e:
            print(f"WebSocket connection error: {e}. Retrying in 5 seconds...")
            await asyncio.sleep(5)
            # Only attempt to reconnect if the collector is still meant to be running
            if self.running:
                await self.connect_and_subscribe()
    
    async def process_tick(self, tick_data):
        """
        Processes an incoming tick, updates the latest_tick global,
        stores it to Firebase, and processes it for candlestick generation.
        """
        global latest_tick
        
        try:
            tick_info = {
                "epoch": tick_data.get("epoch"),
                "quote": tick_data.get("quote"),
                "symbol": tick_data.get("symbol"),
                "timestamp": datetime.now().isoformat(), # Use server time for consistency
                "id": str(uuid.uuid4())[:8] # Unique ID for Firebase key
            }
            
            latest_tick = tick_info # Update global latest tick
            # print(f"Received tick: {tick_info['quote']} at {tick_info['timestamp']}")
            
            await self.store_to_firebase(tick_info)
            await self.process_candlestick_data(tick_info)
            
        except Exception as e:
            print(f"Error processing tick: {e}")
    
    async def process_candlestick_data(self, tick_info):
        """
        Takes a processed tick and updates the current 1-minute and 5-minute
        candlestick data.
        """
        try:
            epoch = tick_info['epoch']
            quote = float(tick_info['quote'])
            
            # Update 1-minute candlestick
            await self.update_candlestick(epoch, quote, '1min', 60)
            
            # Update 5-minute candlestick
            await self.update_candlestick(epoch, quote, '5min', 300)
            
        except Exception as e:
            print(f"Error processing candlestick data: {e}")
    
    async def update_candlestick(self, epoch, quote, timeframe, seconds):
        """
        Updates the current candlestick for a given timeframe (1min or 5min).
        Closes and stores completed candles to Firebase.
        """
        global current_1min_candle, current_5min_candle, candle_buffers
        
        try:
            # Calculate the start epoch of the current candle period
            candle_start = (epoch // seconds) * seconds
            
            # Get the correct global dictionary for the current timeframe
            current_candle_dict = current_1min_candle if timeframe == '1min' else current_5min_candle
            
            # Initialize a new candle if it's a new period or the candle doesn't exist
            if candle_start not in current_candle_dict or current_candle_dict[candle_start] is None:
                current_candle_dict[candle_start] = {
                    "epoch": candle_start,
                    "open": quote,
                    "high": quote,
                    "low": quote,
                    "close": quote,
                    "timestamp": datetime.fromtimestamp(candle_start).isoformat()
                }
                # print(f"Started new {timeframe} candle at {datetime.fromtimestamp(candle_start).isoformat()}")
            else:
                # Update existing candle with new high, low, and close
                candle = current_candle_dict[candle_start]
                candle["high"] = max(candle["high"], quote)
                candle["low"] = min(candle["low"], quote)
                candle["close"] = quote
                candle["timestamp"] = datetime.fromtimestamp(candle_start).isoformat() # Update timestamp to current candle's start
            
            # Check for and close any candles that have completed
            # Iterate over a copy of keys to allow modification during iteration
            for existing_candle_epoch in list(current_candle_dict.keys()):
                if existing_candle_epoch < candle_start: # If an old candle is found
                    completed_candle_data = current_candle_dict[existing_candle_epoch]
                    await self.store_candlestick_to_firebase(completed_candle_data, timeframe)
                    
                    # Add to in-memory buffer for API access (e.g., for charts)
                    candle_buffers[timeframe].append(completed_candle_data)
                    if len(candle_buffers[timeframe]) > 100:  # Keep last 100 candles in memory
                        candle_buffers[timeframe].pop(0)
                    
                    # Remove the completed candle from the current_candle_dict
                    del current_candle_dict[existing_candle_epoch]
                    # print(f"Completed {timeframe} candle: {completed_candle_data['close']}")
            
        except Exception as e:
            print(f"Error updating {timeframe} candlestick: {e}")
    
    async def store_candlestick_to_firebase(self, candle_data, timeframe):
        """
        Stores a completed candlestick to its respective Firebase path.
        Maintains a maximum of 950 candles in Firebase.
        """
        try:
            firebase_path = FIREBASE_1MIN_PATH if timeframe == '1min' else FIREBASE_5MIN_PATH
            
            # Fetch current candles from Firebase
            response = requests.get(f"{FIREBASE_URL}{firebase_path}")
            
            if response.status_code == 200:
                current_candles = response.json() or {}
            else:
                # If fetch fails, initialize as empty to prevent errors
                current_candles = {}
                print(f"Warning: Failed to fetch existing {timeframe} candles (Status: {response.status_code}). Starting fresh.")
            
            # Add new candle with its epoch as the key
            candle_key = str(candle_data['epoch'])
            current_candles[candle_key] = candle_data
            
            # Keep only the latest 950 candles (sorted by epoch)
            if len(current_candles) > 950:
                sorted_candles = dict(sorted(current_candles.items(), 
                                           key=lambda x: int(x[0]), # Sort by epoch (integer key)
                                           reverse=True)[:950]) # Keep latest 950
                current_candles = sorted_candles
            
            # Update Firebase with the modified set of candles
            update_response = requests.put(
                f"{FIREBASE_URL}{firebase_path}",
                json=current_candles
            )
            
            if update_response.status_code == 200:
                # print(f"Successfully stored {timeframe} candle to Firebase. Total candles: {len(current_candles)}")
                pass # Suppress frequent success messages
            else:
                print(f"Failed to store {timeframe} candle to Firebase: {update_response.status_code} - {update_response.text}")
                
        except Exception as e:
            print(f"Error storing {timeframe} candle to Firebase: {e}")
    
    async def store_to_firebase(self, tick_data):
        """
        Stores a raw tick to Firebase and maintains a maximum of 950 latest records.
        """
        try:
            # Fetch current ticks from Firebase
            response = requests.get(f"{FIREBASE_URL}{FIREBASE_TICKS_PATH}")
            
            if response.status_code == 200:
                current_ticks = response.json() or {}
            else:
                # If fetch fails, initialize as empty
                current_ticks = {}
                print(f"Warning: Failed to fetch existing ticks (Status: {response.status_code}). Starting fresh.")

            # Add new tick with a unique key (epoch_id)
            tick_key = f"{tick_data['epoch']}_{tick_data['id']}"
            current_ticks[tick_key] = tick_data
            
            # Keep only the latest 950 ticks (sorted by epoch)
            if len(current_ticks) > 950:
                sorted_ticks = dict(sorted(current_ticks.items(), 
                                         key=lambda x: x[1]['epoch'], # Sort by tick epoch
                                         reverse=True)[:950]) # Keep latest 950
                current_ticks = sorted_ticks
            
            # Update Firebase with the modified set of ticks
            update_response = requests.put(
                f"{FIREBASE_URL}{FIREBASE_TICKS_PATH}",
                json=current_ticks
            )
            
            if update_response.status_code == 200:
                # print(f"Successfully stored tick to Firebase. Total ticks: {len(current_ticks)}")
                pass # Suppress frequent success messages
            else:
                print(f"Failed to store tick to Firebase: {update_response.status_code} - {update_response.text}")
                
        except Exception as e:
            print(f"Error storing to Firebase: {e}")
    
    def start(self):
        """
        Starts the asynchronous WebSocket connection and tick processing loop.
        Runs in a new event loop on a separate thread.
        """
        self.running = True
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self.connect_and_subscribe())

# Initialize tick collector
tick_collector = DerivTickCollector()

# Flask Routes
@app.route('/')
def index():
    """Renders the main index page."""
    return render_template('index.html')

@app.route('/charts')
def charts():
    """Renders the charts page."""
    return render_template('charts.html')

@app.route('/api/analyze', methods=['POST'])
def analyze_ticks():
    """
    API endpoint to perform enhanced technical analysis on tick data
    and generate trading signals/alerts.
    """
    try:
        # Fetch all ticks from Firebase for analysis
        response = requests.get(f"{FIREBASE_URL}{FIREBASE_TICKS_PATH}")
        
        if response.status_code != 200:
            return jsonify({"error": "Failed to fetch tick data from Firebase"}), 500
        
        ticks_data = response.json() or {}
        
        if not ticks_data:
            return jsonify({"error": "No tick data available in Firebase for analysis"}), 404
        
        # Convert dictionary to list, sort by epoch, and extract prices
        ticks_list = list(ticks_data.values())
        ticks_list.sort(key=lambda x: x.get('epoch', 0))
        
        # Use the last 200 ticks for analysis to keep it relevant and performant
        prices = [float(tick.get('quote', 0)) for tick in ticks_list[-200:] if tick.get('quote')]
        
        if len(prices) < 20: # Ensure sufficient data for analysis
            return jsonify({"error": "Insufficient data (less than 20 ticks) for detailed analysis"}), 400
        
        analyzer = TrendlineAnalyzer() # Create an instance of the analyzer
        
        # Perform analysis
        support_levels, resistance_levels = analyzer.find_support_resistance(prices)
        signals = analyzer.generate_enhanced_signals(prices, support_levels, resistance_levels)
        
        # Add strong signals as trading alerts
        for signal in signals:
            if signal['confidence'] > 0.8: # Only add alerts for high-confidence signals
                alert = trading_alerts.add_alert(
                    alert_type=signal['type'],
                    direction=signal['action'],
                    price=signal['entry_price'],
                    confidence=signal['confidence'],
                    description=signal['description'],
                    expiry_minutes=10 # Alerts expire after 10 minutes
                )
                
                if alert:
                    print(f"New trading alert generated: {alert['description']} ({alert['action']} at {alert['price']:.5f})")
        
        # Compile comprehensive analysis result
        current_price = prices[-1]
        ma_data = analyzer.calculate_moving_averages(prices)
        rsi = analyzer.calculate_rsi(prices)
        patterns = analyzer.detect_price_action_patterns(prices) # Also include patterns in the result
        
        analysis_result = {
            'support_levels_count': len(support_levels),
            'resistance_levels_count': len(resistance_levels),
            'current_price': current_price,
            'rsi': rsi,
            'moving_averages': ma_data,
            'detected_patterns': patterns,
            'generated_signals': signals,
            'total_ticks_analyzed': len(prices),
            'analysis_timestamp': datetime.now().isoformat()
        }
        
        return jsonify(analysis_result)
        
    except Exception as e:
        print(f"Error during analysis: {e}")
        return jsonify({"error": f"Analysis failed: {str(e)}"}), 500

@app.route('/api/alerts')
def get_alerts():
    """API endpoint to get currently active trading alerts."""
    try:
        active_alerts = trading_alerts.get_active_alerts()
        return jsonify({
            'active_alerts': active_alerts,
            'total_active_alerts': len(active_alerts)
        })
    except Exception as e:
        print(f"Error fetching active alerts: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/alerts/history')
def get_alerts_history():
    """API endpoint to get the history of alerts stored in Firebase."""
    try:
        response = requests.get(f"{FIREBASE_URL}{FIREBASE_ALERTS_PATH}")
        if response.status_code == 200:
            alerts = response.json() or {}
            return jsonify(alerts)
        else:
            return jsonify({"error": "Failed to fetch alerts history"}), 500
    except Exception as e:
        print(f"Error fetching alerts history: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/latest-tick')
def get_latest_tick():
    """API endpoint to get the single latest tick data from Firebase."""
    try:
        response = requests.get(f"{FIREBASE_URL}{FIREBASE_TICKS_PATH}")
        if response.status_code == 200:
            ticks = response.json() or {}
            if ticks:
                # Find the tick with the maximum epoch (latest)
                latest_tick_data = max(ticks.values(), key=lambda x: x.get('epoch', 0))
                return jsonify(latest_tick_data)
            else:
                return jsonify({"error": "No ticks available"}), 404
        else:
            return jsonify({"error": "Failed to fetch ticks"}), 500
    except Exception as e:
        print(f"Error fetching latest tick: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/all-ticks')
def get_all_ticks():
    """API endpoint to get all raw ticks from Firebase."""
    try:
        response = requests.get(f"{FIREBASE_URL}{FIREBASE_TICKS_PATH}")
        if response.status_code == 200:
            ticks = response.json() or {}
            return jsonify(ticks)
        else:
            return jsonify({"error": "Failed to fetch ticks"}), 500
    except Exception as e:
        print(f"Error fetching all ticks: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/1min-candles')
def get_1min_candles():
    """API endpoint to get 1-minute candlestick data from Firebase."""
    try:
        response = requests.get(f"{FIREBASE_URL}{FIREBASE_1MIN_PATH}")
        if response.status_code == 200:
            candles = response.json() or {}
            return jsonify(candles)
        else:
            return jsonify({"error": "Failed to fetch 1min candles"}), 500
    except Exception as e:
        print(f"Error fetching 1min candles: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/5min-candles')
def get_5min_candles():
    """API endpoint to get 5-minute candlestick data from Firebase."""
    try:
        response = requests.get(f"{FIREBASE_URL}{FIREBASE_5MIN_PATH}")
        if response.status_code == 200:
            candles = response.json() or {}
            return jsonify(candles)
        else:
            return jsonify({"error": "Failed to fetch 5min candles"}), 500
    except Exception as e:
        print(f"Error fetching 5min candles: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/status')
def get_status():
    """
    API endpoint to get the overall status of the application,
    including tick collector status, latest tick, current candles,
    total ticks in Firebase, and active alert count.
    """
    global current_1min_candle, current_5min_candle
    
    tick_count = 0
    try:
        # Attempt to get total tick count from Firebase for status display
        response = requests.get(f"{FIREBASE_URL}{FIREBASE_TICKS_PATH}")
        if response.status_code == 200:
            ticks = response.json() or {}
            tick_count = len(ticks)
    except Exception as e:
        print(f"Could not get total tick count for status: {e}")
        pass # Silently fail if Firebase fetch for count fails
    
    return jsonify({
        "status": "running" if tick_collector.running else "stopped",
        "latest_tick": latest_tick,
        "current_1min_candle": current_1min_candle,
        "current_5min_candle": current_5min_candle,
        "total_ticks_in_firebase": tick_count,
        "active_alerts": len(trading_alerts.get_active_alerts()), # Get count of active alerts
        "timestamp": datetime.now().isoformat()
    })

def start_tick_collector():
    """
    Starts the DerivTickCollector in a separate daemon thread.
    A daemon thread will exit automatically when the main program exits.
    """
    thread = threading.Thread(target=tick_collector.start, daemon=True)
    thread.start()

# Start the tick collector when the module is imported (for production environments like Gunicorn)
start_tick_collector()

if __name__ == '__main__':
    # Run Flask app for local development.
    # use_reloader=False is important when threading is involved to prevent
    # the thread from being started multiple times.
    app.run(debug=True, host='0.0.0.0', port=5000, use_reloader=False)

