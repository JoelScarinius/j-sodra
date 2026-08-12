"""Player-analysis plots for Linus Lyck and Anmar Kiwarkis (Jönköpings Södra).

Generates the full set of individual and comparison plots for:

  Strikers  — L. Lyck (1060409)  vs  K. Grauberg Lepik (629185)
  Wingers   — A. Kiwarkis (1060411)  vs  J. Shamoun (789558)

Each player gets:
    position_map, action_heatmap, pizza (solo), shot_map,
    pass_start_heatmap, pass_end_heatmap, assist_map, dribble_map

Comparison pairs also generate a radar_compare plot.

Usage:
    python pipeline/sections/player_analysis/test_lyck_kiwarkis.py
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

from pipeline.sections.player_analysis.metrics import (
    load_player_dribbles,
    load_player_key_passes,
    load_player_open_play_actions,
    load_player_passes,
    load_player_shots,
)
from pipeline.sections.player_analysis.plots import (
    build_player_action_heatmap,
    build_player_assist_map,
    build_player_dribble_map,
    build_player_pass_end_heatmap,
    build_player_pass_heatmap,
    build_player_pizza,
    build_player_position_map,
    build_player_radar,
    build_player_shot_map,
    make_player_radar_input,
)
from pipeline.settings import load_settings

COMPETITION_ID = 810
TEAM_NAME = "Jönköpings Södra"

_CACHE_DIR = PROJECT_ROOT / "cache" / "players"
_EVENTS_DIR = PROJECT_ROOT / "cache" / "events"


# ---------------------------------------------------------------------------
# Striker stat profile
# ---------------------------------------------------------------------------
ST_STAT_KEYS = [
    "average.goals",
    "average.xgShot",
    "average.shots",
    "percent.goalConversion",
    "percent.shotsOnTarget",
    "average.touchInBox",
    "average.headShots",
    "average.aerialDuels",
    "percent.aerialDuelsWon",
    "average.xgAssist",
    "average.linkupPlays",
    "average.receivedPass",
    "average.counterpressingRecoveries",
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
    "Counterpressing recoveries/90",
]

# ---------------------------------------------------------------------------
# Winger stat profile
# ---------------------------------------------------------------------------
W_STAT_KEYS = [
    "average.goals",
    "average.xgShot",
    "average.shots",
    "percent.shotsOnTarget",
    "average.xgAssist",
    "average.keyPasses",
    "average.successfulDribbles",
    "percent.successfulDribbles",
    "average.successfulCrosses",
    "average.touchInBox",
    "average.progressiveRun",
    "average.counterpressingRecoveries",
]
W_STAT_LABELS = [
    "Goals/90",
    "xG/90",
    "Shots/90",
    "Shots on Target %",
    "xG Assists/90",
    "Key passes/90",
    "Succ. dribbles/90",
    "Dribble success %",
    "Succ. crosses/90",
    "Touches in box/90",
    "Progressive runs/90",
    "Counterpressing rec./90",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_benchmarks() -> dict:
    path = _CACHE_DIR / f"competition_{COMPETITION_ID}_position_benchmarks.json"
    return json.loads(path.read_text(encoding="utf-8"))["benchmarks"]


def _load_player(wy_id: int) -> dict:
    path = _CACHE_DIR / f"competition_{COMPETITION_ID}_players.json"
    players = json.loads(path.read_text(encoding="utf-8"))["players"]
    return next(p for p in players if p["wyId"] == wy_id)


def _load_stats(wy_id: int) -> dict:
    path = _CACHE_DIR / f"player_{wy_id}_advancedstats_comp{COMPETITION_ID}.json"
    return json.loads(path.read_text(encoding="utf-8"))["stats"]


def _build_all_plots(
    player: dict,
    folder: Path,
    style: dict,
    *,
    show_footer: bool = False,
) -> None:
    """Generate the individual (non-comparison) plots for one player."""
    wy_id = player["player_id"]

    # Position map
    p = build_player_position_map(
        player=player,
        output_path=folder / "position_map.png",
        style=style,
        show_footer=show_footer,
    )
    print(f"  position_map         → {p.relative_to(PROJECT_ROOT)}")

    # Action heatmap
    actions = load_player_open_play_actions(wy_id, _EVENTS_DIR)
    p = build_player_action_heatmap(
        player=player,
        actions_df=actions,
        output_path=folder / "action_heatmap.png",
        style=style,
        show_footer=show_footer,
    )
    print(f"  action_heatmap       → {p.relative_to(PROJECT_ROOT)}")

    # Shot map
    shots = load_player_shots(wy_id, _EVENTS_DIR)
    p = build_player_shot_map(
        player=player,
        shots_df=shots,
        output_path=folder / "shot_map.png",
        style=style,
        show_footer=show_footer,
    )
    print(f"  shot_map             → {p.relative_to(PROJECT_ROOT)}")

    # Assist / key-pass map
    key_passes = load_player_key_passes(wy_id, _EVENTS_DIR)
    p = build_player_assist_map(
        player=player,
        key_passes_df=key_passes,
        output_path=folder / "assist_map.png",
        style=style,
        show_footer=show_footer,
    )
    print(f"  assist_map           → {p.relative_to(PROJECT_ROOT)}")

    # Dribble map
    dribbles = load_player_dribbles(wy_id, _EVENTS_DIR)
    p = build_player_dribble_map(
        player=player,
        dribbles_df=dribbles,
        output_path=folder / "dribble_map.png",
        style=style,
        show_footer=show_footer,
    )
    print(f"  dribble_map          → {p.relative_to(PROJECT_ROOT)}")

    # Pass start heatmap
    passes = load_player_passes(wy_id, _EVENTS_DIR)
    p = build_player_pass_heatmap(
        player=player,
        passes_df=passes,
        output_path=folder / "pass_start_heatmap.png",
        style=style,
        show_footer=show_footer,
    )
    print(f"  pass_start_heatmap   → {p.relative_to(PROJECT_ROOT)}")

    # Pass end heatmap
    p = build_player_pass_end_heatmap(
        player=player,
        passes_df=passes,
        output_path=folder / "pass_end_heatmap.png",
        style=style,
        show_footer=show_footer,
    )
    print(f"  pass_end_heatmap     → {p.relative_to(PROJECT_ROOT)}")


def main() -> int:
    settings = load_settings()
    benchmarks = _load_benchmarks()
    style = settings.plot_style
    output_dir = PROJECT_ROOT / "reports" / "player_analysis" / "plots"
    output_dir.mkdir(parents=True, exist_ok=True)

    # --- Player definitions --------------------------------------------------
    lyck         = make_player_radar_input(_load_player(1060409), _load_stats(1060409), team_name=TEAM_NAME)
    grauberg     = make_player_radar_input(_load_player(629185),  _load_stats(629185),  team_name=TEAM_NAME)
    kiwarkis     = make_player_radar_input(_load_player(1060411), _load_stats(1060411), team_name=TEAM_NAME)
    shamoun      = make_player_radar_input(_load_player(789558),  _load_stats(789558),  team_name=TEAM_NAME)

    # =========================================================================
    # STRIKERS: Linus Lyck & Kristoffer Grauberg Lepik
    # =========================================================================
    print("\n── Linus Lyck (ST) ──────────────────────────────────────────────")
    lyck_dir = output_dir / "lyck"
    lyck_dir.mkdir(parents=True, exist_ok=True)

    # Solo pizza
    p = build_player_pizza(
        players=[lyck],
        stat_keys=ST_STAT_KEYS,
        stat_labels=ST_STAT_LABELS,
        benchmarks=benchmarks,
        output_path=lyck_dir / "pizza.png",
        style=style,
        show_footer=False,
    )
    print(f"  pizza                → {p.relative_to(PROJECT_ROOT)}")

    _build_all_plots(lyck, lyck_dir, style)

    print("\n── Kristoffer Grauberg Lepik (ST) ───────────────────────────────")
    grauberg_dir = output_dir / "grauberg_lepik"
    grauberg_dir.mkdir(parents=True, exist_ok=True)

    p = build_player_pizza(
        players=[grauberg],
        stat_keys=ST_STAT_KEYS,
        stat_labels=ST_STAT_LABELS,
        benchmarks=benchmarks,
        output_path=grauberg_dir / "pizza.png",
        style=style,
        show_footer=False,
    )
    print(f"  pizza                → {p.relative_to(PROJECT_ROOT)}")

    _build_all_plots(grauberg, grauberg_dir, style)

    print("\n── Striker comparison radar: Lyck vs Grauberg Lepik ─────────────")
    p = build_player_radar(
        players=[lyck, grauberg],
        stat_keys=ST_STAT_KEYS,
        stat_labels=ST_STAT_LABELS,
        benchmarks=benchmarks,
        output_path=output_dir / "compare_lyck_grauberg.png",
        style=style,
        show_footer=False,
    )
    print(f"  radar_compare        → {p.relative_to(PROJECT_ROOT)}")

    # =========================================================================
    # WINGERS: Anmar Kiwarkis & Jacob Shamoun
    # =========================================================================
    print("\n── Anmar Kiwarkis (LW) ──────────────────────────────────────────")
    kiwarkis_dir = output_dir / "kiwarkis"
    kiwarkis_dir.mkdir(parents=True, exist_ok=True)

    p = build_player_pizza(
        players=[kiwarkis],
        stat_keys=W_STAT_KEYS,
        stat_labels=W_STAT_LABELS,
        benchmarks=benchmarks,
        output_path=kiwarkis_dir / "pizza.png",
        style=style,
        show_footer=False,
    )
    print(f"  pizza                → {p.relative_to(PROJECT_ROOT)}")

    _build_all_plots(kiwarkis, kiwarkis_dir, style)

    print("\n── Jacob Shamoun (RW) ───────────────────────────────────────────")
    shamoun_dir = output_dir / "shamoun"
    shamoun_dir.mkdir(parents=True, exist_ok=True)

    p = build_player_pizza(
        players=[shamoun],
        stat_keys=W_STAT_KEYS,
        stat_labels=W_STAT_LABELS,
        benchmarks=benchmarks,
        output_path=shamoun_dir / "pizza.png",
        style=style,
        show_footer=False,
    )
    print(f"  pizza                → {p.relative_to(PROJECT_ROOT)}")

    _build_all_plots(shamoun, shamoun_dir, style)

    print("\n── Winger comparison radar: Kiwarkis vs Shamoun ─────────────────")
    p = build_player_radar(
        players=[kiwarkis, shamoun],
        stat_keys=W_STAT_KEYS,
        stat_labels=W_STAT_LABELS,
        benchmarks=benchmarks,
        output_path=output_dir / "compare_kiwarkis_shamoun.png",
        style=style,
        show_footer=False,
    )
    print(f"  radar_compare        → {p.relative_to(PROJECT_ROOT)}")

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
