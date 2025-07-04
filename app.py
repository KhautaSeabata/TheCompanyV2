from flask import Flask, render_template, jsonify, request
import asyncio
import websockets
import json
import requests
import threading
import time
from datetime import datetime
import uuid
import numpy as np
from scipy import stats
import pandas as pd

app = Flask(__name__)

# Firebase configuration
FIREBASE_URL = "https://company-bdb78-default-rtdb.firebaseio.com"
FIREBASE_TICKS_PATH = "/ticks.json"
FIREBASE_1MIN_PATH = "/1minVix25.json"
FIREBASE_5MIN_PATH = "/5minVix25.json"

# Deriv WebSocket configuration
DERIV_WS_URL = "wss://ws.derivws.com/websockets/v3?app_id=1089"

# Global variables to store latest data
latest_tick = {}
current_1min_candle = {}
current_5min_candle = {}
candle_buffers = {
    '1min': [],
    '5min': []
}

class TrendlineAnalyzer:
    """Advanced trendline analysis for financial data"""
    
    @staticmethod
    def find_support_resistance(prices, window=5):
        """Find support and resistance levels using local minima and maxima"""
        if len(prices) < window * 2:
            return [], []
        
        # Convert to numpy array for easier manipulation
        prices_array = np.array(prices)
        
        # Find local minima (support levels)
        support_levels = []
        resistance_levels = []
        
        for i in range(window, len(prices_array) - window):
            # Check if current point is a local minimum
            if all(prices_array[i] <= prices_array[i-j] for j in range(1, window+1)) and \
               all(prices_array[i] <= prices_array[i+j] for j in range(1, window+1)):
                support_levels.append({'index': i, 'price': prices_array[i]})
            
            # Check if current point is a local maximum
            elif all(prices_array[i] >= prices_array[i-j] for j in range(1, window+1)) and \
                 all(prices_array[i] >= prices_array[i+j] for j in range(1, window+1)):
                resistance_levels.append({'index': i, 'price': prices_array[i]})
        
        return support_levels, resistance_levels
    
    @staticmethod
    def calculate_trendlines(support_levels, resistance_levels, prices):
        """Calculate trendlines from support and resistance levels"""
        trendlines = []
        
        # Calculate support trendlines
        if len(support_levels) >= 2:
            # Sort by index to get chronological order
            support_levels.sort(key=lambda x: x['index'])
            
            # Create trendline from first two significant support levels
            for i in range(len(support_levels) - 1):
                p1 = support_levels[i]
                p2 = support_levels[i + 1]
                
                # Calculate slope
                slope = (p2['price'] - p1['price']) / (p2['index'] - p1['index'])
                
                trendlines.append({
                    'type': 'support',
                    'slope': slope,
                    'intercept': p1['price'] - slope * p1['index'],
                    'start_index': p1['index'],
                    'end_index': p2['index'],
                    'start_price': p1['price'],
                    'end_price': p2['price']
                })
        
        # Calculate resistance trendlines
        if len(resistance_levels) >= 2:
            resistance_levels.sort(key=lambda x: x['index'])
            
            for i in range(len(resistance_levels) - 1):
                p1 = resistance_levels[i]
                p2 = resistance_levels[i + 1]
                
                slope = (p2['price'] - p1['price']) / (p2['index'] - p1['index'])
                
                trendlines.append({
                    'type': 'resistance',
                    'slope': slope,
                    'intercept': p1['price'] - slope * p1['index'],
                    'start_index': p1['index'],
                    'end_index': p2['index'],
                    'start_price': p1['price'],
                    'end_price': p2['price']
                })
        
        return trendlines
    
    @staticmethod
    def analyze_pattern_strength(prices, trendlines):
        """Analyze pattern strength based on price adherence to trendlines"""
        if not trendlines or len(prices) < 10:
            return 0.0
        
        total_strength = 0.0
        
        for trendline in trendlines:
            strength = 0.0
            touches = 0
            
            # Check how well prices follow the trendline
            for i in range(trendline['start_index'], min(trendline['end_index'] + 1, len(prices))):
                expected_price = trendline['slope'] * i + trendline['intercept']
                actual_price = prices[i]
                
                # Calculate deviation percentage
                deviation = abs(actual_price - expected_price) / expected_price
                
                # Count as a "touch" if deviation is less than 0.5%
                if deviation < 0.005:
                    touches += 1
                    strength += 1.0 - deviation
            
            # Normalize strength by length of trendline
            line_length = trendline['end_index'] - trendline['start_index'] + 1
            if line_length > 0:
                total_strength += (strength / line_length) * (touches / line_length)
        
        return min(total_strength / len(trendlines), 1.0) if trendlines else 0.0
    
    @staticmethod
    def calculate_breakout_probability(prices, trendlines, current_price):
        """Calculate probability of breakout based on current price position"""
        if not trendlines or len(prices) < 10:
            return 0.0
        
        breakout_signals = 0
        total_signals = 0
        
        for trendline in trendlines:
            # Get the current expected price on the trendline
            current_index = len(prices) - 1
            expected_price = trendline['slope'] * current_index + trendline['intercept']
            
            # Calculate how close we are to breaking the trendline
            if trendline['type'] == 'support':
                # For support, breakout is when price goes below
                deviation = (expected_price - current_price) / expected_price
                if deviation > 0.002:  # Price is approaching or breaking support
                    breakout_signals += min(deviation * 100, 1.0)
            else:  # resistance
                # For resistance, breakout is when price goes above
                deviation = (current_price - expected_price) / expected_price
                if deviation > 0.002:  # Price is approaching or breaking resistance
                    breakout_signals += min(deviation * 100, 1.0)
            
            total_signals += 1
        
        return min(breakout_signals / total_signals, 1.0) if total_signals > 0 else 0.0
    
    @staticmethod
    def generate_trading_signals(prices, trendlines, support_levels, resistance_levels):
        """Generate trading signals based on trendline analysis"""
        signals = []
        
        if len(prices) < 10:
            return signals
        
        current_price = prices[-1]
        
        # Check for support/resistance level breaks
        for support in support_levels[-3:]:  # Check last 3 support levels
            if abs(current_price - support['price']) / support['price'] < 0.001:
                signals.append({
                    'type': 'Support Test',
                    'direction': 'WATCH',
                    'confidence': 0.7,
                    'level': support['price'],
                    'description': f"Price testing support at {support['price']:.5f}"
                })
            elif current_price < support['price'] * 0.998:
                signals.append({
                    'type': 'Support Break',
                    'direction': 'DOWN',
                    'confidence': 0.8,
                    'level': support['price'],
                    'description': f"Price broke below support at {support['price']:.5f}"
                })
        
        for resistance in resistance_levels[-3:]:  # Check last 3 resistance levels
            if abs(current_price - resistance['price']) / resistance['price'] < 0.001:
                signals.append({
                    'type': 'Resistance Test',
                    'direction': 'WATCH',
                    'confidence': 0.7,
                    'level': resistance['price'],
                    'description': f"Price testing resistance at {resistance['price']:.5f}"
                })
            elif current_price > resistance['price'] * 1.002:
                signals.append({
                    'type': 'Resistance Break',
                    'direction': 'UP',
                    'confidence': 0.8,
                    'level': resistance['price'],
                    'description': f"Price broke above resistance at {resistance['price']:.5f}"
                })
        
        # Check trendline breaks
        for trendline in trendlines:
            current_index = len(prices) - 1
            expected_price = trendline['slope'] * current_index + trendline['intercept']
            
            if trendline['type'] == 'support' and current_price < expected_price * 0.998:
                signals.append({
                    'type': 'Trendline Break',
                    'direction': 'DOWN',
                    'confidence': 0.75,
                    'level': expected_price,
                    'description': f"Price broke below support trendline at {expected_price:.5f}"
                })
            elif trendline['type'] == 'resistance' and current_price > expected_price * 1.002:
                signals.append({
                    'type': 'Trendline Break',
                    'direction': 'UP',
                    'confidence': 0.75,
                    'level': expected_price,
                    'description': f"Price broke above resistance trendline at {expected_price:.5f}"
                })
        
        return signals[:5]  # Return top 5 signals

