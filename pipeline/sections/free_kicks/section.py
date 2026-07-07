"""Free-kicks dashboard section."""

from __future__ import annotations

import pandas as pd
from matplotlib.colors import LinearSegmentedColormap

from market.metrics import prepare_event_frame

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

SECTION_NAME = "free_kicks"
FREE_KICK_TAG = "free_kick"


def _clock_value(row: pd.Series) -> float:
    return (
        float(row.get("period_order", 9) or 9) * 100000.0
        + float(row.get("minute", 0) or 0) * 60.0
        + float(row.get("second", 0) or 0)
    )


def _landing_xy(row: pd.Series) -> tuple[float, float]:
    for x_key, y_key in (
        ("pass_end_x", "pass_end_y"),
        ("carry_end_x", "carry_end_y"),
        ("start_x", "start_y"),
    ):
        x = float(row.get(x_key, 0.0) or 0.0)
        y = float(row.get(y_key, 0.0) or 0.0)
        if x or y:
            return x, y
    return 0.0, 0.0


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
        full_frame[full_frame["event_type"].eq(FREE_KICK_TAG)].copy()
        if not full_frame.empty
        else full_frame
    )

    records = []
    for _, row in frame.sort_values(
        by=["matchId", "period_order", "minute", "second", "event_id"], kind="mergesort"
    ).iterrows():
        landed_x, landed_y = _landing_xy(row)
        created_shot, goal, shot_xg = _score_sequence(full_frame, row)
        records.append(
            {
                "matchId": row.get("matchId"),
                "player_name": row.get("player_name"),
                "start_x": float(row.get("start_x", 0.0) or 0.0),
                "start_y": float(row.get("start_y", 0.0) or 0.0),
                "landing_x": landed_x,
                "landing_y": landed_y,
                "third": _third_from_x(float(row.get("start_x", 0.0) or 0.0)),
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
    retain_share = ((total - shots) / total * 100.0) if total else 0.0
    attack_share = (len(attacking_df) / total * 100.0) if total else 0.0
    defend_share = (len(defensive_df) / total * 100.0) if total else 0.0
    xg_for = round(float(actions_df["shot_xg"].sum()) if total else 0.0, 3)

    summary = {
        "total": total,
        "created_shots": shots,
        "goals": goals,
        "xg": xg_for,
        "xg_for": xg_for,
        "retention_pct": round(retain_share, 2),
        "attacking_third_share_pct": round(attack_share, 2),
        "defensive_third_share_pct": round(defend_share, 2),
        "competition_label": derive_competition_label(matches_df),
        "season_label": derive_season_label(matches_df, season_id),
        "latest_match_label": derive_latest_match_label(matches_df),
    }
    metrics = [
        {"label": "Free kicks", "value": total, "format": "count"},
        {"label": "Created shots", "value": shots, "format": "count"},
        {"label": "Goals", "value": goals, "format": "count"},
        {"label": "xG", "value": xg_for, "format": "0.000"},
        {"label": "Retention", "value": round(retain_share, 1), "format": "percent"},
    ]
    storylines = [
        f"{team_name} took {attack_share:.0f}% of free kicks from the attacking third and {defend_share:.0f}% from the defensive third.",
        f"Free kicks generated {shots} shots and {goals} goals in the sampled window.",
    ]
    if total:
        storylines.append(
            f"Free-kick sequences created {xg_for:.2f} total xG, or {actions_df['shot_xg'].mean():.2f} xG per free kick in the sample."
        )

    return {
        "summary": summary,
        "metrics": metrics,
        "storylines": storylines,
        "actions_df": actions_df,
        "attacking_df": attacking_df,
        "defensive_df": defensive_df,
    }


def _plot_map(
    output_path, data: pd.DataFrame, title: str, subtitle: str, note: str, mode: str
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
            "No free-kick data available",
            color=STYLE["line"],
            fontsize=14,
            ha="center",
            va="center",
            fontweight="bold",
        )
    else:
        base = data[~data["created_shot"] & ~data["goal"]]
        shot = data[data["created_shot"]]
        goal = data[data["goal"]]
        if mode == "landing":
            cmap = LinearSegmentedColormap.from_list(
                "free_kick_heat",
                [
                    STYLE["bg"],
                    STYLE["panel_alt"],
                    STYLE["accent_2"],
                    STYLE["highlight"],
                ],
            )
            heat = pitch_obj.bin_statistic(
                data["landing_x"], data["landing_y"], statistic="count", bins=(14, 10)
            )
            heatmap = pitch_obj.heatmap(
                heat, ax=ax, cmap=cmap, edgecolors=STYLE["bg"], alpha=0.95
            )
            colorbar = fig.colorbar(heatmap, ax=ax, fraction=0.035, pad=0.03)
            colorbar.outline.set_edgecolor(STYLE["line"])
            colorbar.ax.yaxis.set_tick_params(
                color=STYLE["text"], labelcolor=STYLE["text"]
            )
            colorbar.ax.set_ylabel("Landing count", color=STYLE["text"], fontsize=9.5)
            if not base.empty:
                pitch_obj.scatter(
                    base["landing_x"],
                    base["landing_y"],
                    s=34,
                    color=STYLE["accent_2"],
                    edgecolors=STYLE["line"],
                    linewidth=0.4,
                    alpha=0.72,
                    ax=ax,
                    zorder=4,
                )
            if not shot.empty:
                pitch_obj.scatter(
                    shot["landing_x"],
                    shot["landing_y"],
                    s=74 + shot["shot_xg"].clip(lower=0.0) * 880,
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
                    s=128 + goal["shot_xg"].clip(lower=0.0) * 980,
                    color=STYLE["danger"],
                    marker="*",
                    edgecolors=STYLE["line"],
                    linewidth=1.1,
                    alpha=0.96,
                    ax=ax,
                    zorder=6,
                )
            footer_lines = [
                "What it shows: where free-kick sequences end on the pitch and how often the same zones repeat.",
                "Heatmap cells show landing frequency. Small pale dots are non-shot endings, larger gold circles are shot-producing endings, and red stars are goals.",
                note,
            ]
        else:
            if not base.empty:
                pitch_obj.scatter(
                    base["landing_x"],
                    base["landing_y"],
                    s=22,
                    color=STYLE["muted"],
                    edgecolors=STYLE["line"],
                    linewidth=0.3,
                    alpha=0.28,
                    ax=ax,
                    zorder=3,
                )
            if not shot.empty:
                pitch_obj.scatter(
                    shot["landing_x"],
                    shot["landing_y"],
                    s=110 + shot["shot_xg"].clip(lower=0.0) * 900,
                    color=STYLE["accent_2"],
                    edgecolors=STYLE["line"],
                    linewidth=0.9,
                    alpha=0.94,
                    ax=ax,
                    zorder=5,
                )
            if not goal.empty:
                pitch_obj.scatter(
                    goal["landing_x"],
                    goal["landing_y"],
                    s=160 + goal["shot_xg"].clip(lower=0.0) * 1020,
                    color=STYLE["danger"],
                    marker="*",
                    edgecolors=STYLE["line"],
                    linewidth=1.2,
                    alpha=0.98,
                    ax=ax,
                    zorder=6,
                )
            footer_lines = [
                "What it shows: which free-kick endings actually turn into shots or goals, without the background density layer.",
                "Muted dots are safe outcomes, mint circles are shot-producing endings sized by xG, and red stars are goals.",
                note,
            ]
    add_footer(footer_ax, footer_lines, width=122)
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

    team_side["summary"]["shots_against"] = int(
        opponent_side["summary"]["created_shots"]
    )
    team_side["summary"]["goals_against"] = int(opponent_side["summary"]["goals"])
    team_side["summary"]["xg_against"] = round(
        (
            float(opponent_side["actions_df"]["shot_xg"].sum())
            if not opponent_side["actions_df"].empty
            else 0.0
        ),
        3,
    )
    opponent_side["summary"]["shots_against"] = int(
        team_side["summary"]["created_shots"]
    )
    opponent_side["summary"]["goals_against"] = int(team_side["summary"]["goals"])
    opponent_side["summary"]["xg_against"] = round(
        (
            float(team_side["actions_df"]["shot_xg"].sum())
            if not team_side["actions_df"].empty
            else 0.0
        ),
        3,
    )

    team_side["metrics"].append(
        {
            "label": "xG against",
            "value": team_side["summary"]["xg_against"],
            "format": "0.000",
        }
    )
    opponent_side["metrics"].append(
        {
            "label": "xG against",
            "value": opponent_side["summary"]["xg_against"],
            "format": "0.000",
        }
    )
    team_side["storylines"].append(
        f"The team conceded {team_side['summary']['shots_against']} shots and {team_side['summary']['goals_against']} goals from opponent free kicks, worth {team_side['summary']['xg_against']:.2f} xG against."
    )
    opponent_side["storylines"].append(
        f"The opponent conceded {opponent_side['summary']['shots_against']} shots and {opponent_side['summary']['goals_against']} goals from team free kicks, worth {opponent_side['summary']['xg_against']:.2f} xG against."
    )

    output_dir = context.settings.report_path(SECTION_NAME, "plots")
    output_dir.mkdir(parents=True, exist_ok=True)
    team_plot = _plot_map(
        output_dir / "team_free_kicks.png",
        team_side["actions_df"],
        f"Free Kicks by {context.team_name}",
        f"{context.team_name} | {team_side['summary']['competition_label']} | {team_side['summary']['season_label']}",
        f"Use this view to compare the shot-producing outcomes and goal locations for {context.team_name}.",
        "outcome",
    )
    team_landing = _plot_map(
        output_dir / "team_free_kicks_landing.png",
        team_side["actions_df"],
        f"Free Kick Landing Locations by {context.team_name}",
        f"{context.team_name} | {team_side['summary']['competition_label']} | {team_side['summary']['season_label']}",
        f"Use this view to see where {context.team_name} tends to land free-kick sequences before any outcome is considered.",
        "landing",
    )
    opp_plot = _plot_map(
        output_dir / "next_opponent_free_kicks.png",
        opponent_side["actions_df"],
        f"Free Kicks by {context.opponent_name}",
        f"{context.opponent_name} | {opponent_side['summary']['competition_label']} | {opponent_side['summary']['season_label']}",
        f"Use this view to compare the shot-producing outcomes and goal locations for {context.opponent_name}.",
        "outcome",
    )
    opp_landing = _plot_map(
        output_dir / "next_opponent_free_kicks_landing.png",
        opponent_side["actions_df"],
        f"Free Kick Landing Locations by {context.opponent_name}",
        f"{context.opponent_name} | {opponent_side['summary']['competition_label']} | {opponent_side['summary']['season_label']}",
        f"Use this view to see where {context.opponent_name} tends to land free-kick sequences before any outcome is considered.",
        "landing",
    )

    plot_refs = {}
    for name, path in {
        "team_free_kicks": team_plot,
        "team_free_kicks_landing": team_landing,
        "next_opponent_free_kicks": opp_plot,
        "next_opponent_free_kicks_landing": opp_landing,
    }.items():
        ref = build_ref(context.settings, path)
        if name.endswith("landing"):
            ref.update(
                {
                    "title": name.replace("_", " "),
                    "description": "Density view of where free-kick sequences land on the pitch.",
                    "reading_guide": [
                        "The heatmap shows repeated landing zones.",
                        "Small dots are safe endings, gold circles are shot-producing endings, and red stars are goals.",
                    ],
                }
            )
        else:
            ref.update(
                {
                    "title": name.replace("_", " "),
                    "description": "Outcome view of free-kick endings with shot and goal emphasis.",
                    "reading_guide": [
                        "Muted dots are non-shot endings.",
                        "Mint circles are shot-producing endings sized by xG.",
                        "Red stars are goals.",
                    ],
                }
            )
        plot_refs[name] = ref

    output_path = write_json(
        context.settings.report_path(SECTION_NAME, "analysis.json"),
        {
            "generated_at": context.generated_at,
            "section": SECTION_NAME,
            "title": "Free Kicks",
            "description": "Attacking and defensive free-kick landing zones, shot creation, and goal outcomes.",
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
        files=[output_path, team_plot, team_landing, opp_plot, opp_landing],
        index_entry={"analysis": build_ref(context.settings, output_path)},
        metadata={
            "team_free_kicks": team_side["summary"]["total"],
            "opponent_free_kicks": opponent_side["summary"]["total"],
        },
    )
