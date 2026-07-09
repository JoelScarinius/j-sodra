"""Player-analysis specific analytics: position bucketing and stat benchmarks."""

from __future__ import annotations

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
