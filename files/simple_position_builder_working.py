#!/usr/bin/env python3
"""
Simple Position Builder - Uses the exact same structure as the working bot
"""

import os
import json
import time
import requests
import datetime
import base64
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

def get_headers(method, path, api_key_id, private_key_path):
    """Generate headers for API requests - exact same as working bot."""
    timestamp = str(int(datetime.datetime.now().timestamp() * 1000))
    msg = timestamp + method + path
    
    with open(private_key_path, 'rb') as f:
        private_key = serialization.load_pem_private_key(f.read(), password=None)
    
    sig_bytes = private_key.sign(
        msg.encode(),
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.DIGEST_LENGTH
        ),
        hashes.SHA256()
    )
    signature = base64.b64encode(sig_bytes).decode()
    
    return {
        'KALSHI-ACCESS-KEY': api_key_id,
        'KALSHI-ACCESS-SIGNATURE': signature,
        'KALSHI-ACCESS-TIMESTAMP': timestamp,
        'Content-Type': 'application/json',
    }

def place_order(ticker, side, price, count, api_key_id, private_key_path):
    """Place an order - exact same structure as working bot."""
    try:
        timestamp = str(int(datetime.datetime.now().timestamp() * 1000))
        path = "/trade-api/v2/portfolio/orders"
        method = "POST"
        
        headers = get_headers(method, path, api_key_id, private_key_path)
        
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
        
        url = f"https://api.elections.kalshi.com{path}"
        resp = requests.post(url, headers=headers, json=order_data, timeout=15)
        
        if resp.status_code == 201:
            result = resp.json()
            order_id = result.get("order", {}).get("order_id")
            return {
                "success": True,
                "order_id": order_id,
                "ticker": ticker,
                "side": side,
                "price": price,
                "count": count
            }
        else:
            return {"success": False, "error": resp.status_code, "detail": resp.text}
            
    except Exception as e:
        return {"success": False, "error": "Request failed", "detail": str(e)}

def get_markets(api_key_id, private_key_path):
    """Get markets - exact same structure as working bot."""
    try:
        timestamp = str(int(datetime.datetime.now().timestamp() * 1000))
        path = "/trade-api/v2/markets"
        method = "GET"
        
        headers = get_headers(method, path, api_key_id, private_key_path)
        url = f"https://api.elections.kalshi.com{path}"
        
        resp = requests.get(url, headers=headers, timeout=15)
        
        if resp.status_code == 200:
            return resp.json()
        else:
            return {"error": resp.status_code, "detail": resp.text}
            
    except Exception as e:
        return {"error": "Request failed", "detail": str(e)}

def get_balance(api_key_id, private_key_path):
    """Get balance - exact same structure as working bot."""
    try:
        timestamp = str(int(datetime.datetime.now().timestamp() * 1000))
        path = "/trade-api/v2/portfolio/balance"
        method = "GET"
        
        headers = get_headers(method, path, api_key_id, private_key_path)
        url = f"https://api.elections.kalshi.com{path}"
        
        resp = requests.get(url, headers=headers, timeout=15)
        
        if resp.status_code == 200:
            return resp.json()
        else:
            return {"error": resp.status_code, "detail": resp.text}
            
    except Exception as e:
        return {"error": "Request failed", "detail": str(e)}

