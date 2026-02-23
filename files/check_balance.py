#!/usr/bin/env python3
"""
Check current balance with corrected authentication
"""

import os
import requests
import datetime
import base64
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

def check_balance():
    api_key_id = os.environ.get('KALSHI_API_KEY_ID')
    print(f'Checking balance for API Key: {api_key_id}')

    # Load private key
    with open('kalshi-key.pem', 'rb') as f:
        private_key = serialization.load_pem_private_key(f.read(), password=None)

    # Use current timestamp
    timestamp = str(int(datetime.datetime.now().timestamp() * 1000))
    path = '/trade-api/v2/portfolio/balance'
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
        balance_cents = data.get('balance', 0)
        portfolio_cents = data.get('portfolio_value', 0)
        available_cents = data.get('available', 0)
        
        print(f'✅ Balance: ${balance_cents / 100:.2f}')
        print(f'✅ Portfolio value: ${portfolio_cents / 100:.2f}')
        print(f'✅ Available: ${available_cents / 100:.2f}')
        
        if available_cents > 0:
            print(f'\n🚀 FUNDS AVAILABLE FOR TRADING!')
            print(f'   Can execute {available_cents // 2} arbitrages (10 contracts each)')
        else:
            print(f'\n⚠️  No available funds for trading')
            print(f'   Please deposit funds to start trading')
            
        return data
    else:
        print(f'❌ Error: {resp.status_code} - {resp.text}')
        return None

if __name__ == "__main__":
    check_balance()
