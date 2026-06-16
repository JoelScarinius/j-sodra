"""Registry of enabled modular analytics sections."""

from __future__ import annotations

import os

from pipeline.sections import corners
from pipeline.sections import defensive
from pipeline.sections import free_kicks
from pipeline.sections import head_to_head
from pipeline.sections import open_play
from pipeline.sections import throw_ins


DEFAULT_ENABLED_SECTIONS = [
    head_to_head,
    corners,
    open_play,
    free_kicks,
    throw_ins,
    defensive,
]


def _normalise_name(value: str) -> str:
    return value.strip().lower().replace("-", "_")


def get_enabled_sections():
    configured = os.getenv("ENABLED_SECTIONS", "").strip()
    if not configured:
        return DEFAULT_ENABLED_SECTIONS

    requested_names = {_normalise_name(value) for value in configured.split(",") if value.strip()}
    modules_by_name = {
        _normalise_name(getattr(module, "SECTION_NAME", module.__name__.split(".")[-1])): module
        for module in DEFAULT_ENABLED_SECTIONS
    }

    unknown = sorted(requested_names - set(modules_by_name))
    if unknown:
        known = ", ".join(sorted(modules_by_name))
        raise ValueError(f"Unknown ENABLED_SECTIONS value(s): {', '.join(unknown)}. Known sections: {known}")

    return [module for name, module in modules_by_name.items() if name in requested_names]
