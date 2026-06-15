"""Registry of enabled modular analytics sections.

To add a new dashboard section:

1. Create a file in pipeline/sections/.
2. Implement build_section(context) -> SectionResult.
3. Import the module here.
4. Add it to DEFAULT_ENABLED_SECTIONS.

Example:

    from pipeline.sections import open_play

    DEFAULT_ENABLED_SECTIONS = [
        open_play,
    ]

By default, all sections in DEFAULT_ENABLED_SECTIONS run.

You can override this in GitHub Actions or locally with:

    ENABLED_SECTIONS=open_play,corners,defensive

Use section names, not file paths.
"""

from __future__ import annotations

import os

from pipeline.sections import defensive
from pipeline.sections import free_kicks
from pipeline.sections import open_play
from pipeline.sections import throw_ins

DEFAULT_ENABLED_SECTIONS = [
    open_play,
    free_kicks,
    throw_ins,
    defensive,
]


def _normalise_name(value: str) -> str:
    return value.strip().lower().replace("-", "_")


def get_enabled_sections():
    """Return enabled section modules.

    If ENABLED_SECTIONS is not set, all default sections are enabled.

    If ENABLED_SECTIONS is set, only listed section names are enabled.

    Example:
        ENABLED_SECTIONS=open_play,defensive
    """

    configured = os.getenv("ENABLED_SECTIONS", "").strip()

    if not configured:
        return DEFAULT_ENABLED_SECTIONS

    requested_names = {
        _normalise_name(value) for value in configured.split(",") if value.strip()
    }

    modules_by_name = {
        _normalise_name(getattr(module, "SECTION_NAME", module.__name__)): module
        for module in DEFAULT_ENABLED_SECTIONS
    }

    unknown = sorted(requested_names - set(modules_by_name))

    if unknown:
        known = ", ".join(sorted(modules_by_name))
        raise ValueError(
            f"Unknown ENABLED_SECTIONS value(s): {', '.join(unknown)}. "
            f"Known sections: {known}"
        )

    return [
        module for name, module in modules_by_name.items() if name in requested_names
    ]
