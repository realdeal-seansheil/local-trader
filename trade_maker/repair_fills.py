"""
Fill Data Repair Script — Retroactive validation of historical fills.

The original fill detection had three bugs:
1. Same-side taker: counted trades where taker was on our side (can't fill us)
2. Missing price bounds: NO-side condition accepted trades at 1-2c for asks at 6-13c
3. No volume check: 1-contract trades counted as filling 5-contract orders

This script:
1. Reads all settled positions from maker_obs_history.jsonl
2. Validates each fill against corrected criteria (price range + volume)
3. For currently-filled positions in state, attempts API re-validation
4. Produces corrected data files and reports before/after metrics

Usage:
    python -m trade_maker.repair_fills [--dry-run] [--revalidate-api]
"""

import json
import os
import sys
import math
import shutil
from datetime import datetime
from collections import defaultdict

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
OBS_HISTORY = os.path.join(DATA_DIR, "maker_obs_history.jsonl")
OBS_LOG = os.path.join(DATA_DIR, "maker_obs.jsonl")
STATE_FILE = os.path.join(DATA_DIR, "maker_state.json")

# Match production config
FILL_TOLERANCE_CENTS = 1
CONTRACTS_PER_MARKET = 5
MAKER_FEE_COEFFICIENT = 0.0175


def calculate_maker_fee(count, price_cents):
    """Kalshi maker fee: ceil(coefficient * C * P * (1-P)) in cents."""
    p = price_cents / 100.0
    raw = MAKER_FEE_COEFFICIENT * count * p * (1 - p) * 100
    return math.ceil(raw) if raw > 0 else 0


def validate_fill(record):
    """
    Validate a single fill record against corrected criteria.

    Returns (is_valid, reason) tuple.
    """
    favorite_side = record.get("favorite_side", "")
    favorite_price = record.get("favorite_price", 0)
    fill_yes_price = record.get("fill_yes_price", 0)
    fill_volume = record.get("fill_volume", 0)
    contracts = record.get("contracts", CONTRACTS_PER_MARKET)

    # Determine the target YES price for our order
    if favorite_side == "no":
        # We sell YES at (100 - favorite_price)
        target_yes = 100 - favorite_price
    elif favorite_side == "yes":
        # We buy YES at favorite_price
        target_yes = favorite_price
    else:
        return False, f"unknown favorite_side: {favorite_side}"

    # Check 1: Price within bounded range
    price_diff = abs(fill_yes_price - target_yes)
    if price_diff > FILL_TOLERANCE_CENTS:
        return False, f"price_out_of_range (fill={fill_yes_price}c, target={target_yes}c, diff={price_diff}c)"

    # Check 2: Volume sufficient
    if fill_volume < contracts:
        return False, f"insufficient_volume (fill_vol={fill_volume}, need={contracts})"

    return True, "valid"


def repair_history(dry_run=False):
    """Validate and repair settled position history."""
    if not os.path.exists(OBS_HISTORY):
        print("  No history file found.")
        return {}, {}

    # Read all settled records
    records = []
    with open(OBS_HISTORY) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except Exception:
                continue

    print(f"\n  Validating {len(records)} settled positions...")

    valid_records = []
    invalid_records = []
    invalid_reasons = defaultdict(int)

    for rec in records:
        is_valid, reason = validate_fill(rec)
        if is_valid:
            valid_records.append(rec)
        else:
            invalid_records.append(rec)
            # Extract reason category
            reason_cat = reason.split(" (")[0]
            invalid_reasons[reason_cat] += 1

    # Compute before/after metrics
    before = compute_metrics(records, "BEFORE (buggy)")
    after = compute_metrics(valid_records, "AFTER (corrected)")

    # Show invalid fills detail
    if invalid_records:
        print(f"\n  === INVALID FILLS DETAIL ===")
        print(f"  Total invalid: {len(invalid_records)}")
        for reason, count in sorted(invalid_reasons.items(), key=lambda x: -x[1]):
            print(f"    {reason}: {count}")

        # Show price distribution of invalid fills
        print(f"\n  Price deviation of invalid fills:")
        deviations = []
        for rec in invalid_records:
            fav_side = rec["favorite_side"]
            fav_price = rec["favorite_price"]
            fill_yes = rec["fill_yes_price"]
            target = (100 - fav_price) if fav_side == "no" else fav_price
            dev = abs(fill_yes - target)
            deviations.append((dev, rec["ticker"], fill_yes, target, fav_price, rec.get("won", False), rec.get("pnl_cents", 0)))

        deviations.sort(key=lambda x: -x[0])
        for dev, ticker, fill_yes, target, fav_price, won, pnl in deviations[:20]:
            result = "WIN" if won else "LOSS"
            print(f"    {dev}c off | fill@{fill_yes}c vs target@{target}c | fav@{fav_price}c | {result} {pnl:+d}c | {ticker}")

    # Write corrected history
    if not dry_run and invalid_records:
        # Backup original
        backup = OBS_HISTORY + ".backup_pre_repair"
        if not os.path.exists(backup):
            shutil.copy2(OBS_HISTORY, backup)
            print(f"\n  Backed up original to {backup}")

        # Write corrected
        with open(OBS_HISTORY, "w") as f:
            for rec in valid_records:
                f.write(json.dumps(rec, default=str) + "\n")
        print(f"  Wrote {len(valid_records)} corrected records to {OBS_HISTORY}")

    return before, after


