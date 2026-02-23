# Polymarket Pattern Analyzer → Kalshi Executor

A system that reverse-engineers the trading strategy of Polymarket's `distinct-baguette` wallet (a profitable arbitrage bot) and applies similar patterns on Kalshi, a CFTC-regulated prediction market legal for US traders.

## What This Does

1. **Fetches** all historical trade data for `distinct-baguette` from Polymarket's Data API
2. **Analyzes** trading patterns: arbitrage detection, market preferences, timing, position sizing, price distributions
3. **Monitors** the account in real-time for new trades and strategy shifts
4. **Scans** Kalshi markets for equivalent arbitrage opportunities
5. **Executes** trades on Kalshi (with risk controls and demo mode)

## Architecture

```
┌─────────────────────────────┐     ┌──────────────────────────┐
│   Polymarket (Read Only)    │     │   Kalshi (Read + Write)  │
│                             │     │                          │
│  fetch_trades.py            │     │  kalshi_executor.py      │
│    → trades_raw.json        │     │    → Market scanning     │
│    → activity_raw.json      │     │    → Arb detection       │
│    → positions_raw.json     │     │    → Order placement     │
│                             │     │    → Risk controls       │
│  monitor.py                 │     │                          │
│    → Real-time polling      │     │                          │
│    → Strategy shift alerts  │     │                          │
└─────────────┬───────────────┘     └────────────┬─────────────┘
              │                                   │
              ▼                                   ▲
    ┌─────────────────────┐                       │
    │  analyze_patterns.py │───────────────────────┘
    │                     │   Strategy signals
    │  → Arb detection    │   inform execution
    │  → Price analysis   │
    │  → Category weights │
    │  → Timing patterns  │
    │  → Strategy profile │
    └─────────────────────┘
```

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Step 1: Fetch all historical trade data
python main.py fetch

# Step 2: Analyze patterns
python main.py analyze

# Step 3: Scan Kalshi for opportunities
python main.py scan

# Or run the full pipeline at once
python main.py run
```

## Commands

| Command | Description |
|---------|-------------|
| `python main.py fetch` | Pull all trade history from Polymarket |
| `python main.py analyze` | Run pattern analysis on fetched data |
| `python main.py scan` | Scan Kalshi for arbitrage opportunities |
| `python main.py monitor` | Live-monitor for new trades and strategy shifts |
| `python main.py run` | Full pipeline: fetch → analyze → scan |
| `python main.py live` | Monitor + auto-execute on Kalshi (**use demo first!**) |

## Setting Up Kalshi API

1. Create an account at [kalshi.com](https://kalshi.com)
2. Go to Account → API Keys → Generate a new key pair
3. Save the private key as `kalshi-key.pem` in this directory
4. Set environment variables:
   ```bash
   export KALSHI_API_KEY_ID="your-key-id"
   export KALSHI_PRIVATE_KEY_PATH="./kalshi-key.pem"
   ```
5. **Start with demo mode** (`USE_DEMO = True` in `kalshi_executor.py`)

## Key Findings About distinct-baguette

Based on public analysis, this wallet primarily runs an **arbitrage strategy**:

- Buys both YES and NO when combined price < $1.00
- Captures the spread as risk-free profit
- Focuses on crypto markets (55% win rate reported)
- Uses automated execution (rapid trade clusters)
- Made ~$242K in ~1.5 months

## Adapting for Kalshi

The arbitrage approach is platform-agnostic. On Kalshi:

- Same principle: find markets where YES + NO prices sum to < $1.00
- Kalshi is centralized so execution can be faster (no blockchain confirmation)
- Fewer markets = fewer opportunities, but less competition
- Fee structure differs — calculate net profitability per trade
- Kalshi has exchange hours — not 24/7 like Polymarket

## Risk Controls (kalshi_executor.py)

- `MAX_POSITION_SIZE = 100` — Max contracts per order
- `MAX_DAILY_TRADES = 50` — Max trades per day
- `MAX_DAILY_EXPOSURE = 5000` — Max $ exposure per day
- `MIN_SPREAD_FOR_ARB = 0.02` — Minimum 2c spread to attempt arb
- `USE_DEMO = True` — Start in demo mode!

## Output Files

```
data/
  trades_raw.json           # All historical trades
  activity_raw.json         # Trades + splits + merges + redeems
  positions_raw.json        # Current open positions
  closed_positions_raw.json # Settled positions
  monitor_state.json        # Monitoring state (seen txns)
  new_trades_log.jsonl      # Log of detected new trades
  strategy_shifts.jsonl     # Detected strategy changes
  kalshi_opportunities.json # Latest Kalshi arb scan
  kalshi_orders.jsonl       # Order execution log
  live_signals.jsonl        # Live cross-platform signals

analysis/
  pattern_analysis.json     # Full strategy analysis
```

## Disclaimer

This software is for educational and research purposes. Trading on prediction markets involves real financial risk. Always start with demo/paper trading. The author is not responsible for any financial losses. Ensure you comply with all applicable laws and platform terms of service.
