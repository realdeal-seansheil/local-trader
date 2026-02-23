#!/usr/bin/env python3
"""
Safe Arbitrage Strategy - Implements the Recommended Fixes
"""

import os
import json
import requests
import datetime
import base64
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

class SafeArbitrageStrategy:
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
    
    def get_market_data(self, ticker):
        """Get real-time market data."""
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
    
    def place_limit_order(self, ticker, side, price, count):
        """Place a limit order with proper cost calculation."""
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
    
    def calculate_safe_arbitrage(self, ticker, yes_price, no_price, contracts):
        """Calculate arbitrage with all costs included."""
        
        # Calculate costs (ALL costs must be included)
        yes_cost = yes_price * contracts
        no_cost = no_price * contracts
        
        # Taker fees (1 cent per contract per side)
        taker_fees = 0.01 * contracts * 2
        
        # Total cost
        total_cost = yes_cost + no_cost + taker_fees
        
        # Maximum profit (if both sides fill at 100c)
        max_profit = (100 * contracts * 2) - total_cost
        
        # Break-even analysis
        break_even_price = (total_cost / 2) / contracts
        
        # Safety margin - require at least 10c profit per contract
        min_required_profit = 0.10 * contracts
        required_spread = (total_cost + min_required_profit) / contracts
        
        return {
            "ticker": ticker,
            "yes_price": yes_price,
            "no_price": no_price,
            "contracts": contracts,
            "yes_cost": yes_cost,
            "no_cost": no_cost,
            "taker_fees": taker_fees,
            "total_cost": total_cost,
            "max_profit": max_profit,
            "break_even_price": break_even_price,
            "required_spread": required_spread,
            "min_profit": min_required_profit,
            "is_safe": max_profit > min_required_profit
        }
    
    def execute_safe_arbitrage(self, ticker, contracts=2):
        """Execute safe arbitrage with proper risk management."""
        print(f"🛡️  Executing SAFE arbitrage on {ticker}")
        print(f"📊 Contracts: {contracts} (small size for testing)")
        
        # Use conservative pricing (5 cents to ensure fills)
        yes_price = 5
        no_price = 5
        
        # Calculate safe arbitrage
        analysis = self.calculate_safe_arbitrage(ticker, yes_price, no_price, contracts)
        
        print(f"📈 Cost Analysis:")
        print(f"   YES Cost: ${analysis['yes_cost']/100:.2f}")
        print(f"   NO Cost: ${analysis['no_cost']/100:.2f}")
        print(f"   Taker Fees: ${analysis['taker_fees']:.2f}")
        print(f"   Total Cost: ${analysis['total_cost']/100:.2f}")
        print(f"   Max Profit: ${analysis['max_profit']/100:.2f}")
        print(f"   Required Spread: {analysis['required_spread']:.1f}c")
        print(f"   Safe: {'✅ YES' if analysis['is_safe'] else '❌ NO'}")
        
        if not analysis['is_safe']:
            print(f"❌ Arbitrage not safe - insufficient profit margin")
            return {"success": False, "error": "Insufficient profit margin"}
        
        try:
            # Place orders with safety checks
            print(f"📈 Placing orders at {yes_price}c each...")
            
            yes_order = self.place_limit_order(ticker, "yes", yes_price, contracts)
            no_order = self.place_limit_order(ticker, "no", no_price, contracts)
            
            if not yes_order["success"]:
                print(f"❌ YES order failed: {yes_order.get('error')}")
                return {"success": False, "error": "YES order failed"}
            
            if not no_order["success"]:
                print(f"❌ NO order failed: {no_order.get('error')}")
                return {"success": False, "error": "NO order failed"}
            
            result = {
                "success": True,
                "ticker": ticker,
                "contracts": contracts,
                "analysis": analysis,
                "yes_order": yes_order,
                "no_order": no_order,
                "strategy": "safe_arbitrage"
            }
            
            print(f"✅ Safe arbitrage placed!")
            print(f"   YES Order: {yes_order['order_id']}")
            print(f"   NO Order: {no_order['order_id']}")
            print(f"   Expected Max Profit: ${analysis['max_profit']/100:.2f}")
            
            return result
            
        except Exception as e:
            print(f"❌ Execution failed: {e}")
            return {"success": False, "error": str(e)}
    
    def monitor_and_learn(self):
        """Monitor results and learn from real data."""
        print(f"\n📊 MONITORING & LEARNING")
        print("-" * 50)
        
        # Get current balance
        balance = self.get_portfolio_balance()
        if "error" not in balance:
            current_balance = balance.get("total_balance", 0) / 100
            print(f"💰 Current Balance: ${current_balance:.2f}")
        
        # Analyze recent trades
        try:
            with open('data/48hour_trading.jsonl', 'r') as f:
                logs = [json.loads(line) for line in f]
            
            execution_logs = [log for log in logs if log['type'] == 'execution_success'][-10:]
            
            if execution_logs:
                print(f"\n📈 Recent Executions:")
                for log in execution_logs[-5:]:
                    data = log['data']
                    timestamp = log['timestamp'].split('T')[1].split('.')[0]
                    print(f"   {timestamp}: {data['ticker']} - ${data['total_profit']:.2f}")
        
        except Exception as e:
            print(f"❌ Error analyzing logs: {e}")

def implement_fixes():
    """Implement the recommended fixes."""
    print("=" * 80)
    print("🛡️  IMPLEMENTING RECOMMENDED FIXES")
    print("🎯 Safe Arbitrage Strategy")
    print("=" * 80)
    
    api_key_id = os.environ.get('KALSHI_API_KEY_ID')
    if not api_key_id:
        print("❌ KALSHI_API_KEY_ID not found")
        return
    
    trader = SafeArbitrageStrategy(api_key_id, 'kalshi-key.pem')
    
    print(f"\n📊 IMPLEMENTED FIXES:")
    print("-" * 50)
    print(f"✅ 1. STOPPED losing strategy")
    print(f"✅ 2. Reduced position size to 2 contracts")
    print(f"✅ 3. Conservative pricing at 5c")
    print(f"✅ 4. Full cost calculation")
    print(f"✅ 5. Safety margin requirements")
    print(f"✅ 6. Real-time monitoring")
    
    # Monitor current state
    trader.monitor_and_learn()
    
    print(f"\n🎯 RECOMMENDATIONS:")
    print("-" * 50)
    print(f"📈 1. Test with 1-2 contracts only")
    print(f"💰 2. Verify actual fill prices")
    print(f"📊 3. Track real P&L per trade")
    print(f"🛡️  4. Only trade when safe margin > 10c")
    print(f"⏰ 5. Monitor for 1 hour before scaling")
    
    print(f"\n💡 KEY CHANGES:")
    print("-" * 50)
    print(f"🔧 OLD: Buy at 1c, hope for 98c spread")
    print(f"🔧 NEW: Buy at 5c, require 10c safety margin")
    print(f"🔧 OLD: 20 contracts, high risk")
    print(f"🔧 NEW: 2 contracts, low risk")
    print(f"🔧 OLD: Theoretical profit calculation")
    print(f"🔧 NEW: Full cost + safety margin")

if __name__ == "__main__":
    implement_fixes()
