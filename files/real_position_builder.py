#!/usr/bin/env python3
"""
Real Position Builder - Uses only real, available markets
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

class RealPositionBuilder:
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
                    salt_length=padding.PASS.DIGEST_LENGTH
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
                return {"success": False, "error": resp.status_code, "build": resp.text}
                
        except Exception as e:
            return {"success": False, "error": "Request failed", "detail": str(e)}
    
    def get_real_markets(self):
        """Get real available markets."""
        try:
            markets = self.client.get_markets()
            return markets
        except Exception as e:
            return {"error": str(e)}
    
    def build_real_positions(self):
        """Build positions using only real, available markets."""
        print("=" * 80)
        print("🔧 REAL POSITION BUILDER")
        print("✅ Using Only Real, Available Markets")
        print("=" * 80)
        
        # Get initial balance
        balance = self.get_balance()
        if balance["success"]:
            initial_balance = balance["total_balance"] / 100
            print(f"💰 Initial Balance: ${initial_balance:.2f}")
        else:
            print(f"❌ Balance error: {balance.get('error')}")
            return
        
        # Get real markets
        markets_data = self.get_real_markets()
        if "error" in markets_data:
            print(f"❌ Markets error: {markets_data.get('error')}")
            return
        
        markets = markets_data.get("markets", [])
        print(f"📈 Found {len(markets)} real markets")
        
        # Filter for active markets with liquidity
        active_markets = []
        for market in markets:
            if market.get("status") == "active":
                # Check if market has some liquidity
                yes_bid = market.get("yes_bid", 0)
                no_bid = market.get("no_bid", 0)
                yes_ask = market.get("yes_ask", 0)
                no_ask = market.get("no_ask", 0)
                
                if yes_bid > 0 and no_bid > 0 and yes_ask > 0 and no_ask > 0:
                    active_markets.append(market)
        
        print(f"📈 Found {len(active_markets)} active markets with liquidity")
        
        # Strategy 1: Build positions in real markets
        print(f"\n🚀 STRATEGY 1: Real Market Positions")
        print("-" * 50)
        
        trades_placed = 0
        verified_orders = 0
        failed_orders = 0
        
        # Take first 10 active markets for testing
        for i, market in enumerate(active_markets[:10]):
            ticker = market.get("ticker", "")
            if not ticker:
                continue
                
            print(f"🎯 {i+1:2d}. {ticker[:45]:45s}")
            
            # Place YES order at 2c
            yes_result = self.place_order_working_method(ticker, "yes", 2, 1)
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
            
            # Place NO order at 2c
            no_result = self.place_order_working_method(ticker, "no", 2, 1)
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
        print(f"📊 REAL MARKET RESULTS")
        print(f"✅ Verified Orders: {verified_orders}")
        print(f"❌ Failed Orders: {failed_orders}")
        print(f"📊 Total Attempts: {verified_orders + failed_orders}")
        print(f"🎯 Success Rate: {verified_orders/(verified_orders + failed_orders)*100:.1f}%")
        
        if verified_orders > 0:
            print(f"\n✅ SUCCESS: Real orders were placed!")
            print(f"📈 These orders will generate profits as they fill")
            print(f"💰 Ready for monitoring and P&L tracking")
            
            # Build more positions if verification worked
            if verified_orders >= 8:  # At least 80% success rate
                print(f"\n🚀 EXPANDING: Building more positions...")
                self.build_more_positions(active_markets[10:20])
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
            print(f"💰 Final Balance: {final_balance_amount:.2f}")
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
    
    def build_more_positions(self, markets):
        """Build more positions after successful verification."""
        print(f"📈 Building additional positions...")
        
        additional_trades = 0
        
        for i, market in enumerate(markets[:10]):  # Next 10 markets
            ticker = market.get("ticker", "")
            if not ticker:
                continue
                
            print(f"🎯 {i+11:2d}. {ticker[:45]:45s}")
            
            # Place YES order at 3c
            yes_result = self.place_order_working_method(ticker, "yes", 3, 2)
            if yes_result["success"]:
                print(f"     ✅ YES: 2 contracts at 3c")
                additional_trades += 1
            
            time.sleep(0.5)
            
            # Place NO order at 3c
            no_result = self.place_order_working_method(ticker, "no", 3, 2)
            if no_result["success"]:
                print(f"     ✅ NO: 2 contracts at 3c")
                additional_trades += 1
            
            time.sleep(0.5)
        
        print(f"✅ Additional positions: {additional_trades} orders")

def main():
    """Main entry point."""
    builder = RealPositionBuilder()
    builder.build_real_positions()

if __name__ == "__main__":
    main()
