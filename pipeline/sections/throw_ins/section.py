"""Throw-ins dashboard section."""

from __future__ import annotations

import pandas as pd
from matplotlib.colors import LinearSegmentedColormap

from pipeline.sections._event_metrics import prepare_event_frame

from pipeline.contracts import SectionResult
from pipeline.publishing import build_ref, write_json
from pipeline.sections._labels import (
    derive_competition_label,
    derive_latest_match_label,
    derive_season_label,
)
from pipeline.sections._simple_plots import (
    STYLE,
    add_footer,
    add_header,
    figure_with_footer,
    pitch,
    save_figure,
)

SECTION_NAME = "throw_ins"
THROW_IN_TAG = "throw_in"


def _clock_value(row: pd.Series) -> float:
    return (
        float(row.get("period_order", 9) or 9) * 100000.0
        + float(row.get("minute", 0) or 0) * 60.0
        + float(row.get("second", 0) or 0)
    )


def _landing_xy(row: pd.Series) -> tuple[float | None, float | None]:
    """Return the first complete located endpoint without inventing (0, 0)."""
    for x_key, y_key in (
        ("pass_end_x", "pass_end_y"),
        ("carry_end_x", "carry_end_y"),
        ("start_x", "start_y"),
    ):
        x = row.get(x_key)
        y = row.get(y_key)
        if pd.notna(x) and pd.notna(y):
            return float(x), float(y)
    return None, None


def _third_from_x(value: float) -> str:
    if value >= 66.7:
        return "attacking_third"
    if value <= 33.3:
        return "defensive_third"
    return "middle_third"


def _score_sequence(frame: pd.DataFrame, row: pd.Series) -> tuple[bool, bool, float]:
    if frame.empty or pd.isna(row.get("possession_id")):
        return False, False, 0.0
    same = frame[
        frame["matchId"].eq(row["matchId"])
        & frame["possession_id"].eq(row["possession_id"])
        & frame["team_id"].eq(row["team_id"])
    ].copy()
    if same.empty:
        return False, False, 0.0
    current_clock = _clock_value(row)
    later = same[same.apply(_clock_value, axis=1).gt(current_clock)]
    later = later[later.apply(_clock_value, axis=1).sub(current_clock).le(10.0)]
    shots = later[later["event_type"].eq("shot")].copy()
    if shots.empty:
        return False, False, 0.0
    goal = bool(shots["secondary_tags"].apply(lambda tags: "goal" in tags).any())
    shot_xg = float(shots["shot_xg"].max()) if "shot_xg" in shots.columns else 0.0
    return True, goal, shot_xg


def _build_side(
    team_name: str, events_df: pd.DataFrame, matches_df: pd.DataFrame, season_id
) -> dict:
    full_frame = prepare_event_frame(events_df)
    frame = (
        full_frame[full_frame["event_type"].eq(THROW_IN_TAG)].copy()
        if not full_frame.empty
        else full_frame
    )

    records = []
    for _, row in frame.sort_values(
        by=["matchId", "period_order", "minute", "second", "event_id"], kind="mergesort"
    ).iterrows():
        start_x = row.get("start_x")
        start_y = row.get("start_y")
        landed_x, landed_y = _landing_xy(row)
        if any(pd.isna(value) for value in (start_x, start_y, landed_x, landed_y)):
            continue
        created_shot, goal, shot_xg = _score_sequence(full_frame, row)
        records.append(
            {
                "matchId": row.get("matchId"),
                "player_name": row.get("player_name"),
                "start_x": float(start_x),
                "start_y": float(start_y),
                "landing_x": float(landed_x),
                "landing_y": float(landed_y),
                "third": _third_from_x(float(start_x)),
                "created_shot": created_shot,
                "goal": goal,
                "shot_xg": shot_xg,
            }
        )

    actions_df = pd.DataFrame(records)
    if actions_df.empty:
        actions_df = pd.DataFrame(
            columns=[
                "matchId",
                "player_name",
                "start_x",
                "start_y",
                "landing_x",
                "landing_y",
                "third",
                "created_shot",
                "goal",
                "shot_xg",
            ]
        )
    attacking_df = actions_df[actions_df["third"].eq("attacking_third")].copy()
    defensive_df = actions_df[actions_df["third"].eq("defensive_third")].copy()

    total = int(len(actions_df))
    shots = int(actions_df["created_shot"].sum()) if total else 0
    goals = int(actions_df["goal"].sum()) if total else 0
    no_shot_within_10s_share = ((total - shots) / total * 100.0) if total else None
    attack_share = (len(attacking_df) / total * 100.0) if total else 0.0
    defend_share = (len(defensive_df) / total * 100.0) if total else 0.0
    xg_for = round(float(actions_df["shot_xg"].sum()) if total else 0.0, 3)

    summary = {
        "total": total,
        "created_shots": shots,
        "goals": goals,
        "xg": xg_for,
        "xg_for": xg_for,
        "no_shot_within_10s_pct": (
            round(no_shot_within_10s_share, 2) if no_shot_within_10s_share is not None else None
        ),
        "attacking_third_share_pct": round(attack_share, 2),
        "defensive_third_share_pct": round(defend_share, 2),
        "competition_label": derive_competition_label(matches_df),
        "season_label": derive_season_label(matches_df, season_id),
        "latest_match_label": derive_latest_match_label(matches_df),
    }
    metrics = [
        {"label": "Throw-ins", "value": total, "format": "count"},
        {"label": "Created shots", "value": shots, "format": "count"},
        {"label": "Goals", "value": goals, "format": "count"},
        {"label": "xG", "value": xg_for, "format": "0.000"},
        {
            "label": "No shot within 10s",
            "value": round(no_shot_within_10s_share, 1) if no_shot_within_10s_share is not None else None,
            "format": "percent",
        },
    ]
    storylines = [
        f"{team_name} took {attack_share:.0f}% of throw-ins from the attacking third and {defend_share:.0f}% from the defensive third.",
        f"Throw-in sequences produced {shots} shots and {goals} goals within 10 seconds in the selected completed-match scope.",
        (
            f"{no_shot_within_10s_share:.0f}% of located throw-ins did not lead to a same-possession shot within 10 seconds. "
            "This does not by itself prove possession was retained."
            if no_shot_within_10s_share is not None
            else "No located throw-ins were available for this scope."
        ),
    ]

    return {
        "summary": summary,
        "metrics": metrics,
        "storylines": storylines,
        "actions_df": actions_df,
        "attacking_df": attacking_df,
        "defensive_df": defensive_df,
    }


