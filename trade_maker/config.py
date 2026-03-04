"""
Maker Strategy Configuration — 15-Min Crypto Markets (Observation Mode)
Favorite-longshot bias on KXBTC15M, KXETH15M, KXSOL15M, KXXRP15M.
Posts virtual maker bids on the favorite side, tracks fills via trades API.
"""

# === Observation mode ===
OBSERVATION_MODE = True  # Log only, no orders placed

# === Crypto series (same as momentum bot) ===
CRYPTO_SERIES = [
    "KXBTC15M",   # Bitcoin 15-min
    "KXETH15M",   # Ethereum 15-min
    "KXSOL15M",   # Solana 15-min
    "KXXRP15M",   # XRP 15-min
]

# === Timing ===
SCAN_INTERVAL_SECONDS = 10       # Scan every 10s (short-lived markets need faster checks)
MAKER_ENTRY_SECONDS = 300        # Post virtual order at T=300s (5 min into 15-min window)
MAKER_ENTRY_WINDOW = 60          # Entry window: T=270s to T=330s (±30s tolerance)
MAKER_DEADLINE_SECONDS = 840     # Stop accepting fills after T=840s (14 min, 1 min before close)

# === Entry criteria ===
MIN_FAVORITE_PRICE = 85          # Only buy favorites at 85c+ (longshot at 15c-)
MAX_FAVORITE_PRICE = 97          # Don't buy above 97c (too thin)
MIN_ORDERBOOK_DEPTH = 3          # Minimum contracts at entry price level
MIN_EDGE_CENTS = 0               # Log all positive EV (observation mode)

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

# === Time restrictions (same as momentum bot) ===
SKIP_HOURS = {3, 5, 8, 11, 13, 14, 20, 23}  # Nuclear: skip all negative-P&L hours
# 3am: -$14.48 (87% WR)   | 5am: -$71.93 (72% WR)
# 8am: -$88.42 (68% WR)   | 11am: -$24.37 (80% WR)
# 1pm: -$9.03 (84% WR)    | 2pm: -$3.80 (82% WR)
# 8pm: -$23.79 (81% WR)   | 11pm: -$14.64 (71% WR)

# === Overnight filter (same as momentum bot) ===
OVERNIGHT_MIN_BID = 86           # Require 86c+ overnight
OVERNIGHT_START_HOUR = 20        # 8:00 PM EST
OVERNIGHT_END_HOUR = 8           # 8:00 AM EST

# === Logging ===
PRINT_INTERVAL_SECONDS = 300     # Print summary every 5 min
