#!/usr/bin/env python3
"""
Check market timelines and settlement dates
"""

import os
import requests
import datetime
import base64
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

def check_market_timelines():
    api_key_id = os.environ.get('KALSHI_API_KEY_ID')
    print(f'Checking market timelines with API Key: {api_key_id}')

    # Load private key
    with open('kalshi-key.pem', 'rb') as f:
        private_key = serialization.load_pem_private_key(f.read(), password=None)

    # Get some markets to check their timelines
    timestamp = str(int(datetime.datetime.now().timestamp() * 1000))
    path = '/trade-api/v2/markets?limit=10'
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
        
        print(f'\n📊 Market Timelines Analysis:')
        print(f'=' * 60)
        
        timelines = {}
        
        for market in markets:
            ticker = market.get('ticker', 'Unknown')
            title = market.get('title', 'No title')
            close_time = market.get('close_time')
            
            if close_time:
                try:
                    # Parse the close time
                    close_dt = datetime.datetime.fromisoformat(close_time.replace('Z', '+00:00'))
                    now = datetime.datetime.now(datetime.timezone.utc)
                    
                    time_until_close = close_dt - now
                    days = time_until_close.days
                    hours = time_until_close.seconds // 3600
                    
                    timeline_type = "Unknown"
                    if days == 0 and hours < 1:
                        timeline_type = "⚡ Same Day"
                    elif days == 0 and hours < 24:
                        timeline_type = "📅 Today"
                    elif days < 7:
                        timeline_type = "📆 This Week"
                    elif days < 30:
                        timeline_type = "🗓️ This Month"
                    else:
                        timeline_type = "📅 Future"
                    
                    timelines[timeline_type] = timelines.get(timeline_type, 0) + 1
                    
                    print(f'\n{ticker}:')
                    print(f'  📋 {title}')
                    print(f'  ⏰ {timeline_type} ({days}d {hours}h)')
                    print(f'  📅 Closes: {close_time}')
                    
                except Exception as e:
                    print(f'\n{ticker}: Error parsing timeline - {e}')
        
        print(f'\n' + '=' * 60)
        print(f'📈 Timeline Summary:')
        for timeline, count in sorted(timelines.items()):
            print(f'  {timeline}: {count} markets')
        
        print(f'\n💡 Key Insights:')
        print(f'  • Most markets settle within days/weeks')
        print(f'  • Resting orders have plenty of time to fill')
        print(f'  • Capital is tied up but not at risk (orders can be canceled)')
        
    else:
        print(f'❌ Error getting markets: {resp.status_code} - {resp.text}')

if __name__ == "__main__":
    check_market_timelines()
