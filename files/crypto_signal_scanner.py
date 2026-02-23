#!/usr/bin/env python3
"""
Crypto Signal Scanner - Profitable Trading Signals
Identifies and tracks profitable crypto trading opportunities for manual execution
"""

import os
import json
import time
from datetime import datetime as dt, timedelta
from kalshi_executor import KalshiAuth, KalshiClient
from kalshi_executor import KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH
import requests
import base64
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

# ============================================================
# SIGNAL SCANNER CONFIGURATION
# ============================================================

# Scanning Parameters
SCAN_INTERVAL = 30              # 30-second scans
SESSION_DURATION_HOURS = 4      # 4-hour scanning session

# Crypto Series to Monitor
CRYPTO_SERIES = [
    'KXSATOSHIBTCYEAR',      # Satoshi Bitcoin movement
    'KXDOGE',                # Dogecoin events
    'KXETHATH',              # Ethereum ATH events
    'KXBTCMAXM',             # Bitcoin max price
    'KXCRYPTOPERFORMY',      # Crypto performance
]

# Signal Thresholds
MOMENTUM_THRESHOLD = 0.10     # 10% price movement for strong signal
VOLUME_THRESHOLD = 1000       # Minimum volume for reliable signals
MIN_CONFIDENCE = 0.60         # 60% minimum confidence for trading
MAX_PRICE = 90                # Maximum price to consider (avoid expensive contracts)

# Logging
SIGNALS_FILE = "data/crypto_signals.jsonl"
PERFORMANCE_FILE = "data/crypto_signal_performance.json"

# ============================================================
# GLOBAL STATE
# ============================================================

signals_generated = []
signal_performance = {
    "total_signals": 0,
    "high_confidence_signals": 0,
    "momentum_signals": 0,
    "event_signals": 0,
    "scans_completed": 0,
    "markets_analyzed": 0,
    "opportunities_found": 0
}

# ============================================================
# API FUNCTIONS
# ============================================================

def get_crypto_markets(auth, series_ticker):
    """Get crypto markets from live API."""
    try:
        timestamp = str(int(dt.now().timestamp() * 1000))
        path = f'/trade-api/v2/markets?series_ticker={series_ticker}&limit=50'
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
            print(f"❌ Error getting markets for {series_ticker}: {resp.status_code}")
            return []
            
    except Exception as e:
        print(f"❌ Exception getting markets for {series_ticker}: {e}")
        return []

# ============================================================
# SIGNAL GENERATION
# ============================================================

