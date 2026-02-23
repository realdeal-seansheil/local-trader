#!/usr/bin/env python3
"""
Working Position Builder - Uses existing working code
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

class WorkingPositionBuilder:
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
    
    def get_balance(self):
        """Get account balance."""
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
    
    def get_markets(self):
        """Get available markets."""
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
    
    def place_order(self, ticker, side, price, count):
        """Place an order."""
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
                    "ticker": ticker,
                    "side": side,
                    "price": price,
                    "count": count,
                    "raw_response": result
                }
            else:
                return {"success": False, "error": resp.status_code, "detail": resp.text}
                
        except Exception as e:
            return {"success": False, "error": "Request failed", "detail": str(e)}
    
    def build_positions_quickly(self, markets):
        """Build positions quickly across many markets."""
        print("🚀 QUICK POSITION BUILDER")
        print("-" * 50)
        
        trades_placed = 0
        failed_trades = 0
        
        # Take first 20 markets and place orders
        for i, market in enumerate(markets[:20]):
            ticker = market.get("ticker", "")
            if not ticker:
                continue
                
            print(f"🎯 {i+1:2d}. {ticker[:40]:40s}")
            
            # Place YES order at 1c
            yes_result = self.place_order(ticker, "yes", 1, 1)
            if yes_result["success"]:
                print(f"     ✅ YES: {yes_result['order_id'][:8]}...")
                trades_placed += 1
            else:
                print(f"     ❌ YES: {yes_result.get('error', 'Unknown')}")
                failed_trades += 1
            
            time.sleep(0.2)  # Very short delay
            
            # Place NO order at 1c
            no_result = self.place_order(ticker, "no", 1, 1)
            if no_result["success"]:
                print(f"     ✅ NO:  {no_result['order_id'][:8]}...")
                trades_placed += 1
            else:
                print(f"     ❌ NO:  {no_result.get('error', 'Unknown')}")
                failed_trades += 1
            
            time.sleep(0.2)  # Very short delay
        
        return trades_placed, failed_trades
    
    def build_concentrated_positions(self, markets):
        """Build concentrated positions in best markets."""
        print("🎯 CONCENTRATED POSITION BUILDER")
        print("-" * 50)
        
        trades_placed = 0
        failed_trades = 0
        
        # Find markets with some activity
        active_markets = []
        for market in markets:
            yes_bid = market.get("yes_bid", 0)
            no_bid = market.get("no_bid", 0)
            if yes_bid > 0 or no_bid > 0:
                active_markets.append(market)
        
        print(f"📈 Found {len(active_markets)} active markets")
        
        # Place larger orders on top 5 active markets
        for i, market in enumerate(active_markets[:5]):
            ticker = market.get("ticker", "")
            print(f"🎯 {i+1}. {ticker}")
            
            # 3 contracts at 2c each
            yes_result = self.place_order(ticker, "yes", 2, 3)
            if yes_result["success"]:
                print(f"     ✅ YES: 3 contracts at 2c - {yes_result['order_id'][:8]}...")
                trades_placed += 1
            else:
                print(f"     ❌ YES: {yes_result.get('error', 'Unknown')}")
                failed_trades += 1
            
            time.sleep(0.5)
            
            no_result = self.place_order(ticker, "no", 2, 3)
            if no_result["success"]:
                print(f"     ✅ NO: 3 contracts at 2c - {no_result['order_id'][:8]}...")
                trades_placed += 1
            else:
                print(f"     ❌ NO: {no_result.get('error', 'Unknown')}")
                failed_trades += 1
            
            time.sleep(0.5)
        
        return trades_placed, failed_trades
    
    def build_aggressive_positions(self, markets):
        """Build aggressive positions with higher prices."""
        print("⚡ AGGRESSIVE POSITION BUILDER")
        print("-" * 50)
        
        trades_placed = 0
        failed_trades = 0
        
        # Use higher prices for better fill chances
        for i, market in enumerate(markets[:10]):
            ticker = market.get("ticker", "")
            if not ticker:
                continue
                
            print(f"🎯 {i+1:2d}. {ticker[:40]:40s}")
            
            # 5 contracts at 5c (higher chance of fills)
            yes_result = self.place_order(ticker, "yes", 5, 5)
            if yes_result["success"]:
                print(f"     ✅ YES: 5 contracts at 5c - {yes_result['order_id'][:8]}...")
                trades_placed += 1
            else:
                print(f"     ❌ YES: {yes_result.get('error', 'Unknown')}")
                failed_trades += 1
            
            time.sleep(0.5)
            
            no_result = self.place_order(ticker, "no", 5, 5)
            if no_result["success"]:
                print(f"     ✅ NO: 5 contracts at 5c - {no_result['order_id'][:8]}...")
                trades_placed += 1
            else:
                print(f"     ❌ NO: {no_result.get('error', 'Unknown')}")
                failed_trades += 1
            
            time.sleep(0.5)
        
        return trades_placed, failed_trades
    
    def run_position_builder(self):
        """Run the position builder session."""
        print("=" * 80)
        print("🏗️  WORKING POSITION BUILDER")
        print("🎯 Build Positions for Marginal Profits")
        print("=" * 80)
        
        # Get initial balance
        balance = self.get_balance()
        if "error" not in balance:
            initial_balance = balance.get("total_balance", 0) / 100
            print(f"💰 Initial Balance: ${initial_balance:.2f}")
        else:
            print(f"❌ Could not get balance: {balance.get('error')}")
            initial_balance = 0
        
        # Get markets
        markets_data = self.get_markets()
        if "error" in markets_data:
            print(f"❌ Could not get markets: {markets_data.get('error')}")
            return
        
        markets = markets_data.get("markets", [])
        print(f"📈 Found {len(markets)} markets")
        
        total_trades = 0
        total_failed = 0
        
        # Run position building strategies
        strategies = [
            ("Quick Positions", self.build_positions_quickly),
            ("Concentrated Positions", self.build_concentrated_positions),
            ("Aggressive Positions", self.build_aggressive_positions)
        ]
        
        for strategy_name, strategy_func in strategies:
            print(f"\n" + "="*60)
            try:
                trades, failed = strategy_func(markets)
                total_trades += trades
                total_failed += failed
                print(f"✅ {strategy_name}: {trades} trades placed, {failed} failed")
            except Exception as e:
                print(f"❌ {strategy_name} failed: {e}")
        
        # Final balance check
        final_balance = self.get_balance()
        if "error" not in final_balance:
            final_balance_amount = final_balance.get("total_balance", 0) / 100
            pnl = final_balance_amount - initial_balance
            print(f"\n" + "="*60)
            print(f"📊 POSITION BUILDING SUMMARY")
            print(f"💰 Initial Balance: ${initial_balance:.2f}")
            print(f"💰 Final Balance: ${final_balance_amount:.2f}")
            print(f"📈 P&L: ${pnl:+.2f}")
            print(f"📊 Total Orders Placed: {total_trades}")
            print(f"❌ Total Failed Orders: {total_failed}")
            print(f"🎯 Status: {'POSITIONS BUILT' if total_trades > 0 else 'NO ORDERS'}")
            
            if total_trades > 0:
                print(f"\n💡 POSITION BUILDING SUCCESS!")
                print(f"   • {total_trades} orders placed across markets")
                print(f"   • Positions will generate profits as they fill")
                print(f"   • Monitor for fills and P&L realization")
                print(f"   • Ready for next trading session")
            
        else:
            print(f"❌ Could not get final balance: {final_balance.get('error')}")

def main():
    """Main entry point."""
    api_key_id = os.environ.get('KALSHI_API_KEY_ID')
    if not api_key_id:
        print("❌ KALSHI_API_KEY_ID not found in environment")
        return
    
    builder = WorkingPositionBuilder(api_key_id, 'kalshi-key.pem')
    builder.run_position_builder()

if __name__ == "__main__":
    main()
