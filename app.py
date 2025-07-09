import uuid
import asyncio
import json
import os
import time
from datetime import datetime, timedelta, timezone
import numpy as np
import requests
from flask import Flask, jsonify, render_template, request
from threading import Thread, Lock
from collections import deque
from websockets.client import connect as ws_connect
import firebase_admin
from firebase_admin import credentials, db

# Assuming trading_logic.py is in the same directory
from trading_logic import TradingAlerts, TrendlineAnalyzer

# --- Firebase Configuration (for alerts only) ---
# Check if Firebase app is already initialized to prevent re-initialization errors
if not firebase_admin._apps:
    try:
        # For local development, use a service account key file
        # Make sure 'path/to/your/serviceAccountKey.json' is correct
        # For deployment, consider environment variables for credentials or Firebase Functions
        # IMPORTANT: This path should be correct for your environment.
        FIREBASE_CRED_PATH = "company-bdb78-firebase-adminsdk-v02b4-e4c194689b.json"
        cred = credentials.Certificate(FIREBASE_CRED_PATH)
        firebase_admin.initialize_app(cred, {
            'databaseURL': "https://company-bdb78-default-rtdb.firebaseio.com"
        })
        print(f"Firebase app initialized successfully using {FIREBASE_CRED_PATH}.")
    except Exception as e:
        print(f"Error initializing Firebase: {e}")
        print("Please ensure your Firebase service account key is in the correct path and readable.")
        print("Specifically, check if the file 'company-bdb78-firebase-adminsdk-v02b4-e4c194689b.json' exists and is accessible.")

FIREBASE_URL = "https://company-bdb78-default-rtdb.firebaseio.com"
FIREBASE_ALERTS_PATH = "/alerts.json" # Alerts will still be stored here

# --- Deriv API Configuration ---
# WARNING: HARDCODING API TOKENS IS A SECURITY RISK.
# For production, ALWAYS use environment variables or a secrets management system.
# This is done here ONLY because it was explicitly requested for demonstration.
DERIV_APP_ID = "108" # Your Deriv App ID (e.g., from registering your app)
DERIV_API_TOKEN = "bK3fhHLYrP1sMEb" # Your hardcoded API token as requested
DERIV_WS_URL = "wss://ws.derivws.com/websockets/v3?app_id=" + DERIV_APP_ID
SYMBOL = 'VIX25' # The symbol we are trading

# --- Global Data Stores (in-memory, no Firebase for ticks/candles for now) ---
latest_tick = {'symbol': SYMBOL, 'quote': None, 'timestamp': None, 'epoch': None}
tick_history_buffer = deque(maxlen=2000) # Buffer to hold recent ticks for analysis
min_1_candles = {} # Stores 1-minute OHLCV data by start_epoch
min_5_candles = {} # Stores 5-minute OHLCV data by start_epoch

# --- Concurrency Management ---
tick_collector_running = False
tick_collector_thread = None
data_lock = Lock() # To protect shared data structures (latest_tick, buffers, candles)

# --- Trading Logic Initialization ---
trading_alerts = TradingAlerts() # Alerts system (still uses Firebase)

# --- Flask App Setup ---
app = Flask(__name__)
# WARNING: Hardcoding secret key is also a security risk. Use environment variables.
app.secret_key = 'super_secret_dev_key_do_not_use_in_prod' # Replace with a strong secret key for session management

