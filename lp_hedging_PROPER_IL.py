#!/usr/bin/env python3
"""
LP Hedging Strategy Analyzer with PROPER Concentrated Liquidity IL Calculation

Tracks actual BTC and USDC amounts through Uniswap v3 style concentrated ranges.
Starting position: 50/50 split at midpoint of first range.
"""

import pandas as pd
import numpy as np

# ============================================================================
# CONFIGURATION
# ============================================================================

CSV_FILE_PATH = 'cbbtc_prices_sept2025.csv'
CAPITAL = 2000              # Initial capital in USD
RANGE_WIDTH_PCT = 0.01      # 1% range = 100 ticks
ANNUAL_FEE_RATE = 0.60      # 60% APY
DEFAULT_STOP_BUFFER = 15

# ============================================================================
# CONCENTRATED LIQUIDITY IL CALCULATION
# ============================================================================

def calculate_concentrated_lp_amounts(price, price_lower, price_upper, liquidity):
    """
    Calculate BTC and USDC amounts in a concentrated LP position.

    For Uniswap v3 style concentrated liquidity:
    - If price < price_lower: 100% BTC, 0% USDC
    - If price > price_upper: 0% BTC, 100% USDC
    - If price in range: both tokens present based on constant product

    Args:
        price: Current BTC price
        price_lower: Lower bound of LP range
        price_upper: Upper bound of LP range
        liquidity: Liquidity constant (L = sqrt(btc * usdc))

    Returns:
        (btc_amount, usdc_amount)
    """

    sqrt_price = np.sqrt(price)
    sqrt_lower = np.sqrt(price_lower)
    sqrt_upper = np.sqrt(price_upper)

    if price <= price_lower:
        # All BTC, no USDC
        btc_amount = liquidity * (1/sqrt_lower - 1/sqrt_upper)
        usdc_amount = 0
    elif price >= price_upper:
        # All USDC, no BTC
        btc_amount = 0
        usdc_amount = liquidity * (sqrt_upper - sqrt_lower)
    else:
        # Both tokens
        btc_amount = liquidity * (1/sqrt_price - 1/sqrt_upper)
        usdc_amount = liquidity * (sqrt_price - sqrt_lower)

    return btc_amount, usdc_amount

def initialize_position(initial_price, capital):
    """
    Initialize 50/50 LP position at midpoint of first range.

    Args:
        initial_price: BTC price at start
        capital: Total capital in USD

    Returns:
        (btc_amount, usdc_amount, liquidity, price_lower, price_upper)
    """
    # Range bounds
    price_lower = initial_price * (1 - RANGE_WIDTH_PCT / 2)
    price_upper = initial_price * (1 + RANGE_WIDTH_PCT / 2)

    # At midpoint, we want 50/50 split
    # For 50/50: btc_value = usdc_value = capital/2
    btc_amount = capital / 2 / initial_price
    usdc_amount = capital / 2

    # Calculate liquidity constant that gives us these amounts at midpoint
    sqrt_price = np.sqrt(initial_price)
    sqrt_lower = np.sqrt(price_lower)
    sqrt_upper = np.sqrt(price_upper)

    # From the formulas:
    # usdc = L * (sqrt_P - sqrt_lower)
    # btc = L * (1/sqrt_P - 1/sqrt_upper)
    # Solve for L using usdc equation
    liquidity = usdc_amount / (sqrt_price - sqrt_lower)

    return btc_amount, usdc_amount, liquidity, price_lower, price_upper

def calculate_il_at_rebalance(initial_btc, initial_usdc, final_btc, final_usdc, final_price):
    """
    Calculate IL when rebalancing LP position.

    IL = (HODL value) - (LP value)

    Args:
        initial_btc: BTC amount at start of range
        initial_usdc: USDC amount at start of range
        final_btc: BTC amount at end of range (after price movement)
        final_usdc: USDC amount at end of range
        final_price: BTC price at rebalance

    Returns:
        IL in USD (positive = loss, negative = gain)
    """
    # HODL: keep original amounts
    hodl_value = initial_btc * final_price + initial_usdc

    # LP: rebalanced amounts
    lp_value = final_btc * final_price + final_usdc

    # IL = what you lost by being LP instead of HODL
    il = hodl_value - lp_value

    return il

# ============================================================================
# SIMULATION WITH PROPER IL
# ============================================================================

