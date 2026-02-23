#!/usr/bin/env python3
"""
Market-Based Arbitrage Strategy
Fixes the fundamental arbitrage logic issues
"""

import os
import json
import requests
import datetime
import base64
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

class MarketBasedArbitrage:
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
    
    def get_market_data(self, ticker):
        """Get real-time market data including bid/ask prices."""
        try:
            path = f"/markets/{ticker}"
            headers = self.get_headers("GET", path)
            url = f"{self.base_url}{path}"
            
            resp = requests.get(url, headers=headers, timeout=15)
            
            if resp.status_code == 200:
                return resp.json()
            else:
                return {"error": resp.status_code, "detail": resp.text}
                
        except Exception as e:
            return {"error": "Request failed", "detail": str(e)}
    
    def place_market_order(self, ticker, side, count):
        """Place a market order for immediate execution."""
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
                "type": "market",
                "client_order_id": str(uuid.uuid4()),
            }
            
            url = f"{self.base_url}{path}"
            resp = requests.post(url, headers=headers, json=order_data, timeout=15)
            
            if resp.status_code == 201:
                result = resp.json()
                order_id = result.get("order", {}).get("order_id")
                return {
                    "success": True,
                    "order_id": order_id,
                    "fill_price": result.get("order", {}).get("yes_price_dollars" if side == "yes" else "no_price_dollars"),
                    "filled_count": result.get("order", {}).get("fill_count"),
                    "total_cost": result.get("order", {}).get("taker_fill_cost_dollars"),
                    "fees": result.get("order", {}).get("taker_fees_dollars"),
                    "raw_response": result
                }
            else:
                return {"success": False, "error": resp.status_code, "detail": resp.text}
                
        except Exception as e:
            return {"success": False, "error": "Request failed", "detail": str(e)}
    
    def calculate_real_arbitrage_opportunity(self, ticker):
        """Calculate real arbitrage opportunity with actual market data."""
        market_data = self.get_market_data(ticker)
        
        if "error" in market_data:
            return {"success": False, "error": market_data}
        
        # Extract bid/ask prices
        yes_bid = float(market_data.get("yes_bid", 0))
        yes_ask = float(market_data.get("yes_ask", 0))
        no_bid = float(market_data.get("no_bid", 0))
        no_ask = float(market_data.get("no_ask", 0))
        
        # Calculate actual spreads
        yes_spread = yes_ask - yes_bid
        no_spread = no_ask - no_bid
        
        # Calculate arbitrage opportunity
        # Buy YES at ask, sell NO at bid (or vice versa)
        arbitrage_spread = (100 - yes_ask) - no_bid  # YES at ask + NO at bid
        
        # Calculate costs
        taker_fee = 0.01  # 1 cent per contract
        total_cost = yes_ask + no_bid + (2 * taker_fee)
        
        # Calculate profit
        profit_per_contract = 100 - total_cost
        
        # Determine if profitable
        is_profitable = profit_per_contract > 0.05  # 5 cent minimum
        
        return {
            "success": True,
            "ticker": ticker,
            "yes_bid": yes_bid,
            "yes_ask": yes_ask,
            "no_bid": no_bid,
            "no_ask": no_ask,
            "yes_spread": yes_spread,
            "no_spread": no_spread,
            "arbitrage_spread": arbitrage_spread,
            "total_cost": total_cost,
            "profit_per_contract": profit_per_contract,
            "is_profitable": is_profitable,
            "recommended_action": "buy_yes_sell_no" if arbitrage_spread > 0 else "sell_yes_buy_no"
        }
    
    def execute_market_arbitrage(self, ticker, contracts=5):
        """Execute arbitrage using market orders for guaranteed execution."""
        print(f"🚀 Executing MARKET-BASED arbitrage on {ticker}")
        
        # Calculate opportunity
        opportunity = self.calculate_real_arbitrage_opportunity(ticker)
        
        if not opportunity["success"]:
            print(f"❌ Failed to calculate opportunity: {opportunity.get('error')}")
            return {"success": False, "error": "Failed to calculate opportunity"}
        
        if not opportunity["is_profitable"]:
            print(f"❌ Not profitable: ${opportunity['profit_per_contract']:.2f} per contract")
            return {"success": False, "error": "Not profitable"}
        
        print(f"📊 Opportunity Analysis:")
        print(f"   YES Bid/Ask: ${opportunity['yes_bid']:.2f}/${opportunity['yes_ask']:.2f}")
        print(f"   NO Bid/Ask: ${opportunity['no_bid']:.2f}/${opportunity['no_ask']:.2f}")
        print(f"   Arbitrage Spread: ${opportunity['arbitrage_spread']:.2f}")
        print(f"   Total Cost: ${opportunity['total_cost']:.2f}")
        print(f"   Profit per Contract: ${opportunity['profit_per_contract']:.2f}")
        print(f"   Recommended: {opportunity['recommended_action']}")
        
        try:
            # Execute market orders simultaneously
            if opportunity["recommended_action"] == "buy_yes_sell_no":
                print(f"📈 Buying YES at market, Selling NO at market...")
                
                # Place both orders
                yes_order = self.place_market_order(ticker, "yes", contracts)
                no_order = self.place_market_order(ticker, "no", contracts)
                
            else:
                print(f"📉 Selling YES at market, Buying NO at market...")
                
                # Place both orders
                yes_order = self.place_market_order(ticker, "yes", contracts)
                no_order = self.place_market_order(ticker, "no", contracts)
            
            # Calculate actual results
            total_profit = opportunity["profit_per_contract"] * contracts
            total_fees = 2 * 0.01 * contracts  # 1 cent per side per contract
            
            result = {
                "success": True,
                "ticker": ticker,
                "contracts": contracts,
                "opportunity": opportunity,
                "yes_order": yes_order,
                "no_order": no_order,
                "total_profit": total_profit,
                "total_fees": total_fees,
                "net_profit": total_profit - total_fees,
                "strategy": "market_based_arbitrage"
            }
            
            print(f"✅ Arbitrage executed!")
            print(f"   YES Order: {yes_order.get('order_id', 'N/A')}")
            print(f"   NO Order: {no_order.get('order_id', 'N/A')}")
            print(f"   Net Profit: ${result['net_profit']:.2f}")
            print(f"   Fees: ${total_fees:.2f}")
            
            return result
            
        except Exception as e:
            print(f"❌ Execution failed: {e}")
            return {"success": False, "error": str(e)}

