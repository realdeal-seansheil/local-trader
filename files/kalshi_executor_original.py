"""
Kalshi Trade Executor
Takes strategy signals derived from Polymarket pattern analysis
and executes equivalent trades on Kalshi.

This module handles:
1. Market discovery on Kalshi (find equivalent markets)
2. Order placement via Kalshi API
3. Position management and risk controls

IMPORTANT: Start with the demo API (https://demo-api.kalshi.co) before going live.
"""

import requests
import json
import os
import time
import datetime
import hashlib
import base64
from typing import Optional

# ============================================================
# CONFIGURATION - UPDATE THESE
# ============================================================
KALSHI_API_KEY_ID = os.environ.get("KALSHI_API_KEY_ID", "YOUR_API_KEY_ID")
KALSHI_PRIVATE_KEY_PATH = os.environ.get("KALSHI_PRIVATE_KEY_PATH", "kalshi-key.pem")

# Use demo for testing, production for live trading
USE_DEMO = True
BASE_URL = "https://demo-api.kalshi.co/trade-api/v2" if USE_DEMO else "https://api.elections.kalshi.com/trade-api/v2"

# Risk controls
MAX_POSITION_SIZE = 100        # Max contracts per order
MAX_DAILY_TRADES = 50          # Max trades per day
MAX_DAILY_EXPOSURE = 5000      # Max $ exposure per day
MIN_SPREAD_FOR_ARB = 0.02      # Minimum spread (2 cents) to attempt arb
MAX_PRICE_DEVIATION = 0.05     # Skip if Kalshi price is >5c different from signal

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)


class KalshiAuth:
    """Handle Kalshi API authentication with RSA key signing."""

    def __init__(self, api_key_id: str, private_key_path: str):
        self.api_key_id = api_key_id
        self.private_key = None

        if os.path.exists(private_key_path):
            try:
                from cryptography.hazmat.primitives import serialization
                with open(private_key_path, "rb") as f:
                    self.private_key = serialization.load_pem_private_key(
                        f.read(), password=None
                    )
                print(f"Loaded private key from {private_key_path}")
            except ImportError:
                print("WARNING: cryptography package not installed. Run: pip install cryptography")
            except Exception as e:
                print(f"WARNING: Could not load private key: {e}")
        else:
            print(f"WARNING: Private key not found at {private_key_path}")
            print("Auth will not work. Generate keys at https://kalshi.com/account/api")

    def get_headers(self, method: str, path: str) -> dict:
        """Generate authenticated headers for a request."""
        timestamp = str(int(datetime.datetime.now().timestamp() * 1000))

        # Strip query params for signing
        path_without_query = path.split("?")[0]
        msg = timestamp + method.upper() + path_without_query

        signature = ""
        if self.private_key:
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.asymmetric import padding
            sig_bytes = self.private_key.sign(
                msg.encode(),
                padding.PKCS1v15(),
                hashes.SHA256()
            )
            signature = base64.b64encode(sig_bytes).decode()

        return {
            "KALSHI-ACCESS-KEY": self.api_key_id,
            "KALSHI-ACCESS-SIGNATURE": signature,
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
            "Content-Type": "application/json",
        }


