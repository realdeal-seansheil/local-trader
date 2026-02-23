"""
Pattern Analyzer for distinct-baguette's Polymarket trades.
Identifies trading patterns, strategies, and behavioral signals.

Run after fetch_trades.py: python analyze_patterns.py
"""

import json
import os
from datetime import datetime, timedelta
from collections import defaultdict, Counter
import statistics

DATA_DIR = "data"
OUTPUT_DIR = "analysis"
os.makedirs(OUTPUT_DIR, exist_ok=True)


def load_json(filename):
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        print(f"  WARNING: {path} not found. Run fetch_trades.py first.")
        return []
    with open(path) as f:
        return json.load(f)


def ts_to_dt(ts):
    """Convert timestamp (ms or s) to datetime."""
    if ts > 1e12:  # milliseconds
        return datetime.fromtimestamp(ts / 1000)
    return datetime.fromtimestamp(ts)


def analyze_trades(trades: list) -> dict:
    """Core trade pattern analysis."""
    if not trades:
        return {"error": "No trades to analyze"}

    results = {}

    # ===== BASIC STATS =====
    buys = [t for t in trades if t.get("side") == "BUY"]
    sells = [t for t in trades if t.get("side") == "SELL"]
    results["total_trades"] = len(trades)
    results["total_buys"] = len(buys)
    results["total_sells"] = len(sells)
    results["buy_sell_ratio"] = round(len(buys) / max(len(sells), 1), 2)

    # ===== TIME ANALYSIS =====
    timestamps = sorted([t["timestamp"] for t in trades if t.get("timestamp")])
    if timestamps:
        first_dt = ts_to_dt(timestamps[0])
        last_dt = ts_to_dt(timestamps[-1])
        results["first_trade"] = first_dt.isoformat()
        results["last_trade"] = last_dt.isoformat()
        results["active_days"] = (last_dt - first_dt).days

        # Trading frequency by hour of day (UTC)
        hours = [ts_to_dt(ts).hour for ts in timestamps]
        hour_counts = Counter(hours)
        results["most_active_hours_utc"] = [
            {"hour": h, "trades": c}
            for h, c in hour_counts.most_common(5)
        ]

        # Trading frequency by day of week
        days = [ts_to_dt(ts).strftime("%A") for ts in timestamps]
        day_counts = Counter(days)
        results["most_active_days"] = [
            {"day": d, "trades": c}
            for d, c in day_counts.most_common()
        ]

        # Trades per day over time
        daily_counts = Counter(ts_to_dt(ts).date().isoformat() for ts in timestamps)
        counts = list(daily_counts.values())
        results["avg_trades_per_active_day"] = round(statistics.mean(counts), 1)
        results["max_trades_in_a_day"] = max(counts)
        results["active_trading_days"] = len(daily_counts)

    # ===== MARKET ANALYSIS =====
    market_trades = defaultdict(list)
    for t in trades:
        key = t.get("title") or t.get("slug") or t.get("conditionId", "unknown")
        market_trades[key].append(t)

    results["unique_markets_traded"] = len(market_trades)

    # Most traded markets
    results["top_markets_by_volume"] = [
        {
            "market": m,
            "trade_count": len(tl),
            "total_size": round(sum(t.get("size", 0) for t in tl), 2),
            "avg_price": round(statistics.mean(t.get("price", 0) for t in tl if t.get("price")), 4) if any(t.get("price") for t in tl) else None,
        }
        for m, tl in sorted(market_trades.items(), key=lambda x: len(x[1]), reverse=True)[:20]
    ]

    # ===== PRICE ANALYSIS =====
    prices = [t["price"] for t in trades if t.get("price") and t["price"] > 0]
    if prices:
        results["price_stats"] = {
            "mean_entry_price": round(statistics.mean(prices), 4),
            "median_entry_price": round(statistics.median(prices), 4),
            "stdev_entry_price": round(statistics.stdev(prices), 4) if len(prices) > 1 else 0,
            "min_price": round(min(prices), 4),
            "max_price": round(max(prices), 4),
        }

        # Price distribution buckets (key for understanding strategy)
        buckets = {"0-10c": 0, "10-20c": 0, "20-30c": 0, "30-40c": 0, "40-50c": 0,
                   "50-60c": 0, "60-70c": 0, "70-80c": 0, "80-90c": 0, "90-100c": 0}
        for p in prices:
            if p <= 0.10: buckets["0-10c"] += 1
            elif p <= 0.20: buckets["10-20c"] += 1
            elif p <= 0.30: buckets["20-30c"] += 1
            elif p <= 0.40: buckets["30-40c"] += 1
            elif p <= 0.50: buckets["40-50c"] += 1
            elif p <= 0.60: buckets["50-60c"] += 1
            elif p <= 0.70: buckets["60-70c"] += 1
            elif p <= 0.80: buckets["70-80c"] += 1
            elif p <= 0.90: buckets["80-90c"] += 1
            else: buckets["90-100c"] += 1
        results["price_distribution"] = buckets

    # ===== POSITION SIZE ANALYSIS =====
    sizes = [t["size"] for t in trades if t.get("size") and t["size"] > 0]
    if sizes:
        results["size_stats"] = {
            "mean_size": round(statistics.mean(sizes), 2),
            "median_size": round(statistics.median(sizes), 2),
            "stdev_size": round(statistics.stdev(sizes), 2) if len(sizes) > 1 else 0,
            "min_size": round(min(sizes), 2),
            "max_size": round(max(sizes), 2),
            "total_volume": round(sum(sizes), 2),
        }

    # ===== ARBITRAGE DETECTION =====
    # Look for pairs of trades in the same market where both YES and NO are bought
    arb_candidates = detect_arbitrage_patterns(trades, market_trades)
    results["arbitrage_analysis"] = arb_candidates

    # ===== OUTCOME ANALYSIS =====
    outcomes = Counter(t.get("outcome") for t in trades if t.get("outcome"))
    results["outcome_distribution"] = dict(outcomes)

    # ===== CATEGORY/SLUG ANALYSIS =====
    event_slugs = [t.get("eventSlug", "") for t in trades if t.get("eventSlug")]
    categories = categorize_markets(event_slugs)
    results["market_categories"] = categories

    # ===== TRADE CLUSTERING =====
    # Detect bursts of rapid trading (potential arb execution)
    clusters = detect_trade_clusters(trades)
    results["trade_clustering"] = clusters

    return results


