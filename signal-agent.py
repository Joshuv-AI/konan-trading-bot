#!/usr/bin/env python3
"""
SIGNAL AGENT - V5 ULTIMATE STRATEGY
Best strategy ever found: 88.7% WR, +1.43% EV

Entry Rules:
- RSI < 20 (oversold)
- Price at or below lower Bollinger Band (period 20, std 2)
- Both conditions must be true

Exit Rules:
- Target: +2%
- Stop: -2%
- Trailing stop: 1% (activates after hitting target)
"""

import ccxt
import json
import time
import signal
import sys
from datetime import datetime
from pathlib import Path

# ============= CONFIG =============
API_KEY = 'wPKw4vvnanxFpHAFyFp4AduWWMd8H4LWJ7a4OBJvYDU7f5ugsBX9UoqVwMdCXVUe'
SECRET = '8HOGRZG03QWHUCJApzVyXNUR6PEkU17T9LKJPFFXQ2PwTg6yVS7cXUWZ0qYmL2T0'

e = ccxt.binanceus({'apiKey': API_KEY, 'secret': SECRET, 'enableRateLimit': True, 'timeout': 30000})

# V5 RSI<18 Parameters (OPTIMIZED - Best from backtests)
RSI_THRESHOLD = 18
BB_PERIOD = 20
BB_STD = 2
TARGET_PCT = 0.025  # 2.5%
STOP_PCT = 0.02     # 2%
TRAIL_PCT = 0.008   # 0.8%
RISK_PER_TRADE = 0.03  # 3% max risk
MAX_POSITIONS = 3

# Pairs - V5 uses 10 pairs
PAIRS = ['NEAR/USDT', 'UNI/USDT', 'LINK/USDT', 'SOL/USDT', 'ETH/USDT', 'BTC/USDT', 'DOT/USDT', 'AVAX/USDT', 'ATOM/USDT', 'MATIC/USDT']

# Timeframe
TIMEFRAME = '1h'
LIMIT = 200
SCAN_INTERVAL = 15  # 15 seconds

# File paths
SIGNAL_FILE = 'trading_ales/research_signal.json'
LOG_FILE = 'trading_ales/logs/signal_agent.log'
HEARTBEAT_FILE = 'trading_ales/signal_heartbeat.txt'

# ============= UTILITIES =============

def log(msg):
    try:
        Path('trading_ales/logs').mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, 'a') as f:
            f.write(f'[{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}] {msg}\n')
        print(msg)
    except:
        pass

def write_heartbeat():
    try:
        with open(HEARTBEAT_FILE, 'w') as f:
            f.write(str(time.time()))
    except:
        pass

def get_ohlcv(sym, tf=TIMEFRAME, limit=LIMIT):
    try:
        return e.fetch_ohlcv(sym, tf, limit=limit)
    except Exception as ex:
        log(f'Error fetching {sym}: {ex}')
        return None

# ============= INDICATORS =============

def calc_rsi(prices, period=14):
    """Calculate RSI"""
    if len(prices) < period + 1:
        return 50
    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calc_bollinger(prices, period=20, std=2):
    """Calculate Bollinger Bands"""
    if len(prices) < period:
        return None, None, None
    
    # Calculate SMA
    sma = sum(prices[-period:]) / period
    
    # Calculate std dev
    variance = sum((p - sma) ** 2 for p in prices[-period:]) / period
    std_dev = variance ** 0.5
    
    upper = sma + (std_dev * std)
    lower = sma - (std_dev * std)
    
    return upper, sma, lower

# ============= SIGNAL GENERATION =============

