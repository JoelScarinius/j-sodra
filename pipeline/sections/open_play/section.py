"""Open-play dashboard section."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from market.metrics import (
    build_pass_network,
    player_metric_table,
    progressive_carries,
    progressive_passes,
    select_player_radar,
    shot_events,
)
from market.plots import (
    plot_pass_network,
    plot_player_radar,
    plot_progressive_passes,
    plot_shot_map,
)

from pipeline.contracts import SectionResult
from pipeline.publishing import build_ref, write_json
from pipeline.sections._labels import (
    derive_competition_label,
    derive_latest_match_label,
    derive_season_label,
)

SECTION_NAME = "open_play"


@dataclass(frozen=True, slots=True)
class OpenPlaySubject:
    team_name: str
    competition_label: str
    season_label: str
    latest_match_label: str | None


def _latest_match_id(context, side: str) -> int | None:
    data = context.team_data if side == "team" else context.opponent_data
    for key in ("analysis_selected_match_ids", "selected_match_ids"):
        match_ids = data.get(key) or []
        if match_ids:
            return int(match_ids[0])
    return None



def _events_for_team(events_df: pd.DataFrame, team_id) -> pd.DataFrame:
    """Return events performed by the selected team/provider team id."""

    if events_df.empty or team_id is None or "team.id" not in events_df.columns:
        return pd.DataFrame()
    team_ids = pd.to_numeric(events_df["team.id"], errors="coerce")
    return events_df[team_ids.eq(float(team_id))].copy()


def _events_against_team(events_df: pd.DataFrame, team_id) -> pd.DataFrame:
    """Return opponent events in matches involving the selected team."""

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


def _build_side(
    context,
    team_name: str,
    team_id,
    events_df: pd.DataFrame,
    matches_df: pd.DataFrame,
    latest_match_id: int | None,
    season_id,
    dataset: dict,
) -> dict:
    team_events_df = _events_for_team(events_df, team_id)
    opponent_events_df = _events_against_team(events_df, team_id)

    progressive_df = progressive_passes(team_events_df)
    carries_df = progressive_carries(team_events_df)
    shots_df = shot_events(team_events_df)
    shots_against_df = shot_events(opponent_events_df)
    pass_network = build_pass_network(team_events_df, latest_match_id)
    player_table = player_metric_table(team_events_df)
    radar_payload = select_player_radar(player_table)

    if progressive_df.empty:
        progressive_df = pd.DataFrame(
            columns=[
                "player_name",
                "start_x",
                "start_y",
                "pass_end_x",
                "pass_end_y",
                "progression_gain",
            ]
        )
    if carries_df.empty:
        carries_df = pd.DataFrame(
            columns=[
                "player_name",
                "start_x",
                "start_y",
                "carry_end_x",
                "carry_end_y",
                "carry_gain",
            ]
        )
    if shots_df.empty:
        shots_df = _empty_shots_df()
    if shots_against_df.empty:
        shots_against_df = _empty_shots_df()

    xg_for = round(float(shots_df["shot_xg"].sum()) if not shots_df.empty else 0.0, 3)
    xg_against = round(float(shots_against_df["shot_xg"].sum()) if not shots_against_df.empty else 0.0, 3)
    goals_for = int(shots_df["goal"].sum()) if not shots_df.empty else 0
    goals_against = int(shots_against_df["goal"].sum()) if not shots_against_df.empty else 0

    summary = {
        "progressive_passes": int(len(progressive_df)),
        "progressive_carries": int(len(carries_df)),
        "shots": int(len(shots_df)),
        "shots_for": int(len(shots_df)),
        "shots_against": int(len(shots_against_df)),
        "goals": goals_for,
        "goals_for": goals_for,
        "goals_against": goals_against,
        "xg": xg_for,
        "xg_for": xg_for,
        "xg_against": xg_against,
        "xp": None,
        "box_shots": int(shots_df["inside_box"].sum()) if not shots_df.empty else 0,
        "on_target": int(shots_df["shot_on_target"].sum()) if not shots_df.empty else 0,
        "competition_label": derive_competition_label(matches_df),
        "season_label": derive_season_label(matches_df, season_id),
        "latest_match_label": derive_latest_match_label(matches_df),
    }

    storylines = [
        f"{team_name} produced {summary['progressive_passes']} progressive passes and {summary['progressive_carries']} progressive carries in the sampled window.",
        f"Open play generated {summary['shots_for']} shots, {summary['goals_for']} goals, and {summary['xg_for']:.2f} xG.",
        f"Opponents generated {summary['shots_against']} shots, {summary['goals_against']} goals, and {summary['xg_against']:.2f} xG against in the same sample.",
    ]
    strongest_link = (pass_network.get("meta", {}) or {}).get("strongest_link")
    if isinstance(strongest_link, dict):
        storylines.append(
            f"The clearest passing relationship is {strongest_link['player_a']} to {strongest_link['player_b']} with {strongest_link['pass_count']} completed passes."
        )
    if radar_payload and radar_payload.get("player"):
        storylines.append(
            f"The radar plot highlights {radar_payload['player']['player_name']} as the strongest all-round open-play profile in this sample."
        )
    storylines.append(
        "The published report includes the selected analysis match count and season scope so the frontend can keep the match slider in sync with the exposed data window."
    )

    metrics = [
        {
            "label": "Progressive passes",
            "value": summary["progressive_passes"],
            "format": "count",
        },
        {
            "label": "Progressive carries",
            "value": summary["progressive_carries"],
            "format": "count",
        },
        {"label": "Shots", "value": summary["shots"], "format": "count"},
        {"label": "Goals", "value": summary["goals_for"], "format": "count"},
        {"label": "xG", "value": summary["xg_for"], "format": "0.000"},
        {"label": "Shots against", "value": summary["shots_against"], "format": "count"},
        {"label": "xG against", "value": summary["xg_against"], "format": "0.000"},
    ]

    return {
        "summary": summary,
        "metrics": metrics,
        "storylines": storylines,
        "progressive_passes_df": progressive_df,
        "shots_df": shots_df,
        "shots_for_df": shots_df,
        "shots_against_df": shots_against_df,
        "pass_network": pass_network,
        "radar_payload": radar_payload,
        "analysis_scope": dataset.get("analysis_scope", {}),
        "analysis_match_count": len(dataset.get("analysis_selected_match_ids", [])),
    }


def _plot_subject(
    subject: OpenPlaySubject, payload: dict, output_dir, prefix: str
) -> dict[str, object]:
    plot_paths: dict[str, object] = {}
    plot_paths[f"{prefix}_progressive_passes"] = plot_progressive_passes(
        subject,
        payload["progressive_passes_df"],
        output_dir / f"{prefix}_progressive_passes.png",
    )
    plot_paths[f"{prefix}_shot_map"] = plot_shot_map(
        subject, payload["shots_df"], output_dir / f"{prefix}_shot_map.png"
    )
    plot_paths[f"{prefix}_pass_network"] = plot_pass_network(
        subject, payload["pass_network"], output_dir / f"{prefix}_pass_network.png"
    )
    if payload.get("radar_payload"):
        plot_paths[f"{prefix}_player_radar"] = plot_player_radar(
            subject, payload["radar_payload"], output_dir / f"{prefix}_player_radar.png"
        )
    return plot_paths


def _plot_refs(
    context, plot_paths: dict[str, object], team_name: str, opponent_name: str
) -> dict[str, dict]:
    refs = {}
    for name, path in plot_paths.items():
        if not path:
            continue
        subject_name = team_name if name.startswith("team_") else opponent_name
        ref = build_ref(context.settings, path)
        if name.endswith("progressive_passes"):
            ref.update(
                {
                    "title": f"{subject_name} progressive pass map",
                    "description": "Shows the team's forward passes that moved the ball a clear step closer to goal.",
                    "reading_guide": [
                        "Gold arrows show the biggest forward moves.",
                        "Green arrows show the other important forward passes.",
                    ],
                }
            )
        elif name.endswith("shot_map"):
            ref.update(
                {
                    "title": f"{subject_name} shot map",
                    "description": "Shows where the team took shots and how dangerous each shot was.",
                    "reading_guide": [
                        "Bigger circles mean better chances.",
                        "Gold circles are goals, green circles are shots on target, and muted circles are missed or blocked shots.",
                    ],
                }
            )
        elif name.endswith("pass_network"):
            ref.update(
                {
                    "title": f"{subject_name} pass network",
                    "description": "Shows which players passed to each other most often in the latest match.",
                    "reading_guide": [
                        "Larger dots mean more touches.",
                        "Thicker lines mean more passes between two players.",
                    ],
                }
            )
        elif name.endswith("player_radar"):
            ref.update(
                {
                    "title": f"{subject_name} player radar",
                    "description": "Shows one player's all-round profile compared with similar teammates.",
                    "reading_guide": [
                        "Each spoke is one simple stat.",
                        "A bigger filled shape means a stronger profile on that stat.",
                    ],
                }
            )
        refs[name] = ref
    return refs


def build_section(context) -> SectionResult:
    team_matches_df = context.team_analysis_matches_df()
    opponent_matches_df = context.opponent_analysis_matches_df()

    team_side = _build_side(
        context,
        context.team_name,
        context.team_id,
        context.team_analysis_events_df(),
        team_matches_df,
        _latest_match_id(context, "team"),
        context.active_season_id,
        context.team_data,
    )
    opponent_side = _build_side(
        context,
        context.opponent_name,
        context.opponent_id,
        context.opponent_analysis_events_df(),
        opponent_matches_df,
        _latest_match_id(context, "opponent"),
        context.opponent_season_id,
        context.opponent_data,
    )

    team_subject = OpenPlaySubject(
        context.team_name,
        team_side["summary"]["competition_label"],
        team_side["summary"]["season_label"],
        team_side["summary"]["latest_match_label"],
    )
    opponent_subject = OpenPlaySubject(
        context.opponent_name,
        opponent_side["summary"]["competition_label"],
        opponent_side["summary"]["season_label"],
        opponent_side["summary"]["latest_match_label"],
    )

    output_dir = context.settings.report_path(SECTION_NAME, "plots")
    output_dir.mkdir(parents=True, exist_ok=True)
    plot_paths = {}
    plot_paths.update(_plot_subject(team_subject, team_side, output_dir, "team"))
    plot_paths.update(
        _plot_subject(opponent_subject, opponent_side, output_dir, "next_opponent")
    )

    output_path = write_json(
        context.settings.report_path(SECTION_NAME, "analysis.json"),
        {
            "generated_at": context.generated_at,
            "section": SECTION_NAME,
            "title": "Open Play",
            "description": "Simple view of forward passing, shots, pass connections, and top player profiles for both teams.",
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
                "data": {},
                "plots": _plot_refs(
                    context, plot_paths, context.team_name, context.opponent_name
                ),
            },
        },
    )

    return SectionResult(
        name=SECTION_NAME,
        files=[output_path, *[path for path in plot_paths.values() if path]],
        index_entry={"analysis": build_ref(context.settings, output_path)},
        metadata={
            "team_shots": team_side["summary"]["shots"],
            "opponent_shots": opponent_side["summary"]["shots"],
        },
    )
