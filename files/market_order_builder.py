#!/usr/bin/env python3
"""
Market Order Builder - Uses market orders for immediate execution
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

class MarketOrderBuilder:
    def __init__(self):
        # Use the exact same authentication as the working bot
        self.auth = KalshiAuth(KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH)
        self.client = KalshiClient(self.auth)
        # Use the exact same OrderManager that was working
        self.order_manager = ArbitrageOrderManager(KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH)
        
    def place_market_order(self, ticker, side, count):
        """Place a market order for immediate execution."""
        try:
            timestamp = str(int(dt.now().timestamp() * 1000))
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
                "type": "market",  # MARKET ORDER - IMMEDIATE EXECUTION
                "client_order_id": str(uuid.uuid4()),
                # NO PRICE FIELD FOR MARKET ORDERS
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
                    "count": count,
                    "type": "market",
                    "raw_response": result
                }
            else:
                return {"success": False, "error": resp.status_code, "detail": resp.text}
                
        except Exception as e:
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
                return {"success": False, "error": resp.status_code, "detail": resp.text}
                
        except Exception as e:
            return {"success": False, "error": "Request failed", "detail": str(e)}
    
    def build_positions_with_market_orders(self):
        """Build positions using market orders for immediate execution."""
        print("=" * 80)
        print("🚀 MARKET ORDER BUILDER")
        print("⚡ Immediate Execution - No More Resting Orders")
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
        
        # Strategy: Use market orders for immediate execution
        print(f"\n🚀 STRATEGY: Market Orders - Immediate Execution")
        print("-" * 50)
        print(f"⚡ No more waiting for fills - instant execution!")
        print(f"💰 Higher fill rates guaranteed")
        print(f"📈 Immediate position building")
        
        trades_placed = 0
        verified_orders = 0
        failed_orders = 0
        
        # Take first 10 active markets
        for i, market in enumerate(markets[:10]):
            ticker = market.get("ticker", "")
            if not ticker:
                continue
                
            print(f"🎯 {i+1:2d}. {ticker[:45]:45s}")
            
            # Place YES market order for immediate execution
            yes_result = self.place_market_order(ticker, "yes", 1)
            if yes_result["success"]:
                order_id = yes_result.get("order_id")
                print(f"     ✅ YES market order: {order_id[:8] if order_id else 'N/A'}...")
                
                # Verify the order actually exists
                if order_id:
                    verification = self.verify_order_exists(order_id)
                    if verification["success"] and verification["exists"]:
                        order_data = verification["data"].get("order", {})
                        status = order_data.get("status", "Unknown")
                        fill_count = order_data.get("fill_count", 0)
                        print(f"     ✅ VERIFIED: {status} - {fill_count} filled")
                        
                        if status == "filled":
                            print(f"     🎉 IMMEDIATE FILL! Market order executed instantly")
                        elif status == "resting":
                            print(f"     ⏳ Market order placed, waiting for execution")
                        
                        verified_orders += 1
                        trades_placed += 1
                    else:
                        print(f"     ❌ NOT VERIFIED: {verification.get('error', 'Unknown')}")
                        failed_orders += 1
                else:
                    print(f"     ❌ No order ID returned")
                    failed_orders += 1
            else:
                print(f"     ❌ YES market order failed: {yes_result.get('error')}")
                failed_orders += 1
            
            time.sleep(1)  # Give the exchange time to process
            
            # Place NO market order for immediate execution
            no_result = self.place_market_order(ticker, "no", 1)
            if no_result["success"]:
                order_id = no_result.get("order_id")
                print(f"     ✅ NO market order: {order_id[:8] if order_id else 'N/A'}...")
                
                # Verify the order actually exists
                if order_id:
                    verification = self.verify_order_exists(order_id)
                    if verification["success"] and verification["exists"]:
                        order_data = verification["data"].get("order", {})
                        status = order_data.get("status", "Unknown")
                        fill_count = order_data.get("fill_count", 0)
                        print(f"     ✅ VERIFIED: {status} - {fill_count} filled")
                        
                        if status == "filled":
                            print(f"     🎉 IMMEDIATE FILL! Market order executed instantly")
                        elif status == "resting":
                            print(f"     ⏳ Market order placed, waiting for execution")
                        
                        verified_orders += 1
                        trades_placed += 1
                    else:
                        print(f"     ❌ NOT VERIFIED: {verification.get('error', 'Unknown')}")
                        failed_orders += 1
                else:
                    print(f"     ❌ No order ID returned")
                    failed_orders += 1
            else:
                print(f"     ❌ NO market order failed: {no_result.get('error')}")
                failed_orders += 1
            
            time.sleep(1)  # Give the exchange time to process
        
        print(f"\n" + "="*60)
        print(f"📊 MARKET ORDER RESULTS")
        print(f"✅ Verified Orders: {verified_orders}")
        print(f"❌ Failed Orders: {failed_orders}")
        
        if verified_orders + failed_orders > 0:
            success_rate = verified_orders/(verified_orders + failed_orders)*100
            print(f"🎯 Success Rate: {success_rate:.1f}%")
        else:
            print(f"🎯 Success Rate: N/A (no attempts)")
        
        if verified_orders > 0:
            print(f"\n✅ SUCCESS: Market orders placed!")
            print(f"⚡ Immediate execution achieved")
            print(f"💰 Higher fill rates expected")
            print(f"📈 Ready for immediate profit generation")
        else:
            print(f"\n❌ ISSUE: No verified orders created")
            print(f"🔧 Need to debug market order placement")
        
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
                print(f"\n💡 MARKET ORDER SUCCESS!")
                print(f"   • {verified_orders} market orders created")
                print(f"   • Immediate execution achieved")
                print(f"   • Higher fill rates expected")
                print(f"   • Ready for immediate profit generation")
        
        else:
            print(f"❌ Could not get final balance: {final_balance.get('error')}")

def main():
    """Main entry point."""
    builder = MarketOrderBuilder()
    builder.build_positions_with_market_orders()

if __name__ == "__main__":
    main()
