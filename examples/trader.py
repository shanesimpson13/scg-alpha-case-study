"""
GMGN Trade Execution with Server-Side Condition Orders

Executes buys via GMGN's /v1/trade/swap endpoint with attached
take-profit condition orders. GMGN monitors the price server-side
and auto-executes the sell when the target is hit.

This eliminates thousands of price polling API calls and removes
rate limit concerns entirely.
"""

import os, time, json, uuid, base64, asyncio, logging
import aiohttp

GMGN_HOST = "https://openapi.gmgn.ai"
GMGN_TRADE_KEY = os.getenv("GMGN_TRADE_KEY", "")
TRADE_PEM = os.getenv("TRADE_PRIVATE_KEY", "").replace("\\n", "\n")
WALLET = os.getenv("WALLET_ADDRESS", "")
SOL_MINT = "So11111111111111111111111111111111111111112"

# Strategy params
BUY_AMOUNT_SOL = 0.1        # 0.1 SOL per trade
TP_MULTIPLIER = 2.5          # sell at 2.5x entry
FALLBACK_SECONDS = 900       # dump at 15min if TP not hit

log = logging.getLogger("trader")

_signing_key = None

def _get_signing_key():
    global _signing_key
    if _signing_key is None and TRADE_PEM:
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
        _signing_key = load_pem_private_key(TRADE_PEM.encode(), password=None)
    return _signing_key


def _sign_request(path, query, body, ts):
    """Sign API request with Ed25519 key."""
    qs = "&".join(f"{k}={query[k]}" for k in sorted(query))
    msg = f"{path}:{qs}:{body}:{ts}"
    return base64.b64encode(_get_signing_key().sign(msg.encode())).decode()


async def api_post(session, path, payload):
    """POST to GMGN trade API with signature auth."""
    ts = str(int(time.time()))
    cid = str(uuid.uuid4())
    body_str = json.dumps(payload, separators=(",", ":"))
    query = {"timestamp": ts, "client_id": cid}
    sig = _sign_request(path, query, body_str, ts)

    async with session.post(
        f"{GMGN_HOST}{path}",
        params=query,
        data=body_str,
        headers={
            "X-APIKEY": GMGN_TRADE_KEY,
            "X-Signature": sig,
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0",
        },
        timeout=aiohttp.ClientTimeout(total=15),
    ) as r:
        d = await r.json()
        if d.get("code") == 0:
            return d.get("data")
        log.error(f"POST {path}: {d.get('message', 'unknown error')}")
        return None


async def buy_with_tp(session, mint, name):
    """
    Execute buy via GMGN with server-side take-profit.

    The condition order tells GMGN to automatically sell 100% of the
    position when the price reaches 2.5x the entry price. GMGN monitors
    this server-side — no polling required from our end.

    Returns:
        tuple: (order_id, strategy_id, buy_price) or (None, None, None)
    """
    # price_scale = percentage gain for TP trigger
    # 2.5x entry = 150% gain
    tp_gain_pct = str(int((TP_MULTIPLIER - 1) * 100))  # "150"

    condition_orders = [
        {
            "order_type": "profit_stop",    # Fixed take-profit
            "side": "sell",
            "price_scale": tp_gain_pct,     # "150" = sell at 2.5x
            "sell_ratio": "100"             # Sell entire position
        },
    ]

    payload = {
        "chain": "sol",
        "from": WALLET,
        "input_token": SOL_MINT,
        "output_token": mint,
        "amount": str(int(BUY_AMOUNT_SOL * 1e9)),  # lamports
        "slippage": "0.3",
        "is_anti_mev": True,
        "fee": "0.01",
        "condition_orders": condition_orders,
        "sell_ratio_type": "hold_amount",
    }

    log.info(f"BUY | {name} | {BUY_AMOUNT_SOL} SOL | TP={TP_MULTIPLIER}x")

    data = await api_post(session, "/v1/trade/swap", payload)
    if not data:
        return None, None, None

    order_id = data.get("order_id", "")
    strategy_id = data.get("strategy_order_id", "")
    status = data.get("status", "unknown")

    log.info(f"BUY SUBMITTED | {name} | order={order_id} | status={status}")

    # Poll for confirmation (up to 20 seconds)
    for _ in range(4):
        if status in ("confirmed", "failed", "expired"):
            break
        await asyncio.sleep(5)
        # Query order status
        auth = {"timestamp": str(int(time.time())), "client_id": str(uuid.uuid4())}
        async with session.get(
            f"{GMGN_HOST}/v1/trade/query_order",
            params={"chain": "sol", "order_id": order_id, **auth},
            headers={"X-APIKEY": GMGN_TRADE_KEY, "User-Agent": "Mozilla/5.0"},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as r:
            d = await r.json()
            if d.get("code") == 0 and d.get("data"):
                status = d["data"].get("status", status)
                data = d["data"]

    report = data.get("report", {}) or {}
    if status == "confirmed" or report.get("output_amount"):
        price_usd = float(report.get("price_usd", 0) or 0)
        log.info(f"BUY CONFIRMED | {name} | price=${price_usd} | strategy={strategy_id}")
        return order_id, strategy_id, price_usd

    log.error(f"BUY FAILED | {name} | status={status}")
    return None, None, None


# --- Example: Other condition order types ---

def example_condition_orders():
    """
    GMGN supports several condition order types:

    1. profit_stop — Fixed take-profit
       Sells when price rises by price_scale percent.

    2. profit_stop_trace — Trailing take-profit
       Activates after price_scale gain, then trails with drawdown_rate.

    3. loss_stop — Stop loss
       Sells when price drops by price_scale percent.

    These can be combined for complex strategies:
    """

    # Strategy: 50% at 2x, trail rest with 30% drawdown, SL at -50%
    complex_strategy = [
        {
            "order_type": "profit_stop",
            "side": "sell",
            "price_scale": "100",       # Sell at 2x (+100%)
            "sell_ratio": "50"          # Sell 50% of position
        },
        {
            "order_type": "profit_stop_trace",
            "side": "sell",
            "price_scale": "100",       # Activate trail after 2x
            "sell_ratio": "100",        # Sell remaining 100%
            "drawdown_rate": "30"       # 30% trailing stop
        },
        {
            "order_type": "loss_stop",
            "side": "sell",
            "price_scale": "50",        # Stop loss at -50%
            "sell_ratio": "100"         # Sell everything
        },
    ]

    return complex_strategy
