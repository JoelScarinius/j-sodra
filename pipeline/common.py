"""General reusable helpers for the analytics pipeline.

Only put helpers here when they are useful across multiple sections or pipeline
modules. Section-specific logic belongs in pipeline/sections/<section_name>/.
"""

from __future__ import annotations

import unicodedata
from datetime import datetime, timezone
from typing import Any

import pandas as pd

FINAL_MATCH_STATUSES = frozenset(
    {
        "played",
        "complete",
        "completed",
        "finished",
        "match ended",
    }
)


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return text.lower().strip()


def normalize_status(value: Any) -> str:
    """Return a normalized source status without guessing its meaning."""
    return " ".join(str(value or "").strip().lower().split())


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
    value = None
    for key in ("matchId", "wyId", "id"):
        candidate = record.get(key)
        if candidate is not None:
            value = candidate
            break
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
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


def numeric_or_nan(series) -> pd.Series:
    """Convert to numeric while preserving missing or invalid values as NaN."""
    if series is None:
        return pd.Series(dtype=float)
    return pd.to_numeric(series, errors="coerce")


def numeric_or_zero(series) -> pd.Series:
    """Convert to numeric and replace missing values with zero.

    Use only when the metric contract explicitly defines missing as zero.
    """
    return numeric_or_nan(series).fillna(0.0)


def safe_numeric(series) -> pd.Series:
    """Backward-compatible zero-filling numeric conversion.

    New event-derived metrics such as xG, xT, coordinates and expected points
    should use numeric_or_nan so missing values remain distinguishable from zero.
    """
    return numeric_or_zero(series)


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
    except (TypeError, ValueError):
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
    except (TypeError, ValueError):
        return None


def match_sort_column(matches_df: pd.DataFrame) -> str | None:
    if "dateutc" in matches_df.columns:
        return "dateutc"
    if "date" in matches_df.columns:
        return "date"
    return None


def played_status_mask(matches_df: pd.DataFrame) -> pd.Series:
    """Return True only for explicitly recognized final-match statuses.

    Missing and unknown statuses remain False. This intentionally fails closed:
    scheduled, postponed, cancelled, or unfamiliar statuses must never be
    silently treated as played matches.
    """
    if matches_df.empty:
        return pd.Series(False, index=matches_df.index, dtype=bool)
    if "status" not in matches_df.columns:
        return pd.Series(False, index=matches_df.index, dtype=bool)
    normalized = matches_df["status"].map(normalize_status)
    return normalized.isin(FINAL_MATCH_STATUSES)


def unknown_match_statuses(matches_df: pd.DataFrame) -> list[str]:
    """Return non-empty statuses that are not recognized as final.

    This is useful for integrity checks and logging. It does not classify an
    unknown status as played.
    """
    if matches_df.empty or "status" not in matches_df.columns:
        return []
    normalized = matches_df["status"].map(normalize_status)
    values = {
        value
        for value in normalized.tolist()
        if value and value not in FINAL_MATCH_STATUSES
    }
    return sorted(values)


def team_event_mask(events_df: pd.DataFrame, team_id, team_name: str) -> pd.Series:
    if events_df.empty:
        return pd.Series(False, index=events_df.index, dtype=bool)
    mask = pd.Series(False, index=events_df.index, dtype=bool)
    if "team.id" in events_df.columns and team_id is not None:
        team_ids = pd.to_numeric(events_df["team.id"], errors="coerce")
        mask = mask | team_ids.eq(float(team_id))
    if "team.name" in events_df.columns and team_name:
        team_norm = normalize_text(team_name)
        name_match = events_df["team.name"].fillna("").astype(str).map(normalize_text)
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
