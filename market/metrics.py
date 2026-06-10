from __future__ import annotations

import math

import numpy as np
import pandas as pd

from pipeline.common import safe_bool, safe_numeric

OPEN_PLAY_BLOCKERS = {
    "corner",
    "free_kick",
    "goal_kick",
    "kick_off",
    "penalty",
    "throw_in",
}
DEFENSIVE_TAGS = {
    "ball_recovery",
    "counterpressing_recovery",
    "defensive_duel",
    "ground_defending_duel",
    "interception",
    "loose_ball_duel",
    "recovery",
    "sliding_tackle",
}
OPPONENT_PICKUP_BLOCKERS = {
    "corner",
    "free_kick",
    "game_interruption",
    "goal_kick",
    "offside",
    "throw_in",
}
PERIOD_ORDER = {"1H": 1, "2H": 2, "E1": 3, "E2": 4, "P": 5}
RADAR_METRICS = [
    ("Prog. passes", "progressive_passes_per_match", "{:.2f}"),
    ("Prog. carries", "progressive_carries_per_match", "{:.2f}"),
    ("Shot assists", "shot_assists_per_match", "{:.2f}"),
    ("Box touches", "box_touches_per_match", "{:.2f}"),
    ("xG", "xg_per_match", "{:.2f}"),
    ("Def. actions", "defensive_actions_per_match", "{:.2f}"),
]
PLAYER_GROUP = ["player_id", "player_name"]


def _column(frame: pd.DataFrame, name: str, default):
    if name in frame.columns:
        return frame[name]
    return pd.Series([default] * len(frame), index=frame.index)


def _secondary_tags(value) -> set[str]:
    if isinstance(value, (list, tuple, set)):
        return {
            str(item).strip().lower()
            for item in value
            if str(item).strip()
        }
    if isinstance(value, str) and value.strip():
        return {value.strip().lower()}
    return set()


def _has_any(tags: set[str], candidates: set[str]) -> bool:
    return bool(tags & candidates)


def _is_set_piece(tags: set[str]) -> bool:
    return _has_any(tags, OPEN_PLAY_BLOCKERS)


def _event_clock(row: pd.Series) -> float:
    return float(row.get("period_order", 9) or 9) * 10_000.0 + float(
        (row.get("minute", 0) or 0) * 60 + (row.get("second", 0) or 0)
    )


def prepare_event_frame(events_df: pd.DataFrame) -> pd.DataFrame:
    if events_df.empty:
        return pd.DataFrame()

    frame = events_df.copy()
    frame["event_id"] = pd.to_numeric(_column(frame, "id", np.nan), errors="coerce")
    frame["event_type"] = _column(frame, "type.primary", "").fillna("").astype(str).str.lower()
    frame["secondary_tags"] = _column(frame, "type.secondary", []).apply(_secondary_tags)
    frame["player_name"] = (
        _column(frame, "player.name", "").fillna("").astype(str).str.strip()
    )
    frame["recipient_name"] = (
        _column(frame, "pass.recipient.name", "").fillna("").astype(str).str.strip()
    )
    frame["player_id"] = pd.to_numeric(_column(frame, "player.id", np.nan), errors="coerce")
    frame["matchId"] = pd.to_numeric(_column(frame, "matchId", np.nan), errors="coerce")
    frame["team_id"] = pd.to_numeric(_column(frame, "team.id", np.nan), errors="coerce")
    frame["opponent_team_id"] = pd.to_numeric(
        _column(frame, "opponentTeam.id", np.nan), errors="coerce"
    )
    frame["possession_id"] = pd.to_numeric(
        _column(frame, "possession.id", np.nan), errors="coerce"
    )
    frame["possession_duration"] = safe_numeric(
        _column(frame, "possession.duration", 0.0)
    )
    frame["possession_events"] = safe_numeric(
        _column(frame, "possession.eventsNumber", 0.0)
    )
    frame["period_order"] = (
        _column(frame, "matchPeriod", "").map(PERIOD_ORDER).fillna(9)
    )
    frame["start_x"] = safe_numeric(_column(frame, "location.x", np.nan))
    frame["start_y"] = safe_numeric(_column(frame, "location.y", np.nan))
    frame["pass_end_x"] = safe_numeric(_column(frame, "pass.endLocation.x", np.nan))
    frame["pass_end_y"] = safe_numeric(_column(frame, "pass.endLocation.y", np.nan))
    frame["carry_end_x"] = safe_numeric(_column(frame, "carry.endLocation.x", np.nan))
    frame["carry_end_y"] = safe_numeric(_column(frame, "carry.endLocation.y", np.nan))
    frame["shot_xg"] = safe_numeric(_column(frame, "shot.xg", 0.0))
    frame["pass_accurate"] = safe_bool(_column(frame, "pass.accurate", False))
    frame["shot_on_target"] = safe_bool(_column(frame, "shot.onTarget", False))
    return frame


