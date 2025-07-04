import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy import stats
from typing import List, Tuple, Dict, Optional
import json
import requests
from datetime import datetime, timedelta

class TrendlineAnalyzer:
    def __init__(self, lookback_period: int = 50, min_touches: int = 2):
        """
        Initialize the trendline analyzer
        
        Args:
            lookback_period: Number of candles to look back for pattern detection
            min_touches: Minimum number of touches required for a valid trendline
        """
        self.lookback_period = lookback_period
        self.min_touches = min_touches
        self.support_lines = []
        self.resistance_lines = []
        self.patterns = []
        
    def fetch_data_from_api(self, endpoint: str = "http://localhost:3000/api/1min-candles") -> pd.DataFrame:
        """
        Fetch candlestick data from the API
        
        Args:
            endpoint: API endpoint URL
            
        Returns:
            DataFrame with OHLC data
        """
        try:
            response = requests.get(endpoint)
            if response.status_code == 200:
                data = response.json()
                
                # Convert to DataFrame
                df_data = []
                for key, candle in data.items():
                    df_data.append({
                        'timestamp': pd.to_datetime(candle['timestamp']),
                        'open': float(candle['open']),
                        'high': float(candle['high']),
                        'low': float(candle['low']),
                        'close': float(candle['close']),
                        'epoch': int(candle['epoch'])
                    })
                
                df = pd.DataFrame(df_data)
                df = df.sort_values('timestamp').reset_index(drop=True)
                return df
            else:
                print(f"Error fetching data: {response.status_code}")
                return pd.DataFrame()
                
        except Exception as e:
            print(f"Error fetching data: {e}")
            return pd.DataFrame()
    
    def find_swing_points(self, data: pd.DataFrame, window: int = 5) -> Tuple[List[int], List[int]]:
        """
        Find swing highs and lows in the price data
        
        Args:
            data: DataFrame with OHLC data
            window: Window size for swing point detection
            
        Returns:
            Tuple of (swing_highs_indices, swing_lows_indices)
        """
        highs = data['high'].values
        lows = data['low'].values
        
        swing_highs = []
        swing_lows = []
        
        for i in range(window, len(data) - window):
            # Check for swing high
            if all(highs[i] >= highs[i-j] for j in range(1, window+1)) and \
               all(highs[i] >= highs[i+j] for j in range(1, window+1)):
                swing_highs.append(i)
            
            # Check for swing low
            if all(lows[i] <= lows[i-j] for j in range(1, window+1)) and \
               all(lows[i] <= lows[i+j] for j in range(1, window+1)):
                swing_lows.append(i)
        
        return swing_highs, swing_lows
    
    def calculate_trendline(self, points: List[Tuple[int, float]]) -> Tuple[float, float, float]:
        """
        Calculate trendline using linear regression
        
        Args:
            points: List of (index, price) tuples
            
        Returns:
            Tuple of (slope, intercept, r_squared)
        """
        if len(points) < 2:
            return 0, 0, 0
        
        x_vals = [p[0] for p in points]
        y_vals = [p[1] for p in points]
        
        slope, intercept, r_value, p_value, std_err = stats.linregress(x_vals, y_vals)
        r_squared = r_value ** 2
        
        return slope, intercept, r_squared
    
    def find_support_resistance(self, data: pd.DataFrame, swing_highs: List[int], swing_lows: List[int]) -> Dict:
        """
        Find support and resistance lines
        
        Args:
            data: DataFrame with OHLC data
            swing_highs: List of swing high indices
            swing_lows: List of swing low indices
            
        Returns:
            Dictionary with support and resistance lines
        """
        lines = {
            'support': [],
            'resistance': []
        }
        
        # Find resistance lines using swing highs
        for i in range(len(swing_highs)):
            for j in range(i + 1, len(swing_highs)):
                if swing_highs[j] - swing_highs[i] < self.lookback_period:
                    points = [(swing_highs[i], data.iloc[swing_highs[i]]['high']),
                             (swing_highs[j], data.iloc[swing_highs[j]]['high'])]
                    
                    slope, intercept, r_squared = self.calculate_trendline(points)
                    
                    # Check for additional touches
                    touches = self.count_touches(data, slope, intercept, swing_highs[i], swing_highs[j], 'resistance')
                    
                    if touches >= self.min_touches and r_squared > 0.8:
                        lines['resistance'].append({
                            'start_idx': swing_highs[i],
                            'end_idx': swing_highs[j],
                            'slope': slope,
                            'intercept': intercept,
                            'r_squared': r_squared,
                            'touches': touches,
                            'strength': touches * r_squared
                        })
        
        # Find support lines using swing lows
        for i in range(len(swing_lows)):
            for j in range(i + 1, len(swing_lows)):
                if swing_lows[j] - swing_lows[i] < self.lookback_period:
                    points = [(swing_lows[i], data.iloc[swing_lows[i]]['low']),
                             (swing_lows[j], data.iloc[swing_lows[j]]['low'])]
                    
                    slope, intercept, r_squared = self.calculate_trendline(points)
                    
                    # Check for additional touches
                    touches = self.count_touches(data, slope, intercept, swing_lows[i], swing_lows[j], 'support')
                    
                    if touches >= self.min_touches and r_squared > 0.8:
                        lines['support'].append({
                            'start_idx': swing_lows[i],
                            'end_idx': swing_lows[j],
                            'slope': slope,
                            'intercept': intercept,
                            'r_squared': r_squared,
                            'touches': touches,
                            'strength': touches * r_squared
                        })
        
        return lines
    
    def count_touches(self, data: pd.DataFrame, slope: float, intercept: float, 
                     start_idx: int, end_idx: int, line_type: str, tolerance: float = 0.001) -> int:
        """
        Count how many times price touches the trendline
        
        Args:
            data: DataFrame with OHLC data
            slope: Trendline slope
            intercept: Trendline intercept
            start_idx: Starting index
            end_idx: Ending index
            line_type: 'support' or 'resistance'
            tolerance: Price tolerance for touch detection
            
        Returns:
            Number of touches
        """
        touches = 0
        
        for i in range(start_idx, end_idx + 1):
            expected_price = slope * i + intercept
            
            if line_type == 'support':
                actual_price = data.iloc[i]['low']
                if abs(actual_price - expected_price) / expected_price <= tolerance:
                    touches += 1
            else:  # resistance
                actual_price = data.iloc[i]['high']
                if abs(actual_price - expected_price) / expected_price <= tolerance:
                    touches += 1
        
        return touches
    
    def detect_patterns(self, data: pd.DataFrame, lines: Dict) -> List[Dict]:
        """
        Detect trading patterns like S-H (Support-High) and S-L (Support-Low)
        
        Args:
            data: DataFrame with OHLC data
            lines: Dictionary with support and resistance lines
            
        Returns:
            List of detected patterns
        """
        patterns = []
        
        # Sort lines by strength
        support_lines = sorted(lines['support'], key=lambda x: x['strength'], reverse=True)
        resistance_lines = sorted(lines['resistance'], key=lambda x: x['strength'], reverse=True)
        
        # Pattern detection logic
        for support in support_lines[:3]:  # Take top 3 support lines
            for resistance in resistance_lines[:3]:  # Take top 3 resistance lines
                # Check if lines intersect and form patterns
                if self.check_pattern_formation(data, support, resistance):
                    pattern = {
                        'type': 'channel',
                        'support': support,
                        'resistance': resistance,
                        'strength': (support['strength'] + resistance['strength']) / 2,
                        'breakout_probability': self.calculate_breakout_probability(data, support, resistance)
                    }
                    patterns.append(pattern)
        
        return patterns
    
    def check_pattern_formation(self, data: pd.DataFrame, support: Dict, resistance: Dict) -> bool:
        """
        Check if support and resistance lines form a valid pattern
        
        Args:
            data: DataFrame with OHLC data
            support: Support line data
            resistance: Resistance line data
            
        Returns:
            True if valid pattern is formed
        """
        # Basic validation - lines should not be too close or too far
        avg_support_price = support['slope'] * ((support['start_idx'] + support['end_idx']) / 2) + support['intercept']
        avg_resistance_price = resistance['slope'] * ((resistance['start_idx'] + resistance['end_idx']) / 2) + resistance['intercept']
        
        price_diff = abs(avg_resistance_price - avg_support_price)
        avg_price = (avg_support_price + avg_resistance_price) / 2
        
        # Lines should be at least 0.5% apart and not more than 5% apart
        if 0.005 <= price_diff / avg_price <= 0.05:
            return True
        
        return False
    
    def calculate_breakout_probability(self, data: pd.DataFrame, support: Dict, resistance: Dict) -> float:
        """
        Calculate probability of breakout based on pattern strength
        
        Args:
            data: DataFrame with OHLC data
            support: Support line data
            resistance: Resistance line data
            
        Returns:
            Breakout probability (0-1)
        """
        # Simple calculation based on line strength and recent price action
        combined_strength = (support['strength'] + resistance['strength']) / 2
        
        # Check recent price movement
        recent_data = data.tail(10)
        recent_volatility = recent_data['high'].std() + recent_data['low'].std()
        
        # Higher volatility and stronger lines = higher breakout probability
        probability = min(0.9, combined_strength * 0.1 + recent_volatility * 0.01)
        
        return probability
    
    def analyze_chart(self, data: pd.DataFrame = None) -> Dict:
        """
        Main analysis function that performs complete chart analysis
        
        Args:
            data: DataFrame with OHLC data (optional, will fetch if not provided)
            
        Returns:
            Dictionary with analysis results
        """
        if data is None:
            print("Fetching data from API...")
            data = self.fetch_data_from_api()
        
        if data.empty:
            return {"error": "No data available for analysis"}
        
        print(f"Analyzing {len(data)} candles...")
        
        # Find swing points
        swing_highs, swing_lows = self.find_swing_points(data)
        print(f"Found {len(swing_highs)} swing highs and {len(swing_lows)} swing lows")
        
        # Find support and resistance lines
        lines = self.find_support_resistance(data, swing_highs, swing_lows)
        print(f"Found {len(lines['support'])} support lines and {len(lines['resistance'])} resistance lines")
        
        # Detect patterns
        patterns = self.detect_patterns(data, lines)
        print(f"Detected {len(patterns)} trading patterns")
        
        # Store results
        self.support_lines = lines['support']
        self.resistance_lines = lines['resistance']
        self.patterns = patterns
        
        return {
            'data_points': len(data),
            'swing_highs': len(swing_highs),
            'swing_lows': len(swing_lows),
            'support_lines': len(lines['support']),
            'resistance_lines': len(lines['resistance']),
            'patterns': len(patterns),
            'analysis_time': datetime.now().isoformat(),
            'lines': lines,
            'patterns_detail': patterns
        }
    
    def plot_chart(self, data: pd.DataFrame, save_path: str = 'chart_analysis.png'):
        """
        Plot the chart with trendlines and patterns
        
        Args:
            data: DataFrame with OHLC data
            save_path: Path to save the chart image
        """
        fig, ax = plt.subplots(figsize=(15, 10))
        
        # Plot candlestick chart
        for i in range(len(data)):
            color = 'green' if data.iloc[i]['close'] >= data.iloc[i]['open'] else 'red'
            
            # Draw the wick
            ax.plot([i, i], [data.iloc[i]['low'], data.iloc[i]['high']], 
                   color='black', linewidth=0.5)
            
            # Draw the body
            body_height = abs(data.iloc[i]['close'] - data.iloc[i]['open'])
            bottom = min(data.iloc[i]['close'], data.iloc[i]['open'])
            ax.add_patch(plt.Rectangle((i-0.3, bottom), 0.6, body_height, 
                                     facecolor=color, alpha=0.7))
        
        # Plot support lines
        for line in self.support_lines:
            x_vals = [line['start_idx'], line['end_idx']]
            y_vals = [line['slope'] * x + line['intercept'] for x in x_vals]
            ax.plot(x_vals, y_vals, 'b-', linewidth=2, alpha=0.7, label='Support')
            
            # Add S-L markers
            ax.text(line['start_idx'], y_vals[0], 'S-L', 
                   bbox=dict(boxstyle="round,pad=0.3", facecolor="blue", alpha=0.7),
                   fontsize=8, color='white')
        
        # Plot resistance lines
        for line in self.resistance_lines:
            x_vals = [line['start_idx'], line['end_idx']]
            y_vals = [line['slope'] * x + line['intercept'] for x in x_vals]
            ax.plot(x_vals, y_vals, 'r-', linewidth=2, alpha=0.7, label='Resistance')
            
            # Add S-H markers
            ax.text(line['start_idx'], y_vals[0], 'S-H', 
                   bbox=dict(boxstyle="round,pad=0.3", facecolor="red", alpha=0.7),
                   fontsize=8, color='white')
        
        # Add pattern markers
        for pattern in self.patterns:
            if pattern['type'] == 'channel':
                # Mark potential breakout areas
                ax.axvline(x=len(data)-1, color='orange', linestyle='--', alpha=0.7)
                ax.text(len(data)-10, data.iloc[-1]['close'], 
                       f"Breakout: {pattern['breakout_probability']:.2%}",
                       bbox=dict(boxstyle="round,pad=0.3", facecolor="orange", alpha=0.7),
                       fontsize=10)
        
        # Formatting
        ax.set_title('Volatility 25 - Trendline Analysis', fontsize=16, fontweight='bold')
        ax.set_xlabel('Time', fontsize=12)
        ax.set_ylabel('Price', fontsize=12)
        ax.grid(True, alpha=0.3)
        ax.legend()
        
        # Set x-axis labels
        if len(data) > 0:
            step = max(1, len(data) // 10)
            tick_positions = range(0, len(data), step)
            tick_labels = [data.iloc[i]['timestamp'].strftime('%H:%M') for i in tick_positions]
            ax.set_xticks(tick_positions)
            ax.set_xticklabels(tick_labels, rotation=45)
        
        plt.tight_layout()
        plt.savefig(save_path, dpi=300, bbox_inches='tight')
        plt.show()
        
        print(f"Chart saved as {save_path}")
    
    def get_trading_signals(self) -> List[Dict]:
        """
        Generate trading signals based on pattern analysis
        
        Returns:
            List of trading signals
        """
        signals = []
        
        for pattern in self.patterns:
            if pattern['breakout_probability'] > 0.6:
                signal = {
                    'type': 'breakout_alert',
                    'direction': 'up' if pattern['resistance']['slope'] > 0 else 'down',
                    'confidence': pattern['breakout_probability'],
                    'entry_level': pattern['resistance']['slope'] * pattern['resistance']['end_idx'] + pattern['resistance']['intercept'],
                    'stop_loss': pattern['support']['slope'] * pattern['support']['end_idx'] + pattern['support']['intercept'],
                    'timestamp': datetime.now().isoformat()
                }
                signals.append(signal)
        
        return signals


# Example usage and testing
if __name__ == "__main__":
    # Initialize analyzer
    analyzer = TrendlineAnalyzer(lookback_period=50, min_touches=2)
    
    # Analyze button function
    def analyze_button_click():
        """
        Function to be called when analyze button is clicked
        """
        print("=" * 60)
        print("STARTING TRENDLINE ANALYSIS")
        print("=" * 60)
        
        # Perform analysis
        results = analyzer.analyze_chart()
        
        if "error" in results:
            print(f"Error: {results['error']}")
            return
        
        # Display results
        print("\nANALYSIS RESULTS:")
        print(f"Data Points: {results['data_points']}")
        print(f"Swing Highs: {results['swing_highs']}")
        print(f"Swing Lows: {results['swing_lows']}")
        print(f"Support Lines: {results['support_lines']}")
        print(f"Resistance Lines: {results['resistance_lines']}")
        print(f"Patterns Detected: {results['patterns']}")
        
        # Show trading signals
        signals = analyzer.get_trading_signals()
        if signals:
            print("\nTRADING SIGNALS:")
            for signal in signals:
                print(f"- {signal['type'].upper()}: {signal['direction']} "
                      f"(Confidence: {signal['confidence']:.2%})")
        
        # Generate chart
        try:
            data = analyzer.fetch_data_from_api()
            if not data.empty:
                analyzer.plot_chart(data)
            else:
                print("No data available for chart plotting")
        except Exception as e:
            print(f"Error plotting chart: {e}")
        
        print("\nAnalysis completed!")
        return results
    
    # Run analysis
    if __name__ == "__main__":
        analyze_button_click()
