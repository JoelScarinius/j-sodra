"""Shared label helpers for modular dashboard sections."""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd


def _first_nonblank(frame: pd.DataFrame, columns: Sequence[str]) -> str | None:
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


def derive_competition_label(matches_df: pd.DataFrame) -> str:
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


def derive_season_label(matches_df: pd.DataFrame, season_id: int | None) -> str:
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


def derive_latest_match_label(matches_df: pd.DataFrame) -> str | None:
    if matches_df.empty:
        return None
    for column in ("dateutc", "date"):
        if column not in matches_df.columns:
            continue
        ordered = pd.to_datetime(matches_df[column], errors="coerce", utc=True)
        if ordered.dropna().empty:
            continue
        latest_index = ordered.sort_values(ascending=False).index[0]
        label = matches_df.loc[latest_index].get("label")
        if isinstance(label, str) and label.strip():
            return label.strip()
    return _first_nonblank(matches_df, ["label", "matchLabel", "name"])
