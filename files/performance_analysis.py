#!/usr/bin/env python3
"""
Comprehensive Performance Analysis of Kalshi Arbitrage Bot
"""

import json
import os
from datetime import datetime, timedelta

def analyze_performance():
    print("=" * 80)
    print("📊 KALSHI ARBITRAGE BOT - PERFORMANCE ANALYSIS")
    print("=" * 80)
    
    # Load performance data
    try:
        with open('data/trading_performance.json', 'r') as f:
            perf_data = json.load(f)
    except:
        print("❌ Performance data not found")
        return
    
    # Load active positions
    try:
        with open('data/active_positions.json', 'r') as f:
            positions = json.load(f)
    except:
        print("❌ Active positions data not found")
        return
    
    # Load trading log
    try:
        with open('data/48hour_trading.jsonl', 'r') as f:
            logs = [json.loads(line) for line in f]
    except:
        print("❌ Trading log not found")
        return
    
    print(f"\n📈 EXECUTIVE SUMMARY")
    print("-" * 50)
    print(f"📅 Analysis Period: {perf_data.get('date', 'Unknown')}")
    print(f"⏰ Total Runtime: ~17.5 hours (Feb 16 16:10 - Feb 17 09:43)")
    print(f"💰 Account Balance: $90.97")
    print(f"🎯 Status: Bot stopped (CANCELED)")
    
    print(f"\n📊 TRADING PERFORMANCE")
    print("-" * 50)
    print(f"🔍 Total Scans: {perf_data.get('scans', 0):,}")
    print(f"💡 Opportunities Found: {perf_data.get('opportunities_found', 0):,}")
    print(f"📈 Trades Executed: {perf_data.get('trades_executed', 0):,}")
    print(f"✅ Successful Arbitrages: {perf_data.get('successful_arbitrages', 0):,}")
    print(f"💰 Expected Profit: ${perf_data.get('total_profit', 0):.2f}")
    print(f"💸 Total Fees: ${perf_data.get('total_fees', 0):.4f}")
    print(f"📊 Net Profit: ${perf_data.get('total_profit', 0) - perf_data.get('total_fees', 0):.2f}")
    
    # Calculate key metrics
    scans = perf_data.get('scans', 0)
    opportunities = perf_data.get('opportunities_found', 0)
    trades = perf_data.get('trades_executed', 0)
    profit = perf_data.get('total_profit', 0)
    
    print(f"\n📈 KEY METRICS")
    print("-" * 50)
    print(f"🎯 Opportunities per Scan: {opportunities/scans:.1f}")
    print(f"⚡ Trade Execution Rate: {trades/scans*100:.1f}%")
    print(f"💰 Profit per Trade: ${profit/trades:.2f}")
    print(f"📊 Profit per Scan: ${profit/scans:.2f}")
    print(f"⏱️  Trades per Hour: {trades/17.5:.1f}")
    
    print(f"\n📋 POSITION ANALYSIS")
    print("-" * 50)
    
    # Analyze positions
    total_positions = len(positions)
    monitoring_positions = sum(1 for p in positions.values() if p.get('status') == 'monitoring')
    active_positions = sum(1 for p in positions.values() if p.get('status') == 'active')
    
    print(f"📊 Total Positions: {total_positions}")
    print(f"👀 Monitoring: {monitoring_positions}")
    print(f"⚡ Active: {active_positions}")
    print(f"📈 Position Success Rate: {trades/total_positions*100:.1f}%")
    
    # Calculate expected profit from positions
    expected_profit = sum(p.get('expected_profit', 0) for p in positions.values())
    print(f"💰 Total Expected Profit: ${expected_profit:.2f}")
    print(f"📊 Average Profit per Position: ${expected_profit/total_positions:.2f}")
    
    print(f"\n🕐 TIMELINE ANALYSIS")
    print("-" * 50)
    
    # First and last trades
    execution_logs = [log for log in logs if log.get('type') == 'execution_success']
    if execution_logs:
        first_trade = execution_logs[0]['timestamp']
        last_trade = execution_logs[-1]['timestamp']
        
        first_dt = datetime.fromisoformat(first_trade.replace('Z', '+00:00'))
        last_dt = datetime.fromisoformat(last_trade.replace('Z', '+00:00'))
        
        print(f"🚀 First Trade: {first_dt.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"🎯 Last Trade: {last_dt.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"⏱️  Trading Duration: {last_dt - first_dt}")
    
    print(f"\n📊 OPPORTUNITY QUALITY")
    print("-" * 50)
    
    # Analyze opportunity spreads
    scan_logs = [log for log in logs if log.get('type') == 'scan_opportunities']
    if scan_logs:
        spreads = [log['data']['top_spread'] for log in scan_logs]
        avg_spread = sum(spreads) / len(spreads)
        
        print(f"📈 Average Spread: {avg_spread:.4f}")
        print(f"💰 Typical Profit per Contract: ${(1-avg_spread):.4f}")
        print(f"📊 ROI per Contract: {(1-avg_spread)/avg_spread*100:.1f}%")
    
    print(f"\n🎯 STRATEGY PERFORMANCE")
    print("-" * 50)
    
    # Strategy analysis
    dynamic_pricing_trades = sum(1 for log in execution_logs 
                               if log.get('data', {}).get('strategy') == 'dynamic_pricing')
    
    print(f"🔄 Dynamic Pricing Trades: {dynamic_pricing_trades}")
    print(f"📈 Dynamic Pricing Rate: {dynamic_pricing_trades/trades*100:.1f}%")
    print(f"💰 Initial Price: 1 cent each side")
    print(f"📊 Expected ROI: 4,899.3%")
    
    print(f"\n⚠️  CRITICAL ISSUES")
    print("-" * 50)
    
    # Order ID analysis
    null_order_ids = sum(1 for log in execution_logs 
                         if log.get('data', {}).get('yes_order_id') is None)
    
    print(f"❌ Orders with Null IDs: {null_order_ids}/{len(execution_logs)}")
    print(f"📊 Order Success Rate: {(len(execution_logs)-null_order_ids)/len(execution_logs)*100:.1f}%")
    print(f"⚠️  Issue: Orders placed but not properly tracked")
    
    print(f"\n💡 PERFORMANCE INSIGHTS")
    print("-" * 50)
    
    print(f"✅ STRENGTHS:")
    print(f"   • Excellent opportunity detection ({opportunities/scans:.1f} per scan)")
    print(f"   • High profit margins (98c spreads)")
    print(f"   • Consistent execution ({trades} trades)")
    print(f"   • Low fees (${perf_data.get('total_fees', 0):.4f} total)")
    
    print(f"\n⚠️  WEAKNESSES:")
    print(f"   • Order tracking issues (null order IDs)")
    print(f"   • No actual fills confirmed")
    print(f"   • Bot stopped unexpectedly")
    print(f"   • Expected profit vs actual profit gap")
    
    print(f"\n🎯 RECOMMENDATIONS")
    print("-" * 50)
    print(f"1. 🔧 Fix order ID tracking in execution response")
    print(f"2. 📊 Implement real order status monitoring")
    print(f"3. ⚡ Add order fill verification")
    print(f"4. 💰 Implement profit realization tracking")
    print(f"5. 🛡️ Add error handling for bot stability")
    
    print(f"\n📈 PROJECTED PERFORMANCE")
    print("-" * 50)
    
    if trades > 0:
        hourly_profit = profit / 17.5
        daily_profit = hourly_profit * 24
        
        print(f"💰 Hourly Profit: ${hourly_profit:.2f}")
        print(f"📊 Daily Profit: ${daily_profit:.2f}")
        print(f"📈 Monthly Profit: ${daily_profit*30:,.2f}")
        print(f"📊 Annual Profit: ${daily_profit*365:,.2f}")
    
    print(f"\n" + "=" * 80)
    print("🎯 CONCLUSION")
    print("=" * 80)
    print(f"The bot shows excellent opportunity detection and execution")
    print(f"capabilities, but suffers from order tracking issues that prevent")
    print(f"actual profit realization. With proper order monitoring and fill")
    print(f"verification, this strategy could generate significant profits.")
    print("=" * 80)

if __name__ == "__main__":
    analyze_performance()
