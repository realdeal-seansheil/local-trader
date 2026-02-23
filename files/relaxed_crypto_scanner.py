#!/usr/bin/env python3
"""
Relaxed Crypto Scanner - Find ALL Opportunities
Based on real distinct-baguette strategy: any price, any volume, momentum focus
"""

import os
import json
import time
from datetime import datetime as dt
from kalshi_executor import KalshiAuth, KalshiClient
from kalshi_executor import KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH
import requests
import base64
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

# ============================================================
# RELAXED FILTER CONFIGURATION (Real Distinct-Baguette Style)
# ============================================================

# Relaxed Filters (What distinct-baguette actually uses)
MAX_PRICE = 90                # Include contracts up to 90c
MIN_VOLUME = 50              # Include smaller volumes
MIN_PROFIT = 1               # Include 1 cent profits
ALL_FREQUENCIES = True        # All timeframes, not just 15-min

# Aggressive Parameters (distinct-baguette style)
SCAN_INTERVAL = 15            # 15-second scans
POSITION_SIZE = 10           # 10 contracts per trade
MAX_POSITIONS = 10           # More concurrent positions
TARGET_PROFIT = 0.02         # 2 cent target (realistic)
STOP_LOSS = 0.05            # 5 cent stop loss

# ============================================================
# API FUNCTIONS
# ============================================================

def get_crypto_markets(auth, series_ticker, limit=20):
    """Get markets for a crypto series."""
    try:
        timestamp = str(int(dt.now().timestamp() * 1000))
        path = f'/trade-api/v2/markets?series_ticker={series_ticker}&limit={limit}'
        method = 'GET'
        
        msg = timestamp + method + path
        
        sig_bytes = auth.private_key.sign(
            msg.encode(),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH
            ),
            hashes.SHA256()
        )
        signature = base64.b64encode(sig_bytes).decode()
        
        headers = {
            'KALSHI-ACCESS-KEY': auth.api_key_id,
            'KALSHI-ACCESS-SIGNATURE': signature,
            'KALSHI-ACCESS-TIMESTAMP': timestamp,
            'Content-Type': 'application/json',
        }
        
        url = 'https://api.elections.kalshi.com' + path
        resp = requests.get(url, headers=headers, timeout=15)
        
        if resp.status_code == 200:
            data = resp.json()
            return data.get('markets', [])
        else:
            return []
            
    except Exception as e:
        return []

def get_all_crypto_series(auth):
    """Get all crypto-related series."""
    try:
        timestamp = str(int(dt.now().timestamp() * 1000))
        path = '/trade-api/v2/series'
        method = 'GET'
        
        msg = timestamp + method + path
        
        sig_bytes = auth.private_key.sign(
            msg.encode(),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH
            ),
            hashes.SHA256()
        )
        signature = base64.b64encode(sig_bytes).decode()
        
        headers = {
            'KALSHI-ACCESS-KEY': auth.api_key_id,
            'KALSHI-ACCESS-SIGNATURE': signature,
            'KALSHI-ACCESS-TIMESTAMP': timestamp,
            'Content-Type': 'application/json',
        }
        
        url = 'https://api.elections.kalshi.com' + path
        resp = requests.get(url, headers=headers, timeout=15)
        
        if resp.status_code == 200:
            data = resp.json()
            all_series = data.get('series', [])
            
            # Filter for crypto-related series
            crypto_series = []
            for series in all_series:
                ticker = series.get('ticker', '')
                title = series.get('title', '').lower()
                category = series.get('category', '').lower()
                
                if any(keyword in title for keyword in [
                    'crypto', 'bitcoin', 'ethereum', 'btc', 'eth', 'doge', 
                    'solana', 'cardano', 'ripple', 'xrp', 'litecoin', 'ltc',
                    'chainlink', 'link', 'polkadot', 'dot', 'avalanche', 'avax'
                ]) or any(keyword in ticker.lower() for keyword in [
                    'btc', 'eth', 'doge', 'sol', 'ada', 'xrp', 'ltc', 'link', 'dot', 'avax'
                ]):
                    crypto_series.append(series)
            
            return crypto_series
        else:
            return []
            
    except Exception as e:
        return []

# ============================================================
# OPPORTUNITY ANALYSIS (RELAXED FILTERS)
# ============================================================

