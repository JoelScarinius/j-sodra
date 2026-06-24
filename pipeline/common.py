"""General reusable helpers for the analytics pipeline.

Only put helpers here when they are useful across multiple sections or pipeline
modules. Section-specific logic belongs in pipeline/sections/<section_name>/.
"""

from __future__ import annotations

import unicodedata
from datetime import datetime, timezone
from typing import Any

import pandas as pd


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return text.lower().strip()


def extract_list(payload: Any, key: str) -> list:
    if payload is None:
        return []
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        value = payload.get(key, [])
        return value if isinstance(value, list) else []
    return []


def extract_matches(payload: Any) -> list:
    if payload is None:
        return []
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("matches", "fixtures", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def match_id(record: Any) -> int | None:
    if not isinstance(record, dict):
        return None
    value = record.get("matchId") or record.get("wyId") or record.get("id")
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def safe_bool(series) -> pd.Series:
    if series is None:
        return pd.Series(dtype=bool)
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False)
    if pd.api.types.is_numeric_dtype(series):
        return pd.to_numeric(series, errors="coerce").fillna(0).astype(bool)
    lowered = series.fillna("").astype(str).str.lower()
    return lowered.isin(["true", "1", "yes", "y", "on"])


def safe_numeric(series) -> pd.Series:
    if series is None:
        return pd.Series(dtype=float)
    return pd.to_numeric(series, errors="coerce").fillna(0.0)


def to_iso(value: Any):
    if value is None:
        return None
    if isinstance(value, pd.Timestamp):
        if pd.isna(value):
            return None
        value = value.to_pydatetime()
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


def jsonable(value: Any):
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    if isinstance(value, (pd.Timestamp, datetime)):
        return to_iso(value)
    if isinstance(value, (int, float, str, bool)) or value is None:
        return value
    return str(value)


def normalize_s3_part(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().strip("/")


def parse_iso_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def match_sort_column(matches_df: pd.DataFrame) -> str | None:
    if "dateutc" in matches_df.columns:
        return "dateutc"
    if "date" in matches_df.columns:
        return "date"
    return None


def played_status_mask(matches_df: pd.DataFrame) -> pd.Series:
    if matches_df.empty:
        return pd.Series(dtype=bool)
    if "status" not in matches_df.columns:
        return pd.Series(True, index=matches_df.index)
    normalized = matches_df["status"].fillna("").astype(str).str.lower()
    markers = ("played", "complete", "completed", "finished")
    mask = normalized.apply(lambda value: any(marker in value for marker in markers))
    if not mask.any():
        return pd.Series(True, index=matches_df.index)
    return mask


def team_event_mask(events_df: pd.DataFrame, team_id, team_name: str) -> pd.Series:
    if events_df.empty:
        return pd.Series(dtype=bool)

    mask = pd.Series(False, index=events_df.index)

    if "team.id" in events_df.columns and team_id is not None:
        team_ids = pd.to_numeric(events_df["team.id"], errors="coerce")
        mask = mask | team_ids.eq(float(team_id))

    if "team.name" in events_df.columns and team_name:
        team_norm = normalize_text(team_name)
        name_match = events_df["team.name"].fillna("").astype(str).apply(normalize_text)
        mask = mask | name_match.eq(team_norm)

    return mask


def extract_logo_url(profile: Any) -> str | None:
    if not isinstance(profile, dict):
        return None
    for key in (
        "imageDataURL",
        "logoDataURL",
        "logoURL",
        "logoUrl",
        "logo",
        "image",
        "badge",
        "crest",
    ):
        value = profile.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None
