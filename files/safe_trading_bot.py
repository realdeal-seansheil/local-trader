#!/usr/bin/env python3
"""
Safe Trading Bot - Implements the Fixed Strategy
"""

import os
import json
import time
import requests
import datetime
import base64
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from safe_arbitrage_strategy import SafeArbitrageStrategy

class SafeTradingBot:
    def __init__(self, api_key_id, private_key_path):
        self.api_key_id = api_key_id
        self.private_key_path = private_key_path
        self.trader = SafeArbitrageStrategy(api_key_id, private_key_path)
        self.running = True
        self.start_time = datetime.datetime.now()
        
    def get_active_markets(self):
        """Get list of actively traded markets."""
        try:
            path = "/markets"
            headers = self.trader.get_headers("GET", path)
            url = f"{self.trader.base_url}{path}"
            
            resp = requests.get(url, headers=headers, timeout=15)
            
            if resp.status_code == 200:
                markets = resp.json()
                # Filter for active markets with good liquidity
                active_markets = []
                for market in markets.get("markets", []):
                    if (market.get("status") == "active" and 
                        market.get("yes_bid", 0) > 0 and 
                        market.get("no_bid", 0) > 0 and
                        market.get("yes_ask", 0) > 0 and 
                        market.get("no_ask", 0) > 0):
                        active_markets.append(market)
                return active_markets
            else:
                print(f"❌ Error getting markets: {resp.status_code}")
                return []
                
        except Exception as e:
            print(f"❌ Error fetching markets: {e}")
            return []
    
    def find_safe_opportunities(self, markets):
        """Find safe arbitrage opportunities."""
        opportunities = []
        
        for market in markets[:20]:  # Limit to first 20 for speed
            ticker = market.get("ticker")
            if not ticker:
                continue
                
            # Calculate safe arbitrage
            analysis = self.trader.calculate_safe_arbitrage(
                ticker, 5, 5, 2  # 5c pricing, 2 contracts
            )
            
            if analysis["is_safe"]:
                # Check market liquidity
                yes_bid = market.get("yes_bid", 0)
                no_bid = market.get("no_bid", 0)
                
                if yes_bid >= 5 and no_bid >= 5:  # Ensure our orders can fill
                    opportunities.append({
                        "ticker": ticker,
                        "analysis": analysis,
                        "market": market
                    })
        
        # Sort by profit potential
        opportunities.sort(key=lambda x: x["analysis"]["max_profit"], reverse=True)
        return opportunities
    
    def log_trade(self, trade_type, data):
        """Log trading activity."""
        log_entry = {
            "timestamp": datetime.datetime.now().isoformat(),
            "type": trade_type,
            "data": data
        }
        
        os.makedirs("data", exist_ok=True)
        with open("data/safe_trading.jsonl", "a") as f:
            f.write(json.dumps(log_entry) + "\n")
        
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {trade_type}: {data}")
    
    def run_safe_scan_and_trade(self):
        """Main trading loop with safety measures."""
        print("=" * 80)
        print("🛡️  SAFE TRADING BOT - FIXED STRATEGY")
        print("🎯 Real Execution, Real Profits, Low Risk")
        print("=" * 80)
        
        print(f"\n📊 CONFIGURATION:")
        print(f"   • Position Size: 2 contracts (SAFE)")
        print(f"   • Order Price: 5 cents (CONSERVATIVE)")
        print(f"   • Safety Margin: 10 cents minimum")
        print(f"   • Strategy: Market-based arbitrage")
        print(f"   • Risk Level: LOW")
        
        # Get initial balance
        balance = self.trader.get_portfolio_balance()
        if "error" not in balance:
            initial_balance = balance.get("total_balance", 0) / 100
            print(f"\n💰 Initial Balance: ${initial_balance:.2f}")
            self.log_trade("initial_balance", {"balance": initial_balance})
        
        scan_count = 0
        
        while self.running:
            try:
                scan_count += 1
                current_time = datetime.datetime.now()
                runtime = current_time - self.start_time
                
                print(f"\n📊 Scan #{scan_count} | Runtime: {runtime}")
                print("-" * 50)
                
                # Get active markets
                print("🔍 Scanning for safe opportunities...")
                markets = self.get_active_markets()
                
                if not markets:
                    print("❌ No active markets found")
                    time.sleep(30)
                    continue
                
                print(f"📈 Found {len(markets)} active markets")
                
                # Find safe opportunities
                opportunities = self.find_safe_opportunities(markets)
                
                if not opportunities:
                    print("❌ No safe opportunities found")
                    self.log_trade("no_opportunities", {"markets_checked": len(markets)})
                else:
                    print(f"🎯 Found {len(opportunities)} safe opportunities")
                    
                    # Show top 3 opportunities
                    for i, opp in enumerate(opportunities[:3], 1):
                        analysis = opp["analysis"]
                        print(f"   {i}. {opp['ticker']}")
                        print(f"      Max Profit: ${analysis['max_profit']/100:.2f}")
                        print(f"      Safety Margin: {analysis['required_spread']:.1f}c")
                    
                    # Execute the best opportunity
                    best_opp = opportunities[0]
                    print(f"\n🚀 Executing best opportunity: {best_opp['ticker']}")
                    
                    result = self.trader.execute_safe_arbitrage(
                        best_opp['ticker'], 
                        contracts=2
                    )
                    
                    if result["success"]:
                        self.log_trade("safe_execution", {
                            "ticker": result["ticker"],
                            "contracts": result["contracts"],
                            "analysis": result["analysis"],
                            "yes_order_id": result["yes_order"]["order_id"],
                            "no_order_id": result["no_order"]["order_id"]
                        })
                        
                        # Check balance after trade
                        new_balance = self.trader.get_portfolio_balance()
                        if "error" not in new_balance:
                            current_balance = new_balance.get("total_balance", 0) / 100
                            profit_loss = current_balance - initial_balance
                            print(f"💰 Current Balance: ${current_balance:.2f}")
                            print(f"📈 P&L: ${profit_loss:+.2f}")
                            
                            self.log_trade("balance_update", {
                                "balance": current_balance,
                                "p&l": profit_loss
                            })
                    else:
                        print(f"❌ Execution failed: {result.get('error')}")
                        self.log_trade("execution_failed", {
                            "ticker": best_opp['ticker'],
                            "error": result.get('error')
                        })
                
                # Wait before next scan
                print(f"\n⏳ Waiting 60 seconds before next scan...")
                time.sleep(60)
                
            except KeyboardInterrupt:
                print(f"\n🛑 Keyboard interrupt received")
                self.running = False
                break
            except Exception as e:
                print(f"\n❌ Error in main loop: {e}")
                self.log_trade("loop_error", {"error": str(e)})
                time.sleep(60)
        
        print(f"\n🏁 Safe trading session completed")
        print(f"📊 Total scans: {scan_count}")
        
        # Final balance check
        final_balance = self.trader.get_portfolio_balance()
        if "error" not in final_balance:
            final_balance_amount = final_balance.get("total_balance", 0) / 100
            total_pnl = final_balance_amount - initial_balance
            print(f"💰 Final Balance: ${final_balance_amount:.2f}")
            print(f"📈 Total P&L: ${total_pnl:+.2f}")

def main():
    """Main entry point."""
    api_key_id = os.environ.get('KALSHI_API_KEY_ID')
    if not api_key_id:
        print("❌ KALSHI_API_KEY_ID not found in environment")
        return
    
    bot = SafeTradingBot(api_key_id, 'kalshi-key.pem')
    bot.run_safe_scan_and_trade()

if __name__ == "__main__":
    main()