def analyze_momentum_signals(market):
    """Analyze momentum signals for a single market."""
    signals = []
    
    ticker = market.get('ticker', '')
    title = market.get('title', '')
    yes_ask = market.get('yes_ask', 0)
    no_ask = market.get('no_ask', 0)
    yes_bid = market.get('yes_bid', 0)
    no_bid = market.get('no_bid', 0)
    volume = market.get('volume', 0)
    status = market.get('status', 'unknown')
    
    # Skip markets with no pricing or too expensive
    if yes_ask == 0 and no_ask == 0:
        return signals
    
    if yes_ask > MAX_PRICE and no_ask > MAX_PRICE:
        return signals
    
    # Calculate price metrics
    yes_price = (yes_bid + yes_ask) / 200 if yes_ask > 0 else 0
    no_price = (no_bid + no_ask) / 200 if no_ask > 0 else 0
    
    # Momentum Signal 1: Strong directional bias
    if yes_price > 0.7 and yes_ask < MAX_PRICE:
        confidence = yes_price
        potential_return = (1.0 - yes_price) * 100  # cents per contract
        
        if confidence >= MIN_CONFIDENCE and volume >= VOLUME_THRESHOLD:
            signals.append({
                "type": "momentum_yes",
                "ticker": ticker,
                "title": title,
                "direction": "YES",
                "entry_price": yes_ask,
                "exit_price": 100,
                "confidence": confidence,
                "volume": volume,
                "potential_return_cents": potential_return,
                "risk_reward": f"1:{int(potential_return/yes_ask)}",
                "reasoning": f"Strong YES momentum at {yes_price:.1%} confidence",
                "status": status
            })
    
    if no_price > 0.7 and no_ask < MAX_PRICE:
        confidence = no_price
        potential_return = (1.0 - no_price) * 100  # cents per contract
        
        if confidence >= MIN_CONFIDENCE and volume >= VOLUME_THRESHOLD:
            signals.append({
                "type": "momentum_no",
                "ticker": ticker,
                "title": title,
                "direction": "NO",
                "entry_price": no_ask,
                "exit_price": 100,
                "confidence": confidence,
                "volume": volume,
                "potential_return_cents": potential_return,
                "risk_reward": f"1:{int(potential_return/no_ask)}",
                "reasoning": f"Strong NO momentum at {no_price:.1%} confidence",
                "status": status
            })
    
    # Momentum Signal 2: Value opportunities (cheap contracts)
    if yes_ask > 0 and yes_ask <= 20 and volume >= VOLUME_THRESHOLD * 2:
        confidence = 0.65  # Base confidence for value plays
        potential_return = 100 - yes_ask
        
        signals.append({
            "type": "value_yes",
            "ticker": ticker,
            "title": title,
            "direction": "YES",
            "entry_price": yes_ask,
            "exit_price": 100,
            "confidence": confidence,
            "volume": volume,
            "potential_return_cents": potential_return,
            "risk_reward": f"1:{int(potential_return/yes_ask)}",
            "reasoning": f"Value play - YES contracts at {yes_ask}c",
            "status": status
        })
    
    if no_ask > 0 and no_ask <= 20 and volume >= VOLUME_THRESHOLD * 2:
        confidence = 0.65  # Base confidence for value plays
        potential_return = 100 - no_ask
        
        signals.append({
            "type": "value_no",
            "ticker": ticker,
            "title": title,
            "direction": "NO",
            "entry_price": no_ask,
            "exit_price": 100,
            "confidence": confidence,
            "volume": volume,
            "potential_return_cents": potential_return,
            "risk_reward": f"1:{int(potential_return/no_ask)}",
            "reasoning": f"Value play - NO contracts at {no_ask}c",
            "status": status
        })
    
    return signals

def analyze_event_signals(market):
    """Analyze event-driven signals."""
    signals = []
    
    ticker = market.get('ticker', '')
    title = market.get('title', '')
    yes_ask = market.get('yes_ask', 0)
    no_ask = market.get('no_ask', 0)
    volume = market.get('volume', 0)
    status = market.get('status', 'unknown')
    
    # Event-driven signals based on title analysis
    title_lower = title.lower()
    
    # Bitcoin-related events
    if 'bitcoin' in title_lower or 'btc' in title_lower or 'satoshi' in title_lower:
        if yes_ask > 0 and yes_ask < MAX_PRICE:
            signals.append({
                "type": "event_btc",
                "ticker": ticker,
                "title": title,
                "direction": "YES",
                "entry_price": yes_ask,
                "confidence": 0.70,
                "volume": volume,
                "potential_return_cents": 100 - yes_ask,
                "reasoning": "Bitcoin event - bullish sentiment expected",
                "status": status
            })
    
    # Ethereum-related events
    if 'ethereum' in title_lower or 'eth' in title_lower:
        if yes_ask > 0 and yes_ask < MAX_PRICE:
            signals.append({
                "type": "event_eth",
                "ticker": ticker,
                "title": title,
                "direction": "YES",
                "entry_price": yes_ask,
                "confidence": 0.68,
                "volume": volume,
                "potential_return_cents": 100 - yes_ask,
                "reasoning": "Ethereum event - positive outlook",
                "status": status
            })
    
    # Performance comparison events
    if 'perform' in title_lower or 'better' in title_lower or 'best' in title_lower:
        if yes_ask > 0 and yes_ask < MAX_PRICE:
            signals.append({
                "type": "event_performance",
                "ticker": ticker,
                "title": title,
                "direction": "YES",
                "entry_price": yes_ask,
                "confidence": 0.65,
                "volume": volume,
                "potential_return_cents": 100 - yes_ask,
                "reasoning": "Performance comparison - growth potential",
                "status": status
            })
    
    return signals

