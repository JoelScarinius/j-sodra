"""Shared contracts for modular analytics sections.

Every dashboard section must return a SectionResult. The orchestrator only needs
three things from a section:

1. the stable section name,
2. the files created by the section,
3. the entry that should be added to reports/index.json.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class SectionResult:
    """Result returned by one analytics section."""

    name: str
    files: list[Path] = field(default_factory=list)
    index_entry: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def existing_files(self) -> list[Path]:
        """Return only generated files that exist on disk."""

        return [
            path
            for path in self.files
            if isinstance(path, Path) and path.exists() and path.is_file()
        ]
