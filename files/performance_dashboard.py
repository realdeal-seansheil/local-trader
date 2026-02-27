#!/usr/bin/env python3
"""
Interactive Performance Dashboard for Kalshi 15-Minute Crypto Trader
Generates a standalone HTML file with plotly charts.

Usage: python3 performance_dashboard.py
Output: performance_dashboard.html (open in browser)

Requires: pip install plotly pandas
"""

import sqlite3
import os
from datetime import datetime, timezone

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ============================================================
# CONFIGURATION
# ============================================================

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       'data', 'enhanced_15min_trader_fixed.db')
OUTPUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           'performance_dashboard.html')

# Era boundaries (UTC) — update these when config changes are deployed
ERA_BOUNDARIES = [
    {
        'name': 'Era 2',
        'label': 'conv 0.01, entry 5¢+',
        'start': '2026-02-18T00:00:00+00:00',
        'end': '2026-02-19T01:00:00+00:00',
    },
    {
        'name': 'Era 3',
        'label': 'conv 0.02, entry 40¢+, EV≥2',
        'start': '2026-02-19T01:00:00+00:00',
        'end': '2026-02-19T15:30:00+00:00',
    },
    {
        'name': 'Era 4',
        'label': 'entry 43¢+, YES penalty 0.01, no EV gate, max 7',
        'start': '2026-02-19T15:30:00+00:00',
        'end': '2026-02-20T11:15:00+00:00',
    },
    {
        'name': 'Era 5',
        'label': 'asymmetric YES penalty (only YES signals)',
        'start': '2026-02-20T11:15:00+00:00',
        'end': '2026-02-20T16:00:00+00:00',
    },
    {
        'name': 'Era 6',
        'label': 'penalty 0.005, conv 0.015, dynamic sizing',
        'start': '2026-02-20T16:00:00+00:00',
        'end': '2026-02-20T20:25:00+00:00',
    },
    {
        'name': 'Era 7',
        'label': 'Signal E trend, perf feedback, hour sizing',
        'start': '2026-02-20T20:25:00+00:00',
        'end': '2026-02-21T05:15:00+00:00',
    },
    {
        'name': 'Era 8',
        'label': 'adaptive penalty (asset+macro), macro sizing',
        'start': '2026-02-21T05:15:00+00:00',
        'end': '2026-02-21T21:30:00+00:00',
    },
    {
        'name': 'Era 9',
        'label': 'regime gate, agreement gate, rolling learning, pooled feedback',
        'start': '2026-02-21T21:30:00+00:00',
        'end': '2026-02-22T18:00:00+00:00',
    },
    {
        'name': 'Era 10',
        'label': 'EV-first, entry band 38-49c, payoff Kelly',
        'start': '2026-02-22T18:00:00+00:00',
        'end': '2026-02-22T22:30:00+00:00',
    },
    {
        'name': 'Era 11',
        'label': 'Era 2 redux: gates open, max 5 contracts, full logging',
        'start': '2026-02-22T22:30:00+00:00',
        'end': '2026-02-23T01:30:00+00:00',
    },
    {
        'name': 'Era 12',
        'label': 'Pure Era 2: conviction Kelly, min 2 contracts, no penalty/feedback',
        'start': '2026-02-23T01:30:00+00:00',
        'end': '2026-02-23T15:00:00+00:00',
    },
    {
        'name': 'Era 13',
        'label': 'Sniper: 41-47c only, no XRP, max 5 contracts',
        'start': '2026-02-23T15:00:00+00:00',
        'end': '2026-02-23T20:30:00+00:00',
    },
    {
        'name': 'Era 14',
        'label': 'Era 2 revival: 41-55c, all 4 assets, max 10 contracts',
        'start': '2026-02-23T20:30:00+00:00',
        'end': '2026-02-24T01:00:00+00:00',
    },
    {
        'name': 'Era 15',
        'label': 'Signal purge: Signal E killed, Signal D 0.15→0.05 (observation)',
        'start': '2026-02-24T01:00:00+00:00',
        'end': '2026-02-23T23:30:00+00:00',
    },
    {
        'name': 'Era 16',
        'label': 'Asymmetric Dollar Edge: 44-52c band, payoff ratio gate (observation)',
        'start': '2026-02-23T23:30:00+00:00',
        'end': '2026-02-24T14:40:00+00:00',
    },
    {
        'name': 'Era 17',
        'label': 'Dumb Money: cheaper-side direction, fixed 3 contracts, 44-53c band (observation)',
        'start': '2026-02-24T14:40:00+00:00',
        'end': '2026-02-25T16:10:00+00:00',
    },
    {
        'name': 'Era 18',
        'label': 'Smart Dumb Money: signal veto + 44-49c band (observation)',
        'start': '2026-02-25T16:10:00+00:00',
        'end': '2026-02-25T20:15:00+00:00',
    },
    {
        'name': 'Era 19',
        'label': 'YES Only: structural YES bias, 44-55c band (observation)',
        'start': '2026-02-25T20:15:00+00:00',
        'end': '2026-02-26T15:10:00+00:00',
    },
    {
        'name': 'Era 20',
        'label': 'Tight Spread Cheap Side: spread ≤3c, 46-50c band (observation)',
        'start': '2026-02-26T15:10:00+00:00',
        'end': '2026-02-27T01:57:00+00:00',
    },
    {
        'name': 'Era 21',
        'label': 'Pure Era 2 Revival: wide gates 5-55c, signal direction, conviction Kelly (observation)',
        'start': '2026-02-27T01:57:00+00:00',
        'end': '2099-12-31T23:59:59+00:00',
    },
]

# Target thresholds for KPI coloring
TARGETS = {
    'simple_wr': 55,      # %
    'dollar_wr': 65,      # %
    'profit_factor': 1.7,  # x
    'dollar_per_hour': 2.0, # $
}

# Asset colors
ASSET_COLORS = {
    'BTC': '#f7931a',
    'ETH': '#627eea',
    'SOL': '#9945ff',
    'XRP': '#00aae4',
}

# Hour sizing multipliers from trader config (for overlay on dashboard chart)
HOUR_SIZING_MULTIPLIER = {
    0: 0.5, 1: 0.5, 2: 0.5, 3: 0.5, 4: 0.75, 5: 1.0,
    6: 0.5, 7: 0.75, 8: 0.75, 9: 1.0, 10: 1.0, 11: 1.0,
    12: 1.0, 13: 1.0, 14: 1.0, 15: 1.0, 16: 1.0, 17: 1.0,
    18: 1.0, 19: 1.0, 20: 0.5, 21: 1.0, 22: 0.5, 23: 0.75,
}

