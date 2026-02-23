#!/usr/bin/env python3
"""
Test Public Endpoints
Tests if we can access Kalshi public endpoints without authentication.
"""

import requests

def test_public_endpoints():
    print("=" * 60)
    print("🌐 TESTING KALSHI PUBLIC ENDPOINTS")
    print("=" * 60)
    
    # Test both demo and live public endpoints
    endpoints = [
        ("Demo Markets", "https://demo-api.kalshi.co/trade-api/v2/markets?limit=1"),
        ("Live Markets", "https://api.elections.kalshi.com/trade-api/v2/markets?limit=1"),
        ("Demo Trades", "https://demo-api.kalshi.co/trade-api/v2/markets/trades?limit=1"),
        ("Live Trades", "https://api.elections.kalshi.com/trade-api/v2/markets/trades?limit=1")
    ]
    
    for name, url in endpoints:
        print(f"\n🔍 Testing {name}...")
        try:
            resp = requests.get(url, timeout=15)
            print(f"  Status Code: {resp.status_code}")
            
            if resp.status_code == 200:
                data = resp.json()
                if "markets" in data:
                    count = len(data.get("markets", []))
                    print(f"  ✅ {name} accessible - {count} markets returned")
                elif "trades" in data:
                    count = len(data.get("trades", []))
                    print(f"  ✅ {name} accessible - {count} trades returned")
                else:
                    print(f"  ✅ {name} accessible - data returned")
            else:
                print(f"  ❌ {name} failed: {resp.text[:100]}...")
                
        except Exception as e:
            print(f"  ❌ {name} error: {e}")
    
    print(f"\n" + "=" * 60)
    print("🔧 NEXT STEPS")
    print("=" * 60)
    
    print("If public endpoints work but authentication fails:")
    print("1. The API key ID and private key might not match")
    print("2. Generate a new API key pair from Kalshi")
    print("3. Ensure you're using the correct environment (demo vs live)")
    print("4. Check if the API key has proper permissions")

if __name__ == "__main__":
    test_public_endpoints()