def detect_arbitrage_patterns(trades: list, market_trades: dict) -> dict:
    """
    Detect arbitrage patterns: buying both YES and NO in the same market
    within a short time window, where combined price < $1.
    """
    arb_results = {
        "suspected_arb_markets": 0,
        "suspected_arb_trades": 0,
        "avg_arb_spread": None,
        "examples": [],
    }

    arb_spreads = []

    for market, mtrades in market_trades.items():
        # Group by outcome
        yes_buys = [t for t in mtrades if t.get("side") == "BUY" and t.get("outcomeIndex") == 0]
        no_buys = [t for t in mtrades if t.get("side") == "BUY" and t.get("outcomeIndex") == 1]

        if not yes_buys or not no_buys:
            continue

        # Check if YES + NO were bought close in time
        for yb in yes_buys:
            yt = yb.get("timestamp", 0)
            yp = yb.get("price", 0)
            for nb in no_buys:
                nt = nb.get("timestamp", 0)
                np_ = nb.get("price", 0)

                time_diff = abs(yt - nt)
                # Within 5 minutes (300 seconds or 300000 ms)
                threshold = 300000 if yt > 1e12 else 300

                if time_diff < threshold and yp > 0 and np_ > 0:
                    combined = yp + np_
                    if combined < 1.0:  # Arb opportunity
                        spread = round(1.0 - combined, 4)
                        arb_spreads.append(spread)

                        if len(arb_results["examples"]) < 10:
                            arb_results["examples"].append({
                                "market": market,
                                "yes_price": round(yp, 4),
                                "no_price": round(np_, 4),
                                "combined": round(combined, 4),
                                "spread_captured": spread,
                                "time_between_sec": round(time_diff / (1000 if yt > 1e12 else 1)),
                            })
                        break  # One match per YES buy is enough

    arb_results["suspected_arb_markets"] = len(set(e["market"] for e in arb_results["examples"]))
    arb_results["suspected_arb_trades"] = len(arb_spreads)
    if arb_spreads:
        arb_results["avg_arb_spread"] = round(statistics.mean(arb_spreads), 4)
        arb_results["total_estimated_arb_profit_per_dollar"] = round(sum(arb_spreads), 4)

    return arb_results