# ============================================================
# DATA LOADING
# ============================================================

def load_trades(conn):
    """Load all resolved trades as a DataFrame."""
    query = """
    SELECT
        id, ticker, direction, entry_price, contracts, cost_basis,
        estimated_win_prob, ev_per_contract, kelly_fraction,
        entry_time, expiry_time, status, exit_price, realized_pnl,
        filled_count, requested_contracts,
        CASE
            WHEN ticker LIKE 'KXBTC%' THEN 'BTC'
            WHEN ticker LIKE 'KXETH%' THEN 'ETH'
            WHEN ticker LIKE 'KXSOL%' THEN 'SOL'
            WHEN ticker LIKE 'KXXRP%' THEN 'XRP'
            ELSE 'OTHER'
        END as asset
    FROM trades
    WHERE status IN ('won', 'lost')
    ORDER BY entry_time
    """
    df = pd.read_sql_query(query, conn)
    df['entry_time'] = pd.to_datetime(df['entry_time'], utc=True)
    return df


def load_balance(conn):
    """Load balance history from scans table."""
    query = """
    SELECT scan_time, balance_cents
    FROM scans
    WHERE balance_cents IS NOT NULL AND balance_cents > 0
    ORDER BY scan_time
    """
    df = pd.read_sql_query(query, conn)
    df['scan_time'] = pd.to_datetime(df['scan_time'], utc=True)
    df['balance_dollars'] = df['balance_cents'] / 100.0
    return df


def load_signal_log(conn):
    """Load resolved signal_log entries with Era 7+8 fields as a DataFrame."""
    query = """
    SELECT
        sl.id, sl.ticker, sl.series_ticker, sl.scan_time,
        sl.signal_e, sl.weight_e, sl.perf_adjustment, sl.hour_utc,
        sl.win_prob, sl.best_direction, sl.yes_ask, sl.no_ask,
        sl.action_taken, sl.actual_result, sl.would_have_won,
        sl.signal_correct,
        sl.adaptive_penalty, sl.trend_20m, sl.macro_trend, sl.trend_regime,
        CASE
            WHEN sl.ticker LIKE 'KXBTC%' THEN 'BTC'
            WHEN sl.ticker LIKE 'KXETH%' THEN 'ETH'
            WHEN sl.ticker LIKE 'KXSOL%' THEN 'SOL'
            WHEN sl.ticker LIKE 'KXXRP%' THEN 'XRP'
            ELSE 'OTHER'
        END as asset
    FROM signal_log sl
    WHERE sl.actual_result IN ('yes', 'no')
      AND sl.action_taken = 'placed'
    ORDER BY sl.scan_time
    """
    try:
        df = pd.read_sql_query(query, conn)
        df['scan_time'] = pd.to_datetime(df['scan_time'], utc=True)
        df['is_win'] = (df['would_have_won'] == 1).astype(int)
        return df
    except Exception:
        return pd.DataFrame()


# ============================================================
# METRIC COMPUTATION
# ============================================================

def compute_metrics(df):
    """Compute all KPI metrics from a trades DataFrame."""
    total = len(df)
    if total == 0:
        return {k: 0 for k in [
            'total_trades', 'wins', 'losses', 'simple_wr', 'dollar_wr',
            'profit_factor', 'net_pnl_cents', 'net_pnl_dollars',
            'gross_profit_dollars', 'gross_loss_dollars',
            'hours_elapsed', 'dollar_per_hour', 'trades_per_hour',
            'avg_win_dollars', 'avg_loss_dollars', 'expectancy',
        ]}

    wins = (df['status'] == 'won').sum()
    losses = (df['status'] == 'lost').sum()
    simple_wr = wins / total * 100

    gross_profit = df.loc[df['realized_pnl'] > 0, 'realized_pnl'].sum()
    gross_loss = abs(df.loc[df['realized_pnl'] < 0, 'realized_pnl'].sum())
    dollar_wr = gross_profit / (gross_profit + gross_loss) * 100 if (gross_profit + gross_loss) > 0 else 0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

    net_pnl_cents = df['realized_pnl'].sum()
    net_pnl_dollars = net_pnl_cents / 100.0

    first_trade = df['entry_time'].min()
    last_trade = df['entry_time'].max()
    hours_elapsed = max((last_trade - first_trade).total_seconds() / 3600, 0.01)

    dollar_per_hour = net_pnl_dollars / hours_elapsed
    trades_per_hour = total / hours_elapsed

    win_trades = df[df['status'] == 'won']
    loss_trades = df[df['status'] == 'lost']
    avg_win = (win_trades['realized_pnl'].mean() / 100) if len(win_trades) > 0 else 0
    avg_loss = (abs(loss_trades['realized_pnl'].mean()) / 100) if len(loss_trades) > 0 else 0
    expectancy = net_pnl_dollars / total if total > 0 else 0

    return {
        'total_trades': total,
        'wins': wins,
        'losses': losses,
        'simple_wr': simple_wr,
        'dollar_wr': dollar_wr,
        'profit_factor': profit_factor,
        'net_pnl_cents': net_pnl_cents,
        'net_pnl_dollars': net_pnl_dollars,
        'gross_profit_dollars': gross_profit / 100,
        'gross_loss_dollars': gross_loss / 100,
        'hours_elapsed': hours_elapsed,
        'dollar_per_hour': dollar_per_hour,
        'trades_per_hour': trades_per_hour,
        'avg_win_dollars': avg_win,
        'avg_loss_dollars': avg_loss,
        'expectancy': expectancy,
    }


# ============================================================
# KPI CARD HTML
# ============================================================

def _kpi_color(value, metric):
    """Return green/yellow/red color based on metric thresholds."""
    if metric == 'simple_wr':
        if value >= 55: return '#00ff88'
        if value >= 50: return '#ffaa00'
        return '#ff4444'
    elif metric == 'dollar_wr':
        if value >= 65: return '#00ff88'
        if value >= 55: return '#ffaa00'
        return '#ff4444'
    elif metric == 'profit_factor':
        if value >= 1.7: return '#00ff88'
        if value >= 1.3: return '#ffaa00'
        return '#ff4444'
    elif metric == 'dollar_per_hour':
        if value >= 2.0: return '#00ff88'
        if value >= 1.0: return '#ffaa00'
        return '#ff4444'
    elif metric == 'net_pnl':
        return '#00ff88' if value >= 0 else '#ff4444'
    return '#ffffff'


