"""Minimal section smoke-test helper.

This does not fetch Wyscout data. It builds a tiny PipelineContext with empty
datasets and runs one section. Use it to check imports, publishing, and JSON
contract shape quickly.

Examples:
    python tools/smoke_test_section.py corners
    python tools/smoke_test_section.py head_to_head
"""

from __future__ import annotations

import importlib
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

# Make repo root importable when this script is run from tools/.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from pipeline.context import PipelineContext
from pipeline.settings import load_settings


def empty_dataset():
    return {
        "matches_df": pd.DataFrame(),
        "season_matches_df": pd.DataFrame(),
        "analysis_matches_df": pd.DataFrame(),
        "events_df": pd.DataFrame(),
        "analysis_events_df": pd.DataFrame(),
        "selected_match_ids": [],
        "with_events": [],
        "without_events": [],
        "analysis_scope": {},
        "season_id": None,
    }


def main() -> int:
    section_name = sys.argv[1] if len(sys.argv) > 1 else "corners"

    settings = load_settings(force_refresh=False)
    settings.reports_dir.mkdir(parents=True, exist_ok=True)

    context = PipelineContext(
        settings=settings,
        service=SimpleNamespace(),
        generated_at=datetime.now(timezone.utc).isoformat(),
        team={"id": 1, "name": "J-Södra", "logo_url": None, "season_id": None},
        next_opponent={
            "id": 2,
            "name": "Next opponent",
            "logo_url": None,
            "season_id": None,
        },
        team_data=empty_dataset(),
        opponent_data=empty_dataset(),
        matchup=None,
        extras={},
    )

    module = importlib.import_module(f"pipeline.sections.{section_name}")
    result = module.build_section(context)

    print(f"Section: {result.name}")
    print(f"Files: {[str(path) for path in result.files]}")
    print(f"Existing files: {[str(path) for path in result.existing_files()]}")
    print(f"Index entry: {result.index_entry}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())