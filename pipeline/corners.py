from __future__ import annotations

import ast
import re

import pandas as pd

from .common import normalize_text, safe_bool, safe_numeric, team_event_mask


CORNER_SEQUENCE_WINDOW_SECONDS = 20
CORNER_SEQUENCE_BREAK_TYPES = {
    "corner",
    "free_kick",
    "goal_kick",
    "offside",
    "penalty",
    "throw_in",
    "game_interruption",
}


def parse_secondary_tags(value) -> list[str]:
    if isinstance(value, list):
        tags = []
        for item in value:
            if isinstance(item, dict):
                tags.append(normalize_text(item.get("name") or item.get("primary")))
            else:
                tags.append(normalize_text(item))
        return [tag for tag in tags if tag]

    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = ast.literal_eval(text)
            if isinstance(parsed, list):
                return parse_secondary_tags(parsed)
        except Exception:
            pass
        return [
            normalize_text(part)
            for part in re.split(r"[|,]", text)
            if normalize_text(part)
        ]

    return [normalize_text(value)]


def classify_corner_delivery_zone(end_x, end_y) -> str:
    if pd.isna(end_x) or pd.isna(end_y):
        return "unknown"
    if end_x >= 94 and 38 <= end_y <= 62:
        return "six_yard_central"
    if end_x >= 92 and end_y < 38:
        return "front_post"
    if end_x >= 92 and end_y > 62:
        return "back_post"
    if end_x >= 84 and 30 <= end_y <= 70:
        return "penalty_spot_zone"
    return "edge_recycle_zone"


def build_corner_dataframe(events_df: pd.DataFrame) -> pd.DataFrame:
    if events_df.empty or "type.primary" not in events_df.columns:
        return pd.DataFrame()

    primary = events_df["type.primary"].fillna("").astype(str).str.lower()
    corners = events_df[primary.eq("corner")].copy()
    if corners.empty:
        return pd.DataFrame()

    required_columns = [
        "id",
        "matchId",
        "matchPeriod",
        "team.id",
        "team.name",
        "minute",
        "second",
        "possession.id",
        "player.id",
        "player.name",
        "location.x",
        "location.y",
        "pass.endLocation.x",
        "pass.endLocation.y",
        "type.secondary",
    ]
    for column in required_columns:
        if column not in corners.columns:
            corners[column] = None

    corners["id"] = pd.to_numeric(corners["id"], errors="coerce")
    corners["matchId"] = pd.to_numeric(corners["matchId"], errors="coerce")
    corners["team.id"] = pd.to_numeric(corners["team.id"], errors="coerce")
    corners["possession.id"] = pd.to_numeric(corners["possession.id"], errors="coerce")
    corners["player.id"] = pd.to_numeric(corners["player.id"], errors="coerce")
    corners["start_x"] = pd.to_numeric(corners["location.x"], errors="coerce").fillna(0)
    corners["start_y"] = pd.to_numeric(corners["location.y"], errors="coerce").fillna(
        50
    )
    corners["end_x"] = pd.to_numeric(
        corners["pass.endLocation.x"], errors="coerce"
    ).fillna(88)
    corners["end_y"] = pd.to_numeric(
        corners["pass.endLocation.y"], errors="coerce"
    ).fillna(50)
    corners["side"] = corners["start_y"].apply(
        lambda value: "left" if value < 50 else "right"
    )

    minute = pd.to_numeric(corners.get("minute"), errors="coerce").fillna(0)
    second = pd.to_numeric(corners.get("second"), errors="coerce").fillna(0)
    corners["event_time_seconds"] = (minute * 60) + second

    tags = corners["type.secondary"].apply(parse_secondary_tags)
    corners["tag_shot_assist"] = tags.apply(lambda values: "shot_assist" in values)
    corners["tag_assist"] = tags.apply(lambda values: "assist" in values)
    corners["tag_loss"] = tags.apply(lambda values: "loss" in values)
    corners["delivery_zone"] = corners.apply(
        lambda row: classify_corner_delivery_zone(row.get("end_x"), row.get("end_y")),
        axis=1,
    )

    return corners


