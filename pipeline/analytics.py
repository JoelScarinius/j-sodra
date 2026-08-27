from __future__ import annotations

import re

import pandas as pd

from .common import (
    jsonable,
    match_id,
    match_sort_column,
    normalize_text,
    played_status_mask,
    to_iso,
)


def get_recent_played_matches(
    matches_df: pd.DataFrame, limit: int | None = None
) -> pd.DataFrame:
    if matches_df.empty:
        return pd.DataFrame()

    df = matches_df.copy()
    df = df[played_status_mask(df)]
    if df.empty:
        df = matches_df.copy()

    sort_col = match_sort_column(df)
    if sort_col:
        df = df.sort_values(by=sort_col, ascending=False, na_position="last")

    return df.head(limit) if limit is not None else df


def get_completed_matches(matches_df: pd.DataFrame) -> pd.DataFrame:
    """Return every completed match, newest first, without a display-size cap.

    Unlike get_recent_played_matches, this strict collector never falls back to
    scheduled fixtures when no completed match exists.
    """
    if matches_df.empty:
        return pd.DataFrame()
    df = matches_df.copy()
    df = df[played_status_mask(df)]
    if df.empty:
        return pd.DataFrame(columns=matches_df.columns)
    sort_col = match_sort_column(df)
    if sort_col:
        df = df.sort_values(by=sort_col, ascending=False, na_position="last")
    return df


def parse_match_label(label: str | None) -> dict | None:
    if not label or not isinstance(label, str):
        return None

    left = label.strip()
    score = None
    score_match = re.search(r",\s*(\d+)\s*-\s*(\d+)\s*$", left)
    if score_match:
        score = (int(score_match.group(1)), int(score_match.group(2)))
        left = left[: score_match.start()].strip()

    sides = re.match(r"^(.*?)\s+-\s+(.*?)$", left)
    if not sides:
        return {
            "home_name": None,
            "away_name": None,
            "score": score,
        }

    return {
        "home_name": sides.group(1).strip(),
        "away_name": sides.group(2).strip(),
        "score": score,
    }


def _outcome_from_label(label: str | None, team_name: str) -> dict | None:
    parsed = parse_match_label(label)
    if not parsed or not parsed.get("score"):
        return None

    target = normalize_text(team_name)
    home = normalize_text(parsed.get("home_name"))
    away = normalize_text(parsed.get("away_name"))
    home_goals, away_goals = parsed["score"]

    if home == target:
        goals_for = home_goals
        goals_against = away_goals
        side = "home"
    elif away == target:
        goals_for = away_goals
        goals_against = home_goals
        side = "away"
    else:
        return None

    if goals_for > goals_against:
        result = "W"
    elif goals_for < goals_against:
        result = "L"
    else:
        result = "D"

    return {
        "result": result,
        "goals_for": goals_for,
        "goals_against": goals_against,
        "score": f"{home_goals}-{away_goals}",
        "side": side,
    }


def build_recent_form(matches_df: pd.DataFrame, team_name: str, limit: int) -> dict:
    if matches_df.empty or "label" not in matches_df.columns:
        return {
            "matches": [],
            "summary": {"wins": 0, "draws": 0, "losses": 0, "points": 0},
        }

    played = get_recent_played_matches(matches_df, limit=limit)
    entries = []
    wins = draws = losses = points = 0

    for row in played.to_dict(orient="records"):
        outcome = _outcome_from_label(row.get("label"), team_name)
        entry = {
            "match_id": match_id(row),
            "dateutc": to_iso(row.get("dateutc") or row.get("date")),
            "season_id": jsonable(row.get("seasonId")),
            "competition_id": jsonable(row.get("competitionId")),
            "status": row.get("status"),
            "label": row.get("label"),
            "result": outcome.get("result") if outcome else None,
            "score": outcome.get("score") if outcome else None,
            "goals_for": outcome.get("goals_for") if outcome else None,
            "goals_against": outcome.get("goals_against") if outcome else None,
        }
        entries.append(entry)

        if not outcome:
            continue
        if outcome["result"] == "W":
            wins += 1
            points += 3
        elif outcome["result"] == "D":
            draws += 1
            points += 1
        else:
            losses += 1

    return {
        "matches": entries,
        "summary": {
            "wins": wins,
            "draws": draws,
            "losses": losses,
            "points": points,
        },
    }


def summarize_results_from_matches(matches_df: pd.DataFrame, team_name: str) -> dict:
    played = get_recent_played_matches(matches_df, limit=None)
    if played.empty:
        return {
            "matches_played": 0,
            "wins": 0,
            "draws": 0,
            "losses": 0,
            "points": 0,
            "goals_for": 0,
            "goals_against": 0,
        }

    wins = draws = losses = points = goals_for = goals_against = matches_played = 0
    for row in played.to_dict(orient="records"):
        outcome = _outcome_from_label(row.get("label"), team_name)
        if not outcome:
            continue
        matches_played += 1
        goals_for += int(outcome["goals_for"])
        goals_against += int(outcome["goals_against"])
        if outcome["result"] == "W":
            wins += 1
            points += 3
        elif outcome["result"] == "D":
            draws += 1
            points += 1
        else:
            losses += 1

    return {
        "matches_played": matches_played,
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "points": points,
        "goals_for": goals_for,
        "goals_against": goals_against,
    }


def is_h2h_label(label: str | None, team_name: str, opponent_name: str | None) -> bool:
    if not label or not opponent_name:
        return False
    parsed = parse_match_label(label)
    if not parsed:
        return False
    names = {
        normalize_text(parsed.get("home_name")),
        normalize_text(parsed.get("away_name")),
    }
    return normalize_text(team_name) in names and normalize_text(opponent_name) in names


