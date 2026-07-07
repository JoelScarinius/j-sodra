"""Defensive dashboard section."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from market.metrics import (
    defensive_actions,
    dropped_ball_turnovers,
    player_metric_table,
    select_player_radar,
    shot_events,
)
from market.plots import plot_defensive_actions, plot_dropped_balls, plot_shot_map
from pipeline.contracts import SectionResult
from pipeline.publishing import build_ref, write_json
from pipeline.sections._labels import (
    derive_competition_label,
    derive_latest_match_label,
    derive_season_label,
)

SECTION_NAME = "defensive"


@dataclass(frozen=True, slots=True)
class Subject:
    team_name: str
    competition_label: str
    season_label: str
    latest_match_label: str | None


def _subject(team_name: str, matches_df: pd.DataFrame, season_id) -> Subject:
    return Subject(
        team_name,
        derive_competition_label(matches_df),
        derive_season_label(matches_df, season_id),
        derive_latest_match_label(matches_df),
    )


def _events_for_team(events_df: pd.DataFrame, team_id: int | None) -> pd.DataFrame:
    """Return only events performed by the selected team/provider team id."""

    if events_df.empty or team_id is None or "team.id" not in events_df.columns:
        return pd.DataFrame()
    team_ids = pd.to_numeric(events_df["team.id"], errors="coerce")
    return events_df[team_ids.eq(float(team_id))].copy()


def _events_against_team(events_df: pd.DataFrame, team_id: int | None) -> pd.DataFrame:
    """Return opponent events in matches involving the selected team.

    Prefer Wyscout's opponentTeam.id field when available. Fall back to all rows
    not performed by the selected team, which is safe for team-specific match
    event datasets collected by this pipeline.
    """

    if events_df.empty or team_id is None:
        return pd.DataFrame()

    if "opponentTeam.id" in events_df.columns:
        opponent_ids = pd.to_numeric(events_df["opponentTeam.id"], errors="coerce")
        mask = opponent_ids.eq(float(team_id))
        if mask.any():
            return events_df[mask].copy()

    if "team.id" in events_df.columns:
        team_ids = pd.to_numeric(events_df["team.id"], errors="coerce")
        return events_df[team_ids.ne(float(team_id))].copy()

    return pd.DataFrame()


def _empty_defensive_df() -> pd.DataFrame:
    return pd.DataFrame(
        columns=["player_name", "start_x", "start_y", "action_family", "high_regain"]
    )


def _empty_shots_df() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "player_name",
            "start_x",
            "start_y",
            "shot_xg",
            "goal",
            "shot_on_target",
            "inside_box",
            "distance",
        ]
    )


def _empty_dropped_df() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "player_name",
            "drop_x",
            "drop_y",
            "pickup_x",
            "pickup_y",
            "pickup_delay",
            "possession_duration",
            "possession_events",
            "opponent_event_type",
            "pickup_in_attacking_half",
            "travel_distance",
        ]
    )


def _build_side(
    *,
    team_name: str,
    team_id: int | None,
    events_df: pd.DataFrame,
    dataset: dict,
) -> dict:
    team_events_df = _events_for_team(events_df, team_id)
    opponent_events_df = _events_against_team(events_df, team_id)

    defensive_df = defensive_actions(team_events_df)
    shots_for_df = shot_events(team_events_df)
    shots_against_df = shot_events(opponent_events_df)
    dropped_df = (
        dropped_ball_turnovers(events_df, team_id=team_id)
        if team_id is not None
        else pd.DataFrame()
    )
    player_table = player_metric_table(team_events_df)
    radar_payload = select_player_radar(player_table)

    if defensive_df.empty:
        defensive_df = _empty_defensive_df()
    if shots_for_df.empty:
        shots_for_df = _empty_shots_df()
    if shots_against_df.empty:
        shots_against_df = _empty_shots_df()
    if dropped_df.empty:
        dropped_df = _empty_dropped_df()

    total = int(len(defensive_df))
    action_mix = (
        defensive_df.groupby("action_family")
        .size()
        .sort_values(ascending=False)
        .to_dict()
        if not defensive_df.empty
        else {}
    )
    high_regain_share = (
        float(defensive_df["high_regain"].mean() * 100.0) if total else 0.0
    )
    own_third_share = (
        float(defensive_df["start_x"].le(33.3).mean() * 100.0) if total else 0.0
    )
    average_height = float(defensive_df["start_x"].mean()) if total else 0.0

    shots_against_count = int(len(shots_against_df))
    shots_for_count = int(len(shots_for_df))
    xg_for = round(
        float(shots_for_df["shot_xg"].sum()) if not shots_for_df.empty else 0.0, 3
    )
    xg_against = round(
        float(shots_against_df["shot_xg"].sum()) if not shots_against_df.empty else 0.0,
        3,
    )
    goals_for = int(shots_for_df["goal"].sum()) if not shots_for_df.empty else 0
    goals_against = (
        int(shots_against_df["goal"].sum()) if not shots_against_df.empty else 0
    )

    dropped_count = int(len(dropped_df))
    dangerous_drops = (
        dropped_df.sort_values(
            by=["pickup_in_attacking_half", "travel_distance", "pickup_delay"],
            ascending=[False, False, True],
        ).head(8)
        if not dropped_df.empty
        else dropped_df
    )

    drop_summary = {
        "total": dropped_count,
        "attacking_half": (
            int(dropped_df["pickup_in_attacking_half"].sum())
            if not dropped_df.empty
            else 0
        ),
        "average_pickup_delay": round(
            float(dropped_df["pickup_delay"].mean()) if not dropped_df.empty else 0.0, 2
        ),
        "most_dangerous_drops": [
            {
                "player_name": row.player_name,
                "pickup_x": float(row.pickup_x),
                "pickup_y": float(row.pickup_y),
                "pickup_delay": float(row.pickup_delay),
                "travel_distance": float(row.travel_distance),
                "pickup_in_attacking_half": bool(row.pickup_in_attacking_half),
            }
            for row in dangerous_drops.itertuples(index=False)
        ],
    }

    radar_summary = None
    if radar_payload and radar_payload.get("player"):
        selected_player = radar_payload["player"].get("player_name") or "Unknown"
        radar_summary = {
            "selected_player": selected_player,
            "selection_rule": "Highest selection_score among players with enough appearances, unless a specific player name is requested.",
            "comparison_size": radar_payload.get("comparison_size", 0),
            "minimum_appearances": radar_payload.get("minimum_appearances", 0),
            "raw_values": {
                metric["label"]: metric["raw_value"]
                for metric in radar_payload.get("metrics", [])
            },
        }

    storylines = [
        f"{team_name} records {total} defensive actions in the sampled window.",
        f"The average defensive action starts at pitch height {average_height:.1f}, with {high_regain_share:.0f}% of actions occurring high up the pitch.",
    ]
    if action_mix:
        leader = next(iter(action_mix.items()))
        storylines.append(
            f"Most defensive volume comes from {leader[0].lower()} actions ({leader[1]} events)."
        )
    storylines.append(
        f"Opponents produced {shots_against_count} shots worth {xg_against:.2f} xG against {team_name} in this sample."
    )
    if shots_for_count:
        storylines.append(
            f"For context, {team_name} produced {shots_for_count} own shots worth {xg_for:.2f} xG in the same match sample."
        )
    if goals_against:
        storylines.append(
            f"The shot-against sample includes {goals_against} goals conceded."
        )

    if radar_summary:
        storylines.append(
            f"The radar player is chosen as {radar_summary['selected_player']} because that player has the highest selection score among teammates with at least {radar_summary['minimum_appearances']} appearances in the comparison set of {radar_summary['comparison_size']} players. It changes automatically when another player's season performance overtakes that score or when a specific player is requested."
        )
    if dropped_count:
        storylines.append(
            f"Dropped possessions are published separately so the most dangerous losses can be read directly: {drop_summary['attacking_half']} end in the attacking half and the most exposed losses are listed by pickup location and travel distance."
        )

    summary = {
        "total": total,
        "high_regain_share_pct": round(high_regain_share, 2),
        "own_third_share_pct": round(own_third_share, 2),
        "average_height": round(average_height, 2),
        "shot_count": shots_against_count,
        "shots_for": shots_for_count,
        "shots_against": shots_against_count,
        "xg": xg_for,
        "xg_for": xg_for,
        "xg_against": xg_against,
        "goals": goals_against,
        "goals_for": goals_for,
        "goals_against": goals_against,
        "action_mix": action_mix,
        "dropped_possessions": drop_summary,
        "radar": radar_summary,
    }

    metrics = [
        {"label": "Defensive actions", "value": total, "format": "count"},
        {
            "label": "High regains",
            "value": round(high_regain_share, 1),
            "format": "percent",
        },
        {
            "label": "Own-third share",
            "value": round(own_third_share, 1),
            "format": "percent",
        },
        {
            "label": "Average height",
            "value": round(average_height, 1),
            "format": "number",
        },
        {"label": "Shots against", "value": shots_against_count, "format": "count"},
        {"label": "xG for", "value": xg_for, "format": "0.000"},
        {"label": "xG against", "value": xg_against, "format": "0.000"},
        {"label": "Goals against", "value": goals_against, "format": "count"},
        {"label": "Dropped possessions", "value": dropped_count, "format": "count"},
    ]

    return {
        "summary": summary,
        "metrics": metrics,
        "storylines": storylines,
        "defensive_df": defensive_df,
        "shots_df": shots_against_df,
        "shots_for_df": shots_for_df,
        "shots_against_df": shots_against_df,
        "dropped_df": dropped_df,
        "player_table": player_table,
        "radar_payload": radar_payload,
        "analysis_scope": dataset.get("analysis_scope", {}),
        "analysis_match_count": len(dataset.get("analysis_selected_match_ids", [])),
    }


def _dropped_rows_for_side(source_name: str, side: dict) -> list[dict]:
    rows = []
    for row in side["dropped_df"].itertuples(index=False):
        rows.append(
            {
                "team_name": source_name,
                "player_name": row.player_name,
                "pickup_x": float(row.pickup_x),
                "pickup_y": float(row.pickup_y),
                "pickup_delay": float(row.pickup_delay),
                "travel_distance": float(row.travel_distance),
                "pickup_in_attacking_half": bool(row.pickup_in_attacking_half),
            }
        )
    return rows


def build_section(context) -> SectionResult:
    team_side = _build_side(
        team_name=context.team_name,
        team_id=context.team_id,
        events_df=context.team_analysis_events_df(),
        dataset=context.team_data,
    )
    opponent_side = _build_side(
        team_name=context.opponent_name,
        team_id=context.opponent_id,
        events_df=context.opponent_analysis_events_df(),
        dataset=context.opponent_data,
    )

    team_subject = _subject(
        context.team_name, context.team_analysis_matches_df(), context.active_season_id
    )
    opponent_subject = _subject(
        context.opponent_name,
        context.opponent_analysis_matches_df(),
        context.opponent_season_id,
    )

    output_dir = context.settings.report_path(SECTION_NAME, "plots")
    output_dir.mkdir(parents=True, exist_ok=True)

    team_def = plot_defensive_actions(
        team_subject,
        team_side["defensive_df"],
        output_dir / "team_defensive_actions.png",
    )
    team_shot = plot_shot_map(
        team_subject, team_side["shots_against_df"], output_dir / "team_shot_map.png"
    )
    team_dropped = plot_dropped_balls(
        team_subject,
        team_side["dropped_df"],
        output_dir / "team_dropped_possessions.png",
    )

    opp_def = plot_defensive_actions(
        opponent_subject,
        opponent_side["defensive_df"],
        output_dir / "next_opponent_defensive_actions.png",
    )
    opp_shot = plot_shot_map(
        opponent_subject,
        opponent_side["shots_against_df"],
        output_dir / "next_opponent_shot_map.png",
    )
    opp_dropped = plot_dropped_balls(
        opponent_subject,
        opponent_side["dropped_df"],
        output_dir / "next_opponent_dropped_possessions.png",
    )

    dropped_rows = []
    dropped_rows.extend(_dropped_rows_for_side(context.team_name, team_side))
    dropped_rows.extend(_dropped_rows_for_side(context.opponent_name, opponent_side))

    dropped_path = (
        context.settings.report_path(SECTION_NAME, "data") / "dropped_possessions.csv"
    )
    dropped_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(dropped_rows).to_csv(dropped_path, index=False)

    dropped_rank_rows = pd.DataFrame(dropped_rows)
    if not dropped_rank_rows.empty:
        dropped_rank_rows = dropped_rank_rows.sort_values(
            by=["pickup_in_attacking_half", "travel_distance", "pickup_delay"],
            ascending=[False, False, True],
        )
    dropped_summary_path = (
        context.settings.report_path(SECTION_NAME, "data")
        / "dropped_possessions_rankings.csv"
    )
    dropped_rank_rows.to_csv(dropped_summary_path, index=False)

    plot_refs = {}
    for name, path in {
        "team_defensive_actions": team_def,
        "team_shot_map": team_shot,
        "team_dropped_possessions": team_dropped,
        "next_opponent_defensive_actions": opp_def,
        "next_opponent_shot_map": opp_shot,
        "next_opponent_dropped_possessions": opp_dropped,
    }.items():
        ref = build_ref(context.settings, path)
        if name.endswith("defensive_actions"):
            ref.update(
                {
                    "title": name.replace("_", " "),
                    "description": "Shows where the team won the ball, cleared danger, or made tackles.",
                    "reading_guide": [
                        "Each mark is a defensive action by the selected team.",
                        "Higher marks mean actions closer to the opponent goal.",
                    ],
                }
            )
        elif name.endswith("dropped_possessions"):
            ref.update(
                {
                    "title": name.replace("_", " "),
                    "description": "Shows where the team lost the ball and where the opponent picked it up.",
                    "reading_guide": [
                        "Bigger circles mean more dangerous turnovers.",
                        "Gold circles are the worst losses and red stars show the most dangerous recovery spots.",
                    ],
                }
            )
        else:
            ref.update(
                {
                    "title": name.replace("_", " "),
                    "description": "Shows shots allowed by this team and how dangerous those shots were.",
                    "reading_guide": [
                        "Bigger circles mean higher xG shots.",
                        "Gold circles are goals and green circles are shots on target.",
                    ],
                }
            )
        plot_refs[name] = ref

    output_path = write_json(
        context.settings.report_path(SECTION_NAME, "analysis.json"),
        {
            "generated_at": context.generated_at,
            "section": SECTION_NAME,
            "title": "Defensive",
            "description": "Simple defensive view showing ball wins, dangerous turnovers, and shot danger for both teams.",
            "status": "ready",
            "team": {
                "id": context.team_id,
                "name": context.team_name,
                "summary": team_side["summary"],
                "metrics": team_side["metrics"],
                "storylines": team_side["storylines"],
                "analysis_scope": team_side["analysis_scope"],
                "analysis_match_count": team_side["analysis_match_count"],
            },
            "next_opponent": {
                "id": context.opponent_id,
                "name": context.opponent_name,
                "summary": opponent_side["summary"],
                "metrics": opponent_side["metrics"],
                "storylines": opponent_side["storylines"],
                "analysis_scope": opponent_side["analysis_scope"],
                "analysis_match_count": opponent_side["analysis_match_count"],
            },
            "files": {
                "data": {
                    "dropped_possessions": build_ref(context.settings, dropped_path),
                    "dropped_possessions_rankings": build_ref(
                        context.settings, dropped_summary_path
                    ),
                },
                "plots": plot_refs,
            },
        },
    )

    return SectionResult(
        name=SECTION_NAME,
        files=[
            output_path,
            dropped_path,
            dropped_summary_path,
            team_def,
            team_shot,
            team_dropped,
            opp_def,
            opp_shot,
            opp_dropped,
        ],
        index_entry={"analysis": build_ref(context.settings, output_path)},
        metadata={
            "team_defensive_actions": team_side["summary"]["total"],
            "opponent_defensive_actions": opponent_side["summary"]["total"],
        },
    )
