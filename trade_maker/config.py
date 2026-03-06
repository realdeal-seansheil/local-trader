"""
Maker Strategy Configuration — 15-Min Crypto Markets (Observation Mode)
Momentum strategy (mirrors taker) on KXBTC15M, KXETH15M, KXSOL15M, KXXRP15M.
Posts virtual maker bids on the momentum side, tracks fills via trades API.
Tests whether taker's 93% WR momentum signal works with 4x lower maker fees.
"""

# === Observation mode ===
OBSERVATION_MODE = False  # *** LIVE TRADING — maker fees, momentum signal ***

# === Crypto series (same as momentum bot) ===
CRYPTO_SERIES = [
    "KXBTC15M",   # Bitcoin 15-min
    "KXETH15M",   # Ethereum 15-min
    "KXSOL15M",   # Solana 15-min
    "KXXRP15M",   # XRP 15-min
]

# === Timing (mirrors taker: T=420s ±15s) ===
SCAN_INTERVAL_SECONDS = 10       # Scan every 10s (short-lived markets need faster checks)
MAKER_ENTRY_SECONDS = 420        # Post virtual order at T=420s (7 min into 15-min window)
MAKER_ENTRY_WINDOW = 30          # Entry window: T=405s to T=435s (±15s tolerance)
MAKER_DEADLINE_SECONDS = 840     # Stop accepting fills after T=840s (14 min, 1 min before close)

# === Entry criteria (mirrors taker momentum thresholds) ===
MIN_FAVORITE_PRICE = 75          # Momentum min bid (same as taker MOMENTUM_MIN_BID)
MIN_ORDERBOOK_DEPTH = 3          # Minimum contracts at entry price level

# === Position sizing (hypothetical in obs mode) ===
CONTRACTS_PER_MARKET = 5         # 5 contracts per virtual position
MAX_POSITIONS = 50               # 4 series * ~12 windows/hr is plenty
MAX_EXPOSURE_CENTS = 50000       # $500 virtual exposure cap

# === Fee calculation (Kalshi maker formula) ===
MAKER_FEE_COEFFICIENT = 0.0175

# === Fill simulation ===
FILL_CHECK_INTERVAL = 10         # Check fills every 10s (aligned with scan interval)
FILL_TOLERANCE_CENTS = 1         # Fill if trade within 1c of our price

# === Settlement checking ===
SETTLEMENT_CHECK_INTERVAL = 30   # Check every 30s (markets settle ~2 min after close)

# === Time restrictions ===
SKIP_HOURS = {5, 8}  # Only truly toxic hours (Bayesian handles the rest)
# 5am: 78.6% WR, Bayesian still leaks losses
# 8am: 71.7% WR, worst hour — Bayesian can't save it
# Removed: {3, 11, 13, 14, 20, 23} — Bayesian filters profitably

# === Overnight filter (same as momentum bot) ===
OVERNIGHT_MIN_BID = 86           # Require 86c+ overnight
OVERNIGHT_START_HOUR = 20        # 8:00 PM EST
OVERNIGHT_END_HOUR = 8           # 8:00 AM EST

# === Logging ===
PRINT_INTERVAL_SECONDS = 300     # Print summary every 5 min

# === Bayesian Signal Engine + Kelly Sizing ===
BAYESIAN_ENABLED = True           # LIVE: Bayesian+Kelly controls entry/sizing
BAYESIAN_SHADOW_MODE = True       # Also log what static (5-contract) logic would have done

# Kelly position sizing
KELLY_MULTIPLIER = 0.25           # Quarter-Kelly (conservative start)
KELLY_USE_LIVE_BALANCE = True     # Live balance for apples-to-apples comparison with taker
KELLY_BANKROLL_CENTS = 5000       # Fallback bankroll if API call fails ($50)
KELLY_BALANCE_CACHE_SECONDS = 60  # Cache balance for 60s
KELLY_MIN_CONTRACTS = 1           # Floor: never bet less than 1 contract
KELLY_MAX_CONTRACTS = 15          # Cap: never bet more than 15 contracts
KELLY_MAX_BANKROLL_PCT = 0.05     # Max 5% of bankroll per single trade
KELLY_MIN_CONFIDENCE = 10         # Require 10+ historical trades in weakest feature bin

# Bayesian posterior tuning
BAYESIAN_SECONDARY_DAMPENING = 0.3  # Dampening for series/hour shifts


# === Maker fee function (pluggable into Bayesian engine) ===
import math as _math

def maker_fee_per_contract(buy_ask):
    """
    Kalshi maker fee per contract (raw, no ceil).
    Kalshi applies ceil() to the TOTAL fee, not per-contract.
    For Kelly sizing we need the marginal per-contract cost.
    At 90c: 0.16c/contract vs taker 0.63c/contract.
    """
    p = buy_ask / 100.0
    return MAKER_FEE_COEFFICIENT * p * (1 - p) * 100
