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
KALSHI_API_KEY_ID = os.environ.get("KALSHI_API_KEY_ID", "92ddf45c-87ff-42fd-8a86-3f97a0e0d39c")
# Default key path: look in the files/ directory (shared with 15-min bot)
_DEFAULT_KEY_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "files", "kalshi-key.pem")
KALSHI_PRIVATE_KEY_PATH = os.environ.get("KALSHI_PRIVATE_KEY_PATH", _DEFAULT_KEY_PATH)

# Use demo for testing, production for live trading
USE_DEMO = False  # Live API — real market data for scanning
OBSERVATION_MODE = False  # *** LIVE TRADING ***
BASE_URL = "https://demo-api.kalshi.co/trade-api/v2" if USE_DEMO else "https://api.elections.kalshi.com/trade-api/v2"

# Risk controls — momentum strategy: no limits, full tilt
MAX_POSITION_SIZE = 10         # Max 10 contracts per order (momentum conviction tier)
MAX_DAILY_TRADES = 99999       # No limit
MAX_DAILY_EXPOSURE = 999999    # No limit
MIN_SPREAD_FOR_ARB = 0.03      # 3c minimum spread — accounts for Kalshi fees
MAX_PRICE_DEVIATION = 0.05     # Skip if Kalshi price is >5c different from signal
ARB_BOT_MAX_BALANCE_USAGE = 1000  # $10 in cents — hard cap for arb bot allocation

# Fee-aware profitability
KALSHI_FEE_RATE = 0.007        # 0.7% trading fee per leg
MIN_PROFIT_AFTER_FEES = 0.01   # 1 cent net profit minimum per contract

import pathlib
DATA_DIR = str(pathlib.Path(__file__).parent / "data")
os.makedirs(DATA_DIR, exist_ok=True)


