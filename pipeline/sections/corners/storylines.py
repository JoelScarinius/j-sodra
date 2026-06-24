"""Corner section storylines.

This file owns coach-facing text and interpretation for the Corners dashboard
section. Keep wording changes here so analysts can improve the webpage text
without touching metric calculation or plot code.
"""

from __future__ import annotations


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
