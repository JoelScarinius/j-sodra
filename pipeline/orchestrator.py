"""Pipeline orchestration for the J-Södra analytics refresh.

The orchestrator should coordinate shared data collection and publishing only.
Dashboard-specific logic belongs in pipeline/sections/<section_name>/.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from pipeline.analytics import (
    build_head_to_head_last_meeting,
    build_head_to_head_overview,
    build_matchup_card,
    build_recent_form,
    summarize_results_from_matches,
)
from pipeline.common import extract_logo_url
from pipeline.context import PipelineContext
from pipeline.data_service import DataService
from pipeline.publishing import (
    build_ref,
    delete_files_from_supabase,
    upload_files_to_supabase,
    write_json,
)
from pipeline.section_runner import run_registered_sections


def _empty_team_dataset(settings, season_id=None) -> dict:
    """Return an empty dataset with the same shape as DataService.collect_team_dataset."""

    return {
        "matches_df": pd.DataFrame(),
        "season_matches_df": pd.DataFrame(),
        "recent_played_df": pd.DataFrame(),
        "selected_match_ids": [],
        "events_df": pd.DataFrame(),
        "with_events": [],
        "without_events": [],
        "analysis_matches_df": pd.DataFrame(),
        "analysis_selected_match_ids": [],
        "analysis_events_df": pd.DataFrame(),
        "analysis_with_events": [],
        "analysis_without_events": [],
        "analysis_scope": {
            "target_match_count": int(settings.analysis_event_match_target),
            "current_season_id": season_id,
            "current_season_played_matches_available": 0,
            "current_season_matches_used": 0,
            "previous_season_id": None,
            "previous_season_matches_used": 0,
            "analysis_matches_used": 0,
            "is_complemented_with_previous_season": False,
            "scope_label": "current_season_only",
        },
        "season_id": season_id,
    }


def _derive_refresh_webhook_url(settings) -> str | None:
    """Derive the public refresh endpoint for reports/index.json metadata."""

    public_base = (settings.supabase_public_base_url or "").rstrip("/")
    if public_base:
        return f"{public_base}/functions/v1/refresh-reports"

    function_url = (settings.supabase_function_url or "").rstrip("/")
    marker = "/functions/v1/"
    if marker in function_url:
        base = function_url.split(marker, 1)[0]
        return f"{base}{marker}refresh-reports"

    return None


def _print_scope_notes(settings, team_name: str, dataset: dict):
    if settings.filter_to_active_season:
        print(f"Season scope for {team_name}: seasonId={dataset.get('season_id')}")

    analysis_scope = dataset.get("analysis_scope", {})
    if analysis_scope.get("is_complemented_with_previous_season"):
        print(
            "Analysis scope complemented with previous season "
            f"for {team_name} (previous seasonId={analysis_scope.get('previous_season_id')}, "
            f"added matches={analysis_scope.get('previous_season_matches_used')})."
        )


def _write_core_reports(
    *,
    settings,
    generated_at: str,
    team_payload: dict,
    next_opponent_payload: dict,
    matchup_payload: dict,
    team_summary: dict,
    opponent_summary: dict,
    upcoming_team: list[dict],
    upcoming_opponent: list[dict],
    team_recent_form: dict,
    opponent_recent_form: dict,
) -> tuple[dict, list]:
    """Write non-section core files and return index refs + files."""

    files = []

    team_entity_path = write_json(
        settings.report_path("entities", "team.json"),
        {"generated_at": generated_at, **team_payload},
    )
    files.append(team_entity_path)

    next_opponent_entity_path = write_json(
        settings.report_path("entities", "next_opponent.json"),
        {"generated_at": generated_at, **next_opponent_payload},
    )
    files.append(next_opponent_entity_path)

    matchup_path = write_json(
        settings.report_path("matchup", "current.json"),
        {"generated_at": generated_at, **matchup_payload},
    )
    files.append(matchup_path)

    team_summary_path = write_json(
        settings.report_path("overview", "team.json"),
        {"generated_at": generated_at, **team_summary},
    )
    files.append(team_summary_path)

    next_opponent_summary_path = write_json(
        settings.report_path("overview", "next_opponent.json"),
        {"generated_at": generated_at, **opponent_summary},
    )
    files.append(next_opponent_summary_path)

    fixtures_path = write_json(
        settings.report_path("fixtures", "upcoming.json"),
        {
            "generated_at": generated_at,
            "team": upcoming_team,
            "next_opponent": upcoming_opponent,
        },
    )
    files.append(fixtures_path)

    recent_form_path = write_json(
        settings.report_path("forms", "recent_form.json"),
        {
            "generated_at": generated_at,
            "team": team_recent_form,
            "next_opponent": opponent_recent_form,
        },
    )
    files.append(recent_form_path)

    section_refs = {
        "team": build_ref(settings, team_entity_path),
        "next_opponent": build_ref(settings, next_opponent_entity_path),
        "matchup": build_ref(settings, matchup_path),
        "overview": {
            "team": build_ref(settings, team_summary_path),
            "next_opponent": build_ref(settings, next_opponent_summary_path),
        },
        "fixtures": {"upcoming": build_ref(settings, fixtures_path)},
        "forms": {"recent_form": build_ref(settings, recent_form_path)},
    }

    return section_refs, files


def _export_competitions(service: DataService) -> list:
    """Export competition CSV snapshots used by the dashboard."""

    print("\nExporting competition snapshots...")
    paths = [
        service.export_competition_matches(
            output_name="superettan",
            search_queries=["Superettan", "Sweden Superettan"],
            keywords=["superettan"],
        ),
        service.export_competition_matches(
            output_name="division1",
            search_queries=["Ettan", "Ettan Sodra", "Ettan Norra", "Division 1 Sweden"],
            keywords=["ettan", "division 1"],
        ),
    ]
    return [path for path in paths if path]


def _write_index(
    *,
    settings,
    generated_at: str,
    refresh_webhook_url: str | None,
    section_refs: dict,
) -> object:
    index_path = write_json(
        settings.report_path("index.json"),
        {
            "generated_at": generated_at,
            "version": 3,
            "storage": {
                "bucket": settings.supabase_s3_bucket,
                "prefix": settings.supabase_s3_prefix,
            },
            "refresh": {
                "supports_force_refresh": True,
                "requires_server_side_trigger": True,
                "webhook_url": refresh_webhook_url,
                "webhook_method": "POST",
                "status_method": "GET",
                "status_url_template": (
                    f"{refresh_webhook_url}?run_id={{run_id}}" if refresh_webhook_url else None
                ),
                "poll_interval_ms": 3000,
                "server_command": "python run_pipeline.py --force-refresh",
                "frontend_note": (
                    "Browser refetch alone only reloads published JSON. To recompute analytics, "
                    "POST to the refresh webhook, poll the returned run_id until succeeded, "
                    "then refetch reports/index.json with a cache-busting query string."
                ),
            },
            "sections": section_refs,
        },
    )
    return index_path


def run_pipeline(settings) -> int:
    generated_at = datetime.now(timezone.utc).isoformat()
    refresh_webhook_url = _derive_refresh_webhook_url(settings)
    settings.reports_dir.mkdir(parents=True, exist_ok=True)

    print("Starting J-Södra analytics pipeline...")
    if settings.force_refresh_from_api:
        print("Force refresh enabled: bypassing local caches for live API refresh.")
    if not settings.supabase_anon_key:
        print(
            "Warning: SUPABASE_ANON_KEY is not set. If verify JWT is enabled, calls may fail with 401."
        )

    service = DataService(settings)

    print("\nResolving target team...")
    team = service.resolve_target_team()
    if not team:
        print("Could not resolve J-Södra team id.")
        return 1

    team_id = team.get("wyId")
    team_name = team.get("name", "J-Södra")
    print(f"Found team: {team_name} (ID: {team_id})")

    team_profile = service.get_team_profile(team_id) or {}
    team_logo_url = extract_logo_url(team_profile)

    print("\nCollecting J-Södra matches/events...")
    team_data = service.collect_team_dataset(
        team_id,
        team_name,
        settings.max_event_matches,
        preferred_season_id=None,
        filter_to_active_season=settings.filter_to_active_season,
    )
    _print_scope_notes(settings, team_name, team_data)

    matches_df = team_data.get("matches_df", pd.DataFrame())
    team_season_matches_df = team_data.get("season_matches_df", matches_df)
    team_analysis_matches_df = team_data.get("analysis_matches_df", pd.DataFrame())
    active_season_id = team_data.get("season_id")

    print("\nFinding next opponent and upcoming fixtures...")
    next_opponent_info = service.determine_next_opponent(
        team_id,
        team_name,
        team_season_matches_df,
        preferred_season_id=active_season_id,
    )
    upcoming_team = next_opponent_info.get("upcoming_fixtures", [])

    opponent_id = next_opponent_info.get("opponent_id")
    opponent_name = next_opponent_info.get("opponent_name")

    if not opponent_id and opponent_name:
        found = service.search_team_by_name(opponent_name)
        if found.get("id"):
            opponent_id = found.get("id")
            opponent_name = found.get("name") or opponent_name

    if opponent_id and not opponent_name:
        opponent_name = service.resolve_team_name_by_id(opponent_id)

    next_opponent_info["opponent_id"] = opponent_id
    next_opponent_info["opponent_name"] = opponent_name

    opponent_profile = service.get_team_profile(opponent_id) if opponent_id else {}
    opponent_logo_url = extract_logo_url(opponent_profile or {})

    if opponent_name:
        print(f"Next opponent source={next_opponent_info.get('source')}: {opponent_name} (ID: {opponent_id})")
    else:
        print("No next opponent could be resolved from fixtures or recent matches.")

    opponent_data = _empty_team_dataset(settings)
    upcoming_opponent = []

    if opponent_id:
        opponent_season_id = next_opponent_info.get("season_id") or active_season_id
        print("\nCollecting next-opponent dataset...")
        opponent_data = service.collect_team_dataset(
            opponent_id,
            opponent_name or "Next opponent",
            settings.next_opponent_event_matches,
            preferred_season_id=opponent_season_id,
            filter_to_active_season=settings.filter_to_active_season,
        )
        _print_scope_notes(settings, opponent_name or "Next opponent", opponent_data)

        upcoming_opponent = service.build_upcoming_fixtures(
            opponent_id,
            opponent_name or "Next opponent",
            limit=settings.upcoming_fixture_limit,
            preferred_season_id=opponent_season_id,
        )

    print("\nComputing shared summaries, form, and H2H...")
    opponent_analysis_matches_df = opponent_data.get("analysis_matches_df", pd.DataFrame())

    team_recent_form = build_recent_form(
        team_analysis_matches_df,
        team_name,
        limit=settings.recent_form_matches,
    )
    opponent_recent_form = build_recent_form(
        opponent_analysis_matches_df,
        opponent_name or "",
        limit=settings.recent_form_matches,
    )

    team_result_summary = summarize_results_from_matches(team_season_matches_df, team_name)
    opponent_result_summary = summarize_results_from_matches(
        opponent_data.get("season_matches_df", pd.DataFrame()),
        opponent_name or "",
    )

    head_to_head_overview = build_head_to_head_overview(
        team_id=team_id,
        team_name=team_name,
        opponent_id=opponent_id,
        opponent_name=opponent_name,
        matches_df=matches_df,
        active_season_id=active_season_id,
        fallback_previous_season_id=team_data.get("analysis_scope", {}).get("previous_season_id"),
        max_h2h_matches=settings.max_h2h_matches,
        h2h_fallback_to_previous_season=settings.h2h_fallback_to_previous_season,
    )
    head_to_head_last = build_head_to_head_last_meeting(head_to_head_overview)

    team_payload = {
        "id": team_id,
        "name": team_name,
        "logo_url": team_logo_url,
        "season_id": active_season_id,
    }
    opponent_payload = {
        "id": opponent_id,
        "name": opponent_name,
        "logo_url": opponent_logo_url,
        "season_id": opponent_data.get("season_id"),
    }
    next_opponent_payload = {
        **opponent_payload,
        "source": next_opponent_info.get("source"),
        "match_id": next_opponent_info.get("match_id"),
        "match_dateutc": next_opponent_info.get("dateutc"),
        "status": next_opponent_info.get("status"),
        "label": next_opponent_info.get("label"),
        "target_side": next_opponent_info.get("target_side"),
    }

    matchup_payload = build_matchup_card(
        next_opponent_info=next_opponent_info,
        team_payload=team_payload,
        opponent_payload=opponent_payload,
    )

    team_summary = {
        "team": team_payload,
        "season_id": active_season_id,
        "season_match_count": int(len(team_season_matches_df)),
        "attempted_event_matches": len(team_data.get("selected_match_ids", [])),
        "event_matches_found": len(team_data.get("with_events", [])),
        "event_matches_missing": len(team_data.get("without_events", [])),
        "event_missing_match_ids": team_data.get("without_events", []),
        "results": team_result_summary,
    }
    opponent_summary = {
        "team": opponent_payload,
        "season_id": opponent_data.get("season_id"),
        "season_match_count": int(len(opponent_data.get("season_matches_df", pd.DataFrame()))),
        "attempted_event_matches": len(opponent_data.get("selected_match_ids", [])),
        "event_matches_found": len(opponent_data.get("with_events", [])),
        "event_matches_missing": len(opponent_data.get("without_events", [])),
        "event_missing_match_ids": opponent_data.get("without_events", []),
        "results": opponent_result_summary,
    }

    context = PipelineContext(
        settings=settings,
        service=service,
        generated_at=generated_at,
        team=team_payload,
        next_opponent=next_opponent_payload,
        team_data=team_data,
        opponent_data=opponent_data,
        matchup=matchup_payload,
        extras={
            "next_opponent_info": next_opponent_info,
            "team_recent_form": team_recent_form,
            "opponent_recent_form": opponent_recent_form,
            "team_result_summary": team_result_summary,
            "opponent_result_summary": opponent_result_summary,
            "head_to_head_overview": head_to_head_overview,
            "head_to_head_last": head_to_head_last,
        },
    )

    section_refs, core_files = _write_core_reports(
        settings=settings,
        generated_at=generated_at,
        team_payload=team_payload,
        next_opponent_payload=next_opponent_payload,
        matchup_payload=matchup_payload,
        team_summary=team_summary,
        opponent_summary=opponent_summary,
        upcoming_team=upcoming_team,
        upcoming_opponent=upcoming_opponent,
        team_recent_form=team_recent_form,
        opponent_recent_form=opponent_recent_form,
    )

    section_results = run_registered_sections(context)
    section_files = []
    for result in section_results:
        section_refs[result.name] = result.index_entry
        section_files.extend(result.existing_files())

    competition_paths = _export_competitions(service)
    if competition_paths:
        section_refs.setdefault("exports", {})["competitions"] = {
            path.stem: build_ref(settings, path) for path in competition_paths
        }

    index_path = _write_index(
        settings=settings,
        generated_at=generated_at,
        refresh_webhook_url=refresh_webhook_url,
        section_refs=section_refs,
    )

    upload_candidates = [*core_files, *section_files, *competition_paths, index_path]

    print(f"Wrote modular outputs under {settings.reports_dir}")

    if settings.upload_to_supabase_storage:
        print("\nUploading modular artifacts to Supabase Storage...")
        delete_files_from_supabase(settings, [])
        uploaded = upload_files_to_supabase(settings, upload_candidates)
        if uploaded:
            manifest_path = write_json(
                settings.report_path("upload_manifest.json"),
                {"generated_at": generated_at, "files": uploaded},
            )
            print(f"Uploaded {len(uploaded)} files and wrote manifest -> {manifest_path}")
    else:
        print("\nUpload disabled. Set UPLOAD_TO_SUPABASE_STORAGE=1 to push reports to the bucket.")

    print("\nDone.")
    return 0
