#!/usr/bin/env python3
"""
Enhanced 15-Minute Crypto Trader
Implements proper EV calculation, Kelly sizing, SQLite persistence, and P&L reconciliation
"""

import os
import json
import time
import sqlite3
import requests
import base64
from datetime import datetime as dt, timedelta
from kalshi_executor import KalshiAuth, KalshiClient
from kalshi_executor import KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

# ============================================================
# ENHANCED 15-MINUTE TRADER CONFIGURATION
# ============================================================

# 15-minute crypto series
CRYPTO_15MIN_SERIES = ['KXBTC15M', 'KXETH15M', 'KXSOL15M', 'KXXRP15M']

# Trading parameters
SCAN_INTERVAL = 30              # 30-second scans
MIN_VOLUME = 1000             # Minimum volume threshold
MIN_EV_THRESHOLD = 3          # Minimum 3 cents EV per contract
MIN_TIME_REMAINING = 5 * 60   # 5 minutes minimum remaining
MAX_POSITION_SIZE = 20        # Maximum contracts per trade
KELLY_FRACTION = 0.5          # Use half-Kelly for safety

# Signal configuration
USE_MOMENTUM_SIGNAL = True     # Enable momentum-based signals
MOMENTUM_WINDOW = 300         # 5-minute momentum window
MIN_MOMENTUM_THRESHOLD = 0.008 # 0.8% minimum momentum

# Database configuration
DB_PATH = 'data/enhanced_15min_trader.db'

# ============================================================
# DATABASE SETUP
# ============================================================

