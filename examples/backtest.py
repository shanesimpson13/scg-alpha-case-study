"""
Strategy Backtesting Framework

Uses granular price journal data (30-second readings) collected by the
signal tracker to simulate different exit strategies with realistic
cost modeling for Solana pump.fun tokens.

Demonstrates how GMGN's /v1/token/info endpoint provides the price
data needed for rigorous strategy optimization.
"""

import json

# === Cost Model for Solana/pump.fun ===
SOL_PRICE = 130.0
BUY_SLIPPAGE = 0.025        # 2.5% on low-liq pump.fun tokens
SELL_SLIPPAGE = 0.025        # 2.5% on sell
DEX_FEE = 0.01              # 1% per swap (pump.fun/raydium)
JITO_TIP_SOL = 0.003        # Jito tip per transaction
PRIORITY_FEE_SOL = 0.0005   # Priority fee per transaction

BUY_COST_PCT = BUY_SLIPPAGE + DEX_FEE       # 3.5%
SELL_COST_PCT = SELL_SLIPPAGE + DEX_FEE      # 3.5%
FIXED_TX_COST = (JITO_TIP_SOL + PRIORITY_FEE_SOL) * SOL_PRICE  # ~$0.46


def load_signals(filepath):
    """Load signals with price journal data."""
    with open(filepath) as f:
        alerts = [json.loads(l) for l in f if l.strip()]
    # Filter to signals with enough price data
    return [a for a in alerts if len(a.get("price_journal", [])) > 5 and a["alert_price"] > 0]


def sim_tp_with_fallback(signal, tp_mult, fallback_label):
    """
    Simulate: sell 100% at TP multiplier, fallback to timed exit.

    Walks the price journal tick-by-tick. If price hits tp_mult * entry,
    sell immediately. Otherwise, sell at the timed checkpoint (15m, 30m, etc).

    Returns gross multiplier (before costs).
    """
    entry = signal["alert_price"]
    journal = signal["price_journal"]

    # Check if TP hits in journal
    for reading in journal:
        if reading["price"] / entry >= tp_mult:
            return tp_mult  # Sold at exact TP

    # Fallback to timed exit
    tracked = signal.get("tracked_prices", {}).get(fallback_label, {})
    if tracked and tracked.get("price", 0) > 0:
        return tracked["price"] / entry

    # Last resort: journal end price
    return journal[-1]["price"] / entry


def net_pnl(buy_size_usd, gross_mult, num_sell_txs=1):
    """
    Calculate net USD P&L after all costs.

    Accounts for:
    - Buy slippage + DEX fee (3.5%)
    - Sell slippage + DEX fee (3.5% per sell)
    - Fixed tx costs (Jito tip + priority fee)
    """
    effective_buy = buy_size_usd * (1 - BUY_COST_PCT)
    gross_value = effective_buy * gross_mult
    after_sell_pct = gross_value * (1 - SELL_COST_PCT)
    after_fixed = after_sell_pct - (FIXED_TX_COST * num_sell_txs) - FIXED_TX_COST  # buy tx
    return after_fixed - buy_size_usd


def run_sweep(signals, buy_size=50.0):
    """
    Run strategy parameter sweep across all signals.

    Tests multiple TP levels and fallback timings to find the
    optimal strategy for a given buy size.
    """
    print(f"{'Strategy':<45s} | {'Win':>7s} | {'Net PnL':>9s} | {'ROI':>7s} | {'Avg':>7s}")
    print("-" * 90)

    for tp_mult in [1.3, 1.5, 2.0, 2.5, 3.0]:
        for fallback in ["15m", "30m", "1hr"]:
            pnls = []
            for s in signals:
                gross = sim_tp_with_fallback(s, tp_mult, fallback)
                pnls.append(net_pnl(buy_size, gross))

            total = sum(pnls)
            wins = sum(1 for p in pnls if p >= 0)
            n = len(pnls)
            invested = buy_size * n

            if total > -invested * 0.5:  # only show strategies that aren't total disasters
                print(
                    f"  {tp_mult}x TP, {fallback} fallback"
                    f"{'':<25s} | {wins:>2}/{n} ({wins/n*100:>2.0f}%)"
                    f" | ${total:>+7.1f}"
                    f" | {total/invested*100:>+5.1f}%"
                    f" | ${total/n:>+5.1f}"
                )


if __name__ == "__main__":
    signals = load_signals("/tmp/alerts_bt.jsonl")
    print(f"Loaded {len(signals)} signals with price journal data\n")

    # Apply filters (score >= 65, holder growth >= 10%, bot/degen <= 40%)
    filtered = [s for s in signals if
        s.get("score", 0) >= 65 and
        s.get("holder_growth_pct", 0) >= 10 and
        s.get("bot_degen_pct", 100) <= 40
    ]
    print(f"After filters: {len(filtered)} signals\n")

    print("=" * 90)
    print(f"STRATEGY SWEEP — ${50} buys, cost-adjusted")
    print("=" * 90)
    run_sweep(filtered, buy_size=50.0)
