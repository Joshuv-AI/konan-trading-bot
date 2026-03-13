#!/usr/bin/env python3
"""
BINANCE.US TRADING BOT v3.0 - CLEAN
External signal mode: reads from research_signal.json
"""
import os, sys, json, time, subprocess, traceback, signal
from datetime import datetime
from pathlib import Path
import ccxt, pandas as pd

# ============= CONFIG =============
API_KEY = os.environ.get('BINANCE_API_KEY', 'wPKw4vvnanxFpHAFyFp4AduWWMd8H4LWJ7a4OBJvYDU7f5ugsBX9UoqVwMdCXVUe')
SECRET = os.environ.get('BINANCE_SECRET', '8HOGRZG03QWHUCJApzVyXNUR6PEkU17T9LKJPFFXQ2PwTg6yVS7cXUWZ0qYmL2T0')

# Initialize exchange
e = ccxt.binanceus({'apiKey': API_KEY, 'secret': SECRET, 'enableRateLimit': True, 'timeout': 30000})
# Sheets config for live trades
SHEETS_ENABLED = True
SHEETS_SCRIPT_PATH = 'C:/Users/1/.openclaw/workspace/kraken-bot/backtest-framework/sheets_manager.py'

# Trading - V5 ULTIMATE Parameters
PAIRS = ['NEAR/USDT', 'UNI/USDT', 'LINK/USDT', 'SOL/USDT', 'ETH/USDT', 'BTC/USDT', 'DOT/USDT', 'AVAX/USDT', 'ATOM/USDT', 'MATIC/USDT']
TRADE_AMOUNT_USD = 2.00  # $2 per trade
MIN_NOTIONAL = 1  # $1 minimum (Binance minimum is usually ~$1-5)
TARGET_PCT = 0.025   # 2.5% take profit (optimized!)
STOP_PCT = 0.02      # 2% stop loss
TRAIL_PCT = 0.008    # 0.8% trailing stop (optimized!)
MAX_POSITIONS = 3
MAX_HOLD_HOURS = 24
SCAN_INTERVAL = 10
TRADE_COOLDOWN_MINUTES = 15
MIN_SCORE = 5
STRATEGY_NAME = 'V5_RSI18'
DRY_RUN = False
SIGNAL_SOURCE = 'EXTERNAL'
STRATEGY_NAME = 'V5_RSI18'

# Files
DATA_DIR = Path('C:/Users/1/.openclaw/workspace/trading_ales')
POSITIONS_FILE = DATA_DIR / 'open_positions.json'
LOG_FILE = DATA_DIR / 'logs/trading_bot.log'
SIGNAL_FILE = DATA_DIR / 'research_signal.json'
DISCORD_CHANNEL = '1477133938265821314'  # Open Trades channel
MIN_TRADE_AMOUNTS = {'BTCUSDT': 0.0001, 'ETHUSDT': 0.001, 'SOLUSDT': 0.01, 'DOTUSDT': 0.1, 'AVAXUSDT': 0.01, 'LINKUSDT': 0.01, 'UNIUSDT': 0.01, 'ATOMUSDT': 0.01, 'NEARUSDT': 0.1, 'ADAUSDT': 10}

# Init Sheets
SHEETS_CLIENT = None
if SHEETS_ENABLED:
    try:
        import sys
        sys.path.insert(0, 'C:/Users/1/.openclaw/workspace/kraken-bot/backtest-framework')
        from sheets_manager import log_live_trade_entry, log_live_trade_exit, log_balance
        SHEETS_CLIENT = True
        print('Sheets logging enabled')
    except Exception as e:
        print(f'Sheets init error: {e}')
        SHEETS_CLIENT = False

last_trade_time = 0

# ============= LOGGING =============
def log(msg, level='INFO'):
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        (DATA_DIR / 'logs').mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, 'a') as f:
            f.write(f'[{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}] [{level}] {msg}\n')
        print(f'[{level}] {msg}')
    except:
        pass

def log_error(msg):
    log(f'ERROR: {msg}', 'ERROR')

