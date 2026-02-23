#!/usr/bin/env python3
"""
Check current positions to see where funds are tied up
"""

import os
import requests
import datetime
import base64
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

def check_positions():
    api_key_id = os.environ.get('KALSHI_API_KEY_ID')
    print(f'Checking positions for API Key: {api_key_id}')

    # Load private key
    with open('kalshi-key.pem', 'rb') as f:
        private_key = serialization.load_pem_private_key(f.read(), password=None)

    # Use current timestamp
    timestamp = str(int(datetime.datetime.now().timestamp() * 1000))
    path = '/trade-api/v2/portfolio/positions'
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
        positions = data.get('positions', [])
        
        print(f'📊 Current Positions: {len(positions)}')
        
        if positions:
            total_tied = 0
            for pos in positions:
                ticker = pos.get('ticker', 'Unknown')
                side = pos.get('side', 'Unknown')
                count = pos.get('count', 0)
                price = pos.get('price', 0)
                value = count * price / 100
                total_tied += value
                
                print(f'  • {ticker}: {side} {count} contracts @ ${price/100:.2f} = ${value:.2f}')
            
            print(f'\n💰 Total tied up in positions: ${total_tied:.2f}')
        else:
            print('  No active positions found')
            
        return data
    else:
        print(f'❌ Error: {resp.status_code} - {resp.text}')
        return None

if __name__ == "__main__":
    check_positions()