def generate_trading_signals(auth):
    """Generate all trading signals."""
    all_signals = []
    markets_analyzed = 0
    
    print("🔍 Generating trading signals...")
    
    for series_ticker in CRYPTO_SERIES:
        print(f"\\n📊 Analyzing {series_ticker}...")
        
        markets = get_crypto_markets(auth, series_ticker)
        markets_analyzed += len(markets)
        
        print(f"   📈 Found {len(markets)} markets")
        
        for market in markets:
            # Generate momentum signals
            momentum_signals = analyze_momentum_signals(market)
            
            # Generate event signals
            event_signals = analyze_event_signals(market)
            
            # Combine signals
            combined_signals = momentum_signals + event_signals
            
            # Add timestamp and series info
            for signal in combined_signals:
                signal["timestamp"] = dt.now().isoformat()
                signal["series"] = series_ticker
                signal["signal_id"] = f"{signal['ticker']}_{signal['direction']}_{int(dt.now().timestamp())}"
            
            all_signals.extend(combined_signals)
    
    # Sort by confidence
    all_signals.sort(key=lambda x: x["confidence"], reverse=True)
    
    # Update performance stats
    signal_performance["total_signals"] = len(all_signals)
    signal_performance["high_confidence_signals"] = len([s for s in all_signals if s["confidence"] >= 0.8])
    signal_performance["momentum_signals"] = len([s for s in all_signals if "momentum" in s["type"]])
    signal_performance["event_signals"] = len([s for s in all_signals if "event" in s["type"]])
    signal_performance["markets_analyzed"] = markets_analyzed
    signal_performance["opportunities_found"] = len(all_signals)
    
    print(f"\\n🎯 Signal Generation Complete:")
    print(f"   📈 Total signals: {len(all_signals)}")
    print(f"   🚀 High confidence (80%+): {signal_performance['high_confidence_signals']}")
    print(f"   📊 Momentum signals: {signal_performance['momentum_signals']}")
    print(f"   🎯 Event signals: {signal_performance['event_signals']}")
    print(f"   📈 Markets analyzed: {markets_analyzed}")
    
    return all_signals

# ============================================================
# SIGNAL DISPLAY AND TRACKING
# ============================================================

def display_top_signals(signals, limit=10):
    """Display the top trading signals."""
    if not signals:
        print("📊 No trading signals found")
        return
    
    print(f"\\n🚀 TOP {limit} TRADING SIGNALS:")
    print("=" * 80)
    
    for i, signal in enumerate(signals[:limit]):
        print(f"\\n{i+1}. {signal['ticker']} ({signal['direction']})")
        print(f"   📊 Type: {signal['type']}")
        print(f"   💰 Entry: {signal['entry_price']}c | Confidence: {signal['confidence']:.1%}")
        print(f"   📈 Potential Return: {signal['potential_return_cents']}c per contract")
        print(f"   ⚖️  Risk/Reward: {signal['risk_reward']}")
        print(f"   📊 Volume: {signal['volume']} | Status: {signal['status']}")
        print(f"   💡 Reasoning: {signal['reasoning']}")
        print(f"   📈 Title: {signal['title'][:60]}")
        print(f"   🎯 Signal ID: {signal['signal_id']}")

def save_signals(signals):
    """Save signals to file."""
    os.makedirs(os.path.dirname(SIGNALS_FILE), exist_ok=True)
    
    with open(SIGNALS_FILE, "w") as f:
        for signal in signals:
            f.write(json.dumps(signal) + "\n")
    
    # Also save performance stats
    with open(PERFORMANCE_FILE, "w") as f:
        json.dump(signal_performance, f, indent=2, default=str)

def generate_manual_execution_guide(signals):
    """Generate a manual execution guide."""
    if not signals:
        return
    
    print(f"\\n📋 MANUAL EXECUTION GUIDE:")
    print("=" * 80)
    
    top_signals = signals[:5]  # Top 5 signals
    
    print(f"\\n🎯 RECOMMENDED TRADES (Execute Manually):")
    
    for i, signal in enumerate(top_signals):
        print(f"\\n{'='*60}")
        print(f"TRADE #{i+1}: {signal['ticker']} ({signal['direction']})")
        print(f"{'='*60}")
        print(f"📊 Market: {signal['title']}")
        print(f"💰 Action: BUY {signal['direction']} contracts")
        print(f"📈 Entry Price: {signal['entry_price']}c per contract")
        print(f"🎯 Confidence: {signal['confidence']:.1%}")
        print(f"💸 Potential Profit: {signal['potential_return_cents']}c per contract")
        print(f"⚖️  Risk/Reward: {signal['risk_reward']}")
        print(f"📊 Volume: {signal['volume']} contracts")
        print(f"💡 Reasoning: {signal['reasoning']}")
        print(f"\\n📋 EXECUTION STEPS:")
        print(f"   1. Go to Kalshi trading interface")
        print(f"   2. Search for ticker: {signal['ticker']}")
        print(f"   3. Select {signal['direction']} side")
        print(f"   4. Enter limit order at {signal['entry_price']}c")
        print(f"   5. Recommended size: 5-10 contracts")
        print(f"   6. Set stop-loss at {signal['entry_price'] * 1.5:.0f}c")
        print(f"   7. Take profit at 90c (if successful)")

