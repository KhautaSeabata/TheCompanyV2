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
socketio = SocketIO(app, async_mode='gevent', cors_allowed_origins="*")

# Deriv API configuration
DERIV_APP_ID = 1089
DERIV_WS_URL = f"wss://ws.derivws.com/websockets/v3?app_id={DERIV_APP_ID}"
DERIV_API_TOKEN = os.getenv('DERIV_API_TOKEN', 'bK3fhHLYrP1sMEb')  # Use environment variable for production

# Data storage
tick_data = deque(maxlen=200)  # Store last 200 ticks for R_75
SYMBOL = "R_75"

# Lock for thread-safe access
data_lock = threading.Lock()

# Initialize trading alerts and analyzer
trading_alerts = TradingAlerts()
trendline_analyzer = TrendlineAnalyzer()

def process_tick(price, tick_time):
    with data_lock:
        formatted_tick = {
            'time': tick_time,
            'value': float(price)
        }
        tick_data.append(formatted_tick)

        # Emit to frontend
        socketio.emit('tick_update', {
            'symbol': SYMBOL,
            'data': formatted_tick
        }, namespace='/')

        # Generate trading signals
        prices = [t['value'] for t in tick_data]
        support_levels, resistance_levels = trendline_analyzer.find_support_resistance(prices)
        signals = trendline_analyzer.generate_enhanced_signals(prices, support_levels, resistance_levels)
        
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

                # Subscribe to tick data for R_75
                await websocket.send(json.dumps({
                    "ticks": SYMBOL,
                    "subscribe": 1
                }))
                print(f"Subscribed to ticks for {SYMBOL}")

                while True:
                    message = await websocket.recv()
                    data = json.loads(message)
                    if data.get('msg_type') == 'tick':
                        price = float(data['tick']['quote'])
                        tick_time = int(data['tick']['epoch'])
                        process_tick(price, tick_time)
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
        emit('initial_tick_data', {
            'symbol': SYMBOL,
            'data': list(tick_data)
        }, namespace='/')

@socketio.on('request_initial_data')
def handle_request_initial_data(data):
    if data.get('symbol') == SYMBOL:
        with data_lock:
            emit('initial_tick_data', {
                'symbol': SYMBOL,
                'data': list(tick_data)
            }, namespace='/')

@socketio.on('disconnect')
def handle_disconnect():
    print('Client disconnected')

# Start WebSocket thread
deriv_thread = threading.Thread(target=lambda: asyncio.run(connect_to_deriv_ws()), daemon=True)
deriv_thread.start()

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)
