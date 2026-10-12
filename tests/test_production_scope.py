from pathlib import Path


def test_sync_is_limited_to_current_published_years():
    source = Path("supabase/functions/sync-league/index.ts").read_text(encoding="utf-8")
    assert "SYNC_ALLOWED_SEASON_YEARS" in source
    assert '"2025,2026"' in source
    assert "SYNC_EARLIEST_MATCH_YEAR" in source
    assert "kickoffYear >= earliestMatchYear" in source
    assert "allowedSeasonYears.has(kickoffYear)" in source


def test_refresh_is_incremental_and_checks_search_route():
    source = Path(".github/workflows/refresh-reports.yml").read_text(encoding="utf-8")
    assert 'ENABLE_INCREMENTAL_EVENT_FETCH: "1"' in source
    assert 'ENABLE_INCREMENTAL_COMPETITION_FETCH: "1"' in source
    assert "python run_pipeline.py --force-refresh" not in source
    assert 'check_proxy "/search"' in source
    assert "cache/events" in source
    assert "cache/competitions" in source
