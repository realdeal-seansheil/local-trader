#!/usr/bin/env python3
"""
Check recent orders to see if funds are tied up
"""

import os
import requests
import datetime
import base64
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

def check_orders():
    api_key_id = os.environ.get('KALSHI_API_KEY_ID')
    print(f'Checking orders for API Key: {api_key_id}')

    # Load private key
    with open('kalshi-key.pem', 'rb') as f:
        private_key = serialization.load_pem_private_key(f.read(), password=None)

    # Use current timestamp
    timestamp = str(int(datetime.datetime.now().timestamp() * 1000))
    path = '/trade-api/v2/portfolio/orders'
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
        orders = data.get('orders', [])
        
        print(f'📊 Recent Orders: {len(orders)}')
        
        if orders:
            for order in orders[:10]:  # Show last 10 orders
                ticker = order.get('ticker', 'Unknown')
                side = order.get('side', 'Unknown')
                action = order.get('action', 'Unknown')
                count = order.get('count', 0)
                price = order.get('price', 0)
                status = order.get('status', 'Unknown')
                created = order.get('created_time', 'Unknown')
                
                print(f'  • {ticker}: {action} {side} {count} @ ${price/100:.2f} - {status}')
                print(f'    Created: {created}')
        else:
            print('  No orders found')
            
        return data
    else:
        print(f'❌ Error: {resp.status_code} - {resp.text}')
        return None

if __name__ == "__main__":
    check_orders()