# ============= POSITIONS =============
def get_positions():
    try:
        return json.load(open(POSITIONS_FILE)) if POSITIONS_FILE.exists() else []
    except:
        return []

def sync_positions_from_exchange():
    """Fetch open positions from Binance using BALANCE (not trade history)"""
    global e
    try:
        log('Syncing positions from Binance...')
        
        # Get actual balances
        bal = e.fetch_balance()['total']
        
        # Only check assets we trade
        tracked_assets = {}
        for asset in ['NEAR', 'SOL', 'UNI', 'DOT', 'AVAX', 'ATOM', 'LINK', 'MATIC', 'ETH', 'BTC']:
            symbol = f'{asset}/USDT'
            qty = bal.get(asset, 0)
            if qty and qty > 0.0001:  # Skip tiny amounts
                try:
                    ticker = e.fetch_ticker(symbol)
                    price = ticker['last']
                    notional = qty * price
                    if notional >= 1:  # Track any asset with $1+ value
                        tracked_assets[asset] = {
                            'qty': qty,
                            'price': price,
                            'notional': notional
                        }
                        log(f'Asset {asset}: {qty} @ ${price} = ${notional:.2f}')
                except:
                    pass
        
        # For any asset with balance, we are LONG (we only go long, never short)
        # Use balance to determine direction - if you hold it, you're long
        reconstructed = []
        for asset, data in tracked_assets.items():
            pair = f'{asset}/USDT'
            try:
                # If we have balance > 0, we're LONG
                # Use current price as entry (approximation for synced positions)
                entry_price = data['price']  # Use current market price as reference
                
                # For synced positions, use current price for TP/SL calc
                target = entry_price * (1 + TARGET_PCT)  # 2.5%
                stop = entry_price * (1 - STOP_PCT)     # 2%
                trailing = entry_price * (1 + TRAIL_PCT) # 0.8%
                
                pos = {
                    'pair': pair,
                    'direction': 'BUY',  # If we hold it, we're LONG
                    'entry': entry_price,
                    'amount': data['qty'],
                    'target': target,
                    'stop': stop,
                    'trail_active': False,
                    'trail_price': trailing,
                    'timestamp': datetime.now().isoformat(),
                    'synced': True  # Mark as synced position
                }
                reconstructed.append(pos)
                qty_val = data['qty']
                log(f'Synced position: {pair} {qty_val} @ ${entry_price} (LONG - holding asset)')
            except Exception as ex:
                log(f'Error syncing {pair}: {ex}')
        
        if reconstructed:
            log(f'Total positions synced: {len(reconstructed)}')
            set_positions(reconstructed)
            return reconstructed
        
        log('No open positions found')
        return []
        
    except Exception as ex:
        log(f'Sync error: {ex}')
        return get_positions()

def set_positions(positions):
    try:
        json.dump(positions, open(POSITIONS_FILE, 'w'))
    except:
        pass

def add_position(pos):
    positions = get_positions()
    positions.append(pos)
    set_positions(positions)

def remove_position(pair):
    set_positions([p for p in get_positions() if p.get('pair') != pair])

# ============= EXCHANGE =============
def get_price(sym):
    global e
    try:
        return e.fetch_ticker(sym)['last']
    except:
        return None

def get_ohlcv(sym, tf='1h', lim=200):
    global e
    try:
        return e.fetch_ohlcv(sym, tf, limit=lim)
    except:
        return None

# Cache for minimum notionals
MIN_NOTIONAL_CACHE = {}

def get_min_notional(sym):
    """Fetch minimum notional from Binance exchange info"""
    global e, MIN_NOTIONAL_CACHE
    
    if sym in MIN_NOTIONAL_CACHE:
        return MIN_NOTIONAL_CACHE[sym]
    
    try:
        # Get exchange info for this symbol
        info = e.fetch_markets()
        for market in info:
            if market['symbol'] == sym.replace('/', ''):
                # Get min notional - some markets have minNotional, some have limits
                min_notional = market.get('limits', {}).get('cost', {}).get('min', 1)
                if not min_notional or min_notional < 1:
                    min_notional = 1  # Default to $1
                MIN_NOTIONAL_CACHE[sym] = min_notional
                return min_notional
    except Exception as ex:
        log(f'Error fetching min notional for {sym}: {ex}')
    
    return 1  # Default fallback

