#!/usr/bin/env python3
"""
Enhanced 15-Minute Crypto Trader - FIXED VERSION
Implements proper EV calculation, Kelly sizing, SQLite persistence, and P&L reconciliation
FIXES: Signal logic, UTC datetime, live balance, deduplication, and signal counting
"""

import os
import json
import time
import sqlite3
import requests
import base64
from datetime import datetime as dt, timedelta, timezone
from kalshi_executor import KalshiAuth, KalshiClient
from kalshi_executor import KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
import re

# Module-level spot price cache (avoids redundant API calls within same scan)
_spot_price_cache = {}

# Regex to extract dollar amounts from market titles
# Handles: $100,000  $3,500  $250.50  $100000  etc.
STRIKE_PATTERN = re.compile(r'\$([0-9]{1,3}(?:,?[0-9]{3})*(?:\.[0-9]{1,2})?)')

# ============================================================
# ENHANCED 15-MINUTE TRADER CONFIGURATION
# ============================================================

# 15-minute crypto series
CRYPTO_15MIN_SERIES = ['KXBTC15M', 'KXETH15M', 'KXSOL15M', 'KXXRP15M']

# Trading parameters
SCAN_INTERVAL = 30              # 30-second scans
MIN_VOLUME = 0                # No volume filter - new 15min markets start at 0
MIN_EV_THRESHOLD = -5          # Legacy — replaced by MIN_ADJUSTED_EV in Era 10
MIN_ADJUSTED_EV = -10.0        # Era 11: effectively disabled — let volume flow, learn from data
ASYMMETRY_BONUS_WEIGHT = 3.0   # Era 10: cents of EV credit per 0.1x of payoff asymmetry above 1.0
MIN_TIME_REMAINING = 2 * 60   # 2 minutes minimum remaining (enough for fill, close to expiry = better signal)
MAX_POSITION_SIZE = 5         # Era 11: safety cap — Era 2's 10-contract losers destroyed gains
MAX_CONCURRENT_POSITIONS = 5  # Maximum open positions at once
KELLY_FRACTION = 0.5          # Use half-Kelly for safety

# Signal configuration
USE_MOMENTUM_SIGNAL = True     # ENABLED - Real signal logic implemented
OBSERVATION_MODE = True        # PAUSED — stop losses while we regroup

# External price feed configuration
SERIES_TO_BINANCE = {
    'KXBTC15M': 'BTCUSDT',
    'KXETH15M': 'ETHUSDT',
    'KXSOL15M': 'SOLUSDT',
    'KXXRP15M': 'XRPUSDT',
}
SERIES_TO_COINGECKO = {
    'KXBTC15M': 'bitcoin',
    'KXETH15M': 'ethereum',
    'KXSOL15M': 'solana',
    'KXXRP15M': 'ripple',
}
CACHE_TTL_SECONDS = 10              # Spot price cache TTL
SIGNAL_MIN_SAMPLES = 3              # Min price history points for momentum
SIGNAL_MOMENTUM_WEIGHT = 0.50       # Weight for momentum sub-signal
SIGNAL_SPOT_VS_STRIKE_WEIGHT = 0.45 # Weight for spot-vs-strike sub-signal (was 0.35)
SIGNAL_ORDERBOOK_WEIGHT = 0.05      # Weight for orderbook imbalance (was 0.15, confirmed noise)
SIGNAL_FLOOR = 0.35                 # Minimum win_prob output
SIGNAL_CEILING = 0.65               # Maximum win_prob output

# === LAYER 1: Trade Quality Gates ===
MIN_CONVICTION_THRESHOLD = 0.01      # Era 12: restored Era 2 value
STRONG_CONVICTION_THRESHOLD = 0.03   # Combined win_prob >0.53 or <0.47 = strong conviction
MIN_ENTRY_PRICE = 5                  # Era 12: restored Era 2 — traded as low as 5c
MAX_ENTRY_PRICE = 55                 # Era 12: restored Era 2 range
IDEAL_ENTRY_MIN = 42                 # Logged for analysis only
IDEAL_ENTRY_MAX = 47                 # Logged for analysis only
MIN_CONTRACTS = 2                    # Era 12: restored Era 2 — this was a real filter (declined 388 weak signals)
MAX_CONTRACTS_CEILING = 10           # Era 12: Era 2 had 25 but biggest losers were 10-contract. Cap at 10 for safety.
STRONG_RISK_PCT = 0.035              # Strong conviction: risk up to 3.5% of balance per trade
WEAK_RISK_PCT = 0.020                # Weak conviction: risk up to 2.0% of balance per trade
BASE_RISK_PCT = 0.015                # Era 10: raised from 0.010 — let 'none' agreement trades get 1-2 contracts
VOLATILITY_LOOKBACK_SECONDS = 900    # 15 min lookback for vol calc
VOLATILITY_MIN_SAMPLES = 10          # Need this many price points for vol
VOLATILITY_LOW_THRESHOLD = 0.0001    # Era 9: lowered from 0.0003 — vol gate killed 2 strong-conviction would-have-won signals today
MIN_CONVICTION_IMPROVEMENT = 0.005   # New signal must beat resting order by 0.5pp to replace it
# YES_DIRECTION_PENALTY = 0.005      # Replaced by adaptive penalty (Era 8)

# === REGIME GATE (Era 11: DISABLED) ===
# Paused to collect unbiased data. Regime info still logged for post-hoc analysis.
REGIME_GATE_ENABLED = False
REGIME_ALLOWED_DIRECTIONS = {
    'BEAR': ['YES', 'NO'],     # Not enforced while REGIME_GATE_ENABLED=False
    'BULL': ['YES', 'NO'],     # Not enforced while REGIME_GATE_ENABLED=False
    'FLAT': ['YES', 'NO'],     # Era 11: unblocked — collect data to re-evaluate
}

# === SIGNAL AGREEMENT (Era 10) ===
# Demoted back to sizing-only influence (was hard gate in Era 9)
# Agreement still affects position size via tier selection, but doesn't block trades
REQUIRE_SIGNAL_AGREEMENT = False     # Era 10: demoted — agreement gate was blocking 88% of signals
MIN_AGREEMENT_TO_TRADE = 'weak'      # Only used if REQUIRE_SIGNAL_AGREEMENT is True

# === ROLLING REGIME LEARNING (Era 9) ===
# Dynamically unlock/lock regime+direction combos based on rolling performance
REGIME_LEARNING_ENABLED = False       # Era 11: paused — collect unbiased data first
REGIME_LEARNING_WINDOW_HOURS = 12    # Look back 12 hours for regime WR
REGIME_LEARNING_MIN_SAMPLES = 10     # Need 10+ trades in a regime to override defaults
REGIME_UNLOCK_THRESHOLD = 0.45       # If regime WR rises above 45%, unlock it
REGIME_LOCK_THRESHOLD = 0.35         # If regime WR drops below 35%, lock it

# === ASSET-SPECIFIC SIZING (Era 9) ===
# Based on per-asset performance analysis
ASSET_SIZING_MULTIPLIER = {
    'KXBTC15M': 1.0,     # Era 11: equal — no asset bias, collect clean data
    'KXETH15M': 1.0,     # Era 11: equal
    'KXSOL15M': 1.0,     # Era 11: equal
    'KXXRP15M': 1.0,     # Era 11: equal
}
ASSET_SIZING_LEARNING_ENABLED = False    # Era 11: paused — collect unbiased data first
ASSET_SIZING_LEARNING_HOURS = 24         # Rolling window for asset performance
ASSET_SIZING_MIN_SAMPLES = 8            # Minimum trades to compute asset multiplier
ASSET_SIZING_FLOOR = 0.3                # Never reduce below 30%
ASSET_SIZING_CEILING = 1.5              # Never boost above 150%

# === ADAPTIVE DIRECTIONAL PENALTY (Era 8) ===
# Replaces static YES_DIRECTION_PENALTY with trend-aware bidirectional penalty
ADAPTIVE_PENALTY_LOOKBACK = 1200       # 20 min — matches contract window
ADAPTIVE_PENALTY_SENSITIVITY = 5.0     # Scaling: pct_change * sensitivity → raw trend signal
ADAPTIVE_PENALTY_BASE = 0.0            # Era 11: disabled — was biasing toward NO in flat markets. Era 2 had no penalty.
ADAPTIVE_PENALTY_MAX = 0.0             # Era 11: disabled — penalty was flipping borderline YES signals to NO
ADAPTIVE_PENALTY_MIN_SAMPLES = 5       # Minimum data points to compute trend; below this, use BASE
ADAPTIVE_PENALTY_ASSET_WEIGHT = 0.70   # Weight for asset-specific trend
ADAPTIVE_PENALTY_MACRO_WEIGHT = 0.30   # Weight for cross-asset macro trend
MACRO_TREND_SIZING_THRESHOLD = 0.0015  # 0.15% avg trend triggers sizing adjustment
MACRO_DIVERGENCE_THRESHOLD = 0.003     # If max-min asset trends > 0.3%, assets diverge
ALL_SERIES_TICKERS = ['KXBTC15M', 'KXETH15M', 'KXSOL15M', 'KXXRP15M']

# === TREND SIGNAL (Era 7) ===
TREND_30M_LOOKBACK = 1800            # 30 minutes of spot price history
TREND_2H_LOOKBACK = 7200             # 2 hours of spot price history
TREND_30M_MULTIPLIER = 15            # Sensitivity for 30-min trend (vs 30 for 5-min momentum)
TREND_2H_MULTIPLIER = 8              # Sensitivity for 2-hr trend (more dampened)
SIGNAL_TREND_WEIGHT = 0.10           # Base weight for Signal E in the adaptive weight blend

# === PERFORMANCE FEEDBACK (Era 7, fixed in Era 9) ===
PERF_LOOKBACK_HOURS = 8              # Era 9: extended from 4 — wider window catches more data
PERF_MIN_TRADES = 5                  # Era 9: lowered from 8 — old threshold was unreachable (0 activations in Era 8)
PERF_BASELINE_WR = 0.47              # Expected WR baseline (our overall average)
PERF_MAX_ADJUSTMENT = 0.0            # Era 11: disabled — was reinforcing wrong direction from recent losses. Era 2 had no feedback.
PERF_POOL_ASSETS = True              # Era 9: pool all assets for direction-level feedback (not per-asset)
PERF_REGIME_BASELINES = {            # Era 9: regime-specific baselines for smarter feedback
    'BEAR': 0.55,                    # Higher baseline — our strong regime
    'BULL': 0.40,                    # Lower baseline — weaker edge
    'FLAT': 0.30,                    # Very low — if FLAT exceeds this, cautiously allow
}
SYSTEMIC_LOSS_WINDOW_MIN = 30        # Look back 30 minutes for loss detection
SYSTEMIC_LOSS_THRESHOLD = 3          # 3+ losses in window triggers caution
SYSTEMIC_SIZING_MULTIPLIER = 0.5     # Cut position size in half during systemic loss

# === HOUR-BASED SIZING (Era 7, updated Era 9) ===
# Multiplier applied to dynamic max contracts based on hour of day (UTC)
# 1.0 = normal, 0.5 = half size. Updated with Era 8 data.
HOUR_SIZING_MULTIPLIER = {
    0: 0.5, 1: 0.75, 2: 0.5, 3: 0.5, 4: 0.75, 5: 1.0,
    6: 0.75, 7: 0.75, 8: 1.0, 9: 0.5,             # Era 9: hour 9 reduced (0/3 WR)
    10: 1.0, 11: 0.75, 12: 1.0, 13: 0.5,           # Era 9: hour 13 reduced (0/1 WR)
    14: 0.5, 15: 0.5,                               # Era 9: US market open reduced (2/11 = 18.2% WR)
    16: 1.0, 17: 0.75, 18: 0.5,                     # Era 9: hour 18 reduced (0/3 WR)
    19: 0.5, 20: 1.0, 21: 0.5, 22: 1.0, 23: 0.75,  # Era 9: hour 21 reduced (0/4), hour 20/22 kept (75%/67%)
}

# === LAYER 2: Additional Data Sources ===
SERIES_TO_COINBASE = {
    'KXBTC15M': 'BTC-USD', 'KXETH15M': 'ETH-USD',
    'KXSOL15M': 'SOL-USD', 'KXXRP15M': 'XRP-USD',
}
SERIES_TO_KRAKEN = {
    'KXBTC15M': 'XBTUSD', 'KXETH15M': 'ETHUSD',
    'KXSOL15M': 'SOLUSD', 'KXXRP15M': 'XRPUSD',
}
SERIES_TO_OKX_PERP = {
    'KXBTC15M': 'BTC-USDT-SWAP', 'KXETH15M': 'ETH-USDT-SWAP',
    'KXSOL15M': 'SOL-USDT-SWAP', 'KXXRP15M': 'XRP-USDT-SWAP',
}
SIGNAL_CONVERGENCE_WEIGHT = 0.15     # New Signal D: OKX perp vs spot spread

# Database configuration
DB_PATH = 'data/enhanced_15min_trader_fixed.db'

# ============================================================
# DATABASE SETUP
# ============================================================

