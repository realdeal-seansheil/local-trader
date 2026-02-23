"""
Configuration for the Crypto Straddle Trading Bot.

Strategy: Buy both YES and NO on Kalshi crypto 15-min markets at open,
sell whichever side moves in our favor, hold the hedge to expiry.

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
MAX_COMBINED_ENTRY_CENTS = 110   # Won't enter if YES_ask + NO_ask > 110c
MIN_ORDERBOOK_DEPTH = 5          # Need >= 5 contracts at the ask level

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
OBSERVATION_MODE = True          # True = log everything, execute nothing

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
SCAN_COOLDOWN_SECONDS = 15       # After exit, wait before re-entering same series

# ============================================================
# KALSHI FEE
# ============================================================
KALSHI_FEE_RATE = 0.007           # 0.7% per leg