# ============= INDICATORS =============
def calc_ema(prices, per):
    return pd.Series(prices).ewm(span=per, adjust=False).mean().iloc[-1] if len(prices) >= per else prices[-1]

def calc_rsi(prices, per=14):
    if len(prices) < per + 1:
        return 50
    delta = pd.Series(prices).diff()
    gain, loss = delta.where(delta > 0, 0).rolling(window=per).mean(), (-delta.where(delta < 0, 0)).rolling(window=per).mean()
    return 100 - (100 / (1 + gain / loss)) if loss.iloc[-1] > 0 else 50

def calc_atr(prices, per=14):
    if len(prices) < per + 1:
        return 0
    trs = [max(prices[i]-prices[i-1], abs(prices[i]-prices[i-1]), 0) for i in range(1, len(prices))]
    return sum(trs[-per:])/per if trs else 0

# ============= TRADING =============
def can_trade():
    global last_trade_time
    if time.time() - last_trade_time < TRADE_COOLDOWN_MINUTES * 60:
        return False
    return True

def check_position_limit():
    return len(get_positions()) < MAX_POSITIONS, "Max positions" if len(get_positions()) >= MAX_POSITIONS else "OK"

def execute_trade(pair, direction, price, retries=3):
    global last_trade_time, e
    if DRY_RUN:
        log(f'[DRY] Would trade: {pair} {direction} @ ${price}')
        return {'pair': pair, 'direction': direction, 'entry': price, 'dry_run': True}
    
    # Make sure exchange is initialized
    import ccxt
    if 'e' not in globals():
        global e
        e = ccxt.binanceus({'apiKey': API_KEY, 'secret': SECRET, 'enableRateLimit': True, 'timeout': 30000})
    
    for attempt in range(retries):
        try:
            can_open, _ = check_position_limit()
            if not can_open:
                return None
            if any(p.get('pair') == pair for p in get_positions()):
                return None
            bal = e.fetch_balance()['total'].get('USDT', 0)
            
            # Cap amount to what we can afford (leave 10% buffer for fees)
            max_amt_by_balance = (bal * 0.9) / price
            desired_amt = TRADE_AMOUNT_USD / price
            amt = min(desired_amt, max_amt_by_balance)
            
            # Round to nearest 0.01
            amt = (int((amt / 0.01) * 0.01) if amt else 0)
            
            # Get dynamic minimum notional from Binance
            exchange_min = get_min_notional(pair)
            effective_min = max(MIN_NOTIONAL, exchange_min)
            
            # Ensure minimum notional
            if amt * price < effective_min:
                log(f'SKIP: {pair} notional ${amt * price:.2f} < ${effective_min} minimum (Binance: ${exchange_min}, balance: ${bal:.2f})')
                return None
            log(f'TRADING: {pair} {direction} {amt} @ ${price}')
            # Normalize direction - handle both BUY/LONG and SELL/SHORT
            dir_check = direction if direction in ['BUY', 'SELL'] else ('BUY' if direction == 'LONG' else 'SELL')
            
            # Execute trade and get ACTUAL execution price
            actual_entry_price = None
            if dir_check == 'BUY':
                result = e.create_market_buy_order(pair, amt)
                # Get actual fill price from response
                if result and 'average' in result:
                    actual_entry_price = result['average']
                elif result and 'price' in result:
                    actual_entry_price = result['price']
            else:
                result = e.create_market_sell_order(pair, amt)
                if result and 'average' in result:
                    actual_entry_price = result['average']
                elif result and 'price' in result:
                    actual_entry_price = result['price']
            
            # Verify trade succeeded
            if not result or not actual_entry_price:
                log(f'TRADE FAILED: No result returned for {pair}')
                return None
            
            # Use actual execution price, fallback to estimate if not available
            actual_price = actual_entry_price if actual_entry_price else price
            log(f'CONFIRMED: {pair} entry @ ${actual_price}')
            
            # Calculate fees (Binance US ~0.2% per trade, so ~0.4% round trip)
            fee_rate = 0.002
            
            # V5 ULTIMATE: Fixed percentage TP/SL based on ACTUAL price
            target_price = actual_price * (1 + TARGET_PCT) if dir_check == 'BUY' else actual_price * (1 - TARGET_PCT)
            stop_price = actual_price * (1 - STOP_PCT) if dir_check == 'BUY' else actual_price * (1 + STOP_PCT)
            
            pos = {
                'pair': pair, 'direction': dir_check, 'entry': actual_price, 'amount': amt,
                'target': target_price,
                'stop': stop_price,
                'trail_price': actual_price * (1 + TRAIL_PCT) if dir_check == 'BUY' else actual_price * (1 - TRAIL_PCT),  # Trailing stop activation price
                'trail_active': False,
                'entry_fee': amt * actual_price * fee_rate,
                'timestamp': datetime.now().isoformat()
            }
            
            # Only add position if trade was successful (result exists)
            if result:
                add_position(pos)
                last_trade_time = time.time()
            else:
                log(f'TRADE FAILED: Could not confirm {pair} entry')
                return None
            
            # Log to Sheets
            if SHEETS_CLIENT:
                try:
                    log_live_trade_entry(pair, direction, price, amt, target_price, stop_price, 'V5_RSI18')
                except Exception as sheets_err:
                    log(f'Sheets entry log error: {sheets_err}')
            
            # Post detailed open trade to Discord
            risk_pct = (stop_price / price - 1) * 100 if direction == 'BUY' else (1 - stop_price / price) * 100
            post_discord(f'🚀 **OPEN TRADE** | {pair} | {direction} @ ${price:.4f}\n📈 TP: ${target_price:.4f} | 📉 SL: ${stop_price:.4f}\n📦 Size: {amt} | Risk: {abs(risk_pct):.1f}%')
            return pos
        except Exception as outer_exc:
            import traceback
            log(f'Attempt {attempt+1} failed: {outer_exc}')
            log(f'Traceback: {traceback.format_exc()}')
            if attempt < retries - 1:
                time.sleep(5)
    return None

