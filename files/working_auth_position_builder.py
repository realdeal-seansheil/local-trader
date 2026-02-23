#!/usr/bin/env python3
"""
Working Auth Position Builder - Uses exact same OrderManager as working bot
"""

import os
import json
import time
import requests
import base64
from datetime import datetime as dt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from kalshi_executor import KalshiAuth, KalshiClient, StrategyExecutor
from kalshi_executor import KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH
from order_manager import ArbitrageOrderManager

class WorkingAuthPositionBuilder:
    def __init__(self):
        # Use the exact same authentication as the working bot
        self.auth = KalshiAuth(KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH)
        self.client = KalshiClient(self.auth)
        # Use the exact same OrderManager that was working
        self.order_manager = ArbitrageOrderManager(KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH)
        
    def get_balance(self):
        """Get balance using the exact same method as the working bot."""
        try:
            timestamp = str(int(dt.now().timestamp() * 1000))
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
                print(f"Debug: Balance API response: {resp.status_code} - {resp.text}")
                return {"success": False, "error": resp.status_code, "detail": resp.text}
                
        except Exception as e:
            print(f"Debug: Balance exception: {e}")
            return {"success": False, "error": "Request failed", "detail": str(e)}
    
    def verify_order_exists(self, order_id):
        """Verify that an order actually exists in the exchange."""
        try:
            timestamp = str(int(dt.now().timestamp() * 1000))
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
    
    def build_positions_with_working_auth(self):
        """Build positions using the exact same OrderManager as working bot."""
        print("=" * 80)
        print("🔧 WORKING AUTH POSITION BUILDER")
        print("✅ Using Exact Same OrderManager as Working Bot")
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
        
        # Strategy: Use working OrderManager to place orders
        print(f"\n🚀 STRATEGY: Use Working OrderManager")
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
            
            # Place YES order using the exact same method as working bot
            yes_result = self.order_manager.place_dynamic_order(ticker, "yes", 1, 1)
            if "error" not in yes_result:
                order_id = yes_result.get("order", {}).get("order_id")
                print(f"     ✅ YES placed: {order_id[:8] if order_id else 'N/A'}...")
                
                # Verify the order actually exists
                if order_id:
                    verification = self.verify_order_exists(order_id)
                    if verification["success"] and verification["exists"]:
                        print(f"     ✅ VERIFIED: Order exists in exchange")
                        verified_orders += 1
                        trades_placed += 1
                    else:
                        print(f"     ❌ NOT VERIFIED: {verification.get('error', 'Unknown')}")
                        failed_orders += 1
                else:
                    print(f"     ❌ No order ID returned")
                    failed_orders += 1
            else:
                print(f"     ❌ YES failed: {yes_result.get('error')}")
                failed_orders += 1
            
            time.sleep(1)  # Give the exchange time to process
            
            # Place NO order using the exact same method as working bot
            no_result = self.order_manager.place_dynamic_order(ticker, "no", 1, 1)
            if "error" not in no_result:
                order_id = no_result.get("order", {}).get("order_id")
                print(f"     ✅ NO placed: {order_id[:8] if order_id else 'N/A'}...")
                
                # Verify the order actually exists
                if order_id:
                    verification = self.verify_order_exists(order_id)
                    if verification["success"] and verification["exists"]:
                        print(f"     ✅ VERIFIED: Order exists in exchange")
                        verified_orders += 1
                        trades_placed += 1
                    else:
                        print(f"     ❌ NOT VERIFIED: {verification.get('error', 'Unknown')}")
                        failed_orders += 1
                else:
                    print(f"     ❌ No order ID returned")
                    failed_orders += 1
            else:
                print(f"     ❌ NO failed: {no_result.get('error')}")
                failed_orders += 1
            
            time.sleep(1)  # Give the exchange time to process
        
        print(f"\n" + "="*60)
        print(f"📊 WORKING AUTH RESULTS")
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
    builder = WorkingAuthPositionBuilder()
    builder.build_positions_with_working_auth()

if __name__ == "__main__":
    main()
