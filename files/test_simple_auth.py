#!/usr/bin/env python3
"""
Test Simple Authentication
Try different approaches to fix the authentication.
"""

import os
import requests
import datetime
import base64
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

def test_simple_auth():
    print("=" * 60)
    print("🔧 TESTING SIMPLE AUTHENTICATION")
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
    
    # Test 1: Try different timestamp formats
    timestamp_formats = [
        str(int(datetime.datetime.now().timestamp() * 1000)),  # milliseconds
        str(int(datetime.datetime.now().timestamp())),         # seconds
        datetime.datetime.now().strftime("%Y%m%d%H%M%S"),       # YYYYMMDDHHMMSS
    ]
    
    for i, ts in enumerate(timestamp_formats):
        print(f"\n🔍 Test {i+1}: Timestamp format '{ts}'")
        
        path = "/portfolio/balance"
        method = "GET"
        msg = ts + method.upper() + path
        
        try:
            sig_bytes = private_key.sign(
                msg.encode(),
                padding.PKCS1v15(),
                hashes.SHA256()
            )
            signature = base64.b64encode(sig_bytes).decode()
            
            headers = {
                "KALSHI-ACCESS-KEY": api_key_id,
                "KALSHI-ACCESS-SIGNATURE": signature,
                "KALSHI-ACCESS-TIMESTAMP": ts,
                "Content-Type": "application/json",
            }
            
            url = "https://api.elections.kalshi.com/trade-api/v2" + path
            resp = requests.get(url, headers=headers, timeout=15)
            
            print(f"  Status: {resp.status_code}")
            if resp.status_code == 200:
                print(f"  ✅ SUCCESS! Balance: ${resp.json().get('available', 0):.2f}")
                return True
            else:
                print(f"  ❌ Failed: {resp.text[:100]}...")
                
        except Exception as e:
            print(f"  ❌ Error: {e}")
    
    # Test 2: Try without timestamp
    print(f"\n🔍 Test 4: No timestamp")
    try:
        path = "/portfolio/balance"
        method = "GET"
        msg = method.upper() + path
        
        sig_bytes = private_key.sign(
            msg.encode(),
            padding.PKCS1v15(),
            hashes.SHA256()
        )
        signature = base64.b64encode(sig_bytes).decode()
        
        headers = {
            "KALSHI-ACCESS-KEY": api_key_id,
            "KALSHI-ACCESS-SIGNATURE": signature,
            "Content-Type": "application/json",
        }
        
        url = "https://api.elections.kalshi.com/trade-api/v2" + path
        resp = requests.get(url, headers=headers, timeout=15)
        
        print(f"  Status: {resp.status_code}")
        if resp.status_code == 200:
            print(f"  ✅ SUCCESS! Balance: ${resp.json().get('available', 0):.2f}")
            return True
        else:
            print(f"  ❌ Failed: {resp.text[:100]}...")
            
    except Exception as e:
        print(f"  ❌ Error: {e}")
    
    # Test 3: Try demo API
    print(f"\n🔍 Test 5: Demo API")
    try:
        timestamp = str(int(datetime.datetime.now().timestamp() * 1000))
        path = "/portfolio/balance"
        method = "GET"
        msg = timestamp + method.upper() + path
        
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
        
        url = "https://demo-api.kalshi.co/trade-api/v2" + path
        resp = requests.get(url, headers=headers, timeout=15)
        
        print(f"  Status: {resp.status_code}")
        if resp.status_code == 200:
            print(f"  ✅ SUCCESS! Demo balance: ${resp.json().get('available', 0):.2f}")
            print(f"  💡 Your key works with DEMO API!")
            return True
        else:
            print(f"  ❌ Demo failed: {resp.text[:100]}...")
            
    except Exception as e:
        print(f"  ❌ Demo error: {e}")
    
    print(f"\n💡 If all tests failed, the issue might be:")
    print(f"  1. API key permissions")
    print(f"  2. Account status")
    print(f"  3. Geographic restrictions")
    print(f"  4. API key format requirements")

if __name__ == "__main__":
    test_simple_auth()