def _summarize_corner_sequences(
    events_df: pd.DataFrame, corners_df: pd.DataFrame
) -> pd.DataFrame:
    if events_df.empty or corners_df.empty or "id" not in corners_df.columns:
        return pd.DataFrame()

    ordered = events_df.copy()
    ordered["type.primary"] = (
        ordered.get("type.primary", pd.Series("", index=ordered.index, dtype=object))
        .fillna("")
        .astype(str)
        .str.lower()
    )
    ordered["matchId"] = pd.to_numeric(ordered.get("matchId"), errors="coerce")
    ordered["team.id"] = pd.to_numeric(ordered.get("team.id"), errors="coerce")
    ordered["event_id"] = pd.to_numeric(
        ordered.get("id", pd.Series(index=ordered.index, dtype=float)),
        errors="coerce",
    )
    ordered["possession_event_index"] = pd.to_numeric(
        ordered.get("possession.eventIndex", pd.Series(index=ordered.index, dtype=float)),
        errors="coerce",
    )
    minute = pd.to_numeric(ordered.get("minute"), errors="coerce").fillna(0)
    second = pd.to_numeric(ordered.get("second"), errors="coerce").fillna(0)
    ordered["event_time_seconds"] = (minute * 60) + second
    ordered["is_shot"] = ordered["type.primary"].eq("shot")
    ordered["is_goal"] = safe_bool(ordered.get("shot.isGoal"))

    body_part = ordered.get(
        "shot.bodyPart", pd.Series("", index=ordered.index, dtype=object)
    )
    body_part = body_part.fillna("").astype(str).str.lower()
    ordered["is_header_shot"] = ordered["is_shot"] & body_part.str.contains("head")
    ordered["is_header_goal"] = ordered["is_header_shot"] & ordered["is_goal"]
    ordered["shot_xg"] = safe_numeric(ordered.get("shot.xg"))
    ordered["shot_player_name"] = ordered.get(
        "player.name", pd.Series("", index=ordered.index, dtype=object)
    )
    ordered["shot_player_id"] = pd.to_numeric(
        ordered.get("player.id", pd.Series(index=ordered.index, dtype=float)),
        errors="coerce",
    )

    sort_columns = [
        "matchId",
        "matchPeriod",
        "event_time_seconds",
        "possession_event_index",
        "event_id",
    ]
    available_sort_columns = [
        column for column in sort_columns if column in ordered.columns
    ]
    ordered = ordered.sort_values(
        by=available_sort_columns, ascending=True, na_position="last"
    )

    summary_rows = []
    for corner in corners_df.to_dict(orient="records"):
        corner_id = pd.to_numeric(pd.Series([corner.get("id")]), errors="coerce").iloc[0]
        match_id = pd.to_numeric(pd.Series([corner.get("matchId")]), errors="coerce").iloc[0]
        team_id = pd.to_numeric(pd.Series([corner.get("team.id")]), errors="coerce").iloc[0]
        corner_time = pd.to_numeric(
            pd.Series([corner.get("event_time_seconds")]), errors="coerce"
        ).fillna(0).iloc[0]
        match_period = corner.get("matchPeriod")

        mask = ordered["matchId"].eq(match_id) & ordered["event_time_seconds"].between(
            corner_time,
            corner_time + CORNER_SEQUENCE_WINDOW_SECONDS,
        )
        if pd.notna(match_period) and "matchPeriod" in ordered.columns:
            mask &= ordered["matchPeriod"].eq(match_period)

        window = ordered.loc[mask].copy()
        after_corner = window[
            (window["event_time_seconds"] > corner_time)
            | (
                window["event_time_seconds"].eq(corner_time)
                & window["event_id"].gt(corner_id)
            )
        ].reset_index(drop=True)

        break_positions = after_corner.index[
            after_corner["type.primary"].isin(CORNER_SEQUENCE_BREAK_TYPES)
        ]
        sequence_events = (
            after_corner.iloc[: break_positions[0]]
            if len(break_positions)
            else after_corner
        )

        shots = sequence_events[
            sequence_events["team.id"].eq(team_id) & sequence_events["is_shot"]
        ].copy()
        first_shot = shots.iloc[0] if not shots.empty else None

        summary_rows.append(
            {
                "id": corner_id,
                "possession_shot": bool(not shots.empty),
                "possession_goal": bool(shots["is_goal"].any()) if not shots.empty else False,
                "possession_shot_count": int(len(shots)),
                "possession_goal_count": int(shots["is_goal"].sum()) if not shots.empty else 0,
                "possession_header_shot_count": int(shots["is_header_shot"].sum()) if not shots.empty else 0,
                "possession_header_goal_count": int(shots["is_header_goal"].sum()) if not shots.empty else 0,
                "possession_xg": round(float(shots["shot_xg"].sum()), 4) if not shots.empty else 0.0,
                "first_shot_xg": round(float(first_shot.get("shot_xg", 0.0) or 0.0), 4)
                if first_shot is not None
                else 0.0,
                "first_shooter_name": first_shot.get("shot_player_name") if first_shot is not None else None,
                "first_shooter_id": first_shot.get("shot_player_id") if first_shot is not None else None,
            }
        )

    return pd.DataFrame(summary_rows)