def progressive_passes(events_df: pd.DataFrame) -> pd.DataFrame:
    frame = prepare_event_frame(events_df)
    if frame.empty:
        return pd.DataFrame()

    passes = frame[frame["event_type"].eq("pass") & frame["pass_accurate"]].copy()
    if passes.empty:
        return passes

    passes = passes[passes["recipient_name"].ne("")]
    passes["set_piece"] = passes["secondary_tags"].apply(_is_set_piece)
    passes["progressive"] = passes["secondary_tags"].apply(
        lambda tags: "progressive_pass" in tags
    )
    passes["progression_gain"] = passes["pass_end_x"] - passes["start_x"]
    passes.loc[:, "progressive"] = (
        passes["progressive"]
        | (
            passes["progression_gain"].ge(15)
            & passes["pass_end_x"].gt(passes["start_x"])
        )
    )
    passes = passes[passes["progressive"] & ~passes["set_piece"]].copy()
    return passes.sort_values(
        by=["progression_gain", "pass_end_x"],
        ascending=[False, False],
    )


def progressive_carries(events_df: pd.DataFrame) -> pd.DataFrame:
    frame = prepare_event_frame(events_df)
    if frame.empty:
        return pd.DataFrame()

    carries = frame[
        frame["carry_end_x"].gt(0)
        | frame["secondary_tags"].apply(lambda tags: "progressive_run" in tags)
    ].copy()
    if carries.empty:
        return carries

    carries["carry_gain"] = carries["carry_end_x"] - carries["start_x"]
    carries["progressive"] = carries["secondary_tags"].apply(
        lambda tags: "progressive_run" in tags
    ) | (carries["carry_gain"].ge(12) & carries["carry_end_x"].gt(carries["start_x"]))
    carries = carries[carries["progressive"]].copy()
    return carries.sort_values(by=["carry_gain", "carry_end_x"], ascending=False)


def defensive_actions(events_df: pd.DataFrame) -> pd.DataFrame:
    frame = prepare_event_frame(events_df)
    if frame.empty:
        return pd.DataFrame()

    mask = frame["event_type"].isin({"clearance", "interception", "goalkeeper_exit"})
    mask = mask | frame["secondary_tags"].apply(lambda tags: _has_any(tags, DEFENSIVE_TAGS))
    actions = frame[mask].copy()
    if actions.empty:
        return actions

    def classify(row) -> str:
        tags = row["secondary_tags"]
        if row["event_type"] == "interception" or "interception" in tags:
            return "Interceptions"
        if row["event_type"] == "clearance":
            return "Clearances"
        if {"recovery", "ball_recovery", "counterpressing_recovery"} & tags:
            return "Recoveries"
        return "Duels"

    actions["action_family"] = actions.apply(classify, axis=1)
    actions["high_regain"] = actions["start_x"].ge(60)
    return actions