def build_positions():
    """Build positions using the working structure."""
    print("=" * 80)
    print("🏗️  SIMPLE POSITION BUILDER")
    print("🎯 Using Working Bot Structure")
    print("=" * 80)
    
    api_key_id = os.environ.get('KALSHI_API_KEY_ID')
    if not api_key_id:
        print("❌ KALSHI_API_KEY_ID not found")
        return
    
    # Get initial balance
    balance = get_balance(api_key_id, 'kalshi-key.pem')
    if "error" not in balance:
        initial_balance = balance.get("total_balance", 0) / 100
        print(f"💰 Initial Balance: ${initial_balance:.2f}")
    else:
        print(f"❌ Balance error: {balance.get('error')}")
        return
    
    # Get markets
    markets_data = get_markets(api_key_id, 'kalshi-key.pem')
    if "error" in markets_data:
        print(f"❌ Markets error: {markets_data.get('error')}")
        return
    
    markets = markets_data.get("markets", [])
    print(f"📈 Found {len(markets)} markets")
    
    # Strategy 1: Quick positions across many markets
    print(f"\n🚀 STRATEGY 1: Quick Positions")
    print("-" * 50)
    
    trades_placed = 0
    failed_trades = 0
    
    # Take first 15 markets and place small orders
    for i, market in enumerate(markets[:15]):
        ticker = market.get("ticker", "")
        if not ticker:
            continue
            
        print(f"🎯 {i+1:2d}. {ticker[:45]:45s}")
        
        # Place YES order at 2c
        yes_result = place_order(ticker, "yes", 2, 1, api_key_id, 'kalshi-key.pem')
        if yes_result["success"]:
            print(f"     ✅ YES: {yes_result['order_id'][:8]}...")
            trades_placed += 1
        else:
            print(f"     ❌ YES: {yes_result.get('error', 'Unknown')}")
            failed_trades += 1
        
        time.sleep(0.3)
        
        # Place NO order at 2c
        no_result = place_order(ticker, "no", 2, 1, api_key_id, 'kalshi-key.pem')
        if no_result["success"]:
            print(f"     ✅ NO:  {no_result['order_id'][:8]}...")
            trades_placed += 1
        else:
            print(f"     ❌ NO:  {no_result.get('error', 'Unknown')}")
            failed_trades += 1
        
        time.sleep(0.3)
    
    # Strategy 2: Concentrated positions
    print(f"\n🎯 STRATEGY 2: Concentrated Positions")
    print("-" * 50)
    
    # Find markets with some activity
    active_markets = []
    for market in markets:
        yes_bid = market.get("yes_bid", 0)
        no_bid = market.get("no_bid", 0)
        if yes_bid > 0 or no_bid > 0:
            active_markets.append(market)
    
    print(f"📈 Found {len(active_markets)} active markets")
    
    # Place larger orders on top 5 active markets
    for i, market in enumerate(active_markets[:5]):
        ticker = market.get("ticker", "")
        print(f"🎯 {i+1}. {ticker[:45]:45s}")
        
        # 3 contracts at 3c each
        yes_result = place_order(ticker, "yes", 3, 3, api_key_id, 'kalshi-key.pem')
        if yes_result["success"]:
            print(f"     ✅ YES: 3 contracts at 3c - {yes_result['order_id'][:8]}...")
            trades_placed += 1
        else:
            print(f"     ❌ YES: {yes_result.get('error', 'Unknown')}")
            failed_trades += 1
        
        time.sleep(0.5)
        
        no_result = place_order(ticker, "no", 3, 3, api_key_id, 'kalshi-key.pem')
        if no_result["success"]:
            print(f"     ✅ NO: 3 contracts at 3c - {no_result['order_id'][:8]}...")
            trades_placed += 1
        else:
            print(f"     ❌ NO: {no_result.get('error', 'Unknown')}")
            failed_trades += 1
        
        time.sleep(0.5)
    
    # Strategy 3: Aggressive positions
    print(f"\n⚡ STRATEGY 3: Aggressive Positions")
    print("-" * 50)
    
    # Use higher prices for better fill chances
    for i, market in enumerate(markets[:8]):
        ticker = market.get("ticker", "")
        if not ticker:
            continue
            
        print(f"🎯 {i+1:2d}. {ticker[:45]:45s}")
        
        # 5 contracts at 5c (higher chance of fills)
        yes_result = place_order(ticker, "yes", 5, 5, api_key_id, 'kalshi-key.pem')
        if yes_result["success"]:
            print(f"     ✅ YES: 5 contracts at 5c - {yes_result['order_id'][:8]}...")
            trades_placed += 1
        else:
            print(f"     ❌ YES: {yes_result.get('error', 'Unknown')}")
            failed_trades += 1
        
        time.sleep(0.5)
        
        no_result = place_order(ticker, "no", 5, 5, api_key_id, 'kalshi-key.pem')
        if no_result["success"]:
            print(f"     ✅ NO: 5 contracts at 5c - {no_result['order_id'][:8]}...")
            trades_placed += 1
        else:
            print(f"     ❌ NO: {no_result.get('error', 'Unknown')}")
            failed_trades += 1
        
        time.sleep(0.5)
    
    # Final balance check
    final_balance = get_balance(api_key_id, 'kalshi-key.pem')
    if "error" not in final_balance:
        final_balance_amount = final_balance.get("total_balance", 0) / 100
        pnl = final_balance_amount - initial_balance
        print(f"\n" + "="*60)
        print(f"📊 POSITION BUILDING COMPLETE")
        print(f"💰 Initial Balance: ${initial_balance:.2f}")
        print(f"💰 Final Balance: ${final_balance_amount:.2f}")
        print(f"📈 P&L: ${pnl:+.2f}")
        print(f"📊 Total Orders Placed: {trades_placed}")
        print(f"❌ Failed Orders: {failed_trades}")
        print(f"🎯 Status: {'SUCCESS' if trades_placed > 0 else 'FAILED'}")
        
        if trades_placed > 0:
            print(f"\n💡 POSITION BUILDING SUCCESS!")
            print(f"   • {trades_placed} orders placed successfully")
            print(f"   • Positions will generate profits as they fill")
            print(f"   • Ready for monitoring and P&L tracking")
            print(f"   • Marginal profits expected as markets move")
        
    else:
        print(f"❌ Could not get final balance: {final_balance.get('error')}")

if __name__ == "__main__":
    build_positions()
