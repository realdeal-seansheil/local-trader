"""
Fade Bot Configuration — Enrichment-Gated High-Ratio Fades

Shadow strategy running alongside trade_underdog. Targets the 11-15c
underdog sweet spot where win rate is ~50% and reward/risk is 9:1.
Entry gates derived from backtest of 38 fade trades + 5,353 signal observations.
"""

import math as _math
import os as _os
import pathlib as _pathlib

# === Paths ===
_BASE = _pathlib.Path(__file__).parent
DATA_DIR = str(_BASE / "data")
_os.makedirs(DATA_DIR, exist_ok=True)

# === Observation mode ===
OBSERVATION_MODE = True  # Paper trading — virtual fills via trades API

# === Crypto series ===
CRYPTO_SERIES = [
    "KXBTC15M",   # Bitcoin 15-min
    "KXETH15M",   # Ethereum 15-min
    "KXSOL15M",   # Solana 15-min
    "KXXRP15M",   # XRP 15-min
]

# === Loop timing ===
LOOP_INTERVAL_SECONDS = 3
MAKER_FEE_COEFFICIENT = 0.0175

# ── FADE STRATEGY: Core Thresholds ──
FADE_ENTRY_START_S = 300           # T=5min (not too early)
FADE_ENTRY_END_S = 750             # T=12.5min (not too late — base rate drops after T=600)
FADE_MIN_FAVORITE_BID = 80        # Favorite must be >= 80c
FADE_MIN_UNDERDOG_PRICE = 11      # Sweet spot floor: backtest shows <11c = 0-11% win rate
FADE_MAX_UNDERDOG_PRICE = 15      # Sweet spot ceiling: backtest shows 11-15c = 50% win rate
FADE_MIN_DEPTH = 3                # Minimum orderbook depth
FADE_MAX_CONTRACTS = 2            # Position size
FADE_FILL_DEADLINE_S = 870        # Cancel unfilled at T=14.5min

# ── ENRICHMENT SIGNAL GATES (derived from backtest) ──
# All 4 fade wins shared: negative tape acceleration, low velocity, non-unanimous cross-series
GATE_MAX_TAPE_ACCELERATION = 0     # Tape must be decelerating (≤ 0)
GATE_MAX_VELOCITY_30S = 15         # Low recent trading activity (wins had vel30 2-12)
GATE_MAX_CROSS_AGREEMENT = 3      # Move not unanimous (wins had 2-3, losses had 4)
GATE_MAX_BID_VELOCITY = 0.2       # Favorite bid not still climbing (wins had 0-0.18)

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
