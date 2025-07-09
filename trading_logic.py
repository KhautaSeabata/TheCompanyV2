import uuid
from datetime import datetime, timedelta
import numpy as np
import requests
import pandas as pd # Although pandas is imported, it's not explicitly used in the provided methods. Keeping it for completeness as it was in the original.
from scipy import stats # Although scipy.stats is imported, it's not explicitly used in the provided methods. Keeping it for completeness as it was in the original.

# Firebase configuration (re-defined here for independent use of trading_logic, though app.py will also have it)
FIREBASE_URL = "https://company-bdb78-default-rtdb.firebaseio.com"
FIREBASE_ALERTS_PATH = "/alerts.json"

# Trading alert system
class TradingAlerts:
    def __init__(self):
        self.active_alerts = []
        self.alert_history = [] # This history is maintained in memory; Firebase stores a subset.
        self.last_analysis = {} # This might be better managed by the calling app if it needs to persist.
        self.alert_cooldown = 30  # 30 seconds cooldown between similar alerts
        
    def add_alert(self, alert_type, direction, price, confidence, description, expiry_minutes=5):
        """
        Add a new trading alert.
        Checks for duplicates based on type and direction within a cooldown period.
        Stores the alert to Firebase.
        """
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
            self.alert_history.append(alert) # Add to in-memory history
            self._store_alert_to_firebase(alert)
            return alert
        return None
    
    def _is_duplicate_alert(self, new_alert):
        """
        Check if the new alert is too similar to recent active alerts
        based on type and direction within the cooldown period.
        """
        cutoff_time = datetime.now() - timedelta(seconds=self.alert_cooldown)
        
        for alert in self.active_alerts:
            # Ensure timestamp is a datetime object for comparison
            alert_time = datetime.fromisoformat(alert['timestamp'])
            if (alert_time > cutoff_time and 
                alert['type'] == new_alert['type'] and
                alert['direction'] == new_alert['direction']):
                return True
        return False
    
    def _store_alert_to_firebase(self, alert):
        """
        Store a single alert to Firebase.
        Maintains a maximum of 100 alerts in Firebase by keeping the latest ones.
        """
        try:
            # Fetch current alerts from Firebase
            response = requests.get(f"{FIREBASE_URL}{FIREBASE_ALERTS_PATH}")
            if response.status_code == 200:
                alerts = response.json() or {}
            else:
                # If fetch fails, start with an empty dictionary
                alerts = {}
                print(f"Warning: Failed to fetch existing alerts from Firebase (Status: {response.status_code}). Starting fresh.")
            
            # Add the new alert
            alerts[alert['id']] = alert
            
            # Keep only the latest 100 alerts based on timestamp
            if len(alerts) > 100:
                # Sort by timestamp (ISO format strings can be compared directly)
                sorted_alerts = dict(sorted(alerts.items(), 
                                          key=lambda x: x[1]['timestamp'], 
                                          reverse=True)[:100])
                alerts = sorted_alerts
            
            # Update Firebase with the new set of alerts
            update_response = requests.put(f"{FIREBASE_URL}{FIREBASE_ALERTS_PATH}", json=alerts)
            
            if update_response.status_code != 200:
                print(f"Error storing alert to Firebase: {update_response.status_code} - {update_response.text}")
            
        except Exception as e:
            print(f"Error storing alert to Firebase: {e}")
    
    def get_active_alerts(self):
        """
        Get currently active alerts from the in-memory list.
        Also clears any expired alerts from the active list.
        """
        now = datetime.now()
        active = []
        
        for alert in self.active_alerts:
            # Convert expiry timestamp to datetime object for comparison
            expiry = datetime.fromisoformat(alert['expiry'])
            if now < expiry:
                active.append(alert)
            else:
                alert['status'] = 'expired' # Mark as expired (though it will be removed)
        
        self.active_alerts = active # Update the active alerts list
        return active
    
    def clear_expired_alerts(self):
        """
        Explicitly remove expired alerts from the in-memory active_alerts list.
        This is also implicitly done by get_active_alerts, but can be called separately.
        """
        now = datetime.now()
        self.active_alerts = [
            alert for alert in self.active_alerts 
            if datetime.fromisoformat(alert['expiry']) > now
        ]

