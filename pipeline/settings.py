"""Application settings for the J-Södra analytics pipeline.

This module should only contain environment parsing, defaults, report path helpers,
and shared visual style. Do not add section-specific logic here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(override=True)
except Exception:
    # python-dotenv is optional in CI if environment variables are injected directly.
    pass


def _env_bool(name: str, default: str | bool) -> bool:
    return str(os.getenv(name, str(default))).strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return int(default)
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"Environment variable {name} must be an integer, got {raw!r}") from exc


PLOT_STYLE = {
    "bg": "#002418",
    "line": "#f5f0da",
    "accent": "#d4af37",
    "accent_2": "#6fcf97",
    "muted": "#8ad6b4",
    "danger": "#f07167",
    "text": "#f5f0da",
}


@dataclass(frozen=True, slots=True)
class Settings:
    supabase_function_url: str
    supabase_anon_key: str | None
    http_timeout_seconds: int

    team_query: str
    target_team_keyword: str

    recent_match_limit: int
    max_event_matches: int
    next_opponent_event_matches: int
    recent_form_matches: int
    upcoming_fixture_limit: int
    max_h2h_matches: int
    analysis_event_match_target: int
    max_previous_season_matches: int

    enable_previous_season_complement: bool
    h2h_fallback_to_previous_season: bool
    filter_to_active_season: bool

    output_dir: Path
    reports_dir: Path

    upload_to_supabase_storage: bool
    supabase_s3_endpoint: str
    supabase_s3_bucket: str
    supabase_s3_access_key: str | None
    supabase_s3_secret_key: str | None
    supabase_s3_prefix: str
    supabase_public_base_url: str

    enable_incremental_event_fetch: bool
    event_cache_recheck_missing_hours: int
    event_cache_dir: Path

    enable_incremental_competition_fetch: bool
    competition_cache_ttl_hours: int
    competition_cache_dir: Path

    force_refresh_from_api: bool
    plot_style: dict[str, str]

    def report_path(self, *parts: str) -> Path:
        return self.reports_dir.joinpath(*parts)

    def with_force_refresh(self, enabled: bool) -> "Settings":
        return replace(self, force_refresh_from_api=enabled)


def load_settings(force_refresh: bool = False) -> Settings:
    output_dir = Path(os.getenv("OUTPUT_DIR", ".")).resolve()
    reports_dir = output_dir / os.getenv("REPORTS_DIR", "reports")

    max_event_matches = _env_int("MAX_EVENT_MATCHES", 100)
    analysis_event_match_target = _env_int("ANALYSIS_EVENT_MATCH_TARGET", max_event_matches)
    env_force_refresh = _env_bool("FORCE_REFRESH_FROM_API", "0")

    return Settings(
        supabase_function_url=os.getenv(
            "SUPABASE_FUNCTION_URL",
            "https://ytzuftamjgafzgyogpke.supabase.co/functions/v1/wyscout-proxy",
        ),
        supabase_anon_key=os.getenv("SUPABASE_ANON_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY"),
        http_timeout_seconds=_env_int("HTTP_TIMEOUT_SECONDS", 30),
        team_query=os.getenv("TEAM_QUERY", "Jonkopings"),
        target_team_keyword=os.getenv("TARGET_TEAM_KEYWORD", "jonkopings sodra"),
        recent_match_limit=_env_int("RECENT_MATCH_LIMIT", 100),
        max_event_matches=max_event_matches,
        next_opponent_event_matches=_env_int("NEXT_OPPONENT_EVENT_MATCHES", 100),
        recent_form_matches=_env_int("RECENT_FORM_MATCHES", 5),
        upcoming_fixture_limit=_env_int("UPCOMING_FIXTURE_LIMIT", 5),
        max_h2h_matches=_env_int("MAX_H2H_MATCHES", 5),
        analysis_event_match_target=analysis_event_match_target,
        max_previous_season_matches=_env_int("MAX_PREVIOUS_SEASON_MATCHES", analysis_event_match_target),
        enable_previous_season_complement=_env_bool("ENABLE_PREVIOUS_SEASON_COMPLEMENT", "0"),
        h2h_fallback_to_previous_season=_env_bool("H2H_FALLBACK_TO_PREVIOUS_SEASON", "1"),
        filter_to_active_season=_env_bool("FILTER_TO_ACTIVE_SEASON", "1"),
        output_dir=output_dir,
        reports_dir=reports_dir,
        upload_to_supabase_storage=_env_bool("UPLOAD_TO_SUPABASE_STORAGE", "0"),
        supabase_s3_endpoint=os.getenv(
            "SUPABASE_S3_ENDPOINT",
            "https://ytzuftamjgafzgyogpke.storage.supabase.co/storage/v1/s3",
        ),
        supabase_s3_bucket=os.getenv("SUPABASE_S3_BUCKET", ""),
        supabase_s3_access_key=os.getenv("SUPABASE_S3_ACCESS_KEY"),
        supabase_s3_secret_key=os.getenv("SUPABASE_S3_SECRET_KEY"),
        supabase_s3_prefix=os.getenv("SUPABASE_S3_PREFIX", ""),
        supabase_public_base_url=os.getenv("SUPABASE_PUBLIC_BASE_URL", ""),
        enable_incremental_event_fetch=_env_bool("ENABLE_INCREMENTAL_EVENT_FETCH", "1"),
        event_cache_recheck_missing_hours=max(0, _env_int("EVENT_CACHE_RECHECK_MISSING_HOURS", 24)),
        event_cache_dir=output_dir / os.getenv("EVENT_CACHE_DIR", "cache/events"),
        enable_incremental_competition_fetch=_env_bool("ENABLE_INCREMENTAL_COMPETITION_FETCH", "1"),
        competition_cache_ttl_hours=max(0, _env_int("COMPETITION_CACHE_TTL_HOURS", 24)),
        competition_cache_dir=output_dir / os.getenv("COMPETITION_CACHE_DIR", "cache/competitions"),
        force_refresh_from_api=bool(force_refresh or env_force_refresh),
        plot_style=dict(PLOT_STYLE),
    )