def shot_events(events_df: pd.DataFrame) -> pd.DataFrame:
    frame = prepare_event_frame(events_df)
    if frame.empty:
        return pd.DataFrame()

    shots = frame[frame["event_type"].eq("shot")].copy()
    if shots.empty:
        return shots

    shots["goal"] = shots["secondary_tags"].apply(lambda tags: "goal" in tags)
    shots["inside_box"] = shots["start_x"].ge(83) & shots["start_y"].between(18, 82)
    shots["distance"] = np.sqrt((100 - shots["start_x"]) ** 2 + (50 - shots["start_y"]) ** 2)
    return shots.sort_values(by=["shot_xg", "distance"], ascending=[False, True])


def build_pass_network(
    events_df: pd.DataFrame,
    match_id: int | None,
    max_players: int = 11,
    min_link_count: int = 3,
) -> dict[str, pd.DataFrame | dict]:
    if match_id is None:
        return {
            "positions": pd.DataFrame(),
            "links": pd.DataFrame(),
            "passes": pd.DataFrame(),
            "meta": {},
        }

    frame = prepare_event_frame(events_df)
    match_frame = frame[frame["matchId"].eq(float(match_id))].copy()
    if match_frame.empty:
        return {
            "positions": pd.DataFrame(),
            "links": pd.DataFrame(),
            "passes": pd.DataFrame(),
            "meta": {},
        }

    player_events = match_frame[match_frame["player_name"].ne("")].copy()
    positions = (
        player_events.groupby("player_name", as_index=False)
        .agg(
            average_x=("start_x", "mean"),
            average_y=("start_y", "mean"),
            touches=("player_name", "size"),
        )
        .sort_values(by="touches", ascending=False)
    )
    positions = positions.head(max_players).copy()
    player_pool = set(positions["player_name"])

    passes = match_frame[
        match_frame["event_type"].eq("pass")
        & match_frame["pass_accurate"]
        & match_frame["player_name"].ne("")
        & match_frame["recipient_name"].ne("")
    ].copy()
    if passes.empty:
        return {
            "positions": positions,
            "links": pd.DataFrame(),
            "passes": passes,
            "meta": {},
        }

    passes = passes[
        ~passes["secondary_tags"].apply(_is_set_piece)
    ].copy()
    passes = passes[
        passes["player_name"].isin(player_pool)
        & passes["recipient_name"].isin(player_pool)
    ].copy()
    if passes.empty:
        return {
            "positions": positions,
            "links": pd.DataFrame(),
            "passes": passes,
            "meta": {},
        }

    pairs = passes.apply(
        lambda row: tuple(sorted((row["player_name"], row["recipient_name"]))),
        axis=1,
    )
    all_links = pairs.value_counts().rename_axis("pair").reset_index(name="pass_count")
    links = all_links.copy()
    links["player_a"] = links["pair"].apply(lambda pair: pair[0])
    links["player_b"] = links["pair"].apply(lambda pair: pair[1])
    links = links.drop(columns=["pair"])
    if not links.empty:
        links = links[links["pass_count"].ge(min_link_count)].copy()
        if links.empty:
            links = all_links.copy()
            links["player_a"] = links["pair"].apply(lambda pair: pair[0])
            links["player_b"] = links["pair"].apply(lambda pair: pair[1])
            links = links.drop(columns=["pair"]).head(10)

    strongest_link = None
    if not links.empty:
        top_link = links.sort_values(by="pass_count", ascending=False).iloc[0]
        strongest_link = {
            "player_a": str(top_link["player_a"]),
            "player_b": str(top_link["player_b"]),
            "pass_count": int(top_link["pass_count"]),
        }

    network_height = None
    if not positions.empty:
        network_height = float(
            np.average(positions["average_x"], weights=positions["touches"])
        )

    return {
        "positions": positions,
        "links": links,
        "passes": passes,
        "meta": {
            "network_height": network_height,
            "strongest_link": strongest_link,
        },
    }


