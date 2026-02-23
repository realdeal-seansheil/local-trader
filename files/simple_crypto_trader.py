#!/usr/bin/env python3
"""
Simple Crypto Trader - Demo API Version
Uses demo API for testing where orders work
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
# CONFIGURATION
# ============================================================

# Use demo API for testing (orders work in demo)
USE_DEMO = True
BASE_URL = "https://demo-api.kalshi.co/trade-api/v2" if USE_DEMO else "https://api.elections.kalshi.com/trade-api/v2"

# Trading Parameters
SCAN_INTERVAL = 60              # 60-second scans
MAX_CONTRACTS_PER_TRADE = 5      # Smaller position size for testing
SESSION_DURATION_HOURS = 1       # Short session for testing

# Crypto Series to Monitor
CRYPTO_SERIES = [
    'KXSATOSHIBTCYEAR',      # Satoshi Bitcoin movement
    'KXDOGE',                # Dogecoin events
    'KXETHATH',              # Ethereum ATH events
]

# ============================================================
# API FUNCTIONS
# ============================================================

def get_demo_balance(auth):
    """Get balance from demo API."""
    try:
        timestamp = str(int(dt.now().timestamp() * 1000))
        path = "/trade-api/v2/portfolio/balance"
        method = "GET"
        
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
            "KALSHI-ACCESS-KEY": auth.api_key_id,
            "KALSHI-ACCESS-SIGNATURE": signature,
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
            "Content-Type": "application/json",
        }
        
        url = BASE_URL + path
        resp = requests.get(url, headers=headers, timeout=15)
        
        if resp.status_code == 200:
            data = resp.json()
            return data.get("balance", 10000)  # Default $100 for demo
        else:
            print(f"❌ Demo balance check failed: {resp.status_code}")
            return 10000
            
    except Exception as e:
        print(f"❌ Demo balance error: {e}")
        return 10000

def get_crypto_markets(auth, series_ticker):
    """Get crypto markets from demo API."""
    try:
        timestamp = str(int(dt.now().timestamp() * 1000))
        path = f'/trade-api/v2/markets?series_ticker={series_ticker}&limit=10'
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
        
        url = BASE_URL + path
        resp = requests.get(url, headers=headers, timeout=15)
        
        if resp.status_code == 200:
            data = resp.json()
            return data.get('markets', [])
        else:
            print(f"❌ Error getting markets: {resp.status_code}")
            return []
            
    except Exception as e:
        print(f"❌ Exception getting markets: {e}")
        return []

def place_demo_order(auth, ticker: str, side: str, count: int, price: int) -> dict:
    """Place order using demo API."""
    try:
        timestamp = str(int(dt.now().timestamp() * 1000))
        path = "/trade-api/v2/portfolio/orders"
        method = "POST"
        
        # Order payload
        if side == "yes":
            payload = {
                "ticker": ticker,
                "side": "yes",
                "action": "buy",
                "count": count,
                "yes_price": price,
                "yes_price_dollars": f"{price/100:.4f}",
                "time_in_force": "good_till_canceled"
            }
        else:
            payload = {
                "ticker": ticker,
                "side": "no",
                "action": "buy",
                "count": count,
                "no_price": price,
                "no_price_dollars": f"{price/100:.4f}",
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
        
        url = BASE_URL + path
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

# ============================================================
# TRADING LOGIC
# ============================================================

def analyze_opportunities(auth):
    """Analyze trading opportunities."""
    opportunities = []
    
    print("🔍 Analyzing crypto opportunities...")
    
    for series_ticker in CRYPTO_SERIES:
        markets = get_crypto_markets(auth, series_ticker)
        print(f"   📊 {series_ticker}: {len(markets)} markets")
        
        for market in markets:
            ticker = market.get('ticker', '')
            title = market.get('title', '')
            yes_ask = market.get('yes_ask', 0)
            no_ask = market.get('no_ask', 0)
            volume = market.get('volume', 0)
            status = market.get('status', 'unknown')
            
            # Skip markets with no pricing
            if yes_ask == 0 and no_ask == 0:
                continue
            
            # Simple momentum signal
            if yes_ask > 0 and yes_ask < 50:  # YES is cheap (< 50c)
                opportunities.append({
                    "ticker": ticker,
                    "series": series_ticker,
                    "title": title,
                    "direction": "YES",
                    "entry_price": yes_ask,
                    "confidence": (50 - yes_ask) / 50,
                    "volume": volume,
                    "strategy": "momentum_yes",
                    "status": status
                })
            
            if no_ask > 0 and no_ask < 50:  # NO is cheap (< 50c)
                opportunities.append({
                    "ticker": ticker,
                    "series": series_ticker,
                    "title": title,
                    "direction": "NO",
                    "entry_price": no_ask,
                    "confidence": (50 - no_ask) / 50,
                    "volume": volume,
                    "strategy": "momentum_no",
                    "status": status
                })
    
    # Sort by confidence
    opportunities.sort(key=lambda x: x["confidence"], reverse=True)
    
    print(f"🎯 Found {len(opportunities)} opportunities")
    
    if opportunities:
        print(f"🚀 Top 3 opportunities:")
        for i, opp in enumerate(opportunities[:3]):
            print(f"   {i+1}. {opp['ticker']} ({opp['direction']})")
            print(f"      Confidence: {opp['confidence']:.3f} | Price: {opp['entry_price']}c")
            print(f"      📊 {opp['title'][:50]}")
    
    return opportunities

def execute_trade(auth, opportunity, balance):
    """Execute a trade."""
    ticker = opportunity["ticker"]
    direction = opportunity["direction"]
    entry_price = opportunity["entry_price"]
    
    # Calculate position size
    contracts = min(MAX_CONTRACTS_PER_TRADE, int(balance / 1000))  # Conservative sizing
    
    if contracts < 1:
        print(f"❌ Insufficient balance for {ticker}")
        return None
    
    print(f"\n🎯 EXECUTING TRADE: {ticker}")
    print(f"   📊 Direction: {direction}")
    print(f"   💰 Entry price: {entry_price}c")
    print(f"   📈 Contracts: {contracts}")
    print(f"   📊 Confidence: {opportunity['confidence']:.3f}")
    
    # Place the order
    result = place_demo_order(auth, ticker, direction, contracts, entry_price)
    
    if "success" in result:
        print(f"   ✅ SUCCESS: Order placed!")
        print(f"      Order ID: {result.get('order_id', 'unknown')}")
        return result
    else:
        print(f"   ❌ Order failed: {result.get('error', 'unknown')}")
        print(f"   📊 Details: {result.get('detail', '')[:100]}")
        return result

# ============================================================
# MAIN TRADING LOOP
# ============================================================

def run_simple_crypto_trader():
    """Run the simple crypto trader."""
    print("=" * 80)
    print("🚀 SIMPLE CRYPTO TRADER - DEMO API")
    print("💰 Testing Order Execution with Demo API")
    print("=" * 80)
    
    # Check API key
    if not KALSHI_API_KEY_ID or KALSHI_API_KEY_ID == "YOUR_API_KEY_ID":
        print("❌ Please set KALSHI_API_KEY_ID environment variable")
        return
    
    try:
        # Initialize authentication
        auth = KalshiAuth(KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH)
        
        print(f"✅ Using {'DEMO' if USE_DEMO else 'LIVE'} API")
        print(f"🌐 Base URL: {BASE_URL}")
        
        # Get balance
        balance = get_demo_balance(auth)
        print(f"💰 Starting balance: ${balance/100:.2f}")
        
        # Test order placement
        print(f"\n🔍 Testing order placement...")
        
        # Get a market for testing
        markets = get_crypto_markets(auth, 'KXSATOSHIBTCYEAR')
        if markets:
            test_market = markets[0]
            ticker = test_market.get('ticker', '')
            yes_ask = test_market.get('yes_ask', 0)
            
            if yes_ask > 0:
                print(f"📈 Testing with market: {ticker}")
                print(f"   📊 YES ask: {yes_ask}c")
                
                # Test order
                test_result = place_demo_order(auth, ticker, 'yes', 1, yes_ask)
                
                if "success" in test_result:
                    print(f"✅ DEMO ORDER EXECUTION WORKS!")
                    print(f"   🎉 Order ID: {test_result.get('order_id')}")
                    
                    # Now run the trading loop
                    print(f"\n🚀 Starting trading loop...")
                    run_trading_loop(auth, balance)
                else:
                    print(f"❌ Demo order execution failed")
                    print(f"   📊 Error: {test_result}")
            else:
                print(f"❌ No valid pricing found for testing")
        else:
            print(f"❌ No markets found for testing")
        
    except Exception as e:
        print(f"❌ Initialization failed: {e}")

def run_trading_loop(auth, initial_balance):
    """Run the main trading loop."""
    start_time = dt.now()
    end_time = start_time + timedelta(hours=SESSION_DURATION_HOURS)
    scan_count = 0
    trades_executed = 0
    
    print(f"⏰ Trading for {SESSION_DURATION_HOURS} hours")
    print(f"📊 Scan interval: {SCAN_INTERVAL} seconds")
    print(f"🎯 Session ends: {end_time.strftime('%H:%M:%S')}")
    
    while dt.now() < end_time:
        try:
            scan_count += 1
            current_time = dt.now()
            elapsed = current_time - start_time
            remaining = end_time - current_time
            
            print(f"\n{'='*60}")
            print(f"📊 Scan #{scan_count} | Elapsed: {elapsed.total_seconds()/60:.1f}m | Remaining: {remaining.total_seconds()/60:.1f}m")
            print(f"💰 Trades executed: {trades_executed}")
            
            # Analyze opportunities
            opportunities = analyze_opportunities(auth)
            
            if opportunities and trades_executed < 3:  # Limit to 3 trades for testing
                # Execute best opportunity
                best_opp = opportunities[0]
                current_balance = get_demo_balance(auth)
                
                result = execute_trade(auth, best_opp, current_balance)
                
                if result and "success" in result:
                    trades_executed += 1
                    print(f"🎉 Trade #{trades_executed} executed successfully!")
                else:
                    print(f"❌ Trade execution failed")
            else:
                print(f"📊 No new trades to execute")
            
            # Wait for next scan
            print(f"⏳ Waiting {SCAN_INTERVAL} seconds...")
            time.sleep(SCAN_INTERVAL)
            
        except KeyboardInterrupt:
            print(f"\n🛑 Manual shutdown")
            break
        except Exception as e:
            print(f"❌ Error in trading loop: {e}")
            time.sleep(30)
    
    # Final summary
    print(f"\n{'='*80}")
    print(f"🏁 TRADING SESSION COMPLETE")
    print(f"{'='*80}")
    print(f"📊 Total scans: {scan_count}")
    print(f"📈 Trades executed: {trades_executed}")
    print(f"💰 Final balance: ${get_demo_balance(auth)/100:.2f}")

if __name__ == "__main__":
    run_simple_crypto_trader()