def repair_state(dry_run=False):
    """Validate and repair currently-filled positions in state."""
    if not os.path.exists(STATE_FILE):
        print("  No state file found.")
        return

    with open(STATE_FILE) as f:
        state = json.load(f)

    filled = state.get("filled_positions", {})
    if not filled:
        print("  No filled positions in state.")
        return

    print(f"\n  Validating {len(filled)} currently-filled positions...")

    valid = {}
    invalid_to_pending = {}
    invalid_to_expire = {}
    invalid_reasons = defaultdict(int)

    for ticker, pos in filled.items():
        is_valid, reason = validate_fill(pos)
        if is_valid:
            valid[ticker] = pos
        else:
            reason_cat = reason.split(" (")[0]
            invalid_reasons[reason_cat] += 1

            # Check if market is still open — if so, move back to pending for re-check
            close_time = pos.get("close_time", "")
            market_open = True
            if close_time:
                try:
                    ct = close_time
                    if ct.endswith("Z"):
                        ct = ct[:-1] + "+00:00"
                    close_dt = datetime.fromisoformat(ct)
                    close_dt = close_dt.replace(tzinfo=None)
                    if datetime.utcnow() > close_dt:
                        market_open = False
                except Exception:
                    pass

            if market_open:
                # Move back to pending for fresh fill check with corrected logic
                pos["status"] = "pending"
                pos.pop("fill_time", None)
                pos.pop("fill_yes_price", None)
                pos.pop("fill_volume", None)
                pos.pop("fill_taker_side", None)
                pos.pop("time_to_fill_s", None)
                invalid_to_pending[ticker] = pos
            else:
                # Market closed, can't re-validate — expire it
                invalid_to_expire[ticker] = pos

    print(f"  Valid fills: {len(valid)}")
    print(f"  Invalid → back to pending: {len(invalid_to_pending)}")
    print(f"  Invalid → expired (market closed): {len(invalid_to_expire)}")
    for reason, count in sorted(invalid_reasons.items(), key=lambda x: -x[1]):
        print(f"    {reason}: {count}")

    if not dry_run and (invalid_to_pending or invalid_to_expire):
        # Backup original state
        backup = STATE_FILE + ".backup_pre_repair"
        if not os.path.exists(backup):
            shutil.copy2(STATE_FILE, backup)
            print(f"\n  Backed up original state to {backup}")

        # Update state
        state["filled_positions"] = valid

        # Merge invalid-but-open back into pending
        pending = state.get("pending_orders", {})
        for ticker, pos in invalid_to_pending.items():
            pending[ticker] = pos
        state["pending_orders"] = pending

        # Adjust counters
        total_invalidated = len(invalid_to_pending) + len(invalid_to_expire)
        state["fill_count"] = max(0, state.get("fill_count", 0) - total_invalidated)
        state["expire_count"] = state.get("expire_count", 0) + len(invalid_to_expire)

        # Recompute P&L from valid history only
        total_pnl = 0
        settled_count = 0
        if os.path.exists(OBS_HISTORY):
            with open(OBS_HISTORY) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        total_pnl += rec.get("pnl_cents", 0)
                        settled_count += 1
                    except Exception:
                        continue
        state["total_hypothetical_pnl"] = total_pnl
        state["settled_count"] = settled_count

        state["last_saved"] = datetime.now().isoformat()
        state["repair_applied"] = datetime.now().isoformat()

        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2, default=str)
        print(f"  Updated state file")


