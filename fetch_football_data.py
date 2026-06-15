"""Command-line entrypoint for the J-Södra analytics pipeline.

This file should stay intentionally small.

Do not add feature logic here.
Do not add Wyscout logic here.
Do not add plotting logic here.

The job of this file is only to:

1. Parse command-line arguments.
2. Load settings.
3. Start the pipeline orchestrator.
"""

from __future__ import annotations

import argparse

from pipeline.orchestrator import run_pipeline
from pipeline.settings import load_settings


def parse_args(argv=None):
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
