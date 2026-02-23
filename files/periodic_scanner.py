#!/usr/bin/env python3
"""
Periodic Arbitrage Scanner
Runs continuously and executes trades when opportunities are found.
"""

import time
import json
import os
from datetime import datetime
from kalshi_executor import KalshiAuth, KalshiClient, StrategyExecutor
from kalshi_executor import KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH, USE_DEMO

# Configuration
SCAN_INTERVAL = 60  # seconds between scans
AUTO_EXECUTE = False  # Set to True to auto-execute (USE WITH CAUTION)
MAX_CONTRACTS_PER_TRADE = 10  # Position size for execution
LOG_FILE = "data/periodic_scan.jsonl"

def log_event(event_type, data):
    """Log scan events."""
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    entry = {
        "timestamp": datetime.now().isoformat(),
        "type": event_type,
        "data": data
    }
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")

def check_portfolio_balance(client):
    """Check available portfolio balance."""
    try:
        balance = client.get_balance()
        available = balance.get("available", 0)
        log_event("balance_check", {"available": available})
        return available
    except Exception as e:
        log_event("balance_error", {"error": str(e)})
        return 0

def execute_opportunity(executor, opportunity, available_balance):
    """Execute an arbitrage opportunity."""
    ticker = opportunity["ticker"]
    spread = opportunity["spread"]
    
    # Calculate position size based on available balance
    max_affordable = int(available_balance * 100)  # Convert to cents
    contracts = min(MAX_CONTRACTS_PER_TRADE, max_affordable)
    
    if contracts <= 0:
        log_event("execution_skipped", {
            "ticker": ticker,
            "reason": "insufficient_balance",
            "available": available_balance
        })
        return None
    
    print(f"\n🚀 Executing arbitrage on {ticker}")
    print(f"   Spread: {spread} | Contracts: {contracts}")
    print(f"   Expected profit: ${spread * contracts:.2f}")
    
    try:
        result = executor.execute_arb(ticker, contracts)
        
        if "error" in result:
            log_event("execution_failed", {
                "ticker": ticker,
                "error": result["error"]
            })
            print(f"❌ Execution failed: {result['error']}")
        else:
            log_event("execution_success", {
                "ticker": ticker,
                "result": result
            })
            print(f"✅ Execution successful!")
            print(f"   YES order: {result.get('yes_order', {}).get('id', 'N/A')}")
            print(f"   NO order: {result.get('no_order', {}).get('id', 'N/A')}")
            
            # Display fee-aware results
            execution_summary = result.get('execution_summary', {})
            if execution_summary:
                print(f"   Gross profit per contract: ${execution_summary.get('gross_profit_per_contract', 0):.4f}")
                print(f"   Net profit per contract: ${execution_summary.get('net_profit_per_contract', 0):.4f}")
                print(f"   Total fees: ${execution_summary.get('total_fees', 0):.4f}")
                print(f"   Net ROI: {execution_summary.get('net_roi_percent', 0):.1f}%")
                print(f"   Total expected profit: ${execution_summary.get('total_expected_profit', 0):.2f}")
            else:
                # Fallback for old format
                print(f"   Expected profit: ${result.get('total_expected_profit', 0):.2f}")
        
        return result
        
    except Exception as e:
        log_event("execution_error", {
            "ticker": ticker,
            "error": str(e)
        })
        print(f"❌ Execution error: {e}")
        return None

def main():
    print("=" * 60)
    print("🔄 PERIODIC ARBITRAGE SCANNER")
    print("=" * 60)
    print(f"Mode: {'DEMO' if USE_DEMO else 'LIVE'}")
    print(f"Scan interval: {SCAN_INTERVAL}s")
    print(f"Auto-execute: {'ENABLED' if AUTO_EXECUTE else 'DISABLED'}")
    print(f"Max contracts per trade: {MAX_CONTRACTS_PER_TRADE}")
    print("\nPress Ctrl+C to stop\n")
    
    # Initialize
    auth = KalshiAuth(KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH)
    client = KalshiClient(auth)
    executor = StrategyExecutor(client)
    
    scan_count = 0
    
    try:
        while True:
            scan_count += 1
            timestamp = datetime.now().strftime("%H:%M:%S")
            print(f"[{timestamp}] Scan #{scan_count}...")
            
            try:
                # Check portfolio balance
                available_balance = check_portfolio_balance(client)
                
                # Find opportunities
                opportunities = executor.find_arb_opportunities()
                
                log_event("scan_completed", {
                    "scan_number": scan_count,
                    "opportunities_found": len(opportunities),
                    "available_balance": available_balance
                })
                
                if opportunities:
                    print(f"   Found {len(opportunities)} opportunities")
                    
                    # Show top 3 with fee information
                    for i, opp in enumerate(opportunities[:3]):
                        spread = opp.get('spread', 0)
                        net_profit = opp.get('net_profit_per_contract', 0)
                        fees = opp.get('total_fees_per_contract', 0)
                        roi = opp.get('roi_net_percent', 0)
                        
                        print(f"   {i+1}. {opp['ticker']}: {spread} spread")
                        print(f"      Net profit: ${net_profit:.4f} | Fees: ${fees:.4f} | ROI: {roi:.1f}%")
                    
                    # Auto-execute best opportunity if enabled
                    if AUTO_EXECUTE and opportunities:
                        best = opportunities[0]
                        # Check if profitable after fees (already filtered)
                        if best.get('net_profit_per_contract', 0) > 0.01:  # At least 1 cent profit
                            execute_opportunity(executor, best, available_balance)
                        else:
                            print(f'   Net profit too thin (${best.get("net_profit_per_contract", 0):.4f}), skipping execution')
                else:
                    print("   No opportunities found")
                
            except Exception as e:
                print(f"   Scan error: {e}")
                log_event("scan_error", {"error": str(e)})
            
            print(f"   Next scan in {SCAN_INTERVAL}s...", end="\r")
            time.sleep(SCAN_INTERVAL)
            
    except KeyboardInterrupt:
        print(f"\n\n🛑 Scanner stopped after {scan_count} scans")
        log_event("scanner_stopped", {"total_scans": scan_count})

if __name__ == "__main__":
    main()
