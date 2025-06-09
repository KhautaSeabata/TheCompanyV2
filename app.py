import asyncio
import websockets
import json
import threading
import time
from datetime import datetime
from flask import Flask, render_template, jsonify
from flask_socketio import SocketIO
import requests
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key'
socketio = SocketIO(app, cors_allowed_origins="*")

# Firebase configuration
FIREBASE_URL = "https://company-bdb78-default-rtdb.firebaseio.com"
TICKS_NODE = "volatility25_ticks"

# Global variables
latest_ticks = []
MAX_TICKS = 950

class DerivWebSocket:
    def __init__(self):
        self.websocket = None
        self.running = False
        
    async def connect_and_subscribe(self):
        uri = "wss://ws.binaryws.com/websockets/v3?app_id=1089"
        
        try:
            async with websockets.connect(uri) as websocket:
                self.websocket = websocket
                self.running = True
                
                # Subscribe to Volatility 25 ticks
                subscribe_message = {
                    "ticks": "R_25",
                    "subscribe": 1
                }
                
                await websocket.send(json.dumps(subscribe_message))
                print("Connected to Deriv WebSocket and subscribed to Volatility 25")
                
                async for message in websocket:
                    if not self.running:
                        break
                        
                    data = json.loads(message)
                    
                    if 'tick' in data:
                        tick_data = {
                            'price': data['tick']['quote'],
                            'timestamp': data['tick']['epoch'],
                            'datetime': datetime.fromtimestamp(data['tick']['epoch']).isoformat(),
                            'symbol': data['tick']['symbol']
                        }
                        
                        # Store in Firebase
                        self.store_tick_in_firebase(tick_data)
                        
                        # Update local cache
                        global latest_ticks
                        latest_ticks.append(tick_data)
                        if len(latest_ticks) > MAX_TICKS:
                            latest_ticks.pop(0)
                        
                        # Emit to frontend
                        socketio.emit('new_tick', tick_data)
                        
                        print(f"Tick: {tick_data['price']} at {tick_data['datetime']}")
                        
        except Exception as e:
            print(f"WebSocket error: {e}")
            # Retry connection after 5 seconds
            await asyncio.sleep(5)
            if self.running:
                await self.connect_and_subscribe()
    
    def store_tick_in_firebase(self, tick_data):
        try:
            # Use timestamp as key to avoid duplicates
            tick_key = str(tick_data['timestamp'])
            url = f"{FIREBASE_URL}/{TICKS_NODE}/{tick_key}.json"
            
            response = requests.put(url, json=tick_data, timeout=5)
            
            if response.status_code == 200:
                print(f"Stored tick in Firebase: {tick_key}")
            else:
                print(f"Failed to store tick in Firebase: {response.status_code}")
                
        except Exception as e:
            print(f"Firebase storage error: {e}")
    
    def stop(self):
        self.running = False

# Global WebSocket instance
ws_client = DerivWebSocket()

def run_websocket():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(ws_client.connect_and_subscribe())

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/ticks')
def get_ticks():
    try:
        # Get ticks from Firebase
        url = f"{FIREBASE_URL}/{TICKS_NODE}.json"
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            firebase_data = response.json()
            if firebase_data:
                # Convert to list and sort by timestamp
                ticks = []
                for key, tick in firebase_data.items():
                    ticks.append(tick)
                
                # Sort by timestamp and get latest 950
                ticks.sort(key=lambda x: x['timestamp'])
                ticks = ticks[-MAX_TICKS:]
                
                return jsonify(ticks)
        
        return jsonify(latest_ticks)
        
    except Exception as e:
        print(f"Error getting ticks: {e}")
        return jsonify(latest_ticks)

@socketio.on('connect')
def handle_connect():
    print('Client connected')

@socketio.on('disconnect')
def handle_disconnect():
    print('Client disconnected')

if __name__ == '__main__':
    # Start WebSocket client in a separate thread
    ws_thread = threading.Thread(target=run_websocket, daemon=True)
    ws_thread.start()
    
    # Get port from environment (for Render deployment)
    port = int(os.environ.get('PORT', 5000))
    
    # Run Flask app
    socketio.run(app, host='0.0.0.0', port=port, debug=False)