import asyncio
import json
import time
from collections import deque
from flask import Flask, render_template
from flask_socketio import SocketIO, emit
import websockets
import threading

app = Flask(__name__)
# No SECRET_KEY used — safe for simple WebSocket dashboard apps in dev
socketio = SocketIO(app, async_mode='threading')

DERIV_APP_ID = 1089
DERIV_WS_URL = f"wss://ws.derivws.com/websockets/v3?app_id={DERIV_APP_ID}"
DERIV_API_TOKEN = "bK3fhHLYrP1sMEb"

candlestick_data = {}
tick_data = {}
SYMBOLS = ["R_100", "R_75", "R_50", "R_25"]
INTERVALS = [60, 300, 900]

data_lock = threading.Lock()

def initialize_candlestick_data():
    with data_lock:
        for symbol in SYMBOLS:
            candlestick_data[symbol] = {}
            tick_data[symbol] = deque(maxlen=200)
            for interval in INTERVALS:
                candlestick_data[symbol][interval] = {}

def process_tick(symbol, price, tick_time):
    with data_lock:
        tick_data[symbol].append({'time': tick_time, 'value': price})
        for interval in INTERVALS:
            candle_start = (tick_time // interval) * interval
            if candle_start not in candlestick_data[symbol][interval]:
                candlestick_data[symbol][interval][candle_start] = {
                    'open': price,
                    'high': price,
                    'low': price,
                    'close': price,
                    'volume': 0
                }
            else:
                c = candlestick_data[symbol][interval][candle_start]
                c['high'] = max(c['high'], price)
                c['low'] = min(c['low'], price)
                c['close'] = price

            socketio.emit('candlestick_update', {
                'symbol': symbol,
                'interval': interval,
                'data': {
                    'time': candle_start,
                    'open': c['open'],
                    'high': c['high'],
                    'low': c['low'],
                    'close': c['close']
                }
            })

        socketio.emit('tick_update', {
            'symbol': symbol,
            'data': {'time': tick_time, 'value': price}
        })

async def connect_to_deriv_ws():
    while True:
        try:
            async with websockets.connect(DERIV_WS_URL) as ws:
                print("Connected to Deriv WebSocket")

                await ws.send(json.dumps({"authorize": DERIV_API_TOKEN}))
                auth_data = json.loads(await ws.recv())
                print("Authorized as:", auth_data.get('authorize', {}).get('loginid', ''))

                for symbol in SYMBOLS:
                    await ws.send(json.dumps({
                        "ticks": symbol,
                        "subscribe": 1
                    }))

                while True:
                    msg = await ws.recv()
                    data = json.loads(msg)
                    if data.get('msg_type') == 'tick':
                        tick = data['tick']
                        process_tick(
                            tick['symbol'],
                            float(tick['quote']),
                            int(tick['epoch'])
                        )

        except Exception as e:
            print(f"WebSocket error: {e}. Reconnecting in 5s...")
            await asyncio.sleep(5)

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('connect')
def handle_connect():
    print('Client connected')
    with data_lock:
        for symbol in SYMBOLS:
            emit('initial_tick_data', {
                'symbol': symbol,
                'data': list(tick_data[symbol])
            })
            for interval in INTERVALS:
                candles = sorted(candlestick_data[symbol][interval].items())[-100:]
                emit('initial_candlestick_data', {
                    'symbol': symbol,
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
    initialize_candlestick_data()
    threading.Thread(target=start_ws_thread, daemon=True).start()
    socketio.run(app, host='0.0.0.0', port=5000, allow_unsafe_werkzeug=True)
