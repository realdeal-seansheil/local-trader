#!/usr/bin/env python3
"""
Fee Analysis Demo
Shows how Kalshi fees affect arbitrage profitability.
"""

from kalshi_executor import calculate_arb_profitability

def demo_fee_analysis():
    """Demonstrate fee impact on different arbitrage scenarios."""
    
    print("=" * 60)
    print("💰 KALSHI ARBITRAGE FEE ANALYSIS")
    print("=" * 60)
    print(f"Kalshi Fee Rate: 0.7% per trade")
    print(f"Minimum Profit After Fees: 1 cent per contract\n")
    
    # Test different spread scenarios
    scenarios = [
        {"yes": 1, "no": 1, "name": "Extreme Spread (98c)"},
        {"yes": 5, "no": 5, "name": "High Spread (90c)"},
        {"yes": 10, "no": 10, "name": "Medium Spread (80c)"},
        {"yes": 45, "no": 45, "name": "Low Spread (10c)"},
        {"yes": 48, "no": 48, "name": "Very Low Spread (4c)"},
        {"yes": 49, "no": 49, "name": "Minimal Spread (2c)"},
        {"yes": 49.5, "no": 49.5, "name": "Break-even Spread (1c)"},
    ]
    
    print(f"{'Scenario':<20} {'Gross':<8} {'Fees':<8} {'Net':<8} {'ROI':<8} {'Profitable?'}")
    print("-" * 70)
    
    for scenario in scenarios:
        yes_price = scenario["yes"]
        no_price = scenario["no"]
        name = scenario["name"]
        
        # Calculate for 10 contracts
        analysis = calculate_arb_profitability(yes_price, no_price, count=10)
        
        gross = analysis["gross_total_profit"]
        fees = analysis["total_fees"]
        net = analysis["net_profit"]
        roi = analysis["roi_net_percent"]
        profitable = "✅ YES" if analysis["profitable_after_fees"] else "❌ NO"
        
        print(f"{name:<20} ${gross:<7.2f} ${fees:<7.2f} ${net:<7.2f} {roi:<7.1f}% {profitable}")
    
    print("\n" + "=" * 60)
    print("📊 KEY INSIGHTS:")
    print("=" * 60)
    
    # Calculate breakeven point
    for spread_cents in range(1, 11):
        yes_price = (100 - spread_cents) / 2
        no_price = yes_price
        analysis = calculate_arb_profitability(yes_price, no_price, count=1)
        
        if analysis["profitable_after_fees"]:
            print(f"• Minimum profitable spread: {spread_cents} cents")
            print(f"  → YES price: {yes_price:.1f}c, NO price: {no_price:.1f}c")
            print(f"  → Net profit per contract: ${analysis['net_profit_per_contract']:.4f}")
            print(f"  → Total fees per contract: ${analysis['total_fees']:.4f}")
            break
    
    print(f"\n• Fee Impact Analysis:")
    print(f"  → On $1.00 notional: $0.007 fee per leg (0.7%)")
    print(f"  → On $0.02 notional (1c+1c): $0.00014 fee per leg")
    print(f"  → Total fees for 10 contracts at 1c+1c: ~$0.003")
    
    print(f"\n• Risk Considerations:")
    print(f"  → Small spreads (<2c) may become unprofitable after fees")
    print(f"  → Market impact and slippage not included in calculations")
    print(f"  → Maker vs taker fees may differ (check specific market)")
    
    print(f"\n• Recommendations:")
    print(f"  → Target spreads >3c for comfortable margin")
    print(f"  → Use limit orders to reduce fees (maker rebates may apply)")
    print(f"  → Account for potential slippage in fast-moving markets")

if __name__ == "__main__":
    demo_fee_analysis()