def build_kpi_html(metrics):
    """Generate HTML for the KPI card row."""
    cards = [
        ('Net P&L', f"${metrics['net_pnl_dollars']:+.2f}", _kpi_color(metrics['net_pnl_dollars'], 'net_pnl'),
         f"{metrics['wins']}W / {metrics['losses']}L"),
        ('Simple WR', f"{metrics['simple_wr']:.1f}%", _kpi_color(metrics['simple_wr'], 'simple_wr'),
         f"Target: 55%"),
        ('Dollar WR', f"{metrics['dollar_wr']:.1f}%", _kpi_color(metrics['dollar_wr'], 'dollar_wr'),
         f"Target: 65%"),
        ('Profit Factor', f"{metrics['profit_factor']:.2f}x", _kpi_color(metrics['profit_factor'], 'profit_factor'),
         f"Target: 1.70x"),
        ('$/hr', f"${metrics['dollar_per_hour']:.2f}", _kpi_color(metrics['dollar_per_hour'], 'dollar_per_hour'),
         f"Target: $2.00"),
        ('Trades/hr', f"{metrics['trades_per_hour']:.1f}", '#ffffff',
         f"{metrics['hours_elapsed']:.1f} hrs total"),
        ('Expectancy', f"${metrics['expectancy']:.3f}", _kpi_color(metrics['expectancy'], 'net_pnl'),
         f"Per trade avg"),
    ]

    html = '<div class="kpi-row">\n'
    for label, value, color, sub in cards:
        html += f'''  <div class="kpi-card">
    <div class="kpi-label">{label}</div>
    <div class="kpi-value" style="color:{color}">{value}</div>
    <div class="kpi-sub">{sub}</div>
  </div>\n'''
    html += '</div>'
    return html


# ============================================================
# CHART BUILDERS
# ============================================================

def assign_era(entry_time):
    """Assign an era label to a trade based on its entry_time."""
    for era in ERA_BOUNDARIES:
        start = pd.Timestamp(era['start'])
        end = pd.Timestamp(era['end'])
        if start <= entry_time < end:
            return era['name']
    return 'Unknown'


