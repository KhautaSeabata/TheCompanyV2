from flask import Flask, render_template, jsonify, request
import asyncio
import websockets
import json
import requests
import threading
import time
from datetime import datetime, timedelta
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
FIREBASE_ALERTS_PATH = "/alerts.json"

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

# Trading alert system
class TradingAlerts:
    def __init__(self):
        self.active_alerts = []
        self.alert_history = []
        self.last_analysis = {}
        self.alert_cooldown = 30  # 30 seconds cooldown between similar alerts
        
    def add_alert(self, alert_type, direction, price, confidence, description, expiry_minutes=5):
        """Add a new trading alert"""
        alert = {
            'id': str(uuid.uuid4())[:8],
            'type': alert_type,
            'direction': direction,
            'price': price,
            'confidence': confidence,
            'description': description,
            'timestamp': datetime.now().isoformat(),
            'expiry': (datetime.now() + timedelta(minutes=expiry_minutes)).isoformat(),
            'status': 'active'
        }
        
        # Check for similar recent alerts (cooldown)
        if not self._is_duplicate_alert(alert):
            self.active_alerts.append(alert)
            self.alert_history.append(alert)
            self._store_alert_to_firebase(alert)
            return alert
        return None
    
    def _is_duplicate_alert(self, new_alert):
        """Check if this alert is too similar to recent ones"""
        cutoff_time = datetime.now() - timedelta(seconds=self.alert_cooldown)
        
        for alert in self.active_alerts:
            alert_time = datetime.fromisoformat(alert['timestamp'])
            if (alert_time > cutoff_time and 
                alert['type'] == new_alert['type'] and
                alert['direction'] == new_alert['direction']):
                return True
        return False
    
    def _store_alert_to_firebase(self, alert):
        """Store alert to Firebase"""
        try:
            response = requests.get(f"{FIREBASE_URL}{FIREBASE_ALERTS_PATH}")
            if response.status_code == 200:
                alerts = response.json() or {}
            else:
                alerts = {}
            
            alerts[alert['id']] = alert
            
            # Keep only last 100 alerts
            if len(alerts) > 100:
                sorted_alerts = dict(sorted(alerts.items(), 
                                          key=lambda x: x[1]['timestamp'], 
                                          reverse=True)[:100])
                alerts = sorted_alerts
            
            requests.put(f"{FIREBASE_URL}{FIREBASE_ALERTS_PATH}", json=alerts)
            
        except Exception as e:
            print(f"Error storing alert to Firebase: {e}")
    
    def get_active_alerts(self):
        """Get currently active alerts"""
        now = datetime.now()
        active = []
        
        for alert in self.active_alerts:
            expiry = datetime.fromisoformat(alert['expiry'])
            if now < expiry:
                active.append(alert)
            else:
                alert['status'] = 'expired'
        
        self.active_alerts = active
        return active
    
    def clear_expired_alerts(self):
        """Remove expired alerts"""
        now = datetime.now()
        self.active_alerts = [
            alert for alert in self.active_alerts 
            if datetime.fromisoformat(alert['expiry']) > now
        ]

# Initialize alerts system
trading_alerts = TradingAlerts()