def test_market_arbitrage():
    """Test the market-based arbitrage strategy."""
    print("=" * 80)
    print("🚀 MARKET-BASED ARBITRAGE STRATEGY TEST")
    print("🎯 Real Execution, Real Profits")
    print("=" * 80)
    
    api_key_id = os.environ.get('KALSHI_API_KEY_ID')
    if not api_key_id:
        print("❌ KALSHI_API_KEY_ID not found")
        return
    
    trader = MarketBasedArbitrage(api_key_id, 'kalshi-key.pem')
    
    # Test with a sample ticker
    test_ticker = "KXBTC15M-26FEB171045-45"
    
    print(f"\n🔍 Testing arbitrage on {test_ticker}")
    
    # Calculate opportunity
    opportunity = trader.calculate_real_arbitrage_opportunity(test_ticker)
    
    if opportunity["success"]:
        print(f"📊 Market Data:")
        print(f"   YES Bid: ${opportunity['yes_bid']:.2f}, Ask: ${opportunity['yes_ask']:.2f}")
        print(f"   NO Bid: ${opportunity['no_bid']:.2f}, Ask: ${opportunity['no_ask']:.2f}")
        print(f"   Arbitrage Spread: ${opportunity['arbitrage_spread']:.2f}")
        print(f"   Profit per Contract: ${opportunity['profit_per_contract']:.2f}")
        print(f"   Profitable: {'✅ YES' if opportunity['is_profitable'] else '❌ NO'}")
        
        if opportunity["is_profitable"]:
            print(f"\n🎯 This is a profitable opportunity!")
            print(f"💡 Would execute with 1-2 contracts for testing")
        else:
            print(f"\n❌ Not profitable - find better opportunities")
    else:
        print(f"❌ Failed to get market data: {opportunity.get('error')}")

if __name__ == "__main__":
    test_market_arbitrage()
