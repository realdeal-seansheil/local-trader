#!/usr/bin/env python3
"""
Monitor-Only Trading Bot
Scans opportunities continuously without executing trades.
Perfect for monitoring while fixing API authentication.
"""

import time
import json
import os
from datetime import datetime
from kalshi_executor import KalshiAuth, KalshiClient, StrategyExecutor

# Configuration
SCAN_INTERVAL = 30  # seconds between scans
LOG_FILE = "data/monitor_only_log.jsonl"
PERFORMANCE_FILE = "data/monitor_performance.json"

def log_event(event_type, data):
    """Log monitoring events."""
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    entry = {
        "timestamp": datetime.now().isoformat(),
        "type": event_type,
        "data": data
    }
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")

def save_performance(stats):
    """Save performance statistics."""
    os.makedirs(os.path.dirname(PERFORMANCE_FILE), exist_ok=True)
    with open(PERFORMANCE_FILE, "w") as f:
        json.dump(stats, f, indent=2, default=str)

def monitor_opportunities():
    """Continuously monitor arbitrage opportunities."""
    print("=" * 60)
    print("👁️  MONITOR-ONLY ARBITRAGE BOT")
    print("=" * 60)
    print("⚠️  SCANNING MODE - NO TRADES WILL BE EXECUTED")
    print("⚡ Scanning every 30 seconds for profitable opportunities")
    print("📊 Logging all opportunities to data/monitor_only_log.jsonl")
    print("=" * 60)
    
    # Initialize client (no auth needed for scanning)
    auth = KalshiAuth('dummy', 'dummy')
    client = KalshiClient(auth)
    executor = StrategyExecutor(client)
    
    # Performance tracking
    stats = {
        "start_time": datetime.now().isoformat(),
        "scans": 0,
        "total_opportunities": 0,
        "best_opportunities": [],
        "avg_spread": 0,
        "avg_profit_per_contract": 0
    }
    
    scan_count = 0
    all_opportunities = []
    
    try:
        while True:
            scan_count += 1
            stats["scans"] += 1
            
            timestamp = datetime.now().strftime("%H:%M:%S")
            print(f"[{timestamp}] Scan #{scan_count}...", end="\r")
            
            try:
                # Find opportunities
                opportunities = executor.find_arb_opportunities()
                
                if opportunities:
                    stats["total_opportunities"] += len(opportunities)
                    all_opportunities.extend(opportunities)
                    
                    # Log best opportunity
                    best = opportunities[0]
                    log_event("opportunity_found", {
                        "scan_number": scan_count,
                        "count": len(opportunities),
                        "best_ticker": best["ticker"],
                        "best_spread": best["spread"],
                        "best_net_profit": best.get("net_profit_per_contract", 0),
                        "best_roi": best.get("roi_net_percent", 0)
                    })
                    
                    # Update stats
                    spreads = [opp.get("spread", 0) for opp in opportunities]
                    profits = [opp.get("net_profit_per_contract", 0) for opp in opportunities]
                    
                    stats["avg_spread"] = sum(spreads) / len(spreads)
                    stats["avg_profit_per_contract"] = sum(profits) / len(profits)
                    
                    # Keep top 10 best opportunities
                    all_opportunities.sort(key=lambda x: x.get("spread", 0), reverse=True)
                    stats["best_opportunities"] = all_opportunities[:10]
                    
                    print(f"\n🎯 Scan #{scan_count}: Found {len(opportunities)} opportunities")
                    print(f"   Best: {best['ticker']} - {best['spread']} spread")
                    print(f"   Net profit: ${best.get('net_profit_per_contract', 0):.4f} per contract")
                    print(f"   ROI: {best.get('roi_net_percent', 0):.1f}%")
                    
                else:
                    print(f"\n📊 Scan #{scan_count}: No profitable opportunities found")
                
                # Save performance every 10 scans
                if scan_count % 10 == 0:
                    save_performance(stats)
                    print(f"💾 Performance saved ({scan_count} scans)")
                
            except Exception as e:
                log_event("scan_error", {"scan_number": scan_count, "error": str(e)})
                print(f"\n❌ Scan error: {e}")
            
            # Wait for next scan
            time.sleep(SCAN_INTERVAL)
            
    except KeyboardInterrupt:
        print(f"\n\n🛑 Monitoring stopped by user")
        
        # Final summary
        elapsed = datetime.now() - datetime.fromisoformat(stats["start_time"])
        print(f"\n📊 MONITORING SUMMARY")
        print(f"⏰  Duration: {str(elapsed).split('.')[0]}")
        print(f"🔍  Total scans: {stats['scans']}")
        print(f"🎯  Total opportunities: {stats['total_opportunities']}")
        print(f"💰  Average spread: {stats['avg_spread']:.4f}")
        print(f"💵  Avg profit per contract: ${stats['avg_profit_per_contract']:.4f}")
        
        if stats["best_opportunities"]:
            print(f"\n🏆 TOP 5 OPPORTUNITIES SEEN:")
            for i, opp in enumerate(stats["best_opportunities"][:5]):
                print(f"   {i+1}. {opp['ticker']}: {opp['spread']} spread")
                print(f"      Net profit: ${opp.get('net_profit_per_contract', 0):.4f}")
        
        save_performance(stats)
        print(f"\n💾 Data saved to {PERFORMANCE_FILE}")

if __name__ == "__main__":
    monitor_opportunities()