def build_dashboard(df, balance_df, sl_df, metrics):
    """Build the full plotly dashboard figure."""

    fig = make_subplots(
        rows=8, cols=3,
        specs=[
            [{"colspan": 2}, None, {}],           # Row 1: Cum P&L (2 cols) + Rolling WR
            [{}, {}, {}],                          # Row 2: Direction, Asset, Price
            [{}, {}, {}],                          # Row 3: Contract WR, Contract P&L, Conviction
            [{}, {"colspan": 2}, None],            # Row 4: Hourly WR, Calibration
            [{"colspan": 3}, None, None],          # Row 5: Era comparison
            [{}, {}, {}],                          # Row 6: Era 7 features (Signal E, Perf Feedback, Hour Sizing)
            [{}, {}, {}],                          # Row 7: Era 8 features (Regime WR, Penalty Distribution, Macro Trend)
            [{"colspan": 3}, None, None],          # Row 8: Balance
        ],
        row_heights=[0.15, 0.12, 0.12, 0.12, 0.11, 0.12, 0.12, 0.14],
        subplot_titles=[
            'Cumulative P&L (Trade-by-Trade)', '', 'Rolling 20-Trade Win Rate',
            'Win Rate by Direction', 'Win Rate by Asset', 'Win Rate by Entry Price',
            'Win Rate by Contract Count', 'P&L by Contract Count ($)', 'Win Rate by Conviction',
            'Win Rate by Hour (UTC)', 'Signal Calibration: Estimated vs Actual Win Rate',  '',
            'Era Performance Comparison', '', '',
            'Signal E Accuracy (Trend)', 'Performance Feedback Impact', 'Hour Sizing Effectiveness',
            'WR by Market Regime', 'Adaptive Penalty Distribution', 'Macro vs Asset Trend',
            'Account Balance Over Time', '', '',
        ],
        vertical_spacing=0.038,
        horizontal_spacing=0.06,
    )

    # ---- Derived columns ----
    df = df.copy()
    df['pnl_dollars'] = df['realized_pnl'] / 100.0
    df['cum_pnl'] = df['pnl_dollars'].cumsum()
    df['is_win'] = (df['status'] == 'won').astype(int)
    df['rolling_wr'] = df['is_win'].rolling(window=20, min_periods=10).mean() * 100
    df['conviction'] = (df['estimated_win_prob'] - 0.5).abs()
    df['trade_num'] = range(1, len(df) + 1)
    df['era'] = df['entry_time'].apply(assign_era)

    # ================================================================
    # ROW 1, COL 1-2: Cumulative P&L
    # ================================================================
    # Color the fill green when cum_pnl > 0, red when < 0
    fig.add_trace(go.Scatter(
        x=df['entry_time'], y=df['cum_pnl'],
        mode='lines',
        name='Cumulative P&L',
        line=dict(color='#00ff88', width=2),
        fill='tozeroy',
        fillcolor='rgba(0,255,136,0.08)',
        hovertemplate=(
            'Trade #%{customdata[0]}<br>'
            'Time: %{x}<br>'
            'This trade: $%{customdata[1]:.2f}<br>'
            'Cum P&L: $%{y:.2f}<br>'
            'Direction: %{customdata[2]}<br>'
            'Asset: %{customdata[3]}'
            '<extra></extra>'
        ),
        customdata=list(zip(df['trade_num'], df['pnl_dollars'], df['direction'], df['asset'])),
    ), row=1, col=1)

    # Era boundary vertical lines
    for era in ERA_BOUNDARIES[1:]:
        era_ts = pd.Timestamp(era['start'])
        if era_ts >= df['entry_time'].min() and era_ts <= df['entry_time'].max():
            fig.add_vline(
                x=era_ts.timestamp() * 1000,  # plotly uses ms for datetime
                line_dash="dash", line_color="rgba(255,255,0,0.5)", line_width=1,
                row=1, col=1,
            )
            fig.add_annotation(
                x=era_ts, y=df['cum_pnl'].max() * 0.95,
                text=f"← {era['name']}", showarrow=False,
                font=dict(color='yellow', size=10),
                xref='x', yref='y',
                row=1, col=1,
            )

    # ================================================================
    # ROW 1, COL 3: Rolling 20-trade Win Rate
    # ================================================================
    fig.add_trace(go.Scatter(
        x=df['entry_time'], y=df['rolling_wr'],
        mode='lines',
        name='Rolling 20 WR',
        line=dict(color='#4488ff', width=2),
        hovertemplate='Trade #%{customdata}<br>Rolling WR: %{y:.1f}%<extra></extra>',
        customdata=df['trade_num'],
    ), row=1, col=3)

    # Target line at 55%
    fig.add_hline(y=55, line_dash="dash", line_color="rgba(0,255,136,0.5)",
                  annotation_text="55% target", annotation_font_color="#00ff88",
                  annotation_font_size=9, row=1, col=3)
    # Breakeven at 50%
    fig.add_hline(y=50, line_dash="dot", line_color="rgba(255,68,68,0.4)", row=1, col=3)

    # ================================================================
    # ROW 2, COL 1: Win Rate by Direction
    # ================================================================
    dir_stats = df.groupby('direction').agg(
        total=('status', 'count'),
        wins=('is_win', 'sum'),
        pnl=('pnl_dollars', 'sum'),
    ).reset_index()
    dir_stats['wr'] = dir_stats['wins'] / dir_stats['total'] * 100

    fig.add_trace(go.Bar(
        x=dir_stats['direction'], y=dir_stats['wr'],
        text=[f"{r['wr']:.1f}%<br>({r['wins']}/{r['total']})<br>${r['pnl']:+.2f}"
              for _, r in dir_stats.iterrows()],
        textposition='inside',
        textfont=dict(size=12, color='white'),
        marker_color=['#ff6666' if d == 'YES' else '#66ff66' for d in dir_stats['direction']],
        name='Direction',
        showlegend=False,
    ), row=2, col=1)
    fig.add_hline(y=50, line_dash="dot", line_color="rgba(255,255,255,0.3)", row=2, col=1)

    # ================================================================
    # ROW 2, COL 2: Win Rate by Asset
    # ================================================================
    asset_stats = df.groupby('asset').agg(
        total=('status', 'count'),
        wins=('is_win', 'sum'),
        pnl=('pnl_dollars', 'sum'),
    ).reset_index()
    asset_stats['wr'] = asset_stats['wins'] / asset_stats['total'] * 100

    fig.add_trace(go.Bar(
        x=asset_stats['asset'], y=asset_stats['wr'],
        text=[f"{r['wr']:.1f}%<br>n={r['total']}<br>${r['pnl']:+.2f}"
              for _, r in asset_stats.iterrows()],
        textposition='inside',
        textfont=dict(size=11, color='white'),
        marker_color=[ASSET_COLORS.get(a, '#888') for a in asset_stats['asset']],
        name='Asset',
        showlegend=False,
    ), row=2, col=2)
    fig.add_hline(y=50, line_dash="dot", line_color="rgba(255,255,255,0.3)", row=2, col=2)

    # ================================================================
    # ROW 2, COL 3: Win Rate by Entry Price Bucket
    # ================================================================
    bins = [0, 35, 40, 45, 50, 100]
    labels = ['<35¢', '35-39¢', '40-44¢', '45-49¢', '50+¢']
    df['price_bucket'] = pd.cut(df['entry_price'], bins=bins, labels=labels, right=False)

    price_stats = df.groupby('price_bucket', observed=True).agg(
        total=('status', 'count'),
        wins=('is_win', 'sum'),
        pnl=('pnl_dollars', 'sum'),
    ).reset_index()
    price_stats['wr'] = price_stats['wins'] / price_stats['total'] * 100

    # Color by performance
    price_colors = ['#00ff88' if wr >= 55 else '#ffaa00' if wr >= 48 else '#ff4444'
                    for wr in price_stats['wr']]
    fig.add_trace(go.Bar(
        x=price_stats['price_bucket'].astype(str), y=price_stats['wr'],
        text=[f"{r['wr']:.0f}%<br>n={r['total']}" for _, r in price_stats.iterrows()],
        textposition='inside',
        textfont=dict(size=11, color='white'),
        marker_color=price_colors,
        name='Price',
        showlegend=False,
    ), row=2, col=3)
    fig.add_hline(y=50, line_dash="dot", line_color="rgba(255,255,255,0.3)", row=2, col=3)

    # ================================================================
    # ROW 3, COL 1: Win Rate by Contract Count
    # ================================================================
    df['contract_bucket'] = df['contracts'].clip(upper=7)
    contract_stats = df.groupby('contract_bucket').agg(
        total=('status', 'count'),
        wins=('is_win', 'sum'),
    ).reset_index()
    contract_stats['wr'] = contract_stats['wins'] / contract_stats['total'] * 100

    contract_colors = ['#00ff88' if wr >= 55 else '#ffaa00' if wr >= 48 else '#ff4444'
                       for wr in contract_stats['wr']]
    fig.add_trace(go.Bar(
        x=contract_stats['contract_bucket'], y=contract_stats['wr'],
        text=[f"{r['wr']:.0f}%<br>n={r['total']}" for _, r in contract_stats.iterrows()],
        textposition='inside',
        textfont=dict(size=11, color='white'),
        marker_color=contract_colors,
        name='Contracts WR',
        showlegend=False,
    ), row=3, col=1)
    fig.add_hline(y=50, line_dash="dot", line_color="rgba(255,255,255,0.3)", row=3, col=1)

    # ================================================================
    # ROW 3, COL 2: P&L by Contract Count
    # ================================================================
    pnl_by_contracts = df.groupby('contract_bucket').agg(
        pnl=('pnl_dollars', 'sum'),
        total=('status', 'count'),
    ).reset_index()

    pnl_colors = ['#00ff88' if p > 0 else '#ff4444' for p in pnl_by_contracts['pnl']]
    fig.add_trace(go.Bar(
        x=pnl_by_contracts['contract_bucket'], y=pnl_by_contracts['pnl'],
        text=[f"${p:.2f}<br>n={n}" for p, n in zip(pnl_by_contracts['pnl'], pnl_by_contracts['total'])],
        textposition='outside',
        textfont=dict(size=10),
        marker_color=pnl_colors,
        name='Contract P&L',
        showlegend=False,
    ), row=3, col=2)

    # ================================================================
    # ROW 3, COL 3: Win Rate by Conviction Tier
    # ================================================================
    conv_bins = [0, 0.01, 0.02, 0.03, 0.04, 0.05, 1.0]
    conv_labels = ['<1%', '1-2%', '2-3%', '3-4%', '4-5%', '5%+']
    df['conviction_tier'] = pd.cut(df['conviction'], bins=conv_bins, labels=conv_labels, right=False)

    conv_stats = df.groupby('conviction_tier', observed=True).agg(
        total=('status', 'count'),
        wins=('is_win', 'sum'),
    ).reset_index()
    conv_stats['wr'] = conv_stats['wins'] / conv_stats['total'] * 100

    conv_colors = ['#00ff88' if wr >= 55 else '#ffaa00' if wr >= 48 else '#ff4444'
                   for wr in conv_stats['wr']]
    fig.add_trace(go.Bar(
        x=conv_stats['conviction_tier'].astype(str), y=conv_stats['wr'],
        text=[f"{r['wr']:.0f}%<br>n={r['total']}" for _, r in conv_stats.iterrows()],
        textposition='inside',
        textfont=dict(size=11, color='white'),
        marker_color=conv_colors,
        name='Conviction WR',
        showlegend=False,
    ), row=3, col=3)
    fig.add_hline(y=50, line_dash="dot", line_color="rgba(255,255,255,0.3)", row=3, col=3)

    # ================================================================
    # ROW 4, COL 1: Win Rate by Hour of Day (UTC)
    # ================================================================
    df['hour_utc'] = df['entry_time'].dt.hour
    hourly_stats = df.groupby('hour_utc').agg(
        total=('status', 'count'),
        wins=('is_win', 'sum'),
        pnl=('pnl_dollars', 'sum'),
    ).reset_index()
    hourly_stats['wr'] = hourly_stats['wins'] / hourly_stats['total'] * 100

    hour_colors = ['#00ff88' if wr >= 55 else '#ffaa00' if wr >= 48 else '#ff4444'
                   for wr in hourly_stats['wr']]
    fig.add_trace(go.Bar(
        x=hourly_stats['hour_utc'], y=hourly_stats['wr'],
        text=[f"{r['wr']:.0f}%<br>n={r['total']}<br>${r['pnl']:+.1f}"
              for _, r in hourly_stats.iterrows()],
        textposition='outside',
        textfont=dict(size=9),
        marker_color=hour_colors,
        name='Hourly WR',
        showlegend=False,
    ), row=4, col=1)
    fig.add_hline(y=50, line_dash="dot", line_color="rgba(255,255,255,0.3)", row=4, col=1)

    # ================================================================
    # ROW 4, COL 2-3: Signal Calibration (Estimated vs Actual WR)
    # ================================================================
    prob_bins = [0.35, 0.42, 0.46, 0.48, 0.50, 0.52, 0.54, 0.58, 0.65]
    prob_labels = ['35-42%', '42-46%', '46-48%', '48-50%', '50-52%', '52-54%', '54-58%', '58-65%']
    df['prob_bucket'] = pd.cut(df['estimated_win_prob'], bins=prob_bins, labels=prob_labels, right=False)

    calib = df.groupby('prob_bucket', observed=True).agg(
        avg_est=('estimated_win_prob', 'mean'),
        actual_wr=('is_win', 'mean'),
        n=('status', 'count'),
    ).reset_index()

    # Scatter points — size proportional to sample count
    fig.add_trace(go.Scatter(
        x=calib['avg_est'] * 100, y=calib['actual_wr'] * 100,
        mode='markers+text',
        marker=dict(
            size=[max(8, min(40, n * 0.4)) for n in calib['n']],
            color='#44aaff', opacity=0.7,
            line=dict(width=1, color='white'),
        ),
        text=[f"n={n}" for n in calib['n']],
        textposition='top center',
        textfont=dict(size=9, color='#aaa'),
        name='Calibration',
        showlegend=False,
        hovertemplate='Est: %{x:.1f}%<br>Actual: %{y:.1f}%<br>Trades: %{text}<extra></extra>',
    ), row=4, col=2)

    # Perfect calibration diagonal
    fig.add_trace(go.Scatter(
        x=[35, 65], y=[35, 65],
        mode='lines',
        line=dict(dash='dash', color='rgba(255,255,0,0.4)', width=1),
        name='Perfect Calibration',
        showlegend=False,
    ), row=4, col=2)

    # ================================================================
    # ROW 5: Era Comparison
    # ================================================================
    era_metrics_list = []
    for era in ERA_BOUNDARIES:
        start = pd.Timestamp(era['start'])
        end = pd.Timestamp(era['end'])
        mask = (df['entry_time'] >= start) & (df['entry_time'] < end)
        era_df = df[mask]
        if len(era_df) == 0:
            continue
        m = compute_metrics(era_df)
        m['name'] = era['name']
        m['label'] = era['label']
        era_metrics_list.append(m)

    if era_metrics_list:
        era_names = [f"{e['name']}<br><sub>{e['label']}</sub>" for e in era_metrics_list]
        metric_configs = [
            ('Simple WR %', 'simple_wr', '#4488ff'),
            ('Dollar WR %', 'dollar_wr', '#44ff88'),
            ('Profit Factor', 'profit_factor', '#ff8844'),
            ('$/hr', 'dollar_per_hour', '#ff44aa'),
        ]

        for metric_label, metric_key, color in metric_configs:
            values = [e[metric_key] for e in era_metrics_list]
            fig.add_trace(go.Bar(
                x=era_names, y=values,
                name=metric_label,
                marker_color=color,
                text=[f"{v:.1f}" if metric_key != 'profit_factor' else f"{v:.2f}" for v in values],
                textposition='outside',
                textfont=dict(size=10),
            ), row=5, col=1)

        # Add trade count annotations
        for i, e in enumerate(era_metrics_list):
            fig.add_annotation(
                x=era_names[i], y=-3,
                text=f"n={e['total_trades']} ({e['hours_elapsed']:.0f}h)",
                showarrow=False,
                font=dict(size=9, color='#888'),
                xref=f'x{_get_axis_num(5, 1)}',
                yref=f'y{_get_axis_num(5, 1)}',
            )

    # ================================================================
    # ROW 6: Era 7 Feature Analysis
    # ================================================================

    # ROW 6, COL 1: Signal E Accuracy by Trend Category
    if len(sl_df) > 0 and 'signal_e' in sl_df.columns and sl_df['signal_e'].notna().sum() > 0:
        sl_e = sl_df[sl_df['signal_e'].notna()].copy()

        def classify_trend(row):
            if row['best_direction'] == 'YES' and row['signal_e'] > 0.52:
                return 'Bullish (>0.52)'
            elif row['best_direction'] == 'YES' and row['signal_e'] < 0.48:
                return 'Bearish (<0.48)'
            elif row['best_direction'] == 'NO' and row['signal_e'] < 0.48:
                return 'Bullish (>0.52)'  # For NO, low signal_e = agrees
            elif row['best_direction'] == 'NO' and row['signal_e'] > 0.52:
                return 'Bearish (<0.48)'  # For NO, high signal_e = disagrees
            else:
                return 'Neutral (0.48-0.52)'

        # Simpler approach: just bucket by signal_e value
        sl_e['trend_cat'] = pd.cut(
            sl_e['signal_e'],
            bins=[0, 0.48, 0.52, 1.0],
            labels=['Bearish (<0.48)', 'Neutral (0.48-0.52)', 'Bullish (>0.52)']
        )
        trend_stats = sl_e.groupby('trend_cat', observed=True).agg(
            total=('is_win', 'count'),
            wins=('is_win', 'sum'),
        ).reset_index()
        trend_stats['wr'] = trend_stats.apply(
            lambda r: r['wins'] / r['total'] * 100 if r['total'] > 0 else 0, axis=1)

        trend_colors = ['#ff4444', '#ffaa00', '#00ff88']
        fig.add_trace(go.Bar(
            x=trend_stats['trend_cat'].astype(str), y=trend_stats['wr'],
            text=[f"{r['wr']:.0f}%<br>n={r['total']}" for _, r in trend_stats.iterrows()],
            textposition='inside',
            textfont=dict(size=12, color='white'),
            marker_color=trend_colors[:len(trend_stats)],
            name='Signal E',
            showlegend=False,
        ), row=6, col=1)
        fig.add_hline(y=50, line_dash="dot", line_color="rgba(255,255,255,0.3)", row=6, col=1)

    # ROW 6, COL 2: Performance Feedback Impact
    if len(sl_df) > 0 and 'perf_adjustment' in sl_df.columns and sl_df['perf_adjustment'].notna().sum() > 0:
        sl_p = sl_df[sl_df['perf_adjustment'].notna()].copy()
        sl_p['adj_cat'] = 'No Adj'
        sl_p.loc[sl_p['perf_adjustment'] > 0.001, 'adj_cat'] = 'Boosted'
        sl_p.loc[sl_p['perf_adjustment'] < -0.001, 'adj_cat'] = 'Penalized'

        cat_order = ['Penalized', 'No Adj', 'Boosted']
        adj_stats = sl_p.groupby('adj_cat').agg(
            total=('is_win', 'count'),
            wins=('is_win', 'sum'),
            avg_adj=('perf_adjustment', 'mean'),
        )
        # Reindex to ensure consistent order
        adj_stats = adj_stats.reindex(cat_order).dropna(subset=['total']).reset_index()
        adj_stats['wr'] = adj_stats.apply(
            lambda r: r['wins'] / r['total'] * 100 if r['total'] > 0 else 0, axis=1)

        adj_colors = {'Penalized': '#ff4444', 'No Adj': '#888888', 'Boosted': '#00ff88'}
        fig.add_trace(go.Bar(
            x=adj_stats['adj_cat'], y=adj_stats['wr'],
            text=[f"{r['wr']:.0f}%<br>n={int(r['total'])}<br>adj={r['avg_adj']:+.3f}"
                  for _, r in adj_stats.iterrows()],
            textposition='inside',
            textfont=dict(size=11, color='white'),
            marker_color=[adj_colors.get(c, '#888') for c in adj_stats['adj_cat']],
            name='Perf Feedback',
            showlegend=False,
        ), row=6, col=2)
        fig.add_hline(y=50, line_dash="dot", line_color="rgba(255,255,255,0.3)", row=6, col=2)

    # ROW 6, COL 3: Hour Sizing Effectiveness (WR bars + multiplier line overlay)
    if len(df) > 0:
        all_hours = pd.DataFrame({'hour_utc': range(24)})
        hour_merged = all_hours.merge(hourly_stats, on='hour_utc', how='left').fillna(0)
        hour_merged['multiplier'] = hour_merged['hour_utc'].map(HOUR_SIZING_MULTIPLIER)
        hour_merged['mult_scaled'] = hour_merged['multiplier'] * 60  # Scale to WR axis

        bar_colors = []
        for _, r in hour_merged.iterrows():
            if r['total'] == 0:
                bar_colors.append('#333333')
            elif r['wr'] >= 50:
                bar_colors.append('#00ff88')
            else:
                bar_colors.append('#ff4444')

        fig.add_trace(go.Bar(
            x=hour_merged['hour_utc'], y=hour_merged['wr'],
            text=[f"{int(r['wr'])}%<br>n={int(r['total'])}" if r['total'] > 0 else ''
                  for _, r in hour_merged.iterrows()],
            textposition='outside',
            textfont=dict(size=7),
            marker_color=bar_colors,
            name='Hour WR',
            showlegend=False,
            opacity=0.7,
        ), row=6, col=3)

        # Multiplier line overlay (scaled to WR axis)
        fig.add_trace(go.Scatter(
            x=hour_merged['hour_utc'], y=hour_merged['mult_scaled'],
            mode='lines+markers',
            line=dict(color='#ffaa00', width=2, dash='dot'),
            marker=dict(size=4, color='#ffaa00'),
            name='Sizing Mult',
            showlegend=False,
            hovertemplate='Hour %{x}: Multiplier %{customdata:.2f}x<extra></extra>',
            customdata=hour_merged['multiplier'],
        ), row=6, col=3)

        fig.add_hline(y=50, line_dash="dot", line_color="rgba(255,255,255,0.3)", row=6, col=3)

    # ================================================================
    # ROW 7: Era 8 Feature Analysis (Adaptive Penalty)
    # ================================================================

    # ROW 7, COL 1: WR by Market Regime (BULL/FLAT/BEAR)
    if len(sl_df) > 0 and 'trend_regime' in sl_df.columns and sl_df['trend_regime'].notna().sum() > 0:
        sl_r = sl_df[sl_df['trend_regime'].notna()].copy()
        regime_order = ['BEAR', 'FLAT', 'BULL']
        regime_stats = sl_r.groupby('trend_regime').agg(
            total=('is_win', 'count'),
            wins=('is_win', 'sum'),
        )
        regime_stats = regime_stats.reindex(regime_order).dropna(subset=['total']).reset_index()
        regime_stats['wr'] = regime_stats.apply(
            lambda r: r['wins'] / r['total'] * 100 if r['total'] > 0 else 0, axis=1)

        regime_colors = {'BEAR': '#ff4444', 'FLAT': '#ffaa00', 'BULL': '#00ff88'}
        fig.add_trace(go.Bar(
            x=regime_stats['trend_regime'], y=regime_stats['wr'],
            text=[f"{r['wr']:.0f}%<br>n={int(r['total'])}" for _, r in regime_stats.iterrows()],
            textposition='inside',
            textfont=dict(size=12, color='white'),
            marker_color=[regime_colors.get(r, '#888') for r in regime_stats['trend_regime']],
            name='Regime WR',
            showlegend=False,
        ), row=7, col=1)
        fig.add_hline(y=50, line_dash="dot", line_color="rgba(255,255,255,0.3)", row=7, col=1)

    # ROW 7, COL 2: Adaptive Penalty Distribution (histogram)
    if len(sl_df) > 0 and 'adaptive_penalty' in sl_df.columns and sl_df['adaptive_penalty'].notna().sum() > 0:
        sl_ap = sl_df[sl_df['adaptive_penalty'].notna()].copy()

        # Split wins vs losses for overlapping histograms
        wins_pen = sl_ap[sl_ap['is_win'] == 1]['adaptive_penalty']
        losses_pen = sl_ap[sl_ap['is_win'] == 0]['adaptive_penalty']

        fig.add_trace(go.Histogram(
            x=wins_pen, name='Wins', marker_color='rgba(0,255,136,0.5)',
            nbinsx=20, showlegend=False,
            hovertemplate='Penalty: %{x:.4f}<br>Count: %{y}<extra>Wins</extra>',
        ), row=7, col=2)
        fig.add_trace(go.Histogram(
            x=losses_pen, name='Losses', marker_color='rgba(255,68,68,0.5)',
            nbinsx=20, showlegend=False,
            hovertemplate='Penalty: %{x:.4f}<br>Count: %{y}<extra>Losses</extra>',
        ), row=7, col=2)
        fig.update_layout(barmode='overlay')
        # Mark the zero line (where penalty flips from YES→NO penalty)
        fig.add_vline(x=0, line_dash="dash", line_color="rgba(255,255,255,0.5)", line_width=1, row=7, col=2)

    # ROW 7, COL 3: Macro vs Asset Trend scatter
    if (len(sl_df) > 0 and 'trend_20m' in sl_df.columns and 'macro_trend' in sl_df.columns
            and sl_df['trend_20m'].notna().sum() > 0):
        sl_t = sl_df[sl_df['trend_20m'].notna() & sl_df['macro_trend'].notna()].copy()
        sl_t['trend_20m_pct'] = sl_t['trend_20m'] * 100
        sl_t['macro_trend_pct'] = sl_t['macro_trend'] * 100

        win_mask = sl_t['is_win'] == 1
        fig.add_trace(go.Scatter(
            x=sl_t.loc[win_mask, 'macro_trend_pct'],
            y=sl_t.loc[win_mask, 'trend_20m_pct'],
            mode='markers', marker=dict(color='#00ff88', size=6, opacity=0.6),
            name='Win', showlegend=False,
            hovertemplate='Macro: %{x:.3f}%<br>Asset: %{y:.3f}%<extra>Win</extra>',
        ), row=7, col=3)
        fig.add_trace(go.Scatter(
            x=sl_t.loc[~win_mask, 'macro_trend_pct'],
            y=sl_t.loc[~win_mask, 'trend_20m_pct'],
            mode='markers', marker=dict(color='#ff4444', size=6, opacity=0.6),
            name='Loss', showlegend=False,
            hovertemplate='Macro: %{x:.3f}%<br>Asset: %{y:.3f}%<extra>Loss</extra>',
        ), row=7, col=3)
        # Crosshair at origin
        fig.add_hline(y=0, line_dash="dot", line_color="rgba(255,255,255,0.2)", row=7, col=3)
        fig.add_vline(x=0, line_dash="dot", line_color="rgba(255,255,255,0.2)", row=7, col=3)

    # ================================================================
    # ROW 8: Balance Over Time
    # ================================================================
    if len(balance_df) > 0:
        # Downsample for performance
        step = max(1, len(balance_df) // 500)
        bal_sampled = balance_df.iloc[::step]

        fig.add_trace(go.Scatter(
            x=bal_sampled['scan_time'], y=bal_sampled['balance_dollars'],
            mode='lines',
            name='Balance',
            line=dict(color='#ffaa00', width=1.5),
            fill='tozeroy',
            fillcolor='rgba(255,170,0,0.05)',
            hovertemplate='Time: %{x}<br>Balance: $%{y:.2f}<extra></extra>',
            showlegend=False,
        ), row=8, col=1)

        # Era boundaries on balance chart too
        for era in ERA_BOUNDARIES[1:]:
            era_ts = pd.Timestamp(era['start'])
            if era_ts >= bal_sampled['scan_time'].min() and era_ts <= bal_sampled['scan_time'].max():
                fig.add_vline(
                    x=era_ts.timestamp() * 1000,
                    line_dash="dash", line_color="rgba(255,255,0,0.3)", line_width=1,
                    row=8, col=1,
                )

    # ================================================================
    # LAYOUT STYLING
    # ================================================================
    fig.update_layout(
        template='plotly_dark',
        height=2800,
        width=1500,
        showlegend=True,
        legend=dict(
            orientation='h', yanchor='bottom', y=0.48, xanchor='center', x=0.5,
            font=dict(size=10),
        ),
        paper_bgcolor='#1a1a2e',
        plot_bgcolor='#16213e',
        font=dict(color='#e0e0e0', size=11),
        margin=dict(t=40, b=40, l=60, r=40),
    )

    fig.update_xaxes(gridcolor='rgba(255,255,255,0.05)')
    fig.update_yaxes(gridcolor='rgba(255,255,255,0.05)')

    # Y-axis labels
    fig.update_yaxes(title_text='$', row=1, col=1)
    fig.update_yaxes(title_text='WR %', row=1, col=3)
    fig.update_yaxes(title_text='WR %', row=2, col=1)
    fig.update_yaxes(title_text='WR %', row=2, col=2)
    fig.update_yaxes(title_text='WR %', row=2, col=3)
    fig.update_yaxes(title_text='WR %', row=3, col=1)
    fig.update_yaxes(title_text='$', row=3, col=2)
    fig.update_yaxes(title_text='WR %', row=3, col=3)
    fig.update_yaxes(title_text='WR %', row=4, col=1)
    fig.update_yaxes(title_text='Actual WR %', row=4, col=2)
    fig.update_xaxes(title_text='Estimated Win Prob %', row=4, col=2)
    fig.update_xaxes(title_text='Hour (UTC)', row=4, col=1)
    fig.update_yaxes(title_text='WR %', row=6, col=1)
    fig.update_yaxes(title_text='WR %', row=6, col=2)
    fig.update_yaxes(title_text='WR % / Mult', row=6, col=3)
    fig.update_xaxes(title_text='Hour (UTC)', row=6, col=3)
    fig.update_yaxes(title_text='WR %', row=7, col=1)
    fig.update_yaxes(title_text='Count', row=7, col=2)
    fig.update_xaxes(title_text='Penalty Value', row=7, col=2)
    fig.update_yaxes(title_text='Asset Trend %', row=7, col=3)
    fig.update_xaxes(title_text='Macro Trend %', row=7, col=3)
    fig.update_yaxes(title_text='$', row=8, col=1)

    # Barmode for era comparison (grouped side-by-side)
    fig.update_layout(barmode='group')

    return fig


def _get_axis_num(row, col):
    """Get the plotly axis number for a given subplot position.
    For 8x3 grid with our specs, compute the sequential subplot index."""
    # Plotly assigns axis numbers sequentially based on subplot positions
    # row1=[1,2], row2=[3,4,5], row3=[6,7,8], row4=[9,10], row5=[11],
    # row6=[12,13,14], row7=[15,16,17], row8=[18]
    mapping = {
        (1, 1): '', (1, 3): '2',
        (2, 1): '3', (2, 2): '4', (2, 3): '5',
        (3, 1): '6', (3, 2): '7', (3, 3): '8',
        (4, 1): '9', (4, 2): '10',
        (5, 1): '11',
        (6, 1): '12', (6, 2): '13', (6, 3): '14',
        (7, 1): '15', (7, 2): '16', (7, 3): '17',
        (8, 1): '18',
    }
    return mapping.get((row, col), '')


# ============================================================
# HTML OUTPUT
# ============================================================

def write_html(fig, metrics, output_path):
    """Write the complete dashboard HTML file."""
    plotly_div = fig.to_html(full_html=False, include_plotlyjs='cdn')
    kpi_html = build_kpi_html(metrics)
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')

    full_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Kalshi Crypto Trader Dashboard</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            background: #1a1a2e;
            color: #e0e0e0;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            padding: 20px;
        }}
        .dashboard-header {{
            text-align: center;
            margin-bottom: 20px;
        }}
        .dashboard-title {{
            font-size: 28px;
            font-weight: bold;
            color: white;
            margin-bottom: 4px;
        }}
        .dashboard-subtitle {{
            font-size: 13px;
            color: #666;
        }}
        .kpi-row {{
            display: flex;
            justify-content: space-around;
            margin-bottom: 20px;
            gap: 10px;
            flex-wrap: wrap;
        }}
        .kpi-card {{
            background: #16213e;
            border-radius: 12px;
            padding: 14px 20px;
            text-align: center;
            flex: 1;
            min-width: 140px;
            border: 1px solid #2a2a4a;
            transition: transform 0.2s;
        }}
        .kpi-card:hover {{
            transform: translateY(-2px);
            border-color: #444;
        }}
        .kpi-label {{
            font-size: 11px;
            color: #888;
            text-transform: uppercase;
            letter-spacing: 1px;
        }}
        .kpi-value {{
            font-size: 26px;
            font-weight: bold;
            margin-top: 4px;
        }}
        .kpi-sub {{
            font-size: 10px;
            color: #555;
            margin-top: 2px;
        }}
        .chart-container {{
            border-radius: 12px;
            overflow: hidden;
        }}
    </style>
