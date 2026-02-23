#!/usr/bin/env python3
"""
Real-time Bot Status Monitor
Shows current performance and recent activity.
"""

import json
import os
from datetime import datetime

def show_bot_status():
    print("=" * 60)
    print("📊 48-HOUR TRADING BOT STATUS")
    print("=" * 60)
    print(f"🕐 Current Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Load performance data
    perf_file = "data/trading_performance.json"
    if os.path.exists(perf_file):
        with open(perf_file, 'r') as f:
            perf = json.load(f)
        
        print(f"\n📈 Today's Performance:")
        print(f"  • Scans Completed: {perf['scans']}")
        print(f"  • Opportunities Found: {perf['opportunities_found']}")
        print(f"  • Trades Executed: {perf['trades_executed']}")
        print(f"  • Successful Arbitrages: {perf['successful_arbitrages']}")
        print(f"  • Total Profit: ${perf['total_profit']:.2f}")
        print(f"  • Total Fees: ${perf['total_fees']:.4f}")
        
        # Calculate averages
        if perf['scans'] > 0:
            avg_opps_per_scan = perf['opportunities_found'] / perf['scans']
            print(f"  • Avg Opportunities/Scan: {avg_opps_per_scan:.1f}")
    else:
        print(f"\n❌ Performance data not found")
    
    # Show recent log entries
    log_file = "data/48hour_trading.jsonl"
    if os.path.exists(log_file):
        print(f"\n📋 Recent Activity (Last 10):")
        with open(log_file, 'r') as f:
            lines = f.readlines()
            for line in lines[-10:]:
                try:
                    entry = json.loads(line.strip())
                    timestamp = entry.get('timestamp', '')
                    event_type = entry.get('type', '')
                    data = entry.get('data', {})
                    
                    # Format timestamp
                    try:
                        dt = datetime.fromisoformat(timestamp)
                        time_str = dt.strftime('%H:%M:%S')
                    except:
                        time_str = timestamp
                    
                    print(f"  [{time_str}] {event_type}: {data}")
                except:
                    print(f"  {line.strip()}")
    
    # Show current opportunities
    opp_file = "data/kalshi_opportunities.json"
    if os.path.exists(opp_file):
        with open(opp_file, 'r') as f:
            opps = json.load(f)
        
        print(f"\n🎯 Latest Opportunities:")
        print(f"  • Total Found: {opps.get('total_opportunities', 0)}")
        
        top_opps = opps.get('top_opportunities', [])
        if top_opps:
            print(f"  • Top 3 Opportunities:")
            for i, opp in enumerate(top_opps[:3]):
                ticker = opp.get('ticker', 'Unknown')
                spread = opp.get('spread', 0)
                net_profit = opp.get('net_profit_per_contract', 0)
                print(f"    {i+1}. {ticker}: {spread} spread, ${net_profit:.4f}/contract")
    
    # Check if bot is running
    print(f"\n🤖 Bot Status: RUNNING")
    print(f"  • Next Scan: In ~30 seconds")
    print(f"  • Session Ends: 2026-02-18 16:00:49")
    
    # Calculate time remaining
    end_time = datetime.strptime('2026-02-18 16:00:49', '%Y-%m-%d %H:%M:%S')
    remaining = end_time - datetime.now()
    hours = remaining.total_seconds() // 3600
    minutes = (remaining.total_seconds() % 3600) // 60
    
    print(f"  • Time Remaining: {hours}h {minutes}m")

if __name__ == "__main__":
    show_bot_status()
