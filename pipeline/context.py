"""Pipeline context shared with modular analytics sections.

A section should receive one PipelineContext object instead of many separate
arguments. This keeps section code easy to read and makes collaboration easier.

Sections should read from this context and write their own outputs under:

    reports/<section_name>/

Sections should not fetch from Wyscout directly unless there is a very good
reason. Shared data should normally come from DataService and the datasets
already collected by the orchestrator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from pipeline.data_service import DataService
from pipeline.settings import Settings


@dataclass
class PipelineContext:
    """Shared runtime context for analytics sections."""

    settings: Settings
    service: DataService
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
    def opponent_season_id(self):
        return self.next_opponent.get("season_id")

    def team_matches_df(self) -> pd.DataFrame:
        return self.team_data.get("matches_df", pd.DataFrame())

    def team_season_matches_df(self) -> pd.DataFrame:
        return self.team_data.get("season_matches_df", pd.DataFrame())

    def team_analysis_matches_df(self) -> pd.DataFrame:
        return self.team_data.get("analysis_matches_df", pd.DataFrame())

    def team_events_df(self) -> pd.DataFrame:
        return self.team_data.get("events_df", pd.DataFrame())

    def team_analysis_events_df(self) -> pd.DataFrame:
        return self.team_data.get("analysis_events_df", pd.DataFrame())

    def opponent_matches_df(self) -> pd.DataFrame:
        return self.opponent_data.get("matches_df", pd.DataFrame())

    def opponent_season_matches_df(self) -> pd.DataFrame:
        return self.opponent_data.get("season_matches_df", pd.DataFrame())

    def opponent_analysis_matches_df(self) -> pd.DataFrame:
        return self.opponent_data.get("analysis_matches_df", pd.DataFrame())

    def opponent_events_df(self) -> pd.DataFrame:
        return self.opponent_data.get("events_df", pd.DataFrame())

    def opponent_analysis_events_df(self) -> pd.DataFrame:
        return self.opponent_data.get("analysis_events_df", pd.DataFrame())
