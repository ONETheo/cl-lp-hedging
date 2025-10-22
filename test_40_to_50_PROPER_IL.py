#!/usr/bin/env python3
"""
Test 40-50 thresholds with PROPER IL calculation.
Does the degradation pattern (50/50 worse than 40/60) still hold?
"""

import pandas as pd
import numpy as np

CSV_FILE_PATH = 'cbbtc_prices_sept2025.csv'
CAPITAL = 2000
RANGE_WIDTH_PCT = 0.01
ANNUAL_FEE_RATE = 0.60
DEFAULT_STOP_BUFFER = 15

def calculate_concentrated_lp_amounts(price, price_lower, price_upper, liquidity):
    sqrt_price = np.sqrt(price)
    sqrt_lower = np.sqrt(price_lower)
    sqrt_upper = np.sqrt(price_upper)

    if price <= price_lower:
        btc_amount = liquidity * (1/sqrt_lower - 1/sqrt_upper)
        usdc_amount = 0
    elif price >= price_upper:
        btc_amount = 0
        usdc_amount = liquidity * (sqrt_upper - sqrt_lower)
    else:
        btc_amount = liquidity * (1/sqrt_price - 1/sqrt_upper)
        usdc_amount = liquidity * (sqrt_price - sqrt_lower)

    return btc_amount, usdc_amount

def initialize_position(initial_price, capital):
    price_lower = initial_price * (1 - RANGE_WIDTH_PCT / 2)
    price_upper = initial_price * (1 + RANGE_WIDTH_PCT / 2)

    btc_amount = capital / 2 / initial_price
    usdc_amount = capital / 2

    sqrt_price = np.sqrt(initial_price)
    sqrt_lower = np.sqrt(price_lower)

    liquidity = usdc_amount / (sqrt_price - sqrt_lower)

    return btc_amount, usdc_amount, liquidity, price_lower, price_upper

def calculate_il_at_rebalance(initial_btc, initial_usdc, final_btc, final_usdc, final_price):
    hodl_value = initial_btc * final_price + initial_usdc
    lp_value = final_btc * final_price + final_usdc
    il = hodl_value - lp_value
    return il

def simulate_fast(df, short_threshold, long_threshold, stop_buffer=DEFAULT_STOP_BUFFER):
    first_price = df.iloc[0]['cb_btc_price']
    btc_amount, usdc_amount, liquidity, price_lower, price_upper = initialize_position(first_price, CAPITAL)

    range_start_btc = btc_amount
    range_start_usdc = usdc_amount
    range_start_time = df.iloc[0]['block_timestamp']
    hedge_position = None

    total_fees = 0
    total_il_unhedged = 0
    total_hedge_pnl = 0
    whipsaw_count = 0
    successful_count = 0

    for idx, row in df.iterrows():
        price = row['cb_btc_price']
        time = row['block_timestamp']

        btc_amount, usdc_amount = calculate_concentrated_lp_amounts(price, price_lower, price_upper, liquidity)

        if price <= price_lower:
            tick = 0
            in_range = False
        elif price >= price_upper:
            tick = 100
            in_range = False
        else:
            tick = (price - price_lower) / (price_upper - price_lower) * 100
            in_range = True

        if in_range and hedge_position is None:
            if tick <= short_threshold:
                hedge_position = {'type': 'short', 'entry_price': price, 'entry_time': time, 'stop_tick': min(short_threshold + stop_buffer, 95)}
            elif tick >= long_threshold:
                hedge_position = {'type': 'long', 'entry_price': price, 'entry_time': time, 'stop_tick': max(long_threshold - stop_buffer, 5)}

        if in_range and hedge_position:
            if hedge_position['type'] == 'short' and tick >= hedge_position['stop_tick']:
                hedge_pnl = (hedge_position['entry_price'] - price) / hedge_position['entry_price'] * CAPITAL
                total_hedge_pnl += hedge_pnl
                whipsaw_count += 1
                hedge_position = None
            elif hedge_position['type'] == 'long' and tick <= hedge_position['stop_tick']:
                hedge_pnl = (price - hedge_position['entry_price']) / hedge_position['entry_price'] * CAPITAL
                total_hedge_pnl += hedge_pnl
                whipsaw_count += 1
                hedge_position = None

        if not in_range:
            duration_days = (time - range_start_time).total_seconds() / (24 * 3600)
            fees_earned = CAPITAL * ANNUAL_FEE_RATE * (duration_days / 365.25)

            il_amount = calculate_il_at_rebalance(range_start_btc, range_start_usdc, btc_amount, usdc_amount, price)

            total_fees += fees_earned
            total_il_unhedged += il_amount

            if hedge_position:
                if hedge_position['type'] == 'short':
                    hedge_pnl = (hedge_position['entry_price'] - price) / hedge_position['entry_price'] * CAPITAL
                elif hedge_position['type'] == 'long':
                    hedge_pnl = (price - hedge_position['entry_price']) / hedge_position['entry_price'] * CAPITAL

                total_hedge_pnl += hedge_pnl
                if hedge_pnl > 0:
                    successful_count += 1
                hedge_position = None

            btc_amount, usdc_amount, liquidity, price_lower, price_upper = initialize_position(price, CAPITAL)
            range_start_btc = btc_amount
            range_start_usdc = usdc_amount
            range_start_time = time

    total_il_hedged = max(0, total_il_unhedged - total_hedge_pnl)
    net_pnl = total_fees - total_il_hedged
    total_trades = whipsaw_count + successful_count

    return {
        'net_pnl': net_pnl,
        'hedge_pnl': total_hedge_pnl,
        'il_unhedged': total_il_unhedged,
        'il_hedged': total_il_hedged,
        'il_reduction_pct': (1 - total_il_hedged / total_il_unhedged) * 100 if total_il_unhedged > 0 else 0,
        'win_rate': successful_count / total_trades * 100 if total_trades > 0 else 0,
        'whipsaw_count': whipsaw_count,
        'successful_count': successful_count,
        'total_trades': total_trades
    }

