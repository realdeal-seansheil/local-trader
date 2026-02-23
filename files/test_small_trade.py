#!/usr/bin/env python3
"""
Test if we can place a small trade with available funds
"""

import os
import requests
import datetime
import base64
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

def test_small_trade():
    api_key_id = os.environ.get('KALSHI_API_KEY_ID')
    print(f'Testing small trade for API Key: {api_key_id}')

    # Load private key
    with open('kalshi-key.pem', 'rb') as f:
        private_key = serialization.load_pem_private_key(f.read(), password=None)

    # Get current opportunities first
    timestamp = str(int(datetime.datetime.now().timestamp() * 1000))
    path = '/trade-api/v2/markets?limit=5'
    method = 'GET'

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

    url = 'https://api.elections.kalshi.com' + path
    resp = requests.get(url, headers=headers, timeout=15)

    if resp.status_code == 200:
        data = resp.json()
        markets = data.get('markets', [])
        
        print(f'📊 Found {len(markets)} markets')
        
        if markets:
            # Try to place a small test order on the first market
            market = markets[0]
            ticker = market.get('ticker', 'Unknown')
            print(f'Trying small trade on: {ticker}')
            
            # Place a tiny order (1 contract at 1 cent)
            order_timestamp = str(int(datetime.datetime.now().timestamp() * 1000))
            order_path = '/trade-api/v2/portfolio/orders'
            order_method = 'POST'
            
            order_msg = order_timestamp + order_method + order_path
            
            order_sig_bytes = private_key.sign(
                order_msg.encode(),
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.DIGEST_LENGTH
                ),
                hashes.SHA256()
            )
            order_signature = base64.b64encode(order_sig_bytes).decode()
            
            order_headers = {
                'KALSHI-ACCESS-KEY': api_key_id,
                'KALSHI-ACCESS-SIGNATURE': order_signature,
                'KALSHI-ACCESS-TIMESTAMP': order_timestamp,
                'Content-Type': 'application/json',
            }
            
            import uuid
            order_data = {
                'ticker': ticker,
                'side': 'yes',
                'action': 'buy',
                'count': 1,
                'type': 'limit',
                'yes_price': 1,
                'client_order_id': str(uuid.uuid4()),
            }
            
            order_url = 'https://api.elections.kalshi.com' + order_path
            order_resp = requests.post(order_url, headers=order_headers, json=order_data, timeout=15)
            
            print(f'Order Status: {order_resp.status_code}')
            if order_resp.status_code == 201:
                print(f'✅ Small order placed successfully!')
                print(f'Order details: {order_resp.json()}')
            else:
                print(f'❌ Order failed: {order_resp.text}')
                
        else:
            print('No markets found')
            
    else:
        print(f'❌ Error getting markets: {resp.status_code} - {resp.text}')

if __name__ == "__main__":
    test_small_trade()
