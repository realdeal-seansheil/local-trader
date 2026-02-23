#!/usr/bin/env python3
"""
API Diagnostic Tool
Tests Kalshi API connection and authentication.
"""

import os
import requests
import base64
import datetime
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

def test_api_authentication():
    print("=" * 60)
    print("🔑 KALSHI API AUTHENTICATION DIAGNOSTIC")
    print("=" * 60)
    
    # Load configuration
    api_key_id = os.environ.get("KALSHI_API_KEY_ID")
    private_key_path = "kalshi-key.pem"
    
    print(f"API Key ID: {api_key_id}")
    print(f"Private Key Path: {private_key_path}")
    
    if not api_key_id:
        print("❌ API Key ID not found in environment")
        return False
    
    # Load private key
    try:
        with open(private_key_path, "rb") as f:
            private_key = serialization.load_pem_private_key(
                f.read(), password=None
            )
        print("✅ Private key loaded successfully")
    except Exception as e:
        print(f"❌ Failed to load private key: {e}")
        return False
    
    # Test both demo and live endpoints
    endpoints = [
        ("Demo", "https://demo-api.kalshi.co/trade-api/v2"),
        ("Live", "https://api.elections.kalshi.com/trade-api/v2")
    ]
    
    for name, base_url in endpoints:
        print(f"\n🔍 Testing {name} API...")
        
        # Test authentication
        path = "/portfolio/balance"
        timestamp = str(int(datetime.datetime.now().timestamp() * 1000))
        msg = timestamp + "GET" + path
        
        try:
            # Generate signature
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
            
            # Make request
            url = base_url + path
            print(f"  Requesting: {url}")
            
            resp = requests.get(url, headers=headers, timeout=15)
            
            print(f"  Status Code: {resp.status_code}")
            
            if resp.status_code == 200:
                data = resp.json()
                available = data.get("available", 0)
                print(f"  ✅ {name} API authentication successful!")
                print(f"  💰 Available balance: ${available:.2f}")
                return True
            else:
                print(f"  ❌ {name} API authentication failed")
                print(f"  Response: {resp.text[:200]}...")
                
        except Exception as e:
            print(f"  ❌ {name} API request failed: {e}")
    
    print(f"\n" + "=" * 60)
    print("🔧 TROUBLESHOOTING STEPS")
    print("=" * 60)
    
    print("1. Check API Key ID format:")
    print(f"   • Should be UUID format: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx")
    print(f"   • Your key: {api_key_id}")
    
    print("\n2. Verify API Key permissions:")
    print("   • Log into Kalshi account")
    print("   • Go to Account → API Keys")
    print("   • Ensure key is 'Active'")
    print("   • Check key has 'Trading' permissions")
    
    print("\n3. Check private key format:")
    print("   • Should start with '-----BEGIN RSA PRIVATE KEY-----'")
    print("   • Should end with '-----END RSA PRIVATE KEY-----'")
    print("   • No extra spaces or characters")
    
    print("\n4. Common issues:")
    print("   • API key expired or revoked")
    print("   • Wrong environment (demo vs live)")
    print("   • IP restrictions on API key")
    print("   • Rate limiting")
    
    print("\n5. Next steps:")
    print("   • Generate new API key pair if needed")
    print("   • Contact Kalshi support if issues persist")
    print("   • Try with a different account")
    
    return False

def show_key_info():
    """Show current key information."""
    print(f"\n📋 CURRENT KEY INFORMATION:")
    print(f"API Key ID: {os.environ.get('KALSHI_API_KEY_ID', 'Not set')}")
    
    try:
        with open("kalshi-key.pem", "r") as f:
            key_content = f.read()
            
        print(f"Private Key:")
        print(f"  • File exists: ✅")
        print(f"  • Size: {len(key_content)} characters")
        print(f"  • Starts with RSA key: {'✅' if '-----BEGIN RSA PRIVATE KEY-----' in key_content else '❌'}")
        print(f"  • Ends with RSA key: {'✅' if '-----END RSA PRIVATE KEY-----' in key_content else '❌'}")
        
    except Exception as e:
        print(f"Private Key: ❌ {e}")

if __name__ == "__main__":
    show_key_info()
    test_api_authentication()
