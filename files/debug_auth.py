#!/usr/bin/env python3
"""
Debug Authentication Process
Show exactly what's being signed and how.
"""

import os
import datetime
import base64
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

def debug_authentication():
    print("=" * 60)
    print("🔍 DEBUGGING AUTHENTICATION PROCESS")
    print("=" * 60)
    
    api_key_id = os.environ.get("KALSHI_API_KEY_ID")
    print(f"API Key ID: {api_key_id}")
    
    # Load private key
    with open("kalshi-key.pem", "rb") as f:
        private_key = serialization.load_pem_private_key(f.read(), password=None)
    
    # Test the exact same process as get_headers
    timestamp = str(int(datetime.datetime.now().timestamp() * 1000))
    path = "/trade-api/v2/portfolio/balance"
    path_without_query = path.split("?")[0]
    method = "GET"
    
    msg = timestamp + method.upper() + path_without_query
    
    print(f"\n Message to sign:")
    print(f"  Timestamp: {timestamp}")
    print(f"  Method: {method.upper()}")
    print(f"  Path: {path_without_query}")
    print(f"  Full message: '{msg}'")
    print(f"  Message length: {len(msg)} characters")
    
    # Generate signature
    headers = standard_signature(api_key_id, private_key)
    signature = headers["KALSHI-ACCESS-SIGNATURE"]
    sig_bytes = base64.b64decode(signature)
    
    print(f"\n🔐 Signature generated:")
    print(f"  Raw bytes length: {len(sig_bytes)}")
    print(f"  Base64 signature: {signature[:50]}...")
    print(f"  Base64 length: {len(signature)}")
    
    print(f"\n📋 Headers:")
    for key, value in headers.items():
        if key == "KALSHI-ACCESS-SIGNATURE":
            print(f"  {key}: {value[:30]}...")
        else:
            print(f"  {key}: {value}")
    
    # Test request
    import requests
    url = "https://api.elections.kalshi.com/trade-api/v2/portfolio/balance"
    
    print(f"\n🌐 Making request to:")
    print(f"  URL: {url}")
    
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        print(f"  Status Code: {resp.status_code}")
        print(f"  Response: {resp.text[:200]}...")
        
        if resp.status_code == 200:
            print(f"  ✅ SUCCESS!")
            data = resp.json()
            balance = data.get("available", 0)
            print(f"  💰 Balance: ${balance:.2f}")
        else:
            print(f"  ❌ FAILED")
            
    except Exception as e:
        print(f"  ❌ Request error: {e}")
    
    print(f"\n" + "=" * 60)
    print("🔧 TROUBLESHOOTING NOTES")
    print("=" * 60)
    
    print("If this fails, check:")
    print("1. API Key ID matches the private key")
    print("2. Private key is in correct format")
    print("3. API key has trading permissions")
    print("4. Account is in good standing")
    print("5. No geographic restrictions")

if __name__ == "__main__":
    debug_authentication()
