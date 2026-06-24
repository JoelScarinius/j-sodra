"""Defensive analytics section.

Owner:
    Defensive analytics contributor/team.

Purpose:
    Analyse how J-Södra and the next opponent defend, press, concede entries,
    and protect dangerous spaces.

Expected future outputs:
    reports/defensive/analysis.json
    reports/defensive/data/team_defensive_events.csv
    reports/defensive/data/next_opponent_defensive_events.csv
    reports/defensive/plots/team_defensive_map.png
    reports/defensive/plots/next_opponent_defensive_map.png

Contributor rules:
    1. Keep defensive logic in this file or in dedicated defensive helpers.
    2. Do not add defensive logic to run_pipeline.py.
    3. Do not upload directly to Supabase here.
    4. Return all created files in SectionResult.files.
    5. Use mplsoccer for pitch visualisations where possible.
"""

from __future__ import annotations

from pipeline.contracts import SectionResult
from pipeline.sections._helpers import write_basic_section

SECTION_NAME = "defensive"


def build_section(context) -> SectionResult:
    """Build the Defensive dashboard section.

    This first version publishes a stable placeholder contract so Lovable can
    safely show the tab while the real analysis is implemented.
    """

    extra = {
        "planned_metrics": [
            "Defensive actions",
            "Pressing events",
            "Ball recoveries",
            "Interceptions",
            "Tackles",
            "Entries conceded",
            "Box entries conceded",
            "Shots conceded by zone",
            "xG conceded",
        ],
        "implementation_notes": [
            "Use context.team_analysis_events_df() and context.opponent_analysis_events_df().",
            "Separate defensive actions by zone and match state where possible.",
            "Create opponent-specific defensive preparation views.",
            "Use mplsoccer pitch maps for defensive action maps.",
        ],
    }

    return write_basic_section(
        context=context,
        section_name=SECTION_NAME,
        title="Defensive",
        description=(
            "Defensive actions, pressure, recoveries, and conceded threat for both teams."
        ),
        status="in_progress",
        extra=extra,
    )
