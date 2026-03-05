"""
Straddle Executor — Core engine for crypto 15-min straddle trading on Kalshi.

Strategy (modeled from distinct-baguette's Polymarket behavior):
1. ENTER: Buy both YES and NO at market open (quarter hour)
2. MONITOR: Poll orderbook every 2s, track price movement
3. EXIT: Sell whichever side moves +5c in our favor

Orderbook math:
  - BUY YES at: 100 - max_no_bid  (the YES ask)
  - BUY NO at:  100 - max_yes_bid  (the NO ask)
  - SELL YES at: max_yes_bid       (someone buys our YES)
  - SELL NO at:  max_no_bid        (someone buys our NO)
  - YES P&L = current_yes_bid - yes_entry_price
  - NO P&L  = current_no_bid - no_entry_price

  Note: entry prices here mean what we PAID (the ask price), which we
  compute as 100 - opposite_max_bid at entry time. When selling, we
  receive the current bid on OUR side.
"""

import sys
import os
import json
import time
import calendar
import pathlib
from collections import defaultdict
from datetime import datetime, timedelta

# Add trade_arbitrage to path for imports
_ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / "trade_arbitrage"))
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from kalshi_executor import KalshiAuth, KalshiClient, KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH
from config import (
    CRYPTO_SERIES, MAX_CONTRACTS_PER_SIDE, MAX_COMBINED_ENTRY_CENTS,
    MAX_SINGLE_SIDE_ENTRY, MIN_IMBALANCE_CENTS,
    MIN_ORDERBOOK_DEPTH, EXIT_PROFIT_TARGET_CENTS, EXIT_TIMEOUT_SECONDS,
    POLL_INTERVAL_SECONDS, EXIT_BEFORE_CLOSE_SECONDS, MAX_DAILY_STRADDLES,
    MAX_DAILY_EXPOSURE_CENTS, OBSERVATION_MODE, SCAN_BEFORE_QUARTER_SECONDS,
    ENTRY_WINDOW_SECONDS, KALSHI_FEE_RATE, DATA_DIR,
    LOOP_INTERVAL_SECONDS, MAX_SIMULTANEOUS_POSITIONS,
    SKIP_HOURS,
    PASSIVE_TICK_LOGGING, PASSIVE_TICK_INTERVAL,
    STRADDLE_ENTRIES_ENABLED,
    MOMENTUM_ENABLED, MOMENTUM_ENTRY_SECONDS, MOMENTUM_ENTRY_WINDOW,
    MOMENTUM_MIN_BID, MOMENTUM_CONVICTION_TIERS, MOMENTUM_MAX_DAILY,
    MOMENTUM_MAX_DAILY_EXPOSURE,
    MOMENTUM_STOPLOSS_ENABLED, MOMENTUM_STOPLOSS_THRESHOLDS,
    MOMENTUM_SHADOW_MIN_BID,
    MOMENTUM_STOPLOSS_LIVE, MOMENTUM_STOPLOSS_DROP, MOMENTUM_STOPLOSS_MIN_SERIES,
    MOMENTUM_OVERNIGHT_MIN_BID, MOMENTUM_OVERNIGHT_START_HOUR, MOMENTUM_OVERNIGHT_END_HOUR,
    BAYESIAN_ENABLED, BAYESIAN_SHADOW_MODE,
    KELLY_MULTIPLIER, KELLY_USE_LIVE_BALANCE, KELLY_BANKROLL_CENTS,
    KELLY_BALANCE_CACHE_SECONDS, KELLY_MIN_CONTRACTS, KELLY_MAX_CONTRACTS,
    KELLY_MAX_BANKROLL_PCT, KELLY_MIN_CONFIDENCE, BAYESIAN_SECONDARY_DAMPENING,
)
from position_tracker import PositionTracker


