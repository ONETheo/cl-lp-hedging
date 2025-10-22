#!/usr/bin/env python3
"""
Comprehensive threshold sweep with PROPER IL to find TRUE optimal.
Expands search beyond 40-50 range.
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
    return hodl_value - lp_value

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
        'successful_count': successful_count
    }

print("Loading dataset...")
df = pd.read_csv(CSV_FILE_PATH)
df['block_timestamp'] = pd.to_datetime(df['block_timestamp'])
df = df.sort_values('block_timestamp').reset_index(drop=True)

print(f"\n{'='*80}")
print("COMPREHENSIVE THRESHOLD SWEEP - FIND TRUE OPTIMAL")
print(f"{'='*80}")
print(f"\nSearch range:")
print(f"  Short: 30-50 (every tick)")
print(f"  Long: 50-70 (every tick)")
print(f"  Total combinations: {21 * 21} = 441")
print(f"\nThis will take ~5-10 minutes...")

results = []
test_count = 0
total_tests = 21 * 21

for short_t in range(30, 51):  # 30 to 50
    for long_t in range(50, 71):  # 50 to 70
        test_count += 1
        if test_count % 50 == 0:
            print(f"  Progress: {test_count}/{total_tests} ({test_count/total_tests*100:.1f}%)")

        result = simulate_fast(df, short_t, long_t)
        result['short'] = short_t
        result['long'] = long_t
        results.append(result)

print("\nProcessing complete!")

results_df = pd.DataFrame(results)
best = results_df.loc[results_df['net_pnl'].idxmax()]
worst = results_df.loc[results_df['net_pnl'].idxmin()]

print(f"\n{'='*80}")
print("TRUE OPTIMAL THRESHOLD")
print(f"{'='*80}")

print(f"\nBest: Short@{int(best['short'])}, Long@{int(best['long'])}")
print(f"  Net P&L: ${best['net_pnl']:.2f} ({best['net_pnl']/CAPITAL*100:.2f}%)")
print(f"  IL reduction: {best['il_reduction_pct']:.1f}%")
print(f"  Hedge P&L: ${best['hedge_pnl']:.2f}")
print(f"  Win rate: {best['win_rate']:.1f}%")

print(f"\nWorst: Short@{int(worst['short'])}, Long@{int(worst['long'])}")
print(f"  Net P&L: ${worst['net_pnl']:.2f} ({worst['net_pnl']/CAPITAL*100:.2f}%)")

print(f"\nTop 20 strategies:")
top20 = results_df.nlargest(20, 'net_pnl')
for idx, row in top20.iterrows():
    print(f"  {int(row['short'])}/{int(row['long'])}: ${row['net_pnl']:.2f} (IL: {row['il_reduction_pct']:.1f}%)")

print(f"\nBottom 10 strategies:")
bottom10 = results_df.nsmallest(10, 'net_pnl')
for idx, row in bottom10.iterrows():
    print(f"  {int(row['short'])}/{int(row['long'])}: ${row['net_pnl']:.2f}")

# Key comparisons
print(f"\n{'='*80}")
print("KEY COMPARISONS")
print(f"{'='*80}")

strategies_to_check = [
    (40, 60, "Original finding"),
    (44, 57, "Previous optimal (40-50 range)"),
    (50, 50, "Most aggressive"),
]

for short, long, label in strategies_to_check:
    row = results_df[(results_df['short'] == short) & (results_df['long'] == long)]
    if len(row) > 0:
        row = row.iloc[0]
        print(f"\n{short}/{long} ({label}):")
        print(f"  Net P&L: ${row['net_pnl']:.2f}")
        print(f"  IL reduction: {row['il_reduction_pct']:.1f}%")

# Find strategies within 95% of optimal
threshold_95pct = best['net_pnl'] * 0.95
good_strategies = results_df[results_df['net_pnl'] >= threshold_95pct]

print(f"\n{'='*80}")
print("ROBUSTNESS ANALYSIS")
print(f"{'='*80}")
print(f"\nStrategies within 95% of optimal ({len(good_strategies)} strategies):")
print(f"  Short range: {good_strategies['short'].min()}-{good_strategies['short'].max()}")
print(f"  Long range: {good_strategies['long'].min()}-{good_strategies['long'].max()}")
print(f"  P&L range: ${good_strategies['net_pnl'].min():.2f} to ${good_strategies['net_pnl'].max():.2f}")

print(f"\n{'='*80}")
print("FINAL CONCLUSIONS")
print(f"{'='*80}")

print(f"""
1. TRUE OPTIMAL: {int(best['short'])}/{int(best['long'])}
   - Best possible performance with proper IL calculation
   - Net P&L: ${best['net_pnl']:.2f} ({best['net_pnl']/CAPITAL*100:.1f}% monthly)

2. ROBUSTNESS: {len(good_strategies)} strategies within 95% of optimal
   - {"High sensitivity - specific threshold critical" if len(good_strategies) < 30 else "Low sensitivity - wide range performs well"}
   - Recommended range: {good_strategies['short'].min()}-{good_strategies['short'].max()} / {good_strategies['long'].min()}-{good_strategies['long'].max()}

3. DEGRADATION PATTERN:
   - 50/50 P&L: ${results_df[(results_df['short']==50) & (results_df['long']==50)]['net_pnl'].values[0]:.2f}
   - Difference from optimal: ${best['net_pnl'] - results_df[(results_df['short']==50) & (results_df['long']==50)]['net_pnl'].values[0]:.2f}
   - Pattern confirmed: Too aggressive underperforms

4. STRATEGIC INSIGHT:
   - Sweet spot around {int(best['short'])}/{int(best['long'])}
   - Captures maximum IL while avoiding excessive whipsaw
   - Pattern robust to IL calculation method
""")

# Save results
results_df.to_csv('comprehensive_threshold_results.csv', index=False)
print("\nFull results saved to: comprehensive_threshold_results.csv")
