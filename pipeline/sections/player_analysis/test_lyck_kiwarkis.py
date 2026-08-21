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
    build_player_report,
    build_player_shot_map,
    build_scatter_plot,
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

    # =========================================================================
    # PLAYER REPORT: Linus Lyck
    # =========================================================================
    print("\n── Linus Lyck — full player report ─────────────────────────────")

    # Build striker scatter data for league context
    import json as _json
    _cache = PROJECT_ROOT / "cache" / "players"
    _events = PROJECT_ROOT / "cache" / "events"

    player_team_id: dict[int, int] = {}
    team_names: dict[int, str] = {}
    for ef in _events.glob("match_*.json"):
        for evt in _json.loads(ef.read_text()).get("events", []):
            pid  = (evt.get("player") or {}).get("id")
            team = evt.get("team") or {}
            tid, tname = team.get("id"), team.get("name")
            if pid and tid:
                player_team_id[pid] = tid
            if tid and tname:
                team_names[tid] = tname

    players_file = json.loads(
        (_cache / f"competition_{COMPETITION_ID}_players.json").read_text()
    )["players"]
    players_by_id = {p["wyId"]: p for p in players_file}

    from pipeline.sections.player_analysis.metrics import bucket_player_position

    scatter_strikers = []
    for wy_id, pinfo in players_by_id.items():
        if wy_id not in player_team_id:
            continue
        sp = _cache / f"player_{wy_id}_advancedstats_comp{COMPETITION_ID}.json"
        if not sp.exists():
            continue
        s = _json.loads(sp.read_text())["stats"]
        positions = s.get("positions") or []
        if not positions:
            continue
        primary = max(positions, key=lambda p: p.get("percent", 0))
        code = ((primary.get("position") or {}).get("code") or "").lower()
        if bucket_player_position(code) != "striker":
            continue
        avg = s.get("average") or {}
        touch = avg.get("touchInBox")
        goals = avg.get("goals")
        if touch is None or goals is None:
            continue
        tid = player_team_id[wy_id]
        scatter_strikers.append({
            "name":  pinfo.get("shortName") or pinfo.get("lastName") or str(wy_id),
            "team":  team_names.get(tid, f"Team {tid}"),
            "x":     float(touch),
            "y":     float(goals),
        })

    from pipeline.sofascore import fetch_player as _fetch_ss
    lyck_profile = _load_player(1060409)
    print("  Fetching SofaScore data for Linus Lyck…")
    lyck_ss = _fetch_ss(wyscout_id=1060409, name="Linus Lyck")
    print(f"  SofaScore: shirt={lyck_ss.get('shirt_number')}, "
          f"height={lyck_ss.get('height')}, foot={lyck_ss.get('foot')}, "
          f"photo={'✓' if lyck_ss.get('photo_b64') else '✗'}")

    report_path = build_player_report(
        player=lyck,
        player_profile=lyck_profile,
        stat_keys=ST_STAT_KEYS,
        stat_labels=ST_STAT_LABELS,
        benchmarks=benchmarks,
        events_dir=_events,
        output_path=output_dir / "lyck" / "report.html",
        style=settings.plot_style,
        scatter_players=scatter_strikers,
        scatter_x_label="Touches in box / 90",
        scatter_y_label="Goals / 90",
        scatter_title="Box Threat — Strikers",
        scatter_subtitle="Ettan · Touches in box vs Goals per 90",
        highlight_team=TEAM_NAME,
        sofascore_profile=lyck_ss,
    )
    print(f"  report               → {report_path.relative_to(PROJECT_ROOT)}")

    # =========================================================================
    # PLAYER REPORT: Anmar Kiwarkis
    # =========================================================================
    print("\n── Anmar Kiwarkis — full player report ──────────────────────────")

    # Build winger scatter data for league context
    scatter_wingers = []
    for wy_id, pinfo in players_by_id.items():
        if wy_id not in player_team_id:
            continue
        sp = _cache / f"player_{wy_id}_advancedstats_comp{COMPETITION_ID}.json"
        if not sp.exists():
            continue
        s = _json.loads(sp.read_text())["stats"]
        positions = s.get("positions") or []
        if not positions:
            continue
        primary = max(positions, key=lambda p: p.get("percent", 0))
        code = ((primary.get("position") or {}).get("code") or "").lower()
        if bucket_player_position(code) != "winger":
            continue
        avg = s.get("average") or {}
        dribbles = avg.get("successfulDribbles")
        xg_shot  = avg.get("xgShot") or 0.0
        xg_assist = avg.get("xgAssist") or 0.0
        if dribbles is None:
            continue
        tid = player_team_id[wy_id]
        scatter_wingers.append({
            "name":  pinfo.get("shortName") or pinfo.get("lastName") or str(wy_id),
            "team":  team_names.get(tid, f"Team {tid}"),
            "x":     float(dribbles),
            "y":     float(xg_shot) + float(xg_assist),
        })

    kiwarkis_profile = _load_player(1060411)
    print("  Fetching SofaScore data for Anmar Kiwarkis…")
    kiwarkis_ss = _fetch_ss(wyscout_id=1060411, name="Anmar Kiwarkis")
    print(f"  SofaScore: shirt={kiwarkis_ss.get('shirt_number')}, "
          f"height={kiwarkis_ss.get('height')}, foot={kiwarkis_ss.get('foot')}, "
          f"photo={'✓' if kiwarkis_ss.get('photo_b64') else '✗'}")

    report_path = build_player_report(
        player=kiwarkis,
        player_profile=kiwarkis_profile,
        stat_keys=W_STAT_KEYS,
        stat_labels=W_STAT_LABELS,
        benchmarks=benchmarks,
        events_dir=_events,
        output_path=output_dir / "kiwarkis" / "report.html",
        style=settings.plot_style,
        scatter_players=scatter_wingers,
        scatter_x_label="Successful dribbles / 90",
        scatter_y_label="xG + xA / 90",
        scatter_title="Carry & Chance Creation — Wingers",
        scatter_subtitle="Ettan · Dribbles vs xG+xA per 90",
        highlight_team=TEAM_NAME,
        sofascore_profile=kiwarkis_ss,
    )
    print(f"  report               → {report_path.relative_to(PROJECT_ROOT)}")

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
