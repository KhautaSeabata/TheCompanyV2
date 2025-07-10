import asyncio
import json
import time
from collections import deque
from flask import Flask, render_template
from flask_socketio import SocketIO, emit
import websockets
import threading

# Flask app setup
app = Flask(__name__)
# Use a simple message queue for SocketIO, suitable for a single process/thread setup.
# For production and multiple instances, use Redis or RabbitMQ.
app.config['SECRET_KEY'] = 'your_secret_key_here' # Replace with a strong secret key
socketio = SocketIO(app, async_mode='threading', cors_allowed_origins="*") # Use threading for simplicity with websockets

# Deriv API configuration
DERIV_APP_ID = 1089  # Public app ID for Deriv API
DERIV_WS_URL = f"wss://ws.derivws.com/websockets/v3?app_id={DERIV_APP_ID}"
DERIV_API_TOKEN = "bK3fhHLYrP1sMEb" # Your Deriv API token

# Data storage for candlesticks
# { 'symbol': { 'interval': { 'timestamp': { 'open', 'high', 'low', 'close', 'volume' } } } }
candlestick_data = {}
# Store the last few ticks for the 'tick' chart
tick_data = {}

# Symbols to subscribe to (Volatility Indices)
SYMBOLS = ["R_100", "R_75", "R_50", "R_25"]
INTERVALS = [60, 300, 900] # 1 min, 5 min, 15 min in seconds

# Lock for thread-safe access to candlestick_data and tick_data
data_lock = threading.Lock()

# --- Candlestick Generation Logic ---
def initialize_candlestick_data():
    """Initializes the data structures for all symbols and intervals."""
    with data_lock:
        for symbol in SYMBOLS:
            candlestick_data[symbol] = {}
            tick_data[symbol] = deque(maxlen=200) # Store last 200 ticks for display
            for interval in INTERVALS:
                candlestick_data[symbol][interval] = {}

