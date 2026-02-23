#!/usr/bin/env python3
"""
Orderbook Scanner - Uses the same approach as the original working bot
"""

import os
from kalshi_executor import KalshiAuth, KalshiClient, StrategyExecutor
from kalshi_executor import KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH

def scan_orderbook_opportunities():
    """Scan for arbitrage opportunities using orderbook data like the original bot."""
    auth = KalshiAuth(KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH)
    client = KalshiClient(auth)
    executor = StrategyExecutor(client)
    
    print("🔍 Scanning for arbitrage opportunities using orderbook data...")
    
    # Get all markets first
    result = client.get_markets(status="open", limit=200)
    markets = result.get("markets", [])
    
    opportunities = []
    
    for market in markets:
        ticker = market.get("ticker", "")
        
        try:
            # Get orderbook data like the original bot
            orderbook = client.get_orderbook(ticker)
            
            if not orderbook or "orderbook" not in orderbook:
                continue
                
            yes_bids = orderbook["orderbook"].get("yes", [])
            no_bids = orderbook["orderbook"].get("no", [])
            
            if not yes_bids or not no_bids:
                continue
            
            # Get best prices from orderbook
            best_yes_price = yes_bids[0][0] if yes_bids else None
            best_no_price = no_bids[0][0] if no_bids else None
            
            if not best_yes_price or not best_no_price:
                continue
            
            combined = (best_yes_price + best_no_price) / 100
            
            if combined < 1.0 - 0.02:  # 2 cent minimum spread
                spread = round(1.0 - combined, 4)
                
                opportunities.append({
                    "ticker": ticker,
                    "title": market.get("title", ""),
                    "yes_price_cents": best_yes_price,
                    "no_price_cents": best_no_price,
                    "combined": round(combined, 4),
                    "spread": spread,
                    "volume": market.get("volume", 0),
                    "net_profit_per_contract": spread - 0.002,  # Approximate fees
                    "total_fees_per_contract": 0.002,
                    "roi_net_percent": (spread - 0.002) / 0.98 * 100,
                    "source": "orderbook"
                })
                
        except Exception as e:
            print(f"   ❌ Error scanning {ticker}: {e}")
            continue
    
    # Sort by spread (best first)
    opportunities.sort(key=lambda x: x["spread"], reverse=True)
    
    print(f"📊 Found {len(opportunities)} opportunities using orderbook data")
    
    if opportunities:
        print(f"🎉 Top opportunities:")
        for i, opp in enumerate(opportunities[:5]):
            print(f"   {i+1}. {opp.get('ticker', 'Unknown')}")
            print(f"      Spread: {opp.get('spread', 0)}")
            print(f"      Net profit: ${opp.get('net_profit_per_contract', 0):.4f}")
            print(f"      Source: {opp.get('source', 'Unknown')}")
    else:
        print(f"❌ No opportunities found")
    
    return opportunities

if __name__ == "__main__":
    scan_orderbook_opportunities()