def _plot_map(
    output_path, data: pd.DataFrame, title: str, subtitle: str, note: str
) -> Path:
    pitch_obj = pitch()
    fig, ax, footer_ax = figure_with_footer(
        pitch_obj,
        figsize=(11, 7.4),
        pitch_rect=(0.05, 0.16, 0.86, 0.72),
        footer_rect=(0.05, 0.03, 0.90, 0.11),
    )
    add_header(fig, title, subtitle)
    if data.empty:
        ax.text(
            50,
            50,
            "No throw-in data available",
            color=STYLE["line"],
            fontsize=14,
            ha="center",
            va="center",
            fontweight="bold",
        )
    else:
        cmap = LinearSegmentedColormap.from_list(
            "throw_in_heat",
            [STYLE["bg"], STYLE["panel_alt"], STYLE["accent"], STYLE["highlight"]],
        )
        heat = pitch_obj.bin_statistic(
            data["landing_x"], data["landing_y"], statistic="count", bins=(12, 10)
        )
        heatmap = pitch_obj.heatmap(
            heat, ax=ax, cmap=cmap, edgecolors=STYLE["bg"], alpha=0.95
        )
        colorbar = fig.colorbar(heatmap, ax=ax, fraction=0.035, pad=0.03)
        colorbar.outline.set_edgecolor(STYLE["line"])
        colorbar.ax.yaxis.set_tick_params(color=STYLE["text"], labelcolor=STYLE["text"])
        colorbar.ax.set_ylabel("Landing count", color=STYLE["text"], fontsize=9.5)
        base = data[~data["created_shot"] & ~data["goal"]]
        shot = data[data["created_shot"]]
        goal = data[data["goal"]]
        if not base.empty:
            pitch_obj.scatter(
                base["landing_x"],
                base["landing_y"],
                s=36,
                color=STYLE["accent_2"],
                edgecolors=STYLE["line"],
                linewidth=0.5,
                alpha=0.74,
                ax=ax,
                zorder=4,
            )
        if not shot.empty:
            pitch_obj.scatter(
                shot["landing_x"],
                shot["landing_y"],
                s=75 + shot["shot_xg"].clip(lower=0.0) * 900,
                color=STYLE["accent"],
                edgecolors=STYLE["line"],
                linewidth=0.8,
                alpha=0.92,
                ax=ax,
                zorder=5,
            )
        if not goal.empty:
            pitch_obj.scatter(
                goal["landing_x"],
                goal["landing_y"],
                s=130 + goal["shot_xg"].clip(lower=0.0) * 1000,
                color=STYLE["danger"],
                marker="*",
                edgecolors=STYLE["line"],
                linewidth=1.1,
                alpha=0.96,
                ax=ax,
                zorder=6,
            )
    add_footer(
        footer_ax,
        [
            "What it shows: where throw-in plays end on the pitch and how often they quickly lead to a shot.",
            note,
        ],
        width=122,
    )
    return save_figure(fig, output_path)


