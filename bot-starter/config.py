"""
Config — all knobs in one place. Override anything via env vars.

Copy .env.example to .env and fill in YOUR values. The bot will refuse to
start without an SCG_API_KEY — get one at https://scgalpha.com.
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


def _f(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


def _i(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _b(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).lower() in ("1", "true", "yes", "on")


# ─── Subscription gate ──────────────────────────────────────────────────────
# Your SCG Alpha API key. The bot refuses to start without this.
# Get one at https://scgalpha.com (subscriptions start at $49/mo).
SCG_API_KEY = os.getenv("SCG_API_KEY", "").strip()
SCG_API_BASE = os.getenv("SCG_API_BASE", "https://api.scgalpha.com").rstrip("/")

if not SCG_API_KEY:
    print(
        "\n❌ No SCG_API_KEY found.\n\n"
        "This bot reads signals from the SCG Alpha API.\n"
        "Get a key at https://scgalpha.com (subscriptions start at $49/mo).\n\n"
        "Then add it to your .env:\n"
        "  SCG_API_KEY=mem_xxxxxxxxxxxx\n",
        file=sys.stderr,
    )
    sys.exit(1)


# ─── Run mode ───────────────────────────────────────────────────────────────
# DRY_RUN=1 by default — no real swaps, just log what would happen. ALWAYS
# stress-test in dry mode for at least 24h before flipping to live.
DRY_RUN = _b("SCG_DRY_RUN", True)


# ─── Position sizing ────────────────────────────────────────────────────────
# Start TINY when you go live ($5-10 per trade). Scale only after 50+ live
# trades that match your backtest within 20%.
BUY_SIZE_SOL = _f("SCG_BUY_SIZE_SOL", 0.05)  # ~$5 at $100 SOL
MAX_CONCURRENT = _i("SCG_MAX_CONCURRENT", 3)


# ─── Polling cadence ────────────────────────────────────────────────────────
ALERT_POLL_SECS = _f("SCG_ALERT_POLL_SECS", 5)   # check API for new signals
PRICE_POLL_SECS = _f("SCG_PRICE_POLL_SECS", 5)   # quote each open position


# ─── Sell behavior ──────────────────────────────────────────────────────────
SELL_RETRY_COOLDOWN_SECS = _i("SCG_SELL_COOLDOWN", 60)


# ─── Wallet ─────────────────────────────────────────────────────────────────
# Use a DEDICATED bot wallet. Never put your main wallet's privkey here.
# Only fund what you're willing to lose.
WALLET_ADDRESS = os.getenv("WALLET_ADDRESS", "").strip()
WALLET_PRIVATE_KEY = os.getenv("WALLET_PRIVATE_KEY", "").strip()


# ─── Jupiter Ultra ──────────────────────────────────────────────────────────
# Get a free key at https://portal.jup.ag/
JUP_API_KEY = os.getenv("JUP_API_KEY", "").strip()


# ─── RPC ────────────────────────────────────────────────────────────────────
# Use a dedicated RPC (Helius, QuickNode). Public RPC will fail you under load.
HELIUS_KEY = os.getenv("HELIUS_API_KEY", "").strip()
HELIUS_RPC = (
    f"https://mainnet.helius-rpc.com/?api-key={HELIUS_KEY}"
    if HELIUS_KEY
    else "https://api.mainnet-beta.solana.com"
)


# ─── Optional Telegram alerts ───────────────────────────────────────────────
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TG_CHAT = os.getenv("TELEGRAM_CHAT_ID", "").strip()


# ─── Optional referral (Jupiter Ultra) ──────────────────────────────────────
REFERRAL_ACCOUNT = os.getenv("SCG_REFERRAL_ACCOUNT", "").strip()
REFERRAL_FEE_BPS = _i("SCG_REFERRAL_FEE_BPS", 0)


# ─── Constants ──────────────────────────────────────────────────────────────
SOL_MINT = "So11111111111111111111111111111111111111112"


# ─── Paths (relative to repo) ───────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
STATE_FILE = BASE_DIR / "state" / "positions.json"
TRADES_LOG = BASE_DIR / "trades.jsonl"
