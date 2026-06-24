"""Open-play analytics section.

Owner:
    Open-play contributor/team.

Purpose:
    Analyse how J-Södra and the next opponent create, progress, and concede
    open-play attacks.

Expected future outputs:
    reports/open_play/analysis.json
    reports/open_play/data/team_sequences.csv
    reports/open_play/data/next_opponent_sequences.csv
    reports/open_play/plots/team_progression_map.png
    reports/open_play/plots/next_opponent_progression_map.png

Contributor rules:
    1. Keep open-play logic in this file or in dedicated open-play helpers.
    2. Do not add open-play logic to run_pipeline.py.
    3. Do not upload directly to Supabase here.
    4. Return all created files in SectionResult.files.
    5. Use mplsoccer for pitch visualisations where possible.
"""

from __future__ import annotations

from pipeline.contracts import SectionResult
from pipeline.publishing import build_ref, write_json

SECTION_NAME = "open_play"


def build_section(context) -> SectionResult:
    """Write a placeholder open-play payload.

    Do not register this section in DEFAULT_ENABLED_SECTIONS until real open-play
    metrics, plots, and Lovable UI expectations are ready.
    """

    output_path = write_json(
        context.settings.report_path(SECTION_NAME, "analysis.json"),
        {
            "generated_at": context.generated_at,
            "section": SECTION_NAME,
            "status": "not_ready",
            "message": "Open-play analytics are not implemented yet.",
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