# Your existing DerivTickCollector class remains the same
class DerivTickCollector:
    def __init__(self):
        self.websocket = None
        self.running = False
        
    async def connect_and_subscribe(self):
        """Connect to Deriv WebSocket and subscribe to Volatility 25 ticks"""
        try:
            self.websocket = await websockets.connect(DERIV_WS_URL)
            
            # Subscribe to Volatility 25 (R_25) ticks
            subscribe_request = {
                "ticks": "R_25",
                "subscribe": 1
            }
            
            await self.websocket.send(json.dumps(subscribe_request))
            print("Connected to Deriv WebSocket and subscribed to R_25 ticks")
            
            # Listen for incoming ticks
            async for message in self.websocket:
                try:
                    data = json.loads(message)
                    if 'tick' in data:
                        await self.process_tick(data['tick'])
                except json.JSONDecodeError:
                    print(f"Failed to decode message: {message}")
                except Exception as e:
                    print(f"Error processing message: {e}")
                    
        except Exception as e:
            print(f"WebSocket connection error: {e}")
            # Retry connection after 5 seconds
            await asyncio.sleep(5)
            if self.running:
                await self.connect_and_subscribe()
    
    async def process_tick(self, tick_data):
        """Process incoming tick data and store to Firebase"""
        global latest_tick
        
        try:
            # Extract tick information
            tick_info = {
                "epoch": tick_data.get("epoch"),
                "quote": tick_data.get("quote"),
                "symbol": tick_data.get("symbol"),
                "timestamp": datetime.now().isoformat(),
                "id": str(uuid.uuid4())[:8]
            }
            
            latest_tick = tick_info
            print(f"Received tick: {tick_info}")
            
            # Store to Firebase
            await self.store_to_firebase(tick_info)
            
            # Process candlestick data
            await self.process_candlestick_data(tick_info)
            
        except Exception as e:
            print(f"Error processing tick: {e}")
    
    async def process_candlestick_data(self, tick_info):
        """Process tick data into 1min and 5min candlesticks"""
        try:
            epoch = tick_info['epoch']
            quote = float(tick_info['quote'])
            
            # Process 1-minute candlestick
            await self.update_candlestick(epoch, quote, '1min', 60)
            
            # Process 5-minute candlestick
            await self.update_candlestick(epoch, quote, '5min', 300)
            
        except Exception as e:
            print(f"Error processing candlestick data: {e}")
    
    async def update_candlestick(self, epoch, quote, timeframe, seconds):
        """Update candlestick data for given timeframe"""
        global current_1min_candle, current_5min_candle, candle_buffers
        
        try:
            # Calculate the start of the current candle period
            candle_start = (epoch // seconds) * seconds
            
            # Get the current candle reference
            current_candle = current_1min_candle if timeframe == '1min' else current_5min_candle
            
            # Initialize or update the current candle
            if candle_start not in current_candle or current_candle[candle_start] is None:
                # Start new candle
                current_candle[candle_start] = {
                    "epoch": candle_start,
                    "open": quote,
                    "high": quote,
                    "low": quote,
                    "close": quote,
                    "timestamp": datetime.fromtimestamp(candle_start).isoformat()
                }
                print(f"Started new {timeframe} candle at {candle_start}")
            else:
                # Update existing candle
                candle = current_candle[candle_start]
                candle["high"] = max(candle["high"], quote)
                candle["low"] = min(candle["low"], quote)
                candle["close"] = quote
                candle["timestamp"] = datetime.fromtimestamp(candle_start).isoformat()
            
            # Check if we need to close the previous candle
            current_time = epoch
            for candle_epoch, candle_data in list(current_candle.items()):
                if candle_epoch < candle_start:
                    # This candle is complete, store it
                    await self.store_candlestick_to_firebase(candle_data, timeframe)
                    
                    # Add to buffer for API access
                    candle_buffers[timeframe].append(candle_data)
                    if len(candle_buffers[timeframe]) > 100:  # Keep last 100 candles in memory
                        candle_buffers[timeframe].pop(0)
                    
                    # Remove from current candles
                    del current_candle[candle_epoch]
                    print(f"Completed {timeframe} candle: {candle_data}")
            
        except Exception as e:
            print(f"Error updating {timeframe} candlestick: {e}")
    
    async def store_candlestick_to_firebase(self, candle_data, timeframe):
        """Store candlestick data to Firebase"""
        try:
            # Determine Firebase path
            firebase_path = FIREBASE_1MIN_PATH if timeframe == '1min' else FIREBASE_5MIN_PATH
            
            # Get current candles from Firebase
            response = requests.get(f"{FIREBASE_URL}{firebase_path}")
            
            if response.status_code == 200:
                current_candles = response.json() or {}
            else:
                current_candles = {}
            
            # Add new candle with epoch as key
            candle_key = str(candle_data['epoch'])
            current_candles[candle_key] = candle_data
            
            # Keep only the latest 950 candles
            if len(current_candles) > 950:
                # Sort by epoch and keep the latest 950
                sorted_candles = dict(sorted(current_candles.items(), 
                                           key=lambda x: int(x[0]), 
                                           reverse=True)[:950])
                current_candles = sorted_candles
            
            # Update Firebase
            update_response = requests.put(
                f"{FIREBASE_URL}{firebase_path}",
                json=current_candles
            )
            
            if update_response.status_code == 200:
                print(f"Successfully stored {timeframe} candle to Firebase. Total candles: {len(current_candles)}")
            else:
                print(f"Failed to store {timeframe} candle to Firebase: {update_response.status_code}")
                
        except Exception as e:
            print(f"Error storing {timeframe} candle to Firebase: {e}")
    
    async def store_to_firebase(self, tick_data):
        """Store tick data to Firebase and maintain only 950 latest records"""
        try:
            # Get current ticks from Firebase
            response = requests.get(f"{FIREBASE_URL}{FIREBASE_TICKS_PATH}")
            
            if response.status_code == 200:
                current_ticks = response.json() or {}
            else:
                current_ticks = {}
            
            # Add new tick with timestamp as key
            tick_key = f"{tick_data['epoch']}_{tick_data['id']}"
            current_ticks[tick_key] = tick_data
            
            # Keep only the latest 950 ticks
            if len(current_ticks) > 950:
                # Sort by epoch (timestamp) and keep the latest 950
                sorted_ticks = dict(sorted(current_ticks.items(), 
                                         key=lambda x: x[1]['epoch'], 
                                         reverse=True)[:950])
                current_ticks = sorted_ticks
            
            # Update Firebase
            update_response = requests.put(
                f"{FIREBASE_URL}{FIREBASE_TICKS_PATH}",
                json=current_ticks
            )
            
            if update_response.status_code == 200:
                print(f"Successfully stored tick to Firebase. Total ticks: {len(current_ticks)}")
            else:
                print(f"Failed to store tick to Firebase: {update_response.status_code}")
                
        except Exception as e:
            print(f"Error storing to Firebase: {e}")
    
    def start(self):
        """Start the tick collector"""
        self.running = True
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self.connect_and_subscribe())

