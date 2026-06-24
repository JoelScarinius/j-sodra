"""Run registered analytics sections.

This module belongs in the pipeline root because it is shared pipeline
infrastructure. It knows how to run sections, but it does not know how any
individual section calculates metrics or writes its payload.
"""

from __future__ import annotations

import os
import traceback

from pipeline.context import PipelineContext
from pipeline.contracts import SectionResult
from pipeline.registry import get_enabled_sections


def _allow_section_failure() -> bool:
    """Return whether section failures should be logged instead of raised."""

    return str(os.getenv("ALLOW_SECTION_FAILURES", "0")).lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def run_registered_sections(context: PipelineContext) -> list[SectionResult]:
    """Run all enabled section modules and return their SectionResult objects."""

    results: list[SectionResult] = []
    allow_failure = _allow_section_failure()

    for section_module in get_enabled_sections():
        section_name = getattr(section_module, "SECTION_NAME", section_module.__name__)
        print(f"\nRunning section: {section_name}")

        try:
            result = section_module.build_section(context)
        except Exception as exc:
            print(f"Section failed: {section_name}")
            traceback.print_exc()
            if allow_failure:
                print(f"Continuing because ALLOW_SECTION_FAILURES=1: {section_name}")
                continue
            raise RuntimeError(f"Section failed: {section_name}") from exc

        if not isinstance(result, SectionResult):
            raise TypeError(
                f"Section {section_name} must return SectionResult, "
                f"got {type(result).__name__}"
            )

        print(
            f"Section completed: {result.name} "
            f"({len(result.existing_files())}/{len(result.files)} files created)"
        )
        results.append(result)

    return results