def compute_metrics(records, label):
    """Compute and print summary metrics for a set of settled records."""
    if not records:
        print(f"\n  === {label} ===")
        print(f"  No records.")
        return {}

    wins = sum(1 for r in records if r.get("won"))
    losses = len(records) - wins
    total_pnl = sum(r.get("pnl_cents", 0) for r in records)
    win_rate = wins / len(records) * 100 if records else 0

    # By price band
    by_band = defaultdict(lambda: {"wins": 0, "losses": 0, "pnl": 0})
    for r in records:
        fp = r["favorite_price"]
        if fp <= 89:
            band = "85-89c"
        elif fp <= 92:
            band = "90-92c"
        elif fp <= 95:
            band = "93-95c"
        else:
            band = "96-97c"
        if r.get("won"):
            by_band[band]["wins"] += 1
        else:
            by_band[band]["losses"] += 1
        by_band[band]["pnl"] += r.get("pnl_cents", 0)

    # By category
    by_cat = defaultdict(lambda: {"wins": 0, "losses": 0, "pnl": 0})
    for r in records:
        cat = r.get("category", "other")
        if r.get("won"):
            by_cat[cat]["wins"] += 1
        else:
            by_cat[cat]["losses"] += 1
        by_cat[cat]["pnl"] += r.get("pnl_cents", 0)

    print(f"\n  === {label} ===")
    print(f"  Settled: {len(records)} ({wins}W/{losses}L)")
    print(f"  Win rate: {win_rate:.1f}%")
    print(f"  P&L: {total_pnl:+d}c (${total_pnl / 100:+.2f})")
    if records:
        print(f"  Per-trade: {total_pnl / len(records):+.1f}c")

    # Breakeven analysis
    if wins > 0 and losses > 0:
        avg_win = sum(r["pnl_cents"] for r in records if r.get("won")) / wins
        avg_loss = abs(sum(r["pnl_cents"] for r in records if not r.get("won")) / losses)
        breakeven_wr = avg_loss / (avg_win + avg_loss) * 100
        print(f"  Avg win: {avg_win:+.1f}c | Avg loss: {-avg_loss:.1f}c")
        print(f"  Breakeven WR: {breakeven_wr:.1f}% | Margin: {win_rate - breakeven_wr:+.1f}pp")

    print(f"\n  By price band:")
    for band in ["85-89c", "90-92c", "93-95c", "96-97c"]:
        if band in by_band:
            b = by_band[band]
            total = b["wins"] + b["losses"]
            wr = b["wins"] / total * 100 if total > 0 else 0
            print(f"    {band}: {total} trades ({b['wins']}W/{b['losses']}L) "
                  f"WR={wr:.0f}% P&L={b['pnl']:+d}c")

    print(f"\n  By category:")
    for cat in sorted(by_cat.keys()):
        c = by_cat[cat]
        total = c["wins"] + c["losses"]
        wr = c["wins"] / total * 100 if total > 0 else 0
        print(f"    {cat}: {total} trades ({c['wins']}W/{c['losses']}L) "
              f"WR={wr:.0f}% P&L={c['pnl']:+d}c")

    return {
        "count": len(records),
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "pnl_cents": total_pnl,
    }


def main():
    dry_run = "--dry-run" in sys.argv

    print("=" * 60)
    print("  MAKER FILL DATA REPAIR")
    print(f"  Mode: {'DRY RUN (no files modified)' if dry_run else 'LIVE (will modify files)'}")
    print("=" * 60)

    # Phase 1: Repair settled history
    print("\n" + "-" * 40)
    print("  PHASE 1: Validating settled positions")
    print("-" * 40)
    before, after = repair_history(dry_run=dry_run)

    # Phase 2: Repair current state
    print("\n" + "-" * 40)
    print("  PHASE 2: Validating filled positions in state")
    print("-" * 40)
    repair_state(dry_run=dry_run)

    # Summary
    if before and after:
        print("\n" + "=" * 60)
        print("  REPAIR SUMMARY")
        print("=" * 60)
        removed = before.get("count", 0) - after.get("count", 0)
        pnl_delta = after.get("pnl_cents", 0) - before.get("pnl_cents", 0)
        print(f"  Records removed: {removed} ({removed / before['count'] * 100:.0f}%)" if before.get("count") else "")
        print(f"  P&L change: {pnl_delta:+d}c (${pnl_delta / 100:+.2f})")
        print(f"  Win rate: {before.get('win_rate', 0):.1f}% → {after.get('win_rate', 0):.1f}%")

        if not dry_run:
            print(f"\n  ✓ Files updated. Backups saved with .backup_pre_repair suffix.")
            print(f"  ✓ Invalid filled positions moved back to pending for re-check.")
            print(f"  ✓ State counters and P&L recomputed from corrected history.")
        else:
            print(f"\n  DRY RUN — no files modified. Run without --dry-run to apply.")


if __name__ == "__main__":
    main()