def setup_database():
    """Initialize SQLite database for persistent state tracking."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Trades table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            order_id TEXT,
            direction TEXT,           -- YES or NO
            entry_price INTEGER,      -- cents
            contracts INTEGER,
            cost_basis INTEGER,       -- entry_price * contracts (cents)
            estimated_win_prob REAL,
            ev_per_contract REAL,
            kelly_fraction REAL,
            entry_time TEXT,
            expiry_time TEXT,
            status TEXT DEFAULT 'open', -- open, won, lost, cancelled
            exit_price INTEGER,
            realized_pnl INTEGER,     -- cents, actual outcome
            signal_source TEXT,
            market_resolution TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Scans table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS scans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_time TEXT,
            markets_found INTEGER,
            signals_found INTEGER,
            trades_taken INTEGER,
            balance_cents INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Market data table for backtesting
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS market_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT,
            timestamp TEXT,
            yes_ask INTEGER,
            no_ask INTEGER,
            volume INTEGER,
            status TEXT,
            close_time TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()

# ============================================================
# AUTHENTICATION FUNCTIONS
# ============================================================

def get_headers(auth, method: str, path: str) -> dict:
    """Generate authenticated headers using the correct method."""
    timestamp = str(int(dt.now().timestamp() * 1000))
    path_without_query = path.split("?")[0]
    msg = timestamp + method.upper() + path_without_query

    signature = ""
    if auth.private_key:
        sig_bytes = auth.private_key.sign(
            msg.encode(),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH
            ),
            hashes.SHA256()
        )
        signature = base64.b64encode(sig_bytes).decode()

    return {
        "KALSHI-ACCESS-KEY": auth.api_key_id,
        "KALSHI-ACCESS-SIGNATURE": signature,
        "KALSHI-ACCESS-TIMESTAMP": timestamp,
        "Content-Type": "application/json",
    }

# ============================================================
# SIGNAL GENERATION
# ============================================================

def calculate_momentum_signal(market_data):
    """
    Calculate momentum signal based on price changes.
    This is a placeholder - in production, you'd use real price feeds.
    """
    if not USE_MOMENTUM_SIGNAL:
        return 0.5  # No edge, neutral probability
    
    # For now, use orderbook imbalance as a proxy for momentum
    yes_ask = market_data.get('yes_ask', 0)
    no_ask = market_data.get('no_ask', 0)
    volume = market_data.get('volume', 0)
    
    if yes_ask == 0 or no_ask == 0 or volume < MIN_VOLUME:
        return 0.5  # No signal
    
    # Simple momentum: if YES is cheap relative to NO, bias toward YES
    yes_prob = yes_ask / 100
    no_prob = no_ask / 100
    
    # Imbalance signal
    if yes_prob < 0.45 and no_prob > 0.55:
        return 0.55  # Slight YES bias
    elif yes_prob > 0.55 and no_prob < 0.45:
        return 0.45  # Slight NO bias
    
    return 0.5  # Neutral

def calculate_ev(yes_ask, no_ask, win_prob, direction):
    """
    Calculate Expected Value per contract.
    EV = (win_prob * payout) - (loss_prob * cost)
    """
    if direction == 'YES':
        cost = yes_ask
        payout = 100 - cost
    else:  # NO
        cost = no_ask
        payout = 100 - cost
    
    loss_prob = 1 - win_prob
    ev_per_contract = (win_prob * payout) - (loss_prob * cost)
    
    return ev_per_contract

def calculate_kelly_fraction(win_prob, cost):
    """
    Calculate Kelly fraction for position sizing.
    Uses half-Kelly for safety.
    """
    if win_prob <= 0.5:
        return 0  # No bet if no edge
    
    payout_ratio = (100 - cost) / cost
    kelly_f = (win_prob - (1 - win_prob)) / payout_ratio
    half_kelly = kelly_f * KELLY_FRACTION
    
    return max(0, min(half_kelly, 0.2))  # Cap at 20% of bankroll

# ============================================================
# MARKET DATA FUNCTIONS
# ============================================================

def get_active_15min_markets(auth):
    """Get active 15-minute crypto markets with real pricing."""
    active_markets = []
    
    for series_ticker in CRYPTO_15MIN_SERIES:
        timestamp = str(int(dt.now().timestamp() * 1000))
        path = f'/trade-api/v2/markets?series_ticker={series_ticker}&limit=100'
        method = 'GET'
        
        headers = get_headers(auth, method, path)
        url = 'https://api.elections.kalshi.com' + path
        resp = requests.get(url, headers=headers, timeout=15)
        
        if resp.status_code == 200:
            data = resp.json()
            markets = data.get('markets', [])
            
            for market in markets:
                ticker = market.get('ticker', '')
                title = market.get('title', '')
                yes_ask = market.get('yes_ask', 0)
                no_ask = market.get('no_ask', 0)
                volume = market.get('volume', 0)
                status = market.get('status', '')
                close_time = market.get('close_time', '')
                
                # Check if market has real pricing and volume
                has_pricing = (yes_ask > 0 and yes_ask < 100) or (no_ask > 0 and no_ask < 100)
                has_volume = volume > 0
                is_active = status == 'active'
                
                # Check time remaining
                now = dt.now()
                if close_time:
                    expiry = dt.fromisoformat(close_time.replace('Z', '+00:00'))
                    seconds_remaining = (expiry - now).total_seconds()
                else:
                    seconds_remaining = 0
                
                if has_pricing and has_volume and is_active and seconds_remaining > MIN_TIME_REMAINING:
                    # Store market snapshot
                    store_market_snapshot(ticker, yes_ask, no_ask, volume, status, close_time)
                    
                    active_markets.append({
                        'ticker': ticker,
                        'title': title,
                        'yes_ask': yes_ask,
                        'no_ask': no_ask,
                        'volume': volume,
                        'series': series_ticker,
                        'close_time': close_time,
                        'seconds_remaining': seconds_remaining
                    })
    
    return active_markets

def store_market_snapshot(ticker, yes_ask, no_ask, volume, status, close_time):
    """Store market data for backtesting and analysis."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO market_snapshots 
        (ticker, timestamp, yes_ask, no_ask, volume, status, close_time)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (ticker, dt.now().isoformat(), yes_ask, no_ask, volume, status, close_time))
    
    conn.commit()
    conn.close()

# ============================================================
# ORDER EXECUTION
# ============================================================

