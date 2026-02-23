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
from datetime import datetime, timedelta

# Add trade_arbitrage to path for imports
_ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / "trade_arbitrage"))
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from kalshi_executor import KalshiAuth, KalshiClient, KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH
from config import (
    CRYPTO_SERIES, MAX_CONTRACTS_PER_SIDE, MAX_COMBINED_ENTRY_CENTS,
    MIN_ORDERBOOK_DEPTH, EXIT_PROFIT_TARGET_CENTS, EXIT_TIMEOUT_SECONDS,
    POLL_INTERVAL_SECONDS, EXIT_BEFORE_CLOSE_SECONDS, MAX_DAILY_STRADDLES,
    MAX_DAILY_EXPOSURE_CENTS, OBSERVATION_MODE, SCAN_BEFORE_QUARTER_SECONDS,
    ENTRY_WINDOW_SECONDS, KALSHI_FEE_RATE, DATA_DIR,
    LOOP_INTERVAL_SECONDS, MAX_SIMULTANEOUS_POSITIONS, SCAN_COOLDOWN_SECONDS,
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

            # Trigger A: YES side hit target
            if yes_pnl >= EXIT_PROFIT_TARGET_CENTS:
                print(f"\n    EXIT TRIGGER: YES +{yes_pnl}c >= target +{EXIT_PROFIT_TARGET_CENTS}c")
                return ("yes", current_yes_bid, f"profit_target_yes_{yes_pnl}c")

            # Trigger B: NO side hit target
            if no_pnl >= EXIT_PROFIT_TARGET_CENTS:
                print(f"\n    EXIT TRIGGER: NO +{no_pnl}c >= target +{EXIT_PROFIT_TARGET_CENTS}c")
                return ("no", current_no_bid, f"profit_target_no_{no_pnl}c")

            # Trigger C: Timeout
            if elapsed >= EXIT_TIMEOUT_SECONDS:
                print(f"\n    EXIT TRIGGER: Timeout ({EXIT_TIMEOUT_SECONDS}s)")
                return ("both", None, "timeout")

            # Trigger D: Market close approaching
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
                        print(f"\n    EXIT TRIGGER: Market closing in {secs_to_close:.0f}s")
                        return ("both", None, f"market_close_{secs_to_close:.0f}s")
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
            # Timeout or market close — exit both sides at current prices
            try:
                ob_raw = self.client.get_orderbook(ticker)
                ob = parse_orderbook(ob_raw)
            except Exception as e:
                print(f"    ERROR getting exit prices: {e}")
                self.tracker.close_at_expiry(ticker)
                return

            if ob:
                self._execute_sell(pos, "yes", ob["yes_bid"], contracts)
                self._execute_sell(pos, "no", ob["no_bid"], contracts)
            else:
                print(f"    Empty orderbook — holding to expiry")
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

            # Trigger A: YES profit target
            if yes_pnl >= EXIT_PROFIT_TARGET_CENTS:
                print(f"    [{ticker}] EXIT: YES +{yes_pnl}c hit target")
                exits.append((pos, "yes", current_yes_bid, f"profit_target_yes_{yes_pnl}c"))
                continue

            # Trigger B: NO profit target
            if no_pnl >= EXIT_PROFIT_TARGET_CENTS:
                print(f"    [{ticker}] EXIT: NO +{no_pnl}c hit target")
                exits.append((pos, "no", current_no_bid, f"profit_target_no_{no_pnl}c"))
                continue

            # Trigger C: Market close approaching
            secs_to_close = self._seconds_to_close(pos)
            if secs_to_close < EXIT_BEFORE_CLOSE_SECONDS:
                print(f"    [{ticker}] EXIT: market closing in {secs_to_close:.0f}s")
                exits.append((pos, "both", None, f"market_close_{secs_to_close:.0f}s"))
                continue

            # Trigger D: Timeout — sell both sides
            if elapsed >= EXIT_TIMEOUT_SECONDS:
                print(f"    [{ticker}] EXIT: timeout ({elapsed:.0f}s)")
                exits.append((pos, "both", None, "timeout"))
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

        Returns list of positions entered this tick.
        """
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

        for series in CRYPTO_SERIES:
            if series in open_series:
                continue  # Already have a position in this series

            # Check cooldown
            if hasattr(self, '_series_cooldowns') and series in self._series_cooldowns:
                elapsed = (datetime.now() - self._series_cooldowns[series]).total_seconds()
                if elapsed < SCAN_COOLDOWN_SECONDS:
                    continue

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

            # Skip if already tracking this ticker (defensive)
            if ticker in open_tickers or ticker in self.tracker.positions:
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
            if ob["yes_bid_depth"] < MIN_ORDERBOOK_DEPTH:
                continue
            if ob["no_bid_depth"] < MIN_ORDERBOOK_DEPTH:
                continue

            # Enter!
            pos = self.enter_straddle(market, ob)
            if pos:
                new_entries.append(pos)

        return new_entries

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
        self._series_cooldowns = {}  # series -> datetime of last exit
        loop_count = 0

        print(f"\n  Continuous mode started.")
        print(f"  Loop interval: {LOOP_INTERVAL_SECONDS}s")
        print(f"  Max positions: {MAX_SIMULTANEOUS_POSITIONS}")
        print(f"  Mode: {'OBSERVATION' if OBSERVATION_MODE else '*** LIVE ***'}")
        print()

        while True:
            loop_count += 1

            # Step 1: Check exits on all open positions
            exits = self.check_position_exits()

            # Record cooldowns for exited series
            for pos, _, _, _ in exits:
                self._series_cooldowns[pos.series] = datetime.now()

            # Step 2: Scan for new entries
            new_entries = self.scan_for_entries()

            # Step 3: Periodic status print (~every 5 min at 3s interval)
            if loop_count % 100 == 1:
                now = datetime.now().strftime('%H:%M:%S')
                open_pos = self.tracker.get_open_positions()
                open_str = ", ".join(f"{p.series}" for p in open_pos) if open_pos else "none"
                stats = self.tracker.get_daily_stats()
                print(f"  [{now}] loop #{loop_count} | "
                      f"open: {open_str} | "
                      f"daily: {stats['daily_straddles']} straddles")

            # Step 4: Sleep
            time.sleep(LOOP_INTERVAL_SECONDS)

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