def annotate_corner_possession_outcomes(
    events_df: pd.DataFrame, corners_df: pd.DataFrame
) -> pd.DataFrame:
    default_bool = {
        "possession_shot": False,
        "possession_goal": False,
    }
    default_numeric = {
        "possession_shot_count": 0,
        "possession_goal_count": 0,
        "possession_header_shot_count": 0,
        "possession_header_goal_count": 0,
        "possession_xg": 0.0,
        "first_shot_xg": 0.0,
    }
    default_text = {
        "first_shooter_name": None,
        "first_shooter_id": None,
    }

    if corners_df.empty:
        return corners_df.copy()
    if events_df.empty:
        for key, value in {**default_bool, **default_numeric, **default_text}.items():
            corners_df[key] = value
        return corners_df

    required_columns = {"id", "matchId", "team.id", "type.primary", "minute", "second"}
    if not required_columns.issubset(set(events_df.columns)):
        for key, value in {**default_bool, **default_numeric, **default_text}.items():
            corners_df[key] = value
        return corners_df

    tmp = events_df.copy()
    tmp["matchId"] = pd.to_numeric(tmp["matchId"], errors="coerce")
    tmp["team.id"] = pd.to_numeric(tmp["team.id"], errors="coerce")
    tmp["possession.id"] = pd.to_numeric(tmp["possession.id"], errors="coerce")

    primary = tmp["type.primary"].fillna("").astype(str).str.lower()
    tmp["is_shot"] = primary.eq("shot")
    tmp["is_goal"] = safe_bool(tmp.get("shot.isGoal"))

    body_part = tmp.get("shot.bodyPart", pd.Series("", index=tmp.index, dtype=object))
    body_part = body_part.fillna("").astype(str).str.lower()
    tmp["is_header_shot"] = tmp["is_shot"] & body_part.str.contains("head")
    tmp["is_header_goal"] = tmp["is_header_shot"] & tmp["is_goal"]
    tmp["shot_xg"] = safe_numeric(tmp.get("shot.xg"))
    tmp["event_id"] = pd.to_numeric(
        tmp.get("id", pd.Series(index=tmp.index, dtype=float)),
        errors="coerce",
    )
    tmp["possession_event_index"] = pd.to_numeric(
        tmp.get("possession.eventIndex", pd.Series(index=tmp.index, dtype=float)),
        errors="coerce",
    )

    minute = pd.to_numeric(tmp.get("minute"), errors="coerce").fillna(0)
    second = pd.to_numeric(tmp.get("second"), errors="coerce").fillna(0)
    tmp["event_time_seconds"] = (minute * 60) + second
    tmp["shot_player_name"] = tmp.get(
        "player.name", pd.Series("", index=tmp.index, dtype=object)
    )
    tmp["shot_player_id"] = pd.to_numeric(
        tmp.get("player.id", pd.Series(index=tmp.index, dtype=float)),
        errors="coerce",
    )

    sequence_summary = _summarize_corner_sequences(tmp, corners_df)
    merged = (
        corners_df.merge(sequence_summary, on=["id"], how="left")
        if not sequence_summary.empty
        else corners_df.copy()
    )
    for key, value in default_bool.items():
        if key not in merged.columns:
            merged[key] = value
        merged[key] = merged[key].fillna(value).astype(bool)
    for key, value in default_numeric.items():
        if key not in merged.columns:
            merged[key] = value
        merged[key] = pd.to_numeric(merged[key], errors="coerce").fillna(value)
    for key, value in default_text.items():
        if key not in merged.columns:
            merged[key] = value
        else:
            merged[key] = merged[key].where(merged[key].notna(), value)

    merged["possession_xg"] = merged["possession_xg"].astype(float).round(4)
    merged["first_shot_xg"] = merged["first_shot_xg"].astype(float).round(4)
    merged["first_shooter_id"] = pd.to_numeric(
        merged.get("first_shooter_id"), errors="coerce"
    )
    return merged


