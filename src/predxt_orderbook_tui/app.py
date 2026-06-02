from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import AsyncIterator

from predxt import OrderBookState, VenueMessage
from predxt.kalshi import KalshiWsClient
from predxt.opinion import OpinionWsClient
from predxt.polymarket import PolymarketWsClient
from rich.console import Console
from rich.live import Live
from rich.table import Table


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return asyncio.run(_run(args))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only predxt orderbook TUI.")
    parser.add_argument("--jsonl", type=Path, help="Optional JSONL recording path.")
    parser.add_argument("--limit", type=int, default=0, help="Stop after N messages.")
    subcommands = parser.add_subparsers(dest="venue", required=True)

    polymarket = subcommands.add_parser("polymarket")
    polymarket.add_argument("--asset-id", dest="asset_ids", action="append", required=True)

    kalshi = subcommands.add_parser("kalshi")
    kalshi.add_argument("--market", dest="markets", action="append", required=True)

    opinion = subcommands.add_parser("opinion")
    opinion.add_argument("--market-id", dest="market_ids", action="append", required=True)
    return parser


async def _run(args: argparse.Namespace) -> int:
    console = Console()
    state = OrderBookState()
    count = 0
    recorder = args.jsonl.open("a", encoding="utf-8") if args.jsonl else None

    try:
        async with _messages(args) as messages:
            with Live(_render(state, count), console=console, refresh_per_second=4) as live:
                async for message in messages:
                    count += 1
                    state.apply(message)
                    if recorder:
                        recorder.write(json.dumps(_record(message), sort_keys=True) + "\n")
                        recorder.flush()
                    live.update(_render(state, count))
                    if args.limit and count >= args.limit:
                        return 0
    finally:
        if recorder:
            recorder.close()
    return 0


class _messages:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.client: PolymarketWsClient | KalshiWsClient | OpinionWsClient | None = None

    async def __aenter__(self) -> AsyncIterator[VenueMessage]:
        if self.args.venue == "polymarket":
            client = PolymarketWsClient()
            await client.connect()
            await client.subscribe(
                ["market"],
                {"assets_ids": self.args.asset_ids, "initial_dump": True},
            )
        elif self.args.venue == "kalshi":
            client = KalshiWsClient()
            await client.connect(_kalshi_auth_from_env())
            await client.subscribe(
                ["orderbook_snapshot", "orderbook_delta"],
                {"market_tickers": self.args.markets},
            )
        else:
            api_key = os.environ.get("OPINION_API_KEY", "").strip()
            if not api_key:
                raise SystemExit("Set OPINION_API_KEY.")
            client = OpinionWsClient(api_key=api_key)
            await client.connect()
            await client.subscribe(
                ["market.depth.diff"],
                {"market_ids": self.args.market_ids},
            )

        self.client = client
        return client.messages()

    async def __aexit__(self, *_exc: object) -> None:
        if self.client:
            await self.client.close()


def _render(state: OrderBookState, count: int) -> Table:
    table = Table(title=f"predxt orderbook monitor - {count} messages")
    table.add_column("Side")
    table.add_column("Price", justify="right")
    table.add_column("Size", justify="right")
    for level in state.snapshot(depth=10)["asks"]:
        table.add_row("ask", f"{level['price']:.4f}", f"{level['size']:.2f}")
    table.add_section()
    for level in state.snapshot(depth=10)["bids"]:
        table.add_row("bid", f"{level['price']:.4f}", f"{level['size']:.2f}")
    return table


def _record(message: VenueMessage) -> dict[str, object]:
    return {
        "venue": message.venue,
        "event_type": message.event_type,
        "market_id": message.market_id,
        "asset_id": message.asset_id,
        "timestamp_ms": message.timestamp_ms,
        "raw_data": message.raw_data,
    }


def _kalshi_auth_from_env() -> dict[str, str]:
    key_id = os.environ.get("KALSHI_KEY_ID", "").strip()
    signature = os.environ.get("KALSHI_SIGNATURE", "").strip()
    timestamp = os.environ.get("KALSHI_TIMESTAMP", "").strip()
    private_key_path = os.environ.get("KALSHI_PRIVATE_KEY_PATH", "").strip()
    if key_id and signature and timestamp:
        return {"key_id": key_id, "signature": signature, "timestamp": timestamp}
    if key_id and private_key_path:
        return {
            "key_id": key_id,
            "private_key_pem": Path(private_key_path).read_text(),
        }
    raise SystemExit(
        "Set KALSHI_KEY_ID plus either KALSHI_SIGNATURE/KALSHI_TIMESTAMP "
        "or KALSHI_PRIVATE_KEY_PATH."
    )


if __name__ == "__main__":
    raise SystemExit(main())
