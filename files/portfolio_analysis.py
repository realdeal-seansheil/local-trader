#!/usr/bin/env python3
"""
Actual Portfolio Performance Analysis
Analyzes real portfolio data, positions, orders, and trade history
"""

import os
import json
import requests
import datetime
import base64
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from kalshi_executor import KalshiAuth, KalshiClient
from kalshi_executor import KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH

def get_headers(auth, method: str, path: str) -> dict:
    """Generate authenticated headers using the correct method."""
    timestamp = str(int(datetime.datetime.now().timestamp() * 1000))
    path_without_query = path.split("?")[0]
    msg = timestamp + method.upper() + path_without_query

    signature = ""
    if auth.private_key:
        sig_bytes = auth.private_key.sign(
            msg.encode(),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH
            ),
            hashes.SHA256()
        )
        signature = base64.b64encode(sig_bytes).decode()

    return {
        "KALSHI-ACCESS-KEY": auth.api_key_id,
        "KALSHI-ACCESS-SIGNATURE": signature,
        "KALSHI-ACCESS-TIMESTAMP": timestamp,
        "Content-Type": "application/json",
    }

def analyze_portfolio_performance():
    print('📊 ACTUAL PORTFOLIO PERFORMANCE ANALYSIS')
    print('=' * 60)
    
    try:
        auth = KalshiAuth(KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH)
        
        # Get actual portfolio balance
        print('💰 CHECKING ACTUAL PORTFOLIO BALANCE...')
        
        timestamp = str(int(datetime.datetime.now().timestamp() * 1000))
        path = '/trade-api/v2/portfolio/balance'
        method = 'GET'
        
        headers = get_headers(auth, method, path)
        url = 'https://api.elections.kalshi.com' + path
        resp = requests.get(url, headers=headers, timeout=15)
        
        if resp.status_code == 200:
            balance_data = resp.json()
            print(f'✅ BALANCE DATA:')
            print(f'   💰 Total balance: ${balance_data.get("balance", 0)/100:.2f}')
            print(f'   💸 Available: ${balance_data.get("available", 0)/100:.2f}')
            print(f'   📊 Pending: ${balance_data.get("pending", 0)/100:.2f}')
        else:
            print(f'❌ Balance check failed: {resp.status_code}')
        
        # Get actual positions
        print(f'\n📈 CHECKING ACTUAL POSITIONS...')
        
        timestamp = str(int(datetime.datetime.now().timestamp() * 1000))
        path = '/trade-api/v2/portfolio/positions'
        method = 'GET'
        
        headers = get_headers(auth, method, path)
        url = 'https://api.elections.kalshi.com' + path
        resp = requests.get(url, headers=headers, timeout=15)
        
        if resp.status_code == 200:
            positions_data = resp.json()
            positions = positions_data.get('positions', [])
            print(f'✅ POSITIONS DATA:')
            print(f'   📊 Total positions: {len(positions)}')
            
            if positions:
                total_value = 0
                total_cost = 0
                total_pnl = 0
                
                print(f'\n📋 POSITION DETAILS:')
                for i, pos in enumerate(positions[:10]):  # Show first 10
                    ticker = pos.get('ticker', 'unknown')
                    side = pos.get('side', 'unknown')
                    count = pos.get('count', 0)
                    price = pos.get('price', 0)
                    value = pos.get('value', 0)
                    
                    print(f'   {i+1}. {ticker}')
                    print(f'      📊 Side: {side}')
                    print(f'      📈 Count: {count}')
                    print(f'      💰 Price: ${price/100:.2f}')
                    print(f'      💸 Value: ${value/100:.2f}')
                    
                    total_value += value
                    total_cost += count * price
                    total_pnl += (value - count * price)
                
                print(f'\n💰 POSITION SUMMARY:')
                print(f'   📊 Total value: ${total_value/100:.2f}')
                print(f'   💸 Total cost: ${total_cost/100:.2f}')
                print(f'   💹 Total P&L: ${total_pnl/100:.2f}')
            else:
                print(f'   📊 No open positions')
        else:
            print(f'❌ Positions check failed: {resp.status_code}')
        
        # Get actual order history
        print(f'\n📜 CHECKING ORDER HISTORY...')
        
        timestamp = str(int(datetime.datetime.now().timestamp() * 1000))
        path = '/trade-api/v2/portfolio/orders'
        method = 'GET'
        
        headers = get_headers(auth, method, path)
        url = 'https://api.elections.kalshi.com' + path
        resp = requests.get(url, headers=headers, timeout=15)
        
        if resp.status_code == 200:
            orders_data = resp.json()
            orders = orders_data.get('orders', [])
            print(f'✅ ORDERS DATA:')
            print(f'   📊 Total orders: {len(orders)}')
            
            if orders:
                # Analyze order performance
                filled_orders = [o for o in orders if o.get('status') == 'filled']
                cancelled_orders = [o for o in orders if o.get('status') == 'canceled']
                pending_orders = [o for o in orders if o.get('status') == 'pending']
                
                print(f'   ✅ Filled orders: {len(filled_orders)}')
                print(f'   ❌ Canceled orders: {len(cancelled_orders)}')
                print(f'   ⏳ Pending orders: {len(pending_orders)}')
                
                # Calculate total spent and P&L for filled orders
                total_spent = 0
                
                print(f'\n📋 RECENT FILLED ORDERS:')
                for i, order in enumerate(filled_orders[:10]):  # Show first 10
                    ticker = order.get('ticker', 'unknown')
                    side = order.get('side', 'unknown')
                    action = order.get('action', 'unknown')
                    count = order.get('count', 0)
                    price = order.get('price', 0)
                    created_time = order.get('created_at', '')
                    
                    # Calculate spent amount
                    spent = count * price
                    total_spent += spent
                    
                    print(f'   {i+1}. {ticker}')
                    print(f'      📊 {action} {side} - {count} contracts @ ${price/100:.2f}')
                    print(f'      💸 Spent: ${spent/100:.2f}')
                    print(f'      ⏰ Time: {created_time}')
                
                print(f'\n💰 ORDER SUMMARY:')
                print(f'   💸 Total spent on filled orders: ${total_spent/100:.2f}')
                
                if filled_orders:
                    fill_rate = len(filled_orders) / len(orders) * 100
                    print(f'   📈 Fill rate: {fill_rate:.1f}%')
            else:
                print(f'   📊 No orders found')
        else:
            print(f'❌ Orders check failed: {resp.status_code}')
        
        # Get trade history (settled trades)
        print(f'\n📜 CHECKING TRADE HISTORY (SETTLED TRADES)...')
        
        timestamp = str(int(datetime.datetime.now().timestamp() * 1000))
        path = '/trade-api/v2/portfolio/trades'
        method = 'GET'
        
        headers = get_headers(auth, method, path)
        url = 'https://api.elections.kalshi.com' + path
        resp = requests.get(url, headers=headers, timeout=15)
        
        if resp.status_code == 200:
            trades_data = resp.json()
            trades = trades_data.get('trades', [])
            print(f'✅ TRADES DATA:')
            print(f'   📊 Total settled trades: {len(trades)}')
            
            if trades:
                # Analyze trade performance
                total_profit = 0
                total_loss = 0
                winning_trades = 0
                losing_trades = 0
                
                print(f'\n📋 RECENT SETTLED TRADES:')
                for i, trade in enumerate(trades[:10]):  # Show first 10
                    ticker = trade.get('ticker', 'unknown')
                    side = trade.get('side', 'unknown')
                    count = trade.get('count', 0)
                    price = trade.get('price', 0)
                    proceeds = trade.get('proceeds', 0)
                    fees = trade.get('fees', 0)
                    created_time = trade.get('created_at', '')
                    
                    # Calculate P&L
                    pnl = proceeds - (count * price) - fees
                    
                    print(f'   {i+1}. {ticker}')
                    print(f'      📊 {side} - {count} contracts @ ${price/100:.2f}')
                    print(f'      💰 Proceeds: ${proceeds/100:.2f}')
                    print(f'      💸 Fees: ${fees/100:.2f}')
                    print(f'      💹 P&L: ${pnl/100:.2f}')
                    print(f'      ⏰ Time: {created_time}')
                    
                    if pnl > 0:
                        total_profit += pnl
                        winning_trades += 1
                    else:
                        total_loss += abs(pnl)
                        losing_trades += 1
                
                print(f'\n💰 TRADE PERFORMANCE SUMMARY:')
                print(f'   🎯 Winning trades: {winning_trades}')
                print(f'   ❌ Losing trades: {losing_trades}')
                print(f'   💰 Total profit: ${total_profit/100:.2f}')
                print(f'   💸 Total loss: ${total_loss/100:.2f}')
                print(f'   💹 Net P&L: ${(total_profit - total_loss)/100:.2f}')
                
                if trades:
                    win_rate = winning_trades / len(trades) * 100
                    avg_win = total_profit / winning_trades if winning_trades > 0 else 0
                    avg_loss = total_loss / losing_trades if losing_trades > 0 else 0
                    
                    print(f'   📈 Win rate: {win_rate:.1f}%')
                    print(f'   💰 Average win: ${avg_win/100:.2f}')
                    print(f'   💸 Average loss: ${avg_loss/100:.2f}')
                    
                    if avg_loss > 0:
                        profit_factor = avg_win / avg_loss
                        print(f'   📊 Profit factor: {profit_factor:.2f}')
            else:
                print(f'   📊 No settled trades found')
        else:
            print(f'❌ Trades check failed: {resp.status_code}')
        
        # Save the analysis
        analysis_data = {
            'timestamp': datetime.datetime.now().isoformat(),
            'balance': balance_data if resp.status_code == 200 else None,
            'positions': positions if 'positions' in locals() else [],
            'orders': orders if 'orders' in locals() else [],
            'trades': trades if 'trades' in locals() else []
        }
        
        os.makedirs('data', exist_ok=True)
        with open('data/portfolio_analysis.json', 'w') as f:
            json.dump(analysis_data, f, indent=2, default=str)
        
        print(f'\n💾 Analysis saved to data/portfolio_analysis.json')
        
    except Exception as e:
        print(f'❌ Portfolio analysis failed: {e}')

if __name__ == "__main__":
    analyze_portfolio_performance()