def simulate_with_proper_il(df, short_threshold, long_threshold, stop_buffer=DEFAULT_STOP_BUFFER):
    """
    Simulate LP + hedging with proper concentrated liquidity IL calculation.
    """

    # Initialize first LP range at midpoint (tick 50)
    first_price = df.iloc[0]['cb_btc_price']

    btc_amount, usdc_amount, liquidity, price_lower, price_upper = initialize_position(first_price, CAPITAL)

    # Track initial amounts for this range
    range_start_btc = btc_amount
    range_start_usdc = usdc_amount
    range_start_time = df.iloc[0]['block_timestamp']
    range_start_price = first_price

    hedge_position = None

    # Accumulators
    total_fees = 0
    total_il_unhedged = 0
    total_hedge_pnl = 0
    rebalance_count = 0
    whipsaw_count = 0
    successful_hedge_count = 0

    for idx, row in df.iterrows():
        price = row['cb_btc_price']
        time = row['block_timestamp']

        # Update token amounts based on current price in range
        btc_amount, usdc_amount = calculate_concentrated_lp_amounts(
            price, price_lower, price_upper, liquidity
        )

        # Calculate tick position
        if price <= price_lower:
            tick = 0
            in_range = False
        elif price >= price_upper:
            tick = 100
            in_range = False
        else:
            tick = (price - price_lower) / (price_upper - price_lower) * 100
            in_range = True

        current_tick = tick

        # Hedge entry logic
        if in_range and hedge_position is None:
            if tick <= short_threshold:
                hedge_position = {
                    'type': 'short',
                    'entry_price': price,
                    'entry_time': time,
                    'stop_tick': min(short_threshold + stop_buffer, 95)
                }
            elif tick >= long_threshold:
                hedge_position = {
                    'type': 'long',
                    'entry_price': price,
                    'entry_time': time,
                    'stop_tick': max(long_threshold - stop_buffer, 5)
                }

        # Stop loss checks
        if in_range and hedge_position:
            stopped_out = False

            if hedge_position['type'] == 'short' and tick >= hedge_position['stop_tick']:
                hedge_pnl = (hedge_position['entry_price'] - price) / hedge_position['entry_price'] * CAPITAL
                total_hedge_pnl += hedge_pnl
                whipsaw_count += 1
                stopped_out = True
            elif hedge_position['type'] == 'long' and tick <= hedge_position['stop_tick']:
                hedge_pnl = (price - hedge_position['entry_price']) / hedge_position['entry_price'] * CAPITAL
                total_hedge_pnl += hedge_pnl
                whipsaw_count += 1
                stopped_out = True

            if stopped_out:
                hedge_position = None

        # Range exit - rebalance
        if not in_range:
            duration_days = (time - range_start_time).total_seconds() / (24 * 3600)

            # Calculate fees
            fees_earned = CAPITAL * ANNUAL_FEE_RATE * (duration_days / 365.25)

            # Calculate REAL IL from token amounts
            il_amount = calculate_il_at_rebalance(
                range_start_btc, range_start_usdc,
                btc_amount, usdc_amount,
                price
            )

            total_fees += fees_earned
            total_il_unhedged += il_amount
            rebalance_count += 1

            # Close hedge if open
            if hedge_position:
                if hedge_position['type'] == 'short':
                    hedge_pnl = (hedge_position['entry_price'] - price) / hedge_position['entry_price'] * CAPITAL
                elif hedge_position['type'] == 'long':
                    hedge_pnl = (price - hedge_position['entry_price']) / hedge_position['entry_price'] * CAPITAL

                total_hedge_pnl += hedge_pnl

                if hedge_pnl > 0:
                    successful_hedge_count += 1

                hedge_position = None

            # Start new range at current price
            price_lower = price * (1 - RANGE_WIDTH_PCT / 2)
            price_upper = price * (1 + RANGE_WIDTH_PCT / 2)

            # Reinitialize position at midpoint of new range
            btc_amount, usdc_amount, liquidity, price_lower, price_upper = initialize_position(price, CAPITAL)

            range_start_btc = btc_amount
            range_start_usdc = usdc_amount
            range_start_time = time
            range_start_price = price

    # Calculate final metrics
    total_il_hedged = max(0, total_il_unhedged - total_hedge_pnl)

    net_pnl_unhedged = total_fees - total_il_unhedged
    net_pnl_hedged = total_fees - total_il_hedged

    il_reduction_pct = (1 - total_il_hedged / total_il_unhedged) * 100 if total_il_unhedged > 0 else 0
    total_trades = whipsaw_count + successful_hedge_count
    win_rate = successful_hedge_count / total_trades * 100 if total_trades > 0 else 0

    return {
        'short_threshold': short_threshold,
        'long_threshold': long_threshold,
        'rebalances': rebalance_count,
        'total_fees': total_fees,
        'total_il_unhedged': total_il_unhedged,
        'total_il_hedged': total_il_hedged,
        'hedge_pnl': total_hedge_pnl,
        'il_reduction_pct': il_reduction_pct,
        'net_pnl_unhedged': net_pnl_unhedged,
        'net_pnl_hedged': net_pnl_hedged,
        'total_trades': total_trades,
        'successful_hedges': successful_hedge_count,
        'whipsaws': whipsaw_count,
        'win_rate': win_rate
    }

# ============================================================================
# MAIN
# ============================================================================

