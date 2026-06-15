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
    2. Do not add open-play logic to fetch_football_data.py.
    3. Do not upload directly to Supabase here.
    4. Return all created files in SectionResult.files.
    5. Use mplsoccer for pitch visualisations where possible.
"""

from __future__ import annotations

from pipeline.contracts import SectionResult
from pipeline.sections._helpers import write_basic_section

SECTION_NAME = "open_play"


def build_section(context) -> SectionResult:
    """Build the Open Play dashboard section.

    This first version publishes a stable placeholder contract so Lovable can
    safely show the tab while the real analysis is implemented.
    """

    extra = {
        "planned_metrics": [
            "Possession progression",
            "Final-third entries",
            "Box entries",
            "Shot-ending open-play attacks",
            "xG from open play",
            "Open-play threat conceded",
        ],
        "implementation_notes": [
            "Use context.team_analysis_events_df() for J-Södra event data.",
            "Use context.opponent_analysis_events_df() for next-opponent event data.",
            "Use context.team_analysis_matches_df() and context.opponent_analysis_matches_df() for match scope.",
            "Use mplsoccer for pitch maps and football-specific visualisations.",
        ],
    }

    return write_basic_section(
        context=context,
        section_name=SECTION_NAME,
        title="Open Play",
        description=(
            "Open-play attacking and defensive patterns for J-Södra and the next opponent."
        ),
        status="in_progress",
        extra=extra,
    )