def dropped_ball_turnovers(
    events_df: pd.DataFrame,
    team_id: int,
    min_possession_seconds: float = 8.0,
    min_possession_events: int = 4,
    max_pickup_delay: int = 8,
) -> pd.DataFrame:
    frame = prepare_event_frame(events_df)
    if frame.empty:
        return pd.DataFrame()

    frame = frame.sort_values(
        by=["matchId", "period_order", "minute", "second", "event_id"],
        kind="mergesort",
    ).reset_index(drop=True)

    rows: list[dict] = []
    team_possessions = frame[
        frame["team_id"].eq(float(team_id)) & frame["possession_id"].notna()
    ].groupby(["matchId", "possession_id"], dropna=True, sort=False)

    for (match_id, _), possession_df in team_possessions:
        if possession_df.empty:
            continue

        possession_duration = float(possession_df["possession_duration"].iloc[0])
        possession_events = int(possession_df["possession_events"].iloc[0])
        if possession_duration < min_possession_seconds:
            continue
        if possession_events < min_possession_events:
            continue

        failed_passes = possession_df[
            possession_df["event_type"].eq("pass") & (~possession_df["pass_accurate"])
        ].copy()
        if failed_passes.empty:
            continue

        failed_passes = failed_passes[
            ~failed_passes["secondary_tags"].apply(_is_set_piece)
        ].copy()
        if failed_passes.empty:
            continue

        last_failed_pass = failed_passes.iloc[-1]
        later = frame[
            (frame.index > int(possession_df.index.max()))
            & frame["matchId"].eq(float(match_id))
            & frame["team_id"].ne(float(team_id))
        ].copy()
        later = later[~later["event_type"].isin(OPPONENT_PICKUP_BLOCKERS)]
        later = later[~(later["start_x"].eq(0) & later["start_y"].eq(0))]
        if later.empty:
            continue

        opponent_pickup = later.iloc[0]
        pickup_delay = _event_clock(opponent_pickup) - _event_clock(last_failed_pass)
        if pickup_delay < 0 or pickup_delay > max_pickup_delay:
            continue

        drop_x = float(last_failed_pass["pass_end_x"] or 0.0)
        drop_y = float(last_failed_pass["pass_end_y"] or 0.0)
        if drop_x <= 0 and drop_y <= 0:
            drop_x = float(last_failed_pass["start_x"])
            drop_y = float(last_failed_pass["start_y"])

        pickup_x = 100.0 - float(opponent_pickup["start_x"])
        pickup_y = 100.0 - float(opponent_pickup["start_y"])
        rows.append(
            {
                "matchId": int(match_id),
                "player_name": str(last_failed_pass["player_name"]),
                "drop_x": drop_x,
                "drop_y": drop_y,
                "pickup_x": pickup_x,
                "pickup_y": pickup_y,
                "pickup_delay": float(pickup_delay),
                "possession_duration": possession_duration,
                "possession_events": possession_events,
                "opponent_event_type": str(opponent_pickup["event_type"]),
                "pickup_in_attacking_half": bool(pickup_x >= 50.0),
            }
        )

    if not rows:
        return pd.DataFrame()

    dropped_df = pd.DataFrame(rows)
    dropped_df["travel_distance"] = np.sqrt(
        (dropped_df["pickup_x"] - dropped_df["drop_x"]) ** 2
        + (dropped_df["pickup_y"] - dropped_df["drop_y"]) ** 2
    )
    return dropped_df.sort_values(
        by=["possession_duration", "pickup_x", "pickup_delay"],
        ascending=[False, False, True],
    ).reset_index(drop=True)


