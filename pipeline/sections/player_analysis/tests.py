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
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("OUTPUT_DIR", str(PROJECT_ROOT))

from pipeline.sections.player_analysis.plots import (
    build_player_pizza,
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

ST_STAT_KEYS = [
    "average.goals",
    "average.xgShot",
    "average.shots",
    "percent.goalConversion",
    "percent.shotsOnTarget",
    "average.touchInBox",
    "average.headShots",
    "average.aerialDuels",
    "percentage.aerialDuelsWon",
    "average.xgAssist",
    "average.linkupPlays",
    "average.receivedPass",
    "average.counterpressingRecoveries"
]

ST_STAT_LABELS = [
    "Goals/90",
    "xG/90",
    "Shots/90",
    "Goal Conversion %",
    "Shots on Target %",
    "Box touches/90",
    "Header shots/90",
    "Aerial duels/90",
    "Aerial won %",
    "xG Assists/90",
    "Link-up plays/90",
    "Received passes/90",
    "Counterpressing recoveries/90"
]



_CACHE_DIR = PROJECT_ROOT / "cache" / "players"


def _load_benchmarks() -> dict:
    path = _CACHE_DIR / f"competition_{COMPETITION_ID}_position_benchmarks.json"
    return json.loads(path.read_text(encoding="utf-8"))["benchmarks"]


def _load_players() -> dict[int, dict]:
    path = _CACHE_DIR / f"competition_{COMPETITION_ID}_players.json"
    players = json.loads(path.read_text(encoding="utf-8"))["players"]
    return {p["wyId"]: p for p in players}


def _load_stats(wy_id: int) -> dict:
    path = _CACHE_DIR / f"player_{wy_id}_advancedstats_comp{COMPETITION_ID}.json"
    return json.loads(path.read_text(encoding="utf-8"))["stats"]


def main() -> int:
    settings = load_settings()
    benchmarks = _load_benchmarks()
    players_by_id = _load_players()
    output_dir = PROJECT_ROOT / "reports" / "player_analysis" / "plots"
    output_dir.mkdir(parents=True, exist_ok=True)

    # --- Same-position: A. Jacob (CF) vs W. Gibson (CF) -------------------
    p1 = make_player_radar_input(players_by_id[1322996], _load_stats(1322996), team_name="IK Sirius")
    p2 = make_player_radar_input(players_by_id[1315729], _load_stats(1315729), team_name="Östers IF")

    same_pos_path = build_player_radar(
        players=[p1, p2],
        stat_keys=ST_STAT_KEYS,
        stat_labels=ST_STAT_LABELS,
        benchmarks=benchmarks,
        output_path=output_dir / "test_radar_compare.png",
        style=settings.plot_style,
        show_footer=False,
    )
    print(f"Same-position radar  → {same_pos_path.relative_to(PROJECT_ROOT)}")

    # --- Same-position radar: A. Jacob (CF) ---------------
    jaboc_radar = build_player_radar(
        players=[p1],
        stat_keys=ST_STAT_KEYS,
        stat_labels=ST_STAT_LABELS,
        benchmarks=benchmarks,
        output_path=output_dir / "jacob_radar.png",
        style=settings.plot_style,
        show_footer=False,
    )
    print(f"Same-position radar  → {jaboc_radar.relative_to(PROJECT_ROOT)}")

    # --- Mixed-position: L. Brahim (FW) vs P. Lilja (DF) ------------------
    p3 = make_player_radar_input(players_by_id[1325274], _load_stats(1325274), team_name="Jönköpings Södra")
    p4 = make_player_radar_input(players_by_id[1316266], _load_stats(1316266), team_name="IFK Värnamo")

    mixed_path = build_player_radar(
        players=[p3, p4],
        stat_keys=STAT_KEYS,
        stat_labels=STAT_LABELS,
        benchmarks=benchmarks,
        output_path=output_dir / "test_radar_mixed.png",
        style=settings.plot_style,
        show_footer=False,
    )
    print(f"Mixed-position radar → {mixed_path.relative_to(PROJECT_ROOT)}")

    # --- Same-position pizza: A. Jacob (CF) ---------------
    pizza_path = build_player_pizza(
        players=[p1],
        stat_keys=ST_STAT_KEYS,
        stat_labels=ST_STAT_LABELS,
        benchmarks=benchmarks,
        output_path=output_dir / "test_pizza.png",
        style=settings.plot_style,
        show_footer=False,
    )
    print(f"Same-position pizza  → {pizza_path.relative_to(PROJECT_ROOT)}")

    # --- Position map: O. Hakansson (Rosengård) — plays DMF/AMF/CF, high vertical spread ---
    p5 = make_player_radar_input(players_by_id[1316298], _load_stats(1316298), team_name="Rosengård")

    pos_map_path = build_player_position_map(
        player=p5,
        output_path=output_dir / "hakansson_position_map.png",
        style=settings.plot_style,
        show_footer=False
    )

    pos_map_path = build_player_position_map(
        player=p3,
        output_path=output_dir / "brahim_position_map.png",
        style=settings.plot_style,
        show_footer=False
    )
    print(f"Position map         → {pos_map_path.relative_to(PROJECT_ROOT)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