def calculate_arb_profitability(yes_price_cents, no_price_cents, count=1):
    """
    Calculate profitability of an arb trade after Kalshi's 0.7% fees.

    Returns dict with gross profit, fees, net profit, and whether it's profitable.
    """
    cost_yes = yes_price_cents / 100.0 * count
    cost_no = no_price_cents / 100.0 * count
    total_cost = cost_yes + cost_no
    gross_profit = (1.0 * count) - total_cost

    # Fees on each leg: 0.7% of notional
    fee_yes = cost_yes * KALSHI_FEE_RATE
    fee_no = cost_no * KALSHI_FEE_RATE
    total_fees = fee_yes + fee_no

    net_profit = gross_profit - total_fees
    net_per_contract = net_profit / count if count > 0 else 0

    return {
        "gross_profit_per_contract": round(gross_profit / count, 4) if count else 0,
        "net_profit_per_contract": round(net_per_contract, 4),
        "gross_total_profit": round(gross_profit, 4),
        "total_fees": round(total_fees, 4),
        "net_profit": round(net_profit, 4),
        "roi_net_percent": round((net_profit / total_cost * 100), 2) if total_cost > 0 else 0,
        "profitable_after_fees": net_per_contract >= MIN_PROFIT_AFTER_FEES,
    }


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
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.DIGEST_LENGTH,
                ),
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

        # Observation mode — log but don't execute
        if OBSERVATION_MODE:
            obs_entry = {
                "timestamp": datetime.datetime.now().isoformat(),
                "mode": "observation",
                "order": {"ticker": ticker, "side": side, "action": action,
                          "count": count, "price": price, "type": order_type},
            }
            log_file = os.path.join(DATA_DIR, "observation_orders.jsonl")
            with open(log_file, "a") as f:
                f.write(json.dumps(obs_entry, default=str) + "\n")
            return {"observation": True, "would_have_placed": obs_entry["order"]}

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
        Scan Kalshi markets for arbitrage opportunities using orderbook depth.

        On Kalshi, the orderbook shows bids for YES and bids for NO.
        To BUY both sides (arb), the implied ask prices are:
          YES ask = 100 - max_no_bid
          NO ask  = 100 - max_yes_bid
        Arb exists when yes_ask + no_ask < 100c (i.e., max_yes_bid + max_no_bid > 100).

        Only returns opportunities that are profitable AFTER Kalshi's 0.7% fee.
        """
        opportunities = []
        result = self.client.get_markets(status="open", limit=200)
        markets = result.get("markets", [])

        for market in markets:
            ticker = market.get("ticker", "")
            title = market.get("title", "")

            try:
                ob = self.client.get_orderbook(ticker)
            except Exception:
                continue

            yes_bids = ob.get("orderbook", {}).get("yes", [])
            no_bids = ob.get("orderbook", {}).get("no", [])

            if not yes_bids or not no_bids:
                continue

            # Find highest bids on each side
            max_yes_bid = max(b[0] for b in yes_bids)
            max_no_bid = max(b[0] for b in no_bids)

            # Implied ask prices
            yes_ask = 100 - max_no_bid
            no_ask = 100 - max_yes_bid
            combined_ask = yes_ask + no_ask  # in cents

            if combined_ask < 100 - int(MIN_SPREAD_FOR_ARB * 100):
                # Check profitability after fees
                profitability = calculate_arb_profitability(yes_ask, no_ask, count=1)
                if not profitability["profitable_after_fees"]:
                    continue

                spread = round((100 - combined_ask) / 100.0, 4)
                opportunities.append({
                    "ticker": ticker,
                    "title": title,
                    "yes_ask_cents": yes_ask,
                    "no_ask_cents": no_ask,
                    "combined_ask_cents": combined_ask,
                    "spread": spread,
                    "net_profit_per_contract": profitability["net_profit_per_contract"],
                    "roi_net_percent": profitability["roi_net_percent"],
                    "volume": market.get("volume", 0),
                })

        # Sort by net profit per contract (best first)
        opportunities.sort(key=lambda x: x["net_profit_per_contract"], reverse=True)
        return opportunities

    def check_balance_for_arb(self, count, yes_price, no_price):
        """Verify enough balance and within $10 arb bot allocation."""
        try:
            balance = self.client.get_balance()
            available_cents = balance.get("balance", 0)
            cost_cents = (yes_price + no_price) * count

            if cost_cents > ARB_BOT_MAX_BALANCE_USAGE:
                return False, f"Cost ${cost_cents/100:.2f} exceeds arb bot allocation ${ARB_BOT_MAX_BALANCE_USAGE/100:.2f}"
            if cost_cents > available_cents:
                return False, f"Insufficient balance: need ${cost_cents/100:.2f}, have ${available_cents/100:.2f}"
            return True, "OK"
        except Exception as e:
            return False, f"Balance check failed: {e}"

    def execute_arb(self, ticker: str, count: int = 5) -> dict:
        """
        Execute an arbitrage trade: buy both YES and NO at implied ask prices.

        On Kalshi, to buy YES you place a limit order at the YES ask price.
        The YES ask = 100 - max_no_bid (taking the best NO bidder's offer).

        Includes balance check and fee-aware profitability check.
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

        # Find highest bids
        max_yes_bid = max(b[0] for b in yes_bids)
        max_no_bid = max(b[0] for b in no_bids)

        # Implied ask prices
        yes_ask = 100 - max_no_bid
        no_ask = 100 - max_yes_bid
        combined_ask = yes_ask + no_ask  # in cents

        if combined_ask >= 100 - int(MIN_SPREAD_FOR_ARB * 100):
            return {"error": f"Spread too thin: combined ask = {combined_ask}c"}

        # Check profitability after fees
        profitability = calculate_arb_profitability(yes_ask, no_ask, count)
        if not profitability["profitable_after_fees"]:
            return {"error": f"Not profitable after fees: net {profitability['net_profit_per_contract']:.4f}/contract"}

        # Check balance allocation
        ok, msg = self.check_balance_for_arb(count, yes_ask, no_ask)
        if not ok:
            return {"error": msg}

        # Execute both legs — buy YES at yes_ask, buy NO at no_ask
        yes_result = self.client.place_order(
            ticker=ticker, side="yes", action="buy",
            count=count, price=yes_ask
        )

        no_result = self.client.place_order(
            ticker=ticker, side="no", action="buy",
            count=count, price=no_ask
        )

        return {
            "yes_order": yes_result,
            "no_order": no_result,
            "yes_ask_price": yes_ask,
            "no_ask_price": no_ask,
            "combined_ask_cents": combined_ask,
            "gross_profit_per_contract": profitability["gross_profit_per_contract"],
            "net_profit_per_contract": profitability["net_profit_per_contract"],
            "total_fees": profitability["total_fees"],
            "total_net_profit": profitability["net_profit"],
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
            print(f"     YES ask: {opp['yes_ask_cents']}c | NO ask: {opp['no_ask_cents']}c")
            print(f"     Combined ask: {opp['combined_ask_cents']}c | Spread: {opp['spread']}")
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