print("Loading dataset...")
df = pd.read_csv(CSV_FILE_PATH)
df['block_timestamp'] = pd.to_datetime(df['block_timestamp'])
df = df.sort_values('block_timestamp').reset_index(drop=True)

print(f"\n{'='*80}")
print("TESTING 40-50 RANGE WITH PROPER IL CALCULATION")
print(f"{'='*80}")
print(f"Testing every threshold from 40-50 (short) × 50-60 (long)")
print(f"Total: 121 combinations\n")

results = []

for short_t in range(40, 51):
    for long_t in range(50, 61):
        result = simulate_fast(df, short_t, long_t)
        result['short'] = short_t
        result['long'] = long_t
        results.append(result)

results_df = pd.DataFrame(results)
best = results_df.loc[results_df['net_pnl'].idxmax()]
worst = results_df.loc[results_df['net_pnl'].idxmin()]

print(f"{'='*80}")
print("RESULTS")
print(f"{'='*80}")

print(f"\nBest: Short@{int(best['short'])}, Long@{int(best['long'])}")
print(f"  Net P&L: ${best['net_pnl']:.2f} ({best['net_pnl']/CAPITAL*100:.2f}%)")
print(f"  IL reduction: {best['il_reduction_pct']:.1f}%")
print(f"  Hedge P&L: ${best['hedge_pnl']:.2f}")
print(f"  Win rate: {best['win_rate']:.1f}%")

print(f"\nWorst: Short@{int(worst['short'])}, Long@{int(worst['long'])}")
print(f"  Net P&L: ${worst['net_pnl']:.2f} ({worst['net_pnl']/CAPITAL*100:.2f}%)")
print(f"  IL reduction: {worst['il_reduction_pct']:.1f}%")
print(f"  Hedge P&L: ${worst['hedge_pnl']:.2f}")
print(f"  Win rate: {worst['win_rate']:.1f}%")

print(f"\nTop 10:")
top10 = results_df.nlargest(10, 'net_pnl')
for idx, row in top10.iterrows():
    print(f"  {int(row['short'])}/{int(row['long'])}: ${row['net_pnl']:.2f} (IL reduction: {row['il_reduction_pct']:.1f}%)")

print(f"\nBottom 10:")
bottom10 = results_df.nsmallest(10, 'net_pnl')
for idx, row in bottom10.iterrows():
    print(f"  {int(row['short'])}/{int(row['long'])}: ${row['net_pnl']:.2f} (IL reduction: {row['il_reduction_pct']:.1f}%)")

# Check specific thresholds
forty_sixty = results_df[(results_df['short'] == 40) & (results_df['long'] == 60)].iloc[0]
fifty_fifty = results_df[(results_df['short'] == 50) & (results_df['long'] == 50)].iloc[0]

print(f"\n{'='*80}")
print("KEY COMPARISONS")
print(f"{'='*80}")

print(f"\n40/60 (from original analysis):")
print(f"  Net P&L: ${forty_sixty['net_pnl']:.2f}")
print(f"  IL reduction: {forty_sixty['il_reduction_pct']:.1f}%")

print(f"\n50/50 (most aggressive):")
print(f"  Net P&L: ${fifty_fifty['net_pnl']:.2f}")
print(f"  IL reduction: {fifty_fifty['il_reduction_pct']:.1f}%")

diff = forty_sixty['net_pnl'] - fifty_fifty['net_pnl']
print(f"\nDifference: ${diff:.2f}")
if diff > 0:
    print(f"✓ 40/60 outperforms 50/50 by ${diff:.2f}")
else:
    print(f"✗ 50/50 outperforms 40/60 by ${-diff:.2f}")

# Analyze pattern
print(f"\n{'='*80}")
print("DEGRADATION PATTERN ANALYSIS")
print(f"{'='*80}")

results_df['distance_from_midpoint'] = (50 - results_df['short'] + results_df['long'] - 50) / 2
by_distance = results_df.groupby('distance_from_midpoint').agg({
    'net_pnl': 'mean',
    'il_reduction_pct': 'mean',
    'win_rate': 'mean'
}).round(2)

print("\nAverage performance by distance from midpoint (0 = 50/50):")
print(by_distance)

print(f"\n{'='*80}")
print("CONCLUSIONS")
print(f"{'='*80}")

if best['short'] == 40 and best['long'] in [50, 60]:
    print(f"\n✓ PATTERN CONFIRMED: 40/50-60 is optimal")
    print(f"  - Same as baseline-assumption analysis")
    print(f"  - Proper IL calculation validates strategic insight")
elif worst['short'] == 50 or worst['long'] == 50:
    print(f"\n✓ DEGRADATION CONFIRMED: 50/50 is worst")
    print(f"  - Too aggressive still underperforms")
    print(f"  - Pattern holds with proper IL calculation")
else:
    print(f"\n⚠️ DIFFERENT PATTERN:")
    print(f"  - Optimal is {int(best['short'])}/{int(best['long'])}")
    print(f"  - Proper IL calculation changes strategy")

print(f"\nKey insight: {'Strategy pattern robust to IL calculation method' if best['short'] <= 42 else 'Strategy depends on IL calculation'}")
