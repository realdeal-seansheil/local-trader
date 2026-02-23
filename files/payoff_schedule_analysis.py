#!/usr/bin/env python3
"""
Payoff Schedule Analysis
Analyzes when arbitrage opportunities will pay out based on market expiration dates.
"""

import json
from datetime import datetime, timedelta
from kalshi_executor import KalshiAuth, KalshiClient

def decode_kalshi_ticker(ticker):
    """Decode Kalshi ticker to extract event date and type."""
    parts = ticker.split('-')
    
    # Extract date information
    date_info = ""
    event_type = ""
    
    for part in parts:
        # Look for date patterns like 26FEB16, 15FEB, etc.
        if any(month in part.upper() for month in ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 
                                                  'JUL', 'AUG', 'SEP', 'OPR', 'NOV', 'DEC']):
            date_info = part
        # Look for event types
        elif any(keyword in part.upper() for keyword in ['BTC', 'ETH', 'GAME', 'MATCH', 'SPORT']):
            event_type = part
    
    return date_info, event_type

def parse_date_from_ticker(date_str):
    """Parse date from ticker format like '26FEB16' or '15FEB'."""
    try:
        # Handle different date formats
        if len(date_str) >= 6:  # 26FEB16 format
            day = int(date_str[:2])
            month_str = date_str[2:5].upper()
            year_str = date_str[5:7]
            year = 2000 + int(year_str)  # Assume 20xx
        elif len(date_str) >= 5:  # 15FEB format
            day = int(date_str[:2])
            month_str = date_str[2:5].upper()
            year = datetime.now().year
        else:
            return None
            
        months = {
            'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6,
            'JUL': 7, 'AUG': 8, 'SEP': 9, 'OPR': 10, 'NOV': 11, 'DEC': 12
        }
        
        month = months.get(month_str)
        if month:
            return datetime(year, month, day)
        return None
    except:
        return None

def analyze_payoff_schedules():
    print("=" * 60)
    print("📅 PAYOFF SCHEDULE ANALYSIS")
    print("=" * 60)
    
    # Load current opportunities
    try:
        with open('data/kalshi_opportunities.json', 'r') as f:
            data = json.load(f)
        opportunities = data.get('top_opportunities', [])
    except:
        print("No opportunities data found")
        return
    
    print(f"Analyzing {len(opportunities)} current opportunities...")
    print(f"Analysis date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    print("\n" + "=" * 60)
    print("📊 OPPORTUNITY PAYOFF SCHEDULES")
    print("=" * 60)
    
    # Group by time horizon
    same_day = []
    this_week = []
    next_week = []
    longer_term = []
    
    for opp in opportunities:
        ticker = opp['ticker']
        date_info, event_type = decode_kalshi_ticker(ticker)
        
        event_date = parse_date_from_ticker(date_info) if date_info else None
        
        if event_date:
            days_until = (event_date - datetime.now()).days
            hours_until = (event_date - datetime.now()).total_seconds() / 3600
            
            opportunity_info = {
                'ticker': ticker,
                'event_date': event_date.strftime('%Y-%m-%d'),
                'days_until': days_until,
                'hours_until': hours_until,
                'event_type': event_type,
                'net_profit': opp.get('net_profit_per_contract', 0),
                'roi': opp.get('roi_net_percent', 0)
            }
            
            # Categorize by time horizon
            if days_until <= 1:
                same_day.append(opportunity_info)
            elif days_until <= 7:
                this_week.append(opportunity_info)
            elif days_until <= 14:
                next_week.append(opportunity_info)
            else:
                longer_term.append(opportunity_info)
        else:
            # Could not parse date
            longer_term.append({
                'ticker': ticker,
                'event_date': 'Unknown',
                'days_until': 'Unknown',
                'hours_until': 'Unknown',
                'event_type': event_type,
                'net_profit': opp.get('net_profit_per_contract', 0),
                'roi': opp.get('roi_net_percent', 0)
            })
    
    # Display results by time horizon
    categories = [
        ("Same Day (≤24h)", same_day),
        ("This Week (≤7 days)", this_week),
        ("Next Week (≤14 days)", next_week),
        ("Longer Term (>14 days)", longer_term)
    ]
    
    for category_name, opportunities_list in categories:
        if opportunities_list:
            print(f"\n🎯 {category_name}: {len(opportunities_list)} opportunities")
            print("-" * 50)
            
            for opp in opportunities_list[:5]:  # Show top 5
                if isinstance(opp['hours_until'], (int, float)):
                    time_str = f"{opp['hours_until']:.1f} hours"
                else:
                    time_str = "Unknown"
                
                print(f"  {opp['ticker']}")
                print(f"    Event: {opp['event_date']} ({time_str})")
                print(f"    Type: {opp['event_type']}")
                print(f"    Profit: ${opp['net_profit']:.4f} per contract")
                print(f"    ROI: {opp['roi']:.1f}%")
                print()
    
    print("=" * 60)
    print("⏰ PAYOFF TIMING IMPLICATIONS")
    print("=" * 60)
    
    print("📈 Capital Efficiency Analysis:")
    
    total_opportunities = len(opportunities)
    if same_day:
        print(f"• Same-day payoff: {len(same_day)} opportunities")
        print(f"  → Capital returned within 24 hours")
        print(f"  → Highest turnover potential")
    
    if this_week:
        print(f"• This-week payoff: {len(this_week)} opportunities")
        print(f"  → Capital tied up 1-7 days")
        print(f"  → Good balance of turnover and opportunity")
    
    if next_week:
        print(f"• Next-week payoff: {len(next_week)} opportunities")
        print(f"  → Capital tied up 1-2 weeks")
        print(f"  → Lower turnover, but more opportunities")
    
    if longer_term:
        print(f"• Longer-term: {len(longer_term)} opportunities")
        print(f"  → Capital tied up >2 weeks")
        print(f"  → Lowest turnover efficiency")
    
    print(f"\n💡 Arbitrage Strategy Considerations:")
    print(f"• Faster payoffs = higher annualized ROI")
    print(f"• Slower payoffs = capital lockup risk")
    print(f"• Diversify across time horizons for steady cash flow")
    print(f"• Prioritize same-day and this-week opportunities for maximum efficiency")
    
    print(f"\n⚠️  Risk Factors:")
    print(f"• Early settlement possible (can_close_early)")
    print(f"• Event cancellations or postponements")
    print(f"• Market liquidity changes before expiration")
    print(f"• Counterparty risk for longer-term positions")

if __name__ == "__main__":
    analyze_payoff_schedules()
