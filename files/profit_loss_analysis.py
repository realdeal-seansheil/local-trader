#!/usr/bin/env python3
"""
Profit/Loss Analysis - Why Positions Are Losing Money
"""

import json
import os
from datetime import datetime

def analyze_profit_loss():
    print("=" * 80)
    print("🔍 PROFIT/LOSS ANALYSIS - POSITION PERFORMANCE")
    print("❌ WHY ARE WE LOSING MONEY?")
    print("=" * 80)
    
    # Load trading data
    with open('data/48hour_trading.jsonl', 'r') as f:
        logs = [json.loads(line) for line in f]
    
    print(f"\n💰 BALANCE ANALYSIS")
    print("-" * 50)
    
    # Get balance progression
    balance_logs = [log for log in logs if log['type'] == 'balance_check' and 'total_balance' in log['data']]
    
    if balance_logs:
        # Get key balance points
        start_balance = balance_logs[0]['data']['total_balance'] / 100
        max_balance = max(log['data']['total_balance'] / 100 for log in balance_logs)
        current_balance = balance_logs[-1]['data']['total_balance'] / 100
        
        print(f"📊 Start Balance: ${start_balance:.2f}")
        print(f"📈 Peak Balance: ${max_balance:.2f}")
        print(f"💰 Current Balance: ${current_balance:.2f}")
        print(f"📉 Total Loss: ${start_balance - current_balance:.2f}")
        print(f"📈 Peak Profit: ${max_balance - start_balance:.2f}")
        print(f"📉 Drawdown: ${max_balance - current_balance:.2f}")
    
    print(f"\n🎯 EXECUTION ANALYSIS")
    print("-" * 50)
    
    # Analyze executions
    execution_logs = [log for log in logs if log['type'] == 'execution_success']
    
    if execution_logs:
        print(f"📊 Total Executions: {len(execution_logs)}")
        
        # Group by price
        price_groups = {}
        for log in execution_logs:
            price = log['data'].get('initial_prices', {}).get('yes', 'unknown')
            if price not in price_groups:
                price_groups[price] = []
            price_groups[price].append(log['data'])
        
        print(f"\n📈 EXECUTIONS BY PRICE:")
        for price, trades in sorted(price_groups.items()):
            total_expected = sum(trade['total_profit'] for trade in trades)
            print(f"   {price}c: {len(trades)} trades, ${total_expected:.2f} expected")
    
    print(f"\n❌ CRITICAL ISSUES IDENTIFIED")
    print("-" * 50)
    
    # Check for problems
    print(f"🔍 ISSUE 1: BALANCE DECLINE")
    if start_balance > current_balance:
        loss_amount = start_balance - current_balance
        loss_percent = loss_amount / start_balance * 100
        print(f"   ❌ Account down ${loss_amount:.2f} ({loss_percent:.1f}%)")
        print(f"   ❌ This indicates actual losses, not just unfilled orders")
    
    print(f"\n🔍 ISSUE 2: EXPECTED vs ACTUAL")
    total_expected_profit = sum(log['data']['total_profit'] for log in execution_logs)
    actual_profit = current_balance - start_balance
    
    print(f"   📊 Total Expected Profit: ${total_expected_profit:.2f}")
    print(f"   💰 Actual Profit/Loss: ${actual_profit:+.2f}")
    print(f"   ❌ Gap: ${total_expected_profit - actual_profit:.2f}")
    
    if actual_profit < 0:
        print(f"   ❌ WE ARE ACTUALLY LOSING MONEY!")
    
    print(f"\n🔍 ISSUE 3: ORDER FILL LOGIC")
    print(f"   📈 Theory: Buy YES at 3c, NO at 3c, profit when market moves")
    print(f"   ❌ Reality: Orders might be filling at unfavorable prices")
    print(f"   ❌ Reality: Market conditions changing between orders")
    print(f"   ❌ Reality: Arbitrage window closing before execution")
    
    print(f"\n🎯 ROOT CAUSE ANALYSIS")
    print("-" * 50)
    
    print(f"❌ PROBLEM 1: ARBITRAGE TIMING")
    print(f"   • Market spreads change quickly")
    print(f"   • Our 3c orders might be filling when spread is < 6c")
    print(f"   • We're paying 3c + 3c = 6c but only getting < 6c spread")
    print(f"   • Result: Loss on each filled arbitrage")
    
    print(f"\n❌ PROBLEM 2: MARKET MAKER PENALTY")
    print(f"   • We're acting as market makers at 3c")
    print(f"   • Market makers pay fees when orders fill")
    print(f"   • Taker fees: 1 cent per contract")
    print(f"   • Our calculations might not include all costs")
    
    print(f"\n❌ PROBLEM 3: PRICE IMPACT")
    print(f"   • Large orders (20 contracts) move market")
    print(f"   • Our orders affect the prices we get")
    print(f"   • Theoretical spread ≠ actual execution spread")
    
    print(f"\n🔧 IMMEDIATE FIXES NEEDED")
    print("-" * 50)
    
    print(f"🎯 FIX 1: VERIFY ACTUAL EXECUTION PRICES")
    print(f"   • Check what prices orders actually fill at")
    print(f"   • Compare fill prices with expected prices")
    print(f"   • Account for all fees and costs")
    
    print(f"\n🎯 FIX 2: SMALLER POSITION SIZES")
    print(f"   • Reduce from 20 to 5 contracts")
    print(f"   • Minimize market impact")
    print(f"   • Test profitability with smaller sizes")
    
    print(f"\n🎯 FIX 3: BETTER MARKET TIMING")
    print(f"   • Only trade when spread > 10c")
    print(f"   • Ensure profit margin after all costs")
    print(f"   • Use market orders for guaranteed execution")
    
    print(f"\n🎯 FIX 4: REAL-TIME PROFIT TRACKING")
    print(f"   • Track actual fill prices")
    print(f"   • Calculate real P&L per trade")
    print(f"   • Stop trading if losses continue")
    
    print(f"\n💡 RECOMMENDATION")
    print("-" + 50)
    
    print(f"🛑 STOP THE BOT IMMEDIATELY")
    print(f"❌ We're losing real money, not just theoretical profit")
    print(f"🔍 Need to debug actual execution vs expected execution")
    print(f"📊 Current strategy is flawed - losing money on each trade")
    
    print(f"\n🎯 NEXT STEPS:")
    print(f"1. 🛑 Stop trading to prevent further losses")
    print(f"2. 🔍 Analyze actual order fill data")
    print(f"3. 💰 Calculate real costs and fees")
    print(f"4. 📈 Fix the arbitrage logic")
    print(f"5. 🧪 Test with small position sizes")

if __name__ == "__main__":
    analyze_profit_loss()