def place_order_direct(auth, ticker: str, side: str, count: int, price: int) -> dict:
    """Place order using direct API call with correct authentication."""
    try:
        timestamp = str(int(dt.now().timestamp() * 1000))
        path = "/trade-api/v2/portfolio/orders"
        method = "POST"
        
        # Order payload (correct format)
        import uuid
        order_data = {
            "ticker": ticker,
            "side": side,
            "action": "buy",
            "count": count,
            "type": "limit",
            f"{side}_price": price,
            "client_order_id": str(uuid.uuid4()),
        }
        
        # Generate headers using correct method
        headers = get_headers(auth, method, path)
        
        url = "https://api.elections.kalshi.com" + path
        resp = requests.post(url, headers=headers, json=order_data, timeout=15)
        
        if resp.status_code == 201:
            data = resp.json()
            return {
                "success": True,
                "order": data.get("order", {}),
                "order_id": data.get("order", {}).get("order_id")
            }
        else:
            return {
                "error": resp.status_code,
                "detail": resp.text
            }
            
    except Exception as e:
        return {
            "error": "exception",
            "detail": str(e)
        }

# ============================================================
# TRADE MANAGEMENT
# ============================================================

def execute_trade_enhanced(auth, market, win_prob, ev_per_contract, kelly_frac):
    """Execute a trade with proper position sizing and tracking."""
    ticker = market['ticker']
    yes_ask = market['yes_ask']
    no_ask = market['no_ask']
    volume = market['volume']
    
    # Determine best direction based on EV
    yes_ev = calculate_ev(yes_ask, no_ask, win_prob, 'YES')
    no_ev = calculate_ev(yes_ask, no_ask, 1 - win_prob, 'NO')
    
    if yes_ev > no_ev and yes_ev > MIN_EV_THRESHOLD:
        direction = 'YES'
        price = yes_ask
        ev = yes_ev
    elif no_ev > MIN_EV_THRESHOLD:
        direction = 'NO'
        price = no_ask
        ev = no_ev
    else:
        return False, "EV below threshold"
    
    # Calculate position size based on Kelly and available balance
    max_contracts_by_kelly = int(kelly_frac * 6187 / price)  # $61.87 balance in cents
    contracts = min(max_contracts_by_kelly, MAX_POSITION_SIZE)
    
    if contracts < 1:
        return False, "Position size too small"
    
    expected_profit = ev * contracts
    
    print(f"\n🚨 EXECUTING TRADE: {ticker}")
    print(f"   📊 {market['title']}")
    print(f"   💰 {direction} at {price}c")
    print(f"   📈 Win prob: {win_prob:.1%}")
    print(f"   💸 EV per contract: {ev:.1f}c")
    print(f"   📊 Kelly fraction: {kelly_frac:.1%}")
    print(f"   📈 Contracts: {contracts}")
    print(f"   💸 Expected profit: ${expected_profit/100:.2f}")
    
    # Place the order
    result = place_order_direct(auth, ticker, direction.lower(), contracts, price)
    
    if "success" in result:
        order_id = result.get('order_id', 'unknown')
        cost_basis = price * contracts
        
        # Store trade in database
        store_trade(
            ticker=ticker,
            order_id=order_id,
            direction=direction,
            entry_price=price,
            contracts=contracts,
            cost_basis=cost_basis,
            estimated_win_prob=win_prob,
            ev_per_contract=ev,
            kelly_fraction=kelly_frac,
            expiry_time=market['close_time'],
            signal_source='momentum'
        )
        
        print(f"   ✅ SUCCESS: Order placed!")
        print(f"      Order ID: {order_id}")
        print(f"      Expected profit: ${expected_profit/100:.2f}")
        
        return True, order_id
    else:
        print(f"   ❌ Trade failed: {result.get('error', 'unknown')}")
        print(f"   📊 Details: {result.get('detail', '')[:100]}")
        
        return False, result.get('detail', '')

