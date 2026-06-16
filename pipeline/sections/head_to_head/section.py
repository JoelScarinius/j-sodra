"""Head-to-head dashboard section."""

from __future__ import annotations

from pipeline.analytics import build_head_to_head_last_meeting, build_head_to_head_overview
from pipeline.contracts import SectionResult
from pipeline.publishing import build_ref, write_json
from pipeline.sections.head_to_head.plots import generate_h2h_plots


SECTION_NAME = "head_to_head"


def _get_or_build_h2h(context) -> tuple[dict, dict]:
    extras = context.extras or {}
    overview = extras.get("head_to_head_overview")
    if not isinstance(overview, dict):
        overview = build_head_to_head_overview(
            team_id=context.team_id,
            team_name=context.team_name,
            opponent_id=context.opponent_id,
            opponent_name=context.opponent_name,
            matches_df=context.team_matches_df(),
            active_season_id=context.active_season_id,
            fallback_previous_season_id=context.team_data.get("analysis_scope", {}).get("previous_season_id"),
            max_h2h_matches=context.settings.max_h2h_matches,
            h2h_fallback_to_previous_season=context.settings.h2h_fallback_to_previous_season,
        )

    last = extras.get("head_to_head_last")
    if not isinstance(last, dict):
        last = build_head_to_head_last_meeting(overview)

    return overview, last


def build_section(context) -> SectionResult:
    overview, last_meeting = _get_or_build_h2h(context)
    plot_paths = generate_h2h_plots(context=context, head_to_head_overview=overview)
    plot_refs = {name: build_ref(context.settings, path) for name, path in plot_paths.items() if path}

    output_path = write_json(
        context.settings.report_path("head_to_head", "overview.json"),
        {
            "generated_at": context.generated_at,
            "section": SECTION_NAME,
            "overview": overview,
            "last_meeting": last_meeting,
            "files": {"plots": plot_refs},
        },
    )

    files = [output_path, *[path for path in plot_paths.values() if path]]

    return SectionResult(
        name=SECTION_NAME,
        files=files,
        index_entry={"overview": build_ref(context.settings, output_path)},
        metadata={"found": bool(overview.get("found"))},
    )
