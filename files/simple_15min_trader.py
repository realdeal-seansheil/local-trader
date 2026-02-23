#!/usr/bin/env python3
"""
Simple 15-Minute Crypto Trader
Just finds and executes on the active 15-minute crypto markets
"""

import os
import json
import time
from datetime import datetime as dt
from kalshi_executor import KalshiAuth, KalshiClient
from kalshi_executor import KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH
import requests
import base64
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

# ============================================================
# SIMPLE 15-MINUTE TRADER CONFIGURATION
# ============================================================

# 15-minute crypto series
CRYPTO_15MIN_SERIES = ['KXBTC15M', 'KXETH15M', 'KXSOL15M', 'KXXRP15M']

# Trading parameters
SCAN_INTERVAL = 30              # 30-second scans
POSITION_SIZE = 20             # 20 contracts per trade
MIN_VOLUME = 1000             # Minimum volume threshold
MIN_PROFIT = 0.40             # 40 cent minimum profit

# ============================================================
# API FUNCTIONS
# ============================================================

def get_active_15min_markets(auth):
    """Get active 15-minute crypto markets with real pricing."""
    active_markets = []
    
    for series_ticker in CRYPTO_15MIN_SERIES:
        timestamp = str(int(dt.now().timestamp() * 1000))
        path = f'/trade-api/v2/markets?series_ticker={series_ticker}&limit=100'
        method = 'GET'
        
        msg = timestamp + method + path
        
        sig_bytes = auth.private_key.sign(
            msg.encode(),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH
            ),
            hashes.SHA256()
        )
        signature = base64.b64encode(sig_bytes).decode()
        
        headers = {
            'KALSHI-ACCESS-KEY': auth.api_key_id,
            'KALSHI-ACCESS-SIGNATURE': signature,
            'KALSHI-ACCESS-TIMESTAMP': timestamp,
            'Content-Type': 'application/json',
        }
        
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
                
                # Check if market has real pricing and volume
                has_pricing = (yes_ask > 0 and yes_ask < 100) or (no_ask > 0 and no_ask < 100)
                has_volume = volume > 0
                is_active = status == 'active'
                
                if has_pricing and has_volume and is_active:
                    active_markets.append({
                        'ticker': ticker,
                        'title': title,
                        'yes_ask': yes_ask,
                        'no_ask': no_ask,
                        'volume': volume,
                        'series': series_ticker
                    })
    
    return active_markets

def place_order_direct(auth, ticker: str, side: str, count: int, price: int) -> dict:
    """Place order using direct API call."""
    try:
        timestamp = str(int(dt.now().timestamp() * 1000))
        path = "/trade-api/v2/portfolio/orders"
        method = "POST"
        
        # Convert price from cents to dollars
        price_dollars = f"{price/100:.4f}"
        
        # Order payload
        if side == "yes":
            payload = {
                "ticker": ticker,
                "side": "yes",
                "action": "buy",
                "count": count,
                "yes_price": price,
                "yes_price_dollars": price_dollars,
                "time_in_force": "good_till_canceled"
            }
        else:  # side == "no"
            payload = {
                "ticker": ticker,
                "side": "no",
                "action": "buy",
                "count": count,
                "no_price": price,
                "no_price_dollars": price_dollars,
                "time_in_force": "good_till_canceled"
            }
        
        # Create signature
        msg = timestamp + method + path + json.dumps(payload)
        
        sig_bytes = auth.private_key.sign(
            msg.encode(),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH
            ),
            hashes.SHA256()
        )
        signature = base64.b64encode(sig_bytes).decode()
        
        headers = {
            "KALSHI-ACCESS-KEY": auth.api_key_id,
            "KALSHI-ACCESS-SIGNATURE": signature,
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
            "Content-Type": "application/json",
        }
        
        url = "https://api.elections.kalshi.com" + path
        resp = requests.post(url, headers=headers, json=payload, timeout=15)
        
        if resp.status_code == 200:
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

