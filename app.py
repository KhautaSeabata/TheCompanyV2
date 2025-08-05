import asyncio
import json
import os
import logging
from collections import deque
from flask import Flask, render_template
from flask_socketio import SocketIO, emit
import websockets
import threading
from trading_logic import TradingAlerts, TrendlineAnalyzer

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Flask app setup
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'fallback_dev_key_1234567890')  # Required for SocketIO
socketio = SocketIO()
socketio.init_app(app, async_mode='gevent', cors_allowed_origins="https://thecompanyv2.onrender.com")

# Deriv API configuration
DERIV_APP_ID = 1089
DERIV_WS_URL = f"wss://ws.derivws.com/websockets/v3?app_id={DERIV_APP_ID}"
DERIV_API_TOKEN = os.getenv('DERIV_API_TOKEN', 'bK3fhHLYrP1sMEb')

# Data storage
tick_data = deque(maxlen=100)  # Reduced to 100 to prevent memory issues
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
        logger.info(f"Processed tick: time={tick_time}, price={price}")

        # Emit to frontend
        socketio.emit('tick_update', {
            'symbol': SYMBOL,
            'data': formatted_tick
        }, namespace='/')
        logger.info(f"Emitted tick_update: {formatted_tick}")

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
                logger.info(f"Emitted alert_update: {alert}")

async def connect_to_deriv_ws():
    while True:
        try:
            async with websockets.connect(DERIV_WS_URL) as websocket:
                logger.info(f"Connected to Deriv WebSocket: {DERIV_WS_URL}")

                # Authorize
                await websocket.send(json.dumps({"authorize": DERIV_API_TOKEN}))
                auth_response = await websocket.recv()
                auth_data = json.loads(auth_response)
                if auth_data.get('msg_type') == 'authorize' and auth_data.get('authorize'):
                    logger.info(f"Authorized: {auth_data['authorize']['loginid']}")
                else:
                    error_msg = auth_data.get('error', {}).get('message', 'Unknown error')
                    logger.error(f"Authorization Error: {error_msg}")
                    await asyncio.sleep(5)
                    continue

                # Fetch historical tick data
                await websocket.send(json.dumps({
                    "ticks_history": SYMBOL,
                    "count": 100,
                    "end": "latest",
                    "style": "ticks"
                }))
                logger.info(f"Requested historical ticks for {SYMBOL}")

                # Subscribe to real-time tick data
                await websocket.send(json.dumps({
                    "ticks": SYMBOL,
                    "subscribe": 1
                }))
                logger.info(f"Subscribed to ticks for {SYMBOL}")

                while True:
                    message = await websocket.recv()
                    data = json.loads(message)
                    if data.get('msg_type') == 'history' and data.get('prices'):
                        with data_lock:
                            tick_data.clear()  # Clear old data
                            tick_data.extend([{
                                'time': int(t['epoch']),
                                'value': float(t['quote'])
                            } for t in data['prices']])
                            socketio.emit('initial_tick_data', {
                                'symbol': SYMBOL,
                                'data': list(tick_data)
                            }, namespace='/')
                            logger.info(f"Emitted historical tick data: {len(tick_data)} points")
                    elif data.get('msg_type') == 'tick':
                        price = float(data['tick']['quote'])
                        tick_time = int(data['tick']['epoch'])
                        logger.info(f"Received tick: symbol={data['tick']['symbol']}, price={price}, time={tick_time}")
                        process_tick(price, tick_time)
                    elif data.get('error'):
                        logger.error(f"Deriv API Error: {data['error']['message']}")

        except websockets.exceptions.ConnectionClosedOK:
            logger.warning("WebSocket closed cleanly. Reconnecting...")
        except websockets.exceptions.ConnectionClosedError as e:
            logger.error(f"WebSocket error: {e}. Reconnecting in 5s...")
            await asyncio.sleep(5)
        except Exception as e:
            logger.error(f"Unexpected error: {e}. Reconnecting in 5s...")
            await asyncio.sleep(5)

# Flask Routes
@app.route('/')
def index():
    logger.info("Serving index.html")
    return render_template('index.html')

# SocketIO Events
@socketio.on('connect')
def handle_connect():
    logger.info('Client connected')
    with data_lock:
        emit('initial_tick_data', {
            'symbol': SYMBOL,
            'data': list(tick_data)
        }, namespace='/')
        logger.info(f"Emitted initial_tick_data: {len(tick_data)} points")

@socketio.on('request_initial_data')
def handle_request_initial_data(data):
    if data.get('symbol') == SYMBOL:
        with data_lock:
            emit('initial_tick_data', {
                'symbol': SYMBOL,
                'data': list(tick_data)
            }, namespace='/')
            logger.info(f"Emitted initial_tick_data on request: {len(tick_data)} points")

@socketio.on('disconnect')
def handle_disconnect():
    logger.info('Client disconnected')

# Start WebSocket thread
deriv_thread = threading.Thread(target=lambda: asyncio.run(connect_to_deriv_ws()), daemon=True)
deriv_thread.start()

if __name__ == '__main__':
    logger.info("Starting Flask development server")
    socketio.run(app, host='0.0.0.0', port=5000)