def store_trade(ticker, order_id, direction, entry_price, contracts, cost_basis, 
                estimated_win_prob, ev_per_contract, kelly_fraction, expiry_time, signal_source):
    """Store trade details in database."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO trades 
        (ticker, order_id, direction, entry_price, contracts, cost_basis, 
         estimated_win_prob, ev_per_contract, kelly_fraction, entry_time, 
         expiry_time, signal_source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (ticker, order_id, direction, entry_price, contracts, cost_basis,
          estimated_win_prob, ev_per_contract, kelly_fraction, dt.now().isoformat(),
          expiry_time, signal_source))
    
    conn.commit()
    conn.close()

# ============================================================
# P&L RECONCILIATION
# ============================================================

def reconcile_trades(auth):
    """Reconcile settled trades and update P&L."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Get open trades
    cursor.execute('''
        SELECT id, ticker, direction, entry_price, contracts, expiry_time
        FROM trades WHERE status = 'open'
    ''')
    
    open_trades = cursor.fetchall()
    
    for trade_id, ticker, direction, entry_price, contracts, expiry_time in open_trades:
        # Check if market has resolved
        try:
            timestamp = str(int(dt.now().timestamp() * 1000))
            path = f'/trade-api/v2/markets/{ticker}'
            method = 'GET'
            
            headers = get_headers(auth, method, path)
            url = 'https://api.elections.kalshi.com' + path
            resp = requests.get(url, headers=headers, timeout=15)
            
            if resp.status_code == 200:
                market_data = resp.json()
                status = market_data.get('status', '')
                resolution = market_data.get('resolution', '')
                
                if status == 'closed' and resolution:
                    # Calculate realized P&L
                    if (direction == 'YES' and resolution == 'yes') or \
                       (direction == 'NO' and resolution == 'no'):
                        # Won
                        realized_pnl = (100 - entry_price) * contracts
                        trade_status = 'won'
                    else:
                        # Lost
                        realized_pnl = -(entry_price * contracts)
                        trade_status = 'lost'
                    
                    # Update trade record
                    cursor.execute('''
                        UPDATE trades 
                        SET status = ?, market_resolution = ?, realized_pnl = ?
                        WHERE id = ?
                    ''', (trade_status, resolution, realized_pnl, trade_id))
                    
                    print(f"💰 Trade {ticker} resolved: {trade_status}, P&L: ${realized_pnl/100:.2f}")
                    
        except Exception as e:
            print(f"❌ Error reconciling trade {ticker}: {e}")
    
    conn.commit()
    conn.close()