def analyze_all_opportunities(auth):
    """Analyze all crypto opportunities with relaxed filters."""
    print("🔍 Getting all crypto series...")
    
    crypto_series = get_all_crypto_series(auth)
    print(f"📊 Found {len(crypto_series)} crypto series")
    
    all_opportunities = []
    markets_analyzed = 0
    
    print("🚀 Analyzing markets with relaxed filters...")
    
    for series in crypto_series[:20]:  # Analyze top 20 series for speed
        series_ticker = series.get('ticker', '')
        series_title = series.get('title', '')
        frequency = series.get('frequency', '')
        
        print(f"\\n📊 {series_ticker}: {series_title}")
        print(f"   ⏰ Frequency: {frequency}")
        
        markets = get_crypto_markets(auth, series_ticker, limit=10)
        markets_analyzed += len(markets)
        
        print(f"   📈 Found {len(markets)} markets")
        
        for market in markets:
            ticker = market.get('ticker', '')
            title = market.get('title', '')
            yes_ask = market.get('yes_ask', 0)
            no_ask = market.get('no_ask', 0)
            yes_bid = market.get('yes_bid', 0)
            no_bid = market.get('no_bid', 0)
            volume = market.get('volume', 0)
            status = market.get('status', 'unknown')
            
            # Skip if no pricing
            if yes_ask == 0 and no_ask == 0:
                continue
            
            # RELAXED FILTER 1: Any price under 90c
            if yes_ask > 0 and yes_ask < MAX_PRICE:
                profit_potential = 100 - yes_ask
                confidence = (100 - yes_ask) / 100
                
                # RELAXED FILTER 2: Any volume > 50
                if volume >= MIN_VOLUME:
                    # RELAXED FILTER 3: Any profit > 1c
                    if profit_potential >= MIN_PROFIT:
                        all_opportunities.append({
                            "ticker": ticker,
                            "title": title,
                            "series": series_ticker,
                            "direction": "YES",
                            "entry_price": yes_ask,
                            "target_price": 100,
                            "profit_potential": profit_potential,
                            "confidence": confidence,
                            "volume": volume,
                            "frequency": frequency,
                            "strategy": "relaxed_yes",
                            "reasoning": f"Relaxed filter: YES at {yes_ask}c, {profit_potential}c profit"
                        })
                        
                        print(f"      🚀 YES Opportunity: {ticker} at {yes_ask}c ({profit_potential}c profit)")
            
            # Same for NO contracts
            if no_ask > 0 and no_ask < MAX_PRICE:
                profit_potential = 100 - no_ask
                confidence = (100 - no_ask) / 100
                
                if volume >= MIN_VOLUME and profit_potential >= MIN_PROFIT:
                    all_opportunities.append({
                        "ticker": ticker,
                        "title": title,
                        "series": series_ticker,
                        "direction": "NO",
                        "entry_price": no_ask,
                        "target_price": 100,
                        "profit_potential": profit_potential,
                        "confidence": confidence,
                        "volume": volume,
                        "frequency": frequency,
                        "strategy": "relaxed_no",
                        "reasoning": f"Relaxed filter: NO at {no_ask}c, {profit_potential}c profit"
                    })
                    
                    print(f"      🚀 NO Opportunity: {ticker} at {no_ask}c ({profit_potential}c profit)")
            
            # MOMENTUM OPPORTUNITIES (distinct-baguette specialty)
            if yes_ask > 0 and no_ask > 0:
                combined = (yes_ask + no_ask) / 100
                spread = round(1.0 - combined, 4)
                
                # Look for order imbalances (momentum signals)
                if volume > 100:  # Some volume for momentum
                    if yes_ask < 40:  # YES is cheap (momentum play)
                        momentum_confidence = (40 - yes_ask) / 40
                        
                        all_opportunities.append({
                            "ticker": ticker,
                            "title": title,
                            "series": series_ticker,
                            "direction": "YES",
                            "entry_price": yes_ask,
                            "profit_potential": 40 - yes_ask,
                            "confidence": momentum_confidence,
                            "volume": volume,
                            "frequency": frequency,
                            "strategy": "momentum_yes",
                            "reasoning": f"Momentum: YES cheap at {yes_ask}c, volume {volume}"
                        })
                    
                    if no_ask < 40:  # NO is cheap (momentum play)
                        momentum_confidence = (40 - no_ask) / 40
                        
                        all_opportunities.append({
                            "ticker": ticker,
                            "title": title,
                            "series": series_ticker,
                            "direction": "NO",
                            "entry_price": no_ask,
                            "profit_potential": 40 - no_ask,
                            "confidence": momentum_confidence,
                            "volume": volume,
                            "frequency": frequency,
                            "strategy": "momentum_no",
                            "reasoning": f"Momentum: NO cheap at {no_ask}c, volume {volume}"
                        })
    
    # Sort by volume * confidence (distinct-baguette style)
    all_opportunities.sort(key=lambda x: x["volume"] * x["confidence"], reverse=True)
    
    print(f"\\n🎯 RELAXED FILTER RESULTS:")
    print(f"📈 Markets analyzed: {markets_analyzed}")
    print(f"🚀 Total opportunities: {len(all_opportunities)}")
    
    # Categorize opportunities
    relaxed_yes = [o for o in all_opportunities if o["strategy"] == "relaxed_yes"]
    relaxed_no = [o for o in all_opportunities if o["strategy"] == "relaxed_no"]
    momentum_yes = [o for o in all_opportunities if o["strategy"] == "momentum_yes"]
    momentum_no = [o for o in all_opportunities if o["strategy"] == "momentum_no"]
    
    print(f"💸 Relaxed YES opportunities: {len(relaxed_yes)}")
    print(f"💸 Relaxed NO opportunities: {len(relaxed_no)}")
    print(f"🚀 Momentum YES opportunities: {len(momentum_yes)}")
    print(f"🚀 Momentum NO opportunities: {len(momentum_no)}")
    
    return all_opportunities