</head>
<body>
    <div class="dashboard-header">
        <div class="dashboard-title">Kalshi 15-Min Crypto Trader Dashboard</div>
        <div class="dashboard-subtitle">
            Generated: {timestamp} &nbsp;|&nbsp;
            {metrics['total_trades']} resolved trades over {metrics['hours_elapsed']:.1f} hours &nbsp;|&nbsp;
            Avg win: ${metrics['avg_win_dollars']:.2f} &nbsp; Avg loss: ${metrics['avg_loss_dollars']:.2f}
        </div>
    </div>
    {kpi_html}
    <div class="chart-container">
        {plotly_div}
    </div>
</body>
</html>"""

    with open(output_path, 'w') as f:
        f.write(full_html)

    print(f"Dashboard written to: {output_path}")
    print(f"Open in browser: file://{output_path}")


# ============================================================
# MAIN
# ============================================================

def main():
    print("Loading data...")
    conn = sqlite3.connect(DB_PATH)

    df = load_trades(conn)
    balance_df = load_balance(conn)
    sl_df = load_signal_log(conn)
    conn.close()

    print(f"  Loaded {len(df)} resolved trades, {len(balance_df)} balance snapshots, "
          f"{len(sl_df)} signal log entries")

    metrics = compute_metrics(df)
    print(f"  Net P&L: ${metrics['net_pnl_dollars']:+.2f} | WR: {metrics['simple_wr']:.1f}% | "
          f"PF: {metrics['profit_factor']:.2f}x | $/hr: ${metrics['dollar_per_hour']:.2f}")

    print("Building dashboard...")
    fig = build_dashboard(df, balance_df, sl_df, metrics)

    print("Writing HTML...")
    write_html(fig, metrics, OUTPUT_PATH)

    print("Done!")


if __name__ == '__main__':
    main()
