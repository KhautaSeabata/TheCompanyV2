import asyncio
import json
from collections import deque
from flask import Flask, render_template
from flask_socketio import SocketIO, emit
import websockets
import threading
from trading_logic import TradingAlerts, TrendlineAnalyzer

# Flask app setup
app = Flask(__name__)
socketio = SocketIO(app, async_mode='threading', cors_allowed_origins="*")

# Deriv API configuration
DERIV_APP_ID = 1089
DERIV_WS_URL = f"wss://ws.derivws.com/websockets/v3?app_id={DERIV_APP_ID}"
DERIV_API_TOKEN = "bK3fhHLYrP1sMEb"  # Replace with your actual Deriv API token

# Data storage
candlestick_data = {}
SYMBOLS = ["R_100", "R_75", "R_50", "R_25"]
INTERVAL = 60  # 1 minute in seconds

# Lock for thread-safe access
data_lock = threading.Lock()

# Initialize trading alerts and analyzer
trading_alerts = TradingAlerts()
trendline_analyzer = TrendlineAnalyzer()

# Initialize candlestick data
def initialize_candlestick_data():
    with data_lock:
        for symbol in SYMBOLS:
            candlestick_data[symbol] = {INTERVAL: deque(maxlen=100)}  # Store last 100 candles

def process_candlestick(symbol, candle):
    with data_lock:
        formatted_candle = {
            'time': candle['epoch'],
            'open': float(candle['open']),
            'high': float(candle['high']),
            'low': float(candle['low']),
            'close': float(candle['close']),
            'volume': float(candle.get('volume', 0))
        }
        candlestick_data[symbol][INTERVAL].append(formatted_candle)

        # Emit to frontend
        socketio.emit('candlestick_update', {
            'symbol': symbol,
            'interval': INTERVAL,
            'data': formatted_candle
        }, namespace='/')

        # Generate trading signals
        prices = [c['close'] for c in candlestick_data[symbol][INTERVAL]]
        support_levels, resistance_levels = trendline_analyzer.find_support_resistance(prices)
        signals = trendline_analyzer.generate_enhanced_signals(prices, support_levels, resistance_levels)
        
        # Add signals as alerts
        for signal in signals:
            alert = trading_alerts.add_alert(
                alert_type=signal['type'],
                direction=signal['action'],
                price=signal['entry_price'],
                confidence=signal['confidence'],
                description=signal['description'],
                expiry_minutes=5
            )
            if alert:
                socketio.emit('alert_update', alert, namespace='/')

async def connect_to_deriv_ws():
    while True:
        try:
            async with websockets.connect(DERIV_WS_URL) as websocket:
                print(f"Connected to Deriv WebSocket: {DERIV_WS_URL}")

                # Authorize
                await websocket.send(json.dumps({"authorize": DERIV_API_TOKEN}))
                auth_response = await websocket.recv()
                auth_data = json.loads(auth_response)
                if auth_data.get('msg_type') == 'authorize' and auth_data.get('authorize'):
                    print(f"Authorized: {auth_data['authorize']['loginid']}")
                else:
                    print(f"Authorization Error: {auth_data.get('error', {}).get('message', 'Unknown error')}")
                    await asyncio.sleep(5)
                    continue

                # Fetch historical candlestick data
                for symbol in SYMBOLS:
                    await websocket.send(json.dumps({
                        "candles": symbol,
                        "style": "candles",
                        "granularity": INTERVAL,
                        "count": 100
                    }))
                
                # Subscribe to candlestick updates
                for symbol in SYMBOLS:
                    await websocket.send(json.dumps({
                        "ticks_history": symbol,
                        "style": "candles",
                        "granularity": INTERVAL,
                        "subscribe": 1
                    }))

                while True:
                    message = await websocket.recv()
                    data = json.loads(message)
                    if data.get('msg_type') == 'candles':
                        candles = data.get('candles', [])
                        with data_lock:
                            candlestick_data[data['echo_req']['candles']][INTERVAL].extend([
                                {
                                    'time': c['epoch'],
                                    'open': float(c['open']),
                                    'high': float(c['high']),
                                    'low': float(c['low']),
                                    'close': float(c['close']),
                                    'volume': float(c.get('volume', 0))
                                } for c in candles
                            ])
                            socketio.emit('initial_candlestick_data', {
                                'symbol': data['echo_req']['candles'],
                                'interval': INTERVAL,
                                'data': list(candlestick_data[data['echo_req']['candles']][INTERVAL])
                            }, namespace='/')
                    elif data.get('msg_type') == 'history' and data.get('candles'):
                        process_candlestick(data['echo_req']['ticks_history'], data['candles'][-1])
                    elif data.get('error'):
                        print(f"Deriv API Error: {data['error']['message']}")

        except websockets.exceptions.ConnectionClosedOK:
            print("WebSocket closed cleanly. Reconnecting...")
        except websockets.exceptions.ConnectionClosedError as e:
            print(f"WebSocket error: {e}. Reconnecting in 5s...")
            await asyncio.sleep(5)
        except Exception as e:
            print(f"Unexpected error: {e}. Reconnecting in 5s...")
            await asyncio.sleep(5)

# Flask Routes
@app.route('/')
def index():
    return render_template('index.html')

# SocketIO Events
@socketio.on('connect')
def handle_connect():
    print('Client connected')
    with data_lock:
        for symbol in SYMBOLS:
            emit('initial_candlestick_data', {
                'symbol': symbol,
                'interval': INTERVAL,
                'data': list(candlestick_data[symbol][INTERVAL])
            }, namespace='/')

@socketio.on('request_initial_data')
def handle_request_initial_data(data):
    symbol = data.get('symbol')
    if symbol in SYMBOLS:
        with data_lock:
            emit('initial_candlestick_data', {
                'symbol': symbol,
                'interval': INTERVAL,
                'data': list(candlestick_data[symbol][INTERVAL])
            }, namespace='/')

@socketio.on('disconnect')
def handle_disconnect():
    print('Client disconnected')

# Main execution
def start_deriv_websocket_thread():
    asyncio.run(connect_to_deriv_ws())

if __name__ == '__main__':
    initialize_candlestick_data()
    deriv_thread = threading.Thread(target=start_deriv_websocket_thread, daemon=True)
    deriv_thread.start()
    socketio.run(app, host='0.0.0.0', port=5000)
