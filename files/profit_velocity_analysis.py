#!/usr/bin/env python3
"""
Profit Velocity Analysis - Current Performance vs $20-30/hr Target
"""

import json
import os
from datetime import datetime, timedelta

def analyze_profit_velocity():
    print("=" * 80)
    print("📊 PROFIT VELOCITY ANALYSIS")
    print("🎯 Target: $20-30 per hour")
    print("=" * 80)
    
    # Load balance data
    with open('data/48hour_trading.jsonl', 'r') as f:
        logs = [json.loads(line) for line in f]
    
    balance_logs = [log for log in logs if log['type'] == 'balance_check' and 'total_balance' in log['data']]
    
    if len(balance_logs) < 2:
        print("❌ Not enough balance data")
        return
    
    # Get first and last balance
    first_balance = balance_logs[0]['data']['total_balance'] / 100
    last_balance = balance_logs[-1]['data']['total_balance'] / 100
    
    # Calculate time period
    first_time = datetime.fromisoformat(balance_logs[0]['timestamp'].replace('Z', '+00:00'))
    last_time = datetime.fromisoformat(balance_logs[-1]['timestamp'].replace('Z', '+00:00'))
    time_period = last_time - first_time
    
    # Calculate profit
    total_profit = last_balance - first_balance
    hours = time_period.total_seconds() / 3600
    current_velocity = total_profit / hours if hours > 0 else 0
    
    print(f"\n📈 CURRENT PERFORMANCE")
    print("-" * 50)
    print(f"💰 Starting Balance: ${first_balance:.2f}")
    print(f"💰 Current Balance: ${last_balance:.2f}")
    print(f"📊 Total Profit: ${total_profit:+.2f}")
    print(f"⏰ Time Period: {hours:.1f} hours")
    print(f"🚀 Current Velocity: ${current_velocity:.2f}/hour")
    
    print(f"\n🎯 TARGET ANALYSIS")
    print("-" * 50)
    print(f"🎯 Target Velocity: $20-30/hour")
    print(f"📊 Current vs Target: {current_velocity/25*100:.1f}% of target")
    
    if current_velocity < 20:
        gap_needed = 20 - current_velocity
        print(f"📈 Gap to Minimum Target: ${gap_needed:.2f}/hour")
        print(f"📊 Improvement Needed: {gap_needed/current_velocity*100:.1f}% increase")
    
    print(f"\n🔍 STRATEGY ANALYSIS")
    print("-" * 50)
    
    # Analyze execution logs
    execution_logs = [log for log in logs if log['type'] == 'execution_success']
    total_trades = len(execution_logs)
    
    print(f"📊 Total Trades Placed: {total_trades}")
    print(f"📈 Trades per Hour: {total_trades/hours:.1f}")
    
    if total_trades > 0:
        avg_profit_per_trade = total_profit / total_trades
        print(f"💰 Avg Profit per Trade: ${avg_profit_per_trade:.2f}")
        print(f"📊 Trades Needed for $25/hr: {25/avg_profit_per_trade:.1f} trades/hour")
    
    print(f"\n🚀 VELOCITY BOOST STRATEGIES")
    print("-" * 50)
    
    print(f"1. 📈 INCREASE TRADE FREQUENCY")
    print(f"   • Current: {total_trades/hours:.1f} trades/hour")
    print(f"   • Target: {25/avg_profit_per_trade:.1f} trades/hour")
    print(f"   • Need: {25/avg_profit_per_trade/(total_trades/hours):.1f}x more trades")
    
    print(f"\n2. 💰 INCREASE PROFIT PER TRADE")
    print(f"   • Current: ${avg_profit_per_trade:.2f} per trade")
    print(f"   • Target: ${25/(total_trades/hours):.2f} per trade")
    print(f"   • Need: {25/(total_trades/hours)/avg_profit_per_trade:.1f}x more profit per trade")
    
    print(f"\n3. 🎯 OPTIMIZE ORDER PRICING")
    print(f"   • Current: 1 cent orders (slow fills)")
    print(f"   • Option A: 3-5 cent orders (faster fills, lower profit)")
    print(f"   • Option B: Market-based pricing (realistic fills)")
    print(f"   • Option C: Hybrid approach (mix of prices)")
    
    print(f"\n4. ⚡ REDUCE SCAN INTERVAL")
    print(f"   • Current: 30 seconds")
    print(f"   • Option: 15-20 seconds")
    print(f"   • Impact: 1.5-2x more opportunities")
    
    print(f"\n5. 📊 EXPAND MARKET COVERAGE")
    print(f"   • Current: 27-32 markets")
    print(f"   • Option: Add more markets")
    print(f"   • Impact: More opportunities per scan")
    
    print(f"\n🎯 RECOMMENDED STRATEGY FOR $20-30/hr")
    print("-" * 50)
    
    if current_velocity < 5:
        print(f"📈 PRIORITY 1: Increase Order Prices")
        print(f"   • Try 3-5 cent orders instead of 1 cent")
        print(f"   • Accept $3-5 profit per trade vs $9.80")
        print(f"   • Get actual fills instead of pending orders")
        
    elif current_velocity < 15:
        print(f"📈 PRIORITY 1: Increase Trade Frequency")
        print(f"   • Reduce scan interval to 15 seconds")
        print(f"   • Add more markets to scan")
        print(f"   • Increase position size if possible")
        
    else:
        print(f"📈 PRIORITY 1: Optimize Profit Margins")
        print(f"   • Fine-tune order pricing")
        print(f"   • Focus on highest-probability fills")
        print(f"   • Scale up position sizes")
    
    print(f"\n📊 SPECIFIC RECOMMENDATIONS")
    print("-" * 50)
    
    print(f"🎯 IMMEDIATE ACTIONS:")
    print(f"1. Change order price from 1 cent to 3 cents")
    print(f"2. Reduce scan interval from 30s to 20s")
    print(f"3. Increase position size from 10 to 15 contracts")
    print(f"4. Add 10 more markets to scan")
    
    print(f"\n💰 EXPECTED IMPACT:")
    print(f"• Fill rate: 0% → 60-80%")
    print(f"• Profit per trade: $9.80 → $5.80")
    print(f"• Trades per hour: {total_trades/hours:.1f} → {total_trades/hours*2:.1f}")
    print(f"• Velocity: ${current_velocity:.2f}/hr → ${current_velocity*3:.2f}/hr")
    
    print(f"\n🎯 CONCLUSION")
    print("-" * 50)
    
    if current_velocity >= 20:
        print(f"✅ TARGET MET: ${current_velocity:.2f}/hr")
    elif current_velocity >= 10:
        print(f"📈 GETTING CLOSE: ${current_velocity:.2f}/hr (need {20-current_velocity:.1f} more)")
    else:
        print(f"⚡ NEEDS WORK: ${current_velocity:.2f}/hr (need {20-current_velocity:.1f} more)")
    
    print(f"\n💡 The key is getting actual fills rather than pending orders.")
    print(f"🎯 Better to have $5 profit at 80% fill rate than $10 at 0% fill rate.")

if __name__ == "__main__":
    analyze_profit_velocity()