class KalshiClient:
    """Kalshi API client for market data and trading."""

    def __init__(self, auth: KalshiAuth):
        self.auth = auth
        self.daily_trades = 0
        self.daily_exposure = 0.0
        self.last_reset = datetime.date.today()

    def _reset_daily_limits(self):
        today = datetime.date.today()
        if today > self.last_reset:
            self.daily_trades = 0
            self.daily_exposure = 0.0
            self.last_reset = today

    # --- PUBLIC ENDPOINTS (no auth required) ---

    def get_markets(self, status="open", limit=100, cursor=None,
                    series_ticker=None, event_ticker=None) -> dict:
        """Get list of markets."""
        params = {"status": status, "limit": limit}
        if cursor:
            params["cursor"] = cursor
        if series_ticker:
            params["series_ticker"] = series_ticker
        if event_ticker:
            params["event_ticker"] = event_ticker

        resp = requests.get(f"{BASE_URL}/markets", params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def get_market(self, ticker: str) -> dict:
        """Get a single market by ticker."""
        resp = requests.get(f"{BASE_URL}/markets/{ticker}", timeout=15)
        resp.raise_for_status()
        return resp.json()

    def get_orderbook(self, ticker: str) -> dict:
        """Get orderbook for a market."""
        resp = requests.get(f"{BASE_URL}/markets/{ticker}/orderbook", timeout=15)
        resp.raise_for_status()
        return resp.json()

    def get_trades(self, ticker: str = None, limit=100) -> dict:
        """Get recent trades."""
        params = {"limit": limit}
        if ticker:
            params["ticker"] = ticker
        resp = requests.get(f"{BASE_URL}/markets/trades", params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def search_markets(self, query: str) -> list:
        """
        Search for markets matching a query string.
        Uses the get_markets endpoint and filters client-side.
        """
        all_markets = []
        cursor = None

        for _ in range(5):  # Max 5 pages
            result = self.get_markets(limit=200, cursor=cursor)
            markets = result.get("markets", [])
            all_markets.extend(markets)
            cursor = result.get("cursor")
            if not cursor or not markets:
                break
            time.sleep(0.3)

        # Filter by query
        query_lower = query.lower()
        query_words = query_lower.split()
        matches = []
        for m in all_markets:
            title = (m.get("title") or "").lower()
            if all(w in title for w in query_words):
                matches.append(m)

        return matches

    # --- AUTHENTICATED ENDPOINTS ---

    def get_balance(self) -> dict:
        """Get account balance."""
        path = "/trade-api/v2/portfolio/balance"
        headers = self.auth.get_headers("GET", path)
        resp = requests.get(BASE_URL.rsplit("/trade-api/v2", 1)[0] + path,
                            headers=headers, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def get_positions(self) -> dict:
        """Get current positions."""
        path = "/trade-api/v2/portfolio/positions"
        headers = self.auth.get_headers("GET", path)
        resp = requests.get(BASE_URL.rsplit("/trade-api/v2", 1)[0] + path,
                            headers=headers, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def place_order(self, ticker: str, side: str, action: str,
                    count: int, price: int, order_type: str = "limit") -> dict:
        """
        Place an order on Kalshi.

        Args:
            ticker: Market ticker (e.g., "KXBTC-26FEB14-T100000")
            side: "yes" or "no"
            action: "buy" or "sell"
            count: Number of contracts
            price: Price in cents (1-99)
            order_type: "limit" or "market"
        """
        self._reset_daily_limits()

        # Safety checks
        if self.daily_trades >= MAX_DAILY_TRADES:
            return {"error": f"Daily trade limit reached ({MAX_DAILY_TRADES})"}

        if count > MAX_POSITION_SIZE:
            return {"error": f"Position size {count} exceeds max {MAX_POSITION_SIZE}"}

        exposure = count * price / 100
        if self.daily_exposure + exposure > MAX_DAILY_EXPOSURE:
            return {"error": f"Would exceed daily exposure limit (${MAX_DAILY_EXPOSURE})"}

        import uuid
        path = "/trade-api/v2/portfolio/orders"
        headers = self.auth.get_headers("POST", path)

        order_data = {
            "ticker": ticker,
            "side": side,
            "action": action,
            "count": count,
            "type": order_type,
            "client_order_id": str(uuid.uuid4()),
        }
        if order_type == "limit":
            order_data["yes_price" if side == "yes" else "no_price"] = price

        resp = requests.post(
            BASE_URL.rsplit("/trade-api/v2", 1)[0] + path,
            headers=headers,
            json=order_data,
            timeout=15,
        )

        if resp.status_code == 201:
            self.daily_trades += 1
            self.daily_exposure += exposure
            result = resp.json()
            self._log_order(order_data, result)
            return result
        else:
            return {"error": resp.status_code, "detail": resp.text}

    def _log_order(self, order_data: dict, result: dict):
        log_file = os.path.join(DATA_DIR, "kalshi_orders.jsonl")
        entry = {
            "timestamp": datetime.datetime.now().isoformat(),
            "order": order_data,
            "result": result,
        }
        with open(log_file, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")


class StrategyExecutor:
    """
    Takes signals from the Polymarket pattern analysis and
    executes equivalent strategies on Kalshi.
    """

    def __init__(self, client: KalshiClient):
        self.client = client
        self.market_cache = {}
        self.cache_ttl = 300  # 5 min cache

    def find_arb_opportunities(self) -> list:
        """
        Scan Kalshi markets for arbitrage opportunities
        (YES + NO < $1.00 after fees).
        """
        opportunities = []
        result = self.client.get_markets(status="open", limit=200)
        markets = result.get("markets", [])

        for market in markets:
            ticker = market.get("ticker", "")
            yes_price = market.get("yes_price", 0)  # In cents
            no_price = market.get("no_price", 0)

            if yes_price and no_price:
                combined = (yes_price + no_price) / 100  # Convert to dollars
                if combined < 1.0 - MIN_SPREAD_FOR_ARB:
                    spread = round(1.0 - combined, 4)
                    opportunities.append({
                        "ticker": ticker,
                        "title": market.get("title", ""),
                        "yes_price_cents": yes_price,
                        "no_price_cents": no_price,
                        "combined": round(combined, 4),
                        "spread": spread,
                        "volume": market.get("volume", 0),
                    })

        # Sort by spread (best first)
        opportunities.sort(key=lambda x: x["spread"], reverse=True)
        return opportunities

    def execute_arb(self, ticker: str, count: int = 10) -> dict:
        """
        Execute an arbitrage trade: buy both YES and NO.
        """
        # Get fresh orderbook
        try:
            ob = self.client.get_orderbook(ticker)
        except Exception as e:
            return {"error": f"Failed to get orderbook: {e}"}

        yes_bids = ob.get("orderbook", {}).get("yes", [])
        no_bids = ob.get("orderbook", {}).get("no", [])

        if not yes_bids or not no_bids:
            return {"error": "Insufficient liquidity"}

        # Best available prices (lowest ask = 100 - highest bid on opposite side)
        best_yes_price = yes_bids[0][0] if yes_bids else None
        best_no_price = no_bids[0][0] if no_bids else None

        if not best_yes_price or not best_no_price:
            return {"error": "No valid prices"}

        combined = (best_yes_price + best_no_price) / 100
        if combined >= 1.0 - MIN_SPREAD_FOR_ARB:
            return {"error": f"Spread too thin: {combined:.4f}"}

        # Execute both legs
        yes_result = self.client.place_order(
            ticker=ticker, side="yes", action="buy",
            count=count, price=best_yes_price
        )

        no_result = self.client.place_order(
            ticker=ticker, side="no", action="buy",
            count=count, price=best_no_price
        )

        return {
            "yes_order": yes_result,
            "no_order": no_result,
            "combined_price": combined,
            "expected_profit_per_contract": round(1.0 - combined, 4),
            "total_expected_profit": round((1.0 - combined) * count, 4),
        }

    def execute_directional(self, ticker: str, side: str, price: int,
                            count: int) -> dict:
        """Execute a directional trade based on a signal."""
        return self.client.place_order(
            ticker=ticker, side=side, action="buy",
            count=count, price=price
        )

    def scan_and_report(self) -> dict:
        """Scan for opportunities and return a report (no execution)."""
        print("Scanning Kalshi for opportunities...")
        opps = self.find_arb_opportunities()

        report = {
            "timestamp": datetime.datetime.now().isoformat(),
            "total_opportunities": len(opps),
            "top_opportunities": opps[:10],
        }

        report_file = os.path.join(DATA_DIR, "kalshi_opportunities.json")
        with open(report_file, "w") as f:
            json.dump(report, f, indent=2)

        return report


if __name__ == "__main__":
    print("=== Kalshi Strategy Executor ===\n")
    print(f"Mode: {'DEMO' if USE_DEMO else '*** LIVE ***'}")
    print(f"Base URL: {BASE_URL}\n")

    # Initialize (auth optional for market scanning)
    auth = KalshiAuth(KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH)
    client = KalshiClient(auth)
    executor = StrategyExecutor(client)

    # Scan for opportunities (no auth required)
    print("--- Scanning for Arbitrage Opportunities ---\n")
    try:
        report = executor.scan_and_report()
        print(f"Found {report['total_opportunities']} potential opportunities\n")

        for i, opp in enumerate(report["top_opportunities"][:5]):
            print(f"  {i+1}. {opp['title']}")
            print(f"     Ticker: {opp['ticker']}")
            print(f"     YES: {opp['yes_price_cents']}c | NO: {opp['no_price_cents']}c")
            print(f"     Combined: ${opp['combined']} | Spread: {opp['spread']}")
            print(f"     Volume: {opp['volume']}")
            print()

        print(f"Full report saved to {DATA_DIR}/kalshi_opportunities.json")
    except Exception as e:
        print(f"Error scanning markets: {e}")
        print("This may be due to network restrictions. Run locally for full functionality.")

    print("\n--- To Execute Trades ---")
    print("1. Set KALSHI_API_KEY_ID and KALSHI_PRIVATE_KEY_PATH environment variables")
    print("2. Or update the constants at the top of this file")
    print("3. pip install cryptography")
    print("4. Start with USE_DEMO = True to test")
    print("5. Call executor.execute_arb(ticker, count) to trade")
