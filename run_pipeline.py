"""Command-line entrypoint for the J-Södra analytics pipeline.

Keep this file intentionally small. Do not add feature logic, Wyscout logic,
plotting logic, or section-specific logic here.
"""

from __future__ import annotations

import argparse

from pipeline.orchestrator import run_pipeline
from pipeline.settings import load_settings


def parse_args(argv=None):
    """Parse command-line arguments for the analytics pipeline."""

    parser = argparse.ArgumentParser(
        description="Fetch and publish J-Södra football analytics."
    )
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Bypass local caches and fetch fresh data from the Wyscout API.",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    settings = load_settings(force_refresh=args.force_refresh)
    return run_pipeline(settings)


if __name__ == "__main__":
    raise SystemExit(main())