def get_performance_stats():
    """Get comprehensive performance statistics."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Trade statistics
    cursor.execute('''
        SELECT 
            COUNT(*) as total_trades,
            COUNT(CASE WHEN status = 'won' THEN 1 END) as winning_trades,
            COUNT(CASE WHEN status = 'lost' THEN 1 END) as losing_trades,
            SUM(CASE WHEN status = 'won' THEN realized_pnl ELSE 0 END) as total_profit,
            SUM(CASE WHEN status = 'lost' THEN realized_pnl ELSE 0 END) as total_loss,
            AVG(estimated_win_prob) as avg_win_prob,
            AVG(ev_per_contract) as avg_ev,
            AVG(kelly_fraction) as avg_kelly
        FROM trades
    ''')
    
    trade_stats = cursor.fetchone()
    
    # Recent performance
    cursor.execute('''
        SELECT direction, entry_price, contracts, status, realized_pnl, entry_time
        FROM trades 
        ORDER BY entry_time DESC 
        LIMIT 10
    ''')
    
    recent_trades = cursor.fetchall()
    
    conn.close()
    
    return trade_stats, recent_trades

# ============================================================
# MAIN TRADING LOOP
# ============================================================

def run_enhanced_15min_trader():
    """Run the enhanced 15-minute crypto trader."""
    print("=" * 70)
    print("🚨 ENHANCED 15-MINUTE CRYPTO TRADER")
    print("💰 Proper EV calculation, Kelly sizing, and P&L reconciliation")
    print("📈 SQLite persistence and performance tracking")
    print("=" * 70)
    
    # Setup database
    setup_database()
    
    # Check API key
    if not KALSHI_API_KEY_ID or KALSHI_API_KEY_ID == "YOUR_API_KEY_ID":
        print("❌ Please set KALSHI_API_KEY_ID environment variable")
        return
    
    try:
        # Initialize authentication
        auth = KalshiAuth(KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH)
        
        # Test authentication (no test order!)
        print(f"\n🔍 TESTING AUTHENTICATION...")
        
        timestamp = str(int(dt.now().timestamp() * 1000))
        path = "/trade-api/v2/portfolio/balance"
        method = "GET"
        
        headers = get_headers(auth, method, path)
        url = "https://api.elections.kalshi.com" + path
        resp = requests.get(url, headers=headers, timeout=15)
        
        if resp.status_code == 200:
            balance_data = resp.json()
            balance = balance_data.get("balance", 0)
            print(f"✅ Authentication successful!")
            print(f"💰 Balance: ${balance/100:.2f}")
        else:
            print(f"❌ Authentication failed: {resp.status_code}")
            return
        
        # Trading loop
        scan_count = 0
        
        print(f"\n🚨 Starting enhanced 15-minute trading...")
        
        while True:  # Continuous scanning
            try:
                scan_count += 1
                current_time = dt.now()
                
                print(f"\n{'='*60}")
                print(f"📊 SCAN #{scan_count} | {current_time.strftime('%H:%M:%S')}")
                
                # Reconcile any settled trades
                reconcile_trades(auth)
                
                # Get performance stats
                trade_stats, recent_trades = get_performance_stats()
                if trade_stats[0] > 0:
                    win_rate = (trade_stats[1] / trade_stats[0]) * 100
                    net_pnl = (trade_stats[3] or 0) + (trade_stats[4] or 0)
                    print(f"📈 Performance: {trade_stats[0]} trades, {win_rate:.1f}% win rate, ${net_pnl/100:.2f} P&L")
                
                # Get active markets
                active_markets = get_active_15min_markets(auth)
                
                if active_markets:
                    print(f"🎯 Found {len(active_markets)} active 15-minute markets!")
                    
                    # Sort by volume (most liquid first)
                    active_markets.sort(key=lambda x: x['volume'], reverse=True)
                    
                    trades_taken = 0
                    
                    for market in active_markets:
                        # Generate signal
                        win_prob = calculate_momentum_signal(market)
                        
                        # Calculate EV for both sides
                        yes_ev = calculate_ev(market['yes_ask'], market['no_ask'], win_prob, 'YES')
                        no_ev = calculate_ev(market['yes_ask'], market['no_ask'], 1 - win_prob, 'NO')
                        best_ev = max(yes_ev, no_ev)
                        
                        if best_ev > MIN_EV_THRESHOLD:
                            # Calculate Kelly fraction
                            if yes_ev > no_ev:
                                kelly_frac = calculate_kelly_fraction(win_prob, market['yes_ask'])
                            else:
                                kelly_frac = calculate_kelly_fraction(1 - win_prob, market['no_ask'])
                            
                            # Execute trade
                            success, result = execute_trade_enhanced(
                                auth, market, win_prob, best_ev, kelly_frac
                            )
                            
                            if success:
                                trades_taken += 1
                                print(f"\n🎉 TRADE EXECUTED SUCCESSFULLY!")
                            else:
                                print(f"\n❌ Trade execution failed: {result}")
                        else:
                            print(f"📊 {market['ticker']}: EV {best_ev:.1f}c below threshold")
                    
                    # Record scan
                    store_scan(len(active_markets), 0, trades_taken)
                    
                else:
                    print(f"📊 No active 15-minute markets found")
                    print(f"💡 Waiting for new markets to appear...")
                    store_scan(0, 0, 0)
                
                # Wait for next scan
                print(f"\n⏳ Waiting {SCAN_INTERVAL} seconds for next scan...")
                time.sleep(SCAN_INTERVAL)
                
            except KeyboardInterrupt:
                print(f"\n🛑 Manual shutdown")
                break
            except Exception as e:
                print(f"❌ Error in trading loop: {e}")
                time.sleep(30)
        
    except Exception as e:
        print(f"❌ Trader initialization failed: {e}")

def store_scan(markets_found, signals_found, trades_taken):
    """Store scan statistics."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO scans (scan_time, markets_found, signals_found, trades_taken)
        VALUES (?, ?, ?, ?)
    ''', (dt.now().isoformat(), markets_found, signals_found, trades_taken))
    
    conn.commit()
    conn.close()

if __name__ == "__main__":
    run_enhanced_15min_trader()