def setup_database():
    """Initialize SQLite database for persistent state tracking."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Trades table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            order_id TEXT,
            direction TEXT,           -- YES or NO
            entry_price INTEGER,      -- cents
            contracts INTEGER,
            cost_basis INTEGER,       -- entry_price * contracts (cents)
            estimated_win_prob REAL,
            ev_per_contract REAL,
            kelly_fraction REAL,
            entry_time TEXT,
            expiry_time TEXT,
            status TEXT DEFAULT 'open', -- open, won, lost, cancelled
            exit_price INTEGER,
            realized_pnl INTEGER,     -- cents, actual outcome
            signal_source TEXT,
            market_resolution TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Scans table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS scans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_time TEXT,
            markets_found INTEGER,
            signals_found INTEGER,
            trades_taken INTEGER,
            balance_cents INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Market data table for backtesting
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS market_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT,
            timestamp TEXT,
            yes_ask INTEGER,
            no_ask INTEGER,
            volume INTEGER,
            status TEXT,
            close_time TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # External spot price history for momentum calculation
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS spot_prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            series_ticker TEXT NOT NULL,
            spot_price REAL NOT NULL,
            source TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_spot_prices_series_ts
        ON spot_prices(series_ticker, timestamp DESC)
    ''')

    # Signal log: captures EVERY signal evaluation (placed or declined)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS signal_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            series_ticker TEXT NOT NULL,
            scan_time TEXT NOT NULL,
            close_time TEXT,
            yes_ask INTEGER,
            no_ask INTEGER,
            spot_price REAL,
            floor_strike REAL,
            signal_a REAL,
            signal_b REAL,
            signal_c REAL,
            win_prob REAL,
            yes_ev REAL,
            no_ev REAL,
            best_direction TEXT,
            best_ev REAL,
            kelly_frac REAL,
            action_taken TEXT NOT NULL,
            decline_reason TEXT,
            actual_result TEXT,
            signal_correct INTEGER,
            would_have_won INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_signal_log_ticker
        ON signal_log(ticker)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_signal_log_unresolved
        ON signal_log(actual_result)
        WHERE actual_result IS NULL
    ''')

    # === LAYER 1 + 2 DB MIGRATIONS (safe if columns already exist) ===
    # signal_log additions for L1
    for col in ['agreement_strength TEXT', 'volatility REAL', 'hour_utc INTEGER', 'gate_declined TEXT']:
        try:
            cursor.execute(f'ALTER TABLE signal_log ADD COLUMN {col}')
        except Exception:
            pass  # Column already exists

    # signal_log additions for L2
    for col in ['signal_d REAL', 'perp_price REAL',
                'weight_a REAL', 'weight_b REAL', 'weight_c REAL', 'weight_d REAL']:
        try:
            cursor.execute(f'ALTER TABLE signal_log ADD COLUMN {col}')
        except Exception:
            pass

    # signal_log additions for Era 7 (trend + performance feedback)
    for col in ['signal_e REAL', 'weight_e REAL', 'perf_adjustment REAL']:
        try:
            cursor.execute(f'ALTER TABLE signal_log ADD COLUMN {col}')
        except Exception:
            pass

    # signal_log additions for Era 8 (adaptive penalty)
    for col in ['adaptive_penalty REAL', 'trend_20m REAL', 'macro_trend REAL', 'trend_regime TEXT']:
        try:
            cursor.execute(f'ALTER TABLE signal_log ADD COLUMN {col}')
        except Exception:
            pass

    # signal_log additions for Era 10 (EV-first architecture)
    for col in ['payoff_multiple REAL', 'adjusted_ev REAL', 'entry_band TEXT', 'entry_band_sizing REAL']:
        try:
            cursor.execute(f'ALTER TABLE signal_log ADD COLUMN {col}')
        except Exception:
            pass

    # Feature log table for ML training data (Layer 3 prep)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS feature_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            series_ticker TEXT NOT NULL,
            scan_time TEXT NOT NULL,
            close_time TEXT,
            time_remaining_sec INTEGER,
            spot_price_coinbase REAL,
            spot_price_kraken REAL,
            spot_price_binance_spot REAL,
            binance_perp_price REAL,
            floor_strike REAL,
            spot_vs_strike_distance REAL,
            momentum_5min REAL,
            convergence_spread REAL,
            realized_vol_30min REAL,
            cross_exchange_spread REAL,
            signal_a REAL,
            signal_b REAL,
            signal_c REAL,
            signal_d REAL,
            win_prob REAL,
            weight_a REAL,
            weight_b REAL,
            weight_c REAL,
            weight_d REAL,
            actual_result TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_feature_log_unresolved
        ON feature_log(actual_result)
        WHERE actual_result IS NULL
    ''')

    # === FILL TRACKING: trades table migration ===
    for col in ['filled_count INTEGER DEFAULT 0', 'order_status TEXT DEFAULT "pending"', 'requested_contracts INTEGER']:
        try:
            cursor.execute(f'ALTER TABLE trades ADD COLUMN {col}')
        except Exception:
            pass

    conn.commit()
    conn.close()

# ============================================================
# AUTHENTICATION FUNCTIONS
# ============================================================

def get_headers(auth, method: str, path: str) -> dict:
    """Generate authenticated headers using the correct method."""
    timestamp = str(int(dt.now(timezone.utc).timestamp() * 1000))
    path_without_query = path.split("?")[0]
    msg = timestamp + method.upper() + path_without_query

    signature = ""
    if auth.private_key:
        sig_bytes = auth.private_key.sign(
            msg.encode(),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH
            ),
            hashes.SHA256()
        )
        signature = base64.b64encode(sig_bytes).decode()

    return {
        "KALSHI-ACCESS-KEY": auth.api_key_id,
        "KALSHI-ACCESS-SIGNATURE": signature,
        "KALSHI-ACCESS-TIMESTAMP": timestamp,
        "Content-Type": "application/json",
    }

# ============================================================
# BALANCE FUNCTIONS
# ============================================================

def get_live_balance(auth):
    """Get live portfolio balance from API."""
    try:
        timestamp = str(int(dt.now(timezone.utc).timestamp() * 1000))
        path = "/trade-api/v2/portfolio/balance"
        method = "GET"
        
        headers = get_headers(auth, method, path)
        url = "https://api.elections.kalshi.com" + path
        resp = requests.get(url, headers=headers, timeout=15)
        
        if resp.status_code == 200:
            balance_data = resp.json()
            return balance_data.get("balance", 0)
        else:
            print(f"❌ Balance check failed: {resp.status_code}")
            return 0
    except Exception as e:
        print(f"❌ Balance error: {e}")
        return 0

# ============================================================
# EXTERNAL PRICE FEEDS
# ============================================================

def _fetch_coinbase_price(pair):
    """Fetch current price from Coinbase (BRTI constituent, primary). Returns float or None."""
    try:
        resp = requests.get(
            f'https://api.coinbase.com/v2/prices/{pair}/spot',
            timeout=5
        )
        if resp.status_code == 200:
            return float(resp.json()['data']['amount'])
    except Exception:
        pass
    return None

def _fetch_kraken_price(pair):
    """Fetch current price from Kraken (BRTI constituent, secondary). Returns float or None."""
    try:
        resp = requests.get(
            'https://api.kraken.com/0/public/Ticker',
            params={'pair': pair},
            timeout=5
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get('error') and len(data['error']) > 0:
                return None
            result = data.get('result', {})
            # Kraken returns keys like XXBTZUSD or XBTUSD — get first key
            for key in result:
                return float(result[key]['c'][0])  # 'c' = last trade close [price, lot-volume]
    except Exception:
        pass
    return None

def _fetch_binance_price(symbol):
    """Fetch current price from Binance.US public API (fallback). Returns float or None.
    Note: binance.com returns 451 in the US; binance.us works."""
    try:
        resp = requests.get(
            'https://api.binance.us/api/v3/ticker/price',
            params={'symbol': symbol},
            timeout=5
        )
        if resp.status_code == 200:
            return float(resp.json()['price'])
    except Exception:
        pass
    return None

def _fetch_okx_perp_price(inst_id):
    """Fetch OKX perpetual futures last price (leading indicator).
    OKX public market data API is accessible from the US.
    Returns float or None."""
    try:
        resp = requests.get(
            'https://www.okx.com/api/v5/market/ticker',
            params={'instId': inst_id},
            timeout=5
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get('data'):
                return float(data['data'][0]['last'])
    except Exception:
        pass
    # Fallback: mark price endpoint
    try:
        resp = requests.get(
            'https://www.okx.com/api/v5/public/mark-price',
            params={'instType': 'SWAP', 'instId': inst_id},
            timeout=5
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get('data'):
                return float(data['data'][0]['markPx'])
    except Exception:
        pass
    return None

def _fetch_coingecko_price(coin_id):
    """Fetch current price from CoinGecko (last resort fallback). Returns float or None."""
    try:
        resp = requests.get(
            'https://api.coingecko.com/api/v3/simple/price',
            params={'ids': coin_id, 'vs_currencies': 'usd'},
            timeout=5
        )
        if resp.status_code == 200:
            return resp.json()[coin_id]['usd']
    except Exception:
        pass
    return None

# Module-level cache for multi-exchange prices (for cross-exchange spread)
_multi_price_cache = {}

def get_spot_price(series_ticker):
    """
    Get current spot price for a crypto asset.
    Priority: Coinbase (BRTI) → Kraken (BRTI) → Binance.US (fallback) → CoinGecko (last resort).
    Uses a 10-second TTL cache to avoid redundant calls within the same scan.
    Also fetches all exchange prices for cross-exchange spread calculation.
    Returns (price_float, source_string) or (None, None) on failure.
    """
    global _spot_price_cache, _multi_price_cache

    now = dt.now(timezone.utc)
    cache_key = series_ticker

    # Check cache
    cached = _spot_price_cache.get(cache_key)
    if cached and (now - cached['fetched_at']).total_seconds() < CACHE_TTL_SECONDS:
        return cached['price'], cached['source']

    price = None
    source = None
    prices_by_exchange = {}

    # 1. Coinbase (BRTI constituent — primary)
    coinbase_pair = SERIES_TO_COINBASE.get(series_ticker)
    if coinbase_pair:
        cb_price = _fetch_coinbase_price(coinbase_pair)
        if cb_price is not None:
            prices_by_exchange['coinbase'] = cb_price
            if price is None:
                price, source = cb_price, 'coinbase'

    # 2. Kraken (BRTI constituent — secondary)
    kraken_pair = SERIES_TO_KRAKEN.get(series_ticker)
    if kraken_pair:
        kr_price = _fetch_kraken_price(kraken_pair)
        if kr_price is not None:
            prices_by_exchange['kraken'] = kr_price
            if price is None:
                price, source = kr_price, 'kraken'

    # 3. Binance.US (fallback — NOT in BRTI)
    binance_symbol = SERIES_TO_BINANCE.get(series_ticker)
    if binance_symbol:
        bn_price = _fetch_binance_price(binance_symbol)
        if bn_price is not None:
            prices_by_exchange['binance'] = bn_price
            if price is None:
                price, source = bn_price, 'binance'

    # 4. CoinGecko (last resort)
    if price is None:
        coingecko_id = SERIES_TO_COINGECKO.get(series_ticker)
        if coingecko_id:
            cg_price = _fetch_coingecko_price(coingecko_id)
            if cg_price is not None:
                prices_by_exchange['coingecko'] = cg_price
                price, source = cg_price, 'coingecko'

    # Cache result
    if price is not None:
        _spot_price_cache[cache_key] = {
            'price': price,
            'source': source,
            'fetched_at': now,
        }
        _multi_price_cache[cache_key] = {
            'prices': prices_by_exchange,
            'fetched_at': now,
        }
        return price, source

    return None, None

def get_multi_exchange_prices(series_ticker):
    """Return cached dict of {exchange: price} from most recent get_spot_price() call."""
    cached = _multi_price_cache.get(series_ticker)
    if cached and (dt.now(timezone.utc) - cached['fetched_at']).total_seconds() < CACHE_TTL_SECONDS * 2:
        return cached['prices']
    return {}

def get_perp_price(series_ticker):
    """Get OKX perpetual futures price for convergence signal."""
    inst_id = SERIES_TO_OKX_PERP.get(series_ticker)
    if inst_id:
        return _fetch_okx_perp_price(inst_id)
    return None

def calculate_cross_exchange_spread(series_ticker):
    """Calculate spread between exchange prices. Returns (spread_pct, num_exchanges)."""
    prices = get_multi_exchange_prices(series_ticker)
    if len(prices) < 2:
        return 0.0, len(prices)
    vals = list(prices.values())
    avg = sum(vals) / len(vals)
    if avg == 0:
        return 0.0, len(prices)
    spread = (max(vals) - min(vals)) / avg
    return spread, len(prices)

def store_spot_price(series_ticker, price, source):
    """Store spot price in DB for momentum calculation."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO spot_prices (series_ticker, spot_price, source, timestamp)
            VALUES (?, ?, ?, ?)
        ''', (series_ticker, price, source, dt.now(timezone.utc).isoformat()))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"⚠️ Failed to store spot price: {e}")

# ============================================================
# STRIKE PRICE PARSING
# ============================================================

def parse_strike_price(title):
    """
    Extract the strike price from a Kalshi market title.
    Examples:
        "BTC above $100,000 at 2:45 PM ET?" -> 100000.0
        "ETH above $3,500.50 at 10:00 AM ET?" -> 3500.50
    Returns float or None.
    """
    match = STRIKE_PATTERN.search(title)
    if match:
        price_str = match.group(1).replace(',', '')
        try:
            return float(price_str)
        except ValueError:
            return None
    return None

def parse_direction_from_title(title):
    """
    Determine if the market is 'above' or 'below' style.
    Most 15-min crypto markets are 'above' style.
    Returns 'above' or 'below'.
    """
    if 'below' in title.lower():
        return 'below'
    return 'above'

# ============================================================
# MOMENTUM CALCULATION
# ============================================================

def get_recent_spot_prices(series_ticker, lookback_seconds=300):
    """
    Get recent spot prices from DB for momentum calculation.
    Returns list of (timestamp_str, price) tuples, oldest first.
    Default lookback: 300 seconds (5 minutes).
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cutoff = (dt.now(timezone.utc) - timedelta(seconds=lookback_seconds)).isoformat()
        cursor.execute('''
            SELECT timestamp, spot_price FROM spot_prices
            WHERE series_ticker = ? AND timestamp > ?
            ORDER BY timestamp ASC
        ''', (series_ticker, cutoff))
        rows = cursor.fetchall()
        conn.close()
        return rows
    except Exception:
        return []

def calculate_price_momentum(series_ticker):
    """
    Calculate momentum metrics from recent spot price history.
    Returns dict with velocity, pct_change, direction, num_samples, etc.
    """
    rows = get_recent_spot_prices(series_ticker, lookback_seconds=300)

    result = {
        'velocity': 0.0,
        'pct_change': 0.0,
        'num_samples': len(rows),
        'direction': 'flat',
        'current_price': None,
        'oldest_price': None,
        'window_seconds': 0,
    }

    if len(rows) < 2:
        return result

    oldest_ts, oldest_price = rows[0]
    newest_ts, newest_price = rows[-1]

    try:
        oldest_dt = dt.fromisoformat(oldest_ts)
        newest_dt = dt.fromisoformat(newest_ts)
        elapsed = (newest_dt - oldest_dt).total_seconds()
    except Exception:
        return result

    if elapsed <= 0 or oldest_price <= 0:
        return result

    price_change = newest_price - oldest_price
    pct_change = price_change / oldest_price
    velocity = price_change / elapsed

    result['velocity'] = velocity
    result['pct_change'] = pct_change
    result['current_price'] = newest_price
    result['oldest_price'] = oldest_price
    result['window_seconds'] = elapsed

    if pct_change > 0.001:       # > 0.1% up
        result['direction'] = 'up'
    elif pct_change < -0.001:    # > 0.1% down
        result['direction'] = 'down'
    else:
        result['direction'] = 'flat'

    return result

def _get_trend_pct_change(series_ticker, lookback_seconds):
    """Get percentage price change over a lookback window."""
    rows = get_recent_spot_prices(series_ticker, lookback_seconds=lookback_seconds)
    if len(rows) < 3:
        return 0.0
    oldest_price = rows[0][1]
    newest_price = rows[-1][1]
    if oldest_price <= 0:
        return 0.0
    return (newest_price - oldest_price) / oldest_price

def calculate_trend_signal(series_ticker, strike_type):
    """
    Multi-timeframe trend signal using 30-min and 2-hour price history.
    Returns a signal value in [0.35, 0.65] where >0.5 = bullish, <0.5 = bearish.
    Combines two timeframes: 30-min (responsive) and 2-hr (stable).
    """
    trend_30m = _get_trend_pct_change(series_ticker, TREND_30M_LOOKBACK)
    trend_2h = _get_trend_pct_change(series_ticker, TREND_2H_LOOKBACK)

    # Weighted blend: 60% 30-min, 40% 2-hour
    offset_30m = max(-0.15, min(0.15, trend_30m * TREND_30M_MULTIPLIER))
    offset_2h = max(-0.15, min(0.15, trend_2h * TREND_2H_MULTIPLIER))
    blended_offset = 0.6 * offset_30m + 0.4 * offset_2h

    # Flip for below-strike markets
    if strike_type in ('greater_or_equal', 'greater'):
        signal = 0.5 + blended_offset
    else:
        signal = 0.5 - blended_offset

    return max(0.35, min(0.65, signal))


def calculate_adaptive_penalty(series_ticker):
    """
    Adaptive directional penalty based on asset-specific + macro trend.
    Returns (penalty_float, trend_detail_dict).

    penalty > 0 → penalize YES (bear/flat)
    penalty < 0 → penalize NO (bull)
    ~0.005 in flat markets (identical to old static penalty)

    Two layers:
    1. Asset-specific: 20-min price trend for this specific asset (70% weight)
    2. Macro: average 20-min trend across all 4 crypto assets (30% weight)
    """
    import math

    # Asset-specific trend (20 min)
    rows = get_recent_spot_prices(series_ticker, lookback_seconds=ADAPTIVE_PENALTY_LOOKBACK)
    if len(rows) < ADAPTIVE_PENALTY_MIN_SAMPLES:
        # Insufficient data — fall back to static YES penalty
        return ADAPTIVE_PENALTY_BASE, {
            'asset_trend': 0.0, 'macro_trend': 0.0, 'macro_spread': 0.0,
            'trend_strength': 0.0, 'regime': 'FLAT', 'divergent': False,
        }

    asset_trend = _get_trend_pct_change(series_ticker, ADAPTIVE_PENALTY_LOOKBACK)

    # Macro trend: average 20-min trend across all 4 assets
    all_trends = []
    for ticker in ALL_SERIES_TICKERS:
        t = _get_trend_pct_change(ticker, ADAPTIVE_PENALTY_LOOKBACK)
        all_trends.append(t)

    macro_trend = sum(all_trends) / len(all_trends) if all_trends else 0.0
    macro_spread = max(all_trends) - min(all_trends) if all_trends else 0.0

    # Blend: 70% asset-specific, 30% macro
    blended = (ADAPTIVE_PENALTY_ASSET_WEIGHT * asset_trend +
               ADAPTIVE_PENALTY_MACRO_WEIGHT * macro_trend)

    # Smooth scaling with tanh — graceful saturation, no hard clipping
    # pct_change is a decimal (e.g., 0.002 = 0.2%), so multiply by 100 first
    raw_strength = blended * ADAPTIVE_PENALTY_SENSITIVITY * 100
    trend_strength = math.tanh(raw_strength)

    # Map trend_strength to penalty:
    # trend_strength =  0.0 (flat)  → penalty = +BASE (current behavior)
    # trend_strength = +1.0 (bull)  → penalty = -MAX  (penalize NO)
    # trend_strength = -1.0 (bear)  → penalty = +MAX  (penalize YES harder)
    if trend_strength >= 0:
        # Bullish: shift penalty from +BASE toward -MAX
        penalty = ADAPTIVE_PENALTY_BASE - trend_strength * (ADAPTIVE_PENALTY_BASE + ADAPTIVE_PENALTY_MAX)
    else:
        # Bearish: shift penalty from +BASE toward +MAX
        penalty = ADAPTIVE_PENALTY_BASE + abs(trend_strength) * (ADAPTIVE_PENALTY_MAX - ADAPTIVE_PENALTY_BASE)

    penalty = max(-ADAPTIVE_PENALTY_MAX, min(ADAPTIVE_PENALTY_MAX, penalty))

    # Classify regime for logging
    if trend_strength > 0.3:
        regime = 'BULL'
    elif trend_strength < -0.3:
        regime = 'BEAR'
    else:
        regime = 'FLAT'

    detail = {
        'asset_trend': asset_trend,
        'macro_trend': macro_trend,
        'macro_spread': macro_spread,
        'trend_strength': trend_strength,
        'regime': regime,
        'divergent': macro_spread > MACRO_DIVERGENCE_THRESHOLD,
    }

    return penalty, detail


# ============================================================
# ERA 9: ROLLING REGIME LEARNING
# ============================================================

def get_regime_direction_wr(regime, direction, lookback_hours):
    """
    Get win rate for a specific regime+direction combo from recent signal_log.
    Returns (win_rate, sample_size) or (None, 0) if insufficient data.
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cutoff = (dt.now(timezone.utc) - timedelta(hours=lookback_hours)).isoformat()

        cursor.execute('''
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN would_have_won = 1 THEN 1 ELSE 0 END) as wins
            FROM signal_log
            WHERE action_taken = 'placed'
              AND actual_result IS NOT NULL
              AND trend_regime = ?
              AND best_direction = ?
              AND created_at > ?
        ''', (regime, direction, cutoff))

        row = cursor.fetchone()
        conn.close()

        total = row[0] or 0
        wins = row[1] or 0
        if total >= REGIME_LEARNING_MIN_SAMPLES:
            return wins / total, total
        return None, total
    except Exception:
        return None, 0


def get_regime_permissions():
    """
    Query last N hours of placed trades, compute WR by regime+direction,
    return dict of allowed regime+direction combos.
    Starts with static defaults from REGIME_ALLOWED_DIRECTIONS, then adapts
    based on rolling performance if enough samples exist.
    """
    # Build default permission set from config
    permissions = {}
    for regime in ['BEAR', 'BULL', 'FLAT']:
        for direction in ['YES', 'NO']:
            allowed_dirs = REGIME_ALLOWED_DIRECTIONS.get(regime, [])
            permissions[(regime, direction)] = direction in allowed_dirs

    if not REGIME_LEARNING_ENABLED:
        return permissions

    # Override with rolling performance data
    for (regime, direction) in permissions.keys():
        wr, n = get_regime_direction_wr(regime, direction, REGIME_LEARNING_WINDOW_HOURS)
        if wr is not None and n >= REGIME_LEARNING_MIN_SAMPLES:
            if wr >= REGIME_UNLOCK_THRESHOLD and not permissions[(regime, direction)]:
                permissions[(regime, direction)] = True
                print(f"    🔓 Regime learning: UNLOCKED {regime}+{direction} (WR={wr:.1%}, n={n})")
            elif wr < REGIME_LOCK_THRESHOLD and permissions[(regime, direction)]:
                permissions[(regime, direction)] = False
                print(f"    🔒 Regime learning: LOCKED {regime}+{direction} (WR={wr:.1%}, n={n})")

    return permissions


# ============================================================
# ERA 9: POOLED PERFORMANCE FEEDBACK
# ============================================================

def get_pooled_direction_performance(direction, lookback_hours=None, regime=None):
    """
    Era 9: Get recent WR for a direction across ALL assets (pooled).
    Optionally filtered by regime. Replaces per-asset feedback that never activated.
    Returns (win_rate, sample_size) or (None, 0) if insufficient data.
    """
    if lookback_hours is None:
        lookback_hours = PERF_LOOKBACK_HOURS
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cutoff = (dt.now(timezone.utc) - timedelta(hours=lookback_hours)).isoformat()

        if regime:
            # Join with signal_log to filter by regime
            cursor.execute('''
                SELECT COUNT(*) as total,
                       SUM(CASE WHEN t.status='won' THEN 1 ELSE 0 END) as wins
                FROM trades t
                JOIN signal_log s ON s.ticker = t.ticker
                  AND s.action_taken = 'placed'
                  AND ABS(julianday(s.scan_time) - julianday(t.entry_time)) < 0.005
                WHERE t.direction = ?
                  AND t.status IN ('won', 'lost')
                  AND t.entry_time > ?
                  AND s.trend_regime = ?
            ''', (direction, cutoff, regime))
        else:
            cursor.execute('''
                SELECT COUNT(*) as total,
                       SUM(CASE WHEN status='won' THEN 1 ELSE 0 END) as wins
                FROM trades
                WHERE direction = ?
                  AND status IN ('won', 'lost')
                  AND entry_time > ?
            ''', (direction, cutoff))

        row = cursor.fetchone()
        conn.close()

        total = row[0] or 0
        wins = row[1] or 0
        if total >= PERF_MIN_TRADES:
            return wins / total, total
        return None, total
    except Exception:
        return None, 0


# ============================================================
# ERA 9: ASSET-SPECIFIC SIZING LEARNING
# ============================================================

def get_learned_asset_sizing_multiplier(series_ticker):
    """
    Era 9: Compute asset-specific sizing multiplier from rolling 24h performance.
    Falls back to static ASSET_SIZING_MULTIPLIER if insufficient data.
    """
    if not ASSET_SIZING_LEARNING_ENABLED:
        return ASSET_SIZING_MULTIPLIER.get(series_ticker, 1.0)

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cutoff = (dt.now(timezone.utc) - timedelta(hours=ASSET_SIZING_LEARNING_HOURS)).isoformat()
        ticker_prefix = series_ticker[:5] + '%'

        cursor.execute('''
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN status='won' THEN 1 ELSE 0 END) as wins
            FROM trades
            WHERE ticker LIKE ?
              AND status IN ('won', 'lost')
              AND entry_time > ?
        ''', (ticker_prefix, cutoff))

        row = cursor.fetchone()
        conn.close()

        total = row[0] or 0
        wins = row[1] or 0

        if total < ASSET_SIZING_MIN_SAMPLES:
            # Not enough data — use static default
            return ASSET_SIZING_MULTIPLIER.get(series_ticker, 1.0)

        wr = wins / total
        # Scale multiplier: 50% WR = 1.0x, 30% WR = 0.5x, 70% WR = 1.5x
        # Linear mapping: multiplier = 0.5 + (wr - 0.3) * (1.0 / 0.2)
        multiplier = 0.5 + (wr - 0.30) * 2.5
        multiplier = max(ASSET_SIZING_FLOOR, min(ASSET_SIZING_CEILING, multiplier))

        static_default = ASSET_SIZING_MULTIPLIER.get(series_ticker, 1.0)
        # Blend 60% learned + 40% static to avoid wild swings
        blended = 0.6 * multiplier + 0.4 * static_default

        return max(ASSET_SIZING_FLOOR, min(ASSET_SIZING_CEILING, blended))
    except Exception:
        return ASSET_SIZING_MULTIPLIER.get(series_ticker, 1.0)


# ============================================================
# LAYER 1: TRADE QUALITY HELPERS
# ============================================================

def check_signal_agreement(signal_a, signal_b):
    """
    Check if sub-signals A and B agree on direction.
    Era 9: Now also used as a hard gate (REQUIRE_SIGNAL_AGREEMENT).
    Returns (strength, agrees):
      ('strong', True) if both >0.53 or both <0.47
      ('weak', True) if both >0.51 or both <0.49
      (None, False) if they disagree
    """
    both_yes_strong = (signal_a > 0.53 and signal_b > 0.53)
    both_no_strong = (signal_a < 0.47 and signal_b < 0.47)
    if both_yes_strong or both_no_strong:
        return ('strong', True)

    both_yes_weak = (signal_a > 0.51 and signal_b > 0.51)
    both_no_weak = (signal_a < 0.49 and signal_b < 0.49)
    if both_yes_weak or both_no_weak:
        return ('weak', True)

    return (None, False)

def calculate_volatility(series_ticker):
    """
    Calculate realized volatility from recent spot price history.
    Uses log returns stddev over the last VOLATILITY_LOOKBACK_SECONDS.
    Returns (volatility_float, num_samples).
    """
    import math
    rows = get_recent_spot_prices(series_ticker, lookback_seconds=VOLATILITY_LOOKBACK_SECONDS)
    if len(rows) < 3:
        return 0.0, len(rows)

    prices = [r[1] for r in rows if r[1] and r[1] > 0]
    if len(prices) < 3:
        return 0.0, len(prices)

    # Compute log returns
    log_returns = []
    for i in range(1, len(prices)):
        if prices[i] > 0 and prices[i-1] > 0:
            log_returns.append(math.log(prices[i] / prices[i-1]))

    if len(log_returns) < 2:
        return 0.0, len(prices)

    # Standard deviation of log returns
    mean_ret = sum(log_returns) / len(log_returns)
    variance = sum((r - mean_ret) ** 2 for r in log_returns) / (len(log_returns) - 1)
    volatility = math.sqrt(variance)

    return volatility, len(prices)

def get_current_hour_utc():
    """Return current hour in UTC (0-23)."""
    return dt.now(timezone.utc).hour

# ============================================================
# LAYER 2: CONVERGENCE SIGNAL + ADAPTIVE WEIGHTING
# ============================================================

def calculate_convergence_signal(series_ticker, spot_price, strike_type='greater_or_equal'):
    """
    Compute Signal D: OKX perpetual vs BRTI constituent spot spread.
    When perp > spot, the settlement index tends to drift up (bullish YES).
    Returns (signal_d_float, perp_price_or_None).
    """
    perp_price = get_perp_price(series_ticker)
    if perp_price is None or spot_price is None or spot_price <= 0:
        return 0.5, None  # neutral if no perp data

    spread = (perp_price - spot_price) / spot_price
    # 50x multiplier: 0.1% spread = 0.05 offset (significant signal)
    if strike_type in ('greater_or_equal', 'greater'):
        convergence_offset = max(-0.15, min(0.15, spread * 50))
    else:
        convergence_offset = max(-0.15, min(0.15, -spread * 50))

    signal_d = 0.5 + convergence_offset
    return signal_d, perp_price

def get_adaptive_weights(volatility, time_remaining_seconds):
    """
    Return signal weights (w_a, w_b, w_d, w_c, w_e) based on market conditions.
    Adjusts for volatility regime and time-to-expiry.
    w_e = multi-timeframe trend signal weight (Era 7).
    """
    # Default weights
    w_a = SIGNAL_SPOT_VS_STRIKE_WEIGHT   # 0.45
    w_b = SIGNAL_MOMENTUM_WEIGHT         # 0.50
    w_d = SIGNAL_CONVERGENCE_WEIGHT      # 0.15
    w_c = SIGNAL_ORDERBOOK_WEIGHT        # 0.05
    w_e = SIGNAL_TREND_WEIGHT            # 0.10

    # Volatility regime adaptation
    if volatility > 0 and volatility < VOLATILITY_LOW_THRESHOLD * 2:
        # Low vol: trust momentum + trend more (trends persist in calm markets)
        w_b = 0.50
        w_a = 0.25
        w_d = 0.10
        w_c = 0.05
        w_e = 0.15   # Trend matters more in low vol
    elif volatility > VOLATILITY_LOW_THRESHOLD * 10:
        # High vol: trust distance + convergence (mean reversion, choppy momentum)
        w_a = 0.40
        w_d = 0.25
        w_b = 0.20
        w_c = 0.05
        w_e = 0.12   # Trend still useful for regime detection

    # Time decay: as expiry approaches, spot-vs-strike distance dominates
    if time_remaining_seconds is not None and time_remaining_seconds > 0:
        if time_remaining_seconds < 180:   # <3 min: distance is almost everything
            w_a = 0.55
            w_b = 0.15
            w_d = 0.20
            w_c = 0.05
            w_e = 0.05   # Trend less relevant near expiry
        elif time_remaining_seconds < 420:  # <7 min: distance matters more
            w_a = 0.40
            w_b = 0.25
            w_d = 0.20
            w_c = 0.05
            w_e = 0.08

    # Normalize to sum to 1.0
    total = w_a + w_b + w_d + w_c + w_e
    if total > 0:
        w_a, w_b, w_d, w_c, w_e = w_a/total, w_b/total, w_d/total, w_c/total, w_e/total

    return w_a, w_b, w_d, w_c, w_e

# ============================================================
# SIGNAL GENERATION (EXTERNAL)
# ============================================================

def _calculate_external_signal_impl(market_data):
    """
    EXTERNAL SIGNAL implementation. Returns a dict with full sub-signal breakdown.

    These markets are "price up" style: YES wins if the crypto price at expiry
    is >= floor_strike (the price at market open). The floor_strike comes from
    the API field, NOT from the title.

    Sub-signals:
      A) Spot vs Strike: Is current spot above/below floor_strike?
      B) Price Momentum: Is crypto trending up/down over last 5 minutes?
      C) Orderbook Imbalance: Minor confirmation from Kalshi bid/ask skew.
      D) Convergence: Binance perp vs BRTI constituent spread (leading indicator).

    Weights are adaptive based on volatility regime and time-to-expiry.

    Returns dict with keys: win_prob, signal_a, signal_b, signal_c, signal_d,
                           spot_price, perp_price, volatility, weights_used
    """
    neutral = {'win_prob': 0.5, 'signal_a': 0.5, 'signal_b': 0.5, 'signal_c': 0.5,
               'signal_d': 0.5, 'signal_e': 0.5, 'spot_price': None, 'perp_price': None,
               'volatility': 0.0, 'weights_used': (0.45, 0.50, 0.15, 0.05, 0.10)}

    series_ticker = market_data.get('series', '')
    title = market_data.get('title', '')
    yes_ask = market_data.get('yes_ask', 0)
    no_ask = market_data.get('no_ask', 0)
    floor_strike = market_data.get('floor_strike', None)
    strike_type = market_data.get('strike_type', 'greater_or_equal')

    # Basic validation
    if not series_ticker or yes_ask == 0 or no_ask == 0:
        return neutral

    # --- Fetch external spot price ---
    spot_price, source = get_spot_price(series_ticker)
    if spot_price is None:
        print(f"    ⚠️  No spot price available for {series_ticker}, skipping signal")
        return neutral

    # Store for momentum history
    store_spot_price(series_ticker, spot_price, source)

    # --- Sub-signal A: Spot vs Strike (weight: 0.35) ---
    spot_vs_strike_signal = 0.5  # neutral default

    if floor_strike is not None and floor_strike > 0:
        distance = spot_price - floor_strike
        normalized_distance = distance / floor_strike  # fraction of strike

        if strike_type in ('greater_or_equal', 'greater'):
            offset = min(max(normalized_distance * 10, -0.15), 0.15)
        else:
            offset = min(max(-normalized_distance * 10, -0.15), 0.15)

        spot_vs_strike_signal = 0.5 + offset

        print(f"    📍 Spot: ${spot_price:,.2f} ({source}) | Strike: ${floor_strike:,.2f} | "
              f"Dist: {normalized_distance:+.4f} | Signal A: {spot_vs_strike_signal:.3f}")
    else:
        strike_price = parse_strike_price(title)
        if strike_price and strike_price > 0:
            distance = spot_price - strike_price
            normalized_distance = distance / strike_price
            offset = min(max(normalized_distance * 10, -0.15), 0.15)
            spot_vs_strike_signal = 0.5 + offset
            print(f"    📍 Spot: ${spot_price:,.2f} ({source}) | Strike(title): ${strike_price:,.2f} | "
                  f"Dist: {normalized_distance:+.4f} | Signal A: {spot_vs_strike_signal:.3f}")
        else:
            print(f"    📍 Spot: ${spot_price:,.2f} ({source}) | No strike available | Signal A: 0.500")

    # --- Sub-signal B: Price Momentum (weight: 0.50) ---
    momentum = calculate_price_momentum(series_ticker)
    momentum_signal = 0.5  # neutral default

    if momentum['num_samples'] >= SIGNAL_MIN_SAMPLES:
        pct_change = momentum['pct_change']
        momentum_offset = max(-0.15, min(0.15, pct_change * 30))

        if strike_type in ('greater_or_equal', 'greater'):
            momentum_signal = 0.5 + momentum_offset
        else:
            momentum_signal = 0.5 - momentum_offset

        print(f"    📈 Momentum: {pct_change:+.4f} ({momentum['direction']}) | "
              f"{momentum['num_samples']} samples | Signal B: {momentum_signal:.3f}")
    else:
        print(f"    📈 Momentum: insufficient data ({momentum['num_samples']} samples, need {SIGNAL_MIN_SAMPLES})")

    # --- Sub-signal C: Orderbook Imbalance (minor) ---
    orderbook_signal = 0.5
    price_sum = yes_ask + no_ask
    if price_sum > 0:
        imbalance = (no_ask - yes_ask) / price_sum
        orderbook_signal = 0.5 + max(-0.05, min(0.05, imbalance * 0.05))

    # --- Sub-signal D: OKX Perp Convergence (leading indicator) ---
    convergence_signal, perp_price = calculate_convergence_signal(
        series_ticker, spot_price, strike_type
    )
    if perp_price is not None:
        spread_pct = (perp_price - spot_price) / spot_price * 100
        print(f"    🔄 Convergence: Perp=${perp_price:,.2f} Spot=${spot_price:,.2f} "
              f"Spread={spread_pct:+.3f}% | Signal D: {convergence_signal:.3f}")
    else:
        print(f"    🔄 Convergence: No perp data | Signal D: 0.500")

    # --- Sub-signal E: Multi-Timeframe Trend (30-min + 2-hour) ---
    trend_signal = calculate_trend_signal(series_ticker, strike_type)
    print(f"    📊 Trend: Signal E: {trend_signal:.3f}")

    # --- Calculate volatility for adaptive weighting ---
    vol, vol_samples = calculate_volatility(series_ticker)

    # --- Get time remaining for adaptive weighting ---
    close_time_str = market_data.get('close_time')
    time_remaining = None
    if close_time_str:
        try:
            close_dt = dt.fromisoformat(close_time_str.replace('Z', '+00:00'))
            time_remaining = (close_dt - dt.now(timezone.utc)).total_seconds()
        except Exception:
            pass

    # --- Adaptive weights based on volatility and time-to-expiry ---
    w_a, w_b, w_d, w_c, w_e = get_adaptive_weights(vol, time_remaining)

    # --- Combine sub-signals with adaptive weights ---
    raw_signal = (
        spot_vs_strike_signal * w_a +
        momentum_signal * w_b +
        convergence_signal * w_d +
        orderbook_signal * w_c +
        trend_signal * w_e
    )

    win_prob = max(SIGNAL_FLOOR, min(SIGNAL_CEILING, raw_signal))

    print(f"    🎯 Combined: A={spot_vs_strike_signal:.3f}({w_a:.0%}) B={momentum_signal:.3f}({w_b:.0%}) "
          f"C={orderbook_signal:.3f}({w_c:.0%}) D={convergence_signal:.3f}({w_d:.0%}) "
          f"E={trend_signal:.3f}({w_e:.0%}) -> win_prob={win_prob:.3f} [vol={vol:.5f}]")

    return {
        'win_prob': win_prob,
        'signal_a': spot_vs_strike_signal,
        'signal_b': momentum_signal,
        'signal_c': orderbook_signal,
        'signal_d': convergence_signal,
        'signal_e': trend_signal,
        'spot_price': spot_price,
        'perp_price': perp_price,
        'volatility': vol,
        'weights_used': (w_a, w_b, w_d, w_c, w_e),
    }

def calculate_external_signal(market_data):
    """Backward-compatible wrapper: returns just win_prob as float."""
    return _calculate_external_signal_impl(market_data)['win_prob']

def calculate_external_signal_detailed(market_data):
    """Returns full signal breakdown dict for logging."""
    return _calculate_external_signal_impl(market_data)

def calculate_ev(yes_ask, no_ask, win_prob, direction):
    """
    Calculate Expected Value per contract.
    EV = (win_prob * payout) - (loss_prob * cost)
    """
    if direction == 'YES':
        cost = yes_ask
        payout = 100 - cost
    else:  # NO
        cost = no_ask
        payout = 100 - cost
    
    loss_prob = 1 - win_prob
    ev_per_contract = (win_prob * payout) - (loss_prob * cost)
    
    return ev_per_contract

def calculate_kelly_fraction(win_prob, cost):
    """
    Era 12: Restored to Era 2 conviction-based Kelly.
    kelly = |win_prob - 0.5| (distance from coin flip), half-Kelly for safety.
    Era 2 data confirms: kelly_frac ≈ 0.8-0.95x of conviction across all win_probs.
    This sizes by signal strength regardless of direction — higher conviction = more contracts.
    """
    conviction = abs(win_prob - 0.5)
    half_kelly = conviction * KELLY_FRACTION
    return max(0, min(half_kelly, 0.15))  # Cap at 15% of bankroll


# ============================================================
# ERA 10: ENTRY BAND SIZING AND PAYOFF-ADJUSTED EV
# ============================================================

def get_entry_band_sizing(entry_price):
    """
    Era 10: Returns sizing multiplier based on entry price position within the optimal band.
    Rewards the 42-47c sweet spot (full sizing), penalizes edges of the band.
    Returns 0 for prices outside the tradeable range (should be blocked by Gate 1).
    """
    if entry_price < MIN_ENTRY_PRICE or entry_price >= MAX_ENTRY_PRICE:
        return 0.0  # Should not reach here — blocked by Gate 1
    if IDEAL_ENTRY_MIN <= entry_price <= IDEAL_ENTRY_MAX:
        return 1.0  # Full sizing in the sweet spot
    if entry_price < IDEAL_ENTRY_MIN:
        return 0.7  # Cheap but uncertain — higher payoff, lower WR
    if entry_price > IDEAL_ENTRY_MAX:
        return 0.8  # Decent WR but declining payoff asymmetry
    return 1.0


def get_entry_band_label(entry_price):
    """Era 10: Categorize entry price into band label for logging."""
    if entry_price < MIN_ENTRY_PRICE:
        return 'too_cheap'
    if entry_price >= MAX_ENTRY_PRICE:
        return 'too_expensive'
    if entry_price < IDEAL_ENTRY_MIN:
        return 'cheap'
    if entry_price <= IDEAL_ENTRY_MAX:
        return 'ideal'
    return 'marginal'


def calculate_adjusted_ev(raw_ev, entry_price):
    """
    Era 10: Payoff-adjusted EV that gives credit for asymmetric entries.
    At 43c entry (1.33x payoff): bonus = (1.33 - 1.0) * 3.0 = +0.99c
    At 50c entry (1.0x payoff): bonus = 0
    """
    payoff_multiple = (100 - entry_price) / entry_price if entry_price > 0 else 1.0
    bonus = max(0, (payoff_multiple - 1.0)) * ASYMMETRY_BONUS_WEIGHT
    return raw_ev + bonus


def calculate_dynamic_max_contracts(live_balance, price, tier, hour_utc=None, macro_detail=None, series_ticker=None, entry_price=None):
    """
    Calculate max contracts based on balance-scaled risk budget.
    Replaces fixed MAX_EFFECTIVE_CONTRACTS — allows compounding as balance grows.
    At $99 balance with 48c price, produces identical values to old fixed caps (7/4/2).
    Now also applies hour-based sizing, systemic loss reduction, macro trend adjustment,
    and asset-specific sizing (Era 9).
    """
    if tier == 'strong':
        risk_pct = STRONG_RISK_PCT
    elif tier == 'weak':
        risk_pct = WEAK_RISK_PCT
    else:
        risk_pct = BASE_RISK_PCT

    budget_cents = live_balance * risk_pct
    max_contracts = int(budget_cents / price) if price > 0 else 0

    # Apply hour-based sizing multiplier
    if hour_utc is not None and hour_utc in HOUR_SIZING_MULTIPLIER:
        multiplier = HOUR_SIZING_MULTIPLIER[hour_utc]
        if multiplier < 1.0:
            max_contracts = int(max_contracts * multiplier)

    # Apply systemic loss reduction
    if detect_systemic_losses():
        max_contracts = int(max_contracts * SYSTEMIC_SIZING_MULTIPLIER)
        print(f"    ⚠️ Systemic loss detected — sizing reduced by {(1-SYSTEMIC_SIZING_MULTIPLIER)*100:.0f}%")

    # Apply macro trend sizing adjustment (Era 8)
    if macro_detail is not None:
        macro_trend = macro_detail.get('macro_trend', 0)
        divergent = macro_detail.get('divergent', False)

        if divergent:
            # Assets diverging — uncertain regime, reduce sizing
            max_contracts = int(max_contracts * 0.8)
            print(f"    ⚡ Macro divergence — sizing reduced 20%")
        elif abs(macro_trend) > MACRO_TREND_SIZING_THRESHOLD:
            # Strong macro trend aligned with trade direction — slight boost
            max_contracts = int(max_contracts * 1.1)

    # Apply asset-specific sizing multiplier (Era 9)
    if series_ticker:
        asset_mult = get_learned_asset_sizing_multiplier(series_ticker)
        if asset_mult != 1.0:
            max_contracts = int(max_contracts * asset_mult)
            if asset_mult < 0.9:
                print(f"    📉 Asset sizing: {series_ticker[:5]} multiplier={asset_mult:.2f}")

    # Apply entry band sizing multiplier (Era 10)
    if entry_price is not None:
        band_mult = get_entry_band_sizing(entry_price)
        if band_mult < 1.0 and band_mult > 0:
            max_contracts = max(1, int(max_contracts * band_mult))
            print(f"    📊 Entry band sizing: {entry_price}c → {get_entry_band_label(entry_price)} ({band_mult}x)")

    return max(MIN_CONTRACTS, min(max_contracts, MAX_CONTRACTS_CEILING))

def get_asset_direction_performance(series_ticker, direction, lookback_hours=None):
    """
    Get recent WR for a specific asset+direction combo from trades table.
    Returns (win_rate, sample_size) or (None, 0) if insufficient data.
    """
    if lookback_hours is None:
        lookback_hours = PERF_LOOKBACK_HOURS
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cutoff = (dt.now(timezone.utc) - timedelta(hours=lookback_hours)).isoformat()

        # Match series_ticker prefix (KXBTC15M → KXBTC%)
        ticker_prefix = series_ticker[:5] + '%'

        cursor.execute('''
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN status='won' THEN 1 ELSE 0 END) as wins
            FROM trades
            WHERE ticker LIKE ? AND direction = ?
              AND status IN ('won', 'lost')
              AND entry_time > ?
        ''', (ticker_prefix, direction, cutoff))

        row = cursor.fetchone()
        conn.close()

        total = row[0] or 0
        wins = row[1] or 0
        if total >= PERF_MIN_TRADES:
            return wins / total, total
        return None, total
    except Exception:
        return None, 0

def detect_systemic_losses():
    """
    Check if we've had a cluster of recent losses across all assets.
    Returns True if SYSTEMIC_LOSS_THRESHOLD+ losses in the last SYSTEMIC_LOSS_WINDOW_MIN minutes.
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cutoff = (dt.now(timezone.utc) - timedelta(minutes=SYSTEMIC_LOSS_WINDOW_MIN)).isoformat()

        cursor.execute('''
            SELECT COUNT(*) FROM trades
            WHERE status = 'lost' AND entry_time > ?
        ''', (cutoff,))

        loss_count = cursor.fetchone()[0]
        conn.close()
        return loss_count >= SYSTEMIC_LOSS_THRESHOLD
    except Exception:
        return False

# ============================================================
# MARKET DATA FUNCTIONS (FIXED UTC)
# ============================================================

def get_active_15min_markets(auth):
    """Get active 15-minute crypto markets with real pricing."""
    active_markets = []
    
    for series_ticker in CRYPTO_15MIN_SERIES:
        timestamp = str(int(dt.now(timezone.utc).timestamp() * 1000))
        path = f'/trade-api/v2/markets?series_ticker={series_ticker}&status=open&limit=100'
        method = 'GET'
        
        headers = get_headers(auth, method, path)
        url = 'https://api.elections.kalshi.com' + path
        resp = requests.get(url, headers=headers, timeout=15)
        
        if resp.status_code == 200:
            data = resp.json()
            markets = data.get('markets', [])

            # Debug: Show status distribution
            status_counts = {}
            for m in markets:
                s = m.get('status', 'unknown')
                status_counts[s] = status_counts.get(s, 0) + 1
            print(f"    🔍 {series_ticker}: API returned {len(markets)} markets (statuses: {status_counts})")

            for market in markets:
                ticker = market.get('ticker', '')
                title = market.get('title', '')
                yes_ask = market.get('yes_ask', 0)
                no_ask = market.get('no_ask', 0)
                volume = market.get('volume', 0)
                status = market.get('status', '')
                close_time = market.get('close_time', '')
                floor_strike = market.get('floor_strike', None)
                strike_type = market.get('strike_type', '')

                # Check if market has real pricing
                has_pricing = (yes_ask > 0 and yes_ask < 100) or (no_ask > 0 and no_ask < 100)
                is_active = status == 'active'

                # FIXED: Proper UTC datetime handling
                seconds_remaining = 0
                if close_time:
                    try:
                        # Parse close_time as UTC
                        expiry = dt.fromisoformat(close_time.replace('Z', '+00:00'))
                        now_utc = dt.now(timezone.utc)
                        seconds_remaining = (expiry - now_utc).total_seconds()
                    except Exception as e:
                        print(f"❌ Time parsing error for {ticker}: {e}")
                        continue

                # Debug: Log why active markets are rejected
                if is_active and not has_pricing:
                    print(f"    ❌ {ticker}: No pricing (yes={yes_ask}, no={no_ask})")
                elif is_active and seconds_remaining <= 0:
                    print(f"    ❌ {ticker}: Already expired ({seconds_remaining:.0f}s)")
                elif is_active and seconds_remaining <= MIN_TIME_REMAINING:
                    print(f"    ❌ {ticker}: Too close to expiry ({seconds_remaining:.0f}s remaining, need {MIN_TIME_REMAINING}s)")
                elif not is_active:
                    pass  # Don't log non-active markets (too noisy)

                if has_pricing and is_active and seconds_remaining > MIN_TIME_REMAINING:
                    # Store market snapshot
                    store_market_snapshot(ticker, yes_ask, no_ask, volume, status, close_time)

                    active_markets.append({
                        'ticker': ticker,
                        'title': title,
                        'yes_ask': yes_ask,
                        'no_ask': no_ask,
                        'volume': volume,
                        'series': series_ticker,
                        'close_time': close_time,
                        'seconds_remaining': seconds_remaining,
                        'floor_strike': floor_strike,
                        'strike_type': strike_type,
                    })
        else:
            print(f"    ❌ {series_ticker}: API error {resp.status_code}")

    return active_markets

def store_market_snapshot(ticker, yes_ask, no_ask, volume, status, close_time):
    """Store market data for backtesting and analysis."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO market_snapshots 
        (ticker, timestamp, yes_ask, no_ask, volume, status, close_time)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (ticker, dt.now(timezone.utc).isoformat(), yes_ask, no_ask, volume, status, close_time))
    
    conn.commit()
    conn.close()

# ============================================================
# ORDER EXECUTION
# ============================================================

def place_order_direct(auth, ticker: str, side: str, count: int, price: int) -> dict:
    """Place order using direct API call with correct authentication."""
    try:
        timestamp = str(int(dt.now(timezone.utc).timestamp() * 1000))
        path = "/trade-api/v2/portfolio/orders"
        method = "POST"
        
        # Order payload (correct format)
        import uuid
        order_data = {
            "ticker": ticker,
            "side": side,
            "action": "buy",
            "count": count,
            "type": "limit",
            f"{side}_price": price,
            "client_order_id": str(uuid.uuid4()),
        }
        
        # Generate headers using correct method
        headers = get_headers(auth, method, path)
        
        url = "https://api.elections.kalshi.com" + path
        resp = requests.post(url, headers=headers, json=order_data, timeout=15)
        
        if resp.status_code == 201:
            data = resp.json()
            return {
                "success": True,
                "order": data.get("order", {}),
                "order_id": data.get("order", {}).get("order_id")
            }
        else:
            return {
                "error": resp.status_code,
                "detail": resp.text
            }
            
    except Exception as e:
        return {
            "error": "exception",
            "detail": str(e)
        }

def cancel_order_direct(auth, order_id):
    """Cancel a resting order on Kalshi via DELETE endpoint.
    Returns dict with 'success' key on success, or 'error'/'detail' on failure."""
    try:
        path = f"/trade-api/v2/portfolio/orders/{order_id}"
        method = "DELETE"
        headers = get_headers(auth, method, path)
        url = "https://api.elections.kalshi.com" + path
        resp = requests.delete(url, headers=headers, timeout=15)

        if resp.status_code == 200:
            return {"success": True, "response": resp.json()}
        else:
            return {"error": resp.status_code, "detail": resp.text}
    except Exception as e:
        return {"error": "exception", "detail": str(e)}

def check_order_fill_status(auth, order_id, max_polls=3, poll_interval=2):
    """Check an order's fill status on Kalshi. Polls briefly for fills.
    Returns dict with filled_count, remaining_count, order_status, or error."""
    for attempt in range(max_polls):
        try:
            path = f"/trade-api/v2/portfolio/orders/{order_id}"
            method = "GET"
            headers = get_headers(auth, method, path)
            url = "https://api.elections.kalshi.com" + path
            resp = requests.get(url, headers=headers, timeout=15)

            if resp.status_code == 200:
                data = resp.json()
                order = data.get("order", {})
                order_status = order.get("status", "unknown")
                filled_count = order.get("fill_count", 0)
                remaining_count = order.get("remaining_count", 0)
                initial_count = order.get("initial_count", 0)

                # If fully filled or cancelled, no need to poll further
                if order_status in ("executed", "cancelled") or remaining_count == 0:
                    return {
                        "filled_count": filled_count,
                        "remaining_count": remaining_count,
                        "initial_count": initial_count,
                        "order_status": order_status,
                    }

                # Still resting — wait and re-poll
                if attempt < max_polls - 1:
                    time.sleep(poll_interval)
                    continue

                # Final attempt: return current state
                return {
                    "filled_count": filled_count,
                    "remaining_count": remaining_count,
                    "initial_count": initial_count,
                    "order_status": order_status,
                }
            else:
                return {"error": f"HTTP {resp.status_code}", "detail": resp.text}

        except Exception as e:
            return {"error": "exception", "detail": str(e)}

    return {"error": "max_polls_exceeded"}

# ============================================================
# TRADE MANAGEMENT (FIXED DEDUPLICATION)
# ============================================================

def has_open_position(ticker):
    """Check if we already have an open position in this market."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute('''
        SELECT COUNT(*) FROM trades
        WHERE ticker = ? AND status = 'open'
    ''', (ticker,))

    count = cursor.fetchone()[0]
    conn.close()

    return count > 0

def get_resting_order_for_ticker(ticker):
    """Get details of a resting (unfilled) order for a ticker, if one exists.
    Returns dict with order details, or None if no resting unfilled order exists."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute('''
        SELECT id, order_id, direction, entry_price, estimated_win_prob,
               ev_per_contract, requested_contracts, expiry_time
        FROM trades
        WHERE ticker = ? AND status = 'open'
          AND COALESCE(filled_count, 0) = 0
          AND order_status = 'resting'
          AND order_id IS NOT NULL
          AND order_id != 'unknown'
          AND order_id != 'observation'
        ORDER BY created_at DESC
        LIMIT 1
    ''', (ticker,))

    row = cursor.fetchone()
    conn.close()

    if row is None:
        return None

    return {
        'trade_id': row[0],
        'order_id': row[1],
        'direction': row[2],
        'entry_price': row[3],
        'old_win_prob': row[4],
        'old_ev': row[5],
        'requested_contracts': row[6],
        'expiry_time': row[7],
    }

def mark_trade_cancelled_replaced(trade_id):
    """Mark a resting trade as cancelled/replaced in the DB."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE trades
        SET status = 'cancelled_replaced',
            realized_pnl = 0,
            order_status = 'cancelled_replaced'
        WHERE id = ?
    ''', (trade_id,))
    conn.commit()
    conn.close()

