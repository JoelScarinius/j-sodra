"""Registry of enabled modular analytics sections.

To add a section:

1. create pipeline/sections/<section_name>/,
2. expose SECTION_NAME and build_section from its __init__.py,
3. import the package here,
4. add it to DEFAULT_ENABLED_SECTIONS.

Set ENABLED_SECTIONS=corners,head_to_head to run only selected sections.
"""

from __future__ import annotations

import os
from types import ModuleType

from pipeline.sections import corners
from pipeline.sections import defensive
from pipeline.sections import free_kicks
from pipeline.sections import head_to_head
from pipeline.sections import open_play
from pipeline.sections import throw_ins

DEFAULT_ENABLED_SECTIONS: list[ModuleType] = [
    head_to_head,
    corners,
    open_play,
    free_kicks,
    throw_ins,
    defensive,
]


def _normalise_name(value: str) -> str:
    return value.strip().lower().replace("-", "_")


def _section_name(module: ModuleType) -> str:
    return _normalise_name(
        getattr(module, "SECTION_NAME", module.__name__.split(".")[-1])
    )


def get_enabled_sections() -> list[ModuleType]:
    """Return section modules enabled for the current run."""

    configured = os.getenv("ENABLED_SECTIONS", "").strip()
    if not configured:
        return list(DEFAULT_ENABLED_SECTIONS)

    requested_names = {
        _normalise_name(value) for value in configured.split(",") if value.strip()
    }

    modules_by_name = {
        _section_name(module): module for module in DEFAULT_ENABLED_SECTIONS
    }
    unknown = sorted(requested_names - set(modules_by_name))

    if unknown:
        known = ", ".join(sorted(modules_by_name))
        raise ValueError(
            f"Unknown ENABLED_SECTIONS value(s): {', '.join(unknown)}. "
            f"Known sections: {known}"
        )

    return [
        module
        for module in DEFAULT_ENABLED_SECTIONS
        if _section_name(module) in requested_names
    ]
