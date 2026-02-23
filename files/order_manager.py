#!/usr/bin/env python3
"""
Advanced Order Manager
Handles order monitoring, dynamic pricing, and fill completion.
"""

import os
import json
import requests
import datetime
import base64
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

class OrderManager:
    def __init__(self, api_key_id, private_key_path):
        self.api_key_id = api_key_id
        self.private_key_path = private_key_path
        self.load_private_key()
        
    def load_private_key(self):
        """Load private key for API authentication."""
        try:
            with open(self.private_key_path, "rb") as f:
                self.private_key = serialization.load_pem_private_key(
                    f.read(), password=None
                )
        except Exception as e:
            print(f"❌ Failed to load private key: {e}")
            self.private_key = None
    
    def get_headers(self, method: str, path: str) -> dict:
        """Generate authenticated headers for API requests."""
        timestamp = str(int(datetime.datetime.now().timestamp() * 1000))
        path_without_query = path.split("?")[0]
        msg = timestamp + method.upper() + path_without_query

        if self.private_key:
            sig_bytes = self.private_key.sign(
                msg.encode(),
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.DIGEST_LENGTH
                ),
                hashes.SHA256()
            )
            signature = base64.b64encode(sig_bytes).decode()
        else:
            signature = ""

        return {
            "KALSHI-ACCESS-KEY": self.api_key_id,
            "KALSHI-ACCESS-SIGNATURE": signature,
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
            "Content-Type": "application/json",
        }
    
    def check_order_status(self, order_id: str) -> dict:
        """Check the status of a specific order."""
        try:
            timestamp = str(int(datetime.datetime.now().timestamp() * 1000))
            path = f"/trade-api/v2/portfolio/orders/{order_id}"
            method = "GET"
            
            headers = self.get_headers(method, path)
            url = f"https://api.elections.kalshi.com{path}"
            
            resp = requests.get(url, headers=headers, timeout=15)
            
            if resp.status_code == 200:
                return resp.json()
            else:
                return {"error": resp.status_code, "detail": resp.text}
                
        except Exception as e:
            return {"error": "Request failed", "detail": str(e)}
    
    def cancel_order(self, order_id: str) -> dict:
        """Cancel a specific order."""
        try:
            timestamp = str(int(datetime.datetime.now().timestamp() * 1000))
            path = f"/trade-api/v2/portfolio/orders/{order_id}"
            method = "DELETE"
            
            headers = self.get_headers(method, path)
            url = f"https://api.elections.kalshi.com{path}"
            
            resp = requests.delete(url, headers=headers, timeout=15)
            
            if resp.status_code == 200:
                return resp.json()
            else:
                return {"error": resp.status_code, "detail": resp.text}
                
        except Exception as e:
            return {"error": "Request failed", "detail": str(e)}
    
    def get_portfolio_orders(self) -> dict:
        """Get all portfolio orders."""
        try:
            timestamp = str(int(datetime.datetime.now().timestamp() * 1000))
            path = "/trade-api/v2/portfolio/orders"
            method = "GET"
            
            headers = self.get_headers(method, path)
            url = f"https://api.elections.kalshi.com{path}"
            
            resp = requests.get(url, headers=headers, timeout=15)
            
            if resp.status_code == 200:
                return resp.json()
            else:
                return {"error": resp.status_code, "detail": resp.text}
                
        except Exception as e:
            return {"error": "Request failed", "detail": str(e)}