def count_open_positions():
    """Count total open positions across all markets."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute('''
        SELECT COUNT(*) FROM trades WHERE status = 'open'
    ''')

    count = cursor.fetchone()[0]
    conn.close()

    return count

def execute_trade_enhanced(auth, market, win_prob, ev_per_contract, kelly_frac, live_balance):
    """Execute a trade with proper position sizing and tracking."""
    ticker = market['ticker']
    yes_ask = market['yes_ask']
    no_ask = market['no_ask']
    volume = market['volume']
    
    # Check for existing open position — but allow replacing resting (unfilled) orders
    if has_open_position(ticker):
        resting = get_resting_order_for_ticker(ticker)

        if resting is None:
            # Position has fills or is not resting — cannot replace
            return False, "Already have open position (filled or non-resting)"

        # We have a resting unfilled order. Compare conviction.
        old_conviction = abs(resting['old_win_prob'] - 0.5)
        new_conviction = abs(win_prob - 0.5)

        if new_conviction <= old_conviction + MIN_CONVICTION_IMPROVEMENT:
            return False, (f"Resting order exists, new signal not better "
                           f"(old={old_conviction:.4f}, new={new_conviction:.4f})")

        # New signal IS better — attempt cancel-and-replace
        print(f"   🔄 REPLACING resting order on {ticker}")
        print(f"      Old conviction: {old_conviction:.4f}, New: {new_conviction:.4f} (+{new_conviction - old_conviction:.4f})")

        # Race condition check: verify order is still resting with 0 fills
        fill_info = check_order_fill_status(auth, resting['order_id'], max_polls=1, poll_interval=0)

        if 'error' in fill_info:
            print(f"      ⚠️ Fill check failed: {fill_info.get('error')} — keeping old order")
            return False, f"Fill check failed during replacement: {fill_info.get('error')}"

        if fill_info['filled_count'] > 0:
            # Order got fills since we last checked — do NOT cancel
            print(f"      ⚠️ Order now has {fill_info['filled_count']} fills — keeping it")
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            new_cost = resting['entry_price'] * fill_info['filled_count']
            cursor.execute('''
                UPDATE trades
                SET filled_count = ?, order_status = ?, contracts = ?, cost_basis = ?
                WHERE id = ?
            ''', (fill_info['filled_count'], fill_info['order_status'],
                  fill_info['filled_count'], new_cost, resting['trade_id']))
            conn.commit()
            conn.close()
            return False, f"Resting order got fills ({fill_info['filled_count']}), keeping it"

        if fill_info['order_status'] not in ('resting', 'pending'):
            print(f"      ⚠️ Order status is '{fill_info['order_status']}' — not cancellable")
            return False, f"Order status unexpected: {fill_info['order_status']}"

        # Cancel the resting order on Kalshi
        cancel_result = cancel_order_direct(auth, resting['order_id'])

        if 'error' in cancel_result:
            print(f"      ❌ Cancel failed: {cancel_result.get('detail', '')[:80]} — keeping old order")
            return False, f"Cancel failed: {cancel_result.get('detail', '')}"

        # Mark old trade as cancelled_replaced in DB
        mark_trade_cancelled_replaced(resting['trade_id'])
        print(f"      ✅ Old order {resting['order_id'][:8]}... cancelled, placing better order")

        # Fall through to place the new order below

    # Determine best direction based on EV
    yes_ev = calculate_ev(yes_ask, no_ask, win_prob, 'YES')
    no_ev = calculate_ev(yes_ask, no_ask, 1 - win_prob, 'NO')  # FIXED: Explicit NO probability
    
    if yes_ev > no_ev and yes_ev > MIN_EV_THRESHOLD:
        direction = 'YES'
        price = yes_ask
        ev = yes_ev
    elif no_ev > MIN_EV_THRESHOLD:
        direction = 'NO'
        price = no_ask
        ev = no_ev
    else:
        return False, "EV below threshold"
    
    # Position sizing with L1 guardrails
    effective_max = market.get('_effective_max', MAX_CONTRACTS_CEILING)
    min_contracts = market.get('_min_contracts', 1)

    if OBSERVATION_MODE:
        contracts = min(10, effective_max)  # Fixed size for paper tracking
    else:
        # Era 12: restored Era 2 sizing — min(kelly, budget)
        # Conviction-based Kelly now returns meaningful values for both directions
        max_contracts_by_kelly = int(kelly_frac * live_balance / price)
        contracts = min(max_contracts_by_kelly, effective_max)

        if contracts < min_contracts:
            return False, f"Below minimum contracts ({contracts} < {min_contracts})"
    
    expected_profit = ev * contracts
    
    print(f"\n🚨 EXECUTING TRADE: {ticker}")
    print(f"   📊 {market['title']}")
    print(f"   💰 {direction} at {price}c")
    print(f"   📈 Win prob: {win_prob:.1%}")
    print(f"   💸 EV per contract: {ev:.1f}c")
    print(f"   📊 Kelly fraction: {kelly_frac:.1%}")
    print(f"   📈 Contracts: {contracts}")
    print(f"   💸 Expected profit: ${expected_profit/100:.2f}")
    print(f"   💰 Live balance: ${live_balance/100:.2f}")
    
    # In observation mode, just log the trade without executing
    if OBSERVATION_MODE:
        print(f"   📊 OBSERVATION MODE: Trade logged but not executed")
        store_trade(
            ticker=ticker,
            order_id="observation",
            direction=direction,
            entry_price=price,
            contracts=contracts,
            cost_basis=price * contracts,
            estimated_win_prob=win_prob,
            ev_per_contract=ev,
            kelly_fraction=kelly_frac,
            expiry_time=market['close_time'],
            signal_source='observation'
        )
        return True, "Observation mode - logged only"
    
    # Place the order
    result = place_order_direct(auth, ticker, direction.lower(), contracts, price)

    if "success" in result:
        order_id = result.get('order_id', 'unknown')
        order_obj = result.get('order', {})

        # --- FILL CHECK (single quick poll, non-blocking) ---
        immediate_status = order_obj.get('status', 'unknown')
        immediate_fill = order_obj.get('fill_count', 0)

        # One quick poll to get initial fill status (not gatekeeping — just for logging)
        if immediate_status == 'resting' or immediate_fill < contracts:
            if order_id and order_id != 'unknown':
                print(f"   ⏳ Order resting, checking initial fill status...")
                fill_info = check_order_fill_status(auth, order_id, max_polls=1, poll_interval=2)
                if 'error' not in fill_info:
                    filled_count = fill_info['filled_count']
                    order_status = fill_info['order_status']
                else:
                    filled_count = immediate_fill
                    order_status = immediate_status
                    print(f"   ⚠️ Fill check failed ({fill_info.get('error')}), using placement data")
            else:
                filled_count = immediate_fill
                order_status = immediate_status
        else:
            filled_count = immediate_fill
            order_status = immediate_status

        # ALWAYS store the trade — even if filled_count is 0 (order is resting, will check on reconciliation)
        effective_filled = filled_count  # could be 0
        cost_basis = price * effective_filled

        store_trade(
            ticker=ticker,
            order_id=order_id,
            direction=direction,
            entry_price=price,
            contracts=effective_filled,
            cost_basis=cost_basis,
            estimated_win_prob=win_prob,
            ev_per_contract=ev,
            kelly_fraction=kelly_frac,
            expiry_time=market['close_time'],
            signal_source='external',
            filled_count=effective_filled,
            order_status=order_status,
            requested_contracts=contracts,
        )

        # Log messages based on fill status
        if order_status == 'resting' and filled_count == 0:
            print(f"   ⏳ Order resting, 0/{contracts} filled — will check on reconciliation")
            print(f"      Order ID: {order_id}")
        elif order_status == 'resting' and filled_count > 0:
            print(f"   ⏳ PARTIAL FILL: {filled_count}/{contracts} filled, order still resting")
            print(f"      Order ID: {order_id}")
            print(f"      Expected profit (filled so far): ${(ev * filled_count)/100:.2f}")
        else:
            print(f"   ✅ SUCCESS: Order filled!")
            if filled_count < contracts:
                print(f"      ⚠️ PARTIAL FILL: {filled_count}/{contracts} contracts filled")
            else:
                print(f"      FULL FILL: {filled_count} contracts")
            print(f"      Order ID: {order_id}")
            print(f"      Expected profit: ${(ev * filled_count)/100:.2f}")

        return True, order_id
    else:
        print(f"   ❌ Trade failed: {result.get('error', 'unknown')}")
        print(f"   📊 Details: {result.get('detail', '')[:100]}")

        return False, result.get('detail', '')

def store_trade(ticker, order_id, direction, entry_price, contracts, cost_basis,
                estimated_win_prob, ev_per_contract, kelly_fraction, expiry_time, signal_source,
                filled_count=None, order_status=None, requested_contracts=None):
    """Store trade details in database."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Default fill tracking for backward compat (observation mode)
    if filled_count is None:
        filled_count = contracts
    if order_status is None:
        order_status = 'executed'
    if requested_contracts is None:
        requested_contracts = contracts

    cursor.execute('''
        INSERT INTO trades
        (ticker, order_id, direction, entry_price, contracts, cost_basis,
         estimated_win_prob, ev_per_contract, kelly_fraction, entry_time,
         expiry_time, signal_source, filled_count, order_status, requested_contracts)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (ticker, order_id, direction, entry_price, contracts, cost_basis,
          estimated_win_prob, ev_per_contract, kelly_fraction, dt.now(timezone.utc).isoformat(),
          expiry_time, signal_source, filled_count, order_status, requested_contracts))

    conn.commit()
    conn.close()

def store_signal_log(ticker, series_ticker, scan_time, close_time,
                     yes_ask, no_ask, spot_price, floor_strike,
                     signal_a, signal_b, signal_c,
                     win_prob, yes_ev, no_ev,
                     best_direction, best_ev, kelly_frac,
                     action_taken, decline_reason=None,
                     agreement_strength=None, volatility=None, hour_utc=None,
                     gate_declined=None, signal_d=None, perp_price=None,
                     weight_a=None, weight_b=None, weight_c=None, weight_d=None,
                     signal_e=None, weight_e=None, perf_adjustment=None,
                     adaptive_penalty=None, trend_20m=None, macro_trend=None, trend_regime=None,
                     payoff_multiple=None, adjusted_ev=None, entry_band=None, entry_band_sizing=None):
    """Store a signal evaluation in signal_log (placed or declined). Includes L1+L2+Era7+Era8+Era10 fields."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO signal_log
            (ticker, series_ticker, scan_time, close_time,
             yes_ask, no_ask, spot_price, floor_strike,
             signal_a, signal_b, signal_c,
             win_prob, yes_ev, no_ev,
             best_direction, best_ev, kelly_frac,
             action_taken, decline_reason,
             agreement_strength, volatility, hour_utc, gate_declined,
             signal_d, perp_price, weight_a, weight_b, weight_c, weight_d,
             signal_e, weight_e, perf_adjustment,
             adaptive_penalty, trend_20m, macro_trend, trend_regime,
             payoff_multiple, adjusted_ev, entry_band, entry_band_sizing)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?)
        ''', (ticker, series_ticker, scan_time, close_time,
              yes_ask, no_ask, spot_price, floor_strike,
              signal_a, signal_b, signal_c,
              win_prob, yes_ev, no_ev,
              best_direction, best_ev, kelly_frac,
              action_taken, decline_reason,
              agreement_strength, volatility, hour_utc, gate_declined,
              signal_d, perp_price, weight_a, weight_b, weight_c, weight_d,
              signal_e, weight_e, perf_adjustment,
              adaptive_penalty, trend_20m, macro_trend, trend_regime,
              payoff_multiple, adjusted_ev, entry_band, entry_band_sizing))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"    ⚠️ Failed to store signal_log: {e}")

