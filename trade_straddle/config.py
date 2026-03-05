"""
Configuration for the Crypto Straddle/Momentum Trading Bot.

Strategies:
  1. Straddle: Buy both YES and NO at market open, sell one side, hold other.
  2. Momentum: At T=7min, buy whichever side leads (bid >= 60c), hold to settlement.
     Direction-agnostic — 86% win rate on 203-market backtest.

All values in CENTS unless otherwise noted.
"""

import os
import pathlib

# ============================================================
# PATHS
# ============================================================
_BASE = pathlib.Path(__file__).parent
DATA_DIR = str(_BASE / "data")
os.makedirs(DATA_DIR, exist_ok=True)

# ============================================================
# KALSHI CRYPTO SERIES
# ============================================================
CRYPTO_SERIES = [
    "KXBTC15M",   # Bitcoin 15-min
    "KXETH15M",   # Ethereum 15-min
    "KXSOL15M",   # Solana 15-min
    "KXXRP15M",   # XRP 15-min
]

# ============================================================
# ENTRY PARAMETERS
# ============================================================
MAX_CONTRACTS_PER_SIDE = 5       # Buy 5 YES + 5 NO per straddle
MAX_COMBINED_ENTRY_CENTS = 102   # Won't enter if YES_ask + NO_ask > 102c (was 110; entries >102c are net-negative)
MAX_SINGLE_SIDE_ENTRY = 90       # Skip if either side ask >= 90c (market already decided)
MIN_ORDERBOOK_DEPTH = 5          # Need >= 5 contracts at the ask level
MIN_IMBALANCE_CENTS = 10         # Skip balanced entries: |YES_ask - NO_ask| must be >= 10c

# ============================================================
# EXIT PARAMETERS
# ============================================================
EXIT_PROFIT_TARGET_CENTS = 5     # Sell when one side appreciates +5c
EXIT_TIMEOUT_SECONDS = 600       # 10 min max hold — exit both if no move
POLL_INTERVAL_SECONDS = 2        # Orderbook poll frequency during monitoring
EXIT_BEFORE_CLOSE_SECONDS = 60   # Exit all positions 60s before market close

# ============================================================
# RISK CONTROLS
# ============================================================
MAX_DAILY_STRADDLES = 5          # Max 5 straddle entries per day
MAX_DAILY_EXPOSURE_CENTS = 1000  # $10 hard cap (shared balance ~$53)
OBSERVATION_MODE = False         # *** LIVE TRADING ***

# ============================================================
# TIMING
# ============================================================
SCAN_BEFORE_QUARTER_SECONDS = 10  # Start scanning 10s before :00/:15/:30/:45
ENTRY_WINDOW_SECONDS = 30         # Must enter within 30s of market open

# ============================================================
# CONTINUOUS MODE
# ============================================================
LOOP_INTERVAL_SECONDS = 3        # Main loop tick interval (scan + monitor)
MAX_SIMULTANEOUS_POSITIONS = 4   # One per series max
# Re-entry prevention: ticker-based (not time-based). See _entered_tickers in straddle_executor.py.

# ============================================================
# TIME RESTRICTIONS
# ============================================================
SKIP_HOURS = {5, 8}  # Only truly toxic hours (Bayesian handles the rest)
# 5am: 78.6% WR, Bayesian still leaks losses (-$15.38)
# 8am: 71.7% WR, worst hour — Bayesian can't save it
# Removed: {3, 11, 13, 14, 20, 23} — Bayesian filters profitably (87.4% WR on entered trades)

# ============================================================
# STRADDLE TOGGLE
# ============================================================
STRADDLE_ENTRIES_ENABLED = False     # Disable straddle entries (momentum replaces them)

# ============================================================
# MOMENTUM STRATEGY
# ============================================================
MOMENTUM_ENABLED = True              # Enable momentum entry strategy
MOMENTUM_ENTRY_SECONDS = 420         # Enter at T=420s (7 min into 15-min window)
MOMENTUM_ENTRY_WINDOW = 30           # ±15s tolerance (405s-435s)
MOMENTUM_MIN_BID = 75                # Full range — volume > selectivity
MOMENTUM_CONVICTION_TIERS = {        # contracts by leader bid level
    75: 8,   # 75-79c → 8 contracts
    80: 10,  # 80c+   → 10 contracts
}
MOMENTUM_MAX_DAILY = 9999             # No limit
MOMENTUM_MAX_DAILY_EXPOSURE = 999999  # No limit

# Shadow monitoring: log sub-threshold signals for continued observation
MOMENTUM_SHADOW_MIN_BID = 75         # Still observe signals down to 75c

# Stop-loss observer (runs alongside live trading, logs only — never executes)
MOMENTUM_STOPLOSS_ENABLED = False    # Disable the observer
MOMENTUM_STOPLOSS_THRESHOLDS = [-5, -10, -15, -20]  # Test multiple thresholds simultaneously

# Live correlated stop-loss — sells when 2+ series breach threshold in same window
# Overnight protection — raise min bid during thin-liquidity hours
MOMENTUM_OVERNIGHT_MIN_BID = 86          # Require 86c+ entry overnight (85c band has 64% WR, worst overnight level)
MOMENTUM_OVERNIGHT_START_HOUR = 20       # 8:00 PM EST
MOMENTUM_OVERNIGHT_END_HOUR = 8          # 8:00 AM EST

MOMENTUM_STOPLOSS_LIVE = False         # Disable LIVE stop-loss execution
MOMENTUM_STOPLOSS_DROP = 11          # Drop threshold in cents from entry price
MOMENTUM_STOPLOSS_MIN_SERIES = 2     # Need 2+ series breaching to trigger

# ============================================================
# BAYESIAN SIGNAL ENGINE + KELLY SIZING
# ============================================================
BAYESIAN_ENABLED = True           # LIVE: Bayesian+Kelly controls entry/sizing
BAYESIAN_SHADOW_MODE = True       # Also log shadow decisions for comparison

# Kelly position sizing
KELLY_MULTIPLIER = 0.25           # Quarter-Kelly (conservative start)
KELLY_USE_LIVE_BALANCE = True     # Pull real balance from Kalshi API (vs static fallback)
KELLY_BANKROLL_CENTS = 5000       # Fallback bankroll if API call fails ($50)
KELLY_BALANCE_CACHE_SECONDS = 60  # Cache balance for 60s (avoid hammering API)
KELLY_MIN_CONTRACTS = 1           # Floor: never bet less than 1 contract
KELLY_MAX_CONTRACTS = 15          # Cap: never bet more than 15 contracts
KELLY_MAX_BANKROLL_PCT = 0.05     # Max 5% of bankroll per single trade
KELLY_MIN_CONFIDENCE = 10         # Require 10+ historical trades in weakest feature bin

# Bayesian posterior tuning
BAYESIAN_SECONDARY_DAMPENING = 0.3  # Dampening for series/hour shifts (0=ignore, 1=full weight)

# ============================================================
# PASSIVE TICK LOGGING
# ============================================================
PASSIVE_TICK_LOGGING = True          # Log all market orderbooks every tick (for momentum analysis)
PASSIVE_TICK_INTERVAL = 1            # Log every Nth loop cycle (1 = every 3s, 2 = every 6s)

# ============================================================
# KALSHI FEE
# ============================================================
KALSHI_FEE_RATE = 0.007           # 0.7% per leg
