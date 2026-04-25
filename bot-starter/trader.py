#!/usr/bin/env python3
"""
SCG Alpha bot starter — execution loop for SCG Alpha signals.

Reads new signals from the SCG Alpha API, applies your filter (filters.py),
buys via Jupiter Ultra, and exits on your rules. Lamport-based PnL,
sell-quote polling, retry cooldowns, wallet-balance reconciliation.

Replace `passes_filter` and `decide_exit` in filters.py with your own logic.
Run with SCG_DRY_RUN=1 (the default) until you've stress-tested for 24h+.

Modules of the playbook this implements:
  - Module 01: API setup
  - Module 04: TG bot output (optional, set TELEGRAM_*)
  - Module 05: full auto bot — but YOU bring the filters/exits

What this file is NOT:
  - It's not the SCG Alpha team's strategy. We don't ship our filter or exit
    values. Find your own — that's the whole point of Modules 02 and 03.
"""
import os
import sys
import time
import json
import asyncio
import logging
from pathlib import Path

import aiohttp

import config
from scg_ultra import ultra_swap, quote_sell_to_sol
from filters import passes_filter, decide_exit


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("scg-bot")


# ─── State ──────────────────────────────────────────────────────────────────
positions: dict = {}
processed_alerts: set = set()

_wallet_keypair = None


def get_keypair():
    global _wallet_keypair
    if _wallet_keypair is None and config.WALLET_PRIVATE_KEY:
        from solders.keypair import Keypair
        _wallet_keypair = Keypair.from_base58_string(config.WALLET_PRIVATE_KEY)
    return _wallet_keypair


def save_state():
    try:
        config.STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(config.STATE_FILE, "w") as f:
            json.dump(
                {"positions": positions, "processed_alerts": list(processed_alerts)},
                f,
                default=str,
            )
    except Exception as e:
        log.error(f"save_state: {e}")


def load_state():
    global processed_alerts
    if not config.STATE_FILE.exists():
        return
    try:
        d = json.load(open(config.STATE_FILE))
        positions.update(d.get("positions", {}))
        processed_alerts = set(d.get("processed_alerts", []))
        log.info(
            f"Restored {len(positions)} open positions, "
            f"{len(processed_alerts)} processed alerts"
        )
    except Exception as e:
        log.error(f"load_state: {e}")


def log_trade(rec):
    try:
        with open(config.TRADES_LOG, "a") as f:
            f.write(json.dumps(rec, default=str) + "\n")
    except Exception as e:
        log.error(f"log_trade: {e}")


async def tg(s, msg):
    """Optional Telegram alert. Silent no-op if not configured."""
    if not config.TG_TOKEN or not config.TG_CHAT:
        return
    try:
        await s.post(
            f"https://api.telegram.org/bot{config.TG_TOKEN}/sendMessage",
            json={"chat_id": config.TG_CHAT, "text": msg, "parse_mode": "HTML"},
            timeout=aiohttp.ClientTimeout(total=5),
        )
    except Exception:
        pass