def store_feature_log(ticker, series_ticker, scan_time, close_time,
                      time_remaining_sec, spot_price, floor_strike,
                      perp_price, signal_detail, weights):
    """Store feature vector for ML training (Layer 3 prep)."""
    try:
        multi_prices = get_multi_exchange_prices(series_ticker)
        momentum = calculate_price_momentum(series_ticker)
        cross_spread, _ = calculate_cross_exchange_spread(series_ticker)

        # Compute raw features
        spot_vs_strike_dist = None
        if spot_price and floor_strike and floor_strike > 0:
            spot_vs_strike_dist = (spot_price - floor_strike) / floor_strike

        convergence_spread = None
        if perp_price and spot_price and spot_price > 0:
            convergence_spread = (perp_price - spot_price) / spot_price

        w_a, w_b, w_d, w_c = weights[:4]  # Ignore w_e for legacy feature_log

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO feature_log
            (ticker, series_ticker, scan_time, close_time, time_remaining_sec,
             spot_price_coinbase, spot_price_kraken, spot_price_binance_spot,
             binance_perp_price, floor_strike,
             spot_vs_strike_distance, momentum_5min, convergence_spread,
             realized_vol_30min, cross_exchange_spread,
             signal_a, signal_b, signal_c, signal_d, win_prob,
             weight_a, weight_b, weight_c, weight_d)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (ticker, series_ticker, scan_time, close_time, time_remaining_sec,
              multi_prices.get('coinbase'), multi_prices.get('kraken'),
              multi_prices.get('binance'), perp_price, floor_strike,
              spot_vs_strike_dist, momentum.get('pct_change', 0),
              convergence_spread, signal_detail.get('volatility', 0),
              cross_spread,
              signal_detail.get('signal_a'), signal_detail.get('signal_b'),
              signal_detail.get('signal_c'), signal_detail.get('signal_d'),
              signal_detail.get('win_prob'),
              w_a, w_b, w_d, w_c))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"    ⚠️ Failed to store feature_log: {e}")

