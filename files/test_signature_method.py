#!/usr/bin/env python3
"""
Test Different Signature Methods
Try different approaches to Kalshi API authentication.
"""

import os
import time
import requests
import base64
import datetime
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

def test_different_signature_methods():
    print("=" * 60)
    print("🔐 TESTING DIFFERENT SIGNATURE METHODS")
    print("=" * 60)
    
    api_key_id = os.environ.get("KALSHI_API_KEY_ID")
    
    # Load private key
    with open("kalshi-key.pem", "rb") as f:
        private_key = serialization.load_pem_private_key(f.read(), password=None)
    
    # Test different signature approaches
    methods = [
        ("Standard Method", standard_signature),
        ("Unix Timestamp Method", unix_timestamp_signature),
        ("No Timestamp Method", no_timestamp_signature),
        ("Lowercase Method", lowercase_signature)
    ]
    
    for name, method_func in methods:
        print(f"\n🔍 Testing {name}...")
        
        try:
            headers = method_func(api_key_id, private_key)
            
            # Test with demo API
            url = "https://demo-api.kalshi.co/trade-api/v2/portfolio/balance"
            resp = requests.get(url, headers=headers, timeout=15)
            
            print(f"  Status: {resp.status_code}")
            
            if resp.status_code == 200:
                data = resp.json()
                balance = data.get("available", 0)
                print(f"  ✅ SUCCESS! Balance: ${balance:.2f}")
                return True
            else:
                print(f"  ❌ Failed: {resp.text[:100]}...")
                
        except Exception as e:
            print(f"  ❌ Error: {e}")
    
    return False

def standard_signature(api_key_id, private_key):
    """Standard signature method."""
    timestamp = str(int(datetime.datetime.now().timestamp() * 1000))
    path = "/portfolio/balance"
    msg = timestamp + "GET" + path
    
    sig_bytes = private_key.sign(
        msg.encode(),
        padding.PKCS1v15(),
        hashes.SHA256()
    )
    signature = base64.b64encode(sig_bytes).decode()
    
    return {
        "KALSHI-ACCESS-KEY": api_key_id,
        "KALSHI-ACCESS-SIGNATURE": signature,
        "KALSHI-ACCESS-TIMESTAMP": timestamp,
        "Content-Type": "application/json",
    }

def unix_timestamp_signature(api_key_id, private_key):
    """Unix timestamp in seconds instead of milliseconds."""
    timestamp = str(int(time.time()))
    path = "/portfolio/balance"
    msg = timestamp + "GET" + path
    
    sig_bytes = private_key.sign(
        msg.encode(),
        padding.PKCS1v15(),
        hashes.SHA256()
    )
    signature = base64.b64encode(sig_bytes).decode()
    
    return {
        "KALSHI-ACCESS-KEY": api_key_id,
        "KALSHI-ACCESS-SIGNATURE": signature,
        "KALSHI-ACCESS-TIMESTAMP": timestamp,
        "Content-Type": "application/json",
    }

def no_timestamp_signature(api_key_id, private_key):
    """Try without timestamp (some APIs don't require it)."""
    path = "/portfolio/balance"
    msg = "GET" + path
    
    sig_bytes = private_key.sign(
        msg.encode(),
        padding.PKCS1v15(),
        hashes.SHA256()
    )
    signature = base64.b64encode(sig_bytes).decode()
    
    return {
        "KALSHI-ACCESS-KEY": api_key_id,
        "KALSHI-ACCESS-SIGNATURE": signature,
        "Content-Type": "application/json",
    }

def lowercase_signature(api_key_id, private_key):
    """Try with lowercase method."""
    timestamp = str(int(datetime.datetime.now().timestamp() * 1000))
    path = "/portfolio/balance"
    msg = timestamp + "get" + path.lower()
    
    sig_bytes = private_key.sign(
        msg.encode(),
        padding.PKCS1v15(),
        hashes.SHA256()
    )
    signature = base64.b64encode(sig_bytes).decode()
    
    return {
        "KALSHI-ACCESS-KEY": api_key_id,
        "KALSHI-ACCESS-SIGNATURE": signature,
        "KALSHI-ACCESS-TIMESTAMP": timestamp,
        "Content-Type": "application/json",
    }

if __name__ == "__main__":
    test_different_signature_methods()