# ============= MONITORING =============
def check_positions():
    to_close = []
    positions = get_positions()
    log(f'Checking {len(positions)} positions...')
    for pos in positions:
        pair = pos.get('pair')
        entry, direction = pos.get('entry', 0), pos.get('direction', 'BUY')
        amt, stop_price = pos.get('amount', 0), pos.get('stop', 0)
        target = pos.get('target', 0)
        trail_price = pos.get('trail_price', 0)
        trail_active = pos.get('trail_active', False)
        
        if not entry or not amt:
            continue
        current = get_price(pair)
        if not current:
            log(f'Could not get price for {pair}')
            continue
        
        # Normalize direction to BUY/SELL
        dir_check = direction if direction in ['BUY', 'SELL'] else ('BUY' if direction == 'LONG' else 'SELL')
        
        log(f'{pair}: entry={entry}, current={current}, SL={stop_price}, TP={target}')
        pnl_pct = ((current-entry)/entry*100) if dir_check=='BUY' else ((entry-current)/entry*100)
        should_close, reason = False, ''
        
        # Check if TP hit - activate trailing stop
        if not trail_active and target and ((dir_check=='BUY' and current>=target) or (dir_check=='SELL' and current<=target)):
            # Activate trailing stop
            pos['trail_active'] = True
            pos['stop'] = pos.get('trail_price', entry * (1 + TRAIL_PCT) if dir_check == 'BUY' else entry * (1 - TRAIL_PCT))
            set_positions(get_positions())  # Save updated stop
            log(f'TRAIL ACTIVATED: {pair} new SL: ${pos["stop"]:.4f}')
        
        # Trailing stop logic
        if trail_active:
            # Update trailing stop to lock in profits
            new_stop = 0
            if dir_check == 'BUY':
                # Trail up: stop follows price, always below current price by TRAIL_PCT
                new_stop = current * (1 - TRAIL_PCT)
                if new_stop > stop_price:
                    pos['stop'] = new_stop
                    set_positions(get_positions())
            else:
                # Trail down: stop follows price, always above current price by TRAIL_PCT
                new_stop = current * (1 + TRAIL_PCT)
                if new_stop < stop_price:
                    pos['stop'] = new_stop
                    set_positions(get_positions())
            stop_price = pos['stop']
        
        # Stop Loss check
        sl_triggered = (dir_check=='BUY' and current<=stop_price) or (dir_check=='SELL' and current>=stop_price)
        log(f'SL check: dir={dir_check}, cur={current}, SL={stop_price}, triggered={sl_triggered}')
        if sl_triggered:
            should_close, reason = True, 'SL'
        # Take Profit
        elif target and not trail_active and ((dir_check=='BUY' and current>=target) or (dir_check=='SELL' and current<=target)):
            should_close, reason = True, 'TP'
        # Time Exit
        elif pos.get('timestamp'):
            ts = pos.get('timestamp')
            # Handle both aware and naive timestamps
            try:
                ts_dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                now_dt = datetime.now(ts_dt.tzinfo) if ts_dt.tzinfo else datetime.now()
                hours = (now_dt - ts_dt.replace(tzinfo=None)).total_seconds()/3600
            except:
                hours = 0
            if hours > MAX_HOLD_HOURS:
                should_close, reason = True, f'TIME({hours:.1f}h)'
        if should_close:
            close_position(pair, current, pnl_pct)
            to_close.append(pair)
    if to_close:
        set_positions([p for p in get_positions() if p.get('pair') not in to_close])