def process_tick(symbol, price, tick_time):
    """
    Processes an incoming tick to update candlestick data for all intervals
    and stores it for tick chart.
    """
    with data_lock:
        # Add to tick data - ensure consistent format
        tick_data[symbol].append({
            'time': tick_time, 
            'value': price  # Use 'value' for line chart compatibility
        })

        # Update candlesticks for each interval
        for interval in INTERVALS:
            # Calculate the start time of the current candle for this interval
            # Ensure the timestamp is aligned to the interval (e.g., for 1-min, 12:00:00, 12:01:00)
            candle_start_time = (tick_time // interval) * interval

            if candle_start_time not in candlestick_data[symbol][interval]:
                # New candle started
                candlestick_data[symbol][interval][candle_start_time] = {
                    'open': price,
                    'high': price,
                    'low': price,
                    'close': price,
                    'volume': 0 # Volume is not directly available from Deriv ticks, keeping for structure
                }
            else:
                # Update existing candle
                current_candle = candlestick_data[symbol][interval][candle_start_time]
                current_candle['high'] = max(current_candle['high'], price)
                current_candle['low'] = min(current_candle['low'], price)
                current_candle['close'] = price

            # Emit update to frontend for this symbol and interval
            socketio.emit('candlestick_update', {
                'symbol': symbol,
                'interval': interval,
                'data': {
                    'time': candle_start_time, # Send epoch seconds
                    'open': candlestick_data[symbol][interval][candle_start_time]['open'],
                    'high': candlestick_data[symbol][interval][candle_start_time]['high'],
                    'low': candlestick_data[symbol][interval][candle_start_time]['low'],
                    'close': candlestick_data[symbol][interval][candle_start_time]['close']
                }
            }, namespace='/')

        # Emit tick update to frontend - ensure consistent format
        socketio.emit('tick_update', {
            'symbol': symbol,
            'data': {
                'time': tick_time, 
                'value': price  # Use 'value' for line chart compatibility
            }
        }, namespace='/')

# --- Deriv WebSocket Connection ---
async def connect_to_deriv_ws():
    """Establishes and maintains WebSocket connection to Deriv API."""
    while True:
        try:
            async with websockets.connect(DERIV_WS_URL) as websocket:
                print(f"Connected to Deriv WebSocket: {DERIV_WS_URL}")

                # Authorize with the provided API token
                auth_message = {
                    "authorize": DERIV_API_TOKEN
                }
                await websocket.send(json.dumps(auth_message))
                auth_response = await websocket.recv()
                auth_data = json.loads(auth_response)

                if auth_data.get('msg_type') == 'authorize' and auth_data.get('authorize'):
                    print(f"Successfully authorized with Deriv API for account: {auth_data['authorize']['loginid']}")
                elif auth_data.get('error'):
                    print(f"Deriv API Authorization Error: {auth_data['error']['message']}")
                    # Depending on the error, you might want to break or continue
                    # For now, we'll just print and proceed, but this might lead to issues
                    # if subscription requires authorization.
                else:
                    print(f"Unexpected authorization response: {auth_data}")

                # Subscribe to tick streams for all symbols
                for symbol in SYMBOLS:
                    subscribe_message = {
                        "ticks": symbol,
                        "subscribe": 1
                    }
                    await websocket.send(json.dumps(subscribe_message))
                    print(f"Subscribed to ticks for {symbol}")

                while True:
                    message = await websocket.recv()
                    data = json.loads(message)

                    if data.get('msg_type') == 'tick':
                        symbol = data['tick']['symbol']
                        price = float(data['tick']['quote'])
                        # Convert milliseconds to seconds for candlestick calculation
                        tick_time = int(data['tick']['epoch'])
                        process_tick(symbol, price, tick_time)
                    elif data.get('msg_type') == 'candles':
                        # We are generating candles from ticks, so this might not be needed
                        # unless we want to fetch historical candles.
                        pass
                    elif data.get('error'):
                        print(f"Deriv API Error: {data['error']['message']}")

        except websockets.exceptions.ConnectionClosedOK:
            print("Deriv WebSocket connection closed cleanly. Reconnecting...")
        except websockets.exceptions.ConnectionClosedError as e:
            print(f"Deriv WebSocket connection closed with error: {e}. Reconnecting in 5s...")
            await asyncio.sleep(5)
        except Exception as e:
            print(f"An unexpected error occurred with Deriv WebSocket: {e}. Reconnecting in 5s...")
            await asyncio.sleep(5)

# --- Flask Routes ---
@app.route('/')
def index():
    """Renders the main HTML page."""
    return render_template('index.html')

# --- SocketIO Events ---
@socketio.on('connect')
def handle_connect():
    """Handles new client connections."""
    print('Client connected')
    # When a new client connects, send them the current state of the data
    with data_lock:
        for symbol in SYMBOLS:
            # Send current tick data
            tick_list = list(tick_data[symbol]) # Convert deque to list for JSON serialization
            emit('initial_tick_data', {
                'symbol': symbol,
                'data': tick_list
            }, namespace='/')

            # Send current candlestick data for each interval
            for interval in INTERVALS:
                # Get the last few candles to initialize the chart
                # Sort by timestamp and take the last N candles
                recent_candles = sorted(candlestick_data[symbol][interval].items())[-100:] # Last 100 candles
                formatted_candles = [
                    {'time': ts, 'open': c['open'], 'high': c['high'], 'low': c['low'], 'close': c['close']}
                    for ts, c in recent_candles
                ]
                emit('initial_candlestick_data', {
                    'symbol': symbol,
                    'interval': interval,
                    'data': formatted_candles
                }, namespace='/')

@socketio.on('request_initial_data')
def handle_request_initial_data(data):
    """Handles requests for initial data for a specific symbol."""
    symbol = data.get('symbol')
    if symbol in SYMBOLS:
        with data_lock:
            # Send current tick data for the requested symbol
            tick_list = list(tick_data[symbol])
            emit('initial_tick_data', {
                'symbol': symbol,
                'data': tick_list
            }, namespace='/')

            # Send current candlestick data for each interval
            for interval in INTERVALS:
                recent_candles = sorted(candlestick_data[symbol][interval].items())[-100:]
                formatted_candles = [
                    {'time': ts, 'open': c['open'], 'high': c['high'], 'low': c['low'], 'close': c['close']}
                    for ts, c in recent_candles
                ]
                emit('initial_candlestick_data', {
                    'symbol': symbol,
                    'interval': interval,
                    'data': formatted_candles
                }, namespace='/')

@socketio.on('disconnect')
def handle_disconnect():
    """Handles client disconnections."""
    print('Client disconnected')

# --- Main execution ---
def start_deriv_websocket_thread():
    """Starts the Deriv WebSocket connection in a separate thread."""
    asyncio.run(connect_to_deriv_ws())

if __name__ == '__main__':
    initialize_candlestick_data()
    # Start the Deriv WebSocket connection in a separate thread
    deriv_thread = threading.Thread(target=start_deriv_websocket_thread, daemon=True)
    deriv_thread.start()
    # Run the Flask-SocketIO server
    socketio.run(app, host='0.0.0.0', port=5000, allow_unsafe_werkzeug=True) # allow_unsafe_werkzeug for development
