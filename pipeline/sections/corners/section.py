"""Corners dashboard section.

This file owns the published Corners section contract:
- runs or reuses corner analysis
- writes reports/corners/analysis.json
- writes reports/corners/data/*.csv
- generates reports/corners/plots/*.png
- returns SectionResult so the orchestrator can add the section to reports/index.json
  and upload all artifacts to Supabase Storage.
"""

from __future__ import annotations

import pandas as pd

from pipeline.contracts import SectionResult
from pipeline.publishing import build_ref, write_dataframe, write_json
from pipeline.sections.corners.metrics import build_corner_analysis, empty_corner_summary
from pipeline.sections.corners.plots import generate_corner_plots


SECTION_NAME = "corners"


def _corner_side_payload(
    summary: dict,
    zones: list[dict],
    takers: dict,
    shooters: list[dict],
    storylines: list[str],
) -> dict:
    """Build the frontend payload for one corner side/scope."""

    takers = takers if isinstance(takers, dict) else {}
    return {
        **summary,
        "zones": zones,
        "top_takers_by_volume": takers.get("top_takers_by_volume", []),
        "top_takers_by_xg_created": takers.get("top_takers_by_xg_created", []),
        "top_takers_by_first_shot_xg": takers.get("top_takers_by_first_shot_xg", []),
        "top_shooters_after_corner": shooters,
        "storylines": storylines,
    }


def _corner_plot_meta(plot_name: str, subject_name: str) -> dict:
    """Return human-readable metadata for a generated corner plot."""

    if plot_name.endswith("offensive_map"):
        return {
            "title": f"{subject_name} corner delivery map",
            "description": "Goal-zoomed map of first corner deliveries and their sequence outcome.",
            "reading_guide": [
                "Gold arrows are left-side corners and mint arrows are right-side corners.",
                "Larger circles mean that the corner sequence produced more xG.",
                "White rings mark shot-ending sequences. Red stars mark goal-ending sequences.",
            ],
        }

    if plot_name.endswith("defensive_map"):
        return {
            "title": f"Opposition corner deliveries faced by {subject_name}",
            "description": "Goal-zoomed map of opposition corner deliveries faced by this defence.",
            "reading_guide": [
                "The map shows first-delivery end locations and later sequence outcome.",
                "White rings mark shot-ending sequences against. Red stars mark goal-ending sequences against.",
            ],
        }

    if plot_name.endswith("target_map"):
        return {
            "title": f"{subject_name} corner target map",
            "description": "Aggregated view of recurring target players and target zones.",
        }

    if plot_name.endswith("danger_end_heatmap"):
        return {
            "title": f"{subject_name} xG-weighted corner danger map",
            "description": "Hotspot map of first-delivery end locations weighted by full corner-sequence xG.",
        }

    if plot_name.endswith("taker_impact"):
        return {
            "title": f"{subject_name} corner takers ranked by value created",
            "description": "Horizontal bar chart ranking corner takers by full corner-sequence xG created.",
        }

    if plot_name.endswith("xg_method_comparison"):
        return {
            "title": f"{subject_name} corner xG split: first shot vs recycled threat",
            "description": "Stacked bars showing first-shot xG and extra recycled threat after corners.",
        }

    if plot_name.endswith("shooter_impact"):
        return {
            "title": f"{subject_name} finishers after corners by xG",
            "description": "Horizontal bar chart ranking finishers after corner sequences by xG.",
        }

    return {}


def _corner_plot_ref(context, path, plot_name: str) -> dict:
    """Build a frontend file reference for one plot and attach plot metadata."""

    ref = build_ref(context.settings, path)
    if not path:
        return ref

    subject_name = (
        context.team_name
        if plot_name.startswith("team_")
        else (context.opponent_name or "Next opponent")
    )
    ref.update(_corner_plot_meta(plot_name, subject_name))
    return ref


def _build_or_reuse_corner_analysis(context) -> tuple[dict, dict]:
    """Use precomputed corner analysis from context.extras or compute it here."""

    extras = context.extras or {}

    team_corner = extras.get("team_corner")
    if not isinstance(team_corner, dict):
        team_corner = build_corner_analysis(
            context.team_analysis_events_df(),
            team_id=context.team_id,
            team_name=context.team_name,
        )

    opponent_corner = extras.get("opponent_corner")
    if not isinstance(opponent_corner, dict):
        opponent_corner = build_corner_analysis(
            context.opponent_analysis_events_df(),
            team_id=context.opponent_id,
            team_name=context.opponent_name,
        )

    return team_corner, opponent_corner