def close_position(pair, current, pnl_pct):
    global e
    # Use dynamic minimum from Binance
    exchange_min = get_min_notional(pair)
    close_min = max(MIN_NOTIONAL, exchange_min)
    
    try:
        pos = next((p for p in get_positions() if p.get('pair') == pair), None)
        if not pos:
            return
        amt, entry, direction = pos.get('amount', 0), pos.get('entry', 0), pos.get('direction', 'BUY')
        
        # Check minimum notional - skip if too small
        notional = amt * current
        if notional < MIN_NOTIONAL:
            log(f'SKIP CLOSE: {pair} notional ${notional:.2f} < ${MIN_NOTIONAL} minimum. Removing from tracking.')
            remove_position(pair)
            return
        
        # Normalize direction
        dir_check = direction if direction in ['BUY', 'SELL'] else ('BUY' if direction == 'LONG' else 'SELL')
        
        # Execute close and get ACTUAL exit price
        actual_exit_price = None
        fee_rate = 0.002
        
        if dir_check == 'BUY':
            result = e.create_market_sell_order(pair, amt)
            if result and 'average' in result:
                actual_exit_price = result['average']
            elif result and 'price' in result:
                actual_exit_price = result['price']
        else:
            result = e.create_market_buy_order(pair, amt)
            if result and 'average' in result:
                actual_exit_price = result['average']
            elif result and 'price' in result:
                actual_exit_price = result['price']
        
        # Verify trade succeeded
        if not result or not actual_exit_price:
            log(f'TRADE CLOSE FAILED: No result for {pair}')
            remove_position(pair)
            return
        
        # Use actual exit price
        actual_exit = actual_exit_price if actual_exit_price else current
        
        # Get entry fee from position
        entry_fee = pos.get('entry_fee', 0)
        
        # Calculate exit fee
        exit_fee = amt * actual_exit * fee_rate
        
        # Calculate TRUE PnL including both entry and exit fees
        raw_pnl = ((actual_exit - entry) * amt) if dir_check == 'BUY' else ((entry - actual_exit) * amt)
        total_fees = entry_fee + exit_fee
        net_pnl = raw_pnl - total_fees
        
        log(f'CLOSED: {pair} Entry: ${entry:.4f} Exit: ${actual_exit:.4f} Raw PnL: ${raw_pnl:.2f} Fees: ${total_fees:.2f} NET: ${net_pnl:.2f}')
        
        # Log to Sheets
        if SHEETS_CLIENT:
            try:
                result = 'WIN' if net_pnl > 0 else 'LOSS'
                log_live_trade_exit(pair, actual_exit, round(net_pnl, 2), result)
            except Exception as e:
                log(f'Sheets exit log error: {e}')
        
        # Post detailed closed trade to Discord with profit AFTER FEES
        post_discord(f'✅ **CLOSED** | {pair} | Entry: ${entry:.4f} | Exit: ${actual_exit:.4f}\n💰 **Profit: ${net_pnl:.2f}** (fees: ${total_fees:.2f})')
        remove_position(pair)
    except Exception as ex:
        log_error(f'Close failed: {ex}')

