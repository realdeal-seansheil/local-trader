#!/usr/bin/env python3
"""
Current Market Timing Analysis
Check actual market expiration times from live data.
"""

from kalshi_executor import KalshiAuth, KalshiClient
from datetime import datetime

def check_current_market_timing():
    print("=" * 60)
    print("📅 CURRENT MARKET TIMING ANALYSIS")
    print("=" * 60)
    print(f"Current time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Initialize client
    auth = KalshiAuth('dummy', 'dummy')
    client = KalshiClient(auth)
    
    # Check a few current opportunities
    tickers = [
        'KXLALIGAGAME-26FEB16GIRBAR-TIE',
        'KXATPCHALLENGERMATCH-26FEB16GOJMEN-GOJ',
        'KXBTC15M-26FEB161515-15'
    ]
    
    print(f"\n📊 MARKET EXPIRATION DETAILS:")
    print("-" * 50)
    
    for ticker in tickers:
        try:
            market = client.get_market(ticker)
            
            print(f"\n{ticker}:")
            print(f"  Title: {market.get('title', 'N/A')}")
            print(f"  Status: {market.get('status', 'N/A')}")
            print(f"  Close time: {market.get('close_time', 'N/A')}")
            print(f"  Created: {market.get('created_time', 'N/A')}")
            print(f"  Can close early: {market.get('can_close_early', 'N/A')}")
            
            # Parse close time if available
            close_time = market.get('close_time')
            if close_time:
                try:
                    # Parse ISO datetime
                    close_dt = datetime.fromisoformat(close_time.replace('Z', '+00:00'))
                    now = datetime.now()
                    
                    # Calculate time difference
                    if close_dt.tzinfo:
                        # Convert to local time for comparison
                        close_dt_local = close_dt.replace(tzinfo=None)
                    else:
                        close_dt_local = close_dt
                    
                    time_diff = close_dt_local - now
                    days = time_diff.days
                    hours = time_diff.seconds // 3600
                    minutes = (time_diff.seconds % 3600) // 60
                    
                    print(f"  Time until close: {days}d {hours}h {minutes}m")
                    
                    if days == 0 and hours < 24:
                        print(f"  → PAYS OUT TODAY!")
                    elif days <= 7:
                        print(f"  → PAYS OUT THIS WEEK")
                    else:
                        print(f"  → PAYS OUT IN {days} DAYS")
                        
                except Exception as e:
                    print(f"  Error parsing close time: {e}")
            
            # Check orderbook for liquidity
            try:
                orderbook = client.get_orderbook(ticker)
                yes_bids = orderbook.get('orderbook', {}).get('yes', [])
                no_bids = orderbook.get('orderbook', {}).get('no', [])
                
                print(f"  Liquidity: {len(yes_bids)} YES bids, {len(no_bids)} NO bids")
                
                if yes_bids and no_bids:
                    yes_price = yes_bids[0][0]
                    no_price = no_bids[0][0]
                    print(f"  Prices: YES {yes_price}c, NO {no_price}c")
                    
            except Exception as e:
                print(f"  Error checking orderbook: {e}")
                
        except Exception as e:
            print(f"  Error getting market data: {e}")
    
    print(f"\n" + "=" * 60)
    print("⏰ PAYOFF SCHEDULE SUMMARY")
    print("=" * 60)
    
    print(f"📈 Key Insights:")
    print(f"• Most opportunities appear to be same-day events")
    print(f"• Sports events typically resolve within hours")
    print(f"• Crypto markets (15M) resolve every 15 minutes")
    print(f"• Fast resolution = high capital turnover")
    
    print(f"\n💡 Trading Strategy:")
    print(f"• Same-day events: Multiple turnovers per day possible")
    print(f"• 15-minute crypto: 96+ arbitrage opportunities per day")
    print(f"• Sports events: Usually resolve same day as event")
    
    print(f"\n⚠️  Timing Risks:")
    print(f"• Events can be postponed or cancelled")
    print(f"• Market may suspend before event completion")
    print(f"• Early settlement if outcome becomes certain")

if __name__ == "__main__":
    check_current_market_timing()
