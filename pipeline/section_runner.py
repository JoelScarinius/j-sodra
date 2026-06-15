"""Run registered analytics sections.

The orchestrator calls this module after shared team/opponent datasets have
been collected.

This module is intentionally small. It does not know how sections calculate
their data. It only runs registered section modules and collects their results.
"""

from __future__ import annotations

import traceback

from pipeline.context import PipelineContext
from pipeline.contracts import SectionResult
from pipeline.registry import get_enabled_sections


def run_registered_sections(context: PipelineContext) -> list[SectionResult]:
    """Run all enabled modular analytics sections.

    A section failure should fail the pipeline. This is intentional because a
    broken section should not silently publish incomplete data to the dashboard.

    If you later want non-critical experimental sections, add an
    allow_failure flag to the registry.
    """

    results: list[SectionResult] = []

    for section_module in get_enabled_sections():
        section_name = getattr(section_module, "SECTION_NAME", section_module.__name__)

        print(f"\nRunning section: {section_name}")

        try:
            result = section_module.build_section(context)
        except Exception as exc:
            print(f"Section failed: {section_name}")
            traceback.print_exc()
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