def reconcile_feature_log(auth):
    """Batch-reconcile unresolved feature_log entries with market outcomes."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        now = dt.now(timezone.utc)
        cursor.execute('''
            SELECT DISTINCT ticker, close_time FROM feature_log
            WHERE actual_result IS NULL AND close_time IS NOT NULL
            AND close_time < ?
        ''', (now.isoformat(),))
        unresolved = cursor.fetchall()

        resolved_count = 0
        for ticker, close_time in unresolved:
            try:
                path = f'/trade-api/v2/markets/{ticker}'
                headers = get_headers(auth, 'GET', path)
                url = f"https://api.elections.kalshi.com{path}"
                resp = requests.get(url, headers=headers, timeout=10)
                if resp.status_code == 200:
                    market = resp.json().get('market', {})
                    result = market.get('result', '')
                    if result in ('yes', 'no'):
                        cursor.execute('''
                            UPDATE feature_log SET actual_result = ?
                            WHERE ticker = ? AND actual_result IS NULL
                        ''', (result, ticker))
                        resolved_count += 1
            except Exception:
                pass

        conn.commit()
        conn.close()
        if resolved_count > 0:
            print(f"📋 Feature log: reconciled {resolved_count} entries")
    except Exception as e:
        print(f"    ⚠️ feature_log reconciliation failed: {e}")

# ============================================================
# P&L RECONCILIATION
# ============================================================

def reconcile_trades(auth):
    """Reconcile settled trades and update P&L. Re-checks fill status for resting orders."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # === PHASE 1: Update fill status for non-terminal orders ===
    cursor.execute('''
        SELECT id, order_id, order_status, filled_count, contracts, entry_price
        FROM trades
        WHERE status = 'open'
          AND order_status NOT IN ('executed', 'cancelled')
          AND order_id IS NOT NULL
          AND order_id != 'unknown'
          AND order_id != 'observation'
    ''')
    resting_orders = cursor.fetchall()

    for trade_id, order_id, current_status, current_filled, current_contracts, entry_price in resting_orders:
        try:
            fill_info = check_order_fill_status(auth, order_id, max_polls=1, poll_interval=0)
            if 'error' not in fill_info:
                new_filled = fill_info['filled_count']
                new_status = fill_info['order_status']

                if new_filled != current_filled or new_status != current_status:
                    new_cost_basis = entry_price * new_filled
                    cursor.execute('''
                        UPDATE trades
                        SET filled_count = ?,
                            order_status = ?,
                            contracts = ?,
                            cost_basis = ?
                        WHERE id = ?
                    ''', (new_filled, new_status, new_filled, new_cost_basis, trade_id))
                    if new_filled > (current_filled or 0):
                        print(f"   📦 [FILL UPDATE] {order_id[:8]}...: {current_filled or 0} → {new_filled} contracts (status: {new_status})")
        except Exception:
            pass  # Don't block reconciliation for fill-check errors

    conn.commit()  # Save fill updates before P&L phase

    # === PHASE 2: Check market resolution and compute P&L ===
    cursor.execute('''
        SELECT id, ticker, direction, entry_price, contracts, expiry_time,
               COALESCE(filled_count, contracts) as effective_contracts,
               order_status
        FROM trades WHERE status = 'open'
    ''')

    open_trades = cursor.fetchall()

    if not open_trades:
        conn.close()
        return

    now_utc = dt.now(timezone.utc)

    for trade_id, ticker, direction, entry_price, contracts, expiry_time, effective_contracts, order_status in open_trades:
        # First check: if expiry_time has long passed (>30 min), mark as expired
        # This prevents stale trades from blocking the position limit
        if expiry_time:
            try:
                expiry_dt = dt.fromisoformat(expiry_time.replace('Z', '+00:00'))
                if (now_utc - expiry_dt).total_seconds() > 1800:  # 30 min past expiry
                    # Market is definitely over, try to get resolution from API
                    pass  # Fall through to API check below
            except Exception:
                pass

        # Check if market has resolved via API
        try:
            path = f'/trade-api/v2/markets/{ticker}'
            method = 'GET'

            headers = get_headers(auth, method, path)
            url = 'https://api.elections.kalshi.com' + path
            resp = requests.get(url, headers=headers, timeout=15)

            if resp.status_code == 200:
                market_data = resp.json()
                market_obj = market_data.get('market', market_data)
                status = market_obj.get('status', '')
                resolution = market_obj.get('result', '') or market_obj.get('resolution', '')

                # Terminal states: closed, determined, finalized, settled
                terminal_states = {'closed', 'determined', 'finalized', 'settled'}

                if status in terminal_states and resolution:
                    # Handle unfilled orders that expired with the market
                    if effective_contracts == 0:
                        cursor.execute('''
                            UPDATE trades
                            SET status = 'unfilled_expired',
                                market_resolution = ?,
                                realized_pnl = 0,
                                order_status = CASE
                                    WHEN order_status = 'resting' THEN 'unfilled_expired'
                                    ELSE order_status
                                END
                            WHERE id = ?
                        ''', (resolution, trade_id))
                        print(f"   ⏭️ Trade {ticker} expired with 0 fills, P&L = $0.00")
                        continue

                    # Calculate realized P&L (use effective_contracts which respects actual fills)
                    if (direction == 'YES' and resolution == 'yes') or \
                       (direction == 'NO' and resolution == 'no'):
                        realized_pnl = (100 - entry_price) * effective_contracts
                        trade_status = 'won'
                    else:
                        realized_pnl = -(entry_price * effective_contracts)
                        trade_status = 'lost'

                    cursor.execute('''
                        UPDATE trades
                        SET status = ?, market_resolution = ?, realized_pnl = ?
                        WHERE id = ?
                    ''', (trade_status, resolution, realized_pnl, trade_id))

                    print(f"💰 Trade {ticker} resolved: {trade_status}, P&L: ${realized_pnl/100:.2f}")

                elif status in terminal_states and not resolution:
                    # Market closed but no resolution yet (rare edge case)
                    # If it's been > 30 min past expiry, just expire it
                    if expiry_time:
                        try:
                            expiry_dt = dt.fromisoformat(expiry_time.replace('Z', '+00:00'))
                            if (now_utc - expiry_dt).total_seconds() > 1800:
                                cursor.execute('''
                                    UPDATE trades SET status = 'expired_no_result' WHERE id = ?
                                ''', (trade_id,))
                                print(f"⚠️ Trade {ticker} expired (no resolution after 30min)")
                        except Exception:
                            pass

            elif resp.status_code == 404:
                # Market doesn't exist anymore
                cursor.execute('''
                    UPDATE trades SET status = 'expired_not_found' WHERE id = ?
                ''', (trade_id,))
                print(f"⚠️ Trade {ticker} market not found, marking expired")

        except Exception as e:
            print(f"❌ Error reconciling trade {ticker}: {e}")

    conn.commit()
    conn.close()

def reconcile_signal_log(auth):
    """Batch-reconcile unresolved signal_log entries with market results."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    now_iso = dt.now(timezone.utc).isoformat()
    cursor.execute('''
        SELECT DISTINCT ticker, close_time
        FROM signal_log
        WHERE actual_result IS NULL
          AND close_time IS NOT NULL
          AND close_time < ?
    ''', (now_iso,))

    unresolved_tickers = cursor.fetchall()

    if not unresolved_tickers:
        conn.close()
        return

    resolved_count = 0

    for ticker, close_time in unresolved_tickers:
        try:
            path = f'/trade-api/v2/markets/{ticker}'
            method = 'GET'
            headers = get_headers(auth, method, path)
            url = 'https://api.elections.kalshi.com' + path
            resp = requests.get(url, headers=headers, timeout=15)

            if resp.status_code == 200:
                market_data = resp.json()
                market_obj = market_data.get('market', market_data)
                status = market_obj.get('status', '')
                resolution = market_obj.get('result', '') or market_obj.get('resolution', '')

                terminal_states = {'closed', 'determined', 'finalized', 'settled'}

                if status in terminal_states and resolution:
                    cursor.execute('''
                        UPDATE signal_log
                        SET actual_result = ?,
                            signal_correct = CASE
                                WHEN (win_prob > 0.5 AND ? = 'yes') THEN 1
                                WHEN (win_prob < 0.5 AND ? = 'no') THEN 1
                                WHEN win_prob = 0.5 THEN NULL
                                ELSE 0
                            END,
                            would_have_won = CASE
                                WHEN (best_direction = 'YES' AND ? = 'yes') THEN 1
                                WHEN (best_direction = 'NO' AND ? = 'no') THEN 1
                                ELSE 0
                            END
                        WHERE ticker = ? AND actual_result IS NULL
                    ''', (resolution, resolution, resolution, resolution, resolution, ticker))
                    resolved_count += cursor.rowcount

            elif resp.status_code == 404:
                cursor.execute('''
                    UPDATE signal_log SET actual_result = 'unknown'
                    WHERE ticker = ? AND actual_result IS NULL
                ''', (ticker,))

        except Exception as e:
            print(f"    ⚠️ signal_log reconciliation error for {ticker}: {e}")
            continue

    conn.commit()
    conn.close()

    if resolved_count > 0:
        print(f"📋 Signal log: reconciled {resolved_count} entries")

def get_performance_stats():
    """Get comprehensive performance statistics."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Trade statistics
    cursor.execute('''
        SELECT 
            COUNT(*) as total_trades,
            COUNT(CASE WHEN status = 'won' THEN 1 END) as winning_trades,
            COUNT(CASE WHEN status = 'lost' THEN 1 END) as losing_trades,
            SUM(CASE WHEN status = 'won' THEN realized_pnl ELSE 0 END) as total_profit,
            SUM(CASE WHEN status = 'lost' THEN realized_pnl ELSE 0 END) as total_loss,
            AVG(estimated_win_prob) as avg_win_prob,
            AVG(ev_per_contract) as avg_ev,
            AVG(kelly_fraction) as avg_kelly
        FROM trades
    ''')
    
    trade_stats = cursor.fetchone()
    
    # Recent performance
    cursor.execute('''
        SELECT direction, entry_price, contracts, status, realized_pnl, entry_time
        FROM trades 
        ORDER BY entry_time DESC 
        LIMIT 10
    ''')
    
    recent_trades = cursor.fetchall()
    
    conn.close()
    
    return trade_stats, recent_trades

# ============================================================
# SIGNAL LOG REPORTING
# ============================================================