def next_quarter_hour():
    """Calculate the next quarter hour (:00, :15, :30, :45)."""
    now = datetime.now()
    minute = now.minute
    next_q_minute = ((minute // 15) + 1) * 15
    if next_q_minute >= 60:
        next_q = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    else:
        next_q = now.replace(minute=next_q_minute, second=0, microsecond=0)
    return next_q


def seconds_until(target):
    """Seconds from now until target datetime."""
    return max(0, (target - datetime.now()).total_seconds())


def parse_orderbook(ob_response):
    """
    Parse a Kalshi orderbook response into actionable prices.

    Returns dict with:
      yes_ask: what it costs to BUY YES (= 100 - max_no_bid)
      no_ask:  what it costs to BUY NO  (= 100 - max_yes_bid)
      yes_bid: what we'd receive SELLING YES (= max_yes_bid)
      no_bid:  what we'd receive SELLING NO  (= max_no_bid)
      yes_bid_depth: quantity at best YES bid
      no_bid_depth:  quantity at best NO bid
      combined_ask: yes_ask + no_ask (entry cost)
    """
    ob = ob_response.get("orderbook", {})
    yes_bids = ob.get("yes", [])
    no_bids = ob.get("no", [])

    if not yes_bids or not no_bids:
        return None

    # Find highest bids on each side
    max_yes_bid = max(b[0] for b in yes_bids)
    max_no_bid = max(b[0] for b in no_bids)

    # Quantity at the best bid (for depth check)
    yes_bid_at_max = next((b[1] for b in yes_bids if b[0] == max_yes_bid), 0)
    no_bid_at_max = next((b[1] for b in no_bids if b[0] == max_no_bid), 0)

    # Implied ask prices (cost to take liquidity)
    yes_ask = 100 - max_no_bid
    no_ask = 100 - max_yes_bid

    return {
        "yes_ask": yes_ask,
        "no_ask": no_ask,
        "yes_bid": max_yes_bid,
        "no_bid": max_no_bid,
        "yes_bid_depth": yes_bid_at_max,
        "no_bid_depth": no_bid_at_max,
        "combined_ask": yes_ask + no_ask,
    }


class StraddleExecutor:
    """
    Executes the 3-phase straddle strategy on Kalshi crypto 15-min markets.
    """

    def __init__(self):
        self.auth = KalshiAuth(KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH)
        self.client = KalshiClient(self.auth)
        self.tracker = PositionTracker()

        # Initialize Bayesian signal engine if enabled or in shadow mode
        self.bayesian = None
        if BAYESIAN_ENABLED or BAYESIAN_SHADOW_MODE:
            from bayesian_signal import BayesianSignal
            self.bayesian = BayesianSignal(
                data_dir=DATA_DIR,
                config={
                    "kelly_multiplier": KELLY_MULTIPLIER,
                    "bankroll_cents": KELLY_BANKROLL_CENTS,
                    "min_contracts": KELLY_MIN_CONTRACTS,
                    "max_contracts": KELLY_MAX_CONTRACTS,
                    "max_bankroll_pct": KELLY_MAX_BANKROLL_PCT,
                    "min_confidence": KELLY_MIN_CONFIDENCE,
                    "fee_rate": KALSHI_FEE_RATE,
                    "conviction_tiers": MOMENTUM_CONVICTION_TIERS,
                    "min_bid": MOMENTUM_MIN_BID,
                    "overnight_min_bid": MOMENTUM_OVERNIGHT_MIN_BID,
                    "use_live_balance": KELLY_USE_LIVE_BALANCE,
                    "balance_cache_seconds": KELLY_BALANCE_CACHE_SECONDS,
                    "secondary_dampening": BAYESIAN_SECONDARY_DAMPENING,
                },
                kalshi_client=self.client,
            )

    # ==========================================================
    # PHASE 1: MARKET SELECTION & ENTRY
    # ==========================================================

    def select_best_market(self):
        """
        Scan all crypto series and return the best market for entry.
        Best = lowest combined ask price with sufficient depth.
        Returns (market_dict, orderbook_parsed) or (None, None).
        """
        best_market = None
        best_ob = None
        best_combined = 999

        for series in CRYPTO_SERIES:
            try:
                result = self.client.get_markets(
                    status="open", limit=5, series_ticker=series
                )
                markets = result.get("markets", [])
            except Exception as e:
                print(f"    Error fetching {series}: {e}")
                continue

            for market in markets:
                ticker = market.get("ticker", "")
                try:
                    ob_raw = self.client.get_orderbook(ticker)
                except Exception:
                    continue

                ob = parse_orderbook(ob_raw)
                if ob is None:
                    continue

                # Check entry criteria
                if ob["combined_ask"] > MAX_COMBINED_ENTRY_CENTS:
                    continue
                if ob["yes_ask"] >= MAX_SINGLE_SIDE_ENTRY or ob["no_ask"] >= MAX_SINGLE_SIDE_ENTRY:
                    continue  # Market already decided
                if abs(ob["yes_ask"] - ob["no_ask"]) < MIN_IMBALANCE_CENTS:
                    continue  # Balanced entries are net-negative
                if ob["yes_bid_depth"] < MIN_ORDERBOOK_DEPTH:
                    continue
                if ob["no_bid_depth"] < MIN_ORDERBOOK_DEPTH:
                    continue

                # Track best
                if ob["combined_ask"] < best_combined:
                    best_combined = ob["combined_ask"]
                    best_market = market
                    best_ob = ob

        return best_market, best_ob

    def _derive_series(self, ticker):
        """Derive series from ticker (e.g. KXBTC15M-26FEB231245-45 → KXBTC15M)."""
        for series in CRYPTO_SERIES:
            if ticker.startswith(series):
                return series
        return ticker.split("-")[0] if "-" in ticker else ticker

    def enter_straddle(self, market, ob):
        """
        Enter a straddle: buy both YES and NO.
        Returns StraddlePosition or None.
        """
        ticker = market["ticker"]
        series = market.get("series_ticker") or self._derive_series(ticker)
        title = market.get("title", "")
        close_time = market.get("close_time")
        contracts = MAX_CONTRACTS_PER_SIDE

        yes_price = ob["yes_ask"]
        no_price = ob["no_ask"]
        combined = ob["combined_ask"]

        print(f"\n  STRADDLE ENTRY: {title}")
        print(f"    Ticker: {ticker}")
        print(f"    YES ask: {yes_price}c | NO ask: {no_price}c | Combined: {combined}c")
        print(f"    Contracts: {contracts} per side")
        print(f"    Total cost: {combined * contracts}c (${combined * contracts / 100:.2f})")

        # Check daily limits (skip in observation mode — collect max data)
        if not OBSERVATION_MODE:
            stats = self.tracker.get_daily_stats()
            if stats["daily_straddles"] >= MAX_DAILY_STRADDLES:
                print(f"    SKIP: Daily straddle limit reached ({MAX_DAILY_STRADDLES})")
                return None
            if stats["daily_exposure_cents"] + combined * contracts > MAX_DAILY_EXPOSURE_CENTS:
                print(f"    SKIP: Would exceed daily exposure limit "
                      f"(${MAX_DAILY_EXPOSURE_CENTS/100:.2f})")
                return None

        if OBSERVATION_MODE:
            print(f"    [OBSERVATION MODE — logging entry, not executing]")
            pos = self.tracker.open_straddle(
                ticker=ticker, series=series,
                yes_entry_price=yes_price, no_entry_price=no_price,
                contracts=contracts, market_close_time=close_time,
                observation=True,
            )
            return pos

        # LIVE EXECUTION
        print(f"    Placing orders...")

        yes_result = self.client.place_order(
            ticker=ticker, side="yes", action="buy",
            count=contracts, price=yes_price,
        )
        if "error" in yes_result:
            print(f"    ERROR placing YES buy: {yes_result}")
            return None

        no_result = self.client.place_order(
            ticker=ticker, side="no", action="buy",
            count=contracts, price=no_price,
        )
        if "error" in no_result:
            print(f"    ERROR placing NO buy: {no_result}")
            print(f"    WARNING: YES leg placed but NO failed — directional exposure!")
            # Still record the partial entry
            pos = self.tracker.open_straddle(
                ticker=ticker, series=series,
                yes_entry_price=yes_price, no_entry_price=no_price,
                contracts=contracts, market_close_time=close_time,
                observation=False,
            )
            pos.status = "partial_exit"  # Only one leg filled
            self.tracker.save_state()
            return pos

        print(f"    Both legs placed successfully!")
        pos = self.tracker.open_straddle(
            ticker=ticker, series=series,
            yes_entry_price=yes_price, no_entry_price=no_price,
            contracts=contracts, market_close_time=close_time,
            observation=False,
        )
        return pos

    # ==========================================================
    # PHASE 2: PRICE MONITORING
    # ==========================================================

    def monitor_straddle(self, pos):
        """
        Monitor an open straddle, polling the orderbook for price movement.
        Returns when an exit trigger fires or timeout is reached.

        Returns: (exit_side, exit_price, exit_reason)
          exit_side: "yes", "no", "both", or "timeout"
          exit_price: price in cents (or None for timeout)
          exit_reason: string describing why we're exiting
        """
        ticker = pos.ticker
        entry_time = datetime.now()
        tick_count = 0

        print(f"\n  MONITORING: {ticker}")
        print(f"    Entry: YES@{pos.yes_entry_price}c + NO@{pos.no_entry_price}c")
        print(f"    Target: +{EXIT_PROFIT_TARGET_CENTS}c on either side")
        print(f"    Timeout: {EXIT_TIMEOUT_SECONDS}s")
        print()

        tick_log = os.path.join(DATA_DIR, f"ticks_{ticker}_{entry_time.strftime('%H%M%S')}.jsonl")

        while True:
            elapsed = (datetime.now() - entry_time).total_seconds()
            tick_count += 1

            # Get fresh orderbook
            try:
                ob_raw = self.client.get_orderbook(ticker)
                ob = parse_orderbook(ob_raw)
            except Exception as e:
                print(f"    Tick #{tick_count}: ERROR {e}")
                time.sleep(POLL_INTERVAL_SECONDS)
                continue

            if ob is None:
                print(f"    Tick #{tick_count}: empty orderbook")
                time.sleep(POLL_INTERVAL_SECONDS)
                continue

            # Current exit prices (what we'd receive selling)
            current_yes_bid = ob["yes_bid"]
            current_no_bid = ob["no_bid"]

            # P&L calculation
            # We BOUGHT YES at yes_entry_price (which was 100 - max_no_bid at entry)
            # We can SELL YES at current_yes_bid (the highest YES bid now)
            # The P&L depends on how we entered. If we entered by buying YES at
            # yes_ask, we paid yes_entry_price cents. Now we can sell at current_yes_bid.
            # But wait — on Kalshi, buying YES at X cents means we OWN a YES contract
            # worth X cents. Selling it at the YES bid gives us the bid price.
            # P&L = sell_price - buy_price = current_yes_bid - yes_entry_price
            #
            # HOWEVER: yes_entry_price = 100 - max_no_bid_at_entry (the implied ask)
            # and current_yes_bid is on the YES side of the current book.
            # These are DIFFERENT things — entry used NO-side to derive YES cost,
            # but exit uses YES-side directly.

            yes_pnl = current_yes_bid - pos.yes_entry_price
            no_pnl = current_no_bid - pos.no_entry_price

            # Log tick
            tick_entry = {
                "tick": tick_count,
                "elapsed_s": round(elapsed, 1),
                "yes_bid": current_yes_bid,
                "no_bid": current_no_bid,
                "yes_pnl": yes_pnl,
                "no_pnl": no_pnl,
                "yes_depth": ob["yes_bid_depth"],
                "no_depth": ob["no_bid_depth"],
            }
            with open(tick_log, "a") as f:
                f.write(json.dumps(tick_entry) + "\n")

            # Print periodic update
            if tick_count % 15 == 1:  # Every ~30 seconds
                print(f"    [{elapsed:.0f}s] YES bid:{current_yes_bid}c (pnl:{yes_pnl:+d}c) | "
                      f"NO bid:{current_no_bid}c (pnl:{no_pnl:+d}c)")

            # === EXIT TRIGGERS ===

            # Trigger A: YES side hit target — HOLD (never-sell-YES)
            if yes_pnl >= EXIT_PROFIT_TARGET_CENTS:
                print(f"\n    YES +{yes_pnl}c — holding (never-sell-YES)")
                # Don't return — fall through to check NO trigger

            # Trigger B: NO side hit target
            if no_pnl >= EXIT_PROFIT_TARGET_CENTS:
                print(f"\n    EXIT TRIGGER: NO +{no_pnl}c >= target +{EXIT_PROFIT_TARGET_CENTS}c")
                return ("no", current_no_bid, f"profit_target_no_{no_pnl}c")

            # Trigger C: Timeout — sell NO only, hold YES to settlement
            if elapsed >= EXIT_TIMEOUT_SECONDS:
                print(f"\n    TIMEOUT: selling NO, holding YES to expiry")
                return ("no", current_no_bid, "timeout_hold_yes")

            # Trigger D: Market close approaching — sell NO, hold YES to settlement
            if pos.market_close_time:
                try:
                    # Parse ISO close time
                    close_str = pos.market_close_time
                    if close_str.endswith("Z"):
                        close_str = close_str[:-1] + "+00:00"
                    close_dt = datetime.fromisoformat(close_str)
                    # Convert to local (naive) for comparison
                    close_utc_ts = calendar.timegm(close_dt.timetuple())
                    now_utc_ts = calendar.timegm(datetime.utcnow().timetuple())
                    secs_to_close = close_utc_ts - now_utc_ts
                    if secs_to_close < EXIT_BEFORE_CLOSE_SECONDS:
                        print(f"\n    CLOSE: selling NO, holding YES to settlement")
                        return ("no", current_no_bid, f"market_close_{secs_to_close:.0f}s")
                except Exception:
                    pass  # If we can't parse close time, rely on timeout

            time.sleep(POLL_INTERVAL_SECONDS)

    # ==========================================================
    # PHASE 3: EXIT EXECUTION
    # ==========================================================

    def exit_straddle(self, pos, exit_side, exit_price, exit_reason):
        """
        Execute the exit trade(s) for a straddle.

        exit_side: "yes", "no", or "both"
        exit_price: price in cents for the triggered side (None for "both"/timeout)
        exit_reason: human-readable reason string
        """
        ticker = pos.ticker
        contracts = pos.contracts

        print(f"\n  EXITING: {ticker} — {exit_reason}")

        if exit_side == "both":
            # Never-sell-YES: even on "both" trigger, only sell NO
            try:
                ob_raw = self.client.get_orderbook(ticker)
                ob = parse_orderbook(ob_raw)
            except Exception as e:
                print(f"    ERROR getting exit prices: {e}")
                self.tracker.close_at_expiry(ticker)
                return

            if ob:
                self._execute_sell(pos, "no", ob["no_bid"], contracts)
                print(f"    Holding {contracts}x YES to settlement (never-sell-YES)")
            else:
                print(f"    Empty orderbook — holding both to settlement")
                self.tracker.close_at_expiry(ticker)
                return
        else:
            # Sell the profitable side, hold remaining to expiry
            self._execute_sell(pos, exit_side, exit_price, contracts)
            other_side = "NO" if exit_side == "yes" else "YES"
            print(f"    Holding {contracts}x {other_side} to expiry")

        # Print P&L summary
        self._print_pnl_summary(pos)

    def _execute_sell(self, pos, side, price, qty):
        """Place a single sell order."""
        ticker = pos.ticker

        if OBSERVATION_MODE:
            print(f"    [OBS] Would sell {qty}x {side.upper()} @ {price}c")
            self.tracker.record_exit(ticker, side, price, qty)
            return

        print(f"    Selling {qty}x {side.upper()} @ {price}c...")
        result = self.client.place_order(
            ticker=ticker, side=side, action="sell",
            count=qty, price=price,
        )
        if "error" in result:
            print(f"    SELL ERROR: {result}")
            # Try at bid - 1c
            retry_price = max(1, price - 1)
            print(f"    Retrying at {retry_price}c...")
            result = self.client.place_order(
                ticker=ticker, side=side, action="sell",
                count=qty, price=retry_price,
            )
            if "error" in result:
                print(f"    RETRY FAILED: {result}")
                return
            price = retry_price

        self.tracker.record_exit(ticker, side, price, qty)
        print(f"    Sold {qty}x {side.upper()} @ {price}c")

    def _print_pnl_summary(self, pos):
        """Print P&L summary for a straddle."""
        print(f"\n  {'='*50}")
        print(f"  P&L SUMMARY: {pos.ticker}")
        print(f"  {'='*50}")
        print(f"    Entry: YES@{pos.yes_entry_price}c + "
              f"NO@{pos.no_entry_price}c = "
              f"{pos.combined_entry_cents}c")
        print(f"    Contracts: {pos.contracts} per side")
        print(f"    Total cost: {pos.total_cost_cents}c "
              f"(${pos.total_cost_cents/100:.2f})")

        if pos.yes_exit_price is not None:
            yes_pnl = (pos.yes_exit_price - pos.yes_entry_price) * pos.yes_sold
            print(f"    YES exit: {pos.yes_sold}x @ {pos.yes_exit_price}c "
                  f"(pnl: {yes_pnl:+d}c)")
        if pos.no_exit_price is not None:
            no_pnl = (pos.no_exit_price - pos.no_entry_price) * pos.no_sold
            print(f"    NO exit:  {pos.no_sold}x @ {pos.no_exit_price}c "
                  f"(pnl: {no_pnl:+d}c)")

        remaining_yes = pos.contracts - pos.yes_sold
        remaining_no = pos.contracts - pos.no_sold
        if remaining_yes > 0 or remaining_no > 0:
            hedged = min(remaining_yes, remaining_no)
            print(f"    Remaining: {remaining_yes} YES + {remaining_no} NO "
                  f"({hedged} hedged → ${hedged:.2f} guaranteed)")

        if pos.pnl_cents is not None:
            sign = "+" if pos.pnl_cents >= 0 else ""
            print(f"    Net P&L: {sign}{pos.pnl_cents}c "
                  f"(${pos.pnl_cents/100:.2f})")

        obs_tag = " [OBSERVATION]" if pos.observation else ""
        print(f"    Status: {pos.status}{obs_tag}")

    # ==========================================================
    # CONTINUOUS MODE — non-blocking scan + monitor loop
    # ==========================================================

    def _seconds_to_close(self, pos):
        """Return seconds until market close, or inf if unknown."""
        if not pos.market_close_time:
            return float('inf')
        try:
            close_str = pos.market_close_time
            if close_str.endswith("Z"):
                close_str = close_str[:-1] + "+00:00"
            close_dt = datetime.fromisoformat(close_str)
            close_utc_ts = calendar.timegm(close_dt.timetuple())
            now_utc_ts = calendar.timegm(datetime.utcnow().timetuple())
            return close_utc_ts - now_utc_ts
        except Exception:
            return float('inf')

    def _is_market_expired(self, pos):
        """Return True if the market close time has passed."""
        return self._seconds_to_close(pos) <= 0

    def _compute_elapsed(self, close_time):
        """Compute seconds elapsed since market open (900s window)."""
        if not close_time:
            return None
        try:
            ct = close_time
            if ct.endswith("Z"):
                ct = ct[:-1] + "+00:00"
            close_dt = datetime.fromisoformat(ct)
            close_utc = calendar.timegm(close_dt.timetuple())
            now_utc = calendar.timegm(datetime.utcnow().timetuple())
            return round(900 - (close_utc - now_utc), 1)
        except Exception:
            return None

    def check_position_exits(self):
        """
        Non-blocking, single-pass exit check across ALL positions.

        Position lifecycle:
          "open"         → actively monitoring, check profit targets
          "partial_exit" → one side sold, holding remaining to expiry
          "closed"/"expired" → done, skip

        Returns list of (pos, exit_side, exit_price, exit_reason) for exits.
        """
        exits = []

        # --- Pass 1: ACTIVE positions (status == "open") ---
        # Check profit targets, timeout, market close
        for pos in list(self.tracker.positions.values()):
            if pos.status != "open":
                continue

            ticker = pos.ticker

            # Get fresh orderbook
            try:
                ob_raw = self.client.get_orderbook(ticker)
                ob = parse_orderbook(ob_raw)
            except Exception as e:
                print(f"    [{ticker}] orderbook error: {e}")
                continue

            if ob is None:
                if self._is_market_expired(pos):
                    print(f"    [{ticker}] market expired, closing at expiry")
                    self.tracker.close_at_expiry(ticker)
                continue

            # Current prices
            current_yes_bid = ob["yes_bid"]
            current_no_bid = ob["no_bid"]

            # P&L
            yes_pnl = current_yes_bid - pos.yes_entry_price
            no_pnl = current_no_bid - pos.no_entry_price

            # Log tick
            entry_dt = datetime.fromisoformat(pos.entry_time)
            elapsed = (datetime.now() - entry_dt).total_seconds()
            tick_log = os.path.join(DATA_DIR, f"ticks_{ticker}.jsonl")
            tick_entry = {
                "ts": datetime.now().isoformat(),
                "elapsed_s": round(elapsed, 1),
                "yes_bid": current_yes_bid,
                "no_bid": current_no_bid,
                "yes_pnl": yes_pnl,
                "no_pnl": no_pnl,
                "yes_depth": ob["yes_bid_depth"],
                "no_depth": ob["no_bid_depth"],
            }
            with open(tick_log, "a") as f:
                f.write(json.dumps(tick_entry) + "\n")

            # === EXIT TRIGGERS (only for "open" positions) ===

            # Trigger A: YES profit target — HOLD (never-sell-YES)
            # YES settling 56% means selling YES is selling the likely winner.
            if yes_pnl >= EXIT_PROFIT_TARGET_CENTS:
                print(f"    [{ticker}] YES +{yes_pnl}c — holding (never-sell-YES)")
                # Don't exit — fall through to check NO trigger

            # Trigger B: NO profit target
            if no_pnl >= EXIT_PROFIT_TARGET_CENTS:
                print(f"    [{ticker}] EXIT: NO +{no_pnl}c hit target")
                exits.append((pos, "no", current_no_bid, f"profit_target_no_{no_pnl}c"))
                continue

            # Trigger C: Market close approaching — sell NO, hold YES to settlement
            secs_to_close = self._seconds_to_close(pos)
            if secs_to_close < EXIT_BEFORE_CLOSE_SECONDS:
                print(f"    [{ticker}] CLOSE: selling NO, holding YES to settlement")
                exits.append((pos, "no", current_no_bid, f"market_close_{secs_to_close:.0f}s"))
                continue

            # Trigger D: Timeout — sell NO only, hold YES to settlement
            if elapsed >= EXIT_TIMEOUT_SECONDS:
                print(f"    [{ticker}] TIMEOUT: selling NO, holding YES to expiry")
                exits.append((pos, "no", current_no_bid, "timeout_hold_yes"))
                continue

        # Execute all triggered exits
        for pos, exit_side, exit_price, exit_reason in exits:
            self.exit_straddle(pos, exit_side, exit_price, exit_reason)

        # --- Pass 2: HOLDING positions (status == "partial_exit") ---
        # Only check for market expiry — no more active trading
        for pos in list(self.tracker.positions.values()):
            if pos.status != "partial_exit":
                continue

            if self._is_market_expired(pos):
                print(f"    [{pos.ticker}] holding expired, settling")
                self.tracker.close_at_expiry(pos.ticker)
            elif self._seconds_to_close(pos) < EXIT_BEFORE_CLOSE_SECONDS:
                print(f"    [{pos.ticker}] holding → market closing, settling")
                self.tracker.close_at_expiry(pos.ticker)

        return exits

    def scan_for_entries(self):
        """
        Scan all crypto series for entry opportunities.
        Skips any series where we already have a position (open or holding).
        Respects per-series cooldown after exit.
        Applies quality filters: combined entry, imbalance, skip hours.

        Returns list of positions entered this tick.
        """
        if not STRADDLE_ENTRIES_ENABLED:
            return []

        # Skip restricted hours
        if datetime.now().hour in SKIP_HOURS:
            return []

        # Skip series with ANY active position (open, partial_exit, etc.)
        active_positions = [p for p in self.tracker.positions.values()
                           if p.status in ("open", "partial_exit")]
        open_series = {pos.series for pos in active_positions}
        open_tickers = {pos.ticker for pos in active_positions}

        # Respect max simultaneous positions
        if len(active_positions) >= MAX_SIMULTANEOUS_POSITIONS:
            return []

        # Daily limit check (live mode only)
        if not OBSERVATION_MODE:
            stats = self.tracker.get_daily_stats()
            if stats["daily_straddles"] >= MAX_DAILY_STRADDLES:
                return []

        new_entries = []

        entered = getattr(self, '_entered_tickers', set())

        for series in CRYPTO_SERIES:
            if series in open_series:
                continue  # Already have a position in this series

            # Fetch open market for this series
            try:
                result = self.client.get_markets(
                    status="open", limit=1, series_ticker=series
                )
                markets = result.get("markets", [])
            except Exception:
                continue

            if not markets:
                continue

            market = markets[0]
            ticker = market.get("ticker", "")

            # Skip if already entered this exact ticker (same market window)
            if ticker in open_tickers or ticker in self.tracker.positions or ticker in entered:
                continue

            # Get orderbook and check entry criteria
            try:
                ob_raw = self.client.get_orderbook(ticker)
                ob = parse_orderbook(ob_raw)
            except Exception:
                continue

            if ob is None:
                continue

            if ob["combined_ask"] > MAX_COMBINED_ENTRY_CENTS:
                continue
            if ob["yes_ask"] >= MAX_SINGLE_SIDE_ENTRY or ob["no_ask"] >= MAX_SINGLE_SIDE_ENTRY:
                continue  # Market already decided — no straddle opportunity
            if abs(ob["yes_ask"] - ob["no_ask"]) < MIN_IMBALANCE_CENTS:
                continue  # Balanced entries are net-negative
            if ob["yes_bid_depth"] < MIN_ORDERBOOK_DEPTH:
                continue
            if ob["no_bid_depth"] < MIN_ORDERBOOK_DEPTH:
                continue

            # Enter!
            pos = self.enter_straddle(market, ob)
            if pos:
                new_entries.append(pos)
                self._entered_tickers.add(ticker)

        return new_entries

    def log_passive_ticks(self):
        """
        Poll all crypto series for orderbook data and log ticks.
        Runs every loop cycle regardless of position status.
        Captures full 15-min window for momentum strategy analysis.
        """
        for series in CRYPTO_SERIES:
            try:
                result = self.client.get_markets(
                    status="open", limit=1, series_ticker=series
                )
                markets = result.get("markets", [])
            except Exception:
                continue

            if not markets:
                continue

            market = markets[0]
            ticker = market.get("ticker", "")
            close_time = market.get("close_time")

            try:
                ob_raw = self.client.get_orderbook(ticker)
                ob = parse_orderbook(ob_raw)
            except Exception:
                continue

            if ob is None:
                continue

            # Compute elapsed time from market open
            elapsed_s = self._compute_elapsed(close_time)

            tick_entry = {
                "ts": datetime.now().isoformat(),
                "ticker": ticker,
                "series": series,
                "elapsed_s": elapsed_s,
                "yes_bid": ob["yes_bid"],
                "no_bid": ob["no_bid"],
                "yes_ask": ob["yes_ask"],
                "no_ask": ob["no_ask"],
                "combined_ask": ob["combined_ask"],
                "yes_depth": ob["yes_bid_depth"],
                "no_depth": ob["no_bid_depth"],
            }

            tick_log = os.path.join(DATA_DIR, f"passive_ticks_{ticker}.jsonl")
            with open(tick_log, "a") as f:
                f.write(json.dumps(tick_entry) + "\n")

    def scan_momentum_entries(self):
        """
        Scan all crypto series for momentum entry signals.

        Strategy: At T~420s (7 min into 15-min window), buy whichever side
        has bid >= 60c. Direction-agnostic — works for both YES and NO leaders.
        Hold to settlement.

        Returns list of tickers entered this tick.
        """
        if not MOMENTUM_ENABLED:
            return []

        is_skip_hour = datetime.now().hour in SKIP_HOURS

        # Track which tickers we've already entered (momentum)
        entered = getattr(self, '_momentum_entered', set())

        # Daily limit check
        daily_count = getattr(self, '_momentum_daily_count', 0)
        daily_exposure = getattr(self, '_momentum_daily_exposure', 0)
        if not OBSERVATION_MODE and daily_count >= MOMENTUM_MAX_DAILY:
            return []

        new_entries = []

        for series in CRYPTO_SERIES:
            # Skip if already have any active position in this series
            active = [p for p in self.tracker.positions.values()
                      if p.status in ("open", "partial_exit") and p.series == series]
            if active:
                continue

            try:
                result = self.client.get_markets(
                    status="open", limit=1, series_ticker=series
                )
                markets = result.get("markets", [])
            except Exception:
                continue

            if not markets:
                continue

            market = markets[0]
            ticker = market.get("ticker", "")
            close_time = market.get("close_time")

            # Skip if already entered this ticker
            if ticker in entered or ticker in self.tracker.positions:
                continue

            # Compute elapsed seconds
            elapsed_s = self._compute_elapsed(close_time)
            if elapsed_s is None:
                continue

            # Check if we're in the entry window (T=420 +/- 15s)
            entry_start = MOMENTUM_ENTRY_SECONDS - MOMENTUM_ENTRY_WINDOW // 2
            entry_end = MOMENTUM_ENTRY_SECONDS + MOMENTUM_ENTRY_WINDOW // 2
            if not (entry_start <= elapsed_s <= entry_end):
                continue

            # Get orderbook
            try:
                ob_raw = self.client.get_orderbook(ticker)
                ob = parse_orderbook(ob_raw)
            except Exception:
                continue

            if ob is None:
                continue

            yes_bid = ob["yes_bid"]
            no_bid = ob["no_bid"]
            leader_bid = max(yes_bid, no_bid)

            # Determine which side to buy and its ask price
            if yes_bid >= no_bid:
                buy_side = "yes"
                buy_ask = ob["yes_ask"]
                depth = ob["yes_bid_depth"]
            else:
                buy_side = "no"
                buy_ask = ob["no_ask"]
                depth = ob["no_bid_depth"]

            # Determine effective min bid (higher threshold overnight)
            current_hour = datetime.now().hour
            is_overnight = current_hour >= MOMENTUM_OVERNIGHT_START_HOUR or current_hour < MOMENTUM_OVERNIGHT_END_HOUR
            effective_min_bid = MOMENTUM_OVERNIGHT_MIN_BID if is_overnight else MOMENTUM_MIN_BID

            # ── Bayesian Signal Evaluation ──
            bayesian_signal = None
            if self.bayesian is not None:
                bayesian_signal = self.bayesian.evaluate(
                    leader_bid=leader_bid,
                    buy_ask=buy_ask,
                    series=series,
                    hour=current_hour,
                    depth=depth,
                )

            if leader_bid < effective_min_bid:
                # Shadow-log sub-threshold signals for observation
                if MOMENTUM_SHADOW_MIN_BID and leader_bid >= MOMENTUM_SHADOW_MIN_BID:
                    shadow_entry = {
                        "ts": datetime.now().isoformat(),
                        "ticker": ticker,
                        "series": series,
                        "side": buy_side,
                        "leader_bid": leader_bid,
                        "ask": buy_ask,
                        "elapsed_s": round(elapsed_s, 1) if elapsed_s else None,
                    }
                    shadow_path = os.path.join(DATA_DIR, "momentum_shadow_obs.jsonl")
                    with open(shadow_path, "a") as f:
                        f.write(json.dumps(shadow_entry) + "\n")
                # Log Bayesian evaluation even for sub-threshold signals
                if bayesian_signal is not None and BAYESIAN_SHADOW_MODE:
                    self._log_bayesian_decision(ticker, series, bayesian_signal,
                                                entered=False, mode="shadow",
                                                reason="sub_threshold")
                continue  # No signal

            # ── Entry Decision: Bayesian LIVE vs Static ──
            if BAYESIAN_ENABLED and bayesian_signal is not None:
                # LIVE Bayesian mode: Kelly controls entry and sizing
                if not self.bayesian.should_enter(bayesian_signal):
                    self._log_bayesian_decision(ticker, series, bayesian_signal,
                                                entered=False, mode="live",
                                                reason="kelly_negative")
                    continue  # Bayesian says skip
                contracts = bayesian_signal.recommended_contracts
                # Log the live decision
                self._log_bayesian_decision(ticker, series, bayesian_signal,
                                            entered=True, mode="live")
            else:
                # Static conviction sizing (original logic)
                contracts = 3  # default minimum
                for bid_level in sorted(MOMENTUM_CONVICTION_TIERS.keys(), reverse=True):
                    if leader_bid >= bid_level:
                        contracts = MOMENTUM_CONVICTION_TIERS[bid_level]
                        break
                # Shadow-log what Bayesian WOULD have done
                if bayesian_signal is not None and BAYESIAN_SHADOW_MODE:
                    self._log_bayesian_decision(ticker, series, bayesian_signal,
                                                entered=True, mode="shadow",
                                                static_contracts=contracts)

            # Exposure check
            entry_cost = buy_ask * contracts
            if not OBSERVATION_MODE and daily_exposure + entry_cost > MOMENTUM_MAX_DAILY_EXPOSURE:
                continue

            # Shadow-log skip-hour signals (evaluate but don't enter)
            if is_skip_hour:
                skip_entry = {
                    "ts": datetime.now().isoformat(),
                    "ticker": ticker,
                    "series": series,
                    "side": buy_side,
                    "leader_bid": leader_bid,
                    "ask": buy_ask,
                    "contracts": contracts,
                    "entry_cost_cents": entry_cost,
                    "elapsed_s": round(elapsed_s, 1),
                    "hour": datetime.now().hour,
                    "skipped": True,
                }
                skip_path = os.path.join(DATA_DIR, "momentum_skiphour_obs.jsonl")
                with open(skip_path, "a") as f:
                    f.write(json.dumps(skip_entry) + "\n")
                continue

            # Enter!
            print(f"\n  MOMENTUM ENTRY: {ticker}")
            print(f"    Elapsed: {elapsed_s:.0f}s | Leader: {buy_side.upper()} bid={leader_bid}c ask={buy_ask}c")
            if bayesian_signal:
                mode_tag = "BAYES" if BAYESIAN_ENABLED else "STATIC"
                print(f"    [{mode_tag}] Contracts: {contracts} | "
                      f"P(win)={bayesian_signal.posterior:.1%} "
                      f"Kelly={bayesian_signal.kelly_fraction:+.3f} "
                      f"EV={bayesian_signal.ev_per_contract_cents:+.1f}c/ct "
                      f"conf={bayesian_signal.confidence}")
            else:
                print(f"    Contracts: {contracts} (conviction tier: bid>={leader_bid}c)")
            print(f"    Cost: {entry_cost}c (${entry_cost/100:.2f})")

            taker_fees = 0
            if OBSERVATION_MODE:
                print(f"    [OBSERVATION MODE — logging entry, not executing]")
            else:
                order_result = self.client.place_order(
                    ticker=ticker, side=buy_side, action="buy",
                    count=contracts, price=buy_ask,
                )
                if "error" in order_result:
                    print(f"    ERROR placing {buy_side.upper()} buy: {order_result}")
                    continue
                taker_fees = order_result.get("order", {}).get("taker_fees", 0)
                print(f"    Order placed successfully! (fees: {taker_fees}c)")

            # Record as a "straddle" entry with only one side filled
            # This lets existing settlement tracking work unchanged
            if buy_side == "yes":
                pos = self.tracker.open_straddle(
                    ticker=ticker, series=series,
                    yes_entry_price=buy_ask, no_entry_price=0,
                    contracts=contracts, market_close_time=close_time,
                    observation=OBSERVATION_MODE,
                )
            else:
                pos = self.tracker.open_straddle(
                    ticker=ticker, series=series,
                    yes_entry_price=0, no_entry_price=buy_ask,
                    contracts=contracts, market_close_time=close_time,
                    observation=OBSERVATION_MODE,
                )

            # Store taker fees from Kalshi
            pos.taker_fees = taker_fees

            # Mark as momentum entry + immediately partial_exit (hold to settlement)
            pos.status = "partial_exit"  # triggers settlement tracking
            # Store which side we bought for settlement P&L
            if buy_side == "yes":
                pos.no_sold = contracts  # mark NO as "sold" at 0c (not held)
                pos.no_exit_price = 0
            else:
                pos.yes_sold = contracts  # mark YES as "sold" at 0c (not held)
                pos.yes_exit_price = 0
            pos.exit_time = datetime.now().isoformat()
            self.tracker.save_state()

            entered.add(ticker)
            self._momentum_entered = entered
            daily_count += 1
            daily_exposure += entry_cost
            self._momentum_daily_count = daily_count
            self._momentum_daily_exposure = daily_exposure

            new_entries.append(ticker)

        return new_entries

    # Hours that were previously hard-blocked, now Bayesian-managed
    _FORMERLY_SKIPPED_HOURS = {3, 11, 13, 14, 20, 23}

    def _log_bayesian_decision(self, ticker, series, signal, entered, mode,
                                static_contracts=None, reason=None):
        """Log Bayesian signal evaluation to bayesian_decisions.jsonl."""
        hour = signal.features.get("hour", datetime.now().hour)
        entry = {
            "ts": datetime.now().isoformat(),
            "ticker": ticker,
            "series": series,
            "mode": mode,
            "entered": entered,
            "posterior": round(signal.posterior, 4),
            "confidence": signal.confidence,
            "kelly_fraction": round(signal.kelly_fraction, 4),
            "recommended_contracts": signal.recommended_contracts,
            "ev_per_contract": round(signal.ev_per_contract_cents, 2),
            "bankroll_cents": signal.bankroll_cents,
            "features": signal.features,
            "breakdown": signal.breakdown,
            "old_decision": signal.old_decision,
            "formerly_skipped_hour": hour in self._FORMERLY_SKIPPED_HOURS,
        }
        if static_contracts is not None:
            entry["static_contracts"] = static_contracts
        if reason:
            entry["reason"] = reason

        log_path = os.path.join(DATA_DIR, "bayesian_decisions.jsonl")
        with open(log_path, "a") as f:
            f.write(json.dumps(entry) + "\n")

    def monitor_momentum_stoploss(self):
        """
        OBSERVATION-ONLY stop-loss monitor for momentum positions.

        Runs every loop tick alongside live trading. For each active momentum
        position, checks if the held side's bid has dropped below entry price
        by more than each configured threshold. Logs what WOULD happen at each
        threshold level to straddle_stoploss_obs.jsonl for later analysis.

        CRITICAL: This method NEVER:
          - Calls self.tracker.record_exit()
          - Calls self.client.place_order()
          - Modifies any position attributes
          - Changes position status
        """
        # Track peak bids across ticks (persists between calls)
        peak_bids = getattr(self, '_stoploss_peak_bids', {})

        for pos in list(self.tracker.positions.values()):
            # Only monitor live momentum positions (partial_exit, not observation)
            if pos.status != "partial_exit":
                continue
            if pos.observation:
                continue

            ticker = pos.ticker

            # Skip expired markets (settlement handles those)
            if self._is_market_expired(pos):
                # Clean up peak tracking for expired positions
                peak_bids.pop(ticker, None)
                continue

            # Determine which side we're holding
            if pos.no_sold > 0 and pos.yes_sold == 0:
                held_side = "yes"
                entry_price = pos.yes_entry_price
            elif pos.yes_sold > 0 and pos.no_sold == 0:
                held_side = "no"
                entry_price = pos.no_entry_price
            else:
                continue  # Not a momentum position (both sides or neither)

            if entry_price <= 0:
                continue  # Skip malformed entries

            # Get fresh orderbook
            try:
                ob_raw = self.client.get_orderbook(ticker)
                ob = parse_orderbook(ob_raw)
            except Exception:
                continue

            if ob is None:
                continue

            # Current bid for our held side
            current_bid = ob["yes_bid"] if held_side == "yes" else ob["no_bid"]

            # Track peak bid since entry
            if ticker not in peak_bids or current_bid > peak_bids[ticker]:
                peak_bids[ticker] = current_bid
            peak_bid = peak_bids[ticker]

            # Compute drops
            drop_from_entry = current_bid - entry_price
            drop_from_peak = current_bid - peak_bid

            # Compute elapsed time
            elapsed_s = None
            try:
                entry_dt = datetime.fromisoformat(pos.entry_time)
                elapsed_s = (datetime.now() - entry_dt).total_seconds()
            except Exception:
                pass

            # Check which thresholds would be hit
            thresholds_hit = [t for t in MOMENTUM_STOPLOSS_THRESHOLDS
                              if drop_from_entry <= t]

            # Hypothetical exit P&L if we sold at current bid
            contracts = pos.contracts
            hypothetical_exit_pnl = (current_bid - entry_price) * contracts

            # Log to observation file
            if thresholds_hit or drop_from_entry < 0:
                obs_entry = {
                    "ts": datetime.now().isoformat(),
                    "ticker": ticker,
                    "side": held_side,
                    "entry_price": entry_price,
                    "current_bid": current_bid,
                    "drop": drop_from_entry,
                    "peak_bid": peak_bid,
                    "peak_drop": drop_from_peak,
                    "elapsed_s": round(elapsed_s, 1) if elapsed_s else None,
                    "contracts": contracts,
                    "thresholds_hit": thresholds_hit,
                    "hypothetical_exit_pnl": hypothetical_exit_pnl,
                }

                obs_path = os.path.join(DATA_DIR, "straddle_stoploss_obs.jsonl")
                with open(obs_path, "a") as f:
                    f.write(json.dumps(obs_entry) + "\n")

            # Print one-line summary when any threshold is hit
            if thresholds_hit:
                series_short = self._derive_series(ticker).replace("KX", "").replace("15M", "")
                thresholds_str = ", ".join(f"{t}c" for t in thresholds_hit)
                print(f"    [STOP-LOSS OBS] {series_short} {held_side.upper()}@{entry_price}c "
                      f"→ bid={current_bid}c ({drop_from_entry:+d}c) "
                      f"would trigger at {thresholds_str}")

        self._stoploss_peak_bids = peak_bids

    def execute_correlated_stoploss(self):
        """
        LIVE correlated stop-loss for momentum positions.

        Groups active positions by 15-min window. When 2+ series in the same
        window have dropped >= MOMENTUM_STOPLOSS_DROP cents from entry,
        immediately sells ALL breaching positions in that window.

        Uses _execute_sell() which calls record_exit() → status="closed".
        """
        # Gather all active momentum positions with their current drops
        window_positions = defaultdict(list)  # window_key -> [(pos, held_side, entry_price, current_bid, drop)]

        for pos in list(self.tracker.positions.values()):
            if pos.status != "partial_exit":
                continue
            if pos.observation:
                continue

            ticker = pos.ticker

            # Skip expired markets
            if self._is_market_expired(pos):
                continue

            # Determine held side and entry price
            if pos.no_sold > 0 and pos.yes_sold == 0:
                held_side = "yes"
                entry_price = pos.yes_entry_price
            elif pos.yes_sold > 0 and pos.no_sold == 0:
                held_side = "no"
                entry_price = pos.no_entry_price
            else:
                continue

            if entry_price <= 0:
                continue

            # Get fresh orderbook
            try:
                ob_raw = self.client.get_orderbook(ticker)
                ob = parse_orderbook(ob_raw)
            except Exception:
                continue

            if ob is None:
                continue

            current_bid = ob["yes_bid"] if held_side == "yes" else ob["no_bid"]
            drop = current_bid - entry_price

            # Extract window key from ticker (e.g. KXBTC15M-26MAR021500-00 → "26MAR021500")
            parts = ticker.split("-")
            window_key = parts[1] if len(parts) >= 2 else ticker

            window_positions[window_key].append((pos, held_side, entry_price, current_bid, drop))

        # Check each window for correlated breach
        for window_key, positions in window_positions.items():
            breaching = [(pos, side, ep, bid, drop)
                         for pos, side, ep, bid, drop in positions
                         if drop <= -MOMENTUM_STOPLOSS_DROP]

            if len(breaching) < MOMENTUM_STOPLOSS_MIN_SERIES:
                continue

            # CORRELATED STOP-LOSS TRIGGERED — sell all breaching positions
            window_time = window_key[-4:] if len(window_key) >= 4 else window_key
            series_names = []
            exit_records = []

            for pos, held_side, entry_price, current_bid, drop in breaching:
                series_short = self._derive_series(pos.ticker).replace("KX", "").replace("15M", "")
                series_names.append(f"{series_short}@{current_bid}c")

                print(f"    [STOP-LOSS LIVE] Selling {series_short} "
                      f"{held_side.upper()}@{entry_price}c → bid={current_bid}c ({drop:+d}c)")

                # Execute the sell
                self._execute_sell(pos, held_side, current_bid, pos.contracts)

                exit_records.append({
                    "ticker": pos.ticker,
                    "side": held_side,
                    "entry": entry_price,
                    "sold_at": current_bid,
                    "contracts": pos.contracts,
                    "pnl": drop * pos.contracts,
                })

            print(f"    [STOP-LOSS LIVE] Window :{window_time} — "
                  f"{len(breaching)} series breached -{MOMENTUM_STOPLOSS_DROP}c — "
                  f"sold {', '.join(series_names)}")

            # Log execution
            exec_entry = {
                "ts": datetime.now().isoformat(),
                "window": window_key,
                "series_count": len(breaching),
                "tickers_breaching": [pos.ticker for pos, _, _, _, _ in breaching],
                "exits": exit_records,
            }
            exec_path = os.path.join(DATA_DIR, "straddle_stoploss_exec.jsonl")
            with open(exec_path, "a") as f:
                f.write(json.dumps(exec_entry) + "\n")

    def run_continuous(self):
        """
        Unified continuous event loop for the straddle bot.

        On each tick (~3s):
          1. Check all open positions for exit triggers
          2. Scan for new entry opportunities on available series
          3. Sleep

        Handles up to 4 simultaneous straddles (one per series).
        Market rollovers are automatic: expired position gets archived,
        series becomes available, next scan enters the new market.
        """
        self._entered_tickers = set()  # tickers already entered — prevents same-window re-entry
        loop_count = 0

        print(f"\n  Continuous mode started.")
        print(f"  Loop interval: {LOOP_INTERVAL_SECONDS}s")
        print(f"  Max positions: {MAX_SIMULTANEOUS_POSITIONS}")
        print(f"  Mode: {'OBSERVATION' if OBSERVATION_MODE else '*** LIVE ***'}")
        if PASSIVE_TICK_LOGGING:
            print(f"  Passive tick logging: ON (every {PASSIVE_TICK_INTERVAL * LOOP_INTERVAL_SECONDS}s)")
        if SKIP_HOURS:
            print(f"  Skip hours (EST): {sorted(SKIP_HOURS)}")
        if MOMENTUM_ENABLED:
            print(f"  Momentum strategy: ON (T={MOMENTUM_ENTRY_SECONDS}s, bid>={MOMENTUM_MIN_BID}c)")
            print(f"  Overnight min bid: {MOMENTUM_OVERNIGHT_MIN_BID}c ({MOMENTUM_OVERNIGHT_START_HOUR}:00-{MOMENTUM_OVERNIGHT_END_HOUR}:00 EST)")
        if MOMENTUM_STOPLOSS_ENABLED:
            thresholds_str = ", ".join(f"{t}c" for t in MOMENTUM_STOPLOSS_THRESHOLDS)
            print(f"  Stop-loss observer: ON (thresholds: {thresholds_str}) [OBSERVATION ONLY]")
        if MOMENTUM_STOPLOSS_LIVE:
            print(f"  Stop-loss LIVE: ON (correlated {MOMENTUM_STOPLOSS_MIN_SERIES}+ series @ -{MOMENTUM_STOPLOSS_DROP}c)")

        if self.bayesian:
            if BAYESIAN_ENABLED:
                print(f"  Bayesian signal engine: *** LIVE *** (Kelly={KELLY_MULTIPLIER}x, max={KELLY_MAX_CONTRACTS}ct)")
            elif BAYESIAN_SHADOW_MODE:
                print(f"  Bayesian signal engine: SHADOW (logging only, static logic trades)")

        if not STRADDLE_ENTRIES_ENABLED:
            print(f"  Straddle entries: DISABLED (momentum only)")
        print()

        while True:
            loop_count += 1

            # Step 1: Check exits on all open positions
            exits = self.check_position_exits()

            # Block re-entry into exited tickers (same market window)
            for pos, _, _, _ in exits:
                self._entered_tickers.add(pos.ticker)

            # Step 1.5: Stop-loss monitor (observation logging + live correlated execution)
            if MOMENTUM_STOPLOSS_ENABLED:
                self.monitor_momentum_stoploss()
            if MOMENTUM_STOPLOSS_LIVE:
                self.execute_correlated_stoploss()

            # Step 2: Scan for new entries
            new_entries = self.scan_for_entries()

            # Step 2b: Passive tick logging (full 15-min orderbook capture)
            if PASSIVE_TICK_LOGGING and loop_count % PASSIVE_TICK_INTERVAL == 0:
                self.log_passive_ticks()

            # Step 2c: Momentum entries (buy leader at T~420s)
            if MOMENTUM_ENABLED:
                momentum_entries = self.scan_momentum_entries()

            # Step 3: Periodic status print (~every 5 min at 3s interval)
            if loop_count % 100 == 1:
                now = datetime.now().strftime('%H:%M:%S')
                open_pos = self.tracker.get_open_positions()
                open_str = ", ".join(f"{p.series}" for p in open_pos) if open_pos else "none"
                stats = self.tracker.get_daily_stats()
                print(f"  [{now}] loop #{loop_count} | "
                      f"open: {open_str} | "
                      f"daily: {stats['daily_straddles']} straddles")

                # Check for settlement results and show rolling P&L
                self.check_settlements()
                self.print_rolling_pnl()
                self.print_stats_compact()

                # Reset momentum daily counters at midnight
                from datetime import date
                today = date.today().isoformat()
                if getattr(self, '_momentum_daily_reset', '') != today:
                    self._momentum_daily_count = 0
                    self._momentum_daily_exposure = 0
                    self._momentum_daily_reset = today

            # Step 4: Sleep
            time.sleep(LOOP_INTERVAL_SECONDS)

    # ==========================================================
    # SETTLEMENT TRACKING
    # ==========================================================

    def _settle_entry(self, entry):
        """
        Try to settle a single partial-exit entry via Kalshi API.
        Returns (ticker, result, actual_pnl) or None if not yet settled.
        """
        yes_sold = entry.get("yes_sold", 0)
        no_sold = entry.get("no_sold", 0)
        contracts = entry.get("contracts", 5)

        ticker = entry.get("ticker", "")
        try:
            market_data = self.client.get_market(ticker)
            market = market_data.get("market", market_data)
            result = market.get("result", "")
            if result not in ("yes", "no"):
                return None  # Not yet settled
        except Exception:
            return None

        entry["settlement_result"] = result

        # Determine which side was held and compute payout
        held_yes = contracts - yes_sold
        held_no = contracts - no_sold

        if held_yes > 0 and held_no == 0:
            held_payout = held_yes * 100 if result == "yes" else 0
        elif held_no > 0 and held_yes == 0:
            held_payout = held_no * 100 if result == "no" else 0
        else:
            held_payout = 0

        # Compute sell proceeds from the sold side
        sell_proceeds = 0
        yes_exit = entry.get("yes_exit_price")
        no_exit = entry.get("no_exit_price")
        if yes_exit and yes_sold > 0:
            sell_proceeds += yes_exit * yes_sold
        if no_exit and no_sold > 0:
            sell_proceeds += no_exit * no_sold

        yes_entry = entry.get("yes_entry_price", 0)
        no_entry = entry.get("no_entry_price", 0)
        cost = (yes_entry + no_entry) * contracts
        fees = entry.get("taker_fees", 0)

        actual_pnl = sell_proceeds + held_payout - cost - fees
        entry["pnl_actual"] = actual_pnl

        # Backfill pnl_best_case for legacy entries
        if entry.get("pnl_best_case") is None:
            worst = sell_proceeds - cost
            best = worst + (held_yes + held_no) * 100
            entry["pnl_cents"] = worst
            entry["pnl_best_case"] = best

        held_side = "YES" if held_yes > 0 else "NO"
        won = "WON" if held_payout > 0 else "lost"
        print(f"  Settlement: {ticker} → {result.upper()} | "
              f"held {held_side} {won} | P&L: {actual_pnl:+d}c")

        return (ticker, result, actual_pnl)

    def check_settlements(self):
        """
        Check Kalshi API for settlement results on completed straddles.
        Checks both history file and active state-file positions.

        Returns list of (ticker, result, actual_pnl) for newly resolved.
        """
        resolved = []

        # === Part 1: History file entries ===
        history_path = os.path.join(DATA_DIR, "straddle_history.jsonl")
        entries = []
        if os.path.exists(history_path):
            with open(history_path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            entries.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass

        history_updated = False

        for entry in entries:
            if entry.get("settlement_result"):
                continue

            yes_sold = entry.get("yes_sold", 0)
            no_sold = entry.get("no_sold", 0)
            is_partial = (yes_sold > 0) != (no_sold > 0)
            if not is_partial:
                continue

            result = self._settle_entry(entry)
            if result:
                resolved.append(result)
                history_updated = True

        if history_updated:
            with open(history_path, "w") as f:
                for entry in entries:
                    f.write(json.dumps(entry, default=str) + "\n")

        # === Part 2: State-file positions (partial_exit not yet archived) ===
        for pos in list(self.tracker.positions.values()):
            if pos.status != "partial_exit":
                continue
            if pos.settlement_result:
                continue

            # Check if one side was sold
            is_partial = (pos.yes_sold > 0) != (pos.no_sold > 0)
            if not is_partial:
                continue

            entry = pos.to_dict()
            result = self._settle_entry(entry)
            if result:
                # Update the position object from the settled entry dict
                pos.settlement_result = entry.get("settlement_result")
                pos.pnl_cents = entry.get("pnl_cents")
                pos.pnl_best_case = entry.get("pnl_best_case")
                pos.pnl_actual = entry.get("pnl_actual")
                pos.status = "expired"

                # Archive it to history
                self.tracker._archive_position(pos)
                self.tracker.save_state()
                resolved.append(result)

        # === Part 3: Closed positions (stop-loss, both sides sold — deterministic P&L) ===
        for pos in list(self.tracker.positions.values()):
            if pos.status != "closed":
                continue
            if pos.observation:
                continue

            # P&L is deterministic — _calculate_pnl() already ran when
            # record_exit() set status="closed". pnl_cents is correct.
            pos.pnl_actual = pos.pnl_cents
            pos.settlement_result = "stoploss"

            # Check actual market settlement for analysis (was stop-loss a good call?)
            try:
                market_data = self.client.get_market(pos.ticker)
                market = market_data.get("market", market_data)
                actual_result = market.get("result", "")
                if actual_result in ("yes", "no"):
                    pos.settlement_result = f"stoploss_{actual_result}"
            except Exception:
                pass  # "stoploss" is fine — we don't need settlement to archive

            print(f"  Archiving stop-loss: {pos.ticker} | P&L: {pos.pnl_cents:+d}c | {pos.settlement_result}")

            self.tracker._archive_position(pos)
            self.tracker.save_state()
            resolved.append((pos.ticker, pos.settlement_result, pos.pnl_actual))

        return resolved

    def _load_all_straddles(self, include_observation=False):
        """Load all straddles from history + completed positions still in state.

        Args:
            include_observation: If False (default), exclude observation-mode entries.
                                Set True to include everything (for analysis scripts).
        """
        entries = []

        # 1. History file (archived positions)
        history_path = os.path.join(DATA_DIR, "straddle_history.jsonl")
        if os.path.exists(history_path):
            with open(history_path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            entry = json.loads(line)
                            if not include_observation and entry.get("observation", False):
                                continue  # Skip observation-mode entries
                            entries.append(entry)
                        except json.JSONDecodeError:
                            pass

        # 2. Completed positions still in state (closed/expired not yet archived)
        history_tickers = {e.get("ticker") for e in entries}
        for pos in self.tracker.positions.values():
            if pos.status in ("closed", "expired", "partial_exit"):
                if not include_observation and pos.observation:
                    continue  # Skip observation-mode entries
                d = pos.to_dict()
                # Avoid double-counting: skip if already in history
                # Use ticker + entry_time as dedup key (same ticker can have re-entries)
                key = (d.get("ticker"), d.get("entry_time"))
                already = any(
                    (e.get("ticker"), e.get("entry_time")) == key
                    for e in entries
                )
                if not already:
                    entries.append(d)

        return entries

    _MONTH_MAP = {
        'JAN': '01', 'FEB': '02', 'MAR': '03', 'APR': '04',
        'MAY': '05', 'JUN': '06', 'JUL': '07', 'AUG': '08',
        'SEP': '09', 'OCT': '10', 'NOV': '11', 'DEC': '12',
    }

    def _parse_ticker_date(self, ticker_date_str):
        """Parse YYMMMDD ticker date (e.g. '26FEB23') → ISO '2026-02-23'."""
        if len(ticker_date_str) >= 7:
            yy = ticker_date_str[:2]
            mmm = ticker_date_str[2:5]
            dd = ticker_date_str[5:7]
            mm = self._MONTH_MAP.get(mmm.upper())
            if mm:
                return f"20{yy}-{mm}-{dd}"
        return None

    def _group_by_window(self, entries):
        """Group straddle entries by market window (date-aware).
        Key format: '2026-02-23:1315' — ISO date from ticker + time from ticker.
        Uses the ticker's embedded date (YYMMMDD) so midnight markets sort correctly."""
        windows = {}
        for e in entries:
            ticker = e.get("ticker", "")
            parts = ticker.split("-")
            time_part = parts[1][-4:] if len(parts) >= 2 and len(parts[1]) >= 4 else "?"
            # Use ticker date (YYMMMDD) — correct market date even for midnight entries
            ticker_date = parts[1][:-4] if len(parts) >= 2 and len(parts[1]) > 4 else ""
            date_part = self._parse_ticker_date(ticker_date) if ticker_date else None
            # Fallback to entry_time if ticker date can't be parsed
            if not date_part:
                date_part = e.get("entry_time", "")[:10]
            window = f"{date_part}:{time_part}" if date_part else time_part
            if window not in windows:
                windows[window] = []
            windows[window].append(e)
        return windows

    def _compute_capital_metrics(self, entries):
        """Compute peak concurrent capital and capital turns.

        Builds a timeline of capital in/out events from entry_time and
        exit_time of each straddle to find the maximum capital deployed
        at any single instant.

        Returns (peak_capital, total_wagered, capital_turns).
        """
        from datetime import datetime as _dt
        events = []  # (timestamp_str, delta_cents)
        total_wagered = 0
        for s in entries:
            contracts = s.get("contracts", 5)
            combined = s.get("yes_entry_price", 0) + s.get("no_entry_price", 0)
            cost = combined * contracts
            total_wagered += cost

            entry_t = s.get("entry_time", "")
            exit_t = s.get("exit_time", "")
            if entry_t:
                events.append((entry_t, cost))
            if exit_t:
                events.append((exit_t, -cost))

        if not events:
            return (0, 0, 0)

        events.sort(key=lambda x: x[0])

        current = 0
        peak = 0
        for _, delta in events:
            current += delta
            if current > peak:
                peak = current

        turns = (total_wagered / peak) if peak > 0 else 0
        return (peak, total_wagered, turns)

    def print_rolling_pnl(self):
        """Print a compact rolling P&L summary by window with return %."""
        entries = self._load_all_straddles()
        if not entries:
            return

        windows = self._group_by_window(entries)

        rolling = 0
        rolling_cost = 0
        unsettled_worst = 0
        unsettled_best = 0
        lines = []

        for window in sorted(windows.keys()):
            straddles = windows[window]
            w_pnl = 0
            w_cost = 0
            w_unsettled = 0
            w_worst = 0
            w_best = 0
            all_settled = True

            for s in straddles:
                # Entry cost for this straddle
                contracts = s.get("contracts", 5)
                combined = (s.get("yes_entry_price", 0) + s.get("no_entry_price", 0))
                cost = combined * contracts
                w_cost += cost

                actual = s.get("pnl_actual")
                if actual is not None:
                    w_pnl += actual
                elif s.get("status") == "closed":
                    w_pnl += s.get("pnl_cents", 0) or 0
                elif s.get("status") == "expired" and s.get("yes_sold", 0) == 0 and s.get("no_sold", 0) == 0:
                    # Fully hedged — deterministic
                    w_pnl += s.get("pnl_cents", 0) or 0
                else:
                    # Unsettled partial exit
                    all_settled = False
                    w_unsettled += 1
                    pnl = s.get("pnl_cents", 0) or 0
                    best = s.get("pnl_best_case")
                    if best is None:
                        # Legacy — compute on the fly
                        yes_sold = s.get("yes_sold", 0)
                        no_sold = s.get("no_sold", 0)
                        yes_exit = s.get("yes_exit_price")
                        no_exit = s.get("no_exit_price")
                        sell_proc = 0
                        if yes_exit and yes_sold > 0:
                            sell_proc += yes_exit * yes_sold
                        if no_exit and no_sold > 0:
                            sell_proc += no_exit * no_sold
                        pnl = sell_proc - cost
                        best = pnl + (contracts - yes_sold + contracts - no_sold) * 100
                    w_worst += pnl
                    w_best += best

            rolling += w_pnl
            rolling_cost += w_cost
            unsettled_worst += w_worst
            unsettled_best += w_best

            ret_pct = (w_pnl / w_cost * 100) if w_cost > 0 else 0

            # Parse date:time from window key (e.g. "2026-02-23:1315")
            if ":" in window:
                w_date, w_time = window.split(":", 1)
            else:
                w_date, w_time = "", window

            if all_settled:
                lines.append((w_date,
                    f"  :{w_time}  {w_pnl:+6d}c / {w_cost}c ({ret_pct:+.1f}%)  "
                    f"rolling: {rolling:+d}c"
                ))
            else:
                range_lo = w_pnl + w_worst
                range_hi = w_pnl + w_best
                ret_lo = (range_lo / w_cost * 100) if w_cost > 0 else 0
                ret_hi = (range_hi / w_cost * 100) if w_cost > 0 else 0
                lines.append((w_date,
                    f"  :{w_time}  {range_lo:+d}c to {range_hi:+d}c / {w_cost}c "
                    f"({ret_lo:+.1f}% to {ret_hi:+.1f}%)  "
                    f"({w_unsettled} unsettled)"
                ))

        total_lo = rolling + unsettled_worst
        total_hi = rolling + unsettled_best

        # Compute peak concurrent capital for accurate return %
        peak_capital, total_wagered, capital_turns = self._compute_capital_metrics(entries)

        print(f"\n  ── Rolling P&L ──")
        prev_date = None
        for w_date, line in lines:
            if w_date and w_date != prev_date:
                print(f"  ── {w_date} ──")
                prev_date = w_date
            print(line)
        if unsettled_worst == 0 and unsettled_best == 0:
            ret = (rolling / peak_capital * 100) if peak_capital > 0 else 0
            print(f"  {'─'*50}")
            print(f"  TOTAL: {rolling:+d}c / {peak_capital}c peak = {ret:+.1f}% "
                  f"(${rolling/100:.2f})")
            print(f"         {capital_turns:.0f} turns | {total_wagered}c total wagered")
        else:
            ret_lo = (total_lo / peak_capital * 100) if peak_capital > 0 else 0
            ret_hi = (total_hi / peak_capital * 100) if peak_capital > 0 else 0
            print(f"  {'─'*50}")
            print(f"  Settled: {rolling:+d}c | Unsettled: {unsettled_worst:+d}c to {unsettled_best:+d}c")
            print(f"  TOTAL:  {total_lo:+d}c to {total_hi:+d}c / {peak_capital}c peak "
                  f"({ret_lo:+.1f}% to {ret_hi:+.1f}%)")
            print(f"          {capital_turns:.0f} turns | {total_wagered}c total wagered")
        print()

    def _get_settled_entries(self):
        """Load all straddles and return only those with deterministic P&L.
        Returns list of (entry_dict, pnl_cents) tuples."""
        entries = self._load_all_straddles()
        settled = []
        for e in entries:
            pnl = e.get("pnl_actual")
            if pnl is None:
                if e.get("status") == "closed":
                    pnl = e.get("pnl_cents", 0) or 0
                elif (e.get("status") == "expired"
                      and e.get("yes_sold", 0) == 0
                      and e.get("no_sold", 0) == 0):
                    pnl = e.get("pnl_cents", 0) or 0
                else:
                    continue  # unsettled partial exit
            settled.append((e, pnl))
        return settled

    def print_stats(self):
        """Print analytics dashboard: per-series performance, exit triggers,
        settlement patterns, and entry price analysis."""
        settled = self._get_settled_entries()
        if not settled:
            print("  No settled straddle data to analyze.")
            return

        # ── Section A: Per-Series Performance ──
        series_stats = defaultdict(lambda: {"count": 0, "wins": 0, "pnl_list": []})
        for e, pnl in settled:
            s = e.get("series", "?")
            series_stats[s]["count"] += 1
            series_stats[s]["pnl_list"].append(pnl)
            if pnl > 0:
                series_stats[s]["wins"] += 1

        print(f"\n  {'='*55}")
        print(f"  ANALYTICS DASHBOARD  ({len(settled)} settled entries)")
        print(f"  {'='*55}")

        print(f"\n  ── Series Performance ──")
        print(f"  {'Series':<12} {'#':>3} {'Win%':>6} {'Avg PnL':>9} {'Total':>8}")
        for series in sorted(series_stats.keys()):
            st = series_stats[series]
            n = st["count"]
            wins = st["wins"]
            total = sum(st["pnl_list"])
            avg = total / n if n > 0 else 0
            wr = (wins / n * 100) if n > 0 else 0
            print(f"  {series:<12} {n:>3} {wr:>5.0f}% {avg:>+8.1f}c {total:>+7d}c")

        # ── Section B: Exit Triggers ──
        sold_yes_count = 0
        sold_yes_wins = 0
        sold_no_count = 0
        sold_no_wins = 0
        both_neither = 0
        exit_times = []

        for e, pnl in settled:
            yes_sold = e.get("yes_sold", 0)
            no_sold = e.get("no_sold", 0)

            entry_t = e.get("entry_time")
            exit_t = e.get("exit_time")
            if entry_t and exit_t:
                try:
                    dt_entry = datetime.fromisoformat(entry_t)
                    dt_exit = datetime.fromisoformat(exit_t)
                    exit_times.append((dt_exit - dt_entry).total_seconds())
                except Exception:
                    pass

            if yes_sold > 0 and no_sold == 0:
                sold_yes_count += 1
                if pnl > 0:
                    sold_yes_wins += 1
            elif no_sold > 0 and yes_sold == 0:
                sold_no_count += 1
                if pnl > 0:
                    sold_no_wins += 1
            else:
                both_neither += 1

        print(f"\n  ── Exit Triggers ──")
        yes_wr = (sold_yes_wins / sold_yes_count * 100) if sold_yes_count > 0 else 0
        no_wr = (sold_no_wins / sold_no_count * 100) if sold_no_count > 0 else 0
        print(f"  Sold YES (held NO): {sold_yes_count}  "
              f"({yes_wr:.0f}% held-side win)")
        print(f"  Sold NO  (held YES): {sold_no_count}  "
              f"({no_wr:.0f}% held-side win)")
        if both_neither:
            print(f"  Both/None: {both_neither}")
        if exit_times:
            avg_exit = sum(exit_times) / len(exit_times) / 60
            min_exit = min(exit_times) / 60
            max_exit = max(exit_times) / 60
            print(f"  Time to exit: avg {avg_exit:.1f} min  "
                  f"(range {min_exit:.1f}–{max_exit:.1f} min)")

        # ── Section C: Settlement Patterns ──
        yes_settled = []
        no_settled = []
        for e, pnl in settled:
            sr = e.get("settlement_result")
            if sr == "yes":
                yes_settled.append(pnl)
            elif sr == "no":
                no_settled.append(pnl)

        total_sr = len(yes_settled) + len(no_settled)
        if total_sr > 0:
            print(f"\n  ── Settlement Patterns ──")
            print(f"  YES settled: {len(yes_settled)}/{total_sr} "
                  f"({len(yes_settled)/total_sr*100:.0f}%)")
            print(f"  NO  settled: {len(no_settled)}/{total_sr} "
                  f"({len(no_settled)/total_sr*100:.0f}%)")
            if yes_settled:
                print(f"  Avg PnL when YES: {sum(yes_settled)/len(yes_settled):+.1f}c")
            if no_settled:
                print(f"  Avg PnL when NO:  {sum(no_settled)/len(no_settled):+.1f}c")

        # ── Section D: Entry Prices ──
        combined_all = []
        combined_win = []
        combined_loss = []
        imbalances = []

        for e, pnl in settled:
            yp = e.get("yes_entry_price", 0)
            np = e.get("no_entry_price", 0)
            combined = yp + np
            combined_all.append(combined)
            imbalances.append(abs(yp - np))
            if pnl > 0:
                combined_win.append(combined)
            elif pnl < 0:
                combined_loss.append(combined)

        print(f"\n  ── Entry Prices ──")
        if combined_all:
            print(f"  Avg combined entry: {sum(combined_all)/len(combined_all):.1f}c")
        if combined_win:
            print(f"  Win avg combined:   {sum(combined_win)/len(combined_win):.1f}c")
        if combined_loss:
            print(f"  Loss avg combined:  {sum(combined_loss)/len(combined_loss):.1f}c")
        if imbalances:
            print(f"  Avg |Y-N| imbalance: {sum(imbalances)/len(imbalances):.1f}c")

        print()

    def print_stats_compact(self):
        """One-line best/worst series for loop status output."""
        settled = self._get_settled_entries()
        if not settled:
            return

        series_pnl = defaultdict(list)
        for e, pnl in settled:
            s = e.get("series", "?").replace("KX", "").replace("15M", "")
            series_pnl[s].append(pnl)

        if not series_pnl:
            return

        avgs = {s: sum(v) / len(v) for s, v in series_pnl.items()}
        best = max(avgs, key=avgs.get)
        worst = min(avgs, key=avgs.get)
        total = sum(pnl for _, pnl in settled)
        print(f"  [stats] best: {best} ({avgs[best]:+.0f}c avg) | "
              f"worst: {worst} ({avgs[worst]:+.0f}c avg) | "
              f"net: {total:+d}c")

    # ==========================================================
    # SINGLE CYCLE (for cmd_straddle — unchanged)
    # ==========================================================

    def run_single_cycle(self):
        """
        Run one complete straddle cycle:
        1. Select best market
        2. Enter straddle
        3. Monitor prices
        4. Exit when triggered
        """
        print(f"\n{'='*55}")
        print(f"STRADDLE CYCLE — {datetime.now().strftime('%H:%M:%S')}")
        print(f"Mode: {'OBSERVATION' if OBSERVATION_MODE else '*** LIVE ***'}")
        print(f"{'='*55}")

        # Phase 1: Select and enter
        print(f"\n  Phase 1: Market selection...")
        market, ob = self.select_best_market()

        if market is None:
            print(f"    No suitable market found (all above {MAX_COMBINED_ENTRY_CENTS}c "
                  f"or insufficient depth)")
            return None

        pos = self.enter_straddle(market, ob)
        if pos is None:
            return None

        # Phase 2: Monitor
        print(f"\n  Phase 2: Monitoring...")
        exit_side, exit_price, exit_reason = self.monitor_straddle(pos)

        # Phase 3: Exit
        print(f"\n  Phase 3: Exiting...")
        self.exit_straddle(pos, exit_side, exit_price, exit_reason)

        return pos

    def wait_for_quarter_hour(self):
        """Wait until the next quarter hour entry window."""
        next_q = next_quarter_hour()
        scan_start = next_q - timedelta(seconds=SCAN_BEFORE_QUARTER_SECONDS)
        wait = seconds_until(scan_start)

        if wait > 0:
            print(f"\n  Next quarter: {next_q.strftime('%H:%M:%S')} "
                  f"— sleeping {wait:.0f}s...")
            time.sleep(wait)

        return next_q