# ============= SIGNALS =============
def read_signal():
    """Read signal from file, checking for staleness"""
    try:
        if SIGNAL_FILE.exists():
            s = json.load(open(SIGNAL_FILE))
            if isinstance(s, dict):
                # Check if signal is stale (>15 min old)
                sig_time = s.get('timestamp')
                if sig_time:
                    try:
                        sig_dt = datetime.fromisoformat(sig_time.replace('Z', '+00:00'))
                        age_seconds = (datetime.now(sig_dt.tzinfo) - sig_dt).total_seconds()
                        if age_seconds > 600:  # 10 minutes - clear stale signals
                            log(f'Signal stale ({age_seconds/60:.1f} min old), clearing...')
                            clear_signal()  # Clear the stale signal
                            return None
                    except:
                        pass
                return s
    except:
        pass
    return None

def clear_signal():
    """Clear the signal file after trade execution"""
    try:
        if SIGNAL_FILE.exists():
            SIGNAL_FILE.unlink()
            log('Signal file cleared after trade')
    except:
        pass

def generate_signals():
    btc_prices = [x[4] for x in get_ohlcv('BTC/USDT')] if get_ohlcv('BTC/USDT') else None
    signals = []
    for pair in PAIRS:
        ohlcv = get_ohlcv(pair)
        if not ohlcv or len(ohlcv) < 200:
            continue
        prices = [x[4] for x in ohlcv]
        e200, e50 = calc_ema(prices, 200), calc_ema(prices, 50)
        rsi = calc_rsi(prices)
        score = 0
        if prices[-1] > e200: score += 1
        if prices[-1] > max(prices[-11:-1]): score += 1
        if rsi < 35 or rsi > 65: score += 1
        score += 1 # volume
        if btc_prices and len(btc_prices) >= 50:
            if (btc_prices[-1] > calc_ema(btc_prices, 50)) == (prices[-1] > e200):
                score += 2
        if score >= MIN_SCORE:
            sig = 'BUY' if prices[-1] > e200 else 'SELL'
            signals.append({'pair': pair, 'direction': sig, 'score': score, 'price': prices[-1]})
    if signals:
        signals.sort(key=lambda x: x['score'], reverse=True)
        return signals[0]
    return None

# ============= UTILS =============
def post_discord(msg):
    try:
        subprocess.run(f'openclaw message send --channel discord --target {DISCORD_CHANNEL} --message "{msg}"', shell=True, capture_output=True, timeout=10)
    except:
        pass

# ============= MAIN =============
HEARTBEAT_FILE = DATA_DIR / 'heartbeat.txt'
LOCK_FILE = DATA_DIR / 'bot.lock'

def check_already_running():
    """Prevent multiple instances"""
    import os
    if LOCK_FILE.exists():
        # Check if process is still alive by checking heartbeat age
        try:
            with open(HEARTBEAT_FILE, 'r') as f:
                hb = float(f.read().strip())
            # If heartbeat less than 5 minutes old, another instance is running
            if time.time() - hb < 300:
                return True
        except:
            pass
    # Create lock file
    with open(LOCK_FILE, 'w') as f:
        f.write(str(time.time()))
    return False

def write_heartbeat():
    try:
        with open(HEARTBEAT_FILE, 'w') as f:
            f.write(str(time.time()))
    except:
        pass

def start_signal_agent():
    try:
        subprocess.Popen(['python', 'trading_ales/signal-agent.py'], shell=False)
        log('Signal agent started')
    except:
        log('Failed to start signal agent')

SIGNAL_AGENT_TIMEOUT_MINUTES = 5