# --- Deriv API Helper Functions ---
async def get_deriv_ticks_history(symbol=SYMBOL, count=100):
    """Fetches historical tick data directly from Deriv API."""
    try:
        async with ws_connect(DERIV_WS_URL) as websocket:
            # Authorize if needed for private data, otherwise just send ticks_history
            # For public ticks_history, authorization is often not strictly required.
            # But including it ensures compatibility for any future private data needs.
            await websocket.send(json.dumps({"authorize": DERIV_API_TOKEN}))
            auth_response = await websocket.recv()
            auth_data = json.loads(auth_response)
            if 'error' in auth_data:
                print(f"Deriv API Authorization Error: {auth_data['error']['message']}")
                return None

            request_data = {
                "ticks_history": symbol,
                "count": count,
                "end": "latest",
                "style": "ticks",
                "adjust_start_time": 1,
                "subscribe": 0 # Not subscribing, just getting history
            }
            await websocket.send(json.dumps(request_data))
            response = await websocket.recv()
            data = json.loads(response)

            if 'history' in data and 'prices' in data['history'] and 'times' in data['history']:
                ticks = []
                prices = data['history']['prices']
                times = data['history']['times']
                for i in range(len(prices)):
                    ticks.append({
                        "epoch": times[i],
                        "quote": float(prices[i]),
                        "timestamp": datetime.fromtimestamp(times[i], tz=timezone.utc).isoformat()
                    })
                # Ensure ticks are sorted by epoch ascending
                ticks.sort(key=lambda x: x['epoch'])
                return ticks
            else:
                print(f"Error fetching Deriv ticks history: {data.get('error', {}).get('message', 'Unknown error')}")
                return None
    except Exception as e:
        print(f"WebSocket error fetching Deriv ticks history for {symbol}: {e}")
        return None

async def get_deriv_ohlc_history(symbol=SYMBOL, interval='1m', count=100):
    """Fetches historical OHLC (candlestick) data directly from Deriv API."""
    granularity = 60 # 1 minute
    if interval == '5m':
        granularity = 300 # 5 minutes
    elif interval == '1h':
        granularity = 3600 # 1 hour
    # Add more intervals as needed

    try:
        async with ws_connect(DERIV_WS_URL) as websocket:
            # Authorize if needed
            await websocket.send(json.dumps({"authorize": DERIV_API_TOKEN}))
            auth_response = await websocket.recv()
            auth_data = json.loads(auth_response)
            if 'error' in auth_data:
                print(f"Deriv API Authorization Error: {auth_data['error']['message']}")
                return None

            request_data = {
                "ohlc": symbol,
                "granularity": granularity,
                "count": count,
                "end": "latest",
                "subscribe": 0 # Not subscribing, just getting history
            }
            await websocket.send(json.dumps(request_data))
            response = await websocket.recv()
            data = json.loads(response)

            if 'ohlc' in data and data['ohlc']:
                candles = {}
                # The 'ohlc' field contains a list of candle data
                for candle_data in data['ohlc']:
                    epoch_time = candle_data['open_time']
                    candles[str(epoch_time)] = {
                        'open': float(candle_data['open']),
                        'high': float(candle_data['high']),
                        'low': float(candle_data['low']),
                        'close': float(candle_data['close']),
                        'timestamp': datetime.fromtimestamp(epoch_time, tz=timezone.utc).isoformat(),
                        'epoch': epoch_time,
                        'volume': candle_data.get('volume', 0) # Volume might not be present for VIX
                    }
                # Sort candles by epoch ascending
                sorted_candles = dict(sorted(candles.items(), key=lambda item: int(item[0])))
                return sorted_candles
            else:
                print(f"Error fetching Deriv OHLC history for {symbol} ({interval}): {data.get('error', {}).get('message', 'Unknown error')}")
                return None
    except Exception as e:
        print(f"WebSocket error fetching Deriv OHLC history for {symbol} ({interval}): {e}")
        return None


