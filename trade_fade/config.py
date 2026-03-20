"""
Kelly Bot Configuration — Underdog strategy clone with Kelly criterion sizing.

Mirrors trade_underdog exactly (same strategies, same enrichment filters)
but replaces fixed 3-contract sizing with Kelly-optimal position sizing
based on historical win rates by price bucket.

Starting balance: $100 (10,000c). Tracks virtual balance throughout.
"""

import math as _math
import os as _os
import pathlib as _pathlib

# === Paths ===
_BASE = _pathlib.Path(__file__).parent
DATA_DIR = str(_BASE / "data")
_os.makedirs(DATA_DIR, exist_ok=True)

# === Observation mode ===
OBSERVATION_MODE = True

# === Crypto series ===
CRYPTO_SERIES = [
    "KXBTC15M",
    "KXETH15M",
    "KXSOL15M",
    "KXXRP15M",
]

# === Loop timing ===
LOOP_INTERVAL_SECONDS = 3
MAKER_FEE_COEFFICIENT = 0.0175

# ── STRATEGY 2: EARLY WINDOW (mirrored from underdog) ──
EARLY_ENABLED = True
EARLY_ENTRY_START_S = 180
EARLY_ENTRY_END_S = 600
EARLY_MIN_LEADER_BID = 52
EARLY_MAX_LEADER_BID = 80
EARLY_MIN_DEPTH = 3
EARLY_FILL_DEADLINE_S = 840

# ── STRATEGY 4: FADE THE EXTREME (mirrored from underdog) ──
FADE_ENABLED = True
FADE_ENTRY_START_S = 300
FADE_ENTRY_END_S = 870
FADE_EXTREME_THRESHOLD = 80
FADE_MAX_UNDERDOG_PRICE = 25
FADE_MIN_DEPTH = 3
FADE_FILL_DEADLINE_S = 890

# ── TIME FILTERS (mirrored from underdog) ──
SKIP_HOURS = set()
OVERNIGHT_START_HOUR = 20
OVERNIGHT_END_HOUR = 8
EARLY_OVERNIGHT_MIN_BID = 55
FADE_OVERNIGHT_ENABLED = True

# ── KELLY SIZING ──
STARTING_BALANCE_CENTS = 10000       # $100
KELLY_FRACTION = 0.5                 # Half-Kelly (conservative — full Kelly is too volatile)
KELLY_MIN_CONTRACTS = 1              # Floor: always bet at least 1 contract
KELLY_MAX_CONTRACTS = 20             # Ceiling: cap even if Kelly says more
KELLY_MIN_EDGE = 0.02               # Don't bet if estimated edge < 2%

# Underdog history path (read-only — for bootstrapping win rate estimates)
UNDERDOG_HISTORY_PATH = str(_pathlib.Path(__file__).parent.parent / "trade_underdog" / "data" / "underdog_history.jsonl")

# ── FILL TRACKING ──
FILL_TOLERANCE_CENTS = 2
FILL_CHECK_INTERVAL = 1

# ── SETTLEMENT ──
SETTLEMENT_CHECK_INTERVAL = 30
SETTLEMENT_BUFFER_S = 120

# ── LOGGING ──
PRINT_INTERVAL_SECONDS = 300


# === Maker fee function ===
def calculate_maker_fee(count, price_cents):
    """Kalshi maker fee: ceil(coefficient * C * P * (1-P)) in cents."""
    p = price_cents / 100.0
    raw = MAKER_FEE_COEFFICIENT * count * p * (1 - p) * 100
    return _math.ceil(raw) if raw > 0 else 0
