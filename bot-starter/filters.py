"""
filters.py — your edge lives here.

This file is intentionally incomplete. The functions below decide
WHICH signals to buy and WHEN to exit them. The values you choose are
your strategy. We don't ship ours — you'll find better ones for the
current market regime by following Modules 02 and 03 of the playbook.

Both functions are called from trader.py:
  passes_filter(alert)        — called on every new alert from the API
  decide_exit(pos)            — called every PRICE_POLL_SECS for each open position

Replace the TODO stubs below with your own logic, then run the bot in
DRY_RUN mode for 24h+ before going live.
"""
import os
from typing import Optional, Tuple


# ─── Entry filter ───────────────────────────────────────────────────────────

def passes_filter(alert: dict) -> Tuple[bool, str]:
    """
    Decide whether a fresh alert is worth buying.

    Args:
        alert: the full alert dict from /api/alerts. Includes top-level fields
               (mint, name, alert_mcap, holders, kol_count, liquidity, ...) plus
               the deep `scan_raw_at_alert` payload with everything else (bundler
               rate, dev hold, top10, smart_degen_count, renowned_count,
               price_change_percent5m, price_change_percent1h, etc.).

    Returns:
        (True, "OK") if the alert should be bought, else
        (False, "<reason>") for logs.

    ──────────────────────────────────────────────────────────────────────────
    EXAMPLE SHAPE — replace these checks with your own.

    The values below are placeholders, not recommendations. Read playbook
    Modules 02 (journal) and 03 (backtest) — find filter values that have
    proven edge in YOUR data. Memecoin meta shifts fast; numbers we'd ship
    today would be stale next month anyway.
    ──────────────────────────────────────────────────────────────────────────
    """
    raw = alert.get("scan_raw_at_alert") or {}
    if not raw:
        return False, "no scan_raw"

    # ── TODO: your filter rules go here ──────────────────────────────────
    # Example structure (uncomment and edit, or replace entirely):
    #
    # alert_mcap = float(alert.get("alert_mcap", 0) or 0)
    # if alert_mcap > YOUR_MAX_MCAP:
    #     return False, f"mcap ${alert_mcap:,.0f} too high"
    #
    # holders = int(alert.get("holders", 0) or 0)
    # if holders < YOUR_MIN_HOLDERS:
    #     return False, f"holders {holders} too low"
    #
    # kol_count = int(alert.get("kol_count", 0) or 0)
    # if kol_count < YOUR_MIN_KOLS:
    #     return False, f"kol_count {kol_count} too low"
    #
    # bundler_rate = float(raw.get("bundler_rate", 1) or 1)
    # if bundler_rate > YOUR_MAX_BUNDLER:
    #     return False, f"bundler {bundler_rate*100:.0f}% too high"
    #
    # if not raw.get("renounced_mint") or not raw.get("renounced_freeze_account"):
    #     return False, "authorities not renounced"
    # ──────────────────────────────────────────────────────────────────────

    # Default: everything passes — REPLACE THIS before going live.
    return True, "OK (no filter set)"


# ─── Exit decision ──────────────────────────────────────────────────────────

def decide_exit(pos: dict) -> Optional[Tuple[str, Optional[int]]]:
    """
    Decide whether to exit (or partially exit) an open position.

    Called every PRICE_POLL_SECS for each open position. Position dict has:
        - entry_lamports         (SOL amount you spent at entry, in lamports)
        - original_tokens_raw    (token amount received at entry)
        - tokens_raw             (token amount currently held — shrinks on partials)
        - current_value_lamports (latest sell-quote, what you'd get if you sold all)
        - peak_value_lamports    (highest current_value seen so far)
        - entry_time             (unix ts)
        - tp1_hit                (have you taken first partial yet?)
        - alert_mcap, pc5_at_buy, pc1h_at_buy, name, mint

    Returns:
        None                              — hold (most calls)
        ("<reason>", None)                — full close
        ("<reason>", N_tokens_to_sell)    — partial sell N tokens of `tokens_raw`

    ──────────────────────────────────────────────────────────────────────────
    EXAMPLE SHAPE — replace with your own exit rules.

    The "right" exit is highly strategy-dependent. Common patterns:
      - Hard stop loss (close full at -X%)
      - Tiered take-profit (sell 33% at 5x, 33% at 10x, runner)
      - Holder-decline exit (3 consecutive snapshots of falling holders)
      - Volume-collapse exit (5min volume < 30% of prior 5min)
      - Time-based stop (exit if no progress in N minutes)

    DON'T use trailing TPs on memecoins — playbook Module 06 explains why.
    ──────────────────────────────────────────────────────────────────────────
    """
    entry = pos.get("entry_lamports", 0)
    orig = pos.get("original_tokens_raw", 0) or 0
    remaining = pos.get("tokens_raw", 0) or 0
    current = pos.get("current_value_lamports", 0) or 0

    if entry <= 0 or orig <= 0 or remaining <= 0:
        return None

    # Price-per-token mult — robust across partial sells.
    entry_price = entry / orig
    current_price = current / remaining
    if entry_price <= 0:
        return None
    mult = current_price / entry_price

    # ── TODO: your exit rules here ───────────────────────────────────────
    # Example structure (uncomment and edit, or replace entirely):
    #
    # # 1. Hard stop loss
    # if mult <= (1 - YOUR_STOP_PCT):
    #     return ("stop", None)  # full close
    #
    # # 2. Take-profit tier 2 (full close)
    # if mult >= YOUR_TP2_MULT:
    #     return ("tp2", None)
    #
    # # 3. Take-profit tier 1 (partial — sell a fraction of original)
    # if mult >= YOUR_TP1_MULT and not pos.get("tp1_hit"):
    #     target = int(orig * YOUR_TP1_FRAC)
    #     target = min(target, remaining)
    #     if target > 0:
    #         return ("tp1", target)
    # ──────────────────────────────────────────────────────────────────────

    # Default: never exit — REPLACE THIS before going live.
    return None
