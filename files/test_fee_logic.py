#!/usr/bin/env python3
"""
Test the updated fee-aware logic
"""

from kalshi_executor import KalshiAuth, KalshiClient, StrategyExecutor

def test_fee_logic():
    print("Testing fee-aware arbitrage logic...")
    
    # Initialize
    auth = KalshiAuth('dummy', 'dummy')
    client = KalshiClient(auth)
    executor = StrategyExecutor(client)
    
    # Get opportunities
    opps = executor.find_arb_opportunities()
    print(f'Found {len(opps)} fee-filtered opportunities')
    
    if opps:
        best = opps[0]
        print(f'\nBest opportunity (fee-adjusted):')
        print(f'  Ticker: {best["ticker"]}')
        print(f'  YES: {best["yes_price_cents"]}c | NO: {best["no_price_cents"]}c')
        print(f'  Gross profit per contract: ${best.get("gross_profit_per_contract", 0):.4f}')
        print(f'  Net profit per contract: ${best.get("net_profit_per_contract", 0):.4f}')
        print(f'  Total fees per contract: ${best.get("total_fees_per_contract", 0):.4f}')
        print(f'  Net ROI: {best.get("roi_net_percent", 0):.1f}%')
        print(f'  Liquidity: {best["yes_bids"]} YES bids, {best["no_bids"]} NO bids')
        
        # Test execution logic (without actually trading)
        print(f'\nTesting execution logic (dry run)...')
        result = executor.execute_arb(best["ticker"], count=1)
        
        if "error" in result:
            print(f'  Execution blocked: {result["error"]}')
        else:
            summary = result.get("execution_summary", {})
            print(f'  Would execute with:')
            print(f'    Net profit per contract: ${summary.get("net_profit_per_contract", 0):.4f}')
            print(f'    Total fees: ${summary.get("total_fees", 0):.4f}')
            print(f'    Net ROI: {summary.get("net_roi_percent", 0):.1f}%')
    else:
        print('No profitable opportunities found after fees')

if __name__ == "__main__":
    test_fee_logic()
