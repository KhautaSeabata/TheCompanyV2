import asyncio
import json
import time
from collections import deque
from flask import Flask, render_template
from flask_socketio import SocketIO, emit
import websockets
import threading

app = Flask(__name__)
socketio = SocketIO(app, async_mode='eventlet')  # Use eventlet for WebSocket support

# Deriv config
DERIV_APP_ID = 1089
DERIV_WS_URL = f"wss://ws.derivws.com/websockets/v3?app_id={DERIV_APP_ID}"
DERIV_API_TOKEN = "bK3fhHLYrP1sMEb"

# Work only with Volatility 10 Index
SYMBOL = "R_10"
INTERVALS = [60, 300, 900]  # 1 min, 5 min, 15 min

candlestick_data = {SYMBOL: {interval: {} for interval in INTERVALS}}
tick_data = {SYMBOL: deque(maxlen=200)}
data_lock = threading.Lock()

def process_tick(price, tick_time):
    with data_lock:
        # Store tick
        tick_data[SYMBOL].append({'time': tick_time, 'value': price})

        # Update candlesticks
        for interval in INTERVALS:
            candle_start = (tick_time // interval) * interval
            candles = candlestick_data[SYMBOL][interval]

            if candle_start not in candles:
                candles[candle_start] = {
                    'open': price, 'high': price, 'low': price, 'close': price, 'volume': 0
                }
            else:
                c = candles[candle_start]
                c['high'] = max(c['high'], price)
                c['low'] = min(c['low'], price)
                c['close'] = price

            socketio.emit('candlestick_update', {
                'symbol': SYMBOL,
                'interval': interval,
                'data': {
                    'time': candle_start,
                    'open': candles[candle_start]['open'],
                    'high': candles[candle_start]['high'],
                    'low': candles[candle_start]['low'],
                    'close': candles[candle_start]['close']
                }
            })

        # Emit tick update
        socketio.emit('tick_update', {
            'symbol': SYMBOL,
            'data': {'time': tick_time, 'value': price}
        })

async def connect_to_deriv_ws():
    while True:
        try:
            async with websockets.connect(DERIV_WS_URL) as ws:
                print("Connected to Deriv WebSocket")

                await ws.send(json.dumps({"authorize": DERIV_API_TOKEN}))
                auth_data = json.loads(await ws.recv())
                print("Authorized:", auth_data.get('authorize', {}).get('loginid', ''))

                await ws.send(json.dumps({"ticks": SYMBOL, "subscribe": 1}))
                print(f"Subscribed to ticks for {SYMBOL}")

                while True:
                    msg = await ws.recv()
                    data = json.loads(msg)
                    if data.get('msg_type') == 'tick':
                        tick = data['tick']
                        process_tick(float(tick['quote']), int(tick['epoch']))
        except Exception as e:
            print(f"WebSocket error: {e} — reconnecting in 5s")
            await asyncio.sleep(5)

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('connect')
def handle_connect():
    print('Client connected')
    with data_lock:
        emit('initial_tick_data', {
            'symbol': SYMBOL,
            'data': list(tick_data[SYMBOL])
        })
        for interval in INTERVALS:
            candles = sorted(candlestick_data[SYMBOL][interval].items())[-100:]
            emit('initial_candlestick_data', {
                'symbol': SYMBOL,
                'interval': interval,
                'data': [
                    {'time': ts, 'open': c['open'], 'high': c['high'], 'low': c['low'], 'close': c['close']}
                    for ts, c in candles
                ]
            })

@socketio.on('disconnect')
def handle_disconnect():
    print('Client disconnected')

def start_ws_thread():
    asyncio.run(connect_to_deriv_ws())

if __name__ == '__main__':
    threading.Thread(target=start_ws_thread, daemon=True).start()
    socketio.run(app, host='0.0.0.0', port=5000)