def print_signal_log_report():
    """Print signal accuracy and filter effectiveness report."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    print(f"\n{'='*60}")
    print(f"📋 SIGNAL LOG REPORT")
    print(f"{'='*60}")

    # --- Overview ---
    cursor.execute('''
        SELECT
            COUNT(*) as total,
            COUNT(CASE WHEN action_taken = 'placed' THEN 1 END) as placed,
            COUNT(CASE WHEN action_taken = 'declined' THEN 1 END) as declined,
            COUNT(CASE WHEN actual_result IS NOT NULL AND actual_result != 'unknown' THEN 1 END) as resolved,
            COUNT(CASE WHEN actual_result IS NULL THEN 1 END) as unresolved
        FROM signal_log
    ''')
    total, placed, declined, resolved, unresolved = cursor.fetchone()

    print(f"\n  Total evaluations: {total}  |  Placed: {placed}  |  Declined: {declined}")
    print(f"  Resolved: {resolved}  |  Awaiting: {unresolved}")

    if resolved == 0:
        print(f"\n  No resolved markets yet — report will populate after markets expire.")
        conn.close()
        print(f"{'='*60}")
        return

    # --- Signal Accuracy ---
    cursor.execute('''
        SELECT
            COUNT(*) as total_resolved,
            COALESCE(SUM(signal_correct), 0) as correct,
            AVG(win_prob) as avg_wp,
            AVG(CASE WHEN actual_result = 'yes' THEN 1.0 ELSE 0.0 END) as actual_yes_rate
        FROM signal_log
        WHERE actual_result IS NOT NULL AND actual_result != 'unknown'
          AND signal_correct IS NOT NULL
    ''')
    total_resolved, correct, avg_wp, actual_yes_rate = cursor.fetchone()
    accuracy = (correct / total_resolved * 100) if total_resolved > 0 else 0

    print(f"\n  Signal Accuracy (directional):")
    print(f"    Correct: {accuracy:.1f}% ({correct}/{total_resolved})")
    print(f"    Avg predicted win_prob: {avg_wp:.3f}")
    print(f"    Actual YES rate: {actual_yes_rate:.3f}")
    print(f"    Calibration gap: {(avg_wp - actual_yes_rate):+.3f}")

    # --- Filter Accuracy: placed vs declined ---
    cursor.execute('''
        SELECT
            action_taken,
            COUNT(*) as cnt,
            COALESCE(SUM(would_have_won), 0) as wins,
            AVG(best_ev) as avg_ev,
            AVG(win_prob) as avg_wp
        FROM signal_log
        WHERE actual_result IS NOT NULL AND actual_result != 'unknown'
        GROUP BY action_taken
    ''')
    selection = cursor.fetchall()

    print(f"\n  Filter Accuracy (placed vs declined):")
    for action, cnt, wins, avg_ev, avg_wp in selection:
        win_rate = (wins / cnt * 100) if cnt > 0 else 0
        print(f"    {action:>10}: {cnt} evals, {win_rate:.1f}% would-have-won, "
              f"avg EV={avg_ev:.1f}c, avg wp={avg_wp:.3f}")

    # --- Decline Reasons ---
    cursor.execute('''
        SELECT
            CASE
                WHEN decline_reason LIKE 'EV below%' THEN 'EV below threshold'
                ELSE decline_reason
            END as reason,
            COUNT(*) as cnt,
            COALESCE(SUM(would_have_won), 0) as wins
        FROM signal_log
        WHERE action_taken = 'declined'
          AND actual_result IS NOT NULL AND actual_result != 'unknown'
        GROUP BY reason
        ORDER BY cnt DESC
    ''')
    declines = cursor.fetchall()

    if declines:
        print(f"\n  Decline Reason Breakdown:")
        for reason, cnt, wins in declines:
            win_rate = (wins / cnt * 100) if cnt > 0 else 0
            print(f"    {reason}: {cnt}x, {win_rate:.1f}% would have won")

    # --- Hypothetical P&L ---
    cursor.execute('''
        SELECT
            action_taken,
            SUM(CASE WHEN would_have_won = 1 THEN (100 -
                CASE WHEN best_direction = 'YES' THEN yes_ask ELSE no_ask END)
                ELSE -(CASE WHEN best_direction = 'YES' THEN yes_ask ELSE no_ask END)
            END) as hyp_pnl,
            COUNT(*) as cnt
        FROM signal_log
        WHERE actual_result IS NOT NULL AND actual_result != 'unknown'
        GROUP BY action_taken
    ''')
    pnl = cursor.fetchall()

    print(f"\n  Hypothetical P&L (1 contract per signal):")
    for action, h_pnl, cnt in pnl:
        h_pnl = h_pnl or 0
        print(f"    {action:>10}: ${h_pnl/100:.2f} across {cnt} evals")

    # --- Per-Series ---
    cursor.execute('''
        SELECT
            series_ticker,
            COUNT(*) as cnt,
            COALESCE(SUM(signal_correct), 0) as correct,
            AVG(win_prob) as avg_wp,
            SUM(CASE WHEN action_taken = 'placed' THEN 1 ELSE 0 END) as placed
        FROM signal_log
        WHERE actual_result IS NOT NULL AND actual_result != 'unknown'
          AND signal_correct IS NOT NULL
        GROUP BY series_ticker
    ''')
    per_series = cursor.fetchall()

    if per_series:
        print(f"\n  Per-Series:")
        for series, cnt, correct, avg_wp, placed_count in per_series:
            acc = (correct / cnt * 100) if cnt > 0 else 0
            print(f"    {series}: {acc:.1f}% accurate ({correct}/{cnt}), "
                  f"avg wp={avg_wp:.3f}, {placed_count} placed")

    conn.close()
    print(f"{'='*60}")

def print_gate_effectiveness_report():
    """Print gate-by-gate opportunity cost analysis.
    Shows which gates are blocking trades, how many would have won,
    and the dollar impact of each gate's filtering."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Check if gate_declined column exists
    cursor.execute("PRAGMA table_info(signal_log)")
    cols = [row[1] for row in cursor.fetchall()]
    if 'gate_declined' not in cols:
        conn.close()
        return  # L1 columns not yet migrated

    print(f"\n{'='*60}")
    print(f"🚧 GATE EFFECTIVENESS REPORT")
    print(f"{'='*60}")

    # Count resolved declined entries with gate data
    cursor.execute('''
        SELECT COUNT(*) FROM signal_log
        WHERE action_taken = 'declined'
          AND gate_declined IS NOT NULL
          AND actual_result IN ('yes', 'no')
    ''')
    total_gated = cursor.fetchone()[0]

    if total_gated == 0:
        print(f"\n  No resolved gate-declined signals yet — report will populate after markets expire.")
        conn.close()
        print(f"{'='*60}")
        return

    # === SECTION A: Gate-by-Gate Breakdown ===
    cursor.execute('''
        SELECT
            gate_declined,
            COUNT(*) as blocked,
            SUM(CASE WHEN would_have_won = 1 THEN 1 ELSE 0 END) as missed_wins,
            SUM(CASE WHEN would_have_won = 0 OR would_have_won IS NULL THEN 1 ELSE 0 END) as correct_blocks,
            SUM(CASE WHEN would_have_won = 1 THEN
                (100 - (CASE WHEN best_direction='YES' THEN yes_ask ELSE no_ask END))
                ELSE 0 END) as missed_profit_cents,
            SUM(CASE WHEN would_have_won = 0 OR would_have_won IS NULL THEN
                (CASE WHEN best_direction='YES' THEN yes_ask ELSE no_ask END)
                ELSE 0 END) as saved_loss_cents
        FROM signal_log
        WHERE action_taken = 'declined'
          AND gate_declined IS NOT NULL
          AND actual_result IN ('yes', 'no')
        GROUP BY gate_declined
        ORDER BY blocked DESC
    ''')
    gates = cursor.fetchall()

    gate_names = {
        'signal_disagreement': 'Gate 1: Signal Disagreement',
        'low_conviction': 'Gate 1: Low Conviction',
        'cheap_contract': 'Gate 2: Cheap Contract',
        'low_volatility': 'Gate 3: Low Volatility',
        'ev_below_threshold': 'Gate 4: Low EV',
        'min_contracts': 'Gate 5: Min Contracts',
        'execution_failed': 'Execution Failed',
    }

    print(f"\n  Section A — Gate-by-Gate Breakdown ({total_gated} resolved declines):")
    print(f"  {'Gate':<30} {'Blocked':>7} {'Missed':>7} {'Saved':>7} {'MissWR':>7} {'Missed$':>8} {'Saved$':>8} {'Net$':>8}")
    print(f"  {'-'*88}")

    total_missed_profit = 0
    total_saved_loss = 0
    for gate, blocked, missed, correct, missed_profit, saved_loss in gates:
        missed = missed or 0
        correct = correct or 0
        missed_profit = missed_profit or 0
        saved_loss = saved_loss or 0
        miss_wr = (missed / blocked * 100) if blocked > 0 else 0
        net = missed_profit - saved_loss  # positive = gate cost us money, negative = gate saved us money
        total_missed_profit += missed_profit
        total_saved_loss += saved_loss
        label = gate_names.get(gate, gate)
        print(f"  {label:<30} {blocked:>7} {missed:>7} {correct:>7} {miss_wr:>6.1f}% ${missed_profit/100:>7.2f} ${saved_loss/100:>7.2f} ${net/100:>+7.2f}")

    total_net = total_missed_profit - total_saved_loss
    print(f"  {'-'*88}")
    print(f"  {'TOTAL':<30} {total_gated:>7} {'':>7} {'':>7} {'':>7} ${total_missed_profit/100:>7.2f} ${total_saved_loss/100:>7.2f} ${total_net/100:>+7.2f}")

    if total_net < 0:
        print(f"\n  ✅ Gates are net positive: saving ${abs(total_net)/100:.2f} more than they cost")
    else:
        print(f"\n  ⚠️  Gates are net negative: costing ${total_net/100:.2f} more than they save")

    # === SECTION B: Placed vs Declined vs No-Gates ===
    print(f"\n  Section B — Gate Value Comparison:")

    cursor.execute('''
        SELECT
            action_taken,
            COUNT(*) as cnt,
            SUM(CASE WHEN would_have_won = 1 THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN would_have_won = 1 THEN
                (100 - (CASE WHEN best_direction='YES' THEN yes_ask ELSE no_ask END))
                ELSE
                -(CASE WHEN best_direction='YES' THEN yes_ask ELSE no_ask END)
            END) as hyp_pnl
        FROM signal_log
        WHERE actual_result IN ('yes', 'no')
        GROUP BY action_taken
    ''')
    scenarios = cursor.fetchall()

    placed_cnt, placed_wins, placed_pnl = 0, 0, 0
    declined_cnt, declined_wins, declined_pnl = 0, 0, 0
    for action, cnt, wins, pnl in scenarios:
        wins = wins or 0
        pnl = pnl or 0
        if action == 'placed':
            placed_cnt, placed_wins, placed_pnl = cnt, wins, pnl
        else:
            declined_cnt, declined_wins, declined_pnl = cnt, wins, pnl

    total_cnt = placed_cnt + declined_cnt
    total_wins = placed_wins + declined_wins
    total_pnl = placed_pnl + declined_pnl

    print(f"  {'Scenario':<22} {'Trades':>7} {'WinRate':>8} {'Hyp P&L':>9} {'$/trade':>8}")
    print(f"  {'-'*56}")
    if placed_cnt > 0:
        print(f"  {'Actual (placed)':<22} {placed_cnt:>7} {placed_wins/placed_cnt*100:>7.1f}% ${placed_pnl/100:>8.2f} ${placed_pnl/placed_cnt/100:>7.2f}")
    if declined_cnt > 0:
        print(f"  {'All declined':<22} {declined_cnt:>7} {declined_wins/declined_cnt*100:>7.1f}% ${declined_pnl/100:>8.2f} ${declined_pnl/declined_cnt/100:>7.2f}")
    if total_cnt > 0:
        print(f"  {'No gates (all)':<22} {total_cnt:>7} {total_wins/total_cnt*100:>7.1f}% ${total_pnl/100:>8.2f} ${total_pnl/total_cnt/100:>7.2f}")

    # === SECTION C: Per-Gate "What If" ===
    if gates:
        print(f"\n  Section C — What If We Removed Each Gate?")
        print(f"  {'Remove gate...':<30} {'Extra':>6} {'ExtraWR':>8} {'Extra P&L':>10} {'Verdict':>10}")
        print(f"  {'-'*66}")

        for gate, blocked, missed, correct, missed_profit, saved_loss in gates:
            missed = missed or 0
            correct = correct or 0
            missed_profit = missed_profit or 0
            saved_loss = saved_loss or 0
            miss_wr = (missed / blocked * 100) if blocked > 0 else 0
            extra_pnl = missed_profit - saved_loss  # if we let these through
            verdict = "LOOSEN" if extra_pnl > 0 else "KEEP"
            label = gate_names.get(gate, gate)
            print(f"  {label:<30} {blocked:>+5} {miss_wr:>7.1f}% ${extra_pnl/100:>+9.2f} {verdict:>10}")

    conn.close()
    print(f"{'='*60}")