def detect_trade_clusters(trades: list) -> dict:
    """Detect bursts of rapid trading (multiple trades within seconds)."""
    if not trades:
        return {}

    sorted_trades = sorted(trades, key=lambda t: t.get("timestamp", 0))
    clusters = []
    current_cluster = [sorted_trades[0]]

    for i in range(1, len(sorted_trades)):
        t_prev = sorted_trades[i - 1].get("timestamp", 0)
        t_curr = sorted_trades[i].get("timestamp", 0)
        diff = t_curr - t_prev
        threshold = 60000 if t_curr > 1e12 else 60  # 60 seconds

        if diff < threshold:
            current_cluster.append(sorted_trades[i])
        else:
            if len(current_cluster) >= 3:
                clusters.append({
                    "size": len(current_cluster),
                    "duration_sec": round((current_cluster[-1].get("timestamp", 0) -
                                          current_cluster[0].get("timestamp", 0)) /
                                         (1000 if t_curr > 1e12 else 1)),
                    "markets_involved": len(set(t.get("title", "") for t in current_cluster)),
                    "timestamp": ts_to_dt(current_cluster[0].get("timestamp", 0)).isoformat(),
                })
            current_cluster = [sorted_trades[i]]

    # Handle last cluster
    if len(current_cluster) >= 3:
        t0 = current_cluster[0].get("timestamp", 0)
        clusters.append({
            "size": len(current_cluster),
            "duration_sec": round((current_cluster[-1].get("timestamp", 0) - t0) /
                                 (1000 if t0 > 1e12 else 1)),
            "markets_involved": len(set(t.get("title", "") for t in current_cluster)),
            "timestamp": ts_to_dt(t0).isoformat(),
        })

    return {
        "total_clusters": len(clusters),
        "avg_cluster_size": round(statistics.mean(c["size"] for c in clusters), 1) if clusters else 0,
        "max_cluster_size": max((c["size"] for c in clusters), default=0),
        "recent_clusters": clusters[-10:] if clusters else [],
    }


def categorize_markets(event_slugs: list) -> dict:
    """Categorize markets by keyword matching on slugs."""
    categories = defaultdict(int)
    keywords = {
        "crypto": ["bitcoin", "btc", "eth", "ethereum", "crypto", "sol", "solana",
                    "xrp", "doge", "ada", "bnb", "token", "coin", "defi", "nft"],
        "politics": ["trump", "biden", "election", "president", "congress", "senate",
                      "governor", "democrat", "republican", "gop", "vote", "poll"],
        "sports": ["nfl", "nba", "mlb", "nhl", "soccer", "football", "game",
                    "championship", "super-bowl", "world-cup", "match"],
        "economics": ["fed", "interest-rate", "inflation", "gdp", "unemployment",
                       "recession", "stock", "s-p-500", "nasdaq", "dow"],
        "weather": ["temperature", "weather", "hurricane", "storm", "climate"],
        "tech": ["ai", "openai", "google", "apple", "meta", "microsoft", "tesla"],
        "entertainment": ["oscar", "grammy", "movie", "box-office", "streaming"],
    }

    for slug in event_slugs:
        slug_lower = slug.lower()
        matched = False
        for category, kws in keywords.items():
            if any(kw in slug_lower for kw in kws):
                categories[category] += 1
                matched = True
                break
        if not matched:
            categories["other"] += 1

    total = sum(categories.values())
    return {
        "counts": dict(categories),
        "percentages": {k: round(v / total * 100, 1) for k, v in categories.items()} if total else {},
    }