# ─── SCG Alpha API ──────────────────────────────────────────────────────────
async def fetch_alerts(s, since_ts: float):
    """Pull alerts from the SCG Alpha API. Requires a valid subscription."""
    url = f"{config.SCG_API_BASE}/api/alerts"
    params = {"since": since_ts, "limit": 100}
    headers = {"Authorization": f"Bearer {config.SCG_API_KEY}"}
    try:
        async with s.get(
            url, params=params, headers=headers,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as r:
            if r.status == 401:
                log.error("API key missing or invalid (401). Check SCG_API_KEY in .env.")
                return None
            if r.status == 403:
                log.error(
                    "API key inactive (403). Your subscription may have lapsed — "
                    "renew at https://scgalpha.com."
                )
                return None
            if r.status != 200:
                txt = await r.text()
                log.warning(f"alerts {r.status}: {txt[:200]}")
                return []
            d = await r.json()
            return d.get("alerts", [])
    except Exception as e:
        log.error(f"fetch_alerts: {e}")
        return []


# ─── Solana RPC helpers ─────────────────────────────────────────────────────
async def get_wallet_token_balance(s, mint):
    """Actual tokens_raw held by our wallet for this mint, or None on RPC error."""
    try:
        async with s.post(
            config.HELIUS_RPC,
            json={
                "jsonrpc": "2.0", "id": 1, "method": "getTokenAccountsByOwner",
                "params": [config.WALLET_ADDRESS, {"mint": mint}, {"encoding": "jsonParsed"}],
            },
            timeout=aiohttp.ClientTimeout(total=10),
        ) as r:
            d = await r.json()
            total = 0
            for acc in d.get("result", {}).get("value", []):
                info = acc.get("account", {}).get("data", {}).get("parsed", {}).get("info", {})
                amt = info.get("tokenAmount", {}).get("amount", "0")
                try:
                    total += int(amt)
                except Exception:
                    pass
            return total
    except Exception as e:
        log.warning(f"get_wallet_token_balance {mint[:12]}: {e}")
        return None


# ─── Jupiter Ultra swap ─────────────────────────────────────────────────────
async def jupiter_swap(s, in_mint, out_mint, amount_raw):
    """Buy/sell via Jupiter Ultra. Returns (sig, out_amount_raw) or (None, 0)."""
    kp = get_keypair()
    if not kp:
        log.error("No wallet keypair (set WALLET_PRIVATE_KEY in .env)")
        return None, 0
    if not config.JUP_API_KEY:
        log.error("No JUP_API_KEY (get one at https://portal.jup.ag/)")
        return None, 0
    return await ultra_swap(s, in_mint, out_mint, amount_raw, kp, config.JUP_API_KEY, retries=3)


# ─── Buy ────────────────────────────────────────────────────────────────────
async def buy(s, alert):
    mint = alert["mint"]
    name = alert.get("name", mint[:8])
    raw = alert.get("scan_raw_at_alert") or {}

    log.info(f"BUY {name} | mint={mint[:12]}..")

    alert_price = alert.get("alert_price", 0) or 1e-12
    alert_mcap = alert.get("alert_mcap", 0) or 0
    entry_lamports = int(config.BUY_SIZE_SOL * 1e9)

    if config.DRY_RUN:
        log.info(f"[DRY_RUN] would buy {config.BUY_SIZE_SOL} SOL of {name}")
        pos = {
            "mint": mint, "name": name,
            "entry_time": time.time(),
            "entry_lamports": entry_lamports,
            "entry_sol": config.BUY_SIZE_SOL,
            "tokens_raw": 1,
            "original_tokens_raw": 1,
            "peak_value_lamports": entry_lamports,
            "current_value_lamports": entry_lamports,
            "tp1_hit": False,
            "status": "open",
            "last_sell_attempt_at": 0,
            "dry_run": True,
            "buy_sig": "DRY_RUN",
            "alert_mcap": alert_mcap,
            "entry_price_sol": alert_price,
        }
        positions[mint] = pos
        await tg(s, f"🟢 [DRY] BUY {name}\nmcap ${alert_mcap:,.0f}")
        save_state()
        return

    # Mark "opening" so the alert loop doesn't double-buy
    positions[mint] = {
        "mint": mint, "name": name, "status": "opening",
        "entry_time": time.time(), "entry_lamports": entry_lamports,
        "tokens_raw": 0, "entry_sol": config.BUY_SIZE_SOL,
    }

    sig, tokens_raw = await jupiter_swap(s, config.SOL_MINT, mint, entry_lamports)
    if not sig or tokens_raw <= 0:
        log.error(f"BUY FAILED {name}")
        await tg(s, f"❌ BUY FAILED {name}")
        del positions[mint]
        save_state()
        return

    # Reconcile against actual wallet balance (handles partial fills / dust)
    await asyncio.sleep(1)
    actual_tokens = await get_wallet_token_balance(s, mint)
    if actual_tokens is not None and actual_tokens > 0 and actual_tokens != tokens_raw:
        log.info(f"{name}: wallet has {actual_tokens} tokens (expected {tokens_raw}) — using actual")
        tokens_raw = actual_tokens

    pos = {
        "mint": mint, "name": name,
        "entry_time": time.time(),
        "entry_lamports": entry_lamports,
        "entry_sol": config.BUY_SIZE_SOL,
        "tokens_raw": tokens_raw,
        "original_tokens_raw": tokens_raw,
        "peak_value_lamports": entry_lamports,
        "current_value_lamports": entry_lamports,
        "tp1_hit": False,
        "status": "open",
        "last_sell_attempt_at": 0,
        "buy_sig": sig,
        "alert_mcap": alert_mcap,
        "entry_price_sol": alert_price,
    }
    positions[mint] = pos
    save_state()
    await tg(s, f"🟢 BUY {name}\nmcap ${alert_mcap:,.0f}\ntx: {sig[:16]}...")
    log_trade({
        "event": "buy", "ts": pos["entry_time"], "sig": sig,
        "name": name, "mint": mint,
        "entry_lamports": entry_lamports, "entry_sol": config.BUY_SIZE_SOL,
        "tokens_raw": tokens_raw, "alert_mcap": alert_mcap,
    })


# ─── Sell ───────────────────────────────────────────────────────────────────
async def sell(s, pos, reason, target_tokens_to_sell=None):
    """
    Sell tokens from a position.

    target_tokens_to_sell:
        None → close position (sell all wallet balance)
        int  → partial: attempt to sell exactly that many tokens
    """
    name = pos["name"]
    mint = pos["mint"]
    entry = pos.get("entry_lamports", 0)
    current = pos.get("current_value_lamports", entry)
    peak = pos.get("peak_value_lamports", entry)
    orig = pos.get("original_tokens_raw", pos.get("tokens_raw", 1)) or 1
    remaining_tokens = pos.get("tokens_raw", 0)

    price_mult = (
        (current / remaining_tokens) / (entry / orig)
        if (remaining_tokens > 0 and entry > 0 and orig > 0)
        else 1.0
    )
    pnl_pct = (price_mult - 1) * 100
    peak_x = peak / entry if entry > 0 else 1.0
    held_min = (time.time() - pos["entry_time"]) / 60

    # Sell cooldown — don't spam retries
    last_attempt = pos.get("last_sell_attempt_at", 0)
    if last_attempt > 0 and time.time() - last_attempt < config.SELL_RETRY_COOLDOWN_SECS:
        return

    is_partial = target_tokens_to_sell is not None
    log.info(
        f"SELL {name} | {reason} | price={price_mult:.2f}x | "
        f"peak={peak_x:.2f}x | held={held_min:.1f}m | partial={is_partial}"
    )

    if config.DRY_RUN or pos.get("dry_run"):
        log.info(f"[DRY_RUN] would sell {name} ({reason})")
        rec = {
            "event": "sell", "ts": time.time(), "reason": reason,
            "pnl_pct": pnl_pct, "entry_lamports": entry,
            "exit_lamports": current, "peak_lamports": peak,
            "held_min": held_min, "name": name, "mint": mint,
            "dry_run": True, "partial": is_partial,
        }
        log_trade(rec)
        if is_partial:
            pos["tokens_raw"] = max(0, remaining_tokens - (target_tokens_to_sell or 0))
            if reason.startswith("tp"):
                pos["tp1_hit"] = True
        else:
            if mint in positions:
                del positions[mint]
        save_state()
        tag = "PARTIAL" if is_partial else "SELL"
        await tg(s, f"🔴 [DRY] {tag} {name} ({reason})\nprice {price_mult:.1f}x | peak {peak_x:.1f}x\nheld {held_min:.0f}m")
        return

    pos["status"] = "closing" if not is_partial else "open"
    pos["last_sell_attempt_at"] = time.time()

    # Reconcile against wallet
    actual_tokens = await get_wallet_token_balance(s, mint)
    if actual_tokens is None:
        tokens_to_sell = target_tokens_to_sell if is_partial else pos.get("tokens_raw", 0)
    elif actual_tokens == 0:
        log.info(f"{name}: 0 tokens in wallet, marking closed")
        rec = {
            "event": "sell", "ts": time.time(), "reason": "no_tokens",
            "pnl_pct": 0, "name": name, "mint": mint,
            "note": "wallet had 0 tokens at sell time",
        }
        log_trade(rec)
        if mint in positions:
            del positions[mint]
        save_state()
        return
    else:
        if is_partial:
            tokens_to_sell = min(target_tokens_to_sell, actual_tokens)
        else:
            if actual_tokens != pos.get("tokens_raw", 0):
                log.info(f"{name}: wallet has {actual_tokens} (tracked {pos.get('tokens_raw', 0)}) — using actual")
            tokens_to_sell = actual_tokens

    if tokens_to_sell <= 0:
        log.error(f"{name}: no tokens to sell")
        pos["status"] = "open"
        return

    sig, sol_out_raw = await jupiter_swap(s, mint, config.SOL_MINT, tokens_to_sell)
    if not sig:
        log.error(f"SELL FAILED {name} — will retry after cooldown")
        pos["status"] = "open"
        await tg(s, f"❌ SELL FAILED {name}\n(retry in {config.SELL_RETRY_COOLDOWN_SECS}s)")
        return

    sol_out = sol_out_raw / 1e9
    if is_partial:
        frac = tokens_to_sell / orig if orig > 0 else 0
        entry_sol_portion = pos["entry_sol"] * frac
        real_pnl_sol = sol_out - entry_sol_portion
        real_pnl_pct = (real_pnl_sol / entry_sol_portion * 100) if entry_sol_portion > 0 else 0
    else:
        real_pnl_sol = sol_out - pos["entry_sol"]
        real_pnl_pct = real_pnl_sol / pos["entry_sol"] * 100 if pos["entry_sol"] > 0 else 0

    rec = {
        "event": "sell", "ts": time.time(), "reason": reason,
        "pnl_pct": real_pnl_pct, "pnl_sol": real_pnl_sol,
        "entry_lamports": entry, "exit_lamports": current, "peak_lamports": peak,
        "held_min": held_min, "sell_sig": sig, "sol_out": sol_out,
        "name": name, "mint": mint, "partial": is_partial,
        "tokens_sold": tokens_to_sell, "original_tokens": orig,
    }
    log_trade(rec)

    if is_partial:
        new_remaining = max(0, remaining_tokens - tokens_to_sell)
        pos["tokens_raw"] = new_remaining
        if reason.startswith("tp"):
            pos["tp1_hit"] = True
        pos["status"] = "open"
        pos["last_sell_attempt_at"] = 0
        save_state()
        await tg(s, f"🟠 PARTIAL {name} ({reason})\n+{real_pnl_sol:+.4f} SOL\nprice {price_mult:.1f}x | held {held_min:.0f}m\ntx: {sig[:16]}...")
    else:
        if mint in positions:
            del positions[mint]
        save_state()
        await tg(s, f"🔴 CLOSE {name} ({reason})\nPnL {real_pnl_pct:+.1f}% ({real_pnl_sol:+.4f} SOL)\nprice {price_mult:.1f}x | held {held_min:.0f}m\ntx: {sig[:16]}...")


# ─── Main loops ─────────────────────────────────────────────────────────────
async def alert_loop(s):
    last_ts = time.time() - 60  # start with last minute on first run
    log.info(f"alert_loop start | since_ts={last_ts:.0f}")
    while True:
        try:
            alerts = await fetch_alerts(s, last_ts)
            if alerts is None:
                # API key error — fatal, stop the bot
                log.error("Stopping due to API auth error.")
                os._exit(2)
            for a in alerts:
                mint = a.get("mint")
                if not mint or mint in processed_alerts:
                    continue
                processed_alerts.add(mint)
                at = a.get("alert_time", 0)
                if at > last_ts:
                    last_ts = at

                if mint in positions:
                    continue
                if len(positions) >= config.MAX_CONCURRENT:
                    log.info(f"SKIP {a.get('name','?')}: max concurrent ({config.MAX_CONCURRENT})")
                    continue
                ok, reason = passes_filter(a)
                if not ok:
                    log.info(f"SKIP {a.get('name','?')}: {reason}")
                    continue
                await buy(s, a)
            save_state()
        except Exception as e:
            log.error(f"alert_loop: {e}", exc_info=True)
        await asyncio.sleep(config.ALERT_POLL_SECS)


async def exit_loop(s):
    log.info("exit_loop start")
    while True:
        try:
            for mint in list(positions.keys()):
                pos = positions[mint]
                if pos.get("status") and pos["status"] != "open":
                    continue
                tokens_raw = pos.get("tokens_raw", 0)
                if tokens_raw <= 0:
                    continue
                # Quote what we'd get if we sold everything right now
                current_lamports = await quote_sell_to_sol(
                    s, mint, tokens_raw, config.WALLET_ADDRESS, config.JUP_API_KEY
                )
                if current_lamports is None:
                    # Quote may have failed because tokens_raw is stale — reconcile
                    actual = await get_wallet_token_balance(s, mint)
                    if actual is not None and actual > 0 and actual != tokens_raw:
                        log.info(f"{pos['name']}: quote failed, resyncing tokens {tokens_raw} -> {actual}")
                        pos["tokens_raw"] = actual
                        tokens_raw = actual
                        current_lamports = await quote_sell_to_sol(
                            s, mint, tokens_raw, config.WALLET_ADDRESS, config.JUP_API_KEY
                        )
                    if current_lamports is None:
                        continue
                pos["current_value_lamports"] = current_lamports
                if current_lamports > pos.get("peak_value_lamports", 0):
                    pos["peak_value_lamports"] = current_lamports
                decision = decide_exit(pos)
                if decision:
                    reason, target = decision
                    await sell(s, pos, reason, target_tokens_to_sell=target)
            save_state()
        except Exception as e:
            log.error(f"exit_loop: {e}", exc_info=True)
        await asyncio.sleep(config.PRICE_POLL_SECS)


async def main():
    log.info("=" * 60)
    log.info(f"SCG Alpha bot starter | DRY_RUN={config.DRY_RUN}")
    log.info(f"  BUY_SIZE: {config.BUY_SIZE_SOL} SOL")
    log.info(f"  MAX_CONCURRENT: {config.MAX_CONCURRENT}")
    log.info(f"  WALLET: {config.WALLET_ADDRESS[:12]}..." if config.WALLET_ADDRESS else "  WALLET: (none — DRY only)")
    log.info(f"  API: {config.SCG_API_BASE}")
    log.info("=" * 60)

    load_state()
    async with aiohttp.ClientSession() as s:
        await tg(
            s,
            f"🤖 SCG bot starter starting\nDRY_RUN={config.DRY_RUN} | "
            f"Buy {config.BUY_SIZE_SOL} SOL | Open: {len(positions)}",
        )
        await asyncio.gather(alert_loop(s), exit_loop(s))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Shutdown")