def empty_corner_summary() -> dict:
    return {
        "total": 0,
        "left_side": 0,
        "right_side": 0,
        "shot_assist_tag": 0,
        "assist_tag": 0,
        "loss_tag": 0,
        "possession_shot": 0,
        "possession_goal": 0,
        "possession_xg": 0.0,
        "first_shot_xg": 0.0,
        "possession_xg_per_corner": 0.0,
        "first_shot_xg_per_corner": 0.0,
        "possession_shot_rate_pct": 0.0,
        "possession_goal_rate_pct": 0.0,
    }


def summarize_corners(corner_df: pd.DataFrame) -> dict:
    if corner_df.empty:
        return empty_corner_summary()

    total = int(len(corner_df))
    possession_shot = int(corner_df["possession_shot"].sum())
    possession_goal = int(corner_df["possession_goal"].sum())
    possession_xg = round(
        float(corner_df.get("possession_xg", pd.Series(dtype=float)).sum()), 3
    )
    first_shot_xg = round(
        float(corner_df.get("first_shot_xg", pd.Series(dtype=float)).sum()), 3
    )
    return {
        "total": total,
        "left_side": int((corner_df["side"] == "left").sum()),
        "right_side": int((corner_df["side"] == "right").sum()),
        "shot_assist_tag": int(corner_df["tag_shot_assist"].sum()),
        "assist_tag": int(corner_df["tag_assist"].sum()),
        "loss_tag": int(corner_df["tag_loss"].sum()),
        "possession_shot": possession_shot,
        "possession_goal": possession_goal,
        "possession_xg": possession_xg,
        "first_shot_xg": first_shot_xg,
        "possession_xg_per_corner": (
            round((possession_xg / total), 4) if total else 0.0
        ),
        "first_shot_xg_per_corner": (
            round((first_shot_xg / total), 4) if total else 0.0
        ),
        "possession_shot_rate_pct": (
            round((possession_shot / total) * 100, 2) if total else 0.0
        ),
        "possession_goal_rate_pct": (
            round((possession_goal / total) * 100, 2) if total else 0.0
        ),
    }