# --- Tick Collector Thread (modified to not write to Firebase for ticks/candles) ---
async def _tick_collector_logic():
    global latest_tick, tick_history_buffer, tick_collector_running, min_1_candles, min_5_candles
    print("Starting tick collector logic...")
    while tick_collector_running:
        try:
            async with ws_connect(DERIV_WS_URL) as websocket:
                # Authorize the connection for real-time ticks
                await websocket.send(json.dumps({"authorize": DERIV_API_TOKEN}))
                auth_response = await websocket.recv()
                auth_data = json.loads(auth_response)
                if 'error' in auth_data:
                    print(f"Deriv API Authorization Error for collector: {auth_data['error']['message']}")
                    await asyncio.sleep(5) # Wait before retrying connection
                    continue

                # Subscribe to tick stream
                await websocket.send(json.dumps({"ticks": SYMBOL, "subscribe": 1}))
                print(f"Subscribed to {SYMBOL} ticks.")

                # Initialize current candle data
                current_1min_candle = {'open': None, 'high': None, 'low': None, 'close': None, 'timestamp': None, 'epoch': None}
                current_5min_candle = {'open': None, 'high': None, 'low': None, 'close': None, 'timestamp': None, 'epoch': None}

                while tick_collector_running:
                    try:
                        message = await asyncio.wait_for(websocket.recv(), timeout=10) # Timeout for graceful shutdown
                        data = json.loads(message)

                        if 'tick' in data:
                            tick_data = data['tick']
                            price = float(tick_data['quote'])
                            epoch_time = int(tick_data['epoch'])
                            iso_timestamp = datetime.fromtimestamp(epoch_time, tz=timezone.utc).isoformat()

                            with data_lock:
                                latest_tick.update({
                                    'symbol': tick_data['symbol'],
                                    'quote': price,
                                    'timestamp': iso_timestamp,
                                    'epoch': epoch_time
                                })
                                tick_history_buffer.append(price) # Add to analysis buffer

                                # --- In-memory Candlestick Aggregation (1-minute) ---
                                current_1min_floor_epoch = (epoch_time // 60) * 60 # Floor to nearest minute
                                if current_1min_candle['epoch'] != current_1min_floor_epoch:
                                    # New 1-minute candle starts
                                    if current_1min_candle['epoch'] is not None:
                                        # Close previous candle and store it
                                        min_1_candles[str(current_1min_candle['epoch'])] = current_1min_candle.copy()
                                        # Keep only last 200 candles in memory for performance
                                        if len(min_1_candles) > 200:
                                            oldest_key = sorted(min_1_candles.keys())[0]
                                            del min_1_candles[oldest_key]
                                    current_1min_candle = {
                                        'open': price,
                                        'high': price,
                                        'low': price,
                                        'close': price,
                                        'timestamp': datetime.fromtimestamp(current_1min_floor_epoch, tz=timezone.utc).isoformat(),
                                        'epoch': current_1min_floor_epoch
                                    }
                                else:
                                    # Update current 1-minute candle
                                    current_1min_candle['high'] = max(current_1min_candle['high'], price)
                                    current_1min_candle['low'] = min(current_1min_candle['low'], price)
                                    current_1min_candle['close'] = price

                                # --- In-memory Candlestick Aggregation (5-minute) ---
                                current_5min_floor_epoch = (epoch_time // 300) * 300 # Floor to nearest 5 minutes
                                if current_5min_candle['epoch'] != current_5min_floor_epoch:
                                    # New 5-minute candle starts
                                    if current_5min_candle['epoch'] is not None:
                                        # Close previous candle and store it
                                        min_5_candles[str(current_5min_candle['epoch'])] = current_5min_candle.copy()
                                        # Keep only last 200 candles in memory for performance
                                        if len(min_5_candles) > 200:
                                            oldest_key = sorted(min_5_candles.keys())[0]
                                            del min_5_candles[oldest_key]
                                    current_5min_candle = {
                                        'open': price,
                                        'high': price,
                                        'low': price,
                                        'close': price,
                                        'timestamp': datetime.fromtimestamp(current_5min_floor_epoch, tz=timezone.utc).isoformat(),
                                        'epoch': current_5min_floor_epoch
                                    }
                                else:
                                    # Update current 5-minute candle
                                    current_5min_candle['high'] = max(current_5min_candle['high'], price)
                                    current_5min_candle['low'] = min(current_5min_candle['low'], price)
                                    current_5min_candle['close'] = price

                            # print(f"Received tick: {SYMBOL} - {price} at {iso_timestamp}") # Optional: log ticks

                        elif 'error' in data:
                            print(f"Deriv API Error (collector): {data['error']['message']}")
                        else:
                            # print(f"Received non-tick message: {data}") # Optional: log other messages
                            pass

                    except asyncio.TimeoutError:
                        # No message received within timeout, check if collector is still running
                        print("Tick collector: No message received, re-checking status...")
                        continue # Continue loop to re-evaluate tick_collector_running
                    except Exception as e:
                        print(f"Error in tick collector inner loop: {e}")
                        # Attempt to reconnect after a short delay
                        await asyncio.sleep(2)
                        break # Break inner loop to try re-establishing WebSocket connection

        except Exception as e:
            print(f"Error in tick collector outer loop (websocket connection): {e}")
            # Wait before attempting to reconnect
            await asyncio.sleep(5)
    print("Tick collector stopped.")

def start_tick_collector():
    global tick_collector_running, tick_collector_thread
    if not tick_collector_running:
        tick_collector_running = True
        # Run the async collector logic in a new event loop on a separate thread
        def run_async_loop():
            asyncio.run(_tick_collector_logic())

        tick_collector_thread = Thread(target=run_async_loop)
        tick_collector_thread.start()
        print("Tick collector thread started.")

def stop_tick_collector():
    global tick_collector_running, tick_collector_thread
    if tick_collector_running:
        tick_collector_running = False
        if tick_collector_thread and tick_collector_thread.is_alive():
            tick_collector_thread.join(timeout=10) # Wait for thread to finish
            if tick_collector_thread.is_alive():
                print("Warning: Tick collector thread did not terminate gracefully.")
        tick_collector_thread = None
        print("Tick collector stopped.")


# --- Flask Routes ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/latest-tick')
def get_latest_tick_route():
    with data_lock:
        if latest_tick['quote'] is not None:
            return jsonify(latest_tick)
        return jsonify({"error": "No tick data available yet."}), 404

@app.route('/api/status')
def get_status():
    with data_lock:
        collector_status = "running" if tick_collector_running else "stopped"
        total_ticks_count_in_buffer = len(tick_history_buffer) # Report buffer size instead

        active_alerts = trading_alerts.get_active_alerts()

        # Get the latest 1-min and 5-min candles from in-memory store
        current_1min_candle_data = {}
        if min_1_candles:
            # Get the very last (most recent) candle from the in-memory dictionary
            last_1min_epoch = sorted(min_1_candles.keys())[-1]
            current_1min_candle_data = {last_1min_epoch: min_1_candles[last_1min_epoch]}

        current_5min_candle_data = {}
        if min_5_candles:
            last_5min_epoch = sorted(min_5_candles.keys())[-1]
            current_5min_candle_data = {last_5min_epoch: min_5_candles[last_5min_epoch]}


        return jsonify({
            "status": collector_status,
            "timestamp": datetime.now().isoformat(),
            "latest_tick_price": latest_tick['quote'],
            "total_ticks_in_memory_buffer": total_ticks_count_in_buffer, # Updated status field
            "active_alerts": len(active_alerts),
            "current_1min_candle": current_1min_candle_data,
            "current_5min_candle": current_5min_candle_data
        })

@app.route('/api/alerts')
def get_alerts():
    active_alerts = trading_alerts.get_active_alerts()
    return jsonify({"active_alerts": active_alerts})

@app.route('/api/analyze', methods=['POST'])
async def analyze_data():
    with data_lock:
        if len(tick_history_buffer) < 200: # Need enough data for analysis
            return jsonify({"error": "Not enough tick data for comprehensive analysis (need at least 200 ticks). Please wait for more data to be collected."}), 400

        recent_prices = list(tick_history_buffer) # Convert deque to list

    # Perform analysis using trading_logic
    support_levels, resistance_levels = TrendlineAnalyzer.find_support_resistance(recent_prices)
    ma_data = TrendlineAnalyzer.calculate_moving_averages(recent_prices)
    rsi_value = TrendlineAnalyzer.calculate_rsi(recent_prices)
    price_patterns = TrendlineAnalyzer.detect_price_action_patterns(recent_prices)
    signals = TrendlineAnalyzer.generate_enhanced_signals(recent_prices, support_levels, resistance_levels)

    analysis_timestamp = datetime.now().isoformat()
    current_price_analyzed = recent_prices[-1]

    # Add alerts based on generated signals
    new_alerts_added = []
    for signal in signals:
        alert_description = f"{signal['type']} - {signal['description']} Entry: {signal['entry_price']:.5f} SL: {signal['stop_loss']:.5f} TP: {signal['take_profit']:.5f}"
        added_alert = trading_alerts.add_alert(
            alert_type=signal['type'],
            direction=signal['action'],
            price=signal['entry_price'],
            confidence=signal['confidence'],
            description=alert_description,
            expiry_minutes=10 # Alerts expire after 10 minutes
        )
        if added_alert:
            new_alerts_added.append(added_alert)

    return jsonify({
        "status": "Analysis complete",
        "analysis_timestamp": analysis_timestamp,
        "current_price": current_price_analyzed,
        "rsi": rsi_value,
        "moving_averages": ma_data,
        "detected_patterns": price_patterns,
        "generated_signals": signals,
        "new_alerts_added": new_alerts_added
    })


@app.route('/api/deriv-all-ticks')
async def get_deriv_all_ticks():
    """API endpoint to get historical ticks directly from Deriv."""
    count = int(request.args.get('count', 100))
    ticks = await get_deriv_ticks_history(SYMBOL, count)
    if ticks:
        # Convert list of ticks to a dictionary keyed by epoch for consistency with Firebase structure
        # (Though frontend will just use the list)
        return jsonify({str(tick['epoch']): tick for tick in ticks})
    return jsonify({"error": "Failed to fetch historical ticks from Deriv"}), 500

@app.route('/api/deriv-1min-candles')
async def get_deriv_1min_candles():
    """API endpoint to get historical 1-minute candles directly from Deriv."""
    count = int(request.args.get('count', 100))
    candles = await get_deriv_ohlc_history(SYMBOL, '1m', count)
    if candles:
        return jsonify(candles)
    return jsonify({"error": "Failed to fetch 1-minute candles from Deriv"}), 500

@app.route('/api/deriv-5min-candles')
async def get_deriv_5min_candles():
    """API endpoint to get historical 5-minute candles directly from Deriv."""
    count = int(request.args.get('count', 100))
    candles = await get_deriv_ohlc_history(SYMBOL, '5m', count)
    if candles:
        return jsonify(candles)
    return jsonify({"error": "Failed to fetch 5-minute candles from Deriv"}), 500

# --- Application Startup/Shutdown ---
@app.before_request
def before_first_request():
    # Start the tick collector thread only once when the first request comes in
    global tick_collector_thread
    if tick_collector_thread is None or not tick_collector_thread.is_alive():
        start_tick_collector()

# You might want to define a cleanup function for when the app shuts down
# However, for simple Flask apps run via 'flask run' or gunicorn,
# explicit cleanup on shutdown can be tricky.
# For production, consider using a proper process manager (e.g., systemd)
# to ensure the collector thread is managed correctly.

if __name__ == '__main__':
    # For running locally with an ASGI server (recommended for async routes)
    # You need to install gunicorn and uvicorn: pip install gunicorn "uvicorn[standard]"
    # To run: gunicorn --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:5000 app:app
    # For simple local testing without gunicorn, you can run:
    # app.run(debug=True, host='0.0.0.0', port=5000)
    # But note that async routes might not behave as expected with the default Flask dev server.

    # To simplify local execution for this example, we'll use a basic runner
    # and rely on the before_request to start the collector.
    # For production, always use an ASGI server like Gunicorn/Uvicorn.
    print("Starting Flask app. For production, consider running with Gunicorn/Uvicorn:")
    print("gunicorn --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:5000 app:app")
    app.run(debug=True, host='0.0.0.0', port=5000, use_reloader=False) # use_reloader=False prevents collector restart on code change
