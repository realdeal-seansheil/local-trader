"""
Underdog Strategy Configuration — 15-Min Crypto Markets
Smaller positions on longer-shot wins using maker orders.

Strategy 2: Early Window (T=300-390s, leader 55-74c)
Strategy 4: Fade the Extreme (T=600-840s, favorite >= 90c, buy underdog <= 15c)
Strategy 6: Signal Observation (log all underdog opportunities for future Bayesian)
"""

import math as _math
import os as _os
import pathlib as _pathlib

# === Paths ===
_BASE = _pathlib.Path(__file__).parent
DATA_DIR = str(_BASE / "data")
_os.makedirs(DATA_DIR, exist_ok=True)

# === Observation mode ===
OBSERVATION_MODE = True  # Start observation-only (virtual fills via trades API)

# === Crypto series (same 4 as momentum/maker bots) ===
CRYPTO_SERIES = [
    "KXBTC15M",   # Bitcoin 15-min
    "KXETH15M",   # Ethereum 15-min
    "KXSOL15M",   # Solana 15-min
    "KXXRP15M",   # XRP 15-min
]

# === Loop timing ===
LOOP_INTERVAL_SECONDS = 3           # Scan every 3s (matches straddle bot)
SCAN_INTERVAL_SECONDS = 10          # Market scan interval for entry strategies

# === Fee calculation (Kalshi maker formula) ===
MAKER_FEE_COEFFICIENT = 0.0175

# ── STRATEGY 2: EARLY WINDOW ENTRY ──
# Buy leading side early when prices are cheaper (before momentum bot territory)
EARLY_ENABLED = True
EARLY_ENTRY_START_S = 180            # T=3min (start of early window — wider)
EARLY_ENTRY_END_S = 600              # T=10min (extend to meet fade window)
EARLY_MIN_LEADER_BID = 52           # Slightly lower floor for early entries
EARLY_MAX_LEADER_BID = 80           # Raise cap — capture more leader ranges
EARLY_MIN_CONTRACTS = 1
EARLY_MAX_CONTRACTS = 3
EARLY_MIN_DEPTH = 3                  # Minimum orderbook depth at best bid
EARLY_FILL_DEADLINE_S = 840         # Cancel unfilled orders at T=14min

# ── STRATEGY 4: FADE THE EXTREME ──
# When favorite is 90c+, buy the cheap underdog side
FADE_ENABLED = True
FADE_ENTRY_START_S = 300            # T=5min (start looking for extremes earlier)
FADE_ENTRY_END_S = 870              # T=14.5min (extend closer to close)
FADE_EXTREME_THRESHOLD = 80         # Lower threshold — catch more fades
FADE_MAX_UNDERDOG_PRICE = 25        # Wider range — underdogs up to 25c
FADE_MIN_CONTRACTS = 1
FADE_MAX_CONTRACTS = 2
FADE_MIN_DEPTH = 3
FADE_FILL_DEADLINE_S = 890          # Cancel unfilled at T=14:50 (tight deadline)

# ── STRATEGY 6: SIGNAL OBSERVATION ──
# Log all underdog opportunities for future Bayesian calibration
SIGNAL_OBS_ENABLED = True
SIGNAL_OBS_THRESHOLD = 30           # Log when cheap side ask < 30c

# ── FILL TRACKING ──
FILL_TOLERANCE_CENTS = 2            # Match trades within ±2c of our order
FILL_CHECK_INTERVAL = 1             # Check fills every loop cycle

# ── SETTLEMENT ──
SETTLEMENT_CHECK_INTERVAL = 30      # Check every 30s
SETTLEMENT_BUFFER_S = 120           # Wait 2min after close before checking

# ── TIME FILTERS ──
SKIP_HOURS = set()                   # No skip hours — observe everything
OVERNIGHT_START_HOUR = 20           # 8:00 PM EST
OVERNIGHT_END_HOUR = 8              # 8:00 AM EST
EARLY_OVERNIGHT_MIN_BID = 55        # Same as normal (no overnight restriction)
FADE_OVERNIGHT_ENABLED = True       # Observe fade during all hours

# ── ENRICHMENT: SPOT FEED (Binance) ──
SPOT_FEED_ENABLED = True
BINANCE_BASE_URL = "https://api.binance.us/api/v3"
SPOT_DIVERGENCE_THRESHOLD = 0.05     # % threshold for spot vs leader divergence

# ── ENRICHMENT: OB MOMENTUM ──
OB_MOMENTUM_WINDOW = 10             # snapshots (30s at 3s interval)

# ── ENRICHMENT: CROSS SERIES ──
CROSS_SERIES_MIN_AGREEMENT = 3      # require 3/4 series to agree

# ── ENRICHMENT: TRADE TAPE ──
TRADE_TAPE_ENABLED = True

# ── ENRICHMENT: VOLATILITY REGIME ──
VOL_LOW_THRESHOLD = 1.0             # % — below this = low_vol (skip early)
VOL_HIGH_THRESHOLD = 2.5            # % — above this = high_vol (skip fade)

# ── PASSIVE TICK LOGGING ──
TICK_LOGGING_ENABLED = True          # Full T=0-to-T=900 tick collection

# ── LOGGING ──
PRINT_INTERVAL_SECONDS = 300        # Print summary every 5 min


# === Maker fee function ===
def maker_fee_per_contract(buy_price):
    """
    Kalshi maker fee per contract (raw, no ceil).
    At 10c: 0.16c/contract. At 50c: 0.44c/contract. At 90c: 0.16c/contract.
    """
    p = buy_price / 100.0
    return MAKER_FEE_COEFFICIENT * p * (1 - p) * 100


def calculate_maker_fee(count, price_cents):
    """Kalshi maker fee: ceil(coefficient * C * P * (1-P)) in cents."""
    p = price_cents / 100.0
    raw = MAKER_FEE_COEFFICIENT * count * p * (1 - p) * 100
    return _math.ceil(raw) if raw > 0 else 0
