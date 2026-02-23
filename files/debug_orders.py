#!/usr/bin/env python3
"""
Debug order placement to see what's failing
"""

import os
import requests
import datetime
import base64
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

def test_order_placement():
    api_key_id = os.environ.get('KALSHI_API_KEY_ID')
    print(f'Testing order placement with API Key: {api_key_id}')

    # Load private key
    with open('kalshi-key.pem', 'rb') as f:
        private_key = serialization.load_pem_private_key(f.read(), password=None)

    # Test placing a small order
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
        'ticker': 'KXHIGHDEN-26FEB16-B65.5',  # Use a real ticker
        'side': 'yes',
        'action': 'buy',
        'count': 1,
        'type': 'limit',
        'yes_price': 1,  # 1 cent
        'client_order_id': str(uuid.uuid4()),
    }

    url = 'https://api.elections.kalshi.com' + path
    print(f'Placing order: {order_data}')
    
    resp = requests.post(url, headers=headers, json=order_data, timeout=15)
    
    print(f'Status Code: {resp.status_code}')
    print(f'Response: {resp.text}')
    
    if resp.status_code == 201:
        result = resp.json()
        print(f'✅ Order placed successfully!')
        print(f'Order ID: {result.get("order", {}).get("id", "N/A")}')
    else:
        print(f'❌ Order failed')
        try:
            error_data = resp.json()
            print(f'Error: {error_data}')
        except:
            print(f'Raw error: {resp.text}')

if __name__ == "__main__":
    test_order_placement()
