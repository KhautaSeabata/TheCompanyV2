import asyncio
import websockets
import json
import threading
import requests
from flask import Flask, render_template, jsonify
from flask_socketio import SocketIO

app = Flask(__name__)
app.config['SECRET_KEY'] = 'deriv-live-ticks'
socketio = SocketIO(app, cors_allowed_origins="*")

# Firebase configuration
FIREBASE_URL = "https://company-bdb78-default-rtdb.firebaseio.com"
TICKS_NODE = "live_ticks"

class DerivTicker:
    def __init__(self):
        self.websocket = None
        self.running = False
        self.connected = False
        
    async def start(self):
        self.running = True
        
        while self.running:
            try:
                # Connect to Deriv WebSocket
                uri = "wss://ws.deriv.com/websockets/v3?app_id=1089"
                print("🔗 Connecting to Deriv...")
                
                async with websockets.connect(uri) as websocket:
                    self.websocket = websocket
                    self.connected = True
                    print("✅ Connected to Deriv!")
                    
                    # Subscribe to R_25 ticks
                    await websocket.send(json.dumps({
                        "ticks": "R_25",
                        "subscribe": 1
                    }))
                    print("📡 Subscribed to R_25 ticks")
                    
                    # Listen for ticks
                    async for message in websocket:
                        data = json.loads(message)
                        
                        # Process tick data
                        if 'tick' in data:
                            tick = {
                                'price': data['tick']['quote'],
                                'time': data['tick']['epoch'],
                                'symbol': data['tick']['symbol']
                            }
                            
                            # Store in Firebase and emit to frontend
                            self.process_tick(tick)
                            
            except Exception as e:
                self.connected = False
                print(f"❌ Connection error: {e}")
                await asyncio.sleep(5)  # Wait before retry
    
    def process_tick(self, tick):
        """Store tick in Firebase and emit to frontend"""
        try:
            # Store in Firebase
            url = f"{FIREBASE_URL}/{TICKS_NODE}.json"
            response = requests.post(url, json=tick, timeout=3)
            
            if response.status_code == 200:
                # Emit to frontend immediately
                socketio.emit('new_tick', tick)
                print(f"📈 Tick: {tick['price']} at {tick['time']}")
            
        except Exception as e:
            print(f"❌ Error processing tick: {e}")
    
    def stop(self):
        self.running = False

# Global ticker instance
ticker = DerivTicker()

def run_ticker():
    """Run ticker in separate thread"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(ticker.start())

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/recent-ticks')
def get_recent_ticks():
    """Get recent ticks from Firebase"""
    try:
        url = f"{FIREBASE_URL}/{TICKS_NODE}.json?orderBy=\"time\"&limitToLast=100"
        response = requests.get(url, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            if data:
                # Convert to list and sort by time
                ticks = list(data.values())
                ticks.sort(key=lambda x: x['time'])
                return jsonify(ticks)
        
        return jsonify([])
        
    except Exception as e:
        print(f"❌ Error fetching ticks: {e}")
        return jsonify([])

@app.route('/api/status')
def get_status():
    return jsonify({
        'connected': ticker.connected,
        'running': ticker.running
    })

@socketio.on('connect')
def handle_connect():
    print('🌐 Client connected')

if __name__ == '__main__':
    # Start ticker in background
    ticker_thread = threading.Thread(target=run_ticker, daemon=True)
    ticker_thread.start()
    
    # Run Flask app
    socketio.run(app, host='0.0.0.0', port=5000, debug=False)