def print_era7_feature_report():
    """Print Era 7 feature effectiveness: Signal E, Performance Feedback, Hour Sizing."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # Check if Era 7 columns exist
        cursor.execute("PRAGMA table_info(signal_log)")
        cols = [row[1] for row in cursor.fetchall()]
        if 'signal_e' not in cols or 'perf_adjustment' not in cols:
            conn.close()
            return  # Era 7 columns not yet migrated

        # Check minimum data — need at least 5 resolved placed signals with signal_e
        cursor.execute('''
            SELECT COUNT(*) FROM signal_log
            WHERE actual_result IN ('yes', 'no')
              AND signal_e IS NOT NULL
              AND action_taken = 'placed'
        ''')
        count = cursor.fetchone()[0]
        if count < 5:
            conn.close()
            print(f"\n{'='*60}")
            print(f"📊 ERA 7 FEATURE REPORT — No resolved Era 7 signals yet ({count}/5 minimum)")
            print(f"{'='*60}")
            return

        print(f"\n{'='*60}")
        print(f"📊 ERA 7 FEATURE REPORT")
        print(f"{'='*60}")

        # ---- Section A: Signal E Contribution ----
        cursor.execute('''
            SELECT
                CASE
                    WHEN (best_direction = 'YES' AND signal_e > 0.52) OR
                         (best_direction = 'NO' AND signal_e < 0.48) THEN 'agrees'
                    WHEN (best_direction = 'YES' AND signal_e < 0.48) OR
                         (best_direction = 'NO' AND signal_e > 0.52) THEN 'disagrees'
                    ELSE 'neutral'
                END as trend_alignment,
                COUNT(*) as cnt,
                SUM(CASE WHEN would_have_won = 1 THEN 1 ELSE 0 END) as wins,
                AVG(signal_e) as avg_signal_e
            FROM signal_log
            WHERE actual_result IN ('yes', 'no')
              AND signal_e IS NOT NULL
              AND action_taken = 'placed'
            GROUP BY trend_alignment
        ''')
        trend_rows = cursor.fetchall()

        print(f"\n  Section A — Signal E (Multi-Timeframe Trend):")
        print(f"    {'Trend Alignment':<20} {'Trades':>7} {'WinRate':>8} {'Avg Sig E':>10}")
        print(f"    {'-'*48}")

        trend_data = {}
        for alignment, cnt, wins, avg_e in trend_rows:
            wr = (wins / cnt * 100) if cnt > 0 else 0
            trend_data[alignment] = {'cnt': cnt, 'wr': wr}
            print(f"    {alignment:<20} {cnt:>7} {wr:>7.1f}% {avg_e:>10.3f}")

        # Avg signal_e by outcome
        cursor.execute('''
            SELECT
                CASE WHEN would_have_won = 1 THEN 'win' ELSE 'loss' END as outcome,
                AVG(signal_e) as avg_signal_e,
                COUNT(*) as cnt
            FROM signal_log
            WHERE actual_result IN ('yes', 'no')
              AND signal_e IS NOT NULL
              AND action_taken = 'placed'
            GROUP BY outcome
        ''')
        outcome_rows = cursor.fetchall()
        print()
        for outcome, avg_e, cnt in outcome_rows:
            print(f"    Avg Signal E for {outcome}s:  {avg_e:.3f} (n={cnt})")

        agrees_wr = trend_data.get('agrees', {}).get('wr', 0)
        disagrees_wr = trend_data.get('disagrees', {}).get('wr', 0)
        agrees_n = trend_data.get('agrees', {}).get('cnt', 0)
        disagrees_n = trend_data.get('disagrees', {}).get('cnt', 0)
        if agrees_n >= 3 and disagrees_n >= 3:
            diff = agrees_wr - disagrees_wr
            if diff > 5:
                print(f"    Signal E is PREDICTIVE ✅  (agrees WR > disagrees WR by {diff:.1f}pp)")
            elif diff < -5:
                print(f"    Signal E is COUNTER-PREDICTIVE ❌  (agrees WR < disagrees WR by {-diff:.1f}pp)")
            else:
                print(f"    Signal E is NEUTRAL ➖  (agrees vs disagrees diff: {diff:+.1f}pp)")
        else:
            print(f"    ⏳ Need more data (agrees: {agrees_n}, disagrees: {disagrees_n})")

        # ---- Section B: Performance Feedback Impact ----
        cursor.execute('''
            SELECT
                CASE
                    WHEN perf_adjustment > 0.001 THEN 'boosted'
                    WHEN perf_adjustment < -0.001 THEN 'penalized'
                    ELSE 'no_adjustment'
                END as adj_type,
                COUNT(*) as cnt,
                SUM(CASE WHEN would_have_won = 1 THEN 1 ELSE 0 END) as wins,
                AVG(perf_adjustment) as avg_adj
            FROM signal_log
            WHERE actual_result IN ('yes', 'no')
              AND perf_adjustment IS NOT NULL
              AND action_taken = 'placed'
            GROUP BY adj_type
        ''')
        adj_rows = cursor.fetchall()

        print(f"\n  Section B — Performance Feedback:")
        print(f"    {'Adjustment Type':<20} {'Trades':>7} {'WinRate':>8} {'Avg Adj':>10}")
        print(f"    {'-'*48}")

        adj_data = {}
        for adj_type, cnt, wins, avg_adj in adj_rows:
            wr = (wins / cnt * 100) if cnt > 0 else 0
            adj_data[adj_type] = {'cnt': cnt, 'wr': wr}
            print(f"    {adj_type:<20} {cnt:>7} {wr:>7.1f}% {avg_adj:>+10.3f}")

        # Avg adjustment by outcome
        cursor.execute('''
            SELECT
                CASE WHEN would_have_won = 1 THEN 'win' ELSE 'loss' END as outcome,
                AVG(perf_adjustment) as avg_adj,
                COUNT(*) as cnt
            FROM signal_log
            WHERE actual_result IN ('yes', 'no')
              AND perf_adjustment IS NOT NULL
              AND action_taken = 'placed'
            GROUP BY outcome
        ''')
        adj_outcome_rows = cursor.fetchall()
        print()
        for outcome, avg_adj, cnt in adj_outcome_rows:
            print(f"    Avg perf_adjustment for {outcome}s:  {avg_adj:+.4f} (n={cnt})")

        boosted_wr = adj_data.get('boosted', {}).get('wr', 0)
        penalized_wr = adj_data.get('penalized', {}).get('wr', 0)
        boosted_n = adj_data.get('boosted', {}).get('cnt', 0)
        penalized_n = adj_data.get('penalized', {}).get('cnt', 0)
        if boosted_n >= 3 and penalized_n >= 3:
            diff = boosted_wr - penalized_wr
            if diff > 5:
                print(f"    Feedback is HELPFUL ✅  (boosted WR > penalized WR by {diff:.1f}pp)")
            elif diff < -5:
                print(f"    Feedback is HARMFUL ❌  (boosted WR < penalized WR by {-diff:.1f}pp)")
            else:
                print(f"    Feedback is NEUTRAL ➖  (diff: {diff:+.1f}pp)")
        else:
            print(f"    ⏳ Need more data (boosted: {boosted_n}, penalized: {penalized_n})")

        # ---- Section C: Hour-Based Sizing Summary ----
        hour_utc = get_current_hour_utc()
        current_multiplier = HOUR_SIZING_MULTIPLIER.get(hour_utc, 1.0)

        # Map hours to sizing tiers
        reduced_hours = [h for h, m in HOUR_SIZING_MULTIPLIER.items() if m <= 0.5]
        partial_hours = [h for h, m in HOUR_SIZING_MULTIPLIER.items() if 0.5 < m < 1.0]

        cursor.execute('''
            SELECT
                CASE
                    WHEN hour_utc IN ({reduced_ph}) THEN 'reduced (0.5x)'
                    WHEN hour_utc IN ({partial_ph}) THEN 'partial (0.75x)'
                    ELSE 'full (1.0x)'
                END as sizing_tier,
                COUNT(*) as cnt,
                SUM(CASE WHEN would_have_won = 1 THEN 1 ELSE 0 END) as wins
            FROM signal_log
            WHERE actual_result IN ('yes', 'no')
              AND hour_utc IS NOT NULL
              AND action_taken = 'placed'
            GROUP BY sizing_tier
        '''.format(
            reduced_ph=','.join(str(h) for h in reduced_hours) if reduced_hours else '-1',
            partial_ph=','.join(str(h) for h in partial_hours) if partial_hours else '-1',
        ))
        hour_rows = cursor.fetchall()

        print(f"\n  Section C — Hour-Based Sizing:")
        print(f"    Current hour: {hour_utc} UTC (multiplier: {current_multiplier}x)")
        print(f"    {'Sizing Tier':<20} {'Trades':>7} {'WinRate':>8}")
        print(f"    {'-'*38}")

        hour_data = {}
        for tier, cnt, wins in hour_rows:
            wr = (wins / cnt * 100) if cnt > 0 else 0
            hour_data[tier] = {'cnt': cnt, 'wr': wr}
            print(f"    {tier:<20} {cnt:>7} {wr:>7.1f}%")

        reduced_wr = hour_data.get('reduced (0.5x)', {}).get('wr', 0)
        full_wr = hour_data.get('full (1.0x)', {}).get('wr', 0)
        reduced_n = hour_data.get('reduced (0.5x)', {}).get('cnt', 0)
        full_n = hour_data.get('full (1.0x)', {}).get('cnt', 0)
        if reduced_n >= 3 and full_n >= 3:
            if reduced_wr < full_wr:
                print(f"    Hour sizing is VALIDATED ✅  (reduced-hour WR {reduced_wr:.0f}% < full-hour WR {full_wr:.0f}%)")
            else:
                print(f"    Hour sizing needs REVIEW ⚠️  (reduced-hour WR {reduced_wr:.0f}% >= full-hour WR {full_wr:.0f}%)")
        else:
            print(f"    ⏳ Need more data across hour tiers")

        # ---- Section D: Adaptive Penalty (Era 8) ----
        has_adaptive = 'adaptive_penalty' in cols and 'trend_regime' in cols
        if has_adaptive:
            cursor.execute('''
                SELECT
                    COALESCE(trend_regime, 'FLAT') as regime,
                    COUNT(*) as cnt,
                    SUM(CASE WHEN would_have_won = 1 THEN 1 ELSE 0 END) as wins,
                    AVG(adaptive_penalty) as avg_penalty
                FROM signal_log
                WHERE actual_result IN ('yes', 'no')
                  AND adaptive_penalty IS NOT NULL
                  AND action_taken = 'placed'
                GROUP BY regime
            ''')
            regime_rows = cursor.fetchall()

            if regime_rows:
                print(f"\n  Section D — Adaptive Penalty (Era 8):")
                print(f"    {'Regime':<12} {'Trades':>7} {'WinRate':>8} {'Avg Penalty':>12}")
                print(f"    {'-'*42}")

                regime_data = {}
                for regime, cnt, wins, avg_pen in regime_rows:
                    wr = (wins / cnt * 100) if cnt > 0 else 0
                    regime_data[regime] = {'cnt': cnt, 'wr': wr}
                    print(f"    {regime:<12} {cnt:>7} {wr:>7.1f}% {avg_pen:>+12.4f}")

                # Check macro divergence trades
                cursor.execute('''
                    SELECT COUNT(*) as cnt,
                           SUM(CASE WHEN would_have_won = 1 THEN 1 ELSE 0 END) as wins
                    FROM signal_log
                    WHERE actual_result IN ('yes', 'no')
                      AND action_taken = 'placed'
                      AND adaptive_penalty IS NOT NULL
                      AND trend_regime IS NOT NULL
                      AND macro_trend IS NOT NULL
                      AND trend_20m IS NOT NULL
                ''')
                # We can't easily query divergent from here (no column), but we log the macro_trend/trend_20m
                # For now, just show regime verdict
                bull_wr = regime_data.get('BULL', {}).get('wr', 0)
                flat_wr = regime_data.get('FLAT', {}).get('wr', 0)
                bear_wr = regime_data.get('BEAR', {}).get('wr', 0)
                bull_n = regime_data.get('BULL', {}).get('cnt', 0)
                bear_n = regime_data.get('BEAR', {}).get('cnt', 0)

                if bull_n >= 3 and bear_n >= 3:
                    if bull_wr > bear_wr:
                        print(f"    Penalty is ALIGNED ✅  (BULL WR {bull_wr:.0f}% > BEAR WR {bear_wr:.0f}%)")
                    else:
                        print(f"    Penalty needs REVIEW ⚠️  (BULL WR {bull_wr:.0f}% <= BEAR WR {bear_wr:.0f}%)")
                else:
                    print(f"    ⏳ Need more data (BULL: {bull_n}, BEAR: {bear_n})")

        conn.close()
        print(f"{'='*60}")

    except Exception as e:
        print(f"  ⚠️ Feature report error: {e}")

def print_weighted_performance_report():
    """Print weighted win rate metrics — dollar-weighted, contract-weighted, profit factor, etc."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # Core metrics from resolved trades
        cursor.execute('''
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN realized_pnl < 0 THEN 1 ELSE 0 END) as losses,
                SUM(CASE WHEN realized_pnl > 0 THEN realized_pnl ELSE 0 END) as gross_profit,
                SUM(CASE WHEN realized_pnl < 0 THEN ABS(realized_pnl) ELSE 0 END) as gross_loss,
                SUM(realized_pnl) as net_pnl,
                SUM(cost_basis) as total_deployed,
                SUM(CASE WHEN realized_pnl > 0 THEN contracts ELSE 0 END) as winning_contracts,
                SUM(CASE WHEN realized_pnl < 0 THEN contracts ELSE 0 END) as losing_contracts,
                SUM(contracts) as total_contracts,
                AVG(CASE WHEN realized_pnl > 0 THEN realized_pnl END) as avg_win,
                AVG(CASE WHEN realized_pnl < 0 THEN ABS(realized_pnl) END) as avg_loss,
                MIN(created_at) as first_trade,
                MAX(created_at) as last_trade
            FROM trades
            WHERE status IN ('won', 'lost', 'settled', 'closed')
            AND realized_pnl IS NOT NULL
        ''')
        row = cursor.fetchone()
        total, wins, losses, gross_profit, gross_loss, net_pnl, total_deployed, \
            win_contracts, lose_contracts, total_contracts, avg_win, avg_loss, \
            first_trade, last_trade = row

        if not total or total == 0:
            conn.close()
            return

        print(f"\n{'='*60}")
        print(f"📊 WEIGHTED PERFORMANCE REPORT")
        print(f"{'='*60}")

        # Calculate hours elapsed
        hours_elapsed = 1.0
        if first_trade and last_trade:
            try:
                t1 = dt.fromisoformat(first_trade.replace('Z', '+00:00')) if isinstance(first_trade, str) else first_trade
                t2 = dt.fromisoformat(last_trade.replace('Z', '+00:00')) if isinstance(last_trade, str) else last_trade
                hours_elapsed = max((t2 - t1).total_seconds() / 3600, 1.0)
            except:
                hours_elapsed = 1.0

        # Section 1: Core Metrics
        simple_wr = (wins / total * 100) if total > 0 else 0
        contract_wr = (win_contracts / total_contracts * 100) if total_contracts and total_contracts > 0 else 0
        dollar_wr = (gross_profit / (gross_profit + gross_loss) * 100) if (gross_profit + gross_loss) > 0 else 0
        profit_factor = (gross_profit / gross_loss) if gross_loss and gross_loss > 0 else float('inf')
        wl_ratio = (avg_win / avg_loss) if avg_loss and avg_loss > 0 else float('inf')
        expectancy = net_pnl / total if total > 0 else 0
        edge_pct = (net_pnl / total_deployed * 100) if total_deployed and total_deployed > 0 else 0
        profit_per_hour = net_pnl / 100 / hours_elapsed

        print(f"\n  Core Metrics ({total} resolved trades over {hours_elapsed:.1f}h):")
        print(f"    Simple Win Rate:      {wins}W / {losses}L = {simple_wr:.1f}%")
        print(f"    Contract-Weighted WR: {win_contracts or 0}/{total_contracts or 0} contracts = {contract_wr:.1f}%")
        print(f"    Dollar Win Rate:      ${(gross_profit or 0)/100:.2f} won / ${((gross_profit or 0)+(gross_loss or 0))/100:.2f} total = {dollar_wr:.1f}%")
        print(f"    Profit Factor:        {profit_factor:.2f}x (>${1:.0f} = profitable)")
        print(f"    Win/Loss Ratio:       ${(avg_win or 0)/100:.2f} avg win / ${(avg_loss or 0)/100:.2f} avg loss = {wl_ratio:.2f}x")
        print(f"    Expectancy:           ${expectancy/100:+.4f} per trade")
        print(f"    Edge %%:               {edge_pct:.1f}% return on capital deployed")
        print(f"    Profit/Hour:          ${profit_per_hour:+.2f}/hr")
        print(f"    Net P&L:              ${(net_pnl or 0)/100:+.2f}")

        # Section 2: By Position Size Bucket
        cursor.execute('''
            SELECT
                CASE
                    WHEN contracts = 1 THEN '1 contract'
                    WHEN contracts BETWEEN 2 AND 3 THEN '2-3 contracts'
                    WHEN contracts BETWEEN 4 AND 5 THEN '4-5 contracts'
                    ELSE '6+ contracts'
                END as bucket,
                COUNT(*) as trades,
                SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN realized_pnl > 0 THEN realized_pnl ELSE 0 END) as gp,
                SUM(CASE WHEN realized_pnl < 0 THEN ABS(realized_pnl) ELSE 0 END) as gl,
                SUM(realized_pnl) as net
            FROM trades
            WHERE status IN ('won', 'lost', 'settled', 'closed') AND realized_pnl IS NOT NULL
            GROUP BY bucket ORDER BY bucket
        ''')
        buckets = cursor.fetchall()
        if buckets:
            print(f"\n  By Position Size:")
            print(f"    {'Bucket':<16} {'Trades':>6} {'Simple':>7} {'Dollar':>7} {'PF':>6} {'Net P&L':>8}")
            print(f"    {'-'*52}")
            for bucket, trades, bwins, gp, gl, net in buckets:
                s_wr = (bwins / trades * 100) if trades > 0 else 0
                d_wr = (gp / (gp + gl) * 100) if (gp + gl) > 0 else 0
                pf = (gp / gl) if gl and gl > 0 else float('inf')
                pf_str = f"{pf:.2f}x" if pf != float('inf') else "∞"
                print(f"    {bucket:<16} {trades:>6} {s_wr:>6.1f}% {d_wr:>6.1f}% {pf_str:>6} ${net/100:>+7.2f}")

        # Section 3: By Series (extract from ticker prefix)
        cursor.execute('''
            SELECT
                CASE
                    WHEN ticker LIKE 'KXBTC%' THEN 'KXBTC15M'
                    WHEN ticker LIKE 'KXETH%' THEN 'KXETH15M'
                    WHEN ticker LIKE 'KXSOL%' THEN 'KXSOL15M'
                    WHEN ticker LIKE 'KXXRP%' THEN 'KXXRP15M'
                    ELSE 'OTHER'
                END as series,
                COUNT(*) as trades,
                SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN realized_pnl > 0 THEN realized_pnl ELSE 0 END) as gp,
                SUM(CASE WHEN realized_pnl < 0 THEN ABS(realized_pnl) ELSE 0 END) as gl,
                SUM(realized_pnl) as net,
                AVG(CASE WHEN realized_pnl > 0 THEN realized_pnl END) as avg_w,
                AVG(CASE WHEN realized_pnl < 0 THEN ABS(realized_pnl) END) as avg_l
            FROM trades
            WHERE status IN ('won', 'lost', 'settled', 'closed') AND realized_pnl IS NOT NULL
            GROUP BY series ORDER BY net DESC
        ''')
        series_rows = cursor.fetchall()
        if series_rows:
            print(f"\n  By Series:")
            print(f"    {'Series':<12} {'Trades':>6} {'Simple':>7} {'Dollar':>7} {'W/L':>5} {'Net P&L':>8}")
            print(f"    {'-'*48}")
            for series, trades, swins, gp, gl, net, avg_w, avg_l in series_rows:
                s_wr = (swins / trades * 100) if trades > 0 else 0
                d_wr = (gp / (gp + gl) * 100) if (gp + gl) > 0 else 0
                wl = (avg_w / avg_l) if avg_l and avg_l > 0 else float('inf')
                wl_str = f"{wl:.2f}" if wl != float('inf') else "∞"
                print(f"    {series:<12} {trades:>6} {s_wr:>6.1f}% {d_wr:>6.1f}% {wl_str:>5} ${net/100:>+7.2f}")

        # Section 4: Rolling Window (last 20 trades)
        cursor.execute('''
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN realized_pnl > 0 THEN realized_pnl ELSE 0 END) as gp,
                SUM(CASE WHEN realized_pnl < 0 THEN ABS(realized_pnl) ELSE 0 END) as gl,
                SUM(realized_pnl) as net,
                SUM(cost_basis) as deployed
            FROM (
                SELECT realized_pnl, cost_basis FROM trades
                WHERE status IN ('won', 'lost', 'settled', 'closed') AND realized_pnl IS NOT NULL
                ORDER BY created_at DESC LIMIT 20
            )
        ''')
        recent = cursor.fetchone()
        if recent and recent[0] and recent[0] > 0:
            r_total, r_wins, r_gp, r_gl, r_net, r_deployed = recent
            r_losses = r_total - (r_wins or 0)
            r_swr = ((r_wins or 0) / r_total * 100) if r_total > 0 else 0
            r_dwr = ((r_gp or 0) / ((r_gp or 0) + (r_gl or 0)) * 100) if ((r_gp or 0) + (r_gl or 0)) > 0 else 0
            r_pf = ((r_gp or 0) / (r_gl or 0)) if r_gl and r_gl > 0 else float('inf')
            r_pf_str = f"{r_pf:.2f}x" if r_pf != float('inf') else "∞"
            r_edge = ((r_net or 0) / (r_deployed or 1) * 100)
            print(f"\n  Last 20 Trades (rolling window):")
            print(f"    {r_wins or 0}W / {r_losses}L = {r_swr:.1f}% simple | {r_dwr:.1f}% dollar | PF {r_pf_str} | Edge {r_edge:.1f}% | ${(r_net or 0)/100:+.2f}")

            # Trend indicator
            if total > 20:
                all_time_swr = simple_wr
                trend = "📈 IMPROVING" if r_swr > all_time_swr else ("📉 DECLINING" if r_swr < all_time_swr - 5 else "➡️ STABLE")
                print(f"    Trend vs all-time ({all_time_swr:.1f}%): {trend}")

        conn.close()
        print(f"{'='*60}")

    except Exception as e:
        print(f"⚠️ Weighted report error: {e}")

def get_compact_performance_line():
    """Return a one-line performance summary string for scan-cycle logging."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN realized_pnl < 0 THEN 1 ELSE 0 END) as losses,
                SUM(CASE WHEN realized_pnl > 0 THEN realized_pnl ELSE 0 END) as gp,
                SUM(CASE WHEN realized_pnl < 0 THEN ABS(realized_pnl) ELSE 0 END) as gl,
                SUM(realized_pnl) as net_pnl,
                SUM(cost_basis) as deployed,
                MIN(created_at) as first_trade,
                MAX(created_at) as last_trade
            FROM trades
            WHERE status IN ('won', 'lost', 'settled', 'closed') AND realized_pnl IS NOT NULL
        ''')
        row = cursor.fetchone()

        # Count open and resting trades
        cursor.execute('''
            SELECT COUNT(*) as open_count,
                   SUM(CASE WHEN COALESCE(filled_count, contracts) = 0 THEN 1 ELSE 0 END) as resting_count
            FROM trades WHERE status = 'open'
        ''')
        open_row = cursor.fetchone()
        open_count = open_row[0] if open_row and open_row[0] else 0
        resting_count = open_row[1] if open_row and open_row[1] else 0

        conn.close()

        if not row or not row[0] or row[0] == 0:
            # Even with no resolved trades, show open/resting if any
            if open_count > 0:
                suffix = f"📊 Open: {open_count}"
                if resting_count > 0:
                    suffix += f" ({resting_count} resting)"
                return suffix
            return None

        total, wins, losses, gp, gl, net_pnl, deployed, first_trade, last_trade = row
        wins = wins or 0
        losses = losses or 0
        gp = gp or 0
        gl = gl or 0
        net_pnl = net_pnl or 0
        deployed = deployed or 1

        simple_wr = (wins / total * 100) if total > 0 else 0
        dollar_wr = (gp / (gp + gl) * 100) if (gp + gl) > 0 else 0
        pf = (gp / gl) if gl > 0 else float('inf')
        edge = (net_pnl / deployed * 100)

        # Calculate profit/hr
        hours = 1.0
        if first_trade and last_trade:
            try:
                t1 = dt.fromisoformat(str(first_trade).replace('Z', '+00:00'))
                t2 = dt.fromisoformat(str(last_trade).replace('Z', '+00:00'))
                hours = max((t2 - t1).total_seconds() / 3600, 1.0)
            except:
                hours = 1.0
        pph = net_pnl / 100 / hours

        pf_str = f"{pf:.2f}" if pf != float('inf') else "∞"
        suffix = ""
        if open_count > 0:
            suffix = f" | Open: {open_count}"
            if resting_count > 0:
                suffix += f" ({resting_count} resting)"
        return (f"📊 Performance: {wins}W/{losses}L ({simple_wr:.1f}%) | "
                f"Dollar WR: {dollar_wr:.1f}% | PF: {pf_str} | "
                f"Edge: {edge:.1f}% | ${pph:+.2f}/hr | Net: ${net_pnl/100:+.2f}{suffix}")

    except Exception as e:
        return None

def cleanup_old_signal_logs(days_to_keep=7):
    """Remove resolved signal_log entries older than N days."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cutoff = (dt.now(timezone.utc) - timedelta(days=days_to_keep)).isoformat()
        cursor.execute('''
            DELETE FROM signal_log
            WHERE scan_time < ? AND actual_result IS NOT NULL
        ''', (cutoff,))
        deleted = cursor.rowcount
        conn.commit()
        conn.close()
        if deleted > 0:
            print(f"🗑️ Signal log cleanup: removed {deleted} entries older than {days_to_keep} days")
    except Exception as e:
        print(f"    ⚠️ signal_log cleanup failed: {e}")

# ============================================================
# MAIN TRADING LOOP
# ============================================================