def main():
    print("="*80)
    print("LP HEDGING ANALYZER - PROPER CONCENTRATED LIQUIDITY IL")
    print("="*80)

    # Load data
    print(f"\nLoading: {CSV_FILE_PATH}")
    df = pd.read_csv(CSV_FILE_PATH)
    df['block_timestamp'] = pd.to_datetime(df['block_timestamp'])
    df = df.sort_values('block_timestamp').reset_index(drop=True)

    print(f"✓ Loaded {len(df):,} price points")
    print(f"  Date range: {df['block_timestamp'].min()} to {df['block_timestamp'].max()}")
    print(f"  Price range: ${df['cb_btc_price'].min():,.2f} to ${df['cb_btc_price'].max():,.2f}")

    print(f"\nConfiguration:")
    print(f"  Starting capital: ${CAPITAL:,}")
    print(f"  Starting position: 50/50 BTC/USDC at midpoint")
    print(f"  Annual fee rate: {ANNUAL_FEE_RATE*100:.0f}%")
    print(f"  LP range width: {RANGE_WIDTH_PCT*100:.2f}%")

    # Test baseline
    print(f"\n{'='*80}")
    print("BASELINE (NO HEDGING)")
    print(f"{'='*80}")

    baseline = simulate_with_proper_il(df, -999, 999, 0)
    print(f"  Rebalances: {baseline['rebalances']}")
    print(f"  Fees earned: ${baseline['total_fees']:.2f}")
    print(f"  IL (PROPER): ${baseline['total_il_unhedged']:.2f}")
    print(f"  Net P&L: ${baseline['net_pnl_unhedged']:.2f} ({baseline['net_pnl_unhedged']/CAPITAL*100:.2f}%)")

    # Test strategies
    print(f"\n{'='*80}")
    print("HEDGING STRATEGIES")
    print(f"{'='*80}")

    strategies = [
        (10, 90, "Very Conservative"),
        (20, 80, "Conservative"),
        (25, 75, "Balanced"),
        (30, 70, "Moderate"),
        (35, 65, "Aggressive"),
        (40, 60, "Very Aggressive"),
    ]

    results = []

    for short_t, long_t, description in strategies:
        result = simulate_with_proper_il(df, short_t, long_t)
        result['description'] = description
        results.append(result)

        print(f"\n{description}: Short@{short_t}, Long@{long_t}")
        print(f"  Fees: ${result['total_fees']:.2f}")
        print(f"  IL (unhedged): ${result['total_il_unhedged']:.2f}")
        print(f"  Hedge P&L: ${result['hedge_pnl']:.2f}")
        print(f"  IL (hedged): ${result['total_il_hedged']:.2f}")
        print(f"  IL reduction: {result['il_reduction_pct']:.1f}%")
        print(f"  Win rate: {result['win_rate']:.1f}%")
        print(f"  Net P&L: ${result['net_pnl_hedged']:.2f} ({result['net_pnl_hedged']/CAPITAL*100:.2f}%)")

    # Find optimal
    results_df = pd.DataFrame(results)
    best = results_df.loc[results_df['net_pnl_hedged'].idxmax()]

    print(f"\n{'='*80}")
    print("OPTIMAL STRATEGY")
    print(f"{'='*80}")
    print(f"\n{best['description']}: Short@{best['short_threshold']}, Long@{best['long_threshold']}")
    print(f"\nPerformance:")
    print(f"  Fees: ${best['total_fees']:.2f}")
    print(f"  IL (PROPER): ${best['total_il_unhedged']:.2f}")
    print(f"  Hedge offset: ${best['hedge_pnl']:.2f}")
    print(f"  IL after hedge: ${best['total_il_hedged']:.2f}")
    print(f"  Net P&L: ${best['net_pnl_hedged']:.2f}")
    print(f"  Monthly return: {best['net_pnl_hedged']/CAPITAL*100:.2f}%")
    print(f"  Annualized: {((1 + best['net_pnl_hedged']/CAPITAL)**12 - 1)*100:.1f}%")

    improvement = best['net_pnl_hedged'] - baseline['net_pnl_unhedged']
    print(f"\nImprovement vs no hedging: ${improvement:.2f} ({improvement/CAPITAL*100:.2f}%)")

    print(f"\n{'='*80}")
    print("IL CALCULATION METHOD")
    print(f"{'='*80}")
    print("""
PROPER Concentrated Liquidity IL Calculation:

1. Start with 50/50 BTC/USDC at midpoint of range
2. Track actual BTC and USDC amounts as price moves through range
3. Use Uniswap v3 formulas for token amounts based on price
4. At rebalance:
   - HODL value = (initial_btc × exit_price) + initial_usdc
   - LP value = (current_btc × exit_price) + current_usdc
   - IL = HODL - LP

This is the TRUE impermanent loss from actual token rebalancing.
""")

if __name__ == "__main__":
    main()
