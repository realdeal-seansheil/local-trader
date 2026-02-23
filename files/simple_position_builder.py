#!/usr/bin/env python3
"""
Simple Position Builder - Uses existing API structure
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
from kalshi_executor import KalshiAuth, KalshiClient, StrategyExecutor

class SimplePositionBuilder:
    def __init__(self):
        # Use existing authentication
        self.auth = KalshiAuth()
        self.client = KalshiClient(self.auth)
        self.executor = StrategyExecutor(self.auth, self.client)
        
    def get_all_markets(self):
        """Get all available markets."""
        try:
            markets = self.client.get_markets()
            return markets.get("markets", [])
        except Exception as e:
            print(f"❌ Error getting markets: {e}")
            return []
    
    def place_simple_order(self, ticker, side, price, count):
        """Place a simple order using existing executor."""
        try:
            # Use the existing order placement method
            order_data = {
                "ticker": ticker,
                "side": side,
                "action": "buy",
                "count": count,
                "type": "limit",
                f"{side}_price": price,
            }
            
            # This should work with existing authentication
            result = self.executor.place_order(order_data)
            return result
            
        except Exception as e:
            print(f"❌ Order failed: {e}")
            return {"success": False, "error": str(e)}
    
    def strategy_1_dollar_cost_average(self, markets):
        """Strategy 1: Dollar cost average into multiple markets."""
        print("📊 STRATEGY 1: Dollar Cost Averaging")
        print("-" * 50)
        
        trades_placed = 0
        
        # Take first 10 markets and place small orders
        for i, market in enumerate(markets[:10]):
            ticker = market.get("ticker", "")
            if not ticker:
                continue
                
            print(f"🎯 {i+1}. Placing small position in {ticker}")
            
            # Place very small orders (1 contract at 1c)
            yes_result = self.place_simple_order(ticker, "yes", 1, 1)
            if yes_result.get("success"):
                print(f"✅ YES order placed")
                trades_placed += 1
            else:
                print(f"❌ YES order failed: {yes_result.get('error')}")
            
            time.sleep(0.5)  # Small delay
            
            no_result = self.place_simple_order(ticker, "no", 1, 1)
            if no_result.get("success"):
                print(f"✅ NO order placed")
                trades_placed += 1
            else:
                print(f"❌ NO order failed: {no_result.get('error')}")
            
            time.sleep(0.5)
        
        return trades_placed
    
    def strategy_2_concentrated_positions(self, markets):
        """Strategy 2: Concentrated positions in best markets."""
        print("📊 STRATEGY 2: Concentrated Positions")
        print("-" * 50)
        
        trades_placed = 0
        
        # Find markets with some activity (check if they have bid/ask)
        active_markets = []
        for market in markets:
            ticker = market.get("ticker", "")
            yes_bid = market.get("yes_bid", 0)
            no_bid = market.get("no_bid", 0)
            
            if yes_bid > 0 or no_bid > 0:
                active_markets.append(market)
        
        print(f"📈 Found {len(active_markets)} active markets")
        
        # Place larger orders on top 5 active markets
        for i, market in enumerate(active_markets[:5]):
            ticker = market.get("ticker", "")
            print(f"🎯 {i+1}. Concentrated position in {ticker}")
            
            # 3 contracts at 2c each
            yes_result = self.place_simple_order(ticker, "yes", 2, 3)
            if yes_result.get("success"):
                print(f"✅ YES order: 3 contracts at 2c")
                trades_placed += 1
            
            time.sleep(1)
            
            no_result = self.place_simple_order(ticker, "no", 2, 3)
            if no_result.get("success"):
                print(f"✅ NO order: 3 contracts at 2c")
                trades_placed += 1
            
            time.sleep(1)
        
        return trades_placed
    
    def strategy_3_diversified_spread(self, markets):
        """Strategy 3: Diversified spread across many markets."""
        print("📊 STRATEGY 3: Diversified Spread")
        print("-" * 50)
        
        trades_placed = 0
        
        # Spread across 20 different markets
        for i, market in enumerate(markets[:20]):
            ticker = market.get("ticker", "")
            if not ticker:
                continue
                
            print(f"🎯 {i+1}. Diversified position in {ticker}")
            
            # Vary the position sizes
            contracts = 1 if i % 2 == 0 else 2
            price = 1 if i % 3 == 0 else 2
            
            yes_result = self.place_simple_order(ticker, "yes", price, contracts)
            if yes_result.get("success"):
                print(f"✅ YES: {contracts} contracts at {price}c")
                trades_placed += 1
            
            time.sleep(0.3)
            
            no_result = self.place_simple_order(ticker, "no", price, contracts)
            if no_result.get("success"):
                print(f"✅ NO: {contracts} contracts at {price}c")
                trades_placed += 1
            
            time.sleep(0.3)
        
        return trades_placed
    
    def strategy_4_aggressive_entry(self, markets):
        """Strategy 4: Aggressive entry with higher prices."""
        print("📊 STRATEGY 4: Aggressive Entry")
        print("-" * 50)
        
        trades_placed = 0
        
        # Use higher prices (5c) for better fill chances
        for i, market in enumerate(markets[:8]):
            ticker = market.get("ticker", "")
            if not ticker:
                continue
                
            print(f"🎯 {i+1}. Aggressive position in {ticker}")
            
            # 5 contracts at 5c (higher chance of fills)
            yes_result = self.place_simple_order(ticker, "yes", 5, 5)
            if yes_result.get("success"):
                print(f"✅ YES: 5 contracts at 5c")
                trades_placed += 1
            
            time.sleep(1)
            
            no_result = self.place_simple_order(ticker, "no", 5, 5)
            if no_result.get("success"):
                print(f"✅ NO: 5 contracts at 5c")
                trades_placed += 1
            
            time.sleep(1)
        
        return trades_placed
    
    def run_position_building_session(self):
        """Run a complete position building session."""
        print("=" * 80)
        print("🏗️  SIMPLE POSITION BUILDER")
        print("🎯 Build Positions for Marginal Profits")
        print("=" * 80)
        
        # Get current balance
        try:
            balance = self.client.get_balance()
            current_balance = balance.get("total_balance", 0) / 100
            print(f"💰 Starting Balance: ${current_balance:.2f}")
        except:
            print("❌ Could not get balance")
            current_balance = 0
        
        # Get markets
        print(f"\n🔍 Fetching markets...")
        markets = self.get_all_markets()
        print(f"📈 Found {len(markets)} markets")
        
        total_trades = 0
        
        # Run all strategies
        strategies = [
            ("Dollar Cost Averaging", self.strategy_1_dollar_cost_average),
            ("Concentrated Positions", self.strategy_2_concentrated_positions),
            ("Diversified Spread", self.strategy_3_diversified_spread),
            ("Aggressive Entry", self.strategy_4_aggressive_entry)
        ]
        
        for strategy_name, strategy_func in strategies:
            print(f"\n" + "="*60)
            try:
                trades = strategy_func(markets)
                total_trades += trades
                print(f"✅ {strategy_name}: {trades} trades placed")
            except Exception as e:
                print(f"❌ {strategy_name} failed: {e}")
        
        # Final balance check
        try:
            final_balance = self.client.get_balance()
            final_balance_amount = final_balance.get("total_balance", 0) / 100
            pnl = final_balance_amount - current_balance
            print(f"\n" + "="*60)
            print(f"📊 SESSION SUMMARY")
            print(f"💰 Starting Balance: ${current_balance:.2f}")
            print(f"💰 Ending Balance: ${final_balance_amount:.2f}")
            print(f"📈 P&L: ${pnl:+.2f}")
            print(f"📊 Total Orders Placed: {total_trades}")
            print(f"🎯 Status: {'POSITIONS BUILT' if total_trades > 0 else 'NO ORDERS'}")
            
            if total_trades > 0:
                print(f"\n💡 NEXT STEPS:")
                print(f"   • Monitor orders for fills")
                print(f"   • Track P&L as positions complete")
                print(f"   • Adjust strategy based on results")
            
        except Exception as e:
            print(f"❌ Could not get final balance: {e}")

def main():
    """Main entry point."""
    builder = SimplePositionBuilder()
    builder.run_position_building_session()

if __name__ == "__main__":
    main()
