"""Player-analysis analytics section.

Owner:
    Player-analysis contributor/team.

Purpose:
    Create player level analysis radar plots, metrics, and storylines for the team and next opponent.

Expected future outputs:
    reports/player_analysis/analysis.json

Contributor rules:
    1. Keep player-analysis logic in this file or in dedicated player-analysis helpers.
    2. Do not add player-analysis logic to run_pipeline.py.
    3. Do not upload directly to Supabase here.
    4. Return all created files in SectionResult.files.
    5. Use mplsoccer for pitch visualisations where possible.
"""

from __future__ import annotations

from pipeline.contracts import SectionResult
from pipeline.publishing import build_ref, write_json

SECTION_NAME = "player_analysis"


def build_section(context) -> SectionResult:
    """Write a placeholder player-analysis payload.

    Do not register this section in DEFAULT_ENABLED_SECTIONS until real player-analysis
    metrics, plots, and Lovable UI expectations are ready.
    """

    output_path = write_json(
        context.settings.report_path(SECTION_NAME, "analysis.json"),
        {
            "generated_at": context.generated_at,
            "section": SECTION_NAME,
            "status": "not_ready",
            "message": "Player-analysis analytics are not implemented yet.",
            "team": {
                "id": context.team_id,
                "name": context.team_name,
                "summary": {},
                "metrics": [],
                "storylines": [],
            },
            "next_opponent": {
                "id": context.opponent_id,
                "name": context.opponent_name,
                "summary": {},
                "metrics": [],
                "storylines": [],
            },
            "files": {"data": {}, "plots": {}},
        },
    )

    return SectionResult(
        name=SECTION_NAME,
        files=[output_path],
        index_entry={"analysis": build_ref(context.settings, output_path)},
        metadata={"status": "not_ready"},
    )
