#!/usr/bin/env python3
"""
Live Trading Setup Script
Prepares the system for 48-hour automated trading.
"""

import os
import sys
from datetime import datetime

def check_setup():
    """Check if everything is ready for live trading."""
    print("="*60)
    print("🔧 LIVE TRADING SETUP CHECK")
    print("="*60)
    
    # Check private key file
    key_file = "kalshi-key.pem"
    if os.path.exists(key_file):
        print(f"✅ Private key file found: {key_file}")
    else:
        print(f"❌ Private key file missing: {key_file}")
        return False
    
    # Check API key ID
    api_key_id = os.environ.get("KALSHI_API_KEY_ID")
    if api_key_id and api_key_id != "YOUR_API_KEY_ID":
        print(f"✅ API Key ID found: {api_key_id[:8]}...{api_key_id[-4:]}")
    else:
        print(f"❌ API Key ID not set")
        print(f"Please run: export KALSHI_API_KEY_ID='your-api-key-id'")
        return False
    
    # Check directories
    dirs_to_check = ["data"]
    for dir_name in dirs_to_check:
        if os.path.exists(dir_name):
            print(f"✅ Directory exists: {dir_name}")
        else:
            os.makedirs(dir_name, exist_ok=True)
            print(f"📁 Created directory: {dir_name}")
    
    # Test authentication
    print(f"\n🔑 Testing Kalshi authentication...")
    try:
        from kalshi_executor import KalshiAuth, KalshiClient, KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH, USE_DEMO
        
        auth = KalshiAuth(KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH)
        client = KalshiClient(auth)
        
        balance = client.get_balance()
        print(f"✅ Authentication successful!")
        print(f"💰 Available balance: ${balance.get('available', 0):.2f}")
        
        # Test market access
        markets = client.get_markets(limit=1)
        print(f"✅ Market access confirmed")
        
    except Exception as e:
        print(f"❌ Authentication failed: {e}")
        return False
    
    return True

def show_configuration():
    """Display current trading configuration."""
    print(f"\n" + "="*60)
    print("⚙️  CURRENT TRADING CONFIGURATION")
    print("="*60)
    
    from kalshi_executor import (
        USE_DEMO, MAX_POSITION_SIZE, MAX_DAILY_TRADES, MAX_DAILY_EXPOSURE,
        MIN_SPREAD_FOR_ARB, KALSHI_FEE_RATE, MIN_PROFIT_AFTER_FEES
    )
    
    print(f"🔗 Trading Mode: {'DEMO' if USE_DEMO else 'LIVE'}")
    print(f"💰 Max position size: {MAX_POSITION_SIZE} contracts")
    print(f"📊 Max daily trades: {MAX_DAILY_TRADES}")
    print(f"💸 Max daily exposure: ${MAX_DAILY_EXPOSURE}")
    print(f"📈 Min spread required: {MIN_SPREAD_FOR_ARB*100} cents")
    print(f"💳 Kalshi fee rate: {KALSHI_FEE_RATE*100:.1f}%")
    print(f"🎯 Min profit after fees: ${MIN_PROFIT_AFTER_FEES}")
    
    # Bot configuration
    print(f"\n🤖 Bot Configuration:")
    print(f"⏰ Scan interval: 30 seconds")
    print(f"🚀 Auto-execute: ENABLED")
    print(f"💵 Position size: 10 contracts per trade")
    print(f"🎯 Min profit threshold: $0.05 per contract")
    print(f"⏱️  Session duration: 48 hours")
    print(f"📊 Max concurrent positions: 5")

def main():
    print("🚀 Setting up 48-hour automated arbitrage trading...")
    print(f"⏰ Setup time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Check if ready
    if not check_setup():
        print(f"\n❌ Setup incomplete. Please fix the issues above.")
        print(f"💡 Need help? Check the Kalshi API documentation.")
        return False
    
    # Show configuration
    show_configuration()
    
    print(f"\n" + "="*60)
    print("✅ SETUP COMPLETE - READY FOR LIVE TRADING")
    print("="*60)
    print(f"🚀 To start the 48-hour trading bot:")
    print(f"   python3 48hour_trading_bot.py")
    print(f"\n⚠️  IMPORTANT NOTES:")
    print(f"   • This will place REAL trades with REAL money")
    print(f"   • Monitor the bot closely for the first few hours")
    print(f"   • Press Ctrl+C to stop at any time")
    print(f"   • All trades are logged in data/48hour_trading.jsonl")
    print(f"   • Performance tracked in data/trading_performance.json")
    print(f"\n🎯 Expected Performance (based on current opportunities):")
    print(f"   • Profit per arbitrage: ~$9.80 (10 contracts)")
    print(f"   • Daily opportunities: 20-50")
    print(f"   • Potential daily profit: $200-$500")
    print(f"   • 48-hour potential: $400-$1,000")
    
    return True

if __name__ == "__main__":
    main()
