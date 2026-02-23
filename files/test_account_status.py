#!/usr/bin/env python3
"""
Test Account Status
Check if there are account-specific issues.
"""

import os
import requests
import datetime
import base64
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

def test_account_status():
    print("=" * 60)
    print("🔍 TESTING ACCOUNT STATUS")
    print("=" * 60)
    
    api_key_id = os.environ.get("KALSHI_API_KEY_ID")
    print(f"API Key ID: {api_key_id}")
    
    # Load private key
    try:
        with open("kalshi-key.pem", "rb") as f:
            private_key = serialization.load_pem_private_key(f.read(), password=None)
        print("✅ Private key loaded successfully")
    except Exception as e:
        print(f"❌ Private key error: {e}")
        return
    
    # Test different endpoints that might work
    endpoints = [
        ("Portfolio Balance", "/portfolio/balance"),
        ("Positions", "/portfolio/positions"),
        ("User Info", "/user"),
        ("Account Info", "/account"),
        ("Markets", "/markets?limit=1")  # This one works without auth
    ]
    
    for name, path in endpoints:
        print(f"\n🔍 Testing {name} endpoint...")
        
        # Skip markets as it doesn't need auth
        if path == "/markets?limit=1":
            try:
                url = "https://api.elections.kalshi.com/trade-api/v2" + path
                resp = requests.get(url, timeout=15)
                print(f"  Status: {resp.status_code}")
                if resp.status_code == 200:
                    print(f"  ✅ {name} works without auth")
                else:
                    print(f"  ❌ {name} failed: {resp.text[:100]}...")
            except Exception as e:
                print(f"  ❌ {name} error: {e}")
            continue
        
        # Try authenticated endpoints
        try:
            timestamp = str(int(datetime.datetime.now().timestamp() * 1000))
            msg = timestamp + "GET" + path
            
            sig_bytes = private_key.sign(
                msg.encode(),
                padding.PKCS1v15(),
                hashes.SHA256()
            )
            signature = base64.b64encode(sig_bytes).decode()
            
            headers = {
                "KALSHI-ACCESS-KEY": api_key_id,
                "KALSHI-ACCESS-SIGNATURE": signature,
                "KALSHI-ACCESS-TIMESTAMP": timestamp,
                "Content-Type": "application/json",
            }
            
            url = "https://api.elections.kalshi.com/trade-api/v2" + path
            resp = requests.get(url, headers=headers, timeout=15)
            
            print(f"  Status: {resp.status_code}")
            
            if resp.status_code == 200:
                data = resp.json()
                if name == "Portfolio Balance":
                    balance = data.get("available", 0)
                    print(f"  ✅ SUCCESS! Balance: ${balance:.2f}")
                elif name == "Positions":
                    positions = data.get("positions", [])
                    print(f"  ✅ SUCCESS! {len(positions)} positions")
                else:
                    print(f"  ✅ SUCCESS! {name} accessible")
                return True
            else:
                error_data = resp.json()
                error_code = error_data.get("error", {}).get("code", "unknown")
                error_msg = error_data.get("error", {}).get("message", "unknown")
                error_details = error_data.get("error", {}).get("details", "unknown")
                
                print(f"  ❌ {name} failed:")
                print(f"     Code: {error_code}")
                print(f"     Message: {error_msg}")
                print(f"     Details: {error_details}")
                
                # Check for specific error patterns
                if "INCORRECT_API_KEY_SIGNATURE" in error_details:
                    print(f"     🔑 This suggests key mismatch")
                elif "NOT_FOUND" in error_details:
                    print(f"     🔑 This suggests wrong environment")
                elif "PERMISSION_DENIED" in error_details:
                    print(f"     🔑 This suggests permission issues")
                
        except Exception as e:
            print(f"  ❌ {name} error: {e}")
    
    print(f"\n" + "=" * 60)
    print("🔧 NEXT STEPS")
    print("=" * 60)
    
    print("If authenticated endpoints all fail:")
    print("1. Check if API key is for the correct environment (live vs demo)")
    print("2. Verify API key has trading permissions")
    print("3. Check if account is fully verified")
    print("4. Contact Kalshi support with the specific error codes")
    print("5. Try generating a new API key pair")

if __name__ == "__main__":
    test_account_status()