def generate_strategy_profile(analysis: dict) -> dict:
    """
    Synthesize patterns into a strategy profile that can be used to configure
    a trading bot on Kalshi.
    """
    profile = {
        "strategy_type": "unknown",
        "confidence": "low",
        "key_parameters": {},
        "recommendations_for_kalshi": [],
    }

    # Determine primary strategy
    arb = analysis.get("arbitrage_analysis", {})
    price_dist = analysis.get("price_distribution", {})
    clustering = analysis.get("trade_clustering", {})
    categories = analysis.get("market_categories", {})

    arb_count = arb.get("suspected_arb_trades", 0)
    total = analysis.get("total_trades", 1)

    if arb_count > total * 0.1:
        profile["strategy_type"] = "arbitrage_primary"
        profile["confidence"] = "high"
        profile["key_parameters"]["avg_spread_target"] = arb.get("avg_arb_spread")
        profile["key_parameters"]["execution_speed_required"] = "sub-second"
        profile["recommendations_for_kalshi"] = [
            "Look for mispricings between Kalshi YES + NO prices summing to < $1.00",
            "Monitor new/illiquid markets where pricing inefficiency is highest",
            "Focus on markets with thin order books and wide bid-ask spreads",
            "Need fast execution — use WebSocket feeds for real-time orderbook data",
            "Kalshi fee structure may eat into thin arbitrage margins — calculate net profit per trade",
        ]
    else:
        # Check if directional trading
        buy_ratio = analysis.get("buy_sell_ratio", 1)
        if buy_ratio > 2:
            profile["strategy_type"] = "directional_long_bias"
        elif buy_ratio < 0.5:
            profile["strategy_type"] = "directional_short_bias"
        else:
            profile["strategy_type"] = "mixed_market_making"

        profile["confidence"] = "medium"
        profile["recommendations_for_kalshi"] = [
            "Replicate market selection patterns using category weights",
            "Use similar entry price ranges for position sizing",
            "Monitor the Polymarket account for changes in category focus",
        ]

    # Price targeting
    if price_dist:
        dominant_range = max(price_dist.items(), key=lambda x: x[1])[0]
        profile["key_parameters"]["dominant_price_range"] = dominant_range

    # Market preferences
    cat_pcts = categories.get("percentages", {})
    if cat_pcts:
        profile["key_parameters"]["market_category_weights"] = cat_pcts

    # Timing
    active_hours = analysis.get("most_active_hours_utc", [])
    if active_hours:
        profile["key_parameters"]["peak_trading_hours_utc"] = [h["hour"] for h in active_hours[:3]]

    # Position sizing
    size_stats = analysis.get("size_stats", {})
    if size_stats:
        profile["key_parameters"]["typical_position_size"] = size_stats.get("median_size")
        profile["key_parameters"]["max_position_size"] = size_stats.get("max_size")

    return profile


if __name__ == "__main__":
    print("=== Analyzing distinct-baguette Trading Patterns ===\n")

    # Load data
    trades = load_json("trades_raw.json")
    if not trades:
        print("No trade data found. Run fetch_trades.py first.")
        exit(1)

    print(f"Loaded {len(trades)} trades\n")

    # Run analysis
    print("Running pattern analysis...")
    analysis = analyze_trades(trades)

    # Generate strategy profile
    print("Generating strategy profile...")
    profile = generate_strategy_profile(analysis)
    analysis["strategy_profile"] = profile

    # Save results
    output_path = os.path.join(OUTPUT_DIR, "pattern_analysis.json")
    with open(output_path, "w") as f:
        json.dump(analysis, f, indent=2, default=str)
    print(f"\nFull analysis saved to {output_path}")

    # Print summary
    print("\n" + "=" * 60)
    print("STRATEGY PROFILE SUMMARY")
    print("=" * 60)
    print(f"Strategy Type:        {profile['strategy_type']}")
    print(f"Confidence:           {profile['confidence']}")
    print(f"\nKey Parameters:")
    for k, v in profile["key_parameters"].items():
        print(f"  {k}: {v}")
    print(f"\nRecommendations for Kalshi:")
    for r in profile["recommendations_for_kalshi"]:
        print(f"  - {r}")

    # Print top-level stats
    print(f"\n{'=' * 60}")
    print("TRADE STATISTICS")
    print(f"{'=' * 60}")
    print(f"Total Trades:         {analysis.get('total_trades')}")
    print(f"Buys / Sells:         {analysis.get('total_buys')} / {analysis.get('total_sells')}")
    print(f"Buy/Sell Ratio:       {analysis.get('buy_sell_ratio')}")
    print(f"Unique Markets:       {analysis.get('unique_markets_traded')}")
    print(f"Active Days:          {analysis.get('active_days')}")
    print(f"Avg Trades/Day:       {analysis.get('avg_trades_per_active_day')}")

    ps = analysis.get("price_stats", {})
    if ps:
        print(f"\nPrice Stats:")
        print(f"  Mean Entry:         {ps.get('mean_entry_price')}")
        print(f"  Median Entry:       {ps.get('median_entry_price')}")
        print(f"  Price Range:        {ps.get('min_price')} - {ps.get('max_price')}")

    arb = analysis.get("arbitrage_analysis", {})
    if arb:
        print(f"\nArbitrage Detection:")
        print(f"  Suspected Arb Trades: {arb.get('suspected_arb_trades')}")
        print(f"  Avg Spread Captured:  {arb.get('avg_arb_spread')}")
        if arb.get("examples"):
            print(f"  Example:")
            ex = arb["examples"][0]
            print(f"    Market: {ex['market']}")
            print(f"    YES @ {ex['yes_price']} + NO @ {ex['no_price']} = {ex['combined']}")
            print(f"    Spread: {ex['spread_captured']}")