def corner_zone_breakdown(corner_df: pd.DataFrame) -> list[dict]:
    if corner_df.empty or "delivery_zone" not in corner_df.columns:
        return []

    grouped = (
        corner_df.groupby("delivery_zone", dropna=False)
        .agg(
            corners=("delivery_zone", "size"),
            possession_shot=("possession_shot", "sum"),
            possession_goal=("possession_goal", "sum"),
            possession_xg=("possession_xg", "sum"),
            first_shot_xg=("first_shot_xg", "sum"),
        )
        .reset_index()
    )

    rows = []
    for row in grouped.to_dict(orient="records"):
        corners = int(row.get("corners", 0) or 0)
        possession_shot = int(row.get("possession_shot", 0) or 0)
        possession_goal = int(row.get("possession_goal", 0) or 0)
        possession_xg = float(row.get("possession_xg", 0.0) or 0.0)
        first_shot_xg = float(row.get("first_shot_xg", 0.0) or 0.0)
        rows.append(
            {
                "delivery_zone": row.get("delivery_zone"),
                "corners": corners,
                "possession_shot": possession_shot,
                "possession_goal": possession_goal,
                "possession_xg": round(possession_xg, 3),
                "first_shot_xg": round(first_shot_xg, 3),
                "shot_rate_pct": (
                    round((possession_shot / corners) * 100, 2) if corners else 0.0
                ),
                "goal_rate_pct": (
                    round((possession_goal / corners) * 100, 2) if corners else 0.0
                ),
                "possession_xg_per_corner": (
                    round((possession_xg / corners), 4) if corners else 0.0
                ),
                "first_shot_xg_per_corner": (
                    round((first_shot_xg / corners), 4) if corners else 0.0
                ),
                "xg_per_corner": (
                    round((possession_xg / corners), 4) if corners else 0.0
                ),
            }
        )

    rows.sort(
        key=lambda item: (
            item["xg_per_corner"],
            item["shot_rate_pct"],
            item["corners"],
        ),
        reverse=True,
    )
    return rows


def corner_taker_impact(corner_df: pd.DataFrame, top_n: int = 8) -> dict:
    if corner_df.empty or "player.name" not in corner_df.columns:
        return {"top_takers_by_volume": [], "top_takers_by_xg_created": []}

    df = corner_df.copy()
    if "player.id" not in df.columns:
        df["player.id"] = None

    grouped = (
        df.groupby(["player.id", "player.name"], dropna=False)
        .agg(
            corners=("player.name", "size"),
            possession_shot=("possession_shot", "sum"),
            possession_goal=("possession_goal", "sum"),
            possession_xg=("possession_xg", "sum"),
            first_shot_xg=("first_shot_xg", "sum"),
            header_goals=("possession_header_goal_count", "sum"),
        )
        .reset_index()
    )

    grouped["player_id"] = pd.to_numeric(grouped["player.id"], errors="coerce")
    grouped["player_name"] = grouped["player.name"].fillna("Unknown")
    grouped["shot_rate_pct"] = (
        grouped["possession_shot"]
        .div(grouped["corners"].replace(0, pd.NA))
        .fillna(0)
        .mul(100)
        .round(2)
    )
    grouped["goal_rate_pct"] = (
        grouped["possession_goal"]
        .div(grouped["corners"].replace(0, pd.NA))
        .fillna(0)
        .mul(100)
        .round(2)
    )
    grouped["possession_xg_per_corner"] = (
        grouped["possession_xg"]
        .div(grouped["corners"].replace(0, pd.NA))
        .fillna(0)
        .round(4)
    )
    grouped["first_shot_xg_per_corner"] = (
        grouped["first_shot_xg"]
        .div(grouped["corners"].replace(0, pd.NA))
        .fillna(0)
        .round(4)
    )
    grouped["xg_per_corner"] = grouped["possession_xg_per_corner"]
    grouped["xg"] = grouped["possession_xg"].round(3)
    grouped["shots"] = grouped["possession_shot"].astype(int)
    grouped["goals"] = grouped["possession_goal"].astype(int)

    columns = [
        "player_id",
        "player_name",
        "corners",
        "possession_shot",
        "possession_goal",
        "header_goals",
        "possession_xg",
        "first_shot_xg",
        "xg",
        "shots",
        "goals",
        "possession_xg_per_corner",
        "first_shot_xg_per_corner",
        "xg_per_corner",
        "shot_rate_pct",
        "goal_rate_pct",
    ]

    by_volume = (
        grouped.sort_values(["corners", "possession_xg"], ascending=False)
        .head(top_n)[columns]
        .to_dict(orient="records")
    )
    by_xg = (
        grouped.sort_values(
            ["possession_xg", "xg_per_corner", "corners"], ascending=False
        )
        .head(top_n)[columns]
        .to_dict(orient="records")
    )
    by_first_shot_xg = (
        grouped.sort_values(
            ["first_shot_xg", "first_shot_xg_per_corner", "corners"],
            ascending=False,
        )
        .head(top_n)[columns]
        .to_dict(orient="records")
    )

    return {
        "top_takers_by_volume": by_volume,
        "top_takers_by_xg_created": by_xg,
        "top_takers_by_first_shot_xg": by_first_shot_xg,
    }


