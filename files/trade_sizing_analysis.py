#!/usr/bin/env python3
"""
Trade Sizing Analysis
Shows exactly how much is being placed per trade under different scenarios.
"""

from kalshi_executor import calculate_arb_profitability, MAX_POSITION_SIZE, MAX_DAILY_EXPOSURE

def analyze_trade_sizing():
    print("=" * 60)
    print("💰 TRADE SIZING ANALYSIS")
    print("=" * 60)
    
    print("\n📊 CURRENT CONFIGURATION:")
    print(f"• MAX_POSITION_SIZE: {MAX_POSITION_SIZE} contracts per order")
    print(f"• MAX_DAILY_EXPOSURE: ${MAX_DAILY_EXPOSURE}")
    print(f"• Periodic Scanner: MAX_CONTRACTS_PER_TRADE = 10")
    print(f"• Default execute_arb(): count = 10")
    
    print("\n" + "=" * 60)
    print("📈 TRADE AMOUNTS BY SCENARIO")
    print("=" * 60)
    
    # Different position sizes
    scenarios = [
        {"contracts": 1, "name": "Minimum Trade"},
        {"contracts": 10, "name": "Default (Periodic Scanner)"},
        {"contracts": 25, "name": "Medium Position"},
        {"contracts": 50, "name": "Large Position"},
        {"contracts": 100, "name": "Maximum Position"},
    ]
    
    # Use current market opportunity (1c YES + 1c NO)
    yes_price = 1
    no_price = 1
    
    print(f"{'Scenario':<20} {'Contracts':<10} {'Notional':<10} {'Fees':<10} {'Net Profit':<12} {'ROI'}")
    print("-" * 75)
    
    for scenario in scenarios:
        contracts = scenario["contracts"]
        name = scenario["name"]
        
        # Calculate for current opportunity (1c+1c = 98c spread)
        analysis = calculate_arb_profitability(yes_price, no_price, count=contracts)
        
        notional = analysis["total_notional"]
        fees = analysis["total_fees"]
        net_profit = analysis["net_profit"]
        roi = analysis["roi_net_percent"]
        
        print(f"{name:<20} {contracts:<10} ${notional:<9.2f} ${fees:<9.2f} ${net_profit:<11.2f} {roi:<5.1f}%")
    
    print("\n" + "=" * 60)
    print("🎯 DAILY EXPOSURE LIMITS")
    print("=" * 60)
    
    daily_limit = MAX_DAILY_EXPOSURE
    max_trades_per_day = daily_limit // 2  # Each arb trade costs ~$2 (1c+1c per contract)
    
    print(f"• Daily exposure limit: ${daily_limit}")
    print(f"• With 10 contracts per trade: ~$20 per arbitrage")
    print(f"• Maximum trades per day: {max_trades_per_day}")
    print(f"• At 10 contracts each: {max_trades_per_day // 10} full arbitrage sets")
    
    print(f"\n• If using max position (100 contracts):")
    print(f"  - Cost per arbitrage: ~$200")
    print(f"  - Maximum trades: {daily_limit // 200}")
    print(f"  - Daily profit potential: ${max_trades_per_day * 0.98:.2f}")
    
    print("\n" + "=" * 60)
    print("⚠️  RISK CONSIDERATIONS")
    print("=" * 60)
    
    print("• Current opportunities (1c+1c) may be pricing errors")
    print("• Typical arbitrage spreads are 2-10 cents, not 98 cents")
    print("• Consider starting with 1-5 contracts for testing")
    print("• Monitor for slippage and market impact")
    
    print("\n" + "=" * 60)
    print("🔧 RECOMMENDED SIZING FOR LIVE TRADING")
    print("=" * 60)
    
    recommendations = [
        {"contracts": 1, "reason": "Testing - minimal risk"},
        {"contracts": 5, "reason": "Small trades - good balance"},
        {"contracts": 10, "reason": "Current default - moderate risk"},
        {"contracts": 25, "reason": "Confident trading - higher risk"},
    ]
    
    for rec in recommendations:
        contracts = rec["contracts"]
        reason = rec["reason"]
        
        analysis = calculate_arb_profitability(yes_price, no_price, count=contracts)
        notional = analysis["total_notional"]
        net_profit = analysis["net_profit"]
        
        print(f"• {contracts} contracts: ${notional:.2f} notional, ${net_profit:.2f} profit")
        print(f"  → {reason}")
    
    print(f"\n💡 To modify trade size:")
    print(f"  • Edit MAX_CONTRACTS_PER_TRADE in periodic_scanner.py")
    print(f"  • Edit default count in execute_arb() function")
    print(f"  • Always test with small amounts first!")

if __name__ == "__main__":
    analyze_trade_sizing()
