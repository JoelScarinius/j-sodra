"""Pipeline context shared with modular analytics sections.

Sections receive one PipelineContext object instead of many separate arguments.
This keeps section code readable and makes collaboration easier.

Sections should normally read already-collected data from this context and write
outputs under reports/<section_name>/. They should not fetch directly from
Wyscout unless there is a clear reason.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from pipeline.data_service import DataService
    from pipeline.settings import Settings


@dataclass(slots=True)
class PipelineContext:
    """Shared runtime context passed to every analytics section."""

    settings: "Settings"
    service: "DataService"
    generated_at: str

    team: dict[str, Any]
    next_opponent: dict[str, Any]

    team_data: dict[str, Any]
    opponent_data: dict[str, Any]

    matchup: dict[str, Any] | None = None
    extras: dict[str, Any] = field(default_factory=dict)

    @property
    def team_id(self):
        return self.team.get("id")

    @property
    def team_name(self) -> str:
        return self.team.get("name") or "J-Södra"

    @property
    def opponent_id(self):
        return self.next_opponent.get("id")

    @property
    def opponent_name(self) -> str:
        return self.next_opponent.get("name") or "Next opponent"

    @property
    def active_season_id(self):
        return self.team.get("season_id")
    @property
    def report_scope_key(self) -> str:
        return self.settings.report_scope_key

    @property
    def requested_season_id(self):
        return self.settings.report_season_id

    @property
    def opponent_season_id(self):
        return self.next_opponent.get("season_id")

    def team_matches_df(self) -> pd.DataFrame:
        return _dataframe_from(self.team_data, "matches_df")

    def team_season_matches_df(self) -> pd.DataFrame:
        return _dataframe_from(self.team_data, "season_matches_df")

    def team_analysis_matches_df(self) -> pd.DataFrame:
        return _dataframe_from(self.team_data, "analysis_matches_df")

    def team_events_df(self) -> pd.DataFrame:
        return _dataframe_from(self.team_data, "events_df")

    def team_analysis_events_df(self) -> pd.DataFrame:
        return _dataframe_from(self.team_data, "analysis_events_df")

    def opponent_matches_df(self) -> pd.DataFrame:
        return _dataframe_from(self.opponent_data, "matches_df")

    def opponent_season_matches_df(self) -> pd.DataFrame:
        return _dataframe_from(self.opponent_data, "season_matches_df")

    def opponent_analysis_matches_df(self) -> pd.DataFrame:
        return _dataframe_from(self.opponent_data, "analysis_matches_df")

    def opponent_events_df(self) -> pd.DataFrame:
        return _dataframe_from(self.opponent_data, "events_df")

    def opponent_analysis_events_df(self) -> pd.DataFrame:
        return _dataframe_from(self.opponent_data, "analysis_events_df")


def _dataframe_from(payload: dict[str, Any], key: str) -> pd.DataFrame:
    """Return a DataFrame from a dataset dictionary or an empty DataFrame."""

    value = payload.get(key)
    return value if isinstance(value, pd.DataFrame) else pd.DataFrame()
