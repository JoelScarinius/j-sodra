"""Helpers for modular dashboard sections.

These helpers keep placeholder and early-stage sections consistent.

Once a section becomes more advanced, it can still use these helpers for common
payload structure and publishing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pipeline.contracts import SectionResult
from pipeline.publishing import build_ref, write_json


def section_status_payload(
    *,
    context,
    section_name: str,
    title: str,
    description: str,
    status: str = "in_progress",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a standard payload for a section.

    This is useful for placeholder sections and for keeping frontend contracts
    consistent while collaborators are still implementing the real logic.
    """

    payload = {
        "generated_at": context.generated_at,
        "section": section_name,
        "title": title,
        "description": description,
        "status": status,
        "team": {
            "id": context.team_id,
            "name": context.team_name,
            "season_id": context.active_season_id,
        },
        "next_opponent": {
            "id": context.opponent_id,
            "name": context.opponent_name,
            "season_id": context.opponent_season_id,
        },
        "summary": {
            "team": {},
            "next_opponent": {},
        },
        "metrics": {
            "team": [],
            "next_opponent": [],
        },
        "storylines": {
            "team": [],
            "next_opponent": [],
        },
        "files": {
            "data": {},
            "plots": {},
        },
        "notes": [
            "This section follows the modular section contract.",
            "Replace placeholder metrics and storylines with real analysis inside this section file.",
            "Write section artifacts under reports/<section_name>/.",
        ],
    }

    if extra:
        payload.update(extra)

    return payload


def write_basic_section(
    *,
    context,
    section_name: str,
    title: str,
    description: str,
    status: str = "in_progress",
    extra: dict[str, Any] | None = None,
) -> SectionResult:
    """Write a basic analysis.json file and return a SectionResult."""

    output_path = context.settings.report_path(section_name, "analysis.json")

    payload = section_status_payload(
        context=context,
        section_name=section_name,
        title=title,
        description=description,
        status=status,
        extra=extra,
    )

    written_path = write_json(output_path, payload)

    return SectionResult(
        name=section_name,
        files=[written_path],
        index_entry={
            "analysis": build_ref(context.settings, written_path),
        },
        metadata={
            "status": status,
            "title": title,
        },
    )


def build_data_ref(context, path: Path | None) -> dict:
    """Build a frontend reference for a data file."""

    return build_ref(context.settings, path)


def build_plot_ref(context, path: Path | None) -> dict:
    """Build a frontend reference for a plot file."""

    return build_ref(context.settings, path)
