"""Manual test script for the player-analysis radar builder.

Reads from the local cache (no API calls) and writes two test radar plots:

    same_position  — A. Jacob (CF) vs W. Gibson (CF)
                     Both strikers, so position-specific forward benchmarks apply.

    mixed_position — L. Brahim (RCMF3) vs P. Lilja (AMF)
                     Different positions, so general (all-player) benchmarks apply.

Usage:
    python pipeline/sections/player_analysis/tests.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.sections.player_analysis.plots import (
    build_player_position_map,
    build_player_radar,
    make_player_radar_input,
)
from pipeline.settings import load_settings

COMPETITION_ID = 810

STAT_KEYS = [
    "average.goals",
    "average.xgShot",
    "average.shots",
    "average.touchInBox",
    "average.keyPasses",
    "average.successfulDribbles",
    "percent.aerialDuelsWon",
]
STAT_LABELS = [
    "Goals/90",
    "xG/90",
    "Shots/90",
    "Box touches/90",
    "Key passes/90",
    "Dribbles/90",
    "Aerial won %",
]


def _load_benchmarks(settings) -> dict:
    path = settings.player_cache_dir / f"competition_{COMPETITION_ID}_position_benchmarks.json"
    return json.loads(path.read_text(encoding="utf-8"))["benchmarks"]


def _load_players(settings) -> dict[int, dict]:
    path = settings.player_cache_dir / f"competition_{COMPETITION_ID}_players.json"
    players = json.loads(path.read_text(encoding="utf-8"))["players"]
    return {p["wyId"]: p for p in players}


def _load_stats(settings, wy_id: int) -> dict:
    path = settings.player_cache_dir / f"player_{wy_id}_advancedstats_comp{COMPETITION_ID}.json"
    return json.loads(path.read_text(encoding="utf-8"))["stats"]


def main() -> int:
    settings = load_settings()
    benchmarks = _load_benchmarks(settings)
    players_by_id = _load_players(settings)
    output_dir = settings.report_path("player_analysis", "plots")

    # --- Same-position: A. Jacob (CF) vs W. Gibson (CF) -------------------
    p1 = make_player_radar_input(players_by_id[1322996], _load_stats(settings, 1322996), team_name="IK Sirius")
    p2 = make_player_radar_input(players_by_id[1315729], _load_stats(settings, 1315729), team_name="Östers IF")

    same_pos_path = build_player_radar(
        players=[p1, p2],
        stat_keys=STAT_KEYS,
        stat_labels=STAT_LABELS,
        benchmarks=benchmarks,
        output_path=output_dir / "test_radar_compare.png",
        style=settings.plot_style,
        title="Player Radar",
    )
    print(f"Same-position radar  → {same_pos_path.relative_to(PROJECT_ROOT)}")

    # --- Mixed-position: L. Brahim (FW) vs P. Lilja (DF) ------------------
    p3 = make_player_radar_input(players_by_id[1325274], _load_stats(settings, 1325274), team_name="Jönköpings Södra")
    p4 = make_player_radar_input(players_by_id[1316266], _load_stats(settings, 1316266), team_name="IFK Värnamo")

    mixed_path = build_player_radar(
        players=[p3, p4],
        stat_keys=STAT_KEYS,
        stat_labels=STAT_LABELS,
        benchmarks=benchmarks,
        output_path=output_dir / "test_radar_mixed.png",
        style=settings.plot_style,
        title="Player Radar",
    )
    print(f"Mixed-position radar → {mixed_path.relative_to(PROJECT_ROOT)}")

    # --- Position map: player who plays multiple positions (J. Drott MD) ----
    # wyId 51679 plays DMF + LCMF + LDMF — good multi-position example
    p5 = make_player_radar_input(players_by_id[51679], _load_stats(settings, 51679), team_name="Jönköpings Södra")

    pos_map_path = build_player_position_map(
        player=p5,
        output_path=output_dir / "test_position_map.png",
        style=settings.plot_style,
        title="Position Map",
    )
    print(f"Position map         → {pos_map_path.relative_to(PROJECT_ROOT)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
