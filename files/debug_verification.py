#!/usr/bin/env python3
"""
Debug the verification issue - why does it say verified but then 404?
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

def debug_verification_issue():
    print("=" * 80)
    print("🔍 DEBUGGING VERIFICATION ISSUE")
    print("🎯 Why Does Verification Say Success But Then 404?")
    print("=" * 80)
    
    auth = KalshiAuth(KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH)
    client = KalshiClient(auth)
    
    print(f"\n📊 STEP 1: Place Order Again")
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
    print(f"🎯 Testing on: {ticker}")
    
    # Place order
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
            print(f"✅ Order placed: {order_id}")
            print(f"📊 Full response: {json.dumps(result, indent=2)}")
            
            # Immediate verification
            print(f"\n📊 STEP 2: Immediate Verification")
            print("-" * 50)
            
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
            print(f"📊 Verification Response: {verify_resp.text}")
            
            if verify_resp.status_code == 200:
                print(f"✅ Order VERIFIED to exist in exchange")
                verify_result = verify_resp.json()
                print(f"📊 Order details: {json.dumps(verify_result, indent=2)}")
                
                # Check positions
                print(f"\n📊 STEP 3: Check Positions")
                print("-" * 50)
                
                positions = client.get_positions()
                all_positions = positions.get("positions", [])
                print(f"📊 Total positions: {len(all_positions)}")
                
                # Look for our order
                matching_positions = [p for p in all_positions if p.get("ticker") == ticker]
                print(f"📊 Positions for {ticker}: {len(matching_positions)}")
                
                if matching_positions:
                    for pos in matching_positions:
                        print(f"   📈 {pos.get('side', 'Unknown')} - {pos.get('status', 'Unknown')} - {pos.get('count', 0)}")
                else:
                    print(f"❌ No positions found for {ticker}")
                
                # Wait a bit and check again
                print(f"\n📊 STEP 4: Wait and Check Again")
                print("-" * 50)
                
                import time
                time.sleep(2)
                
                verify_resp2 = requests.get(verify_url, headers=verify_headers, timeout=15)
                print(f"📊 Verification Status (after wait): {verify_resp2.status_code}")
                
                if verify_resp2.status_code == 200:
                    print(f"✅ Order still exists")
                else:
                    print(f"❌ Order no longer exists: {verify_resp2.status_code}")
                    print(f"📊 Response: {verify_resp2.text}")
                
            elif verify_resp.status_code == 404:
                print(f"❌ Order NOT FOUND in exchange")
                print(f"🔍 This explains why no positions in account")
            else:
                print(f"❌ Verification error: {verify_resp.status_code}")
                print(f"📊 Response: {verify_resp.text}")
                
        else:
            print(f"❌ Order placement failed: {resp.status_code}")
            print(f"📊 Response: {resp.text}")
            
    except Exception as e:
        print(f"❌ Exception: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    debug_verification_issue()
