from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

from .analytics import get_recent_played_matches, parse_match_label
from .common import (
    extract_list,
    extract_matches,
    jsonable,
    match_id,
    match_sort_column,
    normalize_text,
    parse_iso_datetime,
    to_iso,
)
from .settings import Settings


class DataService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.team_cache: dict[int, dict] = {}

    def fetch_api(self, endpoint: str, params: dict | None = None):
        query = {"endpoint": endpoint}
        if params:
            query.update(params)

        headers = {}
        if self.settings.supabase_anon_key:
            headers["Authorization"] = f"Bearer {self.settings.supabase_anon_key}"
            headers["apikey"] = self.settings.supabase_anon_key

        try:
            response = requests.get(
                self.settings.supabase_function_url,
                params=query,
                headers=headers,
                timeout=self.settings.http_timeout_seconds,
            )
        except requests.RequestException as exc:
            print(f"Request failed for {endpoint}: {exc}")
            return None

        if response.status_code != 200:
            print(
                f"Error {response.status_code} fetching {endpoint}: {response.text[:500]}"
            )
            return None

        try:
            return response.json()
        except ValueError:
            print(f"Non-JSON response for {endpoint}: {response.text[:200]}")
            return None

    def resolve_target_team(self):
        payload = self.fetch_api(
            "/search", {"query": self.settings.team_query, "objType": "team"}
        )
        candidates = extract_list(payload, "teams")
        if not candidates and isinstance(payload, list):
            candidates = payload
        if not candidates:
            return None

        query = normalize_text(self.settings.team_query)
        keyword = normalize_text(self.settings.target_team_keyword)

        def score(team):
            values = [
                normalize_text(team.get("name")),
                normalize_text(team.get("officialName")),
                normalize_text(team.get("shortName")),
            ]
            bucket = " ".join(value for value in values if value)
            points = 0
            if keyword and keyword in bucket:
                points += 100
            if query and query in bucket:
                points += 25
            if query and values[0].startswith(query):
                points += 5
            return points

        return sorted(candidates, key=score, reverse=True)[0]

    def search_team_by_name(self, name: str | None) -> dict:
        if not name:
            return {"id": None, "name": None}

        payload = self.fetch_api("/search", {"query": name, "objType": "team"})
        candidates = extract_list(payload, "teams")
        if not candidates and isinstance(payload, list):
            candidates = payload
        if not candidates:
            return {"id": None, "name": name}

        expected = normalize_text(name)

        def score(team):
            values = [
                normalize_text(team.get("name")),
                normalize_text(team.get("officialName")),
            ]
            bucket = " ".join(value for value in values if value)
            points = 0
            if expected == values[0]:
                points += 100
            if expected and expected in bucket:
                points += 25
            if values[0].startswith(expected):
                points += 5
            return points

        best = sorted(candidates, key=score, reverse=True)[0]
        return {"id": best.get("wyId"), "name": best.get("name")}

    def get_team_profile(self, team_id):
        if team_id is None:
            return None
        try:
            team_id = int(team_id)
        except Exception:
            return None

        if team_id in self.team_cache:
            return self.team_cache[team_id]

        profile = self.fetch_api(f"/teams/{team_id}")
        if isinstance(profile, dict):
            self.team_cache[team_id] = profile
            return profile
        return None

    def resolve_team_name_by_id(self, team_id):
        profile = self.get_team_profile(team_id)
        if isinstance(profile, dict):
            return profile.get("name")
        return None

    def get_match_detail(self, match_id):
        if match_id is None:
            return None
        return self.fetch_api(f"/matches/{int(match_id)}", {"useSides": 1})

    def normalize_matches_df(self, matches_df: pd.DataFrame) -> pd.DataFrame:
        if matches_df.empty:
            return pd.DataFrame()

        df = matches_df.copy()
        if "wyId" in df.columns and "matchId" not in df.columns:
            df["matchId"] = df["wyId"]
        if "matchId" in df.columns:
            df["matchId"] = pd.to_numeric(df["matchId"], errors="coerce")
        if "seasonId" in df.columns:
            df["seasonId"] = pd.to_numeric(df["seasonId"], errors="coerce")

        for column in ("dateutc", "date"):
            if column in df.columns:
                df[column] = pd.to_datetime(df[column], errors="coerce", utc=True)

        return df

    def detect_active_season_id(
        self, matches_df: pd.DataFrame, preferred_season_id=None
    ):
        if matches_df.empty or "seasonId" not in matches_df.columns:
            return preferred_season_id

        df = matches_df.dropna(subset=["seasonId"]).copy()
        if df.empty:
            return preferred_season_id

        if (
            preferred_season_id is not None
            and df["seasonId"].eq(float(preferred_season_id)).any()
        ):
            return int(preferred_season_id)

        candidate_df = get_recent_played_matches(df, limit=None)
        if candidate_df.empty:
            candidate_df = df
        sort_col = match_sort_column(candidate_df)
        if sort_col:
            candidate_df = candidate_df.sort_values(
                by=sort_col,
                ascending=False,
                na_position="last",
            )
        return int(candidate_df.iloc[0]["seasonId"])

    def filter_matches_to_season(self, matches_df: pd.DataFrame, season_id):
        if (
            matches_df.empty
            or season_id is None
            or "seasonId" not in matches_df.columns
        ):
            return matches_df.copy()

        filtered = matches_df[matches_df["seasonId"].eq(float(season_id))].copy()
        sort_col = match_sort_column(filtered)
        if sort_col and not filtered.empty:
            filtered = filtered.sort_values(
                by=sort_col,
                ascending=False,
                na_position="last",
            )
        return filtered

    def detect_previous_season_id(self, matches_df: pd.DataFrame, active_season_id):
        if (
            matches_df.empty
            or active_season_id is None
            or "seasonId" not in matches_df.columns
        ):
            return None

        candidate_df = get_recent_played_matches(matches_df, limit=None)
        if candidate_df.empty:
            candidate_df = matches_df.copy()
        candidate_df = candidate_df.dropna(subset=["seasonId"])
        sort_col = match_sort_column(candidate_df)
        if sort_col and not candidate_df.empty:
            candidate_df = candidate_df.sort_values(
                by=sort_col,
                ascending=False,
                na_position="last",
            )
        previous_df = candidate_df[
            ~candidate_df["seasonId"].eq(float(active_season_id))
        ]
        if previous_df.empty:
            return None
        return int(previous_df.iloc[0]["seasonId"])

    def build_analysis_match_scope(
        self,
        matches_df: pd.DataFrame,
        active_season_id,
        event_match_limit: int,
        filter_to_active_season: bool,
    ) -> dict:
        target_match_count = max(
            1,
            int(
                self.settings.analysis_event_match_target
                if self.settings.analysis_event_match_target > 0
                else event_match_limit
            ),
        )
        empty_meta = {
            "target_match_count": target_match_count,
            "current_season_id": jsonable(active_season_id),
            "current_season_played_matches_available": 0,
            "current_season_matches_used": 0,
            "previous_season_id": None,
            "previous_season_matches_used": 0,
            "analysis_matches_used": 0,
            "is_complemented_with_previous_season": False,
            "scope_label": "current_season_only",
        }
        if matches_df.empty:
            return {
                "matches_df": pd.DataFrame(),
                "selected_match_ids": [],
                "meta": empty_meta,
            }

        current_scope_df = (
            self.filter_matches_to_season(matches_df, active_season_id)
            if filter_to_active_season
            else matches_df.copy()
        )
        current_played_df = get_recent_played_matches(
            current_scope_df,
            limit=max(self.settings.recent_match_limit, target_match_count * 4),
        )
        current_used_df = current_played_df.head(target_match_count)

        analysis_matches_df = current_used_df.copy()
        sort_col = match_sort_column(analysis_matches_df)
        if sort_col and not analysis_matches_df.empty:
            analysis_matches_df = analysis_matches_df.sort_values(
                by=sort_col,
                ascending=False,
                na_position="last",
            )
        analysis_matches_df = analysis_matches_df.head(target_match_count)
        selected_match_ids = [
            int(value)
            for value in analysis_matches_df.get("matchId", pd.Series(dtype=float))
            .dropna()
            .astype(int)
            .tolist()
        ]
        return {
            "matches_df": analysis_matches_df,
            "selected_match_ids": selected_match_ids,
            "meta": {
                **empty_meta,
                "current_season_played_matches_available": int(len(current_played_df)),
                "current_season_matches_used": int(len(current_used_df)),
                "analysis_matches_used": int(len(analysis_matches_df)),
                "scope_label": "current_season_only",
            },
        }

    def _extract_side_name(self, side_payload) -> str | None:
        if not isinstance(side_payload, dict):
            return None
        for key in ("name", "teamName"):
            if side_payload.get(key):
                return side_payload.get(key)
        nested = side_payload.get("team")
        if isinstance(nested, dict) and nested.get("name"):
            return nested.get("name")
        return None

    def extract_team_ids_from_match_detail(
        self, match_detail
    ) -> tuple[int | None, int | None]:
        if not isinstance(match_detail, dict):
            return None, None
        teams_data = match_detail.get("teamsData")
        if not isinstance(teams_data, dict):
            return None, None

        home = (
            teams_data.get("home") if isinstance(teams_data.get("home"), dict) else {}
        )
        away = (
            teams_data.get("away") if isinstance(teams_data.get("away"), dict) else {}
        )
        home_id = home.get("teamId") or home.get("id")
        away_id = away.get("teamId") or away.get("id")
        try:
            home_id = int(home_id) if home_id is not None else None
        except Exception:
            home_id = None
        try:
            away_id = int(away_id) if away_id is not None else None
        except Exception:
            away_id = None
        return home_id, away_id

    def extract_opponent(self, match_detail, target_team_id, target_team_name: str):
        target_norm = normalize_text(target_team_name)
        home_id, away_id = self.extract_team_ids_from_match_detail(match_detail)

        teams_data = (
            match_detail.get("teamsData") if isinstance(match_detail, dict) else None
        )
        home = teams_data.get("home") if isinstance(teams_data, dict) else {}
        away = teams_data.get("away") if isinstance(teams_data, dict) else {}
        home_name = self._extract_side_name(home)
        away_name = self._extract_side_name(away)

        if target_team_id and home_id and away_id:
            if int(target_team_id) == home_id:
                return {
                    "opponent_id": away_id,
                    "opponent_name": away_name or self.resolve_team_name_by_id(away_id),
                    "target_side": "home",
                }
            if int(target_team_id) == away_id:
                return {
                    "opponent_id": home_id,
                    "opponent_name": home_name or self.resolve_team_name_by_id(home_id),
                    "target_side": "away",
                }

        if home_name and away_name and target_norm:
            if normalize_text(home_name) == target_norm:
                return {
                    "opponent_id": away_id,
                    "opponent_name": away_name,
                    "target_side": "home",
                }
            if normalize_text(away_name) == target_norm:
                return {
                    "opponent_id": home_id,
                    "opponent_name": home_name,
                    "target_side": "away",
                }

        parsed = parse_match_label(
            match_detail.get("label") if isinstance(match_detail, dict) else None
        )
        if parsed:
            parsed_home = parsed.get("home_name")
            parsed_away = parsed.get("away_name")
            if target_norm and normalize_text(parsed_home) == target_norm:
                return {
                    "opponent_id": away_id,
                    "opponent_name": away_name or parsed_away,
                    "target_side": "home",
                }
            if target_norm and normalize_text(parsed_away) == target_norm:
                return {
                    "opponent_id": home_id,
                    "opponent_name": home_name or parsed_home,
                    "target_side": "away",
                }

        return {"opponent_id": None, "opponent_name": None, "target_side": None}

    def build_upcoming_fixtures(
        self,
        team_id,
        team_name: str,
        limit: int,
        preferred_season_id=None,
    ) -> list[dict]:
        payload = self.fetch_api(f"/teams/{team_id}/fixtures")
        fixtures = extract_matches(payload)
        if not fixtures:
            return []

        df = self.normalize_matches_df(pd.json_normalize(fixtures))
        if df.empty:
            return []

        if preferred_season_id is not None and "seasonId" in df.columns:
            season_df = self.filter_matches_to_season(df, preferred_season_id)
            if not season_df.empty:
                df = season_df

        if "status" in df.columns:
            status = df["status"].astype(str).str.lower()
            played_statuses = {
                "played",
                "complete",
                "completed",
                "finished",
                "match ended",
            }
            future_df = df[~status.isin(played_statuses)]
            if not future_df.empty:
                df = future_df

        sort_col = match_sort_column(df)
        if sort_col:
            df = df.sort_values(by=sort_col, ascending=True, na_position="last")

        rows = []
        for row in df.head(limit).to_dict(orient="records"):
            current_match_id = match_id(row)
            match_detail = (
                self.get_match_detail(current_match_id) if current_match_id else row
            )
            opponent = self.extract_opponent(match_detail or row, team_id, team_name)
            rows.append(
                {
                    "match_id": current_match_id,
                    "dateutc": to_iso(row.get("dateutc") or row.get("date")),
                    "status": row.get("status"),
                    "season_id": jsonable(row.get("seasonId")),
                    "opponent_id": opponent.get("opponent_id"),
                    "opponent_name": opponent.get("opponent_name"),
                    "target_side": opponent.get("target_side"),
                    "label": row.get("label") or (match_detail or {}).get("label"),
                }
            )
        return rows

    def determine_next_opponent(
        self,
        team_id,
        team_name: str,
        matches_df: pd.DataFrame,
        preferred_season_id=None,
    ) -> dict:
        upcoming = self.build_upcoming_fixtures(
            team_id,
            team_name,
            limit=self.settings.upcoming_fixture_limit,
            preferred_season_id=preferred_season_id,
        )
        for fixture in upcoming:
            if fixture.get("opponent_name") or fixture.get("opponent_id"):
                return {"source": "fixtures", **fixture, "upcoming_fixtures": upcoming}

        latest_played = get_recent_played_matches(matches_df, limit=1)
        if latest_played.empty:
            return {
                "source": "unavailable",
                "match_id": None,
                "dateutc": None,
                "status": None,
                "season_id": jsonable(preferred_season_id),
                "opponent_id": None,
                "opponent_name": None,
                "target_side": None,
                "label": None,
                "upcoming_fixtures": upcoming,
            }

        row = latest_played.to_dict(orient="records")[0]
        current_match_id = match_id(row)
        match_detail = (
            self.get_match_detail(current_match_id) if current_match_id else row
        )
        opponent = self.extract_opponent(match_detail or row, team_id, team_name)
        return {
            "source": "latest_played_fallback",
            "match_id": current_match_id,
            "dateutc": to_iso(row.get("dateutc") or row.get("date")),
            "status": row.get("status"),
            "season_id": jsonable(row.get("seasonId")),
            "opponent_id": opponent.get("opponent_id"),
            "opponent_name": opponent.get("opponent_name"),
            "target_side": opponent.get("target_side"),
            "label": row.get("label") or (match_detail or {}).get("label"),
            "upcoming_fixtures": upcoming,
        }

    def _event_cache_file_path(self, match_id) -> Path:
        return self.settings.event_cache_dir / f"match_{int(match_id)}.json"

    def _competition_cache_file_path(self, competition_id) -> Path:
        return (
            self.settings.competition_cache_dir
            / f"competition_{int(competition_id)}_matches.json"
        )

    def _use_event_cache(self) -> bool:
        return (
            self.settings.enable_incremental_event_fetch
            and not self.settings.force_refresh_from_api
        )

    def _use_competition_cache(self) -> bool:
        return (
            self.settings.enable_incremental_competition_fetch
            and not self.settings.force_refresh_from_api
        )

    def _competition_players_cache_file_path(self, competition_id) -> Path:
        return (
            self.settings.player_cache_dir
            / f"competition_{int(competition_id)}_players.json"
        )

    def _player_advanced_stats_cache_file_path(self, player_id, competition_id) -> Path:
        return self.settings.player_cache_dir / (
            f"player_{int(player_id)}_advancedstats_comp{int(competition_id)}.json"
        )

    def _position_stat_benchmarks_cache_file_path(self, competition_id) -> Path:
        return (
            self.settings.player_cache_dir
            / f"competition_{int(competition_id)}_position_benchmarks.json"
        )

    def _use_player_cache(self) -> bool:
        return (
            self.settings.enable_incremental_player_fetch
            and not self.settings.force_refresh_from_api
        )

    def _load_cached_match_events(self, match_id):
        if not self._use_event_cache():
            return None

        cache_path = self._event_cache_file_path(match_id)
        if not cache_path.exists():
            return None

        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            return None

        events = payload.get("events")
        if not isinstance(events, list):
            return None
        if payload.get("has_events"):
            return events

        fetched_at = parse_iso_datetime(payload.get("fetched_at"))
        if fetched_at is None:
            return None
        age = datetime.now(timezone.utc) - fetched_at
        if age < timedelta(hours=self.settings.event_cache_recheck_missing_hours):
            return []
        return None

    def _write_cached_match_events(self, match_id, events: list):
        if not self.settings.enable_incremental_event_fetch:
            return

        try:
            self.settings.event_cache_dir.mkdir(parents=True, exist_ok=True)
            payload = {
                "match_id": int(match_id),
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "has_events": bool(events),
                "events": events,
            }
            self._event_cache_file_path(match_id).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            print(f"Event cache write failed for match {match_id}: {exc}")

    def _load_cached_competition_matches(self, competition_id):
        if not self._use_competition_cache():
            return None

        cache_path = self._competition_cache_file_path(competition_id)
        if not cache_path.exists():
            return None

        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            return None

        matches = payload.get("matches")
        if not isinstance(matches, list):
            return None

        fetched_at = parse_iso_datetime(payload.get("fetched_at"))
        if fetched_at is None:
            return None
        age = datetime.now(timezone.utc) - fetched_at
        if age > timedelta(hours=self.settings.competition_cache_ttl_hours):
            return None
        return matches

    def _write_cached_competition_matches(
        self, competition_id, competition_name: str, matches: list
    ):
        if not self.settings.enable_incremental_competition_fetch:
            return

        try:
            self.settings.competition_cache_dir.mkdir(parents=True, exist_ok=True)
            payload = {
                "competition_id": int(competition_id),
                "competition_name": competition_name,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "matches": matches,
            }
            self._competition_cache_file_path(competition_id).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            print(f"Competition cache write failed for {competition_name}: {exc}")

    def fetch_events_for_match_ids(
        self, match_ids: list[int]
    ) -> tuple[list, list[int], list[int]]:
        all_events = []
        with_events: list[int] = []
        without_events: list[int] = []
        cache_hits = 0
        api_requests = 0

        ordered_ids = []
        seen_ids = set()
        for current_match_id in match_ids:
            if current_match_id in seen_ids:
                continue
            seen_ids.add(current_match_id)
            ordered_ids.append(current_match_id)

        for current_match_id in ordered_ids:
            cached = self._load_cached_match_events(current_match_id)
            if cached is not None:
                cache_hits += 1
                if cached:
                    all_events.extend(cached)
                    with_events.append(current_match_id)
                else:
                    without_events.append(current_match_id)
                continue

            payload = self.fetch_api(f"/matches/{current_match_id}/events")
            events = extract_list(payload, "events")
            if not events and isinstance(payload, list):
                events = payload

            if events:
                all_events.extend(events)
                with_events.append(current_match_id)
            else:
                without_events.append(current_match_id)

            api_requests += 1
            self._write_cached_match_events(current_match_id, events or [])

        if self.settings.enable_incremental_event_fetch and ordered_ids:
            print(
                f"Event fetch cache: {cache_hits}/{len(ordered_ids)} cache hits, {api_requests} API calls."
            )

        return all_events, with_events, without_events

    def collect_team_dataset(
        self,
        team_id,
        team_name: str,
        event_match_limit: int,
        preferred_season_id=None,
        filter_to_active_season: bool | None = None,
    ) -> dict:
        if filter_to_active_season is None:
            filter_to_active_season = self.settings.filter_to_active_season

        payload = self.fetch_api(f"/teams/{team_id}/matches")
        matches = extract_matches(payload)
        if not matches:
            target_match_count = max(
                1,
                int(
                    self.settings.analysis_event_match_target
                    if self.settings.analysis_event_match_target > 0
                    else event_match_limit
                ),
            )
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
                    "target_match_count": target_match_count,
                    "current_season_id": None,
                    "current_season_played_matches_available": 0,
                    "current_season_matches_used": 0,
                    "previous_season_id": None,
                    "previous_season_matches_used": 0,
                    "analysis_matches_used": 0,
                    "is_complemented_with_previous_season": False,
                    "scope_label": "current_season_only",
                },
                "season_id": preferred_season_id,
            }

        matches_df = self.normalize_matches_df(pd.json_normalize(matches))
        season_id = self.detect_active_season_id(matches_df, preferred_season_id)
        season_matches_df = (
            self.filter_matches_to_season(matches_df, season_id)
            if filter_to_active_season
            else matches_df.copy()
        )
        recent_played_df = get_recent_played_matches(
            season_matches_df,
            limit=self.settings.recent_match_limit,
        )

        selected_df = recent_played_df.head(event_match_limit)
        selected_match_ids = [
            int(value)
            for value in selected_df.get("matchId", pd.Series(dtype=float))
            .dropna()
            .astype(int)
            .tolist()
        ]
        event_rows, with_events, without_events = self.fetch_events_for_match_ids(
            selected_match_ids
        )
        events_df = pd.json_normalize(event_rows) if event_rows else pd.DataFrame()

        analysis_scope = self.build_analysis_match_scope(
            matches_df=matches_df,
            active_season_id=season_id,
            event_match_limit=event_match_limit,
            filter_to_active_season=filter_to_active_season,
        )
        analysis_matches_df = analysis_scope.get("matches_df", pd.DataFrame())
        analysis_selected_match_ids = analysis_scope.get("selected_match_ids", [])

        analysis_events_df = events_df.copy()
        analysis_with_events = list(with_events)
        analysis_without_events = list(without_events)
        if analysis_selected_match_ids != selected_match_ids:
            analysis_rows, analysis_with_events, analysis_without_events = (
                self.fetch_events_for_match_ids(analysis_selected_match_ids)
            )
            analysis_events_df = (
                pd.json_normalize(analysis_rows) if analysis_rows else pd.DataFrame()
            )

        return {
            "matches_df": matches_df,
            "season_matches_df": season_matches_df,
            "recent_played_df": recent_played_df,
            "selected_match_ids": selected_match_ids,
            "events_df": events_df,
            "with_events": with_events,
            "without_events": without_events,
            "analysis_matches_df": analysis_matches_df,
            "analysis_selected_match_ids": analysis_selected_match_ids,
            "analysis_events_df": analysis_events_df,
            "analysis_with_events": analysis_with_events,
            "analysis_without_events": analysis_without_events,
            "analysis_scope": analysis_scope.get("meta", {}),
            "season_id": season_id,
        }

    def discover_competitions(
        self, search_queries: list[str], keywords: list[str]
    ) -> list[dict]:
        discovered = {}
        keyword_set = [normalize_text(keyword) for keyword in keywords if keyword]

        for query in search_queries:
            payload = self.fetch_api(
                "/search", {"query": query, "objType": "competition"}
            )
            competitions = extract_list(payload, "competitions")
            if not competitions and isinstance(payload, list):
                competitions = payload

            for competition in competitions:
                competition_id = competition.get("wyId")
                competition_name = competition.get("name")
                if not competition_id or not competition_name:
                    continue
                normalized_name = normalize_text(competition_name)
                if keyword_set and not any(
                    keyword in normalized_name for keyword in keyword_set
                ):
                    continue
                discovered[int(competition_id)] = {
                    "id": int(competition_id),
                    "name": competition_name,
                }

        return list(discovered.values())

    def _load_cached_competition_players(self, competition_id):
        if not self._use_player_cache():
            return None

        cache_path = self._competition_players_cache_file_path(competition_id)
        if not cache_path.exists():
            return None

        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            return None

        players = payload.get("players")
        if not isinstance(players, list):
            return None

        fetched_at = parse_iso_datetime(payload.get("fetched_at"))
        if fetched_at is None:
            return None
        age = datetime.now(timezone.utc) - fetched_at
        if age > timedelta(hours=self.settings.player_cache_ttl_hours):
            return None
        return players

    def _write_cached_competition_players(self, competition_id, players: list):
        if not self.settings.enable_incremental_player_fetch:
            return

        try:
            self.settings.player_cache_dir.mkdir(parents=True, exist_ok=True)
            payload = {
                "competition_id": int(competition_id),
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "players": players,
            }
            self._competition_players_cache_file_path(competition_id).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            print(f"Player cache write failed for competition {competition_id}: {exc}")

    def _load_cached_player_advanced_stats(self, player_id, competition_id):
        if not self._use_player_cache():
            return None

        cache_path = self._player_advanced_stats_cache_file_path(player_id, competition_id)
        if not cache_path.exists():
            return None

        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            return None

        stats = payload.get("stats")
        if not isinstance(stats, dict):
            return None

        fetched_at = parse_iso_datetime(payload.get("fetched_at"))
        if fetched_at is None:
            return None
        age = datetime.now(timezone.utc) - fetched_at
        if age > timedelta(hours=self.settings.player_cache_ttl_hours):
            return None
        return stats

    def _write_cached_player_advanced_stats(self, player_id, competition_id, stats: dict):
        if not self.settings.enable_incremental_player_fetch:
            return

        try:
            self.settings.player_cache_dir.mkdir(parents=True, exist_ok=True)
            payload = {
                "player_id": int(player_id),
                "competition_id": int(competition_id),
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "stats": stats,
            }
            self._player_advanced_stats_cache_file_path(
                player_id, competition_id
            ).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            print(f"Player cache write failed for player {player_id}: {exc}")

    def write_position_stat_benchmarks(self, competition_id, benchmarks: dict) -> None:
        try:
            self.settings.player_cache_dir.mkdir(parents=True, exist_ok=True)
            payload = {
                "competition_id": int(competition_id),
                "computed_at": datetime.now(timezone.utc).isoformat(),
                "benchmarks": benchmarks,
            }
            self._position_stat_benchmarks_cache_file_path(competition_id).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            print(f"Position benchmark cache write failed for competition {competition_id}: {exc}")

    def _fetch_competition_matches_with_cache(
        self,
        competition_id,
        competition_name: str,
    ) -> tuple[list, str]:
        cached_matches = self._load_cached_competition_matches(competition_id)
        if cached_matches is not None:
            return cached_matches, "cache"

        payload = self.fetch_api(f"/competitions/{competition_id}/matches")
        matches = extract_matches(payload)
        self._write_cached_competition_matches(
            competition_id, competition_name, matches
        )
        return matches, "api"

    def export_competition_matches(
        self,
        output_name: str,
        search_queries: list[str],
        keywords: list[str],
    ) -> Path | None:
        competitions = self.discover_competitions(search_queries, keywords)
        if not competitions:
            print(f"No competitions resolved for {output_name}.")
            return None

        frames = []
        cache_hits = 0
        api_requests = 0

        for competition in competitions:
            matches, source = self._fetch_competition_matches_with_cache(
                competition["id"], competition["name"]
            )
            print(
                f"Loading matches for competition {competition['name']} ({competition['id']}) source={source}"
            )
            if source == "cache":
                cache_hits += 1
            else:
                api_requests += 1
            if not matches:
                continue

            frame = self.normalize_matches_df(pd.json_normalize(matches))
            if frame.empty:
                continue
            frame["competition_name"] = competition["name"]
            frames.append(frame)

        if self.settings.enable_incremental_competition_fetch and competitions:
            print(
                f"Competition export cache: {cache_hits}/{len(competitions)} cache hits, {api_requests} API calls."
            )

        if not frames:
            print(f"No matches available for {output_name}.")
            return None

        combined = pd.concat(frames, ignore_index=True)
        if "matchId" in combined.columns:
            combined = combined.drop_duplicates(subset=["matchId"])
        elif "wyId" in combined.columns:
            combined = combined.drop_duplicates(subset=["wyId"])

        sort_col = match_sort_column(combined)
        if sort_col:
            combined = combined.sort_values(
                by=sort_col,
                ascending=False,
                na_position="last",
            )

        output_path = self.settings.report_path(
            "exports", "competitions", f"{output_name}_matches.csv"
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        combined.to_csv(output_path, index=False)
        print(
            f"Saved {len(combined)} matches -> {output_path.relative_to(self.settings.output_dir)}"
        )
        return output_path

    def get_competition_players(self, competition_id) -> list[dict]:
        competition_id = int(competition_id)

        cached_players = self._load_cached_competition_players(competition_id)
        if cached_players is not None:
            return cached_players

        players: list[dict] = []
        page = 1
        page_size = 100
        while True:
            payload = self.fetch_api(
                f"/competitions/{competition_id}/players",
                {"limit": page_size, "page": page},
            )
            page_players = extract_list(payload, "players")
            if not page_players and isinstance(payload, list):
                page_players = payload
            if not page_players:
                break
            players.extend(page_players)

            meta = payload.get("meta") if isinstance(payload, dict) else None
            page_count = meta.get("page_count") if isinstance(meta, dict) else None
            if not isinstance(page_count, int) or page >= page_count:
                break
            page += 1

        self._write_cached_competition_players(competition_id, players)
        return players

    def extract_player_ids(self, players: list[dict]) -> list[int]:
        player_ids: list[int] = []
        seen_ids: set[int] = set()
        for player in players:
            if not isinstance(player, dict):
                continue
            wy_id = player.get("wyId") or player.get("id")
            if wy_id is None:
                continue
            try:
                wy_id = int(wy_id)
            except Exception:
                continue
            if wy_id in seen_ids:
                continue
            seen_ids.add(wy_id)
            player_ids.append(wy_id)
        return player_ids

    def get_player_advanced_stats(self, player_id, competition_id) -> dict | None:
        if player_id is None:
            return None
        try:
            player_id = int(player_id)
        except Exception:
            return None
        competition_id = int(competition_id)

        cached_stats = self._load_cached_player_advanced_stats(player_id, competition_id)
        if cached_stats is not None:
            return cached_stats

        payload = self.fetch_api(
            f"/players/{player_id}/advancedstats",
            {"compId": competition_id},
        )
        if not isinstance(payload, dict):
            return None

        self._write_cached_player_advanced_stats(player_id, competition_id, payload)
        return payload
