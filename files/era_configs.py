"""
Era configuration reference — NOT imported by the bot.
Use this to manually revert to any era's config by copying values
into simple_15min_trader_enhanced_fixed.py.

To rollback:
  1. git stash (save current changes)
  2. Copy desired era's values into the main config
  3. Restart bot
  4. If bad: git stash pop (restore previous state)
"""

ERA_CONFIGS = {
    'era2': {
        'description': 'Most profitable era: +$46.80, $2.04/hr, 47.3% WR',
        'MIN_CONVICTION_THRESHOLD': 0.01,
        'MIN_ENTRY_PRICE': 5,
        'MAX_ENTRY_PRICE': 55,
        'MIN_CONTRACTS': 2,
        'MAX_CONTRACTS_CEILING': 25,
        'KELLY_TYPE': 'conviction',  # |win_prob - 0.5| * KELLY_FRACTION
        'ADAPTIVE_PENALTY_BASE': 0.0,  # did not exist
        'ADAPTIVE_PENALTY_MAX': 0.0,   # did not exist
        'PERF_MAX_ADJUSTMENT': 0.0,    # did not exist
        'REGIME_GATE_ENABLED': False,   # did not exist
        'REQUIRE_SIGNAL_AGREEMENT': False,  # was a soft gate, not hard
        'BASE_RISK_PCT': 0.015,
        'STRONG_RISK_PCT': 0.035,
        'WEAK_RISK_PCT': 0.020,
    },
    'era10': {
        'description': 'EV-first architecture: entry band 38-49c, payoff Kelly. -$7.57, 12.5% WR',
        'MIN_CONVICTION_THRESHOLD': 0.010,
        'MIN_ENTRY_PRICE': 38,
        'MAX_ENTRY_PRICE': 49,
        'MIN_CONTRACTS': 1,
        'MAX_CONTRACTS_CEILING': 25,
        'KELLY_TYPE': 'payoff_aware',  # (b*p - q) / b where b = payout/cost
        'ADAPTIVE_PENALTY_BASE': 0.005,
        'ADAPTIVE_PENALTY_MAX': 0.02,
        'PERF_MAX_ADJUSTMENT': 0.02,
        'REGIME_GATE_ENABLED': True,
        'REGIME_LEARNING_ENABLED': True,
        'ASSET_SIZING_LEARNING_ENABLED': True,
        'REQUIRE_SIGNAL_AGREEMENT': False,
        'BASE_RISK_PCT': 0.015,
        'IDEAL_ENTRY_MIN': 42,
        'IDEAL_ENTRY_MAX': 47,
        'MIN_ADJUSTED_EV': -2.0,
    },
    'era11': {
        'description': 'Era 2 redux with Era 10 logging. Gates open, max 5 contracts. -$3.38, 30% WR',
        'MIN_CONVICTION_THRESHOLD': 0.001,
        'MIN_ENTRY_PRICE': 15,
        'MAX_ENTRY_PRICE': 55,
        'MIN_CONTRACTS': 1,
        'MAX_CONTRACTS_CEILING': 5,
        'KELLY_TYPE': 'payoff_aware',  # still had payoff Kelly (bug)
        'ADAPTIVE_PENALTY_BASE': 0.005,  # still active (bug — biased NO)
        'ADAPTIVE_PENALTY_MAX': 0.02,
        'PERF_MAX_ADJUSTMENT': 0.02,    # still active (bug — reinforced losses)
        'REGIME_GATE_ENABLED': False,
        'REGIME_LEARNING_ENABLED': False,
        'ASSET_SIZING_LEARNING_ENABLED': False,
        'REQUIRE_SIGNAL_AGREEMENT': False,
        'BASE_RISK_PCT': 0.015,
        'MIN_ADJUSTED_EV': -10.0,
    },
    'era12': {
        'description': 'Pure Era 2 restoration with Era 10 logging. Balance: $54.16',
        'MIN_CONVICTION_THRESHOLD': 0.01,
        'MIN_ENTRY_PRICE': 5,
        'MAX_ENTRY_PRICE': 55,
        'MIN_CONTRACTS': 2,
        'MAX_CONTRACTS_CEILING': 10,  # reduced from Era 2s 25 for safety
        'KELLY_TYPE': 'conviction',   # |win_prob - 0.5| * KELLY_FRACTION
        'ADAPTIVE_PENALTY_BASE': 0.0,
        'ADAPTIVE_PENALTY_MAX': 0.0,
        'PERF_MAX_ADJUSTMENT': 0.0,
        'REGIME_GATE_ENABLED': False,
        'REGIME_LEARNING_ENABLED': False,
        'ASSET_SIZING_LEARNING_ENABLED': False,
        'REQUIRE_SIGNAL_AGREEMENT': False,
        'BASE_RISK_PCT': 0.015,
        'STRONG_RISK_PCT': 0.035,
        'WEAK_RISK_PCT': 0.020,
    },
}
