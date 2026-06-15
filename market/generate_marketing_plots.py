from __future__ import annotations

import argparse
import json
from pathlib import Path

from market.data import load_marketing_dataset
from market.metrics import (
    build_pass_network,
    defensive_actions,
    dropped_ball_turnovers,
    player_metric_table,
    progressive_passes,
    select_player_radar,
    shot_events,
)
from market.plots import (
    plot_defensive_actions,
    plot_dropped_balls,
    plot_pass_network,
    plot_player_radar,
    plot_progressive_passes,
    plot_shot_map,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate standalone marketing visuals from the J-Sodra Wyscout feed."
    )
    parser.add_argument(
        "--team-id", type=int, default=None, help="Explicit Wyscout team id."
    )
    parser.add_argument("--team-name", default=None, help="Explicit team name lookup.")
    parser.add_argument(
        "--season-id", type=int, default=None, help="Explicit season id."
    )
    parser.add_argument(
        "--player",
        default=None,
        help="Optional player name for the radar chart. Defaults to the standout player.",
    )
    parser.add_argument(
        "--max-matches",
        type=int,
        default=None,
        help="Optional cap on played matches used for the season views.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory for the generated market assets. Defaults to market/output.",
    )
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Bypass local cache and force calls through the Supabase edge function.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    dataset = load_marketing_dataset(
        team_id=args.team_id,
        team_name=args.team_name,
        season_id=args.season_id,
        max_matches=args.max_matches,
        output_dir=args.output_dir,
        force_refresh=args.force_refresh,
    )

    progressive_df = progressive_passes(dataset.team_events_df)
    defensive_df = defensive_actions(dataset.team_events_df)
    dropped_df = dropped_ball_turnovers(dataset.events_df, dataset.team_id)
    shots_df = shot_events(dataset.team_events_df)
    pass_network = build_pass_network(dataset.team_events_df, dataset.latest_match_id)
    player_table = player_metric_table(dataset.team_events_df)
    radar_payload = select_player_radar(player_table, args.player)

    if progressive_df.empty:
        raise RuntimeError(
            "No progressive passes were available for the requested slice."
        )
    if defensive_df.empty:
        raise RuntimeError(
            "No defensive actions were available for the requested slice."
        )
    if dropped_df.empty:
        raise RuntimeError(
            "No dropped-ball turnovers were available for the requested slice."
        )
    if shots_df.empty:
        raise RuntimeError("No shots were available for the requested slice.")
    if radar_payload is None:
        raise RuntimeError(
            "No player radar candidate could be built from the requested slice."
        )

    output_dir = Path(dataset.output_dir)
    files = {
        "progressive_passes": plot_progressive_passes(
            dataset,
            progressive_df,
            output_dir / "progressive_pass_pulse.png",
        ),
        "defensive_actions": plot_defensive_actions(
            dataset,
            defensive_df,
            output_dir / "defensive_footprint.png",
        ),
        "dropped_balls": plot_dropped_balls(
            dataset,
            dropped_df,
            output_dir / "dropped_possessions.png",
        ),
        "pass_network": plot_pass_network(
            dataset,
            pass_network,
            output_dir / "latest_match_pass_network.png",
        ),
        "shot_map": plot_shot_map(
            dataset,
            shots_df,
            output_dir / "season_shot_map.png",
        ),
        "player_radar": plot_player_radar(
            dataset,
            radar_payload,
            output_dir / "standout_player_radar.png",
        ),
    }

    manifest = {
        "team": dataset.team_name,
        "team_id": dataset.team_id,
        "competition": dataset.competition_label,
        "season": dataset.season_label,
        "season_id": dataset.season_id,
        "season_year": dataset.season_year,
        "matches_used": int(len(dataset.played_matches_df)),
        "latest_match": dataset.latest_match_label,
        "radar_player": radar_payload["player"]["player_name"],
        "files": {
            key: str(path.relative_to(output_dir.parent.parent))
            for key, path in files.items()
        },
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