def execute_trade(auth, market):
    """Execute a trade on a market."""
    ticker = market['ticker']
    yes_ask = market['yes_ask']
    no_ask = market['no_ask']
    volume = market['volume']
    
    # Find the best trade
    best_trade = None
    if yes_ask > 0 and yes_ask < 80:
        profit = 100 - yes_ask
        best_trade = ('YES', yes_ask, profit)
    if no_ask > 0 and no_ask < 80:
        profit = 100 - no_ask
        if not best_trade or profit > best_trade[2]:
            best_trade = ('NO', no_ask, profit)
    
    if best_trade:
        direction, price, profit = best_trade
        expected_profit = profit * POSITION_SIZE / 100
        
        print(f"\n🚨 EXECUTING TRADE: {ticker}")
        print(f"   📊 {market['title']}")
        print(f"   💰 {direction} at {price}c")
        print(f"   📊 Volume: {volume}")
        print(f"   💸 Expected profit: ${expected_profit:.2f}")
        
        # Place the order
        result = place_order_direct(auth, ticker, direction.lower(), POSITION_SIZE, price)
        
        if "success" in result:
            print(f"   ✅ SUCCESS: Order placed!")
            print(f"      Order ID: {result.get('order_id', 'unknown')}")
            print(f"      Expected profit: ${expected_profit:.2f}")
            
            # Log the trade
            trade_log = {
                "timestamp": dt.now().isoformat(),
                "ticker": ticker,
                "direction": direction,
                "entry_price": price,
                "contracts": POSITION_SIZE,
                "expected_profit": expected_profit,
                "order_id": result.get('order_id', 'unknown'),
                "success": True
            }
            
            os.makedirs('data', exist_ok=True)
            with open('data/simple_trades.jsonl', 'a') as f:
                f.write(json.dumps(trade_log) + '\n')
            
            return True
        else:
            print(f"   ❌ Trade failed: {result.get('error', 'unknown')}")
            print(f"   📊 Details: {result.get('detail', '')[:100]}")
            
            # Log the failure
            trade_log = {
                "timestamp": dt.now().isoformat(),
                "ticker": ticker,
                "direction": direction,
                "entry_price": price,
                "contracts": POSITION_SIZE,
                "error": result.get('error', 'unknown'),
                "details": result.get('detail', ''),
                "success": False
            }
            
            os.makedirs('data', exist_ok=True)
            with open('data/simple_trades.jsonl', 'a') as f:
                f.write(json.dumps(trade_log) + '\n')
            
            return False
    
    return False

# ============================================================
# MAIN TRADING LOOP
# ============================================================

def run_simple_15min_trader():
    """Run the simple 15-minute crypto trader."""
    print("=" * 70)
    print("🚨 SIMPLE 15-MINUTE CRYPTO TRADER")
    print("💰 Finds and executes on active 15-minute crypto markets")
    print("⚡ Real-time market detection and trading")
    print("=" * 70)
    
    # Check API key
    if not KALSHI_API_KEY_ID or KALSHI_API_KEY_ID == "YOUR_API_KEY_ID":
        print("❌ Please set KALSHI_API_KEY_ID environment variable")
        return
    
    try:
        # Initialize authentication
        auth = KalshiAuth(KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH)
        
        # Test authentication
        client = KalshiClient(auth)
        test_markets = client.get_markets(limit=1)
        
        if not test_markets.get('markets'):
            print("❌ Authentication failed - no market access")
            return
        
        print(f"✅ Authentication successful")
        print(f"🎯 Target series: {', '.join(CRYPTO_15MIN_SERIES)}")
        print(f"⚡ Scan interval: {SCAN_INTERVAL} seconds")
        print(f"💰 Position size: {POSITION_SIZE} contracts")
        
        # Trading loop
        scan_count = 0
        executed_trades = set()
        
        print(f"\n🚨 Starting simple 15-minute trading...")
        
        while True:  # Continuous scanning
            try:
                scan_count += 1
                current_time = dt.now()
                
                print(f"\n{'='*60}")
                print(f"📊 SCAN #{scan_count} | {current_time.strftime('%H:%M:%S')}")
                
                # Get active markets
                active_markets = get_active_15min_markets(auth)
                
                if active_markets:
                    print(f"🎯 Found {len(active_markets)} active 15-minute markets!")
                    
                    # Sort by volume (most liquid first)
                    active_markets.sort(key=lambda x: x['volume'], reverse=True)
                    
                    for market in active_markets:
                        ticker = market['ticker']
                        
                        # Skip if already traded
                        if ticker in executed_trades:
                            print(f"📊 {ticker}: Already traded")
                            continue
                        
                        # Check if it meets our criteria
                        yes_ask = market['yes_ask']
                        no_ask = market['no_ask']
                        volume = market['volume']
                        
                        # Find best opportunity
                        best_trade = None
                        if yes_ask > 0 and yes_ask < 80:
                            profit = 100 - yes_ask
                            if profit >= MIN_PROFIT * 100:
                                best_trade = ('YES', yes_ask, profit)
                        
                        if no_ask > 0 and no_ask < 80:
                            profit = 100 - no_ask
                            if profit >= MIN_PROFIT * 100:
                                if not best_trade or profit > best_trade[2]:
                                    best_trade = ('NO', no_ask, profit)
                        
                        if best_trade and volume >= MIN_VOLUME:
                            direction, price, profit = best_trade
                            expected_profit = profit * POSITION_SIZE / 100
                            
                            print(f"\n🚨 OPPORTUNITY: {ticker}")
                            print(f"   📊 {market['title']}")
                            print(f"   💰 {direction} at {price}c | Profit: {profit}c")
                            print(f"   📊 Volume: {volume}")
                            print(f"   💸 Expected profit: ${expected_profit:.2f}")
                            
                            # Execute the trade
                            success = execute_trade(auth, market)
                            
                            if success:
                                executed_trades.add(ticker)
                                print(f"\n🎉 TRADE EXECUTED SUCCESSFULLY!")
                                print(f"💰 Total trades executed: {len(executed_trades)}")
                            else:
                                print(f"\n❌ Trade execution failed")
                        else:
                            print(f"📊 {ticker}: Doesn't meet criteria")
                else:
                    print(f"📊 No active 15-minute markets found")
                    print(f"💡 Waiting for new markets to appear...")
                
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

if __name__ == "__main__":
    run_simple_15min_trader()
