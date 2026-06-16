"""Free-kick analytics section.

Owner:
    Free-kick contributor/team.

Purpose:
    Analyse attacking and defensive free-kick patterns for J-Södra and the
    next opponent.

Expected future outputs:
    reports/free_kicks/analysis.json
    reports/free_kicks/data/team_free_kicks.csv
    reports/free_kicks/data/next_opponent_free_kicks.csv
    reports/free_kicks/plots/team_free_kick_map.png
    reports/free_kicks/plots/next_opponent_free_kick_map.png

Contributor rules:
    1. Keep free-kick logic in this file or in dedicated free-kick helpers.
    2. Do not add free-kick logic to run_pipeline.py.
    3. Do not upload directly to Supabase here.
    4. Return all created files in SectionResult.files.
    5. Use mplsoccer for pitch visualisations where possible.
"""

from __future__ import annotations

from pipeline.contracts import SectionResult
from pipeline.sections._helpers import write_basic_section

SECTION_NAME = "free_kicks"


def build_section(context) -> SectionResult:
    """Build the Free Kicks dashboard section.

    This first version publishes a stable placeholder contract so Lovable can
    safely show the tab while the real analysis is implemented.
    """

    extra = {
        "planned_metrics": [
            "Free kicks won",
            "Free kicks conceded",
            "Direct free-kick shots",
            "Indirect free-kick deliveries",
            "xG from free-kick situations",
            "Dangerous zones for and against",
        ],
        "implementation_notes": [
            "Filter event data for free-kick related events.",
            "Separate direct shots from deliveries/crosses.",
            "Create attacking and defensive views for both teams.",
            "Use mplsoccer pitch maps where location data is available.",
        ],
    }

    return write_basic_section(
        context=context,
        section_name=SECTION_NAME,
        title="Free Kicks",
        description=(
            "Free-kick attacking and defensive patterns for J-Södra and the next opponent."
        ),
        status="in_progress",
        extra=extra,
    )
