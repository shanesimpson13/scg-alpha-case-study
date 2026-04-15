"""
GMGN Trending Scanner — Discovery Engine

Polls GMGN /v1/market/rank every 30 seconds and tracks tokens across
multiple consecutive scans. Tokens qualify after 10+ scans (~5min) with
healthy holder growth and stable liquidity.

This scan-loop approach replaces expensive websocket connections and gives
us holder growth trajectory data — the strongest signal we've found.
"""

import os, time, asyncio, uuid, logging
import aiohttp

GMGN_HOST = "https://openapi.gmgn.ai"
GMGN_KEY = os.getenv("GMGN_API_KEY", "")

SCAN_INTERVAL = 30          # seconds between scans
MIN_SCANS = 10              # scans before qualifying (~5min)
MIN_HOLDERS = 150           # minimum holder count
MIN_HOLDER_GROWTH = 0.07    # 7% holder growth required
MAX_HOLDER_GROWTH = 0.50    # 50% max (above = bot inflation)
MAX_AGE = 14400             # 4hr max token age
MIN_AGE = 300               # 5min minimum age

log = logging.getLogger("scanner")


def _auth():
    return {"timestamp": str(int(time.time())), "client_id": str(uuid.uuid4())}


async def api_get(session, path, params={}):
    """GET from GMGN API with auth."""
    auth = _auth()
    try:
        async with session.get(
            f"{GMGN_HOST}{path}",
            params={**params, **auth},
            headers={"X-APIKEY": GMGN_KEY, "User-Agent": "Mozilla/5.0"},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as r:
            if r.status in (429, 403):
                await asyncio.sleep(2)
                return None
            d = await r.json()
            return d.get("data") if d.get("code") == 0 else None
    except Exception as e:
        log.error(f"GET {path}: {e}")
    return None


async def scan_trending(session, on_qualified):
    """
    Continuously scan GMGN trending and track tokens across scans.

    on_qualified(token_data) is called when a token passes all checks.
    """
    tracker = {}  # {mint: {name, first_seen, scans: [...], miss_count}}

    while True:
        data = await api_get(session, "/v1/market/rank", {
            "chain": "sol",
            "type": "5m",
            "limit": 50
        })

        if not data:
            await asyncio.sleep(SCAN_INTERVAL)
            continue

        # Parse trending list
        tokens = (
            data.get("data", {}).get("rank", [])
            if isinstance(data.get("data"), dict)
            else data.get("rank", [])
        )
        if not tokens and isinstance(data, list):
            tokens = data

        current_mints = set()
        now = time.time()

        for t in (tokens or []):
            mint = t.get("address") or t.get("mint", "")
            if not mint:
                continue
            current_mints.add(mint)

            # Age filter
            created = t.get("creation_timestamp", 0)
            if created:
                age = now - float(created)
                if age < MIN_AGE or age > MAX_AGE:
                    continue

            # Holder filter
            holders = int(t.get("holder_count", 0) or 0)
            if holders < MIN_HOLDERS:
                continue

            name = t.get("symbol") or t.get("name") or mint[:8]
            mcap = float(t.get("market_cap", 0) or 0)
            liq = float(t.get("liquidity", 0) or 0)

            # Start tracking new tokens
            if mint not in tracker:
                log.info(f"TRACKING | {name} | h={holders} mcap=${mcap:,.0f}")
                tracker[mint] = {
                    "name": name,
                    "mint": mint,
                    "first_seen": now,
                    "miss_count": 0,
                    "scans": [],
                }

            # Record scan data
            tracker[mint]["miss_count"] = 0
            tracker[mint]["scans"].append({
                "holders": holders,
                "liq": liq,
                "mcap": mcap,
                "volume": float(t.get("volume", 0) or 0),
                "buys": int(t.get("buys", 0) or 0),
                "sells": int(t.get("sells", 0) or 0),
                "5m_pct": float(t.get("price_change_percent5m", 0) or 0),
                "rug_ratio": float(t.get("rug_ratio", 0) or 0),
                "entrapment_ratio": float(t.get("entrapment_ratio", 0) or 0),
                "bundler_rate": float(t.get("bundler_rate", 0) or 0),
                "bot_degen_rate": float(t.get("bot_degen_rate", 0) or 0),
                "ts": now,
            })

        # Check qualification for tracked tokens
        expired = []
        for mint, tr in tracker.items():
            if mint not in current_mints:
                tr["miss_count"] += 1
                if tr["miss_count"] >= 3:
                    expired.append(mint)
                continue

            scans = tr["scans"]
            if len(scans) < MIN_SCANS:
                continue

            # Calculate holder growth
            first_h = scans[0]["holders"]
            last_h = scans[-1]["holders"]
            growth = (last_h - first_h) / first_h if first_h > 0 else 0

            # Check liquidity trend (last 3 scans)
            last_3_liq = [s["liq"] for s in scans[-3:]]
            liq_healthy = last_3_liq[-1] >= last_3_liq[0]

            if MIN_HOLDER_GROWTH <= growth <= MAX_HOLDER_GROWTH and liq_healthy:
                log.info(
                    f"QUALIFIED | {tr['name']} | {len(scans)} scans | "
                    f"h: {first_h}->{last_h} (+{growth*100:.1f}%) | "
                    f"liq: ${last_3_liq[0]:,.0f}->${last_3_liq[-1]:,.0f}"
                )
                await on_qualified(tr)
                expired.append(mint)

        for mint in expired:
            tracker.pop(mint, None)

        await asyncio.sleep(SCAN_INTERVAL)