def run_enhanced_15min_trader_fixed():
    """Run the enhanced 15-minute crypto trader - FIXED VERSION."""
    print("=" * 70)
    print("🚨 ENHANCED 15-MINUTE CRYPTO TRADER - FIXED VERSION")
    print("💰 Fixed signal logic, UTC datetime, live balance, deduplication")
    print("📈 SQLite persistence and performance tracking")
    print(f"📊 Mode: {'OBSERVATION' if OBSERVATION_MODE else 'LIVE TRADING'}")
    print("=" * 70)
    
    # Setup database
    setup_database()
    
    # Check API key
    if not KALSHI_API_KEY_ID or KALSHI_API_KEY_ID == "YOUR_API_KEY_ID":
        print("❌ Please set KALSHI_API_KEY_ID environment variable")
        return
    
    try:
        # Initialize authentication
        auth = KalshiAuth(KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH)
        
        # Test authentication (no test order!)
        print(f"\n🔍 TESTING AUTHENTICATION...")
        
        timestamp = str(int(dt.now(timezone.utc).timestamp() * 1000))
        path = "/trade-api/v2/portfolio/balance"
        method = "GET"
        
        headers = get_headers(auth, method, path)
        url = "https://api.elections.kalshi.com" + path
        resp = requests.get(url, headers=headers, timeout=15)
        
        if resp.status_code == 200:
            balance_data = resp.json()
            balance = balance_data.get("balance", 0)
            print(f"✅ Authentication successful!")
            print(f"💰 Balance: ${balance/100:.2f}")
        else:
            print(f"❌ Authentication failed: {resp.status_code}")
            return
        
        # Trading loop
        scan_count = 0
        
        print(f"\n🚨 Starting enhanced 15-minute trading...")
        
        while True:  # Continuous scanning
            try:
                scan_count += 1
                current_time = dt.now(timezone.utc)
                
                print(f"\n{'='*60}")
                print(f"📊 SCAN #{scan_count} | {current_time.strftime('%H:%M:%S')}")
                
                # Get live balance
                live_balance = get_live_balance(auth)
                print(f"💰 Live balance: ${live_balance/100:.2f}")

                # Skip scan if balance unavailable in live mode
                if live_balance == 0 and not OBSERVATION_MODE:
                    print("⚠️ Balance unavailable, skipping scan cycle")
                    time.sleep(SCAN_INTERVAL)
                    continue
                
                # Reconcile any settled trades and signal log
                reconcile_trades(auth)
                reconcile_signal_log(auth)
                reconcile_feature_log(auth)

                # Periodic signal log report (every 60 scans ~30 min)
                if scan_count % 60 == 0 and scan_count > 0:
                    print_signal_log_report()
                    print_gate_effectiveness_report()
                    print_era7_feature_report()
                    print_weighted_performance_report()

                # Periodic cleanup (every 120 scans ~1 hour)
                if scan_count % 120 == 0 and scan_count > 0:
                    cleanup_old_signal_logs()

                # Compact weighted performance summary
                perf_line = get_compact_performance_line()
                if perf_line:
                    print(perf_line)
                
                # Get active markets
                active_markets = get_active_15min_markets(auth)
                
                if active_markets:
                    print(f"🎯 Found {len(active_markets)} active 15-minute markets!")
                    
                    # Sort by volume (most liquid first)
                    active_markets.sort(key=lambda x: x['volume'], reverse=True)
                    
                    trades_taken = 0
                    signals_found = 0

                    # Check concurrent position limit
                    open_count = count_open_positions()
                    if open_count >= MAX_CONCURRENT_POSITIONS:
                        print(f"📊 Max concurrent positions ({MAX_CONCURRENT_POSITIONS}) reached, skipping new entries")
                        store_scan(len(active_markets), 0, 0, live_balance)
                        print(f"\n⏳ Waiting {SCAN_INTERVAL} seconds for next scan...")
                        time.sleep(SCAN_INTERVAL)
                        continue

                    for market in active_markets:
                        # Re-check position limit mid-scan
                        if count_open_positions() >= MAX_CONCURRENT_POSITIONS:
                            print(f"📊 Position limit reached mid-scan, stopping new entries")
                            break

                        # Generate signal with full detail (L2: now includes signal_d, adaptive weights)
                        signal_detail = calculate_external_signal_detailed(market)
                        win_prob = signal_detail['win_prob']

                        # Adaptive directional penalty (Era 8) — trend-aware, per-asset + macro
                        adaptive_penalty, trend_detail = calculate_adaptive_penalty(market['series'])

                        if adaptive_penalty > 0 and win_prob > 0.50:
                            # Bear/flat: penalize YES-leaning signals
                            win_prob = win_prob - adaptive_penalty
                        elif adaptive_penalty < 0 and win_prob < 0.50:
                            # Bull: penalize NO-leaning signals (push toward 0.50)
                            win_prob = win_prob + adaptive_penalty  # negative, so subtracts

                        win_prob = max(SIGNAL_FLOOR, min(SIGNAL_CEILING, win_prob))

                        print(f"    🔧 Adaptive penalty: {adaptive_penalty:+.4f} "
                              f"(asset={trend_detail['asset_trend']*100:+.3f}%, "
                              f"macro={trend_detail['macro_trend']*100:+.3f}%, "
                              f"regime={trend_detail['regime']}"
                              f"{'  ⚡DIVERGENT' if trend_detail.get('divergent') else ''})")

                        # Performance feedback (Era 9: pooled across assets, regime-aware)
                        perf_adjustment = 0.0
                        likely_direction = 'YES' if win_prob > 0.50 else 'NO'
                        current_regime = trend_detail.get('regime', 'FLAT')

                        if PERF_POOL_ASSETS:
                            # Era 9: Pool all assets for direction-level feedback
                            pool_wr, pool_n = get_pooled_direction_performance(
                                likely_direction, PERF_LOOKBACK_HOURS, regime=current_regime)
                            if pool_wr is not None:
                                # Use regime-specific baseline if available
                                baseline = PERF_REGIME_BASELINES.get(current_regime, PERF_BASELINE_WR)
                                wr_delta = pool_wr - baseline
                                perf_adjustment = max(-PERF_MAX_ADJUSTMENT, min(PERF_MAX_ADJUSTMENT, wr_delta * 0.5))
                                win_prob = win_prob + perf_adjustment
                                win_prob = max(SIGNAL_FLOOR, min(SIGNAL_CEILING, win_prob))
                                print(f"    📊 Perf feedback (pooled): {likely_direction} {current_regime} "
                                      f"WR={pool_wr:.1%} (n={pool_n}, baseline={baseline:.0%}) → adj {perf_adjustment:+.3f}")
                        else:
                            # Legacy: per-asset feedback (Era 7)
                            asset_wr, asset_n = get_asset_direction_performance(
                                market['series'], likely_direction, PERF_LOOKBACK_HOURS)
                            if asset_wr is not None:
                                wr_delta = asset_wr - PERF_BASELINE_WR
                                perf_adjustment = max(-PERF_MAX_ADJUSTMENT, min(PERF_MAX_ADJUSTMENT, wr_delta * 0.5))
                                win_prob = win_prob + perf_adjustment
                                win_prob = max(SIGNAL_FLOOR, min(SIGNAL_CEILING, win_prob))
                                print(f"    📊 Perf feedback: {market['series'][:5]} {likely_direction} "
                                      f"WR={asset_wr:.1%} (n={asset_n}) → adj {perf_adjustment:+.3f}")

                        signal_a = signal_detail['signal_a']
                        signal_b = signal_detail['signal_b']
                        signal_c = signal_detail['signal_c']
                        signal_d = signal_detail.get('signal_d', 0.5)
                        signal_e = signal_detail.get('signal_e', 0.5)
                        spot_price = signal_detail['spot_price']
                        perp_price = signal_detail.get('perp_price')
                        vol = signal_detail.get('volatility', 0.0)
                        weights_used = signal_detail.get('weights_used', (0.45, 0.50, 0.15, 0.05, 0.10))

                        # Calculate EV for both sides
                        yes_ev = calculate_ev(market['yes_ask'], market['no_ask'], win_prob, 'YES')
                        no_ev = calculate_ev(market['yes_ask'], market['no_ask'], 1 - win_prob, 'NO')
                        best_ev = max(yes_ev, no_ev)

                        # Determine best direction and kelly (needed for logging even when declined)
                        if yes_ev >= no_ev:
                            best_direction = 'YES'
                            kelly_frac = calculate_kelly_fraction(win_prob, market['yes_ask'])
                        else:
                            best_direction = 'NO'
                            kelly_frac = calculate_kelly_fraction(1 - win_prob, market['no_ask'])

                        scan_time_iso = current_time.isoformat()
                        hour_utc = get_current_hour_utc()

                        # === LAYER 1: MULTI-GATE PIPELINE (Era 10 — EV-first architecture) ===
                        action_taken = 'declined'
                        decline_reason = None
                        gate_declined = None
                        agreement_strength = None

                        # Compute conviction and agreement for sizing
                        combined_conviction = abs(win_prob - 0.5)
                        _agree_strength, agrees = check_signal_agreement(signal_a, signal_b)

                        # Determine agreement_strength tier for position sizing
                        if combined_conviction >= STRONG_CONVICTION_THRESHOLD:
                            agreement_strength = 'strong'
                        elif agrees:
                            agreement_strength = 'weak'
                        else:
                            agreement_strength = 'none'

                        # Compute entry price and payoff metrics (needed by multiple gates)
                        entry_price = market['yes_ask'] if best_direction == 'YES' else market['no_ask']
                        payoff_multiple = (100 - entry_price) / entry_price if entry_price > 0 else 1.0
                        entry_band = get_entry_band_label(entry_price)
                        entry_band_mult = get_entry_band_sizing(entry_price)
                        adjusted_ev = calculate_adjusted_ev(best_ev, entry_price)

                        # GATE 0 — Regime Gate (Era 10: block FLAT only, allow both directions in BEAR/BULL)
                        if REGIME_GATE_ENABLED:
                            regime_perms = get_regime_permissions()
                            if not regime_perms.get((current_regime, best_direction), False):
                                gate_declined = 'regime_blocked'
                                decline_reason = f'Regime blocked ({current_regime}+{best_direction} not in allowed combos)'
                                print(f"    🚫 [GATE 0] {market['ticker']}: {decline_reason}")

                        # GATE 0.5 — Signal Agreement Gate (Era 10: disabled, demoted to sizing-only)
                        if gate_declined is None and REQUIRE_SIGNAL_AGREEMENT:
                            if MIN_AGREEMENT_TO_TRADE == 'strong' and agreement_strength != 'strong':
                                gate_declined = 'weak_agreement'
                                decline_reason = f'Signal agreement too weak ({agreement_strength}, need strong)'
                                print(f"    🚫 [GATE 0.5] {market['ticker']}: {decline_reason}")
                            elif MIN_AGREEMENT_TO_TRADE == 'weak' and agreement_strength == 'none':
                                gate_declined = 'no_agreement'
                                decline_reason = f'No signal agreement (signals A/B disagree)'
                                print(f"    🚫 [GATE 0.5] {market['ticker']}: {decline_reason}")

                        # GATE 1 — Entry Price Band (Era 10: the profit engine — replaces old floor)
                        if gate_declined is None:
                            if entry_price < MIN_ENTRY_PRICE:
                                gate_declined = 'too_cheap'
                                decline_reason = f'Entry too cheap ({entry_price}c < {MIN_ENTRY_PRICE}c floor)'
                                print(f"    🚫 [GATE 1] {market['ticker']}: {decline_reason}")
                            elif entry_price >= MAX_ENTRY_PRICE:
                                gate_declined = 'too_expensive'
                                decline_reason = f'Entry too expensive ({entry_price}c >= {MAX_ENTRY_PRICE}c ceiling, payoff={payoff_multiple:.2f}x)'
                                print(f"    🚫 [GATE 1] {market['ticker']}: {decline_reason}")

                        # GATE 2 — Payoff-Adjusted EV (Era 10: rewards asymmetric entries)
                        if gate_declined is None and adjusted_ev <= MIN_ADJUSTED_EV:
                            gate_declined = 'low_adjusted_ev'
                            decline_reason = f'Adjusted EV too low ({adjusted_ev:.1f}c < {MIN_ADJUSTED_EV}c, raw={best_ev:.1f}c, payoff={payoff_multiple:.2f}x)'
                            print(f"    🚫 [GATE 2] {market['ticker']}: {decline_reason}")

                        # GATE 3 — Adaptive Conviction (Era 10: scaled by payoff multiple)
                        if gate_declined is None:
                            effective_conviction_threshold = MIN_CONVICTION_THRESHOLD / max(payoff_multiple, 1.0)
                            if combined_conviction < effective_conviction_threshold:
                                gate_declined = 'low_conviction'
                                decline_reason = (f'Low conviction (wp={win_prob:.3f}, conv={combined_conviction:.3f} '
                                                  f'< {effective_conviction_threshold:.4f} [base {MIN_CONVICTION_THRESHOLD}/payoff {payoff_multiple:.2f}x])')
                                print(f"    🚫 [GATE 3] {market['ticker']}: {decline_reason}")

                        # GATE 4 — Volatility (skip if too flat to predict)
                        if gate_declined is None and vol > 0 and vol < VOLATILITY_LOW_THRESHOLD and signal_detail.get('volatility', 0) > 0:
                            gate_declined = 'low_volatility'
                            decline_reason = f'Low volatility ({vol:.6f} < {VOLATILITY_LOW_THRESHOLD})'
                            print(f"    🚫 [GATE 4] {market['ticker']}: {decline_reason}")

                        # GATE 5 — Minimum position size
                        if gate_declined is None:
                            price = entry_price

                            # Macro trend sizing: only boost if trade aligns with macro direction
                            sizing_macro = trend_detail.copy() if trend_detail else None
                            if sizing_macro and not sizing_macro.get('divergent'):
                                macro_t = sizing_macro.get('macro_trend', 0)
                                if (best_direction == 'YES' and macro_t < 0) or (best_direction == 'NO' and macro_t > 0):
                                    sizing_macro['macro_trend'] = 0  # no boost for counter-trend trades

                            effective_max = calculate_dynamic_max_contracts(
                                live_balance, price, agreement_strength,
                                hour_utc=get_current_hour_utc(), macro_detail=sizing_macro,
                                series_ticker=market['series'], entry_price=entry_price)
                            if not OBSERVATION_MODE:
                                max_by_kelly = int(kelly_frac * live_balance / price) if price > 0 else 0
                                contracts_would_be = min(max_by_kelly, effective_max)
                            else:
                                contracts_would_be = min(10, effective_max)

                            if contracts_would_be < MIN_CONTRACTS:
                                gate_declined = 'min_contracts'
                                decline_reason = f'Below min contracts ({contracts_would_be} < {MIN_CONTRACTS})'
                                print(f"    🚫 [GATE 5] {market['ticker']}: {decline_reason}")

                            else:
                                # ALL GATES PASSED — attempt trade
                                signals_found += 1
                                market['_effective_max'] = effective_max
                                market['_min_contracts'] = MIN_CONTRACTS

                                print(f"    ✅ GATES PASSED: {entry_band} band ({entry_price}c, {payoff_multiple:.2f}x payoff), "
                                      f"adj_ev={adjusted_ev:.1f}c, {agreement_strength} agreement, {current_regime} regime")

                                # Execute trade
                                success, result = execute_trade_enhanced(
                                    auth, market, win_prob, best_ev, kelly_frac, live_balance
                                )

                                if success:
                                    trades_taken += 1
                                    action_taken = 'placed'
                                    decline_reason = None
                                    gate_declined = None
                                    print(f"\n🎉 TRADE {'LOGGED' if OBSERVATION_MODE else 'PLACED'} SUCCESSFULLY! "
                                          f"[{entry_price}c {best_direction}, {payoff_multiple:.2f}x payoff, "
                                          f"agreement={agreement_strength}, regime={current_regime}]")
                                else:
                                    action_taken = 'declined'
                                    decline_reason = result
                                    gate_declined = 'execution_failed'
                                    print(f"\n❌ Trade execution failed: {result}")

                        # ALWAYS log the signal evaluation (placed or declined)
                        w_a, w_b, w_d, w_c, w_e = weights_used
                        store_signal_log(
                            ticker=market['ticker'],
                            series_ticker=market['series'],
                            scan_time=scan_time_iso,
                            close_time=market['close_time'],
                            yes_ask=market['yes_ask'],
                            no_ask=market['no_ask'],
                            spot_price=spot_price,
                            floor_strike=market.get('floor_strike'),
                            signal_a=signal_a,
                            signal_b=signal_b,
                            signal_c=signal_c,
                            win_prob=win_prob,
                            yes_ev=yes_ev,
                            no_ev=no_ev,
                            best_direction=best_direction,
                            best_ev=best_ev,
                            kelly_frac=kelly_frac,
                            action_taken=action_taken,
                            decline_reason=decline_reason,
                            agreement_strength=agreement_strength,
                            volatility=vol,
                            hour_utc=hour_utc,
                            gate_declined=gate_declined,
                            signal_d=signal_d,
                            perp_price=perp_price,
                            weight_a=w_a, weight_b=w_b, weight_c=w_c, weight_d=w_d,
                            signal_e=signal_e, weight_e=w_e, perf_adjustment=perf_adjustment,
                            adaptive_penalty=adaptive_penalty,
                            trend_20m=trend_detail.get('asset_trend') if trend_detail else None,
                            macro_trend=trend_detail.get('macro_trend') if trend_detail else None,
                            trend_regime=trend_detail.get('regime') if trend_detail else None,
                            payoff_multiple=payoff_multiple,
                            adjusted_ev=adjusted_ev,
                            entry_band=entry_band,
                            entry_band_sizing=entry_band_mult,
                        )

                        # ALWAYS log features for ML training (Layer 3 prep)
                        time_remaining_sec = None
                        if market.get('close_time'):
                            try:
                                close_dt = dt.fromisoformat(market['close_time'].replace('Z', '+00:00'))
                                time_remaining_sec = int((close_dt - current_time).total_seconds())
                            except Exception:
                                pass
                        store_feature_log(
                            ticker=market['ticker'],
                            series_ticker=market['series'],
                            scan_time=scan_time_iso,
                            close_time=market['close_time'],
                            time_remaining_sec=time_remaining_sec,
                            spot_price=spot_price,
                            floor_strike=market.get('floor_strike'),
                            perp_price=perp_price,
                            signal_detail=signal_detail,
                            weights=weights_used,
                        )
                    
                    # FIXED: Record scan with actual signal count
                    store_scan(len(active_markets), signals_found, trades_taken, live_balance)
                    
                else:
                    print(f"📊 No active 15-minute markets found")
                    print(f"💡 Waiting for new markets to appear...")
                    store_scan(0, 0, 0, live_balance)
                
                # Wait for next scan
                print(f"\n⏳ Waiting {SCAN_INTERVAL} seconds for next scan...")
                time.sleep(SCAN_INTERVAL)
                
            except KeyboardInterrupt:
                print(f"\n🛑 Manual shutdown")
                break
            except Exception as e:
                print(f"❌ Error in trading loop: {e}")
                import traceback
                print(f"🐛 Traceback: {traceback.format_exc()}")
                time.sleep(30)
        
    except Exception as e:
        print(f"❌ Trader initialization failed: {e}")

def store_scan(markets_found, signals_found, trades_taken, balance_cents):
    """Store scan statistics."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        cursor.execute('''
            INSERT INTO scans (scan_time, markets_found, signals_found, trades_taken, balance_cents)
            VALUES (?, ?, ?, ?, ?)
        ''', (dt.now(timezone.utc).isoformat(), markets_found, signals_found, trades_taken, balance_cents))

        conn.commit()
        conn.close()
    except Exception as e:
        print(f"⚠️ Failed to store scan record: {e}")

if __name__ == "__main__":
    run_enhanced_15min_trader_fixed()
