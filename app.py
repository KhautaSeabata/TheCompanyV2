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
TICKS_NODE = "ticks/R_25"

# Global variables
latest_ticks = []
MAX_TICKS = 950

class DerivWebSocket:
    def __init__(self):
        self.websocket = None
        self.running = False
        self.connected = False
        
    async def connect_and_subscribe(self):
        max_retries = 10
        retry_count = 0
        
        while retry_count < max_retries and self.running:
            try:
                uri = "wss://ws.binaryws.com/websockets/v3?app_id=1089"
                print(f"Attempting to connect to Deriv WebSocket... (Attempt {retry_count + 1})")
                
                async with websockets.connect(
                    uri,
                    ping_interval=20,
                    ping_timeout=10,
                    close_timeout=10
                ) as websocket:
                    self.websocket = websocket
                    self.connected = True
                    print("✅ Connected to Deriv WebSocket!")
                    
                    # Subscribe to Volatility 25 ticks
                    subscribe_message = {
                        "ticks": "R_25",
                        "subscribe": 1
                    }
                    
                    await websocket.send(json.dumps(subscribe_message))
                    print("📡 Subscribed to Volatility 25 (R_25) ticks")
                    
                    # Reset retry count on successful connection
                    retry_count = 0
                    
                    # Listen for messages
                    async for message in websocket:
                        try:
                            data = json.loads(message)
                            print(f"📨 Received message: {data}")
                            
                            # Handle subscription confirmation
                            if 'echo_req' in data and data.get('msg_type') == 'ticks':
                                print("✅ Subscription confirmed!")
                                continue
                            
                            # Handle tick data
                            if 'tick' in data:
                                print(f"📈 New tick received: {data['tick']}")
                                
                                # Structure exactly like your Firebase example
                                tick_data = {
                                    'epoch': data['tick']['epoch'],
                                    'quote': data['tick']['quote'],
                                    'symbol': data['tick']['symbol']
                                }
                                
                                # Store in Firebase with auto-generated key
                                firebase_key = self.store_tick_in_firebase(tick_data)
                                
                                if firebase_key:
                                    # Immediately fetch and emit the stored data
                                    stored_tick = self.get_tick_from_firebase(firebase_key)
                                    if stored_tick:
                                        # Add the Firebase key for reference
                                        stored_tick['firebase_key'] = firebase_key
                                        
                                        # Update local cache
                                        global latest_ticks
                                        latest_ticks.append(stored_tick)
                                        if len(latest_ticks) > MAX_TICKS:
                                            latest_ticks.pop(0)
                                        
                                        # Emit to frontend
                                        socketio.emit('new_tick', stored_tick)
                                        
                                        print(f"✅ Tick processed: {stored_tick['quote']} at epoch {stored_tick['epoch']} (Key: {firebase_key})")
                            
                            # Handle errors
                            elif 'error' in data:
                                print(f"❌ WebSocket error received: {data['error']}")
                                
                        except json.JSONDecodeError as e:
                            print(f"❌ JSON decode error: {e}")
                            continue
                        except Exception as e:
                            print(f"❌ Error processing message: {e}")
                            continue
                            
            except websockets.exceptions.ConnectionClosed as e:
                self.connected = False
                print(f"🔌 WebSocket connection closed: {e}")
            except websockets.exceptions.WebSocketException as e:
                self.connected = False
                print(f"❌ WebSocket exception: {e}")
            except Exception as e:
                self.connected = False
                print(f"❌ Unexpected error: {e}")
            
            if self.running:
                retry_count += 1
                wait_time = min(5 * retry_count, 30)  # Progressive backoff, max 30 seconds
                print(f"⏳ Retrying connection in {wait_time} seconds... (Attempt {retry_count}/{max_retries})")
                await asyncio.sleep(wait_time)
        
        if retry_count >= max_retries:
            print(f"❌ Failed to connect after {max_retries} attempts. Stopping...")
        
        self.connected = False
    
    def store_tick_in_firebase(self, tick_data):
        try:
            # Post to Firebase to get auto-generated key (like -OSKoc6xIkYxCtFUUzPr)
            url = f"{FIREBASE_URL}/{TICKS_NODE}.json"
            
            response = requests.post(url, json=tick_data, timeout=5)
            
            if response.status_code == 200:
                result = response.json()
                firebase_key = result.get('name')  # This is the auto-generated key
                print(f"Stored tick in Firebase with key: {firebase_key}")
                return firebase_key
            else:
                print(f"Failed to store tick in Firebase: {response.status_code}")
                return None
                
        except Exception as e:
            print(f"Firebase storage error: {e}")
            return None
    
    def get_tick_from_firebase(self, firebase_key):
        try:
            # Get the specific tick that was just stored
            url = f"{FIREBASE_URL}/{TICKS_NODE}/{firebase_key}.json"
            response = requests.get(url, timeout=5)
            
            if response.status_code == 200:
                return response.json()
            else:
                print(f"Failed to get tick from Firebase: {response.status_code}")
                return None
                
        except Exception as e:
            print(f"Firebase get error: {e}")
            return None
    
    def stop(self):
        self.running = False

# Global WebSocket instance
ws_client = DerivWebSocket()

def run_websocket():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # Set running flag before starting
    ws_client.running = True
    
    try:
        print("🚀 Starting WebSocket client...")
        loop.run_until_complete(ws_client.connect_and_subscribe())
    except Exception as e:
        print(f"❌ WebSocket thread error: {e}")
    finally:
        loop.close()
        print("🔚 WebSocket thread ended")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/ticks')
def get_ticks():
    try:
        # Get ticks from Firebase with the correct structure
        url = f"{FIREBASE_URL}/{TICKS_NODE}.json"
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            firebase_data = response.json()
            if firebase_data:
                # Convert to list and sort by epoch
                ticks = []
                for key, tick in firebase_data.items():
                    tick['firebase_key'] = key  # Add the Firebase key
                    ticks.append(tick)
                
                # Sort by epoch and get latest 950
                ticks.sort(key=lambda x: x['epoch'])
                ticks = ticks[-MAX_TICKS:]
                
                return jsonify(ticks)
        
        return jsonify(latest_ticks)
        
    except Exception as e:
        print(f"Error getting ticks: {e}")
        return jsonify(latest_ticks)

@app.route('/api/status')
def get_status():
    return jsonify({
        'websocket_connected': ws_client.connected,
        'websocket_running': ws_client.running,
        'total_ticks': len(latest_ticks)
    })

@socketio.on('connect')
def handle_connect():
    print('🌐 Client connected to SocketIO')

@socketio.on('disconnect')
def handle_disconnect():
    print('🔌 Client disconnected from SocketIO')

if __name__ == '__main__':
    # Start WebSocket client in a separate thread
    ws_thread = threading.Thread(target=run_websocket, daemon=True)
    ws_thread.start()
    
    # Get port from environment (for Render deployment)
    port = int(os.environ.get('PORT', 5000))
    
    # Run Flask app
    socketio.run(app, host='0.0.0.0', port=port, debug=False)