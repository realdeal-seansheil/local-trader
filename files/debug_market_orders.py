#!/usr/bin/env python3
"""
Debug Market Orders - Why are they failing with 400?
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

def debug_market_orders():
    print("=" * 80)
    print("🔍 DEBUGGING MARKET ORDERS")
    print("🎯 Why Are Market Orders Failing with 400?")
    print("=" * 80)
    
    auth = KalshiAuth(KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH)
    client = KalshiClient(auth)
    
    print(f"\n📊 STEP 1: Test a Single Market Order")
    print("-" * 50)
    
    # Get a market
    markets = client.get_markets()
    all_markets = markets.get("markets", [])
    test_market = None
    for market in all_markets:
        if market.get("status") == "active":
            test_market = market
            break
    
    if not test_market:
        print(f"❌ No active markets found")
        return
    
    ticker = test_market.get("ticker")
    print(f"🎯 Testing market order on: {ticker}")
    
    # Check market data first
    print(f"📊 Market Data:")
    print(f"   YES Bid: {test_market.get('yes_bid', 'N/A')}")
    print(f"   YES Ask: {test_market.get('yes_ask', 'N/A')}")
    print(f"   NO Bid: {test_market.get('no_bid', 'N/A')}")
    print(f"   NO Ask: {test_market.get('no_ask', 'N/A')}")
    print(f"   Status: {test_market.get('status', 'N/A')}")
    
    # Test market order
    try:
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
            "type": "market",
            "client_order_id": str(uuid.uuid4()),
        }
        
        print(f"📊 Order Data: {json.dumps(order_data, indent=2)}")
        
        url = "https://api.elections.kalshi.com" + path
        resp = requests.post(url, headers=headers, json=order_data, timeout=15)
        
        print(f"📊 Market Order Status: {resp.status_code}")
        print(f"📊 Response: {resp.text}")
        
        if resp.status_code == 201:
            result = resp.json()
            order_id = result.get("order", {}).get("order_id")
            print(f"✅ Market order placed: {order_id}")
            
            # Verify the order
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
                verify_result = verify_resp.json()
                order_data = verify_result.get("order", {})
                print(f"✅ Market order verified:")
                print(f"   📈 Status: {order_data.get('status', 'Unknown')}")
                print(f"   💰 Fill Count: {order_data.get('fill_count', 0)}")
                yes_price = order_data.get('yes_price_dollars')
                no_price = order_data.get('no_price_dollars')
                print(f"   🎯 Price: {yes_price if yes_price else 'N/A'}")
                
                if order_data.get('status') == 'filled':
                    print(f"🎉 MARKET ORDER FILLED IMMEDIATELY!")
                else:
                    print(f"⏳ Market order placed, waiting for execution")
                    
            elif verify_resp.status_code == 404:
                print(f"❌ Market order NOT FOUND")
            else:
                print(f"❌ Verification error: {verify_resp.status_code}")
                print(f"📊 Response: {verify_resp.text}")
                
        elif resp.status_code == 400:
            print(f"❌ Market order failed with 400")
            print(f"📊 Error details: {resp.text}")
            
            # Try to understand the error
            try:
                error_data = resp.json()
                print(f"📊 Error Data: {json.dumps(error_data, indent=2)}")
                
                # Check if it's a validation error
                if "error" in error_data:
                    error_code = error_data.get("error", {}).get("code", "unknown")
                    error_message = error_data.get("error", {}).get("message", "unknown")
                    print(f"🔍 Error Code: {error_code}")
                    print(f"🔍 Error Message: {error_message}")
                    
                    if error_code == "invalid_order":
                        print(f"🔍 Invalid order - check order data")
                    elif error_code == "market_not_available":
                        print(f"🔍 Market not available for this ticker")
                    elif error_code == "insufficient_balance":
                        print(f"🔍 Insufficient balance")
                    elif error_code == "market_closed":
                        print(f"🔍 Market is closed")
                        
            except:
                print(f"🔍 Could not parse error response")
                
        else:
            print(f"❌ Unexpected status: {resp.status_code}")
            print(f"📊 Response: {resp.text}")
            
    except Exception as e:
        print(f"❌ Exception: {e}")
        import traceback
        traceback.print_exc()
    
    print(f"\n💡 DEBUG CONCLUSION:")
    print(f"📊 If market orders work:")
    print(f"   • We'll get immediate fills")
    print(f"   • No more resting orders")
    print(f"   • Higher fill rates")
    print(f"   • Immediate position building")
    print(f"📊 If market orders fail:")
    print(f"   • Need to understand the 400 error")
    print(f"   • May need to use limit orders with better pricing")
    print(f"   • Market conditions may not support market orders")

if __name__ == "__main__":
    debug_market_orders()
