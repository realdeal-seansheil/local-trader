#!/usr/bin/env python3
"""
Debug Authentication Issue - Find what changed
"""

import os
import json
import requests
import base64
from datetime import datetime as dt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from kalshi_executor import KalshiAuth, KalshiClient, StrategyExecutor
from kalshi_executor import KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH

def debug_authentication():
    print("=" * 80)
    print("🔍 DEBUGGING AUTHENTICATION ISSUE")
    print("🎯 Find What Changed Since Working Bot")
    print("=" * 80)
    
    # Initialize authentication
    auth = KalshiAuth(KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH)
    client = KalshiClient(auth)
    
    print(f"\n📊 STEP 1: Test Basic Authentication")
    print("-" * 50)
    
    # Test basic balance endpoint
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
        
        url = "https://api.elections.kalshi.com" + path
        resp = requests.get(url, headers=headers, timeout=15)
        
        print(f"📊 Balance API Status: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            balance = data.get("balance", 0)
            available = data.get("available", 0)
            print(f"✅ Balance: ${balance/100:.2f}")
            print(f"✅ Available: ${available/100:.2f}")
            print(f"✅ Basic authentication: WORKING")
        else:
            print(f"❌ Balance API failed: {resp.status_code}")
            print(f"📊 Response: {resp.text}")
            return False
            
    except Exception as e:
        print(f"❌ Balance exception: {e}")
        return False
    
    print(f"\n📊 STEP 2: Test Markets Endpoint")
    print("-" * 50)
    
    # Test markets endpoint
    try:
        markets = client.get_markets()
        if "error" in markets:
            print(f"❌ Markets API failed: {markets.get('error')}")
            return False
        else:
            all_markets = markets.get("markets", [])
            print(f"✅ Markets API: WORKING")
            print(f"✅ Found {len(all_markets)} markets")
            
            # Check market status
            active_count = 0
            for market in all_markets[:10]:
                if market.get("status") == "active":
                    active_count += 1
            
            print(f"✅ Active markets: {active_count}/10 checked")
    
    except Exception as e:
        print(f"❌ Markets exception: {e}")
        return False
    
    print(f"\n📊 STEP 3: Test Order Placement")
    print("-" * 50)
    
    # Test order placement with a real market
    try:
        markets = client.get_markets()
        all_markets = markets.get("markets", [])
        
        # Find an active market
        test_market = None
        for market in all_markets:
            if market.get("status") == "active":
                test_market = market
                break
        
        if not test_market:
            print(f"❌ No active markets found")
            return False
        
        ticker = test_market.get("ticker")
        print(f"🎯 Testing order placement on: {ticker}")
        
        # Use the exact same method as working bot
        timestamp = str(int(dt.now().timestamp() * 1000))
        path = "/trade-api/v2/portfolio/orders"
        method = "POST"
        
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
        
        import uuid
        order_data = {
            "ticker": ticker,
            "side": "yes",
            "action": "buy",
            "count": 1,
            "type": "limit",
            "yes_price": 1,
            "client_order_id": str(uuid.uuid4()),
        }
        
        url = "https://api.elections.kalshi.com" + path
        resp = requests.post(url, headers=headers, json=order_data, timeout=15)
        
        print(f"📊 Order API Status: {resp.status_code}")
        
        if resp.status_code == 201:
            result = resp.json()
            order_id = result.get("order", {}).get("order_id")
            print(f"✅ Order placed: {order_id[:8] if order_id else 'N/A'}...")
            
            # Now verify the order exists
            print(f"🔍 Verifying order exists...")
            
            verify_timestamp = str(int(dt.now().timestamp() * 1000))
            verify_path = f"/trade-api/v2/portfolio/orders/{order_id}"
            verify_method = "GET"
            
            verify_msg = verify_timestamp + verify_method + verify_path
            
            verify_sig_bytes = auth.private_key.sign(
                verify_msg.encode(),
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.DIGEST_LENGTH
                ),
                hashes.SHA256()
            )
            verify_signature = base64.b64encode(verify_sig_bytes).decode()
            
            verify_headers = {
                "KALSHI-ACCESS-KEY": auth.api_key_id,
                "KALSHI-ACCESS-SIGNATURE": verify_signature,
                "KALSHI-ACCESS-TIMESTAMP": verify_timestamp,
                "Content-Type": "application/json",
            }
            
            verify_url = "https://api.elections.kalshi.com" + verify_path
            verify_resp = requests.get(verify_url, headers=verify_headers, timeout=15)
            
            print(f"📊 Verification Status: {verify_resp.status_code}")
            
            if verify_resp.status_code == 200:
                print(f"✅ Order VERIFIED to exist in exchange")
                return True
            elif verify_resp.status_code == 404:
                print(f"❌ Order NOT FOUND in exchange")
                print(f"🔍 This is the core issue!")
                print(f"📊 Order placement returns 201 but order doesn't exist")
                return False
            else:
                print(f"❌ Verification error: {verify_resp.status_code}")
                print(f"📊 Response: {verify_resp.text}")
                return False
                
        else:
            print(f"❌ Order placement failed: {resp.status_code}")
            print(f"📊 Response: {resp.text}")
            return False
            
    except Exception as e:
        print(f"❌ Order placement exception: {e}")
        return False
    
    print(f"\n📊 STEP 4: Check Account Status")
    print("-" * 50)
    
    # Check if there are any restrictions
    try:
        positions = client.get_positions()
        all_positions = positions.get("positions", [])
        print(f"📊 Current positions: {len(all_positions)}")
        
        trades = client.get_trades()
        all_trades = trades.get("trades", [])
        print(f"📊 Recent trades: {len(all_trades)}")
        
        if all_trades:
            latest_trade = all_trades[0]
            trade_time = latest_trade.get("executed_time", "Unknown")
            print(f"📊 Latest trade: {trade_time}")
        
    except Exception as e:
        print(f"❌ Account status check failed: {e}")
    
    print(f"\n💡 DEBUG CONCLUSION:")
    print(f"📊 If order placement returns 201 but verification returns 404:")
    print(f"   • API accepts request but doesn't create order")
    print(f"   • Exchange validation is failing silently")
    print(f"   • This explains why no positions appear in account")
    print(f"   • Need to investigate exchange-side validation")

if __name__ == "__main__":
    debug_authentication()
