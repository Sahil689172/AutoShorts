#!/usr/bin/env python3
"""CLI for offline asset collection — separate from video generation."""

from __future__ import annotations

import argparse
import logging
import sys

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from backend.services.assets.collector import AssetCollector, AssetCollectorError
from backend.services.assets.providers import available_provider_names

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def _prompt(text: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        value = input(f"{text}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled.", file=sys.stderr)
        raise SystemExit(130)
    return value or default


def _parse_providers(raw: str) -> list[str]:
    names = [p.strip().lower() for p in raw.split(",") if p.strip()]
    return names or ["pexels"]


def run_interactive() -> int:
    print("AutoShorts Asset Collector")
    print("──────────────────────────")
    topic = _prompt("Topic")
    if not topic:
        print("Error: Topic cannot be empty.", file=sys.stderr)
        return 1

    count_raw = _prompt("Desired Count", "20")
    try:
        desired_count = int(count_raw)
    except ValueError:
        print("Error: Desired count must be a number.", file=sys.stderr)
        return 1

    default_providers = ",".join(available_provider_names())
    providers_raw = _prompt("Providers", default_providers)
    providers = _parse_providers(providers_raw)

    return _run_collection(topic, desired_count, providers)


def _run_collection(topic: str, desired_count: int, providers: list[str]) -> int:
    collector = AssetCollector()
    try:
        collector.collect(topic, desired_count, providers)
    except AssetCollectorError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        logger.exception("Collection failed")
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Collect stock assets into the local library (offline from video generation)."
    )
    parser.add_argument("topic", nargs="?", help="Collection topic (e.g. Ferrari)")
    parser.add_argument(
        "-n",
        "--count",
        type=int,
        default=None,
        help="Desired number of assets to download",
    )
    parser.add_argument(
        "-p",
        "--providers",
        default=None,
        help=f"Comma-separated providers (default: pexels). Available: {', '.join(available_provider_names())}",
    )
    parser.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="Interactive prompts for topic, count, and providers",
    )

    args = parser.parse_args()

    if args.interactive or not args.topic:
        return run_interactive()

    desired_count = args.count
    if desired_count is None:
        count_raw = _prompt("Desired Count", "20")
        try:
            desired_count = int(count_raw)
        except ValueError:
            print("Error: Desired count must be a number.", file=sys.stderr)
            return 1

    providers = _parse_providers(args.providers or "pexels")
    return _run_collection(args.topic, desired_count, providers)


if __name__ == "__main__":
    raise SystemExit(main())