# Initialize tick collector
tick_collector = DerivTickCollector()

@app.route('/')
def index():
    """Main page"""
    return render_template('index.html')

@app.route('/charts')
def charts():
    """Charts page"""
    return render_template('charts.html')

@app.route('/api/tick')
def get_latest_tick():
    """API endpoint to get the latest tick data from Firebase"""
    try:
        response = requests.get(f"{FIREBASE_URL}{FIREBASE_TICKS_PATH}")
        if response.status_code == 200:
            ticks = response.json() or {}
            if ticks:
                # Get the most recent tick
                latest_tick_data = max(ticks.values(), key=lambda x: x.get('epoch', 0))
                return jsonify(latest_tick_data)
            else:
                return jsonify({"error": "No ticks available"}), 404
        else:
            return jsonify({"error": "Failed to fetch ticks"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/latest-tick')
def get_latest_tick_simple():
    """API endpoint to get the latest tick data"""
    return jsonify(latest_tick)

@app.route('/api/all-ticks')
def get_all_ticks():
    """API endpoint to get all ticks from Firebase"""
    try:
        response = requests.get(f"{FIREBASE_URL}{FIREBASE_TICKS_PATH}")
        if response.status_code == 200:
            ticks = response.json() or {}
            return jsonify(ticks)
        else:
            return jsonify({"error": "Failed to fetch ticks"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/1min-candles')
def get_1min_candles():
    """API endpoint to get 1-minute candlestick data"""
    try:
        response = requests.get(f"{FIREBASE_URL}{FIREBASE_1MIN_PATH}")
        if response.status_code == 200:
            candles = response.json() or {}
            return jsonify(candles)
        else:
            return jsonify({"error": "Failed to fetch 1min candles"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/5min-candles')
def get_5min_candles():
    """API endpoint to get 5-minute candlestick data"""
    try:
        response = requests.get(f"{FIREBASE_URL}{FIREBASE_5MIN_PATH}")
        if response.status_code == 200:
            candles = response.json() or {}
            return jsonify(candles)
        else:
            return jsonify({"error": "Failed to fetch 5min candles"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/analyze', methods=['POST'])
def analyze_ticks():
    """API endpoint to analyze tick data and generate trading signals"""
    try:
        # Get tick data from Firebase instead of using request data
        response = requests.get(f"{FIREBASE_URL}{FIREBASE_TICKS_PATH}")
        
        if response.status_code != 200:
            return jsonify({"error": "Failed to fetch tick data from Firebase"}), 500
        
        ticks_data = response.json() or {}
        
        if not ticks_data:
            return jsonify({"error": "No tick data available in Firebase"}), 404
        
        # Convert to list and sort by epoch
        ticks_list = list(ticks_data.values())
        ticks_list.sort(key=lambda x: x.get('epoch', 0))
        
        # Extract prices for analysis (last 200 ticks)
        prices = [float(tick.get('quote', 0)) for tick in ticks_list[-200:] if tick.get('quote')]
        
        if len(prices) < 10:
            return jsonify({"error": "Insufficient data for analysis"}), 400
        
        # Initialize analyzer
        analyzer = TrendlineAnalyzer()
        
        # Find support and resistance levels
        support_levels, resistance_levels = analyzer.find_support_resistance(prices)
        
        # Calculate trendlines
        trendlines = analyzer.calculate_trendlines(support_levels, resistance_levels, prices)
        
        # Analyze pattern strength
        pattern_strength = analyzer.analyze_pattern_strength(prices, trendlines)
        
        # Calculate breakout probability
        current_price = prices[-1]
        breakout_probability = analyzer.calculate_breakout_probability(prices, trendlines, current_price)
        
        # Generate trading signals
        signals = analyzer.generate_trading_signals(prices, trendlines, support_levels, resistance_levels)
        
        # Format trendlines for chart display
        formatted_trendlines = []
        for trendline in trendlines:
            formatted_trendlines.append({
                'type': trendline['type'],
                'points': [
                    {'x': trendline['start_index'], 'y': trendline['start_price']},
                    {'x': trendline['end_index'], 'y': trendline['end_price']}
                ]
            })
        
        analysis_result = {
            'support_lines': len(support_levels),
            'resistance_lines': len(resistance_levels),
            'pattern_strength': pattern_strength,
            'breakout_probability': breakout_probability,
            'signals': signals,
            'trendlines': formatted_trendlines,
            'current_price': current_price,
            'total_ticks_analyzed': len(prices),
            'analysis_timestamp': datetime.now().isoformat()
        }
        
        return jsonify(analysis_result)
        
    except Exception as e:
        print(f"Error in analysis: {e}")
        return jsonify({"error": f"Analysis failed: {str(e)}"}), 500

@app.route('/api/current-candles')
def get_current_candles():
    """API endpoint to get current incomplete candles"""
    global current_1min_candle, current_5min_candle
    return jsonify({
        "1min": current_1min_candle,
        "5min": current_5min_candle
    })

@app.route('/api/status')
def get_status():
    """API endpoint to get connection status"""
    global current_1min_candle, current_5min_candle
    
    # Get tick count from Firebase
    tick_count = 0
    try:
        response = requests.get(f"{FIREBASE_URL}{FIREBASE_TICKS_PATH}")
        if response.status_code == 200:
            ticks = response.json() or {}
            tick_count = len(ticks)
    except:
        pass
    
    return jsonify({
        "status": "running" if tick_collector.running else "stopped",
        "latest_tick": latest_tick,
        "current_1min_candle": current_1min_candle,
        "current_5min_candle": current_5min_candle,
        "total_ticks_in_firebase": tick_count,
        "timestamp": datetime.now().isoformat()
    })

def start_tick_collector():
    """Start the tick collector in a separate thread"""
    thread = threading.Thread(target=tick_collector.start, daemon=True)
    thread.start()

# Start the tick collector when the module is imported (for production)
start_tick_collector()

if __name__ == '__main__':
    # Start Flask app (for local development)
    app.run(debug=True, host='0.0.0.0', port=5000, use_reloader=False)
