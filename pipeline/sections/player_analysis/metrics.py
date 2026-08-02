"""Player-analysis specific analytics: position bucketing and stat benchmarks."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


POSITION_BUCKETS: dict[str, str] = {
    "gk": "goalkeeper",
    "cb": "centre_back",
    "lcb": "centre_back",
    "rcb": "centre_back",
    "lcb3": "centre_back",
    "rcb3": "centre_back",
    "lb": "fullback_wingback",
    "rb": "fullback_wingback",
    "lb5": "fullback_wingback",
    "rb5": "fullback_wingback",
    "lwb": "fullback_wingback",
    "rwb": "fullback_wingback",
    "dmf": "defensive_midfielder",
    "ldmf": "defensive_midfielder",
    "rdmf": "defensive_midfielder",
    "lcmf": "centre_midfielder",
    "rcmf": "centre_midfielder",
    "lcmf3": "centre_midfielder",
    "rcmf3": "centre_midfielder",
    "amf": "attacking_midfielder",
    "lamf": "attacking_midfielder",
    "ramf": "attacking_midfielder",
    "lw": "winger",
    "rw": "winger",
    "lwf": "winger",
    "rwf": "winger",
    "cf": "striker",
}

PLAYER_STAT_GROUPS: tuple[str, ...] = ("average", "percent")


def bucket_player_position(position_code: str | None) -> str | None:
    """Map a specific Wyscout position code (e.g. 'cf', 'lb') to a radar position bucket."""
    if not position_code:
        return None
    return POSITION_BUCKETS.get(str(position_code).strip().lower())


def _flatten_player_stat_groups(stats: dict) -> dict[str, float]:
    flattened: dict[str, float] = {}
    for group in PLAYER_STAT_GROUPS:
        section = stats.get(group)
        if not isinstance(section, dict):
            continue
        for key, value in section.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                flattened[f"{group}.{key}"] = float(value)
    return flattened


def compute_position_stat_benchmarks(
    players: list[dict],
    advanced_stats_by_player_id: dict[int, dict],
) -> dict[str, dict[str, dict[str, float]]]:
    """Compute per-position league-context benchmarks for each advanced stat.

    Players are bucketed by their primary position from advanced stats (the position
    where they spent the highest share of minutes). The 8 buckets are: goalkeeper,
    centre_back, fullback_wingback, defensive_midfielder, centre_midfielder,
    attacking_midfielder, winger, striker.
    For each stat, returns the 25th/50th/75th percentile and the max (q4) value
    within that position group, matching the 4 radar quadrant boundaries.
    """
    unique_buckets = dict.fromkeys(POSITION_BUCKETS.values())
    values_by_position: dict[str, dict[str, list[float]]] = {b: {} for b in unique_buckets}
    general_values: dict[str, list[float]] = {}

    for player in players:
        if not isinstance(player, dict):
            continue
        wy_id = player.get("wyId") or player.get("id")
        try:
            wy_id = int(wy_id)
        except Exception:
            continue

        stats = advanced_stats_by_player_id.get(wy_id)
        if not isinstance(stats, dict):
            continue

        flat = _flatten_player_stat_groups(stats)

        positions = stats.get("positions") or []
        primary_code = None
        if positions:
            primary = max(positions, key=lambda p: p.get("percent", 0))
            primary_code = ((primary.get("position") or {}).get("code") or "").lower() or None
        position = bucket_player_position(primary_code)
        if position is not None:
            for stat_key, value in flat.items():
                values_by_position[position].setdefault(stat_key, []).append(value)

        for stat_key, value in flat.items():
            general_values.setdefault(stat_key, []).append(value)

    def _compute_group(stat_values: dict[str, list[float]]) -> dict[str, dict[str, float]]:
        result: dict[str, dict[str, float]] = {}
        for stat_key, values in stat_values.items():
            series = pd.Series(values, dtype=float)
            result[stat_key] = {
                "q1": float(series.quantile(0.25)),
                "q2": float(series.quantile(0.50)),
                "q3": float(series.quantile(0.75)),
                "max": float(series.max()),
                "sample_size": int(series.shape[0]),
            }
        return result

    benchmarks: dict[str, dict[str, dict[str, float]]] = {}
    for position, stat_values in values_by_position.items():
        benchmarks[position] = _compute_group(stat_values)
    benchmarks["general"] = _compute_group(general_values)

    return benchmarks


def load_player_shots(player_id: int, events_dir: Path) -> "pd.DataFrame":
    """Scan cached match event files and return all shot events for one player.

    Returns a DataFrame with columns:
        x, y            — shot location on the 100×100 custom pitch
        xg              — expected goals value
        is_goal         — whether the shot resulted in a goal
        on_target       — whether the shot was on target
        body_part       — "head_or_other" or "right_foot" / "left_foot"
        inside_box      — True when x ≥ 83 and 18 ≤ y ≤ 82
    """
    rows = []
    for f in Path(events_dir).glob("match_*.json"):
        data = json.loads(f.read_text(encoding="utf-8"))
        for evt in data.get("events", []):
            if (evt.get("player") or {}).get("id") != player_id:
                continue
            if (evt.get("type") or {}).get("primary") != "shot":
                continue
            shot = evt.get("shot") or {}
            loc = evt.get("location") or {}
            x = float(loc.get("x") or 0)
            y = float(loc.get("y") or 0)
            rows.append({
                "x": x,
                "y": y,
                "xg": float(shot.get("xg") or 0.0),
                "is_goal": bool(shot.get("isGoal", False)),
                "on_target": bool(shot.get("onTarget", False)),
                "body_part": shot.get("bodyPart", ""),
                "inside_box": x >= 83 and 18 <= y <= 82,
            })
    return pd.DataFrame(rows)


def load_player_dribbles(player_id: int, events_dir: Path) -> "pd.DataFrame":
    """Scan cached match event files and return all dribble attempts for one player.

    A dribble is any offensive ground duel with 'dribble' in its secondary
    types — i.e. a 1v1 challenge where the player attempted to beat a defender.
    Success is determined by groundDuel.keptPossession.

    End location is derived from the related event (relatedEventId): for a
    successful dribble this is the player's next action (pass, shot, carry),
    for a failed one it is where the defender regained the ball.  Falls back
    to the start location when the related event is missing.

    Returns a DataFrame with columns:
        x, y            — dribble start on the 100×100 pitch
        end_x, end_y    — dribble end (from relatedEventId.location)
        successful      — True when the player kept possession
    """
    rows = []
    for f in Path(events_dir).glob("match_*.json"):
        data = json.loads(f.read_text(encoding="utf-8"))
        events_by_id = {e["id"]: e for e in data.get("events", [])}
        for evt in data.get("events", []):
            if (evt.get("player") or {}).get("id") != player_id:
                continue
            if (evt.get("type") or {}).get("primary") != "duel":
                continue
            secondary = (evt.get("type") or {}).get("secondary") or []
            if "dribble" not in secondary or "offensive_duel" not in secondary:
                continue
            loc = evt.get("location") or {}
            gd = evt.get("groundDuel") or {}
            x = float(loc.get("x") or 0)
            y = float(loc.get("y") or 0)

            related = events_by_id.get(evt.get("relatedEventId"))
            end_loc = (related or {}).get("location") or {}
            end_x = float(end_loc.get("x") or x)
            end_y = float(end_loc.get("y") or y)

            rows.append({
                "x": x,
                "y": y,
                "end_x": end_x,
                "end_y": end_y,
                "successful": bool(gd.get("keptPossession", False)),
            })
    return pd.DataFrame(rows)


_SET_PIECE_PRIMARIES = {"corner", "goal_kick", "free_kick", "throw_in", "penalty"}


def load_player_open_play_actions(player_id: int, events_dir: Path) -> "pd.DataFrame":
    """Scan cached match event files and return all open-play actions for one player.

    Set pieces (corner, goal_kick, free_kick, throw_in, penalty) are excluded.
    Events without a location are skipped.

    Returns a DataFrame with columns:
        x, y         — action location on the 100×100 pitch
        event_type   — primary event type string
    """
    rows = []
    for f in Path(events_dir).glob("match_*.json"):
        data = json.loads(f.read_text(encoding="utf-8"))
        for evt in data.get("events", []):
            if (evt.get("player") or {}).get("id") != player_id:
                continue
            primary = (evt.get("type") or {}).get("primary") or ""
            if primary in _SET_PIECE_PRIMARIES:
                continue
            loc = evt.get("location") or {}
            x = loc.get("x")
            y = loc.get("y")
            if x is None or y is None:
                continue
            rows.append({"x": float(x), "y": float(y), "event_type": primary})
    return pd.DataFrame(rows)


def load_player_passes(player_id: int, events_dir: Path) -> "pd.DataFrame":
    """Scan cached match event files and return all pass events for one player.

    Returns a DataFrame with columns:
        x, y       — pass origin on the 100×100 pitch
        accurate   — whether the pass was marked accurate
    """
    rows = []
    for f in Path(events_dir).glob("match_*.json"):
        data = json.loads(f.read_text(encoding="utf-8"))
        for evt in data.get("events", []):
            if (evt.get("player") or {}).get("id") != player_id:
                continue
            if (evt.get("type") or {}).get("primary") != "pass":
                continue
            loc = evt.get("location") or {}
            pass_data = evt.get("pass") or {}
            end_loc = pass_data.get("endLocation") or {}
            rows.append({
                "x": float(loc.get("x") or 0),
                "y": float(loc.get("y") or 0),
                "end_x": float(end_loc.get("x") or 0),
                "end_y": float(end_loc.get("y") or 0),
                "accurate": bool(pass_data.get("accurate", False)),
            })
    return pd.DataFrame(rows)


def load_player_key_passes(player_id: int, events_dir: Path) -> "pd.DataFrame":
    """Scan cached match event files and return all key passes for one player.

    A key pass is any pass whose secondary types include 'key_pass',
    'shot_assist', or 'assist'. Rows where 'assist' is present are flagged
    as actual goal assists.

    Returns a DataFrame with columns:
        x, y            — pass origin on the 100×100 pitch
        end_x, end_y    — pass destination (where the shot was taken from)
        is_assist       — True when the pass directly led to a goal
        accurate        — whether the pass was marked accurate
    """
    rows = []
    for f in Path(events_dir).glob("match_*.json"):
        data = json.loads(f.read_text(encoding="utf-8"))
        for evt in data.get("events", []):
            if (evt.get("player") or {}).get("id") != player_id:
                continue
            secondary = (evt.get("type") or {}).get("secondary") or []
            if not any(s in secondary for s in ("key_pass", "shot_assist", "assist")):
                continue
            loc = evt.get("location") or {}
            pass_data = evt.get("pass") or {}
            end_loc = pass_data.get("endLocation") or {}
            rows.append({
                "x": float(loc.get("x") or 0),
                "y": float(loc.get("y") or 0),
                "end_x": float(end_loc.get("x") or 0),
                "end_y": float(end_loc.get("y") or 0),
                "is_assist": "assist" in secondary,
                "accurate": bool(pass_data.get("accurate", False)),
            })
    return pd.DataFrame(rows)
