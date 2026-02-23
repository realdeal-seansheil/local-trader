#!/usr/bin/env python3
"""
Debug order response to see exact API format
"""

import os
import requests
import datetime
import base64
import json
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

def debug_order_response():
    api_key_id = os.environ.get('KALSHI_API_KEY_ID')
    print(f'Debugging order response with API Key: {api_key_id}')

    # Load private key
    with open('kalshi-key.pem', 'rb') as f:
        private_key = serialization.load_pem_private_key(f.read(), password=None)

    # Place a test order to see response format
    timestamp = str(int(datetime.datetime.now().timestamp() * 1000))
    path = '/trade-api/v2/portfolio/orders'
    method = 'POST'

    msg = timestamp + method + path

    sig_bytes = private_key.sign(
        msg.encode(),
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.DIGEST_LENGTH
        ),
        hashes.SHA256()
    )
    signature = base64.b64encode(sig_bytes).decode()

    headers = {
        'KALSHI-ACCESS-KEY': api_key_id,
        'KALSHI-ACCESS-SIGNATURE': signature,
        'KALSHI-ACCESS-TIMESTAMP': timestamp,
        'Content-Type': 'application/json',
    }

    # Try to place a test order
    import uuid
    order_data = {
        'ticker': 'KXBTC-26FEB1710-B67625',  # Use a real ticker
        'side': 'yes',
        'action': 'buy',
        'count': 1,
        'type': 'limit',
        'yes_price': 1,  # 1 cent
        'client_order_id': str(uuid.uuid4()),
    }

    url = 'https://api.elections.kalshi.com' + path
    print(f'Placing test order: {order_data}')
    
    resp = requests.post(url, headers=headers, json=order_data, timeout=15)
    
    print(f'Status Code: {resp.status_code}')
    print(f'Response Headers: {dict(resp.headers)}')
    print(f'Response Text: {resp.text}')
    
    if resp.status_code == 201:
        result = resp.json()
        print(f'\n✅ Order placed successfully!')
        print(f'Full Response JSON:')
        print(json.dumps(result, indent=2))
        
        # Try different ways to extract order ID
        print(f'\n🔍 Testing order ID extraction:')
        
        # Method 1: result.get("order", {}).get("id")
        order_id_1 = result.get("order", {}).get("id")
        print(f'Method 1 - result.get("order", {{}}).get("id"): {order_id_1}')
        
        # Method 2: result.get("order_id")
        order_id_2 = result.get("order_id")
        print(f'Method 2 - result.get("order_id"): {order_id_2}')
        
        # Method 3: result.get("id")
        order_id_3 = result.get("id")
        print(f'Method 3 - result.get("id"): {order_id_3}')
        
        # Method 4: Look at all keys
        print(f'Method 4 - All keys in response: {list(result.keys())}')
        if "order" in result:
            print(f'Keys in "order": {list(result["order"].keys())}')
        
        # Method 5: Check if it's nested differently
        if "data" in result:
            print(f'Keys in "data": {list(result["data"].keys())}')
            
    else:
        print(f'❌ Order failed')
        try:
            error_data = resp.json()
            print(f'Error: {error_data}')
        except:
            print(f'Raw error: {resp.text}')

if __name__ == "__main__":
    debug_order_response()