class TrendlineAnalyzer:
    """Enhanced trendline analysis with trading signals"""
    
    @staticmethod
    def find_support_resistance(prices, window=5):
        """Find support and resistance levels using local minima and maxima"""
        if len(prices) < window * 2:
            return [], []
        
        prices_array = np.array(prices)
        support_levels = []
        resistance_levels = []
        
        for i in range(window, len(prices_array) - window):
            if all(prices_array[i] <= prices_array[i-j] for j in range(1, window+1)) and \
               all(prices_array[i] <= prices_array[i+j] for j in range(1, window+1)):
                support_levels.append({'index': i, 'price': prices_array[i]})
            
            elif all(prices_array[i] >= prices_array[i-j] for j in range(1, window+1)) and \
                 all(prices_array[i] >= prices_array[i+j] for j in range(1, window+1)):
                resistance_levels.append({'index': i, 'price': prices_array[i]})
        
        return support_levels, resistance_levels
    
    @staticmethod
    def calculate_moving_averages(prices, periods=[5, 10, 20]):
        """Calculate moving averages for trend analysis"""
        if len(prices) < max(periods):
            return {}
        
        averages = {}
        for period in periods:
            if len(prices) >= period:
                ma = np.mean(prices[-period:])
                averages[f'MA{period}'] = ma
        
        return averages
    
    @staticmethod
    def calculate_rsi(prices, period=14):
        """Calculate Relative Strength Index"""
        if len(prices) < period + 1:
            return 50.0
        
        deltas = np.diff(prices)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        
        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
    
    @staticmethod
    def detect_price_action_patterns(prices):
        """Detect key price action patterns"""
        patterns = []
        
        if len(prices) < 10:
            return patterns
        
        recent_prices = prices[-10:]
        current_price = prices[-1]
        
        # Higher highs and higher lows (uptrend)
        if (recent_prices[-1] > recent_prices[-3] and 
            recent_prices[-2] > recent_prices[-4]):
            patterns.append({
                'type': 'Uptrend',
                'strength': 0.8,
                'description': 'Higher highs and higher lows detected'
            })
        
        # Lower highs and lower lows (downtrend)
        elif (recent_prices[-1] < recent_prices[-3] and 
              recent_prices[-2] < recent_prices[-4]):
            patterns.append({
                'type': 'Downtrend',
                'strength': 0.8,
                'description': 'Lower highs and lower lows detected'
            })
        
        # Consolidation pattern
        price_range = max(recent_prices) - min(recent_prices)
        avg_price = np.mean(recent_prices)
        if price_range / avg_price < 0.005:  # Less than 0.5% range
            patterns.append({
                'type': 'Consolidation',
                'strength': 0.7,
                'description': 'Price consolidating in tight range'
            })
        
        return patterns
    
    @staticmethod
    def generate_enhanced_signals(prices, support_levels, resistance_levels):
        """Generate enhanced trading signals with entry points"""
        signals = []
        
        if len(prices) < 20:
            return signals
        
        current_price = prices[-1]
        prev_price = prices[-2]
        
        # Calculate technical indicators
        ma_data = TrendlineAnalyzer.calculate_moving_averages(prices)
        rsi = TrendlineAnalyzer.calculate_rsi(prices)
        patterns = TrendlineAnalyzer.detect_price_action_patterns(prices)
        
        # Support and resistance signals
        for support in support_levels[-3:]:
            support_price = support['price']
            distance_to_support = abs(current_price - support_price) / support_price
            
            # Near support level
            if distance_to_support < 0.002:
                if current_price > support_price and prev_price <= support_price:
                    # Bounce from support - BUY signal
                    signals.append({
                        'type': 'Support Bounce',
                        'action': 'BUY',
                        'entry_price': current_price,
                        'stop_loss': support_price * 0.999,
                        'take_profit': support_price * 1.006,
                        'confidence': 0.85,
                        'description': f'Price bounced from support at {support_price:.5f}',
                        'risk_reward': 2.0
                    })
                elif current_price < support_price * 0.999:
                    # Support break - SELL signal
                    signals.append({
                        'type': 'Support Break',
                        'action': 'SELL',
                        'entry_price': current_price,
                        'stop_loss': support_price * 1.001,
                        'take_profit': support_price * 0.994,
                        'confidence': 0.8,
                        'description': f'Price broke below support at {support_price:.5f}',
                        'risk_reward': 2.0
                    })
        
        for resistance in resistance_levels[-3:]:
            resistance_price = resistance['price']
            distance_to_resistance = abs(current_price - resistance_price) / resistance_price
            
            # Near resistance level
            if distance_to_resistance < 0.002:
                if current_price < resistance_price and prev_price >= resistance_price:
                    # Rejection from resistance - SELL signal
                    signals.append({
                        'type': 'Resistance Rejection',
                        'action': 'SELL',
                        'entry_price': current_price,
                        'stop_loss': resistance_price * 1.001,
                        'take_profit': resistance_price * 0.994,
                        'confidence': 0.85,
                        'description': f'Price rejected at resistance {resistance_price:.5f}',
                        'risk_reward': 2.0
                    })
                elif current_price > resistance_price * 1.001:
                    # Resistance break - BUY signal
                    signals.append({
                        'type': 'Resistance Break',
                        'action': 'BUY',
                        'entry_price': current_price,
                        'stop_loss': resistance_price * 0.999,
                        'take_profit': resistance_price * 1.006,
                        'confidence': 0.8,
                        'description': f'Price broke above resistance at {resistance_price:.5f}',
                        'risk_reward': 2.0
                    })
        
        # RSI-based signals
        if rsi > 70 and prev_price > current_price:
            signals.append({
                'type': 'RSI Overbought',
                'action': 'SELL',
                'entry_price': current_price,
                'stop_loss': current_price * 1.002,
                'take_profit': current_price * 0.996,
                'confidence': 0.7,
                'description': f'RSI overbought at {rsi:.1f}, price declining',
                'risk_reward': 2.0
            })
        
        elif rsi < 30 and prev_price < current_price:
            signals.append({
                'type': 'RSI Oversold',
                'action': 'BUY',
                'entry_price': current_price,
                'stop_loss': current_price * 0.998,
                'take_profit': current_price * 1.004,
                'confidence': 0.7,
                'description': f'RSI oversold at {rsi:.1f}, price rising',
                'risk_reward': 2.0
            })
        
        # Moving average crossover signals
        if 'MA5' in ma_data and 'MA10' in ma_data:
            ma5 = ma_data['MA5']
            ma10 = ma_data['MA10']
            
            if current_price > ma5 > ma10 and prev_price <= ma5:
                signals.append({
                    'type': 'MA Crossover',
                    'action': 'BUY',
                    'entry_price': current_price,
                    'stop_loss': ma10,
                    'take_profit': current_price + (current_price - ma10) * 2,
                    'confidence': 0.75,
                    'description': 'Price crossed above MA5, uptrend confirmed',
                    'risk_reward': 2.0
                })
            
            elif current_price < ma5 < ma10 and prev_price >= ma5:
                signals.append({
                    'type': 'MA Crossover',
                    'action': 'SELL',
                    'entry_price': current_price,
                    'stop_loss': ma10,
                    'take_profit': current_price - (ma10 - current_price) * 2,
                    'confidence': 0.75,
                    'description': 'Price crossed below MA5, downtrend confirmed',
                    'risk_reward': 2.0
                })
        
        # Filter and rank signals by confidence
        signals = sorted(signals, key=lambda x: x['confidence'], reverse=True)
        return signals[:3]  # Return top 3 signals