def build_section(context) -> SectionResult:
    team_side = _build_side(
        context.team_name,
        context.team_analysis_events_df(),
        context.team_analysis_matches_df(),
        context.active_season_id,
    )
    opponent_side = _build_side(
        context.opponent_name,
        context.opponent_analysis_events_df(),
        context.opponent_analysis_matches_df(),
        context.opponent_season_id,
    )

    output_dir = context.settings.report_path(SECTION_NAME, "plots")
    output_dir.mkdir(parents=True, exist_ok=True)
    team_plot = _plot_map(
        output_dir / "team_attacking_third.png",
        team_side["attacking_df"],
        f"Throw-Ins From {context.team_name} In Attacking Third",
        f"{context.team_name} | {team_side['summary']['competition_label']} | {team_side['summary']['season_label']}",
        f"The highlighted zones show where {context.team_name} most often ends throw-ins.",
    )
    team_def = _plot_map(
        output_dir / "team_defensive_third.png",
        team_side["defensive_df"],
        f"Throw-Ins Against {context.team_name} In Defensive Third",
        f"{context.team_name} | {team_side['summary']['competition_label']} | {team_side['summary']['season_label']}",
        f"The highlighted zones show where throw-ins land near {context.team_name}'s defensive third.",
    )
    opp_plot = _plot_map(
        output_dir / "next_opponent_attacking_third.png",
        opponent_side["attacking_df"],
        f"Throw-Ins From {context.opponent_name} In Attacking Third",
        f"{context.opponent_name} | {opponent_side['summary']['competition_label']} | {opponent_side['summary']['season_label']}",
        f"The highlighted zones show where {context.opponent_name} most often ends throw-ins.",
    )
    opp_def = _plot_map(
        output_dir / "next_opponent_defensive_third.png",
        opponent_side["defensive_df"],
        f"Throw-Ins Against {context.opponent_name} In Defensive Third",
        f"{context.opponent_name} | {opponent_side['summary']['competition_label']} | {opponent_side['summary']['season_label']}",
        f"The highlighted zones show where throw-ins land near {context.opponent_name}'s defensive third.",
    )

    plot_refs = {}
    for name, path in {
        "team_attacking_third": team_plot,
        "team_defensive_third": team_def,
        "next_opponent_attacking_third": opp_plot,
        "next_opponent_defensive_third": opp_def,
    }.items():
        ref = build_ref(context.settings, path)
        if name.endswith("attacking_third"):
            ref.update(
                {
                    "title": name.replace("_", " "),
                    "description": "Shows where attacking throw-ins usually land and whether they lead to a shot.",
                    "reading_guide": [
                        "Darker areas mean the team lands there often.",
                        "Gold circles mean a shot happened soon after the throw-in.",
                        "Red stars mean the throw-in sequence ended in a goal.",
                    ],
                }
            )
        else:
            ref.update(
                {
                    "title": name.replace("_", " "),
                    "description": "Shows where defensive throw-ins land near the team’s own goal.",
                    "reading_guide": [
                        "The map shows how safely the team handles throw-ins near its own goal.",
                        "Gold circles mean the throw-in sequence quickly led to a shot.",
                    ],
                }
            )
        plot_refs[name] = ref

    output_path = write_json(
        context.settings.report_path(SECTION_NAME, "analysis.json"),
        {
            "generated_at": context.generated_at,
            "section": SECTION_NAME,
            "title": "Throw-ins",
            "description": "Simple throw-in view showing where the ball lands and how often the move becomes a shot or goal.",
            "status": "ready",
            "team": {
                "id": context.team_id,
                "name": context.team_name,
                "summary": team_side["summary"],
                "metrics": team_side["metrics"],
                "storylines": team_side["storylines"],
            },
            "next_opponent": {
                "id": context.opponent_id,
                "name": context.opponent_name,
                "summary": opponent_side["summary"],
                "metrics": opponent_side["metrics"],
                "storylines": opponent_side["storylines"],
            },
            "files": {"data": {}, "plots": plot_refs},
        },
    )
    return SectionResult(
        name=SECTION_NAME,
        files=[output_path, team_plot, team_def, opp_plot, opp_def],
        index_entry={"analysis": build_ref(context.settings, output_path)},
        metadata={
            "team_throw_ins": team_side["summary"]["total"],
            "opponent_throw_ins": opponent_side["summary"]["total"],
        },
    )