# Trendline analysis and signal generation
class TrendlineAnalyzer:
    """Enhanced trendline analysis with trading signals based on price action and indicators."""
    
    @staticmethod
    def find_support_resistance(prices, window=5):
        """
        Find support and resistance levels using local minima and maxima.
        A point is considered support/resistance if it's the lowest/highest
        within a specified window before and after itself.
        """
        if len(prices) < window * 2 + 1: # Need enough data for the window on both sides
            return [], []
        
        prices_array = np.array(prices)
        support_levels = []
        resistance_levels = []
        
        for i in range(window, len(prices_array) - window):
            # Check for local minimum (support)
            if all(prices_array[i] <= prices_array[i-j] for j in range(1, window+1)) and \
               all(prices_array[i] <= prices_array[i+j] for j in range(1, window+1)):
                support_levels.append({'index': i, 'price': prices_array[i]})
            
            # Check for local maximum (resistance)
            elif all(prices_array[i] >= prices_array[i-j] for j in range(1, window+1)) and \
                 all(prices_array[i] >= prices_array[i+j] for j in range(1, window+1)):
                resistance_levels.append({'index': i, 'price': prices_array[i]})
        
        return support_levels, resistance_levels
    
    @staticmethod
    def calculate_moving_averages(prices, periods=[5, 10, 20]):
        """
        Calculate simple moving averages for specified periods.
        Returns a dictionary with MA values.
        """
        averages = {}
        for period in periods:
            if len(prices) >= period:
                ma = np.mean(prices[-period:])
                averages[f'MA{period}'] = ma
        return averages
    
    @staticmethod
    def calculate_rsi(prices, period=14):
        """
        Calculate the Relative Strength Index (RSI).
        RSI is a momentum oscillator that measures the speed and change of price movements.
        """
        if len(prices) < period + 1:
            return 50.0 # Return neutral RSI if not enough data
        
        # Calculate price changes (deltas)
        deltas = np.diff(prices)
        
        # Separate gains (positive deltas) and losses (negative deltas)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0) # Convert losses to positive values
        
        # Calculate average gain and average loss over the period
        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])
        
        if avg_loss == 0: # Avoid division by zero
            return 100.0 # If no losses, RSI is 100 (extremely overbought)
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
    
    @staticmethod
    def detect_price_action_patterns(prices):
        """
        Detect basic price action patterns like uptrend, downtrend, and consolidation.
        Analyzes the last 10 prices for pattern recognition.
        """
        patterns = []
        
        if len(prices) < 10:
            return patterns
        
        recent_prices = prices[-10:]
        
        # Higher highs and higher lows (uptrend)
        # Check if the last price is higher than the price 2 steps back,
        # and the second to last price is higher than the price 3 steps back.
        if (recent_prices[-1] > recent_prices[-3] and 
            recent_prices[-2] > recent_prices[-4]):
            patterns.append({
                'type': 'Uptrend',
                'strength': 0.8,
                'description': 'Higher highs and higher lows detected over recent prices.'
            })
        
        # Lower highs and lower lows (downtrend)
        # Check if the last price is lower than the price 2 steps back,
        # and the second to last price is lower than the price 3 steps back.
        elif (recent_prices[-1] < recent_prices[-3] and 
              recent_prices[-2] < recent_prices[-4]):
            patterns.append({
                'type': 'Downtrend',
                'strength': 0.8,
                'description': 'Lower highs and lower lows detected over recent prices.'
            })
        
        # Consolidation pattern
        # Check if the price range is very small relative to the average price.
        price_range = max(recent_prices) - min(recent_prices)
        avg_price = np.mean(recent_prices)
        if avg_price > 0 and (price_range / avg_price) < 0.005:  # Less than 0.5% range
            patterns.append({
                'type': 'Consolidation',
                'strength': 0.7,
                'description': 'Price consolidating in a tight range, indicating potential breakout.'
            })
        
        return patterns
    
    @staticmethod
    def generate_enhanced_signals(prices, support_levels, resistance_levels):
        """
        Generate enhanced trading signals based on support/resistance, RSI, and moving averages.
        Includes suggested entry, stop loss, and take profit levels.
        """
        signals = []
        
        if len(prices) < 20: # Need sufficient data for meaningful analysis
            return signals
        
        current_price = prices[-1]
        prev_price = prices[-2] # Price before the current one
        
        # Calculate technical indicators
        ma_data = TrendlineAnalyzer.calculate_moving_averages(prices)
        rsi = TrendlineAnalyzer.calculate_rsi(prices)
        # patterns = TrendlineAnalyzer.detect_price_action_patterns(prices) # Patterns are for general trend, not direct signals here
        
        # Support and resistance signals
        # Check recent support levels (last 3 found levels)
        for support in support_levels[-3:]:
            support_price = support['price']
            # Distance as a percentage of support price
            distance_to_support = abs(current_price - support_price) / support_price
            
            # If price is very close to support (e.g., within 0.2%)
            if distance_to_support < 0.002:
                # Support Bounce: current price above support, previous was below/at
                if current_price > support_price and prev_price <= support_price:
                    signals.append({
                        'type': 'Support Bounce',
                        'action': 'BUY',
                        'entry_price': current_price,
                        'stop_loss': support_price * 0.999, # 0.1% below support
                        'take_profit': support_price * 1.006, # 0.6% above support
                        'confidence': 0.85,
                        'description': f'Price bounced off support at {support_price:.5f}. Potential uptrend.',
                        'risk_reward': 2.0 # Example risk-reward ratio
                    })
                # Support Break: current price significantly below support
                elif current_price < support_price * 0.999:
                    signals.append({
                        'type': 'Support Break',
                        'action': 'SELL',
                        'entry_price': current_price,
                        'stop_loss': support_price * 1.001, # 0.1% above support
                        'take_profit': support_price * 0.994, # 0.6% below support
                        'confidence': 0.8,
                        'description': f'Price broke below support at {support_price:.5f}. Potential downtrend.',
                        'risk_reward': 2.0
                    })
        
        # Check recent resistance levels (last 3 found levels)
        for resistance in resistance_levels[-3:]:
            resistance_price = resistance['price']
            distance_to_resistance = abs(current_price - resistance_price) / resistance_price
            
            # If price is very close to resistance (e.g., within 0.2%)
            if distance_to_resistance < 0.002:
                # Resistance Rejection: current price below resistance, previous was above/at
                if current_price < resistance_price and prev_price >= resistance_price:
                    signals.append({
                        'type': 'Resistance Rejection',
                        'action': 'SELL',
                        'entry_price': current_price,
                        'stop_loss': resistance_price * 1.001, # 0.1% above resistance
                        'take_profit': resistance_price * 0.994, # 0.6% below resistance
                        'confidence': 0.85,
                        'description': f'Price rejected at resistance {resistance_price:.5f}. Potential downtrend.',
                        'risk_reward': 2.0
                    })
                # Resistance Break: current price significantly above resistance
                elif current_price > resistance_price * 1.001:
                    signals.append({
                        'type': 'Resistance Break',
                        'action': 'BUY',
                        'entry_price': current_price,
                        'stop_loss': resistance_price * 0.999, # 0.1% below resistance
                        'take_profit': resistance_price * 1.006, # 0.6% above resistance
                        'confidence': 0.8,
                        'description': f'Price broke above resistance at {resistance_price:.5f}. Potential uptrend.',
                        'risk_reward': 2.0
                    })
        
        # RSI-based signals (Overbought/Oversold)
        if rsi > 70 and prev_price > current_price: # Overbought and price is declining
            signals.append({
                'type': 'RSI Overbought',
                'action': 'SELL',
                'entry_price': current_price,
                'stop_loss': current_price * 1.002, # 0.2% above current price
                'take_profit': current_price * 0.996, # 0.4% below current price
                'confidence': 0.7,
                'description': f'RSI overbought at {rsi:.1f}, indicating potential reversal down.',
                'risk_reward': 2.0
            })
        
        elif rsi < 30 and prev_price < current_price: # Oversold and price is rising
            signals.append({
                'type': 'RSI Oversold',
                'action': 'BUY',
                'entry_price': current_price,
                'stop_loss': current_price * 0.998, # 0.2% below current price
                'take_profit': current_price * 1.004, # 0.4% above current price
                'confidence': 0.7,
                'description': f'RSI oversold at {rsi:.1f}, indicating potential reversal up.',
                'risk_reward': 2.0
            })
        
        # Moving average crossover signals (MA5 crossing MA10)
        if 'MA5' in ma_data and 'MA10' in ma_data:
            ma5 = ma_data['MA5']
            ma10 = ma_data['MA10']
            
            # Golden Cross (MA5 crosses above MA10) - BUY signal
            # Simplified: current price above MA5 which is above MA10, and previous price was below MA5
            if current_price > ma5 and ma5 > ma10 and prev_price <= ma5:
                signals.append({
                    'type': 'MA Crossover (Bullish)',
                    'action': 'BUY',
                    'entry_price': current_price,
                    'stop_loss': ma10, # Stop loss at the slower MA
                    'take_profit': current_price + (current_price - ma10) * 2, # Take profit based on MA distance
                    'confidence': 0.75,
                    'description': 'Price crossed above MA5, with MA5 above MA10. Strong uptrend.',
                    'risk_reward': 2.0
                })
            
            # Death Cross (MA5 crosses below MA10) - SELL signal
            # Simplified: current price below MA5 which is below MA10, and previous price was above MA5
            elif current_price < ma5 and ma5 < ma10 and prev_price >= ma5:
                signals.append({
                    'type': 'MA Crossover (Bearish)',
                    'action': 'SELL',
                    'entry_price': current_price,
                    'stop_loss': ma10, # Stop loss at the slower MA
                    'take_profit': current_price - (ma10 - current_price) * 2, # Take profit based on MA distance
                    'confidence': 0.75,
                    'description': 'Price crossed below MA5, with MA5 below MA10. Strong downtrend.',
                    'risk_reward': 2.0
                })
        
        # Filter and rank signals by confidence (highest confidence first)
        signals = sorted(signals, key=lambda x: x['confidence'], reverse=True)
        return signals[:3]  # Return top 3 signals

# Initialize alerts system globally within this module
trading_alerts = TradingAlerts()