def build_section(context) -> SectionResult:
    """Build and publish the Corners dashboard section."""

    team_corner, opponent_corner = _build_or_reuse_corner_analysis(context)

    plot_paths = generate_corner_plots(
        settings=context.settings,
        team_name=context.team_name,
        team_corner=team_corner,
        opponent_name=context.opponent_name,
        opponent_corner=opponent_corner,
    )

    data_paths = {
        "team_offensive": write_dataframe(
            context.settings.report_path("corners", "data", "team_offensive.csv"),
            team_corner.get("offensive_df", pd.DataFrame()),
        ),
        "team_defensive": write_dataframe(
            context.settings.report_path("corners", "data", "team_defensive.csv"),
            team_corner.get("defensive_df", pd.DataFrame()),
        ),
        "next_opponent_offensive": write_dataframe(
            context.settings.report_path("corners", "data", "next_opponent_offensive.csv"),
            opponent_corner.get("offensive_df", pd.DataFrame()),
        ),
        "next_opponent_defensive": write_dataframe(
            context.settings.report_path("corners", "data", "next_opponent_defensive.csv"),
            opponent_corner.get("defensive_df", pd.DataFrame()),
        ),
    }

    data_refs = {
        name: build_ref(context.settings, path)
        for name, path in data_paths.items()
        if path
    }
    plot_refs = {
        name: _corner_plot_ref(context, path, name)
        for name, path in plot_paths.items()
        if path
    }

    output_path = write_json(
        context.settings.report_path("corners", "analysis.json"),
        {
            "generated_at": context.generated_at,
            "section": SECTION_NAME,
            "team": {
                "offensive": _corner_side_payload(
                    team_corner.get("offensive_summary", empty_corner_summary()),
                    team_corner.get("offensive_zones", []),
                    team_corner.get("offensive_takers", {}),
                    team_corner.get("offensive_shooters", []),
                    team_corner.get("offensive_storylines", []),
                ),
                "defensive": _corner_side_payload(
                    team_corner.get("defensive_summary", empty_corner_summary()),
                    team_corner.get("defensive_zones", []),
                    team_corner.get("defensive_takers", {}),
                    team_corner.get("defensive_shooters", []),
                    team_corner.get("defensive_storylines", []),
                ),
            },
            "next_opponent": {
                "offensive": _corner_side_payload(
                    opponent_corner.get("offensive_summary", empty_corner_summary()),
                    opponent_corner.get("offensive_zones", []),
                    opponent_corner.get("offensive_takers", {}),
                    opponent_corner.get("offensive_shooters", []),
                    opponent_corner.get("offensive_storylines", []),
                ),
                "defensive": _corner_side_payload(
                    opponent_corner.get("defensive_summary", empty_corner_summary()),
                    opponent_corner.get("defensive_zones", []),
                    opponent_corner.get("defensive_takers", {}),
                    opponent_corner.get("defensive_shooters", []),
                    opponent_corner.get("defensive_storylines", []),
                ),
            },
            "storylines": {
                "team_offensive_success_factors": team_corner.get("offensive_storylines", []),
                "team_defensive_risk_factors": team_corner.get("defensive_storylines", []),
                "next_opponent_offensive_success_factors": opponent_corner.get("offensive_storylines", []),
                "next_opponent_defensive_risk_factors": opponent_corner.get("defensive_storylines", []),
            },
            "files": {
                "data": data_refs,
                "plots": plot_refs,
            },
        },
    )

    files = [output_path]
    files.extend(path for path in data_paths.values() if path)
    files.extend(path for path in plot_paths.values() if path)

    return SectionResult(
        name=SECTION_NAME,
        files=files,
        index_entry={"analysis": build_ref(context.settings, output_path)},
        metadata={
            "team_corner_count": team_corner.get("offensive_summary", {}).get("total", 0),
            "opponent_corner_count": opponent_corner.get("offensive_summary", {}).get("total", 0),
        },
    )