def corner_shooter_impact(
    events_df: pd.DataFrame, corner_df: pd.DataFrame, top_n: int = 8
) -> list[dict]:
    if events_df.empty or corner_df.empty:
        return []

    key_columns = ["matchId", "team.id", "possession.id"]
    if not set(key_columns).issubset(corner_df.columns) or not set(
        key_columns
    ).issubset(events_df.columns):
        return []

    keys = corner_df[key_columns].copy()
    for column in key_columns:
        keys[column] = pd.to_numeric(keys[column], errors="coerce")
    keys = keys.dropna(subset=key_columns).drop_duplicates()
    if keys.empty:
        return []

    tmp = events_df.copy()
    tmp["matchId"] = pd.to_numeric(tmp["matchId"], errors="coerce")
    tmp["team.id"] = pd.to_numeric(tmp["team.id"], errors="coerce")
    tmp["possession.id"] = pd.to_numeric(tmp["possession.id"], errors="coerce")

    primary = tmp.get("type.primary", pd.Series("", index=tmp.index, dtype=object))
    shots = tmp[primary.fillna("").astype(str).str.lower().eq("shot")].copy()
    if shots.empty:
        return []

    shots = shots.merge(keys, on=key_columns, how="inner")
    if shots.empty:
        return []

    shots["is_goal"] = safe_bool(shots.get("shot.isGoal"))
    body_part = shots.get(
        "shot.bodyPart", pd.Series("", index=shots.index, dtype=object)
    )
    shots["is_header"] = (
        body_part.fillna("").astype(str).str.lower().str.contains("head")
    )
    shots["is_header_goal"] = shots["is_header"] & shots["is_goal"]
    shots["xg"] = safe_numeric(shots.get("shot.xg"))
    shots["event_id"] = pd.to_numeric(
        shots.get("id", pd.Series(index=shots.index, dtype=float)),
        errors="coerce",
    )
    shots["possession_event_index"] = pd.to_numeric(
        shots.get("possession.eventIndex", pd.Series(index=shots.index, dtype=float)),
        errors="coerce",
    )
    minute = pd.to_numeric(shots.get("minute"), errors="coerce").fillna(0)
    second = pd.to_numeric(shots.get("second"), errors="coerce").fillna(0)
    shots["event_time_seconds"] = (minute * 60) + second
    shots = shots.sort_values(
        by=key_columns + ["event_time_seconds", "possession_event_index", "event_id"],
        ascending=True,
        na_position="last",
    )
    shots["is_first_shot"] = shots.groupby(key_columns, dropna=False).cumcount().eq(0)
    shots["first_shot_xg"] = shots["xg"].where(shots["is_first_shot"], 0.0)

    if "player.id" not in shots.columns:
        shots["player.id"] = None
    if "player.name" not in shots.columns:
        shots["player.name"] = "Unknown"

    grouped = (
        shots.groupby(["player.id", "player.name"], dropna=False)
        .agg(
            shots_after_corner=("is_goal", "size"),
            goals_after_corner=("is_goal", "sum"),
            header_shots_after_corner=("is_header", "sum"),
            header_goals_after_corner=("is_header_goal", "sum"),
            first_shots_after_corner=("is_first_shot", "sum"),
            xg_after_corner=("xg", "sum"),
            first_shot_xg_after_corner=("first_shot_xg", "sum"),
        )
        .reset_index()
    )

    grouped["player_id"] = pd.to_numeric(grouped["player.id"], errors="coerce")
    grouped["player_name"] = grouped["player.name"].fillna("Unknown")
    grouped["xg_after_corner"] = grouped["xg_after_corner"].round(3)
    grouped["first_shot_xg_after_corner"] = grouped[
        "first_shot_xg_after_corner"
    ].round(3)
    grouped["xg"] = grouped["xg_after_corner"]
    grouped["shots"] = grouped["shots_after_corner"].astype(int)
    grouped["goals"] = grouped["goals_after_corner"].astype(int)

    output = grouped[
        [
            "player_id",
            "player_name",
            "shots_after_corner",
            "goals_after_corner",
            "header_shots_after_corner",
            "header_goals_after_corner",
            "first_shots_after_corner",
            "xg_after_corner",
            "first_shot_xg_after_corner",
            "xg",
            "shots",
            "goals",
        ]
    ].sort_values(["xg_after_corner", "shots_after_corner"], ascending=False)

    return output.head(top_n).to_dict(orient="records")


