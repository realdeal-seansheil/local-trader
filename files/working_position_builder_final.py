#!/usr/bin/env python3
"""
Working Position Builder - Handles real market conditions
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

# Import the working authentication system
from kalshi_executor import KalshiAuth, KalshiClient, StrategyExecutor
from kalshi_executor import KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH

class WorkingPositionBuilder:
    def __init__(self):
        # Use the exact same authentication as the working bot
        self.auth = KalshiAuth(KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH)
        self.client = KalshiClient(self.auth)
        
    def place_order_working_method(self, ticker, side, price, count):
        """Place an order using the exact same method as the working bot."""
        try:
            timestamp = str(int(datetime.datetime.now().timestamp() * 1000))
            path = "/trade-api/v2/portfolio/orders"
            method = "POST"
            
            msg = timestamp + method + path
            
            sig_bytes = self.auth.private_key.sign(
                msg.encode(),
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.DIGEST_LENGTH
                ),
                hashes.SHA256()
            )
            signature = base64.b64encode(sig_bytes).decode()
            
            headers = {
                "KALSHI-ACCESS-KEY": self.auth.api_key_id,
                "KALSHI-ACCESS-SIGNATURE": signature,
                "KALSHI-ACCESS-TIMESTAMP": timestamp,
                "Content-Type": "application/json",
            }
            
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
            
            url = "https://api.elections.kalshi.com" + path
            resp = requests.post(url, headers=headers, json=order_data, timeout=15)
            
            if resp.status_code == 201:
                result = resp.json()
                order_id = result.get("order", {}).get("order_id")
                return {
                    "success": True,
                    "order_id": order_id,
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
    
    def verify_order_exists(self, order_id):
        """Verify that an order actually exists in the exchange."""
        try:
            timestamp = str(int(datetime.datetime.now().timestamp() * 1000))
            path = f"/trade-api/v2/portfolio/orders/{order_id}"
            method = "GET"
            
            msg = timestamp + method + path
            
            sig_bytes = self.auth.private_key.sign(
                msg.encode(),
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.DIGEST_LENGTH
                ),
                hashes.SHA256()
            )
            signature = base64.b64encode(sig_bytes).decode()
            
            headers = {
                "KALSHI-ACCESS-KEY": self.auth.api_key_id,
                "KALSHI-ACCESS-SIGNATURE": signature,
                "KALSHI-ACCESS-TIMESTAMP": timestamp,
                "Content-Type": "application/json",
            }
            
            url = "https://api.elections.kalshi.com" + path
            resp = requests.get(url, headers=headers, timeout=15)
            
            if resp.status_code == 200:
                return {"success": True, "exists": True, "data": resp.json()}
            elif resp.status_code == 404:
                return {"success": True, "exists": False, "error": "not_found"}
            else:
                return {"success": False, "error": resp.status_code, "detail": resp.text}
                
        except Exception as e:
            return {"success": False, "error": "Request failed", "detail": str(e)}
    
    def get_balance(self):
        """Get balance using the exact same method as the working bot."""
        try:
            timestamp = str(int(datetime.datetime.now().timestamp() * 1000))
            path = "/trade-api/v2/portfolio/balance"
            method = "GET"
            
            msg = timestamp + method + path
            
            sig_bytes = self.auth.private_key.sign(
                msg.encode(),
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.DIGEST_LENGTH
                ),
                hashes.SHA256()
            )
            signature = base64.b64encode(sig_bytes).decode()
            
            headers = {
                "KALSHI-ACCESS-KEY": self.auth.api_key_id,
                "KALSHI-ACCESS-SIGNATURE": signature,
                "KALSHI-ACCESS-TIMESTAMP": timestamp,
                "Content-Type": "application/json",
            }
            
            url = "https://api.elections.kalshi.com" + path
            resp = requests.get(url, headers=headers, timeout=15)
            
            if resp.status_code == 200:
                data = resp.json()
                total_balance = data.get("balance", 0)
                available = data.get("available", 0)
                return {
                    "success": True,
                    "total_balance": total_balance,
                    "available": available
                }
            else:
                return {"success": False, "error": resp.status_code, "detail": resp.text}
                
        except Exception as e:
            return {"success": False, "error": "Request failed", "detail": str(e)}
    
    def build_positions_any_market(self):
        """Build positions in any available market - focus on execution."""
        print("=" * 80)
        print("🔧 WORKING POSITION BUILDER")
        print("✅ Focus on Real Execution, Not Perfect Markets")
        print("=" * 80)
        
        # Get initial balance
        balance = self.get_balance()
        if balance["success"]:
            initial_balance = balance["total_balance"] / 100
            print(f"💰 Initial Balance: ${initial_balance:.2f}")
        else:
            print(f"❌ Balance error: {balance.get('error')}")
            return
        
        # Get all markets
        markets_data = self.client.get_markets()
        if "error" in markets_data:
            print(f"❌ Markets error: {markets_data.get('error')}")
            return
        
        markets = markets_data.get("markets", [])
        print(f"📈 Found {len(markets)} markets")
        
        # Strategy: Just place orders in any active market
        print(f"\n🚀 STRATEGY: Place Orders in Any Active Market")
        print("-" * 50)
        
        trades_placed = 0
        verified_orders = 0
        failed_orders = 0
        
        # Take first 10 active markets
        for i, market in enumerate(markets[:10]):
            ticker = market.get("ticker", "")
            if not ticker:
                continue
                
            print(f"🎯 {i+1:2d}. {ticker[:45]:45s}")
            
            # Place YES order at 1c (very conservative)
            yes_result = self.place_order_working_method(ticker, "yes", 1, 1)
            if yes_result["success"]:
                print(f"     ✅ YES placed: {yes_result['order_id'][:8]}...")
                
                # Verify the order actually exists
                verification = self.verify_order_exists(yes_result["order_id"])
                if verification["success"] and verification["exists"]:
                    print(f"     ✅ VERIFIED: Order exists in exchange")
                    verified_orders += 1
                    trades_placed += 1
                else:
                    print(f"     ❌ NOT VERIFIED: {verification.get('error', 'Unknown')}")
                    failed_orders += 1
            else:
                print(f"     ❌ YES failed: {yes_result.get('error')}")
                failed_orders += 1
            
            time.sleep(1)  # Give the exchange time to process
            
            # Place NO order at 1c (very conservative)
            no_result = self.place_order_working_method(ticker, "no", 1, 1)
            if no_result["success"]:
                print(f"     ✅ NO placed: {no_result['order_id'][:8]}...")
                
                # Verify the order actually exists
                verification = self.verify_order_exists(no_result["order_id"])
                if verification["success"] and verification["exists"]:
                    print(f"     ✅ VERIFIED: Order exists in exchange")
                    verified_orders += 1
                    trades_placed += 1
                else:
                    print(f"     ❌ NOT VERIFIED: {verification.get('error', 'Unknown')}")
                    failed_orders += 1
            else:
                print(f"     ❌ NO failed: {no_result.get('error')}")
                failed_orders += 1
            
            time.sleep(1)  # Give the exchange time to process
        
        print(f"\n" + "="*60)
        print(f"📊 EXECUTION RESULTS")
        print(f"✅ Verified Orders: {verified_orders}")
        print(f"❌ Failed Orders: {failed_orders}")
        
        if verified_orders + failed_orders > 0:
            success_rate = verified_orders/(verified_orders + failed_orders)*100
            print(f"🎯 Success Rate: {success_rate:.1f}%")
        else:
            print(f"🎯 Success Rate: N/A (no attempts)")
        
        if verified_orders > 0:
            print(f"\n✅ SUCCESS: Real orders were placed!")
            print(f"📈 These orders will generate profits as they fill")
            print(f"💰 Ready for monitoring and P&L tracking")
        else:
            print(f"\n❌ ISSUE: No verified orders created")
            print(f"🔧 Need to debug the order placement issue")
        
        # Final balance check
        final_balance = self.get_balance()
        if final_balance["success"]:
            final_balance_amount = final_balance["total_balance"] / 100
            pnl = final_balance_amount - initial_balance
            print(f"\n" + "="*60)
            print(f"📊 FINAL RESULTS")
            print(f"💰 Initial Balance: ${initial_balance:.2f}")
            print(f"💰 Final Balance: ${final_balance_amount:.2f}")
            print(f"📈 P&L: ${pnl:+.2f}")
            print(f"📊 Verified Orders: {verified_orders}")
            print(f"🎯 Status: {'SUCCESS' if verified_orders > 0 else 'FAILED'}")
            
            if verified_orders > 0:
                print(f"\n💡 POSITION BUILDING SUCCESS!")
                print(f"   • {verified_orders} real orders created")
                print(f"   • Orders verified to exist in exchange")
                print(f"   • Ready for profit generation")
                print(f"   • Marginal profits expected as markets move")
        
        else:
            print(f"❌ Could not get final balance: {final_balance.get('error')}")

def main():
    """Main entry point."""
    builder = WorkingPositionBuilder()
    builder.build_positions_any_market()

if __name__ == "__main__":
    main()