# ============================================================
# MAIN SCANNING LOOP
# ============================================================

def run_crypto_signal_scanner():
    """Run the crypto signal scanner."""
    print("=" * 80)
    print("🚀 CRYPTO SIGNAL SCANNER")
    print("💰 Identifying Profitable Trading Opportunities")
    print("📋 Signals for Manual Execution")
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
        print(f"🎯 Monitoring {len(CRYPTO_SERIES)} crypto series")
        print(f"📊 Scan interval: {SCAN_INTERVAL} seconds")
        print(f"⏰ Session duration: {SESSION_DURATION_HOURS} hours")
        
        # Trading loop
        start_time = dt.now()
        end_time = start_time + timedelta(hours=SESSION_DURATION_HOURS)
        scan_count = 0
        
        print(f"🚀 Starting signal scanning...")
        print(f"📈 Session ends: {end_time.strftime('%H:%M:%S')}")
        
        while dt.now() < end_time:
            try:
                scan_count += 1
                signal_performance["scans_completed"] = scan_count
                current_time = dt.now()
                elapsed = current_time - start_time
                remaining = end_time - current_time
                
                print(f"\\n{'='*80}")
                print(f"📊 SCAN #{scan_count} | Elapsed: {elapsed.total_seconds()/60:.1f}m | Remaining: {remaining.total_seconds()/60:.1f}m")
                print(f"📈 Total signals generated: {signal_performance['total_signals']}")
                print(f"🚀 High confidence signals: {signal_performance['high_confidence_signals']}")
                
                # Generate trading signals
                signals = generate_trading_signals(auth)
                
                if signals:
                    # Display top signals
                    display_top_signals(signals, limit=5)
                    
                    # Generate execution guide
                    generate_manual_execution_guide(signals)
                    
                    # Save signals
                    save_signals(signals)
                    
                    print(f"\\n💾 Signals saved to: {SIGNALS_FILE}")
                    print(f"📊 Performance stats saved to: {PERFORMANCE_FILE}")
                else:
                    print(f"📊 No trading signals found in this scan")
                
                # Wait for next scan
                if dt.now() < end_time:
                    print(f"\\n⏳ Waiting {SCAN_INTERVAL} seconds for next scan...")
                    time.sleep(SCAN_INTERVAL)
                
            except KeyboardInterrupt:
                print(f"\\n🛑 Manual shutdown")
                break
            except Exception as e:
                print(f"❌ Error in scanning loop: {e}")
                time.sleep(30)
        
        # Final summary
        print(f"\\n{'='*80}")
        print(f"🏁 SIGNAL SCANNING SESSION COMPLETE")
        print(f"{'='*80}")
        print(f"📊 Total scans completed: {scan_count}")
        print(f"🚀 Total signals generated: {signal_performance['total_signals']}")
        print(f"🎯 High confidence signals: {signal_performance['high_confidence_signals']}")
        print(f"📈 Momentum signals: {signal_performance['momentum_signals']}")
        print(f"🎯 Event signals: {signal_performance['event_signals']}")
        print(f"📊 Markets analyzed: {signal_performance['markets_analyzed']}")
        print(f"💾 All signals saved to: {SIGNALS_FILE}")
        
        print(f"\\n🎉 READY FOR MANUAL TRADING!")
        print(f"📋 Check the signals file and execute the best opportunities manually.")
        
    except Exception as e:
        print(f"❌ Scanner initialization failed: {e}")

if __name__ == "__main__":
    run_crypto_signal_scanner()