def build_corner_storylines(
    team_name: str,
    offensive_summary: dict,
    zone_rows: list[dict],
    takers: dict,
    shooters: list[dict],
) -> list[str]:
    if int(offensive_summary.get("total", 0) or 0) == 0:
        return [f"No corners available yet for {team_name}."]

    lines = []
    total = int(offensive_summary.get("total", 0) or 0)
    left = int(offensive_summary.get("left_side", 0) or 0)
    right = int(offensive_summary.get("right_side", 0) or 0)
    dominant_side = "right" if right >= left else "left"
    dominant_share = round((max(left, right) / total) * 100, 1) if total else 0.0
    lines.append(
        f"{team_name} takes {dominant_share}% of corners from the {dominant_side} side ({max(left, right)}/{total})."
    )

    shot_rate = float(offensive_summary.get("possession_shot_rate_pct", 0.0) or 0.0)
    goal_rate = float(offensive_summary.get("possession_goal_rate_pct", 0.0) or 0.0)
    lines.append(
        f"Corner sequences produce shots at {shot_rate:.2f}% and goals at {goal_rate:.2f}% for {team_name}."
    )

    first_shot_xg_total = float(offensive_summary.get("first_shot_xg", 0.0) or 0.0)
    possession_xg_total = float(offensive_summary.get("possession_xg", 0.0) or 0.0)
    recycled_xg_total = max(possession_xg_total - first_shot_xg_total, 0.0)
    if recycled_xg_total <= 0.005:
        lines.append(
            f"Corner sequences create {possession_xg_total:.2f} total xG for {team_name}, and all of it comes from the first shot in this sample."
        )
    else:
        lines.append(
            f"Corner sequences create {first_shot_xg_total:.2f} first-shot xG and {possession_xg_total:.2f} full-sequence xG for {team_name}, with {recycled_xg_total:.2f} added after the first attempt."
        )

    if zone_rows:
        best_zone = zone_rows[0]
        zone_first_shot_xg = float(best_zone.get("first_shot_xg_per_corner", 0.0) or 0.0)
        zone_total_xg = float(
            best_zone.get("possession_xg_per_corner", best_zone.get("xg_per_corner", 0.0))
            or 0.0
        )
        zone_recycled_xg = max(zone_total_xg - zone_first_shot_xg, 0.0)
        if zone_recycled_xg <= 0.0005:
            lines.append(
                f"Most dangerous delivery zone: {best_zone.get('delivery_zone')} ({zone_total_xg:.3f} total xG per corner, all from the first shot in this sample)."
            )
        else:
            lines.append(
                f"Most dangerous delivery zone: {best_zone.get('delivery_zone')} ({zone_first_shot_xg:.3f} first-shot xG and {zone_total_xg:.3f} total xG per corner)."
            )

    top_takers = (
        takers.get("top_takers_by_xg_created", []) if isinstance(takers, dict) else []
    )
    if top_takers:
        leader = top_takers[0]
        leader_total_xg = float(leader.get("possession_xg", 0.0) or 0.0)
        leader_first_xg = float(leader.get("first_shot_xg", 0.0) or 0.0)
        leader_recycled_xg = max(leader_total_xg - leader_first_xg, 0.0)
        if leader_recycled_xg <= 0.005:
            lines.append(
                f"Primary value creator: {leader.get('player_name')} with {leader_total_xg:.2f} total xG created from corners, all from first-shot outcomes in this sample."
            )
        else:
            lines.append(
                f"Primary value creator: {leader.get('player_name')} with {leader_first_xg:.2f} first-shot xG and {leader_total_xg:.2f} total xG created from corners."
            )

    if shooters:
        target = shooters[0]
        target_total_xg = float(target.get("xg_after_corner", 0.0) or 0.0)
        target_first_xg = float(target.get("first_shot_xg_after_corner", 0.0) or 0.0)
        target_recycled_xg = max(target_total_xg - target_first_xg, 0.0)
        if target_recycled_xg <= 0.005:
            lines.append(
                f"Main corner target: {target.get('player_name')} with {target_total_xg:.2f} total xG after corners, all from the first shot in this sample."
            )
        else:
            lines.append(
                f"Main corner target: {target.get('player_name')} with {target_first_xg:.2f} first-shot xG and {target_total_xg:.2f} total xG after corners."
            )

    return lines