class ArbitrageOrderManager:
    def __init__(self, api_key_id, private_key_path):
        self.order_manager = OrderManager(api_key_id, private_key_path)
        self.active_orders = {}  # {ticker: {yes_order_id, no_order_id, timestamp, price_level}}
        self.order_history = []
        
    def place_dynamic_order(self, ticker: str, side: str, price: int, count: int = 1) -> dict:
        """Place an order with dynamic pricing strategy."""
        try:
            timestamp = str(int(datetime.datetime.now().timestamp() * 1000))
            path = "/trade-api/v2/portfolio/orders"
            method = "POST"
            
            headers = self.order_manager.get_headers(method, path)
            
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
            
            url = f"https://api.elections.kalshi.com{path}"
            resp = requests.post(url, headers=headers, json=order_data, timeout=15)
            
            if resp.status_code == 201:
                result = resp.json()
                order_id = result.get("order", {}).get("order_id")  # FIXED: use "order_id" instead of "id"
                
                # Track the order
                if ticker not in self.active_orders:
                    self.active_orders[ticker] = {}
                
                self.active_orders[ticker][f"{side}_order_id"] = order_id
                self.active_orders[ticker][f"{side}_timestamp"] = datetime.datetime.now()
                self.active_orders[ticker][f"{side}_price"] = price
                
                return result
            else:
                return {"error": resp.status_code, "detail": resp.text}
                
        except Exception as e:
            return {"error": "Request failed", "detail": str(e)}
    
    def monitor_and_complete_arbitrage(self, ticker: str, max_wait_hours: int = 7) -> dict:
        """Monitor orders and complete arbitrage when one side fills."""
        if ticker not in self.active_orders:
            return {"error": "No active orders for this ticker"}
        
        orders = self.active_orders[ticker]
        
        # Check both orders
        yes_order_id = orders.get("yes_order_id")
        no_order_id = orders.get("no_order_id")
        
        if not yes_order_id or not no_order_id:
            return {"error": "Missing order IDs"}
        
        # Check order statuses
        yes_status = self.order_manager.check_order_status(yes_order_id)
        no_status = self.order_manager.check_order_status(no_order_id)
        
        if "error" in yes_status or "error" in no_status:
            return {"error": "Failed to check order status"}
        
        yes_order = yes_status.get("order", {})
        no_order = no_status.get("order", {})
        
        yes_filled = yes_order.get("remaining_count", 0) == 0
        no_filled = no_order.get("remaining_count", 0) == 0
        
        # Check if orders are too old
        now = datetime.datetime.now()
        yes_age = now - orders.get("yes_timestamp", now)
        no_age = now - orders.get("no_timestamp", now)
        
        max_age = datetime.timedelta(hours=max_wait_hours)
        
        if yes_age > max_age or no_age > max_age:
            # Cancel old orders
            result = {"action": "cancel_old_orders", "reason": "timeout"}
            
            if yes_age > max_age:
                cancel_result = self.order_manager.cancel_order(yes_order_id)
                result["yes_cancel"] = cancel_result
            
            if no_age > max_age:
                cancel_result = self.order_manager.cancel_order(no_order_id)
                result["no_cancel"] = cancel_result
            
            # Clean up
            if ticker in self.active_orders:
                del self.active_orders[ticker]
            
            return result
        
        # Check for fills and complete arbitrage
        if yes_filled and not no_filled:
            # YES filled, place NO order immediately
            no_price = orders.get("no_price", 2)  # Try higher price
            result = self.place_dynamic_order(ticker, "no", no_price)
            result["action"] = "yes_filled_placing_no"
            return result
        
        elif no_filled and not yes_filled:
            # NO filled, place YES order immediately
            yes_price = orders.get("yes_price", 2)  # Try higher price
            result = self.place_dynamic_order(ticker, "yes", yes_price)
            result["action"] = "no_filled_placing_yes"
            return result
        
        elif yes_filled and no_filled:
            # Both filled - arbitrage complete!
            result = {
                "action": "arbitrage_complete",
                "yes_order": yes_order,
                "no_order": no_order,
                "yes_fill_time": yes_order.get("filled_at"),
                "no_fill_time": no_order.get("filled_at")
            }
            
            # Clean up
            if ticker in self.active_orders:
                del self.active_orders[ticker]
            
            return result
        
        else:
            # Still waiting for fills
            return {
                "action": "waiting_for_fills",
                "yes_status": yes_order.get("status"),
                "no_status": no_order.get("status"),
                "yes_remaining": yes_order.get("remaining_count"),
                "no_remaining": no_order.get("remaining_count"),
                "yes_age_hours": yes_age.total_seconds() / 3600,
                "no_age_hours": no_age.total_seconds() / 3600
            }
    
    def upgrade_price_if_needed(self, ticker: str, hours_elapsed: int) -> dict:
        """Upgrade price if order hasn't filled after certain time."""
        if ticker not in self.active_orders:
            return {"error": "No active orders for this ticker"}
        
        orders = self.active_orders[ticker]
        
        # Determine price level based on time elapsed
        current_prices = {
            "yes_price": orders.get("yes_price", 1),
            "no_price": orders.get("no_price", 1)
        }
        
        new_prices = current_prices.copy()
        upgraded = False
        
        if hours_elapsed >= 1 and current_prices["yes_price"] == 1:
            new_prices["yes_price"] = 2
            new_prices["no_price"] = 2
            upgraded = True
        elif hours_elapsed >= 4 and current_prices["yes_price"] == 2:
            new_prices["yes_price"] = 3
            new_prices["no_price"] = 3
            upgraded = True
        elif hours_elapsed >= 6 and current_prices["yes_price"] == 3:
            new_prices["yes_price"] = 4
            new_prices["no_price"] = 4
            upgraded = True
        elif hours_elapsed >= 7 and current_prices["yes_price"] == 4:
            new_prices["yes_price"] = 5
            new_prices["no_price"] = 5
            upgraded = True
        
        if upgraded:
            # Cancel old orders and place new ones
            result = {"action": "price_upgrade", "old_prices": current_prices, "new_prices": new_prices}
            
            # Cancel old orders
            yes_order_id = orders.get("yes_order_id")
            no_order_id = orders.get("no_order_id")
            
            if yes_order_id:
                cancel_result = self.order_manager.cancel_order(yes_order_id)
                result["yes_cancel"] = cancel_result
            
            if no_order_id:
                cancel_result = self.order_manager.cancel_order(no_order_id)
                result["no_cancel"] = cancel_result
            
            # Place new orders at higher prices
            yes_result = self.place_dynamic_order(ticker, "yes", new_prices["yes_price"])
            no_result = self.place_dynamic_order(ticker, "no", new_prices["no_price"])
            
            result["yes_new"] = yes_result
            result["no_new"] = no_result
            
            return result
        else:
            return {"action": "no_upgrade_needed", "current_prices": current_prices}
    
    def get_all_active_orders(self) -> dict:
        """Get status of all active orders."""
        result = {"active_orders": len(self.active_orders), "orders": {}}
        
        for ticker, orders in self.active_orders.items():
            result["orders"][ticker] = {
                "yes_order_id": orders.get("yes_order_id"),
                "no_order_id": orders.get("no_order_id"),
                "yes_timestamp": orders.get("yes_timestamp"),
                "no_timestamp": orders.get("no_timestamp"),
                "yes_price": orders.get("yes_price"),
                "no_price": orders.get("no_price")
            }
        
        return result
