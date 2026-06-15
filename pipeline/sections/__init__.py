"""Modular dashboard sections.

Each file in this package should represent one dashboard section.

Recommended section file structure:

    SECTION_NAME = "open_play"

    def build_section(context) -> SectionResult:
        ...
        return SectionResult(...)

Sections should:

1. Use the shared PipelineContext.
2. Write outputs under reports/<section_name>/.
3. Return SectionResult.
4. Avoid direct Supabase Storage upload.
5. Avoid direct Wyscout API calls unless agreed.
6. Use mplsoccer as much as possible for football pitch visualisations.
"""
