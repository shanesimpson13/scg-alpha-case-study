"""
GMGN Token Scoring Engine

Computes a 0-100 conviction score for each token using GMGN's rich
on-chain metrics. Higher scores indicate stronger signals with lower
scam probability and healthier market dynamics.

The scoring weights were derived from backtesting 100+ historical signals
against actual return data.
"""


def compute_score(token_data):
    """
    Compute conviction score (0-100) from GMGN token data.

    Inputs come from /v1/token/info, /v1/token/security, and /v1/market/rank.

    Returns:
        int: Score from 0-100
    """
    score = 0.0

    # --- Safety metrics (45 points) ---
    # Rug ratio: probability of rug pull based on on-chain patterns
    # Lower = safer. From /v1/market/rank or /v1/token/security
    rug_ratio = float(token_data.get("rug_ratio", 0) or 0)
    score += 25 * (1 - min(rug_ratio, 1.0))

    # Entrapment ratio: likelihood token is an entrapment scheme
    # Lower = safer. From /v1/market/rank
    entrapment = float(token_data.get("entrapment_ratio", 0) or 0)
    score += 20 * (1 - min(entrapment, 1.0))

    # --- Growth metrics (15 points) ---
    # Holder growth over tracking period (measured across 10+ scans)
    # Sweet spot: 7-50%. Below = stagnant, above = bot inflation
    growth = float(token_data.get("holder_growth_pct", 0) or 0) / 100
    if growth > 0:
        growth_score = min(growth / 0.50, 1.0)  # scales linearly to 50%
        score += 15 * growth_score

    # --- Quality metrics (20 points) ---
    # Bot/degen wallet percentage: high = artificial holder count
    # From /v1/token/info -> stat.bot_degen_rate
    bot_degen = float(token_data.get("bot_degen_rate", 0) or 0)
    if bot_degen < 0.45:
        score += 10 * (1 - bot_degen / 0.45)

    # Bundler rate: bundled transactions = coordinated manipulation
    # From /v1/market/rank -> bundler_rate
    bundler = float(token_data.get("bundler_rate", 0) or 0)
    if bundler < 0.40:
        score += 10 * (1 - bundler / 0.40)

    # --- Social metrics (10 points) ---
    # KOL (Key Opinion Leader) count: smart money attention
    # From /v1/market/rank -> renowned_count or similar
    kol_count = int(token_data.get("kol_count", 0) or 0)
    score += 10 * min(kol_count / 3, 1.0)

    # --- Bonus conditions (up to 10 points) ---
    # Additional signals that boost conviction
    # (specific thresholds omitted — these are our edge)

    return max(0, min(100, int(score)))


def passes_filters(token_data):
    """
    Apply scam detection filters using GMGN data.
    Returns True if token passes all safety checks.
    """
    # Developer team hold rate — high = potential rug
    dev_hold = float(token_data.get("dev_team_hold_rate", 0) or 0)
    if dev_hold > 0.10:
        return False

    # Top 10 holder concentration — high = whale manipulation risk
    top10 = float(token_data.get("top_10_holder_rate", 0) or 0)
    if top10 > 0.30:
        return False

    # Bot/degen rate — high = artificial market
    bot_degen = float(token_data.get("bot_degen_rate", 0) or 0)
    if bot_degen > 0.45:
        return False

    # Bundler trader volume — high = coordinated activity
    bundler_vol = float(token_data.get("top_bundler_trader_pct", 0) or 0)
    if bundler_vol >= 0.40:
        return False

    # Migration check — must be migrated off bonding curve
    if not token_data.get("open_timestamp") and not token_data.get("migrated_timestamp"):
        return False

    # Wash trading detection: symmetric B/S + high volume
    buys = int(token_data.get("buys", 0) or 0)
    sells = int(token_data.get("sells", 0) or 0)
    volume = float(token_data.get("volume", 0) or 0)
    if sells > 0:
        bs_ratio = buys / sells
        if bs_ratio <= 1.15 and volume > 100000:
            return False

    return True
