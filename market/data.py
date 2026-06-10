from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from pipeline.analytics import get_recent_played_matches
from pipeline.common import extract_logo_url, extract_matches, team_event_mask
from pipeline.data_service import DataService
from pipeline.settings import Settings, load_settings


@dataclass(frozen=True)
class MarketingDataset:
    settings: Settings
    service: DataService
    team_id: int
    team_name: str
    competition_label: str
    season_id: int | None
    season_label: str
    season_year: int | None
    team_logo_url: str | None
    matches_df: pd.DataFrame
    played_matches_df: pd.DataFrame
    events_df: pd.DataFrame
    team_events_df: pd.DataFrame
    latest_match_id: int | None
    latest_match_label: str | None
    output_dir: Path


def _first_nonblank(frame: pd.DataFrame, columns: list[str]) -> str | None:
    if frame.empty:
        return None
    for column in columns:
        if column not in frame.columns:
            continue
        values = frame[column].dropna().astype(str).str.strip()
        values = values[values.ne("")]
        if not values.empty:
            return values.iloc[0]
    return None


def _derive_season_label(matches_df: pd.DataFrame, season_id: int | None) -> str:
    explicit = _first_nonblank(
        matches_df,
        ["season.name", "seasonName", "season.displayName", "season.shortName"],
    )
    if explicit:
        return explicit

    for column in ("dateutc", "date"):
        if column not in matches_df.columns:
            continue
        dates = pd.to_datetime(matches_df[column], errors="coerce", utc=True).dropna()
        if dates.empty:
            continue
        years = sorted({int(value.year) for value in dates})
        if not years:
            continue
        if len(years) == 1:
            return str(years[0])
        return f"{years[0]}/{str(years[-1])[-2:]}"

    if season_id is not None:
        return str(season_id)
    return "Current season"


def _match_datetime_series(matches_df: pd.DataFrame) -> pd.Series:
    if matches_df.empty:
        return pd.Series(dtype="datetime64[ns, UTC]")
    for column in ("dateutc", "date"):
        if column in matches_df.columns:
            return pd.to_datetime(matches_df[column], errors="coerce", utc=True)
    return pd.Series(pd.NaT, index=matches_df.index, dtype="datetime64[ns, UTC]")


def _derive_primary_year(matches_df: pd.DataFrame) -> int | None:
    dates = _match_datetime_series(matches_df).dropna()
    if dates.empty:
        return None
    years = dates.dt.year.astype(int)
    return int(years.mode().iloc[0])


def _derive_competition_label(service: DataService, matches_df: pd.DataFrame) -> str:
    if not matches_df.empty and "competitionId" in matches_df.columns:
        competition_ids = pd.to_numeric(matches_df["competitionId"], errors="coerce").dropna()
        if not competition_ids.empty:
            competition_id = int(competition_ids.iloc[0])
            detail = service.fetch_api(f"/competitions/{competition_id}")
            if isinstance(detail, dict):
                for key in ("displayName", "officialName", "name", "shortName"):
                    value = detail.get(key)
                    if isinstance(value, str) and value.strip():
                        return value.strip()

    explicit = _first_nonblank(
        matches_df,
        [
            "competition.name",
            "competitionName",
            "competition.displayName",
            "competition.shortName",
        ],
    )
    return explicit or "League campaign"


def _resolve_team(
    service: DataService,
    explicit_team_id: int | None,
    explicit_team_name: str | None,
) -> tuple[int, str]:
    if explicit_team_id is not None:
        team_name = explicit_team_name or service.resolve_team_name_by_id(explicit_team_id)
        if team_name:
            return int(explicit_team_id), str(team_name)
        return int(explicit_team_id), f"Team {int(explicit_team_id)}"

    if explicit_team_name:
        result = service.search_team_by_name(explicit_team_name)
        if result.get("id") is not None:
            return int(result["id"]), str(result.get("name") or explicit_team_name)

    target = service.resolve_target_team()
    if not isinstance(target, dict) or target.get("wyId") is None:
        raise RuntimeError(
            "Could not resolve a target team from the Wyscout proxy. Check TEAM_QUERY or pass --team-id."
        )

    return int(target["wyId"]), str(target.get("name") or service.settings.team_query)


def _load_matches(service: DataService, team_id: int) -> pd.DataFrame:
    payload = service.fetch_api(f"/teams/{team_id}/matches")
    matches = extract_matches(payload)
    if not matches:
        raise RuntimeError(
            f"No matches were returned for team {team_id}. Check your Supabase edge-function credentials."
        )
    return service.normalize_matches_df(pd.json_normalize(matches))


def load_marketing_dataset(
    team_id: int | None = None,
    team_name: str | None = None,
    season_id: int | None = None,
    max_matches: int | None = None,
    output_dir: str | Path | None = None,
    force_refresh: bool = False,
) -> MarketingDataset:
    settings = load_settings(force_refresh=force_refresh)
    service = DataService(settings)

    resolved_team_id, resolved_team_name = _resolve_team(service, team_id, team_name)
    team_profile = service.get_team_profile(resolved_team_id)
    matches_df = _load_matches(service, resolved_team_id)
    active_season_id = service.detect_active_season_id(matches_df, season_id)
    season_matches_df = service.filter_matches_to_season(matches_df, active_season_id)
    if season_id is None:
        current_year = datetime.now(timezone.utc).year
        season_dates = _match_datetime_series(season_matches_df)
        current_year_matches_df = season_matches_df[
            season_dates.dt.year.eq(current_year).fillna(False)
        ].copy()
        if not current_year_matches_df.empty:
            season_matches_df = current_year_matches_df

    played_matches_df = get_recent_played_matches(season_matches_df, limit=max_matches)

    if played_matches_df.empty:
        raise RuntimeError(
            f"No played matches were found for {resolved_team_name} in the requested season."
        )

    match_ids = [
        int(value)
        for value in played_matches_df.get("matchId", pd.Series(dtype=float))
        .dropna()
        .astype(int)
        .tolist()
    ]
    if not match_ids:
        raise RuntimeError(
            f"No match identifiers were available for {resolved_team_name} after filtering to played matches."
        )

    event_rows, _, _ = service.fetch_events_for_match_ids(match_ids)
    events_df = pd.json_normalize(event_rows) if event_rows else pd.DataFrame()
    team_events_df = (
        events_df[team_event_mask(events_df, resolved_team_id, resolved_team_name)].copy()
        if not events_df.empty
        else pd.DataFrame()
    )

    if team_events_df.empty:
        raise RuntimeError(
            f"Event data loaded for {len(match_ids)} matches but no events could be scoped to {resolved_team_name}."
        )

    latest_match_row = played_matches_df.iloc[0].to_dict()
    latest_match_id = latest_match_row.get("matchId")
    if latest_match_id is not None:
        latest_match_id = int(latest_match_id)

    destination = Path(output_dir or settings.output_dir / "market" / "output").resolve()
    destination.mkdir(parents=True, exist_ok=True)

    return MarketingDataset(
        settings=settings,
        service=service,
        team_id=resolved_team_id,
        team_name=resolved_team_name,
        competition_label=_derive_competition_label(service, season_matches_df),
        season_id=active_season_id,
        season_label=_derive_season_label(season_matches_df, active_season_id),
        season_year=_derive_primary_year(season_matches_df),
        team_logo_url=extract_logo_url(team_profile),
        matches_df=season_matches_df,
        played_matches_df=played_matches_df,
        events_df=events_df,
        team_events_df=team_events_df,
        latest_match_id=latest_match_id,
        latest_match_label=str(latest_match_row.get("label") or "").strip() or None,
        output_dir=destination,
    )