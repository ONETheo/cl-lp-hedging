#!/usr/bin/env python3
"""
Optimize stop loss buffer for the two best thresholds: 43/59 and 44/57
Test stop losses from 10 to 30 ticks.
"""

import pandas as pd
import numpy as np

CSV_FILE_PATH = 'cbbtc_prices_sept2025.csv'
CAPITAL = 2000
RANGE_WIDTH_PCT = 0.01
ANNUAL_FEE_RATE = 0.60

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
    return hodl_value - lp_value

def simulate_with_stop(df, short_threshold, long_threshold, stop_buffer):
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
                hedge_position = {'type': 'short', 'entry_price': price, 'stop_tick': min(short_threshold + stop_buffer, 95)}
            elif tick >= long_threshold:
                hedge_position = {'type': 'long', 'entry_price': price, 'stop_tick': max(long_threshold - stop_buffer, 5)}

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
print("OPTIMIZING STOP LOSS FOR BEST THRESHOLDS")
print(f"{'='*80}")
print(f"\nTesting:")
print(f"  Thresholds: 43/59 and 44/57")
print(f"  Stop loss: 10, 12, 15, 18, 20, 25, 30 ticks")
print(f"  Total tests: 14\n")

results = []

for short_t, long_t in [(43, 59), (44, 57)]:
    print(f"\nTesting {short_t}/{long_t}:")

    for stop_buffer in [10, 12, 15, 18, 20, 25, 30]:
        result = simulate_with_stop(df, short_t, long_t, stop_buffer)
        result['short'] = short_t
        result['long'] = long_t
        result['stop'] = stop_buffer
        results.append(result)

        print(f"  Stop {stop_buffer}: ${result['net_pnl']:.2f} (IL: {result['il_reduction_pct']:.1f}%, WR: {result['win_rate']:.1f}%)")

results_df = pd.DataFrame(results)

print(f"\n{'='*80}")
print("RESULTS BY THRESHOLD")
print(f"{'='*80}")

for short_t, long_t in [(43, 59), (44, 57)]:
    subset = results_df[(results_df['short'] == short_t) & (results_df['long'] == long_t)]
    best_stop = subset.loc[subset['net_pnl'].idxmax()]

    print(f"\n{short_t}/{long_t} - Best stop: {int(best_stop['stop'])} ticks")
    print(f"  Net P&L: ${best_stop['net_pnl']:.2f}")
    print(f"  IL reduction: {best_stop['il_reduction_pct']:.1f}%")
    print(f"  Win rate: {best_stop['win_rate']:.1f}%")
    print(f"  Whipsaws: {int(best_stop['whipsaw_count'])}/{int(best_stop['total_trades'])}")

    print(f"\n  All results:")
    for idx, row in subset.iterrows():
        print(f"    Stop {int(row['stop'])}: ${row['net_pnl']:.2f} (IL: {row['il_reduction_pct']:.1f}%, WR: {row['win_rate']:.1f}%)")

# Overall best
best = results_df.loc[results_df['net_pnl'].idxmax()]

print(f"\n{'='*80}")
print("ULTIMATE OPTIMAL CONFIGURATION")
print(f"{'='*80}")
print(f"\nThreshold: {int(best['short'])}/{int(best['long'])}")
print(f"Stop loss: {int(best['stop'])} ticks")
print(f"\nPerformance:")
print(f"  Net P&L: ${best['net_pnl']:.2f} ({best['net_pnl']/CAPITAL*100:.2f}% monthly)")
print(f"  IL reduction: {best['il_reduction_pct']:.1f}%")
print(f"  Hedge P&L: ${best['hedge_pnl']:.2f}")
print(f"  Win rate: {best['win_rate']:.1f}%")
print(f"  Whipsaws: {int(best['whipsaw_count'])}/{int(best['total_trades'])} trades")

# Compare to baseline 15-tick stop
baseline_15 = results_df[(results_df['short'] == best['short']) &
                         (results_df['long'] == best['long']) &
                         (results_df['stop'] == 15)]

if len(baseline_15) > 0:
    baseline_15 = baseline_15.iloc[0]
    improvement = best['net_pnl'] - baseline_15['net_pnl']
    print(f"\nImprovement vs 15-tick stop: ${improvement:.2f} ({improvement/CAPITAL*100:.2f}%)")

print(f"\n{'='*80}")
print("STOP LOSS INSIGHTS")
print(f"{'='*80}")

print(f"""
1. OPTIMAL STOP LOSS: {int(best['stop'])} ticks
   - Balances whipsaw protection vs letting winners run
   - {"Tighter than 15-tick baseline" if best['stop'] < 15 else "Wider than 15-tick baseline" if best['stop'] > 15 else "Confirms 15-tick baseline"}

2. TRADE-OFFS:
   - Tighter stops (10-12): Fewer losses per whipsaw, but more whipsaws
   - Wider stops (20-30): Fewer whipsaws, but bigger losses when wrong
   - Sweet spot: {int(best['stop'])} ticks

3. SENSITIVITY:
   - {"High - stop loss matters significantly" if max(results_df['net_pnl']) - min(results_df['net_pnl']) > 50 else "Low - stop loss doesn't matter much"}
   - Range: ${results_df['net_pnl'].min():.2f} to ${results_df['net_pnl'].max():.2f}
   - Spread: ${results_df['net_pnl'].max() - results_df['net_pnl'].min():.2f}
""")

# Save results
results_df.to_csv('stop_loss_optimization_results.csv', index=False)
print("\nResults saved to: stop_loss_optimization_results.csv")
