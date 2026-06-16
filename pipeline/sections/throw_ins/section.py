"""Throw-in analytics section.

Owner:
    Throw-in contributor/team.

Purpose:
    Analyse how J-Södra and the next opponent use throw-ins to retain the ball,
    progress play, create entries, or expose defensive weaknesses.

Expected future outputs:
    reports/throw_ins/analysis.json
    reports/throw_ins/data/team_throw_ins.csv
    reports/throw_ins/data/next_opponent_throw_ins.csv
    reports/throw_ins/plots/team_throw_in_zones.png
    reports/throw_ins/plots/next_opponent_throw_in_zones.png

Contributor rules:
    1. Keep throw-in logic in this file or in dedicated throw-in helpers.
    2. Do not add throw-in logic to run_pipeline.py.
    3. Do not upload directly to Supabase here.
    4. Return all created files in SectionResult.files.
    5. Use mplsoccer for pitch visualisations where possible.
"""

from __future__ import annotations

from pipeline.contracts import SectionResult
from pipeline.sections._helpers import write_basic_section

SECTION_NAME = "throw_ins"


def build_section(context) -> SectionResult:
    """Build the Throw-ins dashboard section.

    This first version publishes a stable placeholder contract so Lovable can
    safely show the tab while the real analysis is implemented.
    """

    extra = {
        "planned_metrics": [
            "Throw-ins taken",
            "Throw-ins conceded",
            "Retention after throw-in",
            "Progression after throw-in",
            "Final-third throw-ins",
            "Throw-ins leading to shots",
            "Dangerous throw-in zones for and against",
        ],
        "implementation_notes": [
            "Filter event data for throw-in related events.",
            "Measure first action and short possession outcome after the throw-in.",
            "Separate defensive and attacking throw-ins.",
            "Use mplsoccer pitch maps for zone visualisations.",
        ],
    }

    return write_basic_section(
        context=context,
        section_name=SECTION_NAME,
        title="Throw-ins",
        description=(
            "Throw-in usage, retention, progression, and danger patterns for both teams."
        ),
        status="in_progress",
        extra=extra,
    )