def check_signal_agent_health():
    """Restart signal agent if no signals for X minutes"""
    try:
        hb_file = Path('trading_ales/signal_heartbeat.txt')
        if hb_file.exists():
            with open(hb_file, 'r') as f:
                hb = float(f.read().strip())
            age_minutes = (time.time() - hb) / 60
            if age_minutes > SIGNAL_AGENT_TIMEOUT_MINUTES:
                log(f'Signal agent stale ({age_minutes:.1f}m) - restarting')
                start_signal_agent()
    except:
        pass

def main():
    # Check if already running
    if check_already_running():
        print('Bot already running - exiting')
        return
    
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / 'logs').mkdir(parents=True, exist_ok=True)
    
    # Clear old positions file first
    set_positions([])
    
    # Sync positions from Binance on startup
    sync_positions_from_exchange()
    
    # Start signal agent automatically
    if SIGNAL_SOURCE == 'EXTERNAL':
        start_signal_agent()
    
    print('='*40)
    print(f'BOT v3.0 - {SIGNAL_SOURCE} MODE')
    print(f'DRY RUN: {DRY_RUN}')
    print('='*40)
    if DRY_RUN:
        log('*** DRY RUN MODE ***')
    start = datetime.now()
    cycle = 0
    # Trading hours controlled by CRON JOB:
    # - Start: 8 AM (cron starts bot)
    # - Stop: 4 PM (cron kills bot)
    # Set to 24/7 here, cron controls when to run
    trading_start_hour = 0   # 12 AM (cron controls start)
    trading_end_hour = 24     # 12 AM (cron controls stop)
    
    while True:
        try:
            # Time check - only open new trades during trading hours
            # BUT always monitor and manage EXISTING positions 24/7
            current_hour = datetime.now().hour
            
            if current_hour < trading_start_hour or current_hour >= trading_end_hour:
                # Outside trading hours - still monitor existing positions!
                log(f'Monitoring positions 24/7...')
                check_positions()  # Still check existing positions for TP/SL
                write_heartbeat()
                time.sleep(SCAN_INTERVAL)
                continue
            
            # Inside trading hours - run normal loop
            cycle += 1
            runtime = (datetime.now() - start).total_seconds()
            if runtime > 24 * 3600:
                break
            check_positions()
            if len(get_positions()) < MAX_POSITIONS and can_trade():
                signal = None
                if SIGNAL_SOURCE == 'EXTERNAL':
                    # Trust signal agent completely - no re-filtering
                    sig = read_signal()
                    if sig:
                        signal = sig
                else:
                    # Internal mode - use own generation with MIN_SCORE
                    signal = generate_signals()
                    if signal and signal.get('score', 0) < MIN_SCORE:
                        signal = None
                if signal:
                    # V3 ULTIMATE uses 'entry', other strategies use 'price'
                    # ALWAYS fetch fresh price from exchange, don't use stale signal price
                    fresh_price = get_price(signal['pair'])
                    if fresh_price:
                        price = fresh_price
                        pair_name = signal.get('pair', 'UNKNOWN')
                        log(f'Using FRESH price: {pair_name} @ ${price}')
                    else:
                        price = signal.get('entry') or signal.get('price')
                    
                    result = execute_trade(signal['pair'], signal['direction'], price)
                    
                    # Clear signal file after trade execution
                    if result:
                        clear_signal()
            
            # Check signal agent health every cycle
            check_signal_agent_health()
            
            if cycle % 50 == 0:
                try:
                    bal = e.fetch_balance()['total'].get('USDT', 0)
                    pos = get_positions()
                    log(f'STATUS: ${bal:.2f} | {len(pos)} pos')
                    
                    # Log balance to Sheets
                    if SHEETS_CLIENT:
                        try:
                            log_balance(round(bal, 2))
                        except Exception as e:
                            log(f'Sheets balance log error: {e}')
                except:
                    pass
            
            write_heartbeat()
            time.sleep(SCAN_INTERVAL)
        except KeyboardInterrupt:
            log('Stopped')
            break
        except Exception as ex:
            log_error(f'Loop: {ex}')
            time.sleep(60)

if __name__ == '__main__':
    main()