def build_corner_analysis(events_df: pd.DataFrame, team_id, team_name: str) -> dict:
    corners = build_corner_dataframe(events_df)
    corners = annotate_corner_possession_outcomes(events_df, corners)
    if corners.empty:
        return {
            "offensive_summary": empty_corner_summary(),
            "defensive_summary": empty_corner_summary(),
            "offensive_df": pd.DataFrame(),
            "defensive_df": pd.DataFrame(),
            "offensive_zones": [],
            "defensive_zones": [],
            "offensive_takers": {
                "top_takers_by_volume": [],
                "top_takers_by_xg_created": [],
            },
            "defensive_takers": {
                "top_takers_by_volume": [],
                "top_takers_by_xg_created": [],
            },
            "offensive_shooters": [],
            "defensive_shooters": [],
            "offensive_storylines": [f"No corners available yet for {team_name}."],
            "defensive_storylines": [f"No corners available yet against {team_name}."],
        }

    mask = team_event_mask(corners, team_id, team_name)
    offensive = corners[mask].copy()
    defensive = corners[~mask].copy()

    offensive_summary = summarize_corners(offensive)
    defensive_summary = summarize_corners(defensive)
    offensive_zones = corner_zone_breakdown(offensive)
    defensive_zones = corner_zone_breakdown(defensive)
    offensive_takers = corner_taker_impact(offensive)
    defensive_takers = corner_taker_impact(defensive)
    offensive_shooters = corner_shooter_impact(events_df, offensive)
    defensive_shooters = corner_shooter_impact(events_df, defensive)

    offensive_storylines = build_corner_storylines(
        team_name,
        offensive_summary,
        offensive_zones,
        offensive_takers,
        offensive_shooters,
    )
    defensive_storylines = build_corner_storylines(
        f"Opponents vs {team_name}",
        defensive_summary,
        defensive_zones,
        defensive_takers,
        defensive_shooters,
    )

    return {
        "offensive_summary": offensive_summary,
        "defensive_summary": defensive_summary,
        "offensive_df": offensive,
        "defensive_df": defensive,
        "offensive_zones": offensive_zones,
        "defensive_zones": defensive_zones,
        "offensive_takers": offensive_takers,
        "defensive_takers": defensive_takers,
        "offensive_shooters": offensive_shooters,
        "defensive_shooters": defensive_shooters,
        "offensive_storylines": offensive_storylines,
        "defensive_storylines": defensive_storylines,
    }