def player_metric_table(events_df: pd.DataFrame) -> pd.DataFrame:
    frame = prepare_event_frame(events_df)
    if frame.empty:
        return pd.DataFrame()

    player_events = frame[frame["player_name"].ne("")].copy()
    if player_events.empty:
        return pd.DataFrame()

    appearances = (
        player_events.groupby(PLAYER_GROUP, dropna=False)["matchId"]
        .nunique()
        .rename("appearances")
    )
    touches = player_events.groupby(PLAYER_GROUP, dropna=False).size().rename("touches")
    prog_pass_counts = (
        progressive_passes(frame).groupby(PLAYER_GROUP, dropna=False).size().rename("progressive_passes")
    )
    prog_carry_counts = (
        progressive_carries(frame)
        .groupby(PLAYER_GROUP, dropna=False)
        .size()
        .rename("progressive_carries")
    )

    shot_assist_mask = frame["event_type"].eq("pass") & frame["secondary_tags"].apply(
        lambda tags: _has_any(tags, {"assist", "key_pass"})
    )
    shot_assists = (
        frame[shot_assist_mask]
        .groupby(PLAYER_GROUP, dropna=False)
        .size()
        .rename("shot_assists")
    )
    box_touches = (
        player_events[player_events["start_x"].ge(83) & player_events["start_y"].between(18, 82)]
        .groupby(PLAYER_GROUP, dropna=False)
        .size()
        .rename("box_touches")
    )
    xg = shot_events(frame).groupby(PLAYER_GROUP, dropna=False)["shot_xg"].sum().rename("xg")
    defensive = (
        defensive_actions(frame)
        .groupby(PLAYER_GROUP, dropna=False)
        .size()
        .rename("defensive_actions")
    )

    table = appearances.to_frame().join(
        [touches, prog_pass_counts, prog_carry_counts, shot_assists, box_touches, xg, defensive],
        how="left",
    )
    table = table.fillna(0.0).reset_index()

    divisor = table["appearances"].clip(lower=1.0)
    for column in (
        "touches",
        "progressive_passes",
        "progressive_carries",
        "shot_assists",
        "box_touches",
        "xg",
        "defensive_actions",
    ):
        table[f"{column}_per_match"] = table[column] / divisor

    table["selection_score"] = (
        table["progressive_passes_per_match"] * 2.2
        + table["progressive_carries_per_match"] * 1.6
        + table["shot_assists_per_match"] * 2.0
        + table["box_touches_per_match"] * 0.8
        + table["xg_per_match"] * 6.0
        + table["defensive_actions_per_match"] * 0.35
    )
    return table.sort_values(by=["selection_score", "touches"], ascending=False).reset_index(drop=True)


def select_player_radar(
    player_table: pd.DataFrame,
    player_name: str | None = None,
) -> dict | None:
    if player_table.empty:
        return None

    minimum_appearances = max(2, math.ceil(player_table["appearances"].max() / 4))
    comparison = player_table[player_table["appearances"].ge(minimum_appearances)].copy()
    if comparison.empty:
        comparison = player_table.copy()

    for _, column, _ in RADAR_METRICS:
        comparison[f"{column}_pct"] = comparison[column].rank(pct=True, method="average") * 100

    if player_name:
        lowered = comparison["player_name"].fillna("").astype(str).str.lower()
        match = lowered.eq(player_name.strip().lower())
        selected = comparison[match].head(1)
        if selected.empty:
            selected = comparison.head(1)
    else:
        selected = comparison.sort_values(by=["selection_score", "touches"], ascending=False).head(1)

    if selected.empty:
        return None

    player = selected.iloc[0].to_dict()
    metrics = []
    for label, column, formatter in RADAR_METRICS:
        metrics.append(
            {
                "label": label,
                "percentile": float(player.get(f"{column}_pct", 0.0) or 0.0),
                "raw_value": float(player.get(column, 0.0) or 0.0),
                "display_value": formatter.format(float(player.get(column, 0.0) or 0.0)),
            }
        )

    return {
        "player": player,
        "metrics": metrics,
        "comparison_size": int(len(comparison)),
        "minimum_appearances": int(minimum_appearances),
    }