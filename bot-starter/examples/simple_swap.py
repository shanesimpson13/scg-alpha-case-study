#!/usr/bin/env python3
"""
simple_swap.py — minimal Jupiter Ultra swap example.

Demonstrates: load wallet → quote → swap → confirm. No filters, no signal
loop, no journaling. Just buys 0.01 SOL of a token you specify and exits.

Use this to verify your wallet, JUP_API_KEY, and RPC are set up correctly
BEFORE running the full trader.

Usage:
    cd bot-starter
    cp .env.example .env
    # Fill in WALLET_ADDRESS, WALLET_PRIVATE_KEY, JUP_API_KEY in .env
    python examples/simple_swap.py <MINT_ADDRESS>
"""
import asyncio
import sys
from pathlib import Path

# Allow `from scg_ultra import ...` when run from examples/
sys.path.insert(0, str(Path(__file__).parent.parent))

import aiohttp
from solders.keypair import Keypair
from dotenv import load_dotenv
import os

load_dotenv(Path(__file__).parent.parent / ".env")

from scg_ultra import ultra_swap


SOL_MINT = "So11111111111111111111111111111111111111112"
BUY_SIZE_SOL = 0.01  # 0.01 SOL ≈ $1 — tiny test amount


async def main(target_mint: str):
    privkey = os.getenv("WALLET_PRIVATE_KEY", "").strip()
    api_key = os.getenv("JUP_API_KEY", "").strip()

    if not privkey:
        print("Set WALLET_PRIVATE_KEY in .env")
        return
    if not api_key:
        print("Set JUP_API_KEY in .env (get one at https://portal.jup.ag/)")
        return

    kp = Keypair.from_base58_string(privkey)
    amount_lamports = int(BUY_SIZE_SOL * 1e9)

    print(f"Wallet:      {kp.pubkey()}")
    print(f"Buying:      {BUY_SIZE_SOL} SOL of {target_mint}")
    print(f"Lamports:    {amount_lamports:,}")
    print()

    async with aiohttp.ClientSession() as s:
        sig, out = await ultra_swap(s, SOL_MINT, target_mint, amount_lamports, kp, api_key)

    if sig:
        print(f"✅ Swap confirmed")
        print(f"   tx:        {sig}")
        print(f"   tokens out: {out:,}")
        print(f"   solscan:    https://solscan.io/tx/{sig}")
    else:
        print("❌ Swap failed (see logs above)")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python examples/simple_swap.py <MINT_ADDRESS>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
