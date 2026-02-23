#!/usr/bin/env python3
"""
Kalshi Trading Performance Analysis
Analyzes all trading logs and provides performance insights
"""

import json
import os
from datetime import datetime

def analyze_trading_performance():
    print('📊 KALSHI TRADING PERFORMANCE ANALYSIS')
    print('=' * 60)
    
    # Find all trading log files
    log_files = [
        'data/simple_trades_correct.jsonl',
        'data/crypto_arbitrage_trading.jsonl', 
        'data/distinct_baguette_trades.jsonl',
        'data/enhanced_48hour_trading.jsonl',
        'data/simple_trades.jsonl',
        'data/crypto_momentum_trading.jsonl',
        'data/crypto_momentum_trading_fixed.jsonl',
        'data/conservative_48hour_trading.jsonl',
        'data/48hour_trading.jsonl'
    ]
    
    total_stats = {
        'total_trades': 0,
        'successful_trades': 0,
        'failed_trades': 0,
        'total_profit': 0.0,
        'total_fees': 0.0,
        'unique_markets': set(),
        'earliest_trade': None,
        'latest_trade': None,
        'contracts_traded': 0
    }
    
    for log_file in log_files:
        if os.path.exists(log_file):
            print(f'\n📋 Analyzing {log_file}:')
            
            file_stats = {
                'trades': 0,
                'successful': 0,
                'failed': 0,
                'profit': 0.0,
                'fees': 0.0,
                'markets': set(),
                'contracts': 0
            }
            
            try:
                with open(log_file, 'r') as f:
                    for line in f:
                        if line.strip():
                            try:
                                trade = json.loads(line)
                                
                                # Count trades
                                file_stats['trades'] += 1
                                total_stats['total_trades'] += 1
                                
                                # Check success
                                if trade.get('success', False):
                                    file_stats['successful'] += 1
                                    total_stats['successful_trades'] += 1
                                    
                                    # Add profit
                                    profit = trade.get('expected_profit', 0)
                                    file_stats['profit'] += profit
                                    total_stats['total_profit'] += profit
                                    
                                    # Add fees
                                    fees = trade.get('total_fees', 0)
                                    file_stats['fees'] += fees
                                    total_stats['total_fees'] += fees
                                    
                                    # Track contracts
                                    contracts = trade.get('contracts', 0)
                                    file_stats['contracts'] += contracts
                                    total_stats['contracts_traded'] += contracts
                                else:
                                    file_stats['failed'] += 1
                                    total_stats['failed_trades'] += 1
                                
                                # Track markets
                                ticker = trade.get('ticker', 'unknown')
                                file_stats['markets'].add(ticker)
                                total_stats['unique_markets'].add(ticker)
                                
                                # Track time
                                timestamp = trade.get('timestamp', '')
                                if timestamp:
                                    try:
                                        trade_time = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                                        if not total_stats['earliest_trade'] or trade_time < total_stats['earliest_trade']:
                                            total_stats['earliest_trade'] = trade_time
                                        if not total_stats['latest_trade'] or trade_time > total_stats['latest_trade']:
                                            total_stats['latest_trade'] = trade_time
                                    except:
                                        pass
                                
                            except json.JSONDecodeError:
                                continue
                
                # Print file stats
                print(f'   📊 Trades: {file_stats["trades"]}')
                print(f'   ✅ Successful: {file_stats["successful"]}')
                print(f'   ❌ Failed: {file_stats["failed"]}')
                print(f'   💰 Profit: ${file_stats["profit"]:.2f}')
                print(f'   💸 Fees: ${file_stats["fees"]:.4f}')
                print(f'   📈 Contracts: {file_stats["contracts"]}')
                print(f'   🎯 Markets: {len(file_stats["markets"])}')
                
                if file_stats['trades'] > 0:
                    success_rate = file_stats['successful'] / file_stats['trades'] * 100
                    avg_profit = file_stats['profit'] / file_stats['successful'] if file_stats['successful'] > 0 else 0
                    print(f'   📈 Success rate: {success_rate:.1f}%')
                    print(f'   💰 Avg profit per trade: ${avg_profit:.2f}')
            
            except Exception as e:
                print(f'   ❌ Error reading file: {e}')
        else:
            print(f'\n📋 {log_file}: File not found')
    
    # Overall summary
    print(f'\n' + '='*60)
    print(f'🎯 OVERALL PERFORMANCE SUMMARY')
    print(f'='*60)
    
    print(f'📊 Total trades attempted: {total_stats["total_trades"]}')
    print(f'✅ Successful trades: {total_stats["successful_trades"]}')
    print(f'❌ Failed trades: {total_stats["failed_trades"]}')
    
    if total_stats['total_trades'] > 0:
        success_rate = total_stats['successful_trades'] / total_stats['total_trades'] * 100
        print(f'📈 Overall success rate: {success_rate:.1f}%')
    
    print(f'💰 Total expected profit: ${total_stats["total_profit"]:.2f}')
    print(f'💸 Total fees: ${total_stats["total_fees"]:.4f}')
    print(f'💸 Net profit: ${total_stats["total_profit"] - total_stats["total_fees"]:.2f}')
    print(f'📈 Total contracts traded: {total_stats["contracts_traded"]}')
    print(f'🎯 Unique markets traded: {len(total_stats["unique_markets"])}')
    
    if total_stats['successful_trades'] > 0:
        avg_profit = total_stats['total_profit'] / total_stats['successful_trades']
        avg_contracts = total_stats['contracts_traded'] / total_stats['successful_trades']
        print(f'💰 Average profit per successful trade: ${avg_profit:.2f}')
        print(f'📈 Average contracts per trade: {avg_contracts:.1f}')
    
    # Time analysis
    if total_stats['earliest_trade'] and total_stats['latest_trade']:
        duration = total_stats['latest_trade'] - total_stats['earliest_trade']
        hours = duration.total_seconds() / 3600
        print(f'⏰ Trading period: {hours:.1f} hours')
        
        if hours > 0:
            trades_per_hour = total_stats['total_trades'] / hours
            profit_per_hour = total_stats['total_profit'] / hours
            print(f'📊 Trades per hour: {trades_per_hour:.1f}')
            print(f'💰 Profit per hour: ${profit_per_hour:.2f}')
    
    # Market analysis
    print(f'\n🎯 MARKET ANALYSIS:')
    print(f'   📊 Most traded markets:')
    
    market_counts = {}
    for log_file in log_files:
        if os.path.exists(log_file):
            try:
                with open(log_file, 'r') as f:
                    for line in f:
                        if line.strip():
                            try:
                                trade = json.loads(line)
                                ticker = trade.get('ticker', 'unknown')
                                if ticker != 'unknown':
                                    market_counts[ticker] = market_counts.get(ticker, 0) + 1
                            except:
                                continue
            except:
                continue
    
    # Sort by trade count
    sorted_markets = sorted(market_counts.items(), key=lambda x: x[1], reverse=True)
    for i, (ticker, count) in enumerate(sorted_markets[:10]):
        print(f'   {i+1}. {ticker}: {count} trades')
    
    print(f'\n💡 PERFORMANCE INSIGHTS:')
    if total_stats['total_trades'] > 0:
        if total_stats['successful_trades'] == 0:
            print(f'   ❌ No successful trades - authentication or execution issues')
        elif success_rate < 50:
            print(f'   ⚠️  Low success rate ({success_rate:.1f}%) - check execution logic')
        elif success_rate > 80:
            print(f'   ✅ High success rate ({success_rate:.1f}%) - good execution')
        
        if total_stats['total_profit'] > 0:
            print(f'   ✅ Positive expected profit (${total_stats["total_profit"]:.2f})')
        else:
            print(f'   ❌ Negative or zero profit - strategy needs review')
        
        if total_stats['contracts_traded'] > 0:
            avg_contracts_per_trade = total_stats['contracts_traded'] / total_stats['successful_trades'] if total_stats['successful_trades'] > 0 else 0
            if avg_contracts_per_trade > 15:
                print(f'   📈 High position sizing (avg {avg_contracts_per_trade:.1f} contracts)')
            else:
                print(f'   📊 Conservative position sizing (avg {avg_contracts_per_trade:.1f} contracts)')

if __name__ == "__main__":
    analyze_trading_performance()