def _season_subset(matches_df: pd.DataFrame, season_id) -> pd.DataFrame:
    if matches_df.empty or season_id is None or "seasonId" not in matches_df.columns:
        return matches_df.copy()
    df = matches_df.copy()
    df["seasonId"] = pd.to_numeric(df["seasonId"], errors="coerce")
    return df[df["seasonId"].eq(float(season_id))]


def _collect_h2h_meetings(
    matches_df: pd.DataFrame,
    team_name: str,
    opponent_name: str,
    max_h2h_matches: int,
) -> list[dict]:
    meetings = []
    for row in get_recent_played_matches(matches_df, limit=max_h2h_matches * 4).to_dict(
        orient="records"
    ):
        if not is_h2h_label(row.get("label"), team_name, opponent_name):
            continue
        outcome = _outcome_from_label(row.get("label"), team_name)
        meetings.append(
            {
                "match_id": match_id(row),
                "dateutc": to_iso(row.get("dateutc") or row.get("date")),
                "season_id": jsonable(row.get("seasonId")),
                "competition_id": jsonable(row.get("competitionId")),
                "status": row.get("status"),
                "label": row.get("label"),
                "result": outcome.get("result") if outcome else None,
                "score": outcome.get("score") if outcome else None,
                "goals_for": outcome.get("goals_for") if outcome else None,
                "goals_against": outcome.get("goals_against") if outcome else None,
            }
        )
        if len(meetings) >= max_h2h_matches:
            break
    return meetings


def build_head_to_head_overview(
    team_id,
    team_name: str,
    opponent_id,
    opponent_name: str | None,
    matches_df: pd.DataFrame,
    active_season_id=None,
    fallback_previous_season_id=None,
    max_h2h_matches: int = 8,
    h2h_fallback_to_previous_season: bool = True,
) -> dict:
    default_payload = {
        "found": False,
        "team_id": team_id,
        "team_name": team_name,
        "opponent_id": opponent_id,
        "opponent_name": opponent_name,
        "summary": {
            "matches_played": 0,
            "wins": 0,
            "draws": 0,
            "losses": 0,
            "goals_for": 0,
            "goals_against": 0,
        },
        "meetings": [],
        "scope": {
            "mode": "current_season",
            "requested_current_season_id": jsonable(active_season_id),
            "fallback_previous_season_id": jsonable(fallback_previous_season_id),
            "used_previous_season_fallback": False,
        },
    }

    if matches_df.empty or not opponent_name:
        return default_payload

    current_scope = _season_subset(matches_df, active_season_id)
    meetings = _collect_h2h_meetings(
        current_scope if not current_scope.empty else matches_df,
        team_name,
        opponent_name,
        max_h2h_matches,
    )

    used_previous_season_fallback = False
    if (
        not meetings
        and fallback_previous_season_id is not None
        and h2h_fallback_to_previous_season
    ):
        previous_scope = _season_subset(matches_df, fallback_previous_season_id)
        meetings = _collect_h2h_meetings(
            previous_scope,
            team_name,
            opponent_name,
            max_h2h_matches,
        )
        used_previous_season_fallback = bool(meetings)

    if not meetings:
        default_payload["scope"]["mode"] = (
            "previous_season_fallback"
            if used_previous_season_fallback
            else "current_season"
        )
        return default_payload

    summary = {
        "matches_played": len(meetings),
        "wins": sum(1 for row in meetings if row.get("result") == "W"),
        "draws": sum(1 for row in meetings if row.get("result") == "D"),
        "losses": sum(1 for row in meetings if row.get("result") == "L"),
        "goals_for": sum(int(row.get("goals_for") or 0) for row in meetings),
        "goals_against": sum(int(row.get("goals_against") or 0) for row in meetings),
    }

    return {
        "found": True,
        "team_id": team_id,
        "team_name": team_name,
        "opponent_id": opponent_id,
        "opponent_name": opponent_name,
        "summary": summary,
        "meetings": meetings,
        "scope": {
            "mode": (
                "previous_season_fallback"
                if used_previous_season_fallback
                else "current_season"
            ),
            "requested_current_season_id": jsonable(active_season_id),
            "fallback_previous_season_id": jsonable(fallback_previous_season_id),
            "used_previous_season_fallback": used_previous_season_fallback,
        },
    }


def build_head_to_head_last_meeting(head_to_head_overview: dict) -> dict:
    if not isinstance(head_to_head_overview, dict) or not head_to_head_overview.get(
        "found"
    ):
        return {
            "found": False,
            "note": "No previous meeting found. Using recent-form context.",
        }
    meetings = head_to_head_overview.get("meetings", [])
    if not meetings:
        return {
            "found": False,
            "note": "No previous meeting found. Using recent-form context.",
        }
    return {"found": True, **meetings[0]}


def build_matchup_card(
    next_opponent_info: dict, team_payload: dict, opponent_payload: dict
) -> dict:
    target_side = next_opponent_info.get("target_side")
    if target_side == "away":
        home = opponent_payload
        away = team_payload
    else:
        home = team_payload
        away = opponent_payload

    return {
        "home": home,
        "away": away,
        "dateutc": next_opponent_info.get("dateutc"),
        "status": next_opponent_info.get("status"),
        "season_id": next_opponent_info.get("season_id"),
        "source": next_opponent_info.get("source"),
        "match_id": next_opponent_info.get("match_id"),
        "label": next_opponent_info.get("label"),
    }
