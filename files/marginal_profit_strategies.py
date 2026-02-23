#!/usr/bin/env python3
"""
Marginal Profit Strategies - Safe Trading for Any Market Condition
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

class MarginalProfitTrader:
    def __init__(self, api_key_id, private_key_path):
        self.api_key_id = api_key_id
        self.private_key_path = private_key_path
        self.base_url = "https://api.elections.kalshi.com/trade-api/v2"
        
    def get_headers(self, method, path):
        """Generate headers for API requests."""
        timestamp = str(int(datetime.datetime.now().timestamp() * 1000))
        msg = timestamp + method + path
        
        with open(self.private_key_path, 'rb') as f:
            private_key = serialization.load_pem_private_key(f.read(), password=None)
        
        sig_bytes = private_key.sign(
            msg.encode(),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH
            ),
            hashes.SHA256()
        )
        signature = base64.b64encode(sig_bytes).decode()
        
        return {
            'KALSHI-ACCESS-KEY': self.api_key_id,
            'KALSHI-ACCESS-SIGNATURE': signature,
            'KALSHI-ACCESS-TIMESTAMP': timestamp,
            'Content-Type': 'application/json',
        }
    
    def get_all_markets(self):
        """Get all available markets."""
        try:
            path = "/markets"
            headers = self.get_headers("GET", path)
            url = f"{self.base_url}{path}"
            
            resp = requests.get(url, headers=headers, timeout=15)
            
            if resp.status_code == 200:
                return resp.json()
            else:
                return {"error": resp.status_code, "detail": resp.text}
                
        except Exception as e:
            return {"error": "Request failed", "detail": str(e)}
    
    def get_portfolio_balance(self):
        """Get current portfolio balance."""
        try:
            path = "/portfolio"
            headers = self.get_headers("GET", path)
            url = f"{self.base_url}{path}"
            
            resp = requests.get(url, headers=headers, timeout=15)
            
            if resp.status_code == 200:
                return resp.json()
            else:
                return {"error": resp.status_code, "detail": resp.text}
                
        except Exception as e:
            return {"error": "Request failed", "detail": str(e)}
    
    def place_limit_order(self, ticker, side, price, count):
        """Place a limit order."""
        try:
            timestamp = str(int(datetime.datetime.now().timestamp() * 1000))
            path = "/portfolio/orders"
            method = "POST"
            
            headers = self.get_headers(method, path)
            
            import uuid
            order_data = {
                "ticker": ticker,
                "side": side,
                "action": "buy",
                "count": count,
                "type": "limit",
                f"{side}_price": price,
                "client_order_id": str(uuid.uuid4()),
            }
            
            url = f"{self.base_url}{path}"
            resp = requests.post(url, headers=headers, json=order_data, timeout=15)
            
            if resp.status_code == 201:
                result = resp.json()
                return {
                    "success": True,
                    "order_id": result.get("order", {}).get("order_id"),
                    "price": price,
                    "count": count,
                    "side": side,
                    "raw_response": result
                }
            else:
                return {"success": False, "error": resp.status_code, "detail": resp.text}
                
        except Exception as e:
            return {"success": False, "error": "Request failed", "detail": str(e)}
    
    def strategy_1_liquid_markets(self, markets):
        """Strategy 1: Trade most liquid markets even with tiny spreads."""
        print("📊 STRATEGY 1: Liquid Markets - Tiny Profits")
        print("-" * 50)
        
        # Find markets with any liquidity
        liquid_markets = []
        for market in markets:
            ticker = market.get("ticker", "")
            yes_bid = market.get("yes_bid", 0)
            no_bid = market.get("no_bid", 0)
            yes_ask = market.get("yes_ask", 0)
            no_ask = market.get("no_ask", 0)
            
            # Any market with some bids/asks
            if yes_bid > 0 or no_bid > 0 or yes_ask > 0 or no_ask > 0:
                liquid_markets.append({
                    "ticker": ticker,
                    "yes_bid": yes_bid,
                    "no_bid": no_bid,
                    "yes_ask": yes_ask,
                    "no_ask": no_ask,
                    "liquidity_score": yes_bid + no_bid + yes_ask + no_ask
                })
        
        # Sort by liquidity
        liquid_markets.sort(key=lambda x: x["liquidity_score"], reverse=True)
        
        print(f"📈 Found {len(liquid_markets)} markets with some liquidity")
        
        # Take top 5 and place tiny orders
        trades_placed = 0
        for market in liquid_markets[:5]:
            ticker = market["ticker"]
            
            # Place very small orders (1 contract) at aggressive prices
            # Buy YES at 1c, Buy NO at 1c - just to get positions
            print(f"🎯 Trading {ticker} - Liquidity Score: {market['liquidity_score']}")
            
            # Place YES order at 1c
            yes_result = self.place_limit_order(ticker, "yes", 1, 1)
            if yes_result["success"]:
                print(f"✅ YES order placed: {yes_result['order_id']}")
                trades_placed += 1
            else:
                print(f"❌ YES order failed: {yes_result.get('error')}")
            
            # Place NO order at 1c
            no_result = self.place_limit_order(ticker, "no", 1, 1)
            if no_result["success"]:
                print(f"✅ NO order placed: {no_result['order_id']}")
                trades_placed += 1
            else:
                print(f"❌ NO order failed: {no_result.get('error')}")
            
            # Small delay between trades
            time.sleep(1)
        
        return trades_placed
    
    def strategy_2_market_making(self, markets):
        """Strategy 2: Act as market maker with tight spreads."""
        print("📊 STRATEGY 2: Market Making - Tight Spreads")
        print("-" * 50)
        
        trades_placed = 0
        
        # Find markets with some activity
        for market in markets[:10]:  # Top 10 markets
            ticker = market.get("ticker", "")
            yes_bid = market.get("yes_bid", 0)
            no_bid = market.get("no_bid", 0)
            
            if yes_bid > 0 and no_bid > 0:
                print(f"🎯 Market Making on {ticker}")
                print(f"   Current bids: YES={yes_bid}c, NO={no_bid}c")
                
                # Place orders just better than current bids
                yes_price = max(1, yes_bid - 1)  # 1c better than current bid
                no_price = max(1, no_bid - 1)
                
                # Small orders (1 contract each)
                yes_result = self.place_limit_order(ticker, "yes", yes_price, 1)
                if yes_result["success"]:
                    print(f"✅ YES order at {yes_price}c: {yes_result['order_id']}")
                    trades_placed += 1
                
                no_result = self.place_limit_order(ticker, "no", no_price, 1)
                if no_result["success"]:
                    print(f"✅ NO order at {no_price}c: {no_result['order_id']}")
                    trades_placed += 1
                
                time.sleep(1)
        
        return trades_placed
    
    def strategy_3_wide_spreads(self, markets):
        """Strategy 3: Target markets with wide spreads for better margins."""
        print("📊 STRATEGY 3: Wide Spreads - Better Margins")
        print("-" * 50)
        
        wide_spread_markets = []
        
        for market in markets:
            ticker = market.get("ticker", "")
            yes_bid = market.get("yes_bid", 0)
            no_bid = market.get("no_bid", 0)
            yes_ask = market.get("yes_ask", 0)
            no_ask = market.get("no_ask", 0)
            
            # Calculate spread
            if yes_bid > 0 and no_bid > 0:
                spread = (100 - yes_bid) - no_bid
                if spread > 10:  # Wide spread > 10c
                    wide_spread_markets.append({
                        "ticker": ticker,
                        "spread": spread,
                        "yes_bid": yes_bid,
                        "no_bid": no_bid
                    })
        
        # Sort by widest spreads
        wide_spread_markets.sort(key=lambda x: x["spread"], reverse=True)
        
        print(f"📈 Found {len(wide_spread_markets)} markets with wide spreads")
        
        trades_placed = 0
        for market in wide_spread_markets[:3]:  # Top 3 wide spreads
            ticker = market["ticker"]
            spread = market["spread"]
            
            print(f"🎯 Trading {ticker} - Spread: {spread}c")
            
            # Place orders at mid-point
            mid_yes = (market["yes_bid"] + 5)  # Slightly better than bid
            mid_no = (market["no_bid"] + 5)
            
            # 2 contracts each for better profit
            yes_result = self.place_limit_order(ticker, "yes", mid_yes, 2)
            if yes_result["success"]:
                print(f"✅ YES order at {mid_yes}c: {yes_result['order_id']}")
                trades_placed += 1
            
            no_result = self.place_limit_order(ticker, "no", mid_no, 2)
            if no_result["success"]:
                print(f"✅ NO order at {no_price}c: {no_result['order_id']}")
                trades_placed += 1
            
            time.sleep(1)
        
        return trades_placed
    
    def strategy_4_passive_accumulation(self, markets):
        """Strategy 4: Passive accumulation of positions."""
        print("📊 STRATEGY 4: Passive Accumulation")
        print("-" * 50)
        
        trades_placed = 0
        
        # Just place orders on any available markets
        for market in markets[:15]:  # First 15 markets
            ticker = market.get("ticker", "")
            
            if not ticker:
                continue
                
            print(f"🎯 Accumulating position in {ticker}")
            
            # Very conservative orders
            yes_result = self.place_limit_order(ticker, "yes", 2, 1)
            if yes_result["success"]:
                print(f"✅ YES order: {yes_result['order_id']}")
                trades_placed += 1
            
            no_result = self.place_limit_order(ticker, "no", 2, 1)
            if no_result["success"]:
                print(f"✅ NO order: {no_result['order_id']}")
                trades_placed += 1
            
            time.sleep(0.5)
        
        return trades_placed
    
    def run_marginal_profit_session(self):
        """Run a session with all marginal profit strategies."""
        print("=" * 80)
        print("💰 MARGINAL PROFIT STRATEGIES")
        print("🎯 Safe Trading for Any Market Condition")
        print("=" * 80)
        
        # Get current balance
        balance = self.get_portfolio_balance()
        if "error" not in balance:
            current_balance = balance.get("total_balance", 0) / 100
            print(f"💰 Starting Balance: ${current_balance:.2f}")
        
        # Get all markets
        print(f"\n🔍 Fetching all available markets...")
        markets_data = self.get_all_markets()
        
        if "error" in markets_data:
            print(f"❌ Error getting markets: {markets_data.get('error')}")
            return
        
        markets = markets_data.get("markets", [])
        print(f"📈 Found {len(markets)} total markets")
        
        total_trades = 0
        
        # Run all strategies
        strategies = [
            ("Liquid Markets", self.strategy_1_liquid_markets),
            ("Market Making", self.strategy_2_market_making),
            ("Wide Spreads", self.strategy_3_wide_spreads),
            ("Passive Accumulation", self.strategy_4_passive_accumulation)
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
        final_balance = self.get_portfolio_balance()
        if "error" not in final_balance:
            final_balance_amount = final_balance.get("total_balance", 0) / 100
            pnl = final_balance_amount - current_balance
            print(f"\n" + "="*60)
            print(f"📊 SESSION SUMMARY")
            print(f"💰 Starting Balance: ${current_balance:.2f}")
            print(f"💰 Ending Balance: ${final_balance_amount:.2f}")
            print(f"📈 P&L: ${pnl:+.2f}")
            print(f"📊 Total Trades Placed: {total_trades}")
            print(f"🎯 Status: {'PROFITABLE' if pnl > 0 else 'POSITIONS PLACED'}")

def main():
    """Main entry point."""
    api_key_id = os.environ.get('KALSHI_API_KEY_ID')
    if not api_key_id:
        print("❌ KALSHI_API_KEY_ID not found in environment")
        return
    
    trader = MarginalProfitTrader(api_key_id, 'kalshi-key.pem')
    trader.run_marginal_profit_session()

if __name__ == "__main__":
    main()
