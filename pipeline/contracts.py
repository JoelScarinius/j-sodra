"""Shared contracts for modular analytics sections.

Every dashboard section should return a SectionResult.

The orchestrator does not need to know how each section works internally.
It only needs to know:

1. The section name.
2. Which files were created.
3. What should be added to reports/index.json.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class SectionResult:
    """Result returned by one analytics section.

    Attributes:
        name:
            Stable section key used in reports/index.json.

            Examples:
                "open_play"
                "corners"
                "throw_ins"
                "defensive"

        files:
            Local files created by the section.

            These files will be included in the Supabase Storage upload list
            when UPLOAD_TO_SUPABASE_STORAGE=1.

        index_entry:
            JSON-compatible object inserted into reports/index.json under
            sections[name].

            Example:
                {
                    "analysis": {
                        "path": "reports/open_play/analysis.json",
                        "url": "https://..."
                    }
                }

        metadata:
            Optional internal metadata useful for debugging or logs.
            This is not automatically published unless a section adds it to
            its JSON payload.
    """

    name: str
    files: list[Path] = field(default_factory=list)
    index_entry: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def existing_files(self) -> list[Path]:
        """Return only files that currently exist on disk."""

        return [
            path
            for path in self.files
            if isinstance(path, Path) and path.exists() and path.is_file()
        ]