# Your existing DerivTickCollector class remains the same
class DerivTickCollector:
    def __init__(self):
        self.websocket = None
        self.running = False
        
    async def connect_and_subscribe(self):
        """Connect to Deriv WebSocket and subscribe to Volatility 25 ticks"""
        try:
            self.websocket = await websockets.connect(DERIV_WS_URL)
            
            subscribe_request = {
                "ticks": "R_25",
                "subscribe": 1
            }
            
            await self.websocket.send(json.dumps(subscribe_request))
            print("Connected to Deriv WebSocket and subscribed to R_25 ticks")
            
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
            await asyncio.sleep(5)
            if self.running:
                await self.connect_and_subscribe()
    
    async def process_tick(self, tick_data):
        """Process incoming tick data and store to Firebase"""
        global latest_tick
        
        try:
            tick_info = {
                "epoch": tick_data.get("epoch"),
                "quote": tick_data.get("quote"),
                "symbol": tick_data.get("symbol"),
                "timestamp": datetime.now().isoformat(),
                "id": str(uuid.uuid4())[:8]
            }
            
            latest_tick = tick_info
            print(f"Received tick: {tick_info}")
            
            await self.store_to_firebase(tick_info)
            await self.process_candlestick_data(tick_info)
            
        except Exception as e:
            print(f"Error processing tick: {e}")
    
    async def process_candlestick_data(self, tick_info):
        """Process tick data into 1min and 5min candlesticks"""
        try:
            epoch = tick_info['epoch']
            quote = float(tick_info['quote'])
            
            await self.update_candlestick(epoch, quote, '1min', 60)
            await self.update_candlestick(epoch, quote, '5min', 300)
            
        except Exception as e:
            print(f"Error processing candlestick data: {e}")
    
    async def update_candlestick(self, epoch, quote, timeframe, seconds):
        """Update candlestick data for given timeframe"""
        global current_1min_candle, current_5min_candle, candle_buffers
        
        try:
            candle_start = (epoch // seconds) * seconds
            current_candle = current_1min_candle if timeframe == '1min' else current_5min_candle
            
            if candle_start not in current_candle or current_candle[candle_start] is None:
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
                candle = current_candle[candle_start]
                candle["high"] = max(candle["high"], quote)
                candle["low"] = min(candle["low"], quote)
                candle["close"] = quote
                candle["timestamp"] = datetime.fromtimestamp(candle_start).isoformat()
            
            current_time = epoch
            for candle_epoch, candle_data in list(current_candle.items()):
                if candle_epoch < candle_start:
                    await self.store_candlestick_to_firebase(candle_data, timeframe)
                    
                    candle_buffers[timeframe].append(candle_data)
                    if len(candle_buffers[timeframe]) > 100:
                        candle_buffers[timeframe].pop(0)
                    
                    del current_candle[candle_epoch]
                    print(f"Completed {timeframe} candle: {candle_data}")
            
        except Exception as e:
            print(f"Error updating {timeframe} candlestick: {e}")
    
    async def store_candlestick_to_firebase(self, candle_data, timeframe):
        """Store candlestick data to Firebase"""
        try:
            firebase_path = FIREBASE_1MIN_PATH if timeframe == '1min' else FIREBASE_5MIN_PATH
            
            response = requests.get(f"{FIREBASE_URL}{firebase_path}")
            
            if response.status_code == 200:
                current_candles = response.json() or {}
            else:
                current_candles = {}
            
            candle_key = str(candle_data['epoch'])
            current_candles[candle_key] = candle_data
            
            if len(current_candles) > 950:
                sorted_candles = dict(sorted(current_candles.items(), 
                                           key=lambda x: int(x[0]), 
                                           reverse=True)[:950])
                current_candles = sorted_candles
            
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
            response = requests.get(f"{FIREBASE_URL}{FIREBASE_TICKS_PATH}")
            
            if response.status_code == 200:
                current_ticks = response.json() or {}
            else:
                current_ticks = {}
            
            tick_key = f"{tick_data['epoch']}_{tick_data['id']}"
            current_ticks[tick_key] = tick_data
            
            if len(current_ticks) > 950:
                sorted_ticks = dict(sorted(current_ticks.items(), 
                                         key=lambda x: x[1]['epoch'], 
                                         reverse=True)[:950])
                current_ticks = sorted_ticks
            
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

# Routes
@app.route('/')
def index():
    """Main page"""
    return render_template('index.html')

@app.route('/api/analyze', methods=['POST'])
def analyze_ticks():
    """Enhanced analysis endpoint with trading alerts"""
    try:
        response = requests.get(f"{FIREBASE_URL}{FIREBASE_TICKS_PATH}")
        
        if response.status_code != 200:
            return jsonify({"error": "Failed to fetch tick data from Firebase"}), 500
        
        ticks_data = response.json() or {}
        
        if not ticks_data:
            return jsonify({"error": "No tick data available in Firebase"}), 404
        
        ticks_list = list(ticks_data.values())
        ticks_list.sort(key=lambda x: x.get('epoch', 0))
        
        prices = [float(tick.get('quote', 0)) for tick in ticks_list[-200:] if tick.get('quote')]
        
        if len(prices) < 20:
            return jsonify({"error": "Insufficient data for analysis"}), 400
        
        analyzer = TrendlineAnalyzer()
        
        # Find support and resistance levels
        support_levels, resistance_levels = analyzer.find_support_resistance(prices)
        
        # Generate enhanced signals
        signals = analyzer.generate_enhanced_signals(prices, support_levels, resistance_levels)
        
        # Create alerts for strong signals
        for signal in signals:
            if signal['confidence'] > 0.8:
                alert = trading_alerts.add_alert(
                    alert_type=signal['type'],
                    direction=signal['action'],
                    price=signal['entry_price'],
                    confidence=signal['confidence'],
                    description=signal['description'],
                    expiry_minutes=10
                )
                
                if alert:
                    print(f"New trading alert: {alert}")
        
        # Calculate additional metrics
        current_price = prices[-1]
        ma_data = analyzer.calculate_moving_averages(prices)
        rsi = analyzer.calculate_rsi(prices)
        patterns = analyzer.detect_price_action_patterns(prices)
        
        analysis_result = {
            'support_lines': len(support_levels),
            'resistance_lines': len(resistance_levels),
            'current_price': current_price,
            'rsi': rsi,
            'moving_averages': ma_data,
            'patterns': patterns,
            'signals': signals,
            'total_ticks_analyzed': len(prices),
            'analysis_timestamp': datetime.now().isoformat()
        }
        
        return jsonify(analysis_result)
        
    except Exception as e:
        print(f"Error in analysis: {e}")
        return jsonify({"error": f"Analysis failed: {str(e)}"}), 500

@app.route('/api/alerts')
def get_alerts():
    """Get active trading alerts"""
    try:
        active_alerts = trading_alerts.get_active_alerts()
        return jsonify({
            'active_alerts': active_alerts,
            'total_alerts': len(active_alerts)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/alerts/history')
def get_alerts_history():
    """Get alerts history from Firebase"""
    try:
        response = requests.get(f"{FIREBASE_URL}{FIREBASE_ALERTS_PATH}")
        if response.status_code == 200:
            alerts = response.json() or {}
            return jsonify(alerts)
        else:
            return jsonify({"error": "Failed to fetch alerts"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/tick')
def get_latest_tick():
    """API endpoint to get the latest tick data from Firebase"""
    try:
        response = requests.get(f"{FIREBASE_URL}{FIREBASE_TICKS_PATH}")
        if response.status_code == 200:
            ticks = response.json() or {}
            if ticks:
                latest_tick_data = max(ticks.values(), key=lambda x: x.get('epoch', 0))
                return jsonify(latest_tick_data)
            else:
                return jsonify({"error": "No ticks available"}), 404
        else:
            return jsonify({"error": "Failed to fetch ticks"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

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

@app.route('/api/status')
def get_status():
    """API endpoint to get connection status"""
    global current_1min_candle, current_5min_candle
    
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
        "active_alerts": len(trading_alerts.get_active_alerts()),
        "timestamp": datetime.now().isoformat()
    })

def start_tick_collector():
    """Start the tick collector in a separate thread"""
    thread = threading.Thread(target=tick_collector.start, daemon=True)
    thread.start()

# Start the tick collector when the module is imported
start_tick_collector()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000, use_reloader=False)
