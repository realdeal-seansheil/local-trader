"""
Polymarket Account Monitor for distinct-baguette.
Polls for new trades and detects strategy shifts over time.

Run: python monitor.py
Runs continuously, checking every POLL_INTERVAL seconds.
"""

import requests
import json
import os
import time
from datetime import datetime
from collections import defaultdict

WALLET_ADDRESS = "0xe00740bce98a594e26861838885ab310ec3b548c"
DATA_API = "https://data-api.polymarket.com"
DATA_DIR = "data"
MONITOR_LOG = os.path.join(DATA_DIR, "monitor_log.json")
POLL_INTERVAL = 60  # seconds between checks

os.makedirs(DATA_DIR, exist_ok=True)


class TradeMonitor:
    def __init__(self, wallet_address: str):
        self.wallet = wallet_address
        self.seen_txns = set()
        self.recent_trades = []
        self.strategy_window = []  # Rolling window for strategy detection
        self.callbacks = []  # Functions to call on new trade

        # Load previously seen transactions
        self._load_state()

    def _load_state(self):
        state_file = os.path.join(DATA_DIR, "monitor_state.json")
        if os.path.exists(state_file):
            with open(state_file) as f:
                state = json.load(f)
                self.seen_txns = set(state.get("seen_txns", []))
            print(f"Loaded {len(self.seen_txns)} previously seen transactions")

    def _save_state(self):
        state_file = os.path.join(DATA_DIR, "monitor_state.json")
        with open(state_file, "w") as f:
            json.dump({"seen_txns": list(self.seen_txns)[-10000:]}, f)  # Keep last 10k

    def on_new_trade(self, callback):
        """Register a callback for new trades."""
        self.callbacks.append(callback)

    def check_for_new_trades(self) -> list:
        """Poll the API for new trades."""
        try:
            resp = requests.get(f"{DATA_API}/trades", params={
                "user": self.wallet,
                "limit": 50,
                "offset": 0,
                "takerOnly": "false",
            }, timeout=15)
            resp.raise_for_status()
            trades = resp.json()
        except Exception as e:
            print(f"  Error fetching trades: {e}")
            return []

        new_trades = []
        for t in trades:
            txn = t.get("transactionHash", "")
            if txn and txn not in self.seen_txns:
                self.seen_txns.add(txn)
                new_trades.append(t)

        if new_trades:
            self.recent_trades.extend(new_trades)
            self.strategy_window.extend(new_trades)
            # Keep rolling window to last 500 trades
            self.strategy_window = self.strategy_window[-500:]
            self._save_state()

            for trade in new_trades:
                for callback in self.callbacks:
                    callback(trade)

        return new_trades

    def detect_strategy_shift(self) -> dict | None:
        """
        Compare recent trading behavior against historical baseline.
        Returns shift info if a significant change is detected.
        """
        if len(self.strategy_window) < 20:
            return None

        recent = self.strategy_window[-20:]
        older = self.strategy_window[:-20]

        if len(older) < 20:
            return None

        shifts = {}

        # Compare category distribution
        recent_cats = self._categorize_trades(recent)
        older_cats = self._categorize_trades(older)

        for cat in set(list(recent_cats.keys()) + list(older_cats.keys())):
            r_pct = recent_cats.get(cat, 0) / len(recent) * 100
            o_pct = older_cats.get(cat, 0) / len(older) * 100
            if abs(r_pct - o_pct) > 20:  # >20 percentage point shift
                shifts[f"category_shift_{cat}"] = {
                    "old_pct": round(o_pct, 1),
                    "new_pct": round(r_pct, 1),
                    "direction": "increase" if r_pct > o_pct else "decrease",
                }

        # Compare avg price
        recent_prices = [t.get("price", 0) for t in recent if t.get("price")]
        older_prices = [t.get("price", 0) for t in older if t.get("price")]
        if recent_prices and older_prices:
            r_avg = sum(recent_prices) / len(recent_prices)
            o_avg = sum(older_prices) / len(older_prices)
            if abs(r_avg - o_avg) > 0.1:
                shifts["price_shift"] = {
                    "old_avg": round(o_avg, 4),
                    "new_avg": round(r_avg, 4),
                }

        # Compare buy/sell ratio
        r_buys = sum(1 for t in recent if t.get("side") == "BUY")
        o_buys = sum(1 for t in older if t.get("side") == "BUY")
        r_ratio = r_buys / len(recent)
        o_ratio = o_buys / len(older)
        if abs(r_ratio - o_ratio) > 0.2:
            shifts["buy_ratio_shift"] = {
                "old_buy_ratio": round(o_ratio, 2),
                "new_buy_ratio": round(r_ratio, 2),
            }

        # Compare position sizes
        recent_sizes = [t.get("size", 0) for t in recent if t.get("size")]
        older_sizes = [t.get("size", 0) for t in older if t.get("size")]
        if recent_sizes and older_sizes:
            r_med = sorted(recent_sizes)[len(recent_sizes) // 2]
            o_med = sorted(older_sizes)[len(older_sizes) // 2]
            if r_med > 0 and o_med > 0 and (r_med / o_med > 2 or o_med / r_med > 2):
                shifts["size_shift"] = {
                    "old_median_size": round(o_med, 2),
                    "new_median_size": round(r_med, 2),
                }

        return shifts if shifts else None

    def _categorize_trades(self, trades: list) -> dict:
        cats = defaultdict(int)
        keywords = {
            "crypto": ["bitcoin", "btc", "eth", "crypto", "sol", "token"],
            "politics": ["trump", "biden", "election", "president"],
            "sports": ["nfl", "nba", "mlb", "game", "match"],
            "economics": ["fed", "rate", "inflation", "gdp"],
        }
        for t in trades:
            slug = (t.get("eventSlug") or t.get("slug") or "").lower()
            matched = False
            for cat, kws in keywords.items():
                if any(kw in slug for kw in kws):
                    cats[cat] += 1
                    matched = True
                    break
            if not matched:
                cats["other"] += 1
        return dict(cats)

    def get_status(self) -> dict:
        return {
            "wallet": self.wallet,
            "seen_transactions": len(self.seen_txns),
            "recent_trades_in_window": len(self.strategy_window),
            "last_check": datetime.now().isoformat(),
        }


def log_trade(trade: dict):
    """Default callback: print and log new trades."""
    ts = trade.get("timestamp", 0)
    dt = datetime.fromtimestamp(ts / 1000 if ts > 1e12 else ts) if ts else "unknown"
    print(f"\n  NEW TRADE @ {dt}")
    print(f"    Market: {trade.get('title', 'N/A')}")
    print(f"    Side:   {trade.get('side')} {trade.get('outcome', '')}")
    print(f"    Price:  {trade.get('price', 'N/A')}")
    print(f"    Size:   {trade.get('size', 'N/A')}")
    print(f"    Txn:    {trade.get('transactionHash', 'N/A')[:20]}...")

    # Append to log file
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "trade": {
            "title": trade.get("title"),
            "side": trade.get("side"),
            "outcome": trade.get("outcome"),
            "price": trade.get("price"),
            "size": trade.get("size"),
            "slug": trade.get("eventSlug"),
        }
    }
    log_file = os.path.join(DATA_DIR, "new_trades_log.jsonl")
    with open(log_file, "a") as f:
        f.write(json.dumps(log_entry) + "\n")


if __name__ == "__main__":
    print(f"=== Monitoring distinct-baguette ({WALLET_ADDRESS}) ===")
    print(f"Poll interval: {POLL_INTERVAL}s\n")

    monitor = TradeMonitor(WALLET_ADDRESS)
    monitor.on_new_trade(log_trade)

    check_count = 0
    while True:
        check_count += 1
        now = datetime.now().strftime("%H:%M:%S")
        print(f"[{now}] Check #{check_count}...", end="")

        new = monitor.check_for_new_trades()
        if new:
            print(f" {len(new)} new trades!")

            # Check for strategy shifts
            shifts = monitor.detect_strategy_shift()
            if shifts:
                print(f"\n  *** STRATEGY SHIFT DETECTED ***")
                for k, v in shifts.items():
                    print(f"    {k}: {v}")

                shift_log = os.path.join(DATA_DIR, "strategy_shifts.jsonl")
                with open(shift_log, "a") as f:
                    f.write(json.dumps({"timestamp": datetime.now().isoformat(), "shifts": shifts}) + "\n")
        else:
            print(" no new trades")

        time.sleep(POLL_INTERVAL)
