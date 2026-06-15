"""Pipeline orchestration for the J-Södra analytics refresh.

This module coordinates the existing services and analytics modules. It should
contain orchestration only: no new football calculations, no low-level API calls,
and no plotting implementation. Add those to dedicated modules instead.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from pipeline.context import PipelineContext
from pipeline.section_runner import run_registered_sections

from pipeline.analytics import (
    build_head_to_head_last_meeting,
    build_head_to_head_overview,
    build_matchup_card,
    build_recent_form,
    summarize_results_from_matches,
)
from pipeline.common import extract_logo_url, jsonable
from pipeline.corners import build_corner_analysis, empty_corner_summary
from pipeline.data_service import DataService
from pipeline.plots import generate_section_plots
from pipeline.publishing import (
    build_ref,
    delete_files_from_supabase,
    upload_files_to_supabase,
    write_dataframe,
    write_json,
)

# from pipeline.registry import ENABLED_SECTIONS

# section_refs = {}
# upload_candidates = []

# for section in ENABLED_SECTIONS:
#     result = section.build_section(context)
#     section_refs[result.name] = result.index_entry
#     upload_candidates.extend(result.files)


def _default_corner_analysis() -> dict:
    return {
        "offensive_summary": empty_corner_summary(),
        "defensive_summary": empty_corner_summary(),
        "offensive_df": pd.DataFrame(),
        "defensive_df": pd.DataFrame(),
        "offensive_zones": [],
        "defensive_zones": [],
        "offensive_takers": {
            "top_takers_by_volume": [],
            "top_takers_by_xg_created": [],
            "top_takers_by_first_shot_xg": [],
        },
        "defensive_takers": {
            "top_takers_by_volume": [],
            "top_takers_by_xg_created": [],
            "top_takers_by_first_shot_xg": [],
        },
        "offensive_shooters": [],
        "defensive_shooters": [],
        "offensive_storylines": [],
        "defensive_storylines": [],
    }


def _default_analysis_scope(target_count: int) -> dict:
    return {
        "target_match_count": int(target_count),
        "current_season_id": None,
        "current_season_played_matches_available": 0,
        "current_season_matches_used": 0,
        "previous_season_id": None,
        "previous_season_matches_used": 0,
        "analysis_matches_used": 0,
        "is_complemented_with_previous_season": False,
        "scope_label": "current_season_only",
    }


def _corner_side_payload(
    summary: dict,
    zones: list[dict],
    takers: dict,
    shooters: list[dict],
    storylines: list[str],
) -> dict:
    return {
        **summary,
        "zones": zones,
        "top_takers_by_volume": takers.get("top_takers_by_volume", []),
        "top_takers_by_xg_created": takers.get("top_takers_by_xg_created", []),
        "top_takers_by_first_shot_xg": takers.get("top_takers_by_first_shot_xg", []),
        "top_shooters_after_corner": shooters,
        "storylines": storylines,
    }


def _corner_plot_meta(plot_name: str, subject_name: str) -> dict:
    if plot_name.endswith("offensive_map"):
        return {
            "title": f"{subject_name} corner delivery map",
            "description": "Goal-zoomed map of every first corner delivery. Each arrow runs from the corner side of origin to the first in-box end location for that delivery.",
            "reading_guide": [
                "Gold arrows are left-side corners and mint arrows are right-side corners.",
                "Filled circles are actual first-delivery end locations, and larger circles mean that specific delivery created more full corner-sequence xG.",
                "A white ring means that delivery's corner sequence produced at least one shot. A red star means it produced at least one goal.",
                "Player callouts point to highlighted representative circles from real deliveries, while the label text totals that player's targeted corners and full corner-sequence xG.",
            ],
            "caveats": [
                "This shows the first delivery end location only, not later pass locations, second-ball locations, or the exact eventual shot location.",
            ],
        }

    if plot_name.endswith("defensive_map"):
        return {
            "title": f"Opposition corner deliveries faced by {subject_name}",
            "description": "Goal-zoomed map of opposition first corner deliveries faced by this defense. Each arrow ends at the first in-box end location for that delivery.",
            "reading_guide": [
                "Arrow colors still separate left-side and right-side deliveries by the attacking team.",
                "Filled circles are actual first-delivery end locations, and larger circles mean those deliveries created more full corner-sequence xG against this defense.",
                "White rings mark deliveries whose sequence produced at least one shot. Red stars mark deliveries whose sequence produced at least one goal.",
                "Player callouts point to highlighted representative circles from real deliveries, while the label text totals the grouped target player and full corner-sequence xG.",
            ],
            "caveats": [
                "It measures first-delivery end location and the later possession outcome, not the exact location of the eventual shot.",
            ],
        }

    if plot_name.endswith("target_map"):
        return {
            "title": f"{subject_name} corner target map",
            "description": "Aggregated view of recurring target players. Each circle sits at that player's average first-delivery target zone across all targeted corners.",
            "reading_guide": [
                "Circle size shows how many corners had their first delivery targeted to that player.",
                "Warmer colors mean those targeted corners produced more total full corner-sequence xG.",
                "A white ring means at least one of those targeted corners produced a shot. A red star means at least one produced a goal.",
                "The callout line points to the player-average circle, and the label gives the grouped player name, targeted-corner count, and total full corner-sequence xG.",
            ],
            "caveats": [
                "Circle location is an average zone, not a single event location. When the pass recipient is missing in the source feed, the plot falls back to the first shooter in that corner sequence.",
            ],
        }

    if plot_name.endswith("danger_end_heatmap"):
        return {
            "title": f"{subject_name} xG-weighted corner danger map",
            "description": "Goal-zoomed hotspot map of first-delivery end locations, with each circular hotspot representing one small delivery zone weighted by the sum of full corner-sequence xG landing there.",
            "reading_guide": [
                "Bigger and warmer hotspot circles are not just busier zones; they are zones whose deliveries create more threat after the corner is taken.",
                "Small pale dots mark actual first-delivery end points. A white ring means that delivery sequence produced at least one shot. A red star means it produced at least one goal.",
                "Use this plot to identify the most dangerous delivery corridor, not simply the busiest one.",
            ],
            "caveats": [
                "Each hotspot circle summarises a small delivery zone rather than a single event, so use it to read danger corridors and clusters rather than exact centimeter-level end locations.",
            ],
        }

    if plot_name.endswith("taker_impact"):
        return {
            "title": f"{subject_name} corner takers ranked by value created",
            "description": "Horizontal bars rank takers by the summed full corner-sequence xG created from the corners they took, with labels focused on volume and any extra recycled-shot uplift when it exists.",
            "reading_guide": [
                "Bar length is total full corner-sequence xG created after that player's corners.",
                "Value labels show total xG, the number of corners taken, and only call out recycled-shot uplift when later shots add threat beyond the first attempt.",
                "Use this with the xG split chart to see whether the total comes entirely from the first shot or whether recycled attacks add extra value.",
            ],
            "caveats": [
                "This credits the taker for the possession outcome of the corner sequence, not only for direct shot assists.",
            ],
        }

    if plot_name.endswith("xg_method_comparison"):
        return {
            "title": f"{subject_name} corner xG split: first shot vs recycled threat",
            "description": "Stacked bars split each taker's total corner-sequence xG into the first-shot part and any extra xG created by later shots in the same corner sequence.",
            "reading_guide": [
                "Mint bars are first-shot xG and gold add-ons are the extra recycled threat created after the first attempt.",
                "If there is no gold add-on, that taker's total corner threat is fully explained by the first shot.",
                "A visible gold segment means recycled attacks, second balls, or later shots are adding threat beyond the first attempt.",
            ],
            "caveats": [
                "This plot changes how the threat is partitioned visually; it does not change the provider xG model underneath the shots themselves.",
            ],
        }

    if plot_name.endswith("shooter_impact"):
        return {
            "title": f"{subject_name} finishers after corners by xG",
            "description": "Horizontal bars rank finishers by the summed full corner-sequence xG from shots they took in corner sequences, with labels focused on shots, goals, and any extra recycled-shot uplift when it exists.",
            "reading_guide": [
                "Bar length is total xG from shots taken across the full corner sequence.",
                "Value labels show total xG plus raw shots and goals, and only call out recycled-shot uplift when later shots add extra threat beyond the first attempt.",
                "This identifies the main finishers after corners, not the corner takers or the first intended receiver.",
            ],
            "caveats": [
                "A player can appear here even if they were not the intended first receiver on the delivery.",
            ],
        }

    return {}


def _corner_plot_ref(
    settings, path, plot_name: str, team_name: str, opponent_name: str | None
):
    ref = build_ref(settings, path)
    if not path:
        return ref

    subject_name = (
        team_name
        if plot_name.startswith("team_")
        else (opponent_name or "Next opponent")
    )
    ref.update(_corner_plot_meta(plot_name, subject_name))
    return ref


def _flatten_plot_paths(plot_groups: dict[str, dict[str, object]]) -> list:
    paths = []
    for group in plot_groups.values():
        paths.extend(group.values())
    return [path for path in paths if path]


def _derive_refresh_webhook_url(settings) -> str | None:
    public_base = (settings.supabase_public_base_url or "").rstrip("/")
    if public_base:
        return f"{public_base}/functions/v1/refresh-reports"

    function_url = (settings.supabase_function_url or "").rstrip("/")
    marker = "/functions/v1/"
    if marker in function_url:
        base = function_url.split(marker, 1)[0]
        return f"{base}{marker}refresh-reports"

    return None


def run_pipeline(settings) -> int:
    generated_at = datetime.now(timezone.utc).isoformat()
    refresh_webhook_url = _derive_refresh_webhook_url(settings)
    settings.reports_dir.mkdir(parents=True, exist_ok=True)

    print("Starting J-Sodra analytics pipeline...")
    if settings.force_refresh_from_api:
        print("Force refresh enabled: bypassing local caches for live API refresh.")
    if not settings.supabase_anon_key:
        print(
            "Warning: SUPABASE_ANON_KEY is not set. If verify JWT is enabled, calls will fail with 401."
        )

    service = DataService(settings)

    print("\nResolving target team...")
    team = service.resolve_target_team()
    if not team:
        print("Could not resolve J-Sodra team id.")
        return 1

    team_id = team.get("wyId")
    team_name = team.get("name", "J-Sodra")
    print(f"Found team: {team_name} (ID: {team_id})")

    team_profile = service.get_team_profile(team_id) or {}
    team_logo_url = extract_logo_url(team_profile)

    print("\nCollecting J-Sodra matches/events...")
    team_data = service.collect_team_dataset(
        team_id,
        team_name,
        settings.max_event_matches,
        preferred_season_id=None,
        filter_to_active_season=settings.filter_to_active_season,
    )
    matches_df = team_data["matches_df"]
    team_season_matches_df = team_data.get("season_matches_df", matches_df)
    team_analysis_matches_df = team_data.get(
        "analysis_matches_df", team_data.get("recent_played_df", pd.DataFrame())
    )
    team_analysis_events_df = team_data.get(
        "analysis_events_df", team_data.get("events_df", pd.DataFrame())
    )
    team_analysis_scope = team_data.get("analysis_scope", {})
    active_season_id = team_data.get("season_id")

    if settings.filter_to_active_season:
        print(f"Season scope for {team_name}: seasonId={active_season_id}")
    if team_analysis_scope.get("is_complemented_with_previous_season"):
        print(
            "Analysis scope complemented with previous season "
            f"for {team_name} (previous seasonId={team_analysis_scope.get('previous_season_id')}, "
            f"added matches={team_analysis_scope.get('previous_season_matches_used')})."
        )

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
        print(
            f"Next opponent source={next_opponent_info.get('source')}: {opponent_name} (ID: {opponent_id})"
        )
    else:
        print("No next opponent could be resolved from fixtures or recent matches.")

    opp_data = {
        "matches_df": pd.DataFrame(),
        "season_matches_df": pd.DataFrame(),
        "events_df": pd.DataFrame(),
        "with_events": [],
        "without_events": [],
        "analysis_matches_df": pd.DataFrame(),
        "analysis_events_df": pd.DataFrame(),
        "analysis_scope": _default_analysis_scope(settings.analysis_event_match_target),
        "season_id": None,
    }
    upcoming_opp = []

    if opponent_id:
        opponent_season_id = next_opponent_info.get("season_id") or active_season_id
        print("\nCollecting next-opponent dataset...")
        opp_data = service.collect_team_dataset(
            opponent_id,
            opponent_name or "Next opponent",
            settings.next_opponent_event_matches,
            preferred_season_id=opponent_season_id,
            filter_to_active_season=settings.filter_to_active_season,
        )
        if settings.filter_to_active_season:
            print(
                f"Season scope for {opponent_name}: seasonId={opp_data.get('season_id')}"
            )
        if opp_data.get("analysis_scope", {}).get(
            "is_complemented_with_previous_season"
        ):
            print(
                "Analysis scope complemented with previous season "
                f"for {opponent_name} (previous seasonId={opp_data.get('analysis_scope', {}).get('previous_season_id')}, "
                f"added matches={opp_data.get('analysis_scope', {}).get('previous_season_matches_used')})."
            )
        upcoming_opp = service.build_upcoming_fixtures(
            opponent_id,
            opponent_name or "Next opponent",
            limit=settings.upcoming_fixture_limit,
            preferred_season_id=opponent_season_id,
        )

    print("\nComputing corner analytics...")
    team_corner = build_corner_analysis(
        team_analysis_events_df, team_id=team_id, team_name=team_name
    )
    opp_analysis_events_df = opp_data.get("analysis_events_df", pd.DataFrame())
    opp_analysis_matches_df = opp_data.get(
        "analysis_matches_df",
        opp_data.get("season_matches_df", opp_data.get("matches_df", pd.DataFrame())),
    )
    opp_corner = _default_corner_analysis()
    if opponent_id and not opp_analysis_events_df.empty:
        opp_corner = build_corner_analysis(
            opp_analysis_events_df,
            team_id=opponent_id,
            team_name=opponent_name or "",
        )

    print("\nComputing summaries, form, and H2H...")
    team_recent_form = build_recent_form(
        team_analysis_matches_df,
        team_name,
        limit=settings.recent_form_matches,
    )
    opp_recent_form = build_recent_form(
        opp_analysis_matches_df,
        opponent_name or "",
        limit=settings.recent_form_matches,
    )

    team_result_summary = summarize_results_from_matches(
        team_season_matches_df, team_name
    )
    opp_result_summary = summarize_results_from_matches(
        opp_data.get("season_matches_df", pd.DataFrame()),
        opponent_name or "",
    )

    head_to_head_overview = build_head_to_head_overview(
        team_id=team_id,
        team_name=team_name,
        opponent_id=opponent_id,
        opponent_name=opponent_name,
        matches_df=matches_df,
        active_season_id=active_season_id,
        fallback_previous_season_id=team_analysis_scope.get("previous_season_id"),
        max_h2h_matches=settings.max_h2h_matches,
        h2h_fallback_to_previous_season=settings.h2h_fallback_to_previous_season,
    )
    head_to_head_last = build_head_to_head_last_meeting(head_to_head_overview)

    print("\nGenerating corner and H2H plots...")
    plot_groups = generate_section_plots(
        settings=settings,
        team_name=team_name,
        team_corner=team_corner,
        opponent_name=opponent_name,
        opponent_corner=opp_corner,
        head_to_head_overview=head_to_head_overview,
    )

    print("\nExporting competition snapshots...")
    competition_paths = [
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
    competition_paths = [path for path in competition_paths if path]

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
        "season_id": opp_data.get("season_id"),
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
        "season_id": opp_data.get("season_id"),
        "season_match_count": int(
            len(
                opp_data.get(
                    "season_matches_df", opp_data.get("matches_df", pd.DataFrame())
                )
            )
        ),
        "attempted_event_matches": len(opp_data.get("selected_match_ids", [])),
        "event_matches_found": len(opp_data.get("with_events", [])),
        "event_matches_missing": len(opp_data.get("without_events", [])),
        "event_missing_match_ids": opp_data.get("without_events", []),
        "results": opp_result_summary,
    }

    season_context = {
        "filter_to_active_season": settings.filter_to_active_season,
        "overview_scope": "current_season_only",
        "team_season_id": active_season_id,
        "team_match_count_in_scope": int(len(team_season_matches_df)),
        "team_event_matches_found_in_scope": len(team_data.get("with_events", [])),
        "team_event_matches_missing_in_scope": len(team_data.get("without_events", [])),
        "next_opponent_season_id": opp_data.get("season_id"),
        "next_opponent_match_count_in_scope": int(
            len(opp_data.get("season_matches_df", pd.DataFrame()))
        ),
        "next_opponent_event_matches_found_in_scope": len(
            opp_data.get("with_events", [])
        ),
        "next_opponent_event_matches_missing_in_scope": len(
            opp_data.get("without_events", [])
        ),
    }

    analysis_context = {
        "enabled_previous_season_complement": False,
        "strategy": "current season only",
        "applies_to": [
            "recent_form",
            "corner_analysis",
            "corner_storylines",
            "corner_plots",
        ],
        "does_not_apply_to": ["overview", "head_to_head"],
        "team": team_analysis_scope,
        "next_opponent": opp_data.get(
            "analysis_scope",
            _default_analysis_scope(settings.analysis_event_match_target),
        ),
    }

    matchup_payload = build_matchup_card(
        next_opponent_info=next_opponent_info,
        team_payload=team_payload,
        opponent_payload=opponent_payload,
    )

    context = PipelineContext(
        settings=settings,
        service=service,
        generated_at=generated_at,
        team=team_payload,
        next_opponent=next_opponent_payload,
        team_data=team_data,
        opponent_data=opp_data,
        matchup=matchup_payload,
        extras={
            "next_opponent_info": next_opponent_info,
            "team_corner": team_corner,
            "opponent_corner": opp_corner,
            "head_to_head_overview": head_to_head_overview,
            "head_to_head_last": head_to_head_last,
            "season_context": season_context,
            "analysis_context": analysis_context,
        },
    )

    extra_section_results = run_registered_sections(context)
    extra_section_files = [
        file_path
        for result in extra_section_results
        for file_path in result.existing_files()
    ]

    corner_data_paths = {
        "team_offensive": write_dataframe(
            settings.report_path("corners", "data", "team_offensive.csv"),
            team_corner.get("offensive_df", pd.DataFrame()),
        ),
        "team_defensive": write_dataframe(
            settings.report_path("corners", "data", "team_defensive.csv"),
            team_corner.get("defensive_df", pd.DataFrame()),
        ),
        "next_opponent_offensive": write_dataframe(
            settings.report_path("corners", "data", "next_opponent_offensive.csv"),
            opp_corner.get("offensive_df", pd.DataFrame()),
        ),
        "next_opponent_defensive": write_dataframe(
            settings.report_path("corners", "data", "next_opponent_defensive.csv"),
            opp_corner.get("defensive_df", pd.DataFrame()),
        ),
    }

    team_entity_path = write_json(
        settings.report_path("entities", "team.json"),
        {"generated_at": generated_at, **team_payload},
    )
    next_opponent_entity_path = write_json(
        settings.report_path("entities", "next_opponent.json"),
        {"generated_at": generated_at, **next_opponent_payload},
    )
    matchup_path = write_json(
        settings.report_path("matchup", "current.json"),
        {"generated_at": generated_at, **matchup_payload},
    )
    team_summary_path = write_json(
        settings.report_path("overview", "team.json"),
        {"generated_at": generated_at, **team_summary},
    )
    next_opponent_summary_path = write_json(
        settings.report_path("overview", "next_opponent.json"),
        {"generated_at": generated_at, **opponent_summary},
    )
    fixtures_path = write_json(
        settings.report_path("fixtures", "upcoming.json"),
        {
            "generated_at": generated_at,
            "team": upcoming_team,
            "next_opponent": upcoming_opp,
        },
    )
    recent_form_path = write_json(
        settings.report_path("forms", "recent_form.json"),
        {
            "generated_at": generated_at,
            "team": team_recent_form,
            "next_opponent": opp_recent_form,
        },
    )

    h2h_plot_refs = {
        name: build_ref(settings, path)
        for name, path in plot_groups.get("head_to_head", {}).items()
    }
    head_to_head_path = write_json(
        settings.report_path("head_to_head", "overview.json"),
        {
            "generated_at": generated_at,
            "overview": head_to_head_overview,
            "last_meeting": head_to_head_last,
            "files": {"plots": h2h_plot_refs},
        },
    )

    corner_plot_refs = {
        name: _corner_plot_ref(settings, path, name, team_name, opponent_name)
        for name, path in plot_groups.get("corners", {}).items()
    }
    corner_data_refs = {
        name: build_ref(settings, path)
        for name, path in corner_data_paths.items()
        if path
    }
    corners_path = write_json(
        settings.report_path("corners", "analysis.json"),
        {
            "generated_at": generated_at,
            "team": {
                "offensive": _corner_side_payload(
                    team_corner.get("offensive_summary", empty_corner_summary()),
                    team_corner.get("offensive_zones", []),
                    team_corner.get("offensive_takers", {}),
                    team_corner.get("offensive_shooters", []),
                    team_corner.get("offensive_storylines", []),
                ),
                "defensive": _corner_side_payload(
                    team_corner.get("defensive_summary", empty_corner_summary()),
                    team_corner.get("defensive_zones", []),
                    team_corner.get("defensive_takers", {}),
                    team_corner.get("defensive_shooters", []),
                    team_corner.get("defensive_storylines", []),
                ),
            },
            "next_opponent": {
                "offensive": _corner_side_payload(
                    opp_corner.get("offensive_summary", empty_corner_summary()),
                    opp_corner.get("offensive_zones", []),
                    opp_corner.get("offensive_takers", {}),
                    opp_corner.get("offensive_shooters", []),
                    opp_corner.get("offensive_storylines", []),
                ),
                "defensive": _corner_side_payload(
                    opp_corner.get("defensive_summary", empty_corner_summary()),
                    opp_corner.get("defensive_zones", []),
                    opp_corner.get("defensive_takers", {}),
                    opp_corner.get("defensive_shooters", []),
                    opp_corner.get("defensive_storylines", []),
                ),
            },
            "storylines": {
                "team_offensive_success_factors": team_corner.get(
                    "offensive_storylines", []
                ),
                "next_opponent_offensive_success_factors": opp_corner.get(
                    "offensive_storylines", []
                ),
            },
            "files": {
                "data": corner_data_refs,
                "plots": corner_plot_refs,
            },
        },
    )

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
        "head_to_head": {"overview": build_ref(settings, head_to_head_path)},
        "corners": {"analysis": build_ref(settings, corners_path)},
        "exports": {
            "competitions": {
                path.stem: build_ref(settings, path) for path in competition_paths
            }
        },
    }

    for result in extra_section_results:
        section_refs[result.name] = result.index_entry

    index_path = write_json(
        settings.report_path("index.json"),
        {
            "generated_at": generated_at,
            "version": 2,
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
                    f"{refresh_webhook_url}?run_id={{run_id}}"
                    if refresh_webhook_url
                    else None
                ),
                "poll_interval_ms": 3000,
                "server_command": "python fetch_football_data.py --force-refresh",
                "frontend_note": "Browser refetch alone only reloads published JSON. To recompute analytics from Wyscout, POST to the refresh webhook, poll the returned run_id until status is succeeded, then refetch reports/index.json with a cache-busting query string.",
            },
            "sections": section_refs,
        },
    )

    print(f"Wrote modular outputs under {settings.reports_dir}")

    upload_candidates = [
        team_entity_path,
        next_opponent_entity_path,
        matchup_path,
        team_summary_path,
        next_opponent_summary_path,
        fixtures_path,
        recent_form_path,
        head_to_head_path,
        corners_path,
        index_path,
        *[path for path in corner_data_paths.values() if path],
        *_flatten_plot_paths(plot_groups),
        *competition_paths,
        *extra_section_files,
    ]

    if settings.upload_to_supabase_storage:
        print("\nUploading modular artifacts to Supabase Storage...")
        deleted = delete_files_from_supabase(
            settings,
            [
                "reports/context/season.json",
                "reports/context/analysis.json",
                "reports/corners/plots/team_offensive_heatmap.png",
                "reports/corners/plots/next_opponent_offensive_heatmap.png",
            ],
        )
        if deleted:
            print(
                f"Removed {len(deleted)} obsolete corner-origin heatmap objects from storage."
            )
        uploaded = upload_files_to_supabase(settings, upload_candidates)
        if uploaded:
            upload_manifest_path = write_json(
                settings.report_path("upload_manifest.json"),
                {"generated_at": generated_at, "files": uploaded},
            )
            print(
                f"Uploaded {len(uploaded)} files and wrote manifest -> {upload_manifest_path.relative_to(settings.output_dir)}"
            )
    else:
        print(
            "\nUpload disabled. Set UPLOAD_TO_SUPABASE_STORAGE=1 to push reports to the bucket."
        )

    print("\nDone.")
    return 0