def display_top_opportunities(opportunities, limit=15):
    """Display top opportunities with manual execution guide."""
    if not opportunities:
        print("📊 No opportunities found with relaxed filters")
        return
    
    print(f"\\n🚀 TOP {limit} OPPORTUNITIES (RELAXED FILTERS):")
    print("=" * 80)
    
    for i, opp in enumerate(opportunities[:limit]):
        print(f"\\n{i+1}. {opp['ticker']} ({opp['direction']})")
        print(f"   📊 Strategy: {opp['strategy']}")
        print(f"   📈 Series: {opp['series']} ({opp['frequency']})")
        print(f"   💰 Entry: {opp['entry_price']}c | Target: {opp['target_price']}c")
        print(f"   📈 Profit: {opp['profit_potential']}c | Confidence: {opp['confidence']:.1%}")
        print(f"   📊 Volume: {opp['volume']} | Status: Active")
        print(f"   💡 Reasoning: {opp['reasoning']}")
        print(f"   📈 Title: {opp['title'][:60]}")
        
        # Manual execution guide
        print(f"   📋 EXECUTE: Buy {opp['direction']} at {opp['entry_price']}c, size 10 contracts")
        print(f"   🎯 Expected profit: ${opp['profit_potential'] * 10 / 100:.2f}")

# ============================================================
# MAIN SCANNER
# ============================================================

def run_relaxed_crypto_scanner():
    """Run the relaxed crypto scanner."""
    print("=" * 80)
    print("🚀 RELAXED CRYPTO SCANNER")
    print("💰 Real Distinct-Baguette Strategy: Any Price, Any Volume, Momentum Focus")
    print("=" * 80)
    
    # Check API key
    if not KALSHI_API_KEY_ID or KALSHI_API_KEY_ID == "YOUR_API_KEY_ID":
        print("❌ Please set KALSHI_API_KEY_ID environment variable")
        return
    
    try:
        # Initialize authentication
        auth = KalshiAuth(KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH)
        
        # Test authentication
        client = KalshiClient(auth)
        test_markets = client.get_markets(limit=1)
        
        if not test_markets.get('markets'):
            print("❌ Authentication failed - no market access")
            return
        
        print(f"✅ Authentication successful")
        print(f"🎯 Relaxed Filters: Price < {MAX_PRICE}c, Volume > {MIN_VOLUME}, Profit > {MIN_PROFIT}c")
        print(f"📊 All crypto frequencies (not just 15-min)")
        print(f"⚡ Scan interval: {SCAN_INTERVAL} seconds")
        
        # Analyze all opportunities
        opportunities = analyze_all_opportunities(auth)
        
        if opportunities:
            # Display top opportunities
            display_top_opportunities(opportunities, limit=15)
            
            # Save opportunities
            with open('relaxed_crypto_opportunities.json', 'w') as f:
                json.dump(opportunities, f, indent=2)
            
            print(f"\\n💾 Opportunities saved to: relaxed_crypto_opportunities.json")
            
            # Generate execution summary
            print(f"\\n📋 EXECUTION SUMMARY:")
            print(f"🎯 Top 5 recommendations for immediate execution:")
            
            for i, opp in enumerate(opportunities[:5]):
                expected_profit = opp['profit_potential'] * POSITION_SIZE / 100
                print(f"\\n{i+1}. {opp['ticker']} ({opp['direction']})")
                print(f"   💰 Buy at {opp['entry_price']}c, size {POSITION_SIZE} contracts")
                print(f"   📈 Expected profit: ${expected_profit:.2f}")
                print(f"   📊 Volume: {opp['volume']} | Confidence: {opp['confidence']:.1%}")
                print(f"   💡 {opp['reasoning']}")
            
            total_potential = sum(opp['profit_potential'] * POSITION_SIZE / 100 for opp in opportunities[:5])
            print(f"\\n💰 Total potential profit (top 5): ${total_potential:.2f}")
            
        else:
            print(f"📊 No opportunities found even with relaxed filters")
        
        print(f"\\n🎉 RELAXED SCANNER COMPLETE!")
        print(f"📋 This is the real distinct-baguette approach - many small opportunities!")
        
    except Exception as e:
        print(f"❌ Scanner failed: {e}")

if __name__ == "__main__":
    run_relaxed_crypto_scanner()