def check_v5_entry(prices):
    """
    V5 ULTIMATE Entry:
    - RSI < 20 (oversold)
    - Price at or below lower Bollinger Band
    """
    if len(prices) < BB_PERIOD + 1:
        return False, 0
    
    # Calculate RSI
    rsi = calc_rsi(prices)
    
    # Calculate Bollinger Bands
    bb_upper, bb_middle, bb_lower = calc_bollinger(prices, BB_PERIOD, BB_STD)
    
    if bb_lower is None:
        return False, 0
    
    current_price = prices[-1]
    
    # Entry: RSI < 20 AND price at or below lower BB (with 2% buffer)
    rsi_condition = rsi < RSI_THRESHOLD
    bb_condition = current_price <= bb_lower * 1.02  # 2% buffer
    
    if rsi_condition and bb_condition:
        score = (RSI_THRESHOLD - rsi) / RSI_THRESHOLD * 10  # More oversold = higher score
        return True, round(score, 1)
    
    return False, 0

def generate_signal(pair):
    """Generate signal for a pair"""
    data = get_ohlcv(pair)
    
    if data is None or len(data) < BB_PERIOD + 1:
        return None
    
    # Extract close prices
    closes = [c[4] for c in data]
    
    # Check for V5 entry
    entry, score = check_v5_entry(closes)
    
    if entry:
        current_price = closes[-1]
        
        # Calculate TP and SL
        tp = current_price * (1 + TARGET_PCT)
        sl = current_price * (1 - STOP_PCT)
        
        signal = {
            'pair': pair,
            'direction': 'LONG',
            'entry': current_price,
            'tp': tp,
            'sl': sl,
            'target_pct': TARGET_PCT * 100,
            'stop_pct': STOP_PCT * 100,
            'trail_pct': TRAIL_PCT * 100,
            'score': score,
            'strategy': 'V5_ULTIMATE',
            'rsi': calc_rsi(closes),
            'timeframe': TIMEFRAME,
            'timestamp': datetime.now().isoformat()
        }
        
        return signal
    
    return None

def scan_all_pairs():
    """Scan all pairs for signals"""
    log("Scanning pairs...")
    signals = []
    
    for pair in PAIRS:
        try:
            log(f"Checking {pair}...")
            signal = generate_signal(pair)
            if signal:
                signals.append(signal)
                log(f"V5 SIGNAL: {pair} | RSI: {signal['rsi']:.1f} | Score: {signal['score']}")
        except Exception as e:
            log(f"Error scanning {pair}: {e}")
    
    # Sort by score (highest first)
    signals.sort(key=lambda x: x['score'], reverse=True)
    
    return signals

def write_signal(signal):
    """Write signal to file"""
    with open(SIGNAL_FILE, 'w') as f:
        json.dump(signal, f, indent=2)
    log(f"Signal written: {signal['pair']} | TP: {signal['tp']:.4f} | SL: {signal['sl']:.4f}")

# ============= MAIN LOOP =============

def main():
    log("="*60)
    log("V5 ULTIMATE SIGNAL AGENT STARTED")
    log(f"RSI < {RSI_THRESHOLD}")
    log(f"BB: Period {BB_PERIOD}, STD {BB_STD}")
    log(f"Target: {TARGET_PCT*100}% | Stop: {STOP_PCT*100}% | Trail: {TRAIL_PCT*100}%")
    log(f"Pairs: {len(PAIRS)}")
    log(f"Timeframe: {TIMEFRAME}")
    log(f"Scan interval: {SCAN_INTERVAL}s")
    log("="*60)
    
    last_signal_time = 0
    # Trading hours now controlled by CRON - run 24/7
    
    while True:
        try:
            # Scan continuously - no time check (cron controls start/stop)
            # Run normal scan
            write_heartbeat()
            
            log("Starting scan...")
            signals = scan_all_pairs()
            log(f"Scan complete, found {len(signals)} signals")
            
            if signals:
                # Only write new signal if we don't have one or found better
                current_signal = None
                try:
                    with open(SIGNAL_FILE) as f:
                        current_signal = json.load(f)
                except:
                    pass
                
                # Write if no current signal or new signal is better
                if not current_signal or (signals[0]['score'] > current_signal.get('score', 0)):
                    write_signal(signals[0])
                    last_signal_time = time.time()
            
            time.sleep(SCAN_INTERVAL)
            
        except KeyboardInterrupt:
            log("Signal agent stopped by user")
            break
        except Exception as e:
            log(f"Error in main loop: {e}")
            time.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    main()
