# SCG Alpha Bot Starter

A working Solana auto-trading bot you can plug your strategy into. Reads signals from the SCG Alpha API, executes swaps via Jupiter Ultra (battle-tested submission + on-chain confirmation), tracks positions, handles partial sells, retries failed transactions, and logs everything.

**What's included:** the boring plumbing that's hard to get right — Jupiter swaps with retries, wallet balance reconciliation, dry-run mode, position state, Telegram alerts, lamport-based PnL.

**What's NOT included:** the SCG Alpha team's filter or exit values. `filters.py` ships with empty stubs. You bring your own — that's the whole point of [the playbook](https://scgalpha.com/welcome).

---

## Subscription required

The bot reads signals from `api.scgalpha.com`, which requires an active subscription. **Get a key at [scgalpha.com](https://scgalpha.com)** ($49/month). Without one, the bot exits on launch with a friendly message — there's no scraping path.

The code itself is open source (MIT). What's gated is the data feed.

---

## Quick start

```bash
# 1. Clone and install
git clone https://github.com/shanesimpson13/scg-alpha-case-study.git
cd scg-alpha-case-study/bot-starter
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# Edit .env — at minimum set SCG_API_KEY (from scgalpha.com)

# 3. Verify Jupiter swaps work (optional but recommended — uses 0.01 SOL real)
python examples/simple_swap.py <ANY_MINT_ADDRESS>

# 4. Run the bot in DRY mode (default — no real swaps)
python trader.py
```

By default `SCG_DRY_RUN=1` — the bot logs every decision but never sends a transaction. **Stress-test for 24+ hours in dry mode** before flipping to live.

---

## Going live

When you're ready:

1. Fund a **dedicated** bot wallet (never use your main). Only fund what you can afford to lose.
2. Get a Jupiter API key (free tier): https://portal.jup.ag/
3. Get a Helius RPC key (free tier): https://helius.dev/
4. Fill in `WALLET_ADDRESS`, `WALLET_PRIVATE_KEY`, `JUP_API_KEY`, `HELIUS_API_KEY` in `.env`
5. **Lower your buy size to $5-10 worth of SOL** (`SCG_BUY_SIZE_SOL=0.05`)
6. Set `SCG_DRY_RUN=0`
7. Run for ~50 trades. Verify win rate matches your backtest within 20%.
8. Only then scale up your buy size.

---

## File structure

```
bot-starter/
├── trader.py              ← main loop: signal → buy → manage → exit
├── filters.py             ← YOUR strategy lives here (TODO stubs to fill in)
├── scg_ultra.py           ← Jupiter Ultra swap helper (battle-tested)
├── config.py              ← env loading, all knobs
├── examples/
│   └── simple_swap.py     ← minimal swap test
├── requirements.txt
└── .env.example
```

The interesting parts (your edge) live in `filters.py`. Everything else is plumbing.

---

## Where to put your strategy

`filters.py` has two functions you'll edit:

```python
def passes_filter(alert: dict) -> Tuple[bool, str]:
    """Decide whether to BUY a fresh signal."""
    # YOUR rules here — see playbook Module 02 for the data points available
    return True, "OK"

def decide_exit(pos: dict) -> Optional[Tuple[str, Optional[int]]]:
    """Decide whether to EXIT (or partially exit) an open position."""
    # YOUR rules here — see playbook Module 06 for what works (and doesn't)
    return None
```

Run the bot with stub filters in dry mode for an hour to confirm everything wires up. Then start writing your real strategy — Modules 02 (journal) and 03 (backtest) of the playbook show how to find values that actually have edge.

---

## Telegram alerts (optional)

Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env`. Each buy/sell/error gets posted to your channel. See playbook Module 04 for setup.

---

## Common gotchas

- **Swaps fail silently** → check `JUP_API_KEY` is valid, wallet has SOL for gas (~0.01 SOL minimum).
- **Bot exits on launch** → missing `SCG_API_KEY`. Get one at scgalpha.com.
- **401 errors after working fine** → subscription lapsed. Renew at scgalpha.com.
- **High slippage on small caps** → expected. Jupiter Ultra uses dynamic routing but liquidity matters.
- **Failed sells** → the bot has a 60s cooldown before retry. If sells consistently fail, your priority fee may be too low (set via Jupiter's defaults).

---

## What this is not

- **Not financial advice.** Backtests lie, markets shift, you can lose money. Test in dry mode, scale slowly.
- **Not a managed service.** You run it on your machine or VPS, you fund the wallet, you bear the risk.
- **Not the SCG Alpha trader.** This is a clean skeleton based on the same plumbing, with the strategy intentionally stripped out.

---

## License

MIT. Use it, fork it, ship it. Just don't blame us if your bot loses money — the strategy is yours, the responsibility is yours.

---

## Support

- Subscribers: hop in the Discord (link is on [scgalpha.com/welcome](https://scgalpha.com/welcome) after checkout)
- Bug in the plumbing? Open a GitHub issue
- Strategy questions? Discord
