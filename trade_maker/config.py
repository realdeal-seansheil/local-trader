"""
Maker Strategy Configuration — Observation Mode
Systematic favorite buying across all Kalshi markets.
"""

# === Observation mode ===
OBSERVATION_MODE = True  # Log only, no orders placed

# === Market scanning ===
SCAN_INTERVAL_SECONDS = 30   # How often to scan for new opportunities
MAX_PAGES_PER_SCAN = 25      # Max pagination pages (200 markets each = up to 5000 markets)

# === Entry criteria ===
MIN_FAVORITE_PRICE = 85      # Only buy favorites at 85c+ (implies longshot at 15c-)
MAX_FAVORITE_PRICE = 97      # Don't buy above 97c (too thin)
MIN_ORDERBOOK_DEPTH = 3      # Minimum contracts available at entry price
MIN_EDGE_CENTS = 0           # Log all positive EV opportunities (observation mode)

# === Position sizing (hypothetical in obs mode) ===
CONTRACTS_PER_MARKET = 5     # 5 contracts per position
MAX_POSITIONS = 50           # Max simultaneous virtual positions
MAX_EXPOSURE_CENTS = 20000   # Max total deployed = $200

# === Fee calculation (parabolic Kalshi formula) ===
MAKER_FEE_COEFFICIENT = 0.0175
TAKER_FEE_COEFFICIENT = 0.07

# === Fill simulation ===
FILL_CHECK_INTERVAL = 30     # Check for fills every 30s (same as scan interval)
FILL_TOLERANCE_CENTS = 1     # Count as fill if trade within 1c of our price
ORDER_EXPIRY_HOURS = 24      # Cancel unfilled virtual orders after 24h

# === Settlement checking ===
SETTLEMENT_CHECK_INTERVAL = 60  # Check virtual positions for settlement every 60s

# === Logging ===
PRINT_INTERVAL_SECONDS = 300  # Print summary every 5 minutes
