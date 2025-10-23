#!/usr/bin/env python3
"""
LP Hedging IL Analysis - Corrected calculations without fees
Shows pure impermanent loss and hedge effectiveness
"""

import csv
import math
from datetime import datetime
import os
import sys

# Configuration
CAPITAL = 2000
RANGE_WIDTH_PCT = 0.01  # 1% range
CSV_FILE = 'cbbtc_prices_sept2025.csv'

def load_data(filepath):
    """Load CSV data with error handling"""
    if not os.path.exists(filepath):
        print(f"ERROR: Data file '{filepath}' not found!")
        print(f"Please ensure the file is in the current directory: {os.getcwd()}")
        sys.exit(1)

    try:
        data = []
        with open(filepath, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                data.append({
                    'timestamp': datetime.fromisoformat(row['block_timestamp'].replace('Z', '+00:00')),
                    'price': float(row['cb_btc_price'])
                })
        if len(data) == 0:
            print(f"ERROR: No data found in '{filepath}'")
            sys.exit(1)
        return data
    except Exception as e:
        print(f"ERROR reading CSV file: {e}")
        sys.exit(1)

def calculate_concentrated_lp_amounts(price, price_lower, price_upper, liquidity):
    sqrt_price = math.sqrt(price)
    sqrt_lower = math.sqrt(price_lower)
    sqrt_upper = math.sqrt(price_upper)

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

    sqrt_price = math.sqrt(initial_price)
    sqrt_lower = math.sqrt(price_lower)
    liquidity = usdc_amount / (sqrt_price - sqrt_lower)

    return btc_amount, usdc_amount, liquidity, price_lower, price_upper

def simulate_strategy(data, short_threshold, long_threshold, stop_buffer):
    first_price = data[0]['price']
    btc_amount, usdc_amount, liquidity, price_lower, price_upper = initialize_position(first_price, CAPITAL)

    range_start_btc = btc_amount
    range_start_usdc = usdc_amount

    hedge_position = None
    total_il = 0
    total_hedge_pnl = 0
    rebalance_count = 0
    successful_hedges = 0
    whipsaws = 0
    total_trades = 0

    for row in data:
        price = row['price']

        btc_amount, usdc_amount = calculate_concentrated_lp_amounts(
            price, price_lower, price_upper, liquidity
        )

        if price <= price_lower:
            tick = 0
            in_range = False
        elif price >= price_upper:
            tick = 100
            in_range = False
        else:
            tick = (price - price_lower) / (price_upper - price_lower) * 100
            in_range = True

        # Hedge entry
        if in_range and hedge_position is None:
            if tick <= short_threshold:
                hedge_position = {
                    'type': 'short',
                    'entry_price': price,
                    'stop_tick': min(short_threshold + stop_buffer, 95)
                }
                total_trades += 1
            elif tick >= long_threshold:
                hedge_position = {
                    'type': 'long',
                    'entry_price': price,
                    'stop_tick': max(long_threshold - stop_buffer, 5)
                }
                total_trades += 1

        # Stop loss
        if in_range and hedge_position:
            if hedge_position['type'] == 'short' and tick >= hedge_position['stop_tick']:
                hedge_pnl = (hedge_position['entry_price'] - price) / hedge_position['entry_price'] * CAPITAL
                total_hedge_pnl += hedge_pnl
                if hedge_pnl < 0:
                    whipsaws += 1
                hedge_position = None
            elif hedge_position['type'] == 'long' and tick <= hedge_position['stop_tick']:
                hedge_pnl = (price - hedge_position['entry_price']) / hedge_position['entry_price'] * CAPITAL
                total_hedge_pnl += hedge_pnl
                if hedge_pnl < 0:
                    whipsaws += 1
                hedge_position = None

        # Rebalance on range exit
        if not in_range:
            hodl_value = range_start_btc * price + range_start_usdc
            lp_value = btc_amount * price + usdc_amount
            il_amount = hodl_value - lp_value

            total_il += il_amount
            rebalance_count += 1

            if hedge_position:
                if hedge_position['type'] == 'short':
                    hedge_pnl = (hedge_position['entry_price'] - price) / hedge_position['entry_price'] * CAPITAL
                else:
                    hedge_pnl = (price - hedge_position['entry_price']) / hedge_position['entry_price'] * CAPITAL

                total_hedge_pnl += hedge_pnl
                if hedge_pnl > 0:
                    successful_hedges += 1
                hedge_position = None

            btc_amount, usdc_amount, liquidity, price_lower, price_upper = initialize_position(price, CAPITAL)
            range_start_btc = btc_amount
            range_start_usdc = usdc_amount

    # Calculate metrics
    il_pct_unhedged = (total_il / CAPITAL) * 100
    il_hedged = total_il - total_hedge_pnl  # Corrected: no max(0,...) cap
    il_pct_hedged = (il_hedged / CAPITAL) * 100
    hedge_pnl_pct = (total_hedge_pnl / CAPITAL) * 100
    il_reduction = il_pct_unhedged - il_pct_hedged
    il_reduction_pct = (il_reduction / abs(il_pct_unhedged)) * 100 if il_pct_unhedged != 0 else 0
    win_rate = (successful_hedges / total_trades * 100) if total_trades > 0 else 0

    return {
        'il_pct_unhedged': il_pct_unhedged,
        'il_pct_hedged': il_pct_hedged,
        'hedge_pnl_pct': hedge_pnl_pct,
        'il_reduction': il_reduction,
        'il_reduction_pct': il_reduction_pct,
        'rebalances': rebalance_count,
        'total_trades': total_trades,
        'successful_hedges': successful_hedges,
        'whipsaws': whipsaws,
        'win_rate': win_rate
    }

def main():
    print("=" * 80)
    print("LP HEDGING IL ANALYSIS - CORRECTED")
    print("Pure IL without fees | Fixed calculations")
    print("=" * 80)

    # Load data
    print(f"\nLoading data from {CSV_FILE}...")
    data = load_data(CSV_FILE)
    print(f"Loaded {len(data):,} price points")

    prices = [d['price'] for d in data]
    start_date = data[0]['timestamp']
    end_date = data[-1]['timestamp']
    total_days = (end_date - start_date).total_seconds() / (24 * 3600)

    print(f"Period: {total_days:.1f} days ({start_date.date()} to {end_date.date()})")
    print(f"Price range: ${min(prices):,.0f} - ${max(prices):,.0f}")

    # Test strategies
    strategies = [
        ("Baseline", -999, 999, 0),
        ("Conservative", 30, 70, 12),
        ("Moderate", 35, 65, 12),
        ("Aggressive", 40, 60, 12),
        ("Original (44/57)", 44, 57, 12),
        ("Optimal (45/58/s8)", 45, 58, 8),
        ("44/57 tight stop", 44, 57, 8),
        ("Symmetric", 50, 50, 12),
    ]

    print("\n" + "=" * 80)
    print("STRATEGY COMPARISON")
    print("=" * 80)

    print(f"\n{'Strategy':<20} {'IL Unhgd':<10} {'Hedge P&L':<10} {'IL Hedged':<10} {'Reduction':<10} {'Win Rate':<10}")
    print("-" * 70)

    results = []
    baseline_il = None

    for name, short, long, stop in strategies:
        result = simulate_strategy(data, short, long, stop)
        results.append((name, result))

        if name == "Baseline":
            baseline_il = result['il_pct_unhedged']

        print(f"{name:<20} {result['il_pct_unhedged']:>9.2f}% "
              f"{result['hedge_pnl_pct']:>9.2f}% {result['il_pct_hedged']:>9.2f}% "
              f"{result['il_reduction']:>9.2f}% {result['win_rate']:>9.1f}%")

    # Find best and worst performing strategies
    best_name = None
    best_reduction = -float('inf')
    worst_reduction = float('inf')
    symmetric_result = None

    for name, result in results:
        if name != "Baseline":
            if result['il_reduction'] > best_reduction:
                best_reduction = result['il_reduction']
                best_name = name
                best_result = result
            if result['il_reduction'] < worst_reduction:
                worst_reduction = result['il_reduction']
        if name == "Symmetric":
            symmetric_result = result

    print("\n" + "=" * 80)
    print("OPTIMAL STRATEGY")
    print("=" * 80)

    print(f"\n{best_name}")
    print(f"IL reduction: {best_result['il_reduction']:.2f} percentage points ({best_result['il_reduction_pct']:.1f}% relative)")
    print(f"Final IL: {best_result['il_pct_hedged']:.2f}% (from {best_result['il_pct_unhedged']:.2f}%)")
    print(f"Win rate: {best_result['win_rate']:.1f}% on {best_result['total_trades']} trades")

    print("\n" + "=" * 80)
    print("KEY FINDINGS (from actual calculations)")
    print("=" * 80)

    # All findings based on actual calculated results
    print(f"\n• Baseline IL: {baseline_il:.1f}% loss in {total_days:.0f} days on {RANGE_WIDTH_PCT*100:.0f}% range")
    print(f"• Best strategy reduces IL by {best_result['il_reduction_pct']:.0f}% (relative)")
    print(f"• Optimal final IL: {best_result['il_pct_hedged']:.1f}% (from {baseline_il:.1f}%)")

    if symmetric_result:
        sym_vs_optimal = best_result['il_reduction'] - symmetric_result['il_reduction']
        if sym_vs_optimal > 0:
            print(f"• Asymmetric beats symmetric by {sym_vs_optimal:.1f} percentage points")

    print(f"• Best strategy win rate: {best_result['win_rate']:.0f}% (shows lower win rate can be better)")
    print(f"• Required fee APY to break even: {abs(best_result['il_pct_hedged']):.0f}%")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nAnalysis interrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        sys.exit(1)