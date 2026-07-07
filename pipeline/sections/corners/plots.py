"""Corner section plots.

This file owns visualisations for the Corners dashboard section.
Pitch-based football plots should use mplsoccer and the shared repo colours
from settings.plot_style.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import fill

import numpy as np
import pandas as pd

try:
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap
    from matplotlib.lines import Line2D
except Exception:
    plt = None
    LinearSegmentedColormap = None
    Line2D = None

try:
    from mplsoccer import VerticalPitch
except Exception:
    VerticalPitch = None


def _goal_zoom_pitch(style: dict[str, str]):
    if VerticalPitch is None or plt is None:
        return None
    return VerticalPitch(
        pitch_type="custom",
        pitch_length=100,
        pitch_width=100,
        half=True,
        pitch_color=style["bg"],
        line_color=style["line"],
        linewidth=1.6,
        goal_type="box",
        spot_type="square",
        corner_arcs=True,
        line_zorder=3,
        pad_left=-1.5,
        pad_right=-1.5,
        pad_top=1.5,
        pad_bottom=2.5,
    )


def _target_player_names(corner_df: pd.DataFrame) -> pd.Series:
    recipient = corner_df.get("pass.recipient.name")
    if recipient is None:
        recipient = pd.Series(index=corner_df.index, dtype=object)
    recipient = recipient.fillna("").astype(str).str.strip()
    recipient = recipient.mask(recipient.isin({"", "0", "nan", "None"}))

    shooter = corner_df.get("first_shooter_name")
    if shooter is None:
        shooter = pd.Series(index=corner_df.index, dtype=object)
    shooter = shooter.fillna("").astype(str).str.strip()
    shooter = shooter.mask(shooter.isin({"", "0", "nan", "None"}))

    return recipient.where(recipient.notna(), shooter)


def _plot_context_note(fig, text: str, style: dict[str, str]):
    fig.text(
        0.05,
        0.045,
        fill(text, width=130),
        ha="left",
        va="bottom",
        color=style["text"],
        fontsize=9.5,
        bbox={
            "boxstyle": "round,pad=0.35",
            "facecolor": style["bg"],
            "edgecolor": style["line"],
            "alpha": 0.78,
        },
    )


def _recycled_xg_delta(row: dict, total_key: str, first_key: str) -> float:
    total_value = float(row.get(total_key, 0.0) or 0.0)
    first_value = float(row.get(first_key, 0.0) or 0.0)
    return max(total_value - first_value, 0.0)


def _max_recycled_xg(rows: list[dict], total_key: str, first_key: str) -> float:
    return max(
        (_recycled_xg_delta(row, total_key, first_key) for row in rows), default=0.0
    )


def _goal_zoom_label_slots() -> list[dict[str, float | str]]:
    y_positions = [0.37, 0.26, 0.15]
    slots: list[dict[str, float | str]] = []
    for text_x, column in ((0.055, "left"), (0.365, "center"), (0.685, "right")):
        for text_y in y_positions:
            slots.append(
                {
                    "text_x": text_x,
                    "text_y": text_y,
                    "ha": "left",
                    "va": "center",
                    "column": column,
                }
            )
    return slots


def _annotate_goal_zoom_labels(
    ax, label_items: list[dict[str, float | str]], style: dict[str, str]
):
    slots = _goal_zoom_label_slots()
    for label_item, slot in zip(label_items, slots):
        _add_goal_zoom_annotation(
            ax=ax,
            x=float(label_item["x"]),
            y=float(label_item["y"]),
            text=str(label_item["text"]),
            style=style,
            slot=slot,
        )


def _goal_zoom_display_xy(x: float, y: float) -> tuple[float, float]:
    # VerticalPitch uses displayed coordinates as (y, x) for our custom 100x100 feed.
    return y, x


def _add_goal_zoom_annotation(
    ax,
    x: float,
    y: float,
    text: str,
    style: dict[str, str],
    slot: dict[str, float | str],
):
    display_x, display_y = _goal_zoom_display_xy(x, y)
    return ax.annotate(
        text,
        xy=(display_x, display_y),
        xytext=(float(slot["text_x"]), float(slot["text_y"])),
        xycoords="data",
        textcoords="axes fraction",
        color=style["text"],
        fontsize=8,
        ha=str(slot["ha"]),
        va=str(slot["va"]),
        zorder=10,
        annotation_clip=False,
        bbox={
            "boxstyle": "round,pad=0.25",
            "facecolor": style["bg"],
            "edgecolor": style["line"],
            "alpha": 0.98,
        },
        arrowprops={
            "arrowstyle": "-",
            "color": style["line"],
            "lw": 0.95,
            "alpha": 0.72,
            "shrinkA": 0,
            "shrinkB": 0,
            "connectionstyle": "arc3,rad=0",
        },
    )


def _finalize_goal_zoom_figure(fig, title: str, style: dict[str, str]):
    fig.suptitle(title, color=style["line"], fontsize=15, y=0.97)
    fig.subplots_adjust(left=0.04, right=0.98, top=0.86, bottom=0.16)


def _apply_goal_zoom_crop(ax):
    _, top = ax.get_ylim()
    ax.set_ylim(64, top)


def _draw_goal_highlight(ax, style: dict[str, str]):
    goal_left = 44.6
    goal_right = 55.4
    goal_line = 100.0
    goal_depth = max(ax.get_ylim()) - 0.25
    ax.plot(
        [goal_left, goal_right],
        [goal_line, goal_line],
        color=style["line"],
        linewidth=3.0,
        zorder=7,
    )
    ax.plot(
        [goal_left, goal_left],
        [goal_line, goal_depth],
        color=style["line"],
        linewidth=2.2,
        zorder=7,
    )
    ax.plot(
        [goal_right, goal_right],
        [goal_line, goal_depth],
        color=style["line"],
        linewidth=2.2,
        zorder=7,
    )
    ax.plot(
        [goal_left, goal_right],
        [goal_depth, goal_depth],
        color=style["line"],
        linewidth=1.1,
        alpha=0.55,
        zorder=7,
    )


def _plot_pitch_message(ax, message: str, style: dict[str, str]):
    ax.text(
        50,
        50,
        message,
        ha="center",
        va="center",
        color=style["line"],
        fontsize=12,
        fontweight="bold",
    )


def _plot_corner_map(
    corner_df: pd.DataFrame, title: str, output_path: Path, style: dict[str, str]
):
    pitch = _goal_zoom_pitch(style)
    if pitch is None:
        return None

    fig, ax = pitch.draw(figsize=(11, 6.2))
    fig.patch.set_facecolor(style["bg"])
    ax.set_facecolor(style["bg"])

    if corner_df.empty:
        _plot_pitch_message(ax, "No corner data available", style)
    else:
        left = corner_df[corner_df["side"] == "left"]
        right = corner_df[corner_df["side"] == "right"]
        colors = (
            corner_df["side"]
            .map({"left": style["accent"], "right": style["accent_2"]})
            .fillna(style["line"])
        )
        marker_size = (
            pd.to_numeric(corner_df.get("possession_xg"), errors="coerce")
            .fillna(0)
            .mul(1400)
            .add(105)
        )
        pitch.scatter(
            corner_df["end_x"],
            corner_df["end_y"],
            ax=ax,
            c=colors,
            s=marker_size,
            edgecolors=style["bg"],
            linewidth=0.8,
            zorder=4,
        )

        if Line2D is not None:
            legend_handles = [
                Line2D(
                    [0],
                    [0],
                    marker="o",
                    color="none",
                    markerfacecolor=style["accent"],
                    markeredgecolor=style["bg"],
                    markersize=8,
                    label="Left-side corners",
                ),
                Line2D(
                    [0],
                    [0],
                    marker="o",
                    color="none",
                    markerfacecolor=style["accent_2"],
                    markeredgecolor=style["bg"],
                    markersize=8,
                    label="Right-side corners",
                ),
            ]
            ax.legend(
                handles=legend_handles,
                loc="upper left",
                frameon=True,
                facecolor=style["bg"],
                edgecolor=style["line"],
                labelcolor=style["line"],
            )

        shot_mask = (
            corner_df.get("possession_shot", pd.Series(False, index=corner_df.index))
            .fillna(False)
            .astype(bool)
        )
        goal_mask = (
            corner_df.get("possession_goal", pd.Series(False, index=corner_df.index))
            .fillna(False)
            .astype(bool)
        )

        if shot_mask.any():
            pitch.scatter(
                corner_df.loc[shot_mask, "end_x"],
                corner_df.loc[shot_mask, "end_y"],
                ax=ax,
                facecolors="none",
                edgecolors=style["line"],
                s=marker_size.loc[shot_mask] * 1.35,
                linewidth=1.2,
                zorder=5,
            )
        if goal_mask.any():
            pitch.scatter(
                corner_df.loc[goal_mask, "end_x"],
                corner_df.loc[goal_mask, "end_y"],
                ax=ax,
                c=style["danger"],
                s=marker_size.loc[goal_mask] * 1.5,
                marker="*",
                edgecolors=style["line"],
                linewidth=1.3,
                zorder=7,
            )

        targets = corner_df.copy()
        targets["target_player"] = _target_player_names(targets)
        targets = targets.dropna(subset=["target_player"])
        if not targets.empty:
            grouped_targets = targets.groupby("target_player", dropna=False)
            label_rows = (
                targets.groupby("target_player", dropna=False)
                .agg(
                    avg_end_x=("end_x", "mean"),
                    avg_end_y=("end_y", "mean"),
                    corners=("target_player", "size"),
                    possession_xg=("possession_xg", "sum"),
                )
                .reset_index()
                .sort_values(["possession_xg", "corners"], ascending=False)
                .head(5)
            )

            label_items = []
            representative_indices: list[int] = []
            for row in label_rows.itertuples(index=False):
                player_rows = grouped_targets.get_group(row.target_player).copy()
                player_rows["_distance_to_mean"] = np.square(
                    player_rows["end_x"] - float(row.avg_end_x)
                ) + np.square(player_rows["end_y"] - float(row.avg_end_y))
                player_rows["_xg_sort"] = pd.to_numeric(
                    player_rows.get("possession_xg"), errors="coerce"
                ).fillna(0.0)
                representative_row = player_rows.sort_values(
                    ["_distance_to_mean", "_xg_sort"], ascending=[True, False]
                ).iloc[0]

                representative_indices.append(int(representative_row.name))
                label_items.append(
                    {
                        "x": float(representative_row["end_x"]),
                        "y": float(representative_row["end_y"]),
                        "text": f"{row.target_player}\n{int(row.corners)} targets | {float(row.possession_xg):.2f} xG",
                    }
                )

            if representative_indices:
                representative_sizes = (
                    marker_size.loc[representative_indices].mul(1.35).add(80)
                )
                pitch.scatter(
                    corner_df.loc[representative_indices, "end_x"],
                    corner_df.loc[representative_indices, "end_y"],
                    ax=ax,
                    facecolors="none",
                    edgecolors=style["text"],
                    s=representative_sizes,
                    linewidth=1.8,
                    zorder=6,
                )

            _annotate_goal_zoom_labels(ax, label_items, style)

        _plot_context_note(
            fig,
            "Each dot is one corner landing point. Green dots are left-side corners, yellow dots are right-side corners. Larger circles mean more full corner-sequence xG. White ring = shot in the sequence. Red star = goal. Player callouts connect to representative circles, while the text totals all targets and full-sequence xG for that player.",
            style,
        )

    _finalize_goal_zoom_figure(fig, title, style)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=160, facecolor=style["bg"])
    plt.close(fig)
    return output_path


def _plot_corner_target_map(
    corner_df: pd.DataFrame, title: str, output_path: Path, style: dict[str, str]
):
    pitch = _goal_zoom_pitch(style)
    if pitch is None:
        return None

    fig, ax = pitch.draw(figsize=(11, 6.2))
    fig.patch.set_facecolor(style["bg"])
    ax.set_facecolor(style["bg"])

    if corner_df.empty:
        _plot_pitch_message(ax, "No target-player data available", style)
    else:
        targets = corner_df.copy()
        targets["target_player"] = _target_player_names(targets)
        targets = targets.dropna(subset=["target_player"])

        if targets.empty:
            _plot_pitch_message(ax, "No target-player data available", style)
        else:
            grouped = (
                targets.groupby("target_player", dropna=False)
                .agg(
                    avg_end_x=("end_x", "mean"),
                    avg_end_y=("end_y", "mean"),
                    corners=("target_player", "size"),
                    possession_shot=("possession_shot", "sum"),
                    possession_goal=("possession_goal", "sum"),
                    possession_xg=("possession_xg", "sum"),
                )
                .reset_index()
                .sort_values(
                    ["possession_xg", "corners", "possession_shot"], ascending=False
                )
                .head(6)
            )

            max_xg = max(float(grouped["possession_xg"].max()), 0.001)
            sizes = grouped["corners"].astype(float).mul(130).add(180)
            cmap_values = grouped["possession_xg"].astype(float).div(max_xg)

            pitch.scatter(
                grouped["avg_end_x"],
                grouped["avg_end_y"],
                ax=ax,
                c=cmap_values,
                cmap="YlOrRd",
                s=sizes,
                edgecolors=style["line"],
                linewidth=1.2,
                zorder=4,
            )

            shot_targets = grouped[grouped["possession_shot"] > 0]
            if not shot_targets.empty:
                pitch.scatter(
                    shot_targets["avg_end_x"],
                    shot_targets["avg_end_y"],
                    ax=ax,
                    facecolors="none",
                    edgecolors=style["line"],
                    s=shot_targets["corners"].astype(float).mul(150).add(230),
                    linewidth=1.4,
                    zorder=4.8,
                )

            goal_targets = grouped[grouped["possession_goal"] > 0]
            if not goal_targets.empty:
                pitch.scatter(
                    goal_targets["avg_end_x"],
                    goal_targets["avg_end_y"],
                    ax=ax,
                    c=style["danger"],
                    marker="*",
                    s=goal_targets["corners"].astype(float).mul(85).add(120),
                    edgecolors=style["line"],
                    linewidth=0.8,
                    zorder=5,
                )

            label_items = [
                {
                    "x": float(row.avg_end_x),
                    "y": float(row.avg_end_y),
                    "text": f"{row.target_player}\n{int(row.corners)} corners | {float(row.possession_xg):.2f} xG",
                }
                for row in grouped.itertuples(index=False)
            ]
            _annotate_goal_zoom_labels(ax, label_items, style)

            _plot_context_note(
                fig,
                "Each circle is one grouped target player placed at that player's average first-delivery target zone. Bigger circles mean more targeted corners, warmer colors mean more full corner-sequence xG, white ring = at least one shot from those corners, red star = at least one goal. Callout lines point to the player-average circle, not to a single delivery.",
                style,
            )

    _finalize_goal_zoom_figure(fig, title, style)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=160, facecolor=style["bg"])
    plt.close(fig)
    return output_path


def _plot_corner_end_threat_heatmap(
    corner_df: pd.DataFrame,
    title: str,
    output_path: Path,
    style: dict[str, str],
):
    pitch = _goal_zoom_pitch(style)
    if pitch is None:
        return None

    fig, ax = pitch.draw(figsize=(11, 6.2))
    fig.patch.set_facecolor(style["bg"])
    ax.set_facecolor(style["bg"])

    if corner_df.empty:
        _plot_pitch_message(ax, "No corner threat data available", style)
    else:
        values = pd.to_numeric(
            corner_df.get("possession_xg", pd.Series(1.0, index=corner_df.index)),
            errors="coerce",
        ).fillna(0.0)
        if values.sum() == 0:
            values = pd.Series(1.0, index=corner_df.index, dtype=float)

        end_x = pd.to_numeric(corner_df.get("end_x"), errors="coerce")
        end_y = pd.to_numeric(corner_df.get("end_y"), errors="coerce")
        valid_mask = end_x.notna() & end_y.notna()

        if not valid_mask.any():
            _plot_pitch_message(ax, "No corner threat data available", style)
        else:
            end_x = end_x.loc[valid_mask].astype(float)
            end_y = end_y.loc[valid_mask].astype(float)
            values = values.loc[valid_mask].astype(float)

            x_edges = np.linspace(64, 100, 43)
            y_edges = np.linspace(0, 100, 61)
            hotspot, _, _ = np.histogram2d(
                end_x,
                end_y,
                bins=(x_edges, y_edges),
                weights=values,
            )
            x_centers = 0.5 * (x_edges[:-1] + x_edges[1:])
            y_centers = 0.5 * (y_edges[:-1] + y_edges[1:])
            grid_x, grid_y = np.meshgrid(x_centers, y_centers, indexing="ij")

            cmap = (
                LinearSegmentedColormap.from_list(
                    "corner_threat",
                    [
                        style["muted"],
                        style["accent_2"],
                        style["accent"],
                        style["danger"],
                    ],
                )
                if LinearSegmentedColormap is not None
                else "YlOrRd"
            )
            max_hotspot = float(hotspot.max()) if hotspot.size else 0.0
            if max_hotspot > 0:
                normalized = hotspot / max_hotspot
                hotspot_mask = hotspot > 0
                if hotspot_mask.any():
                    hotspot_sizes = 110 + 780 * np.power(normalized[hotspot_mask], 0.92)
                    pitch.scatter(
                        grid_x[hotspot_mask],
                        grid_y[hotspot_mask],
                        ax=ax,
                        c=normalized[hotspot_mask],
                        cmap=cmap,
                        s=hotspot_sizes,
                        edgecolors=style["line"],
                        linewidth=0.22,
                        alpha=0.86,
                        zorder=2.5,
                    )

            pitch.scatter(
                end_x,
                end_y,
                ax=ax,
                c=style["line"],
                s=34,
                alpha=0.82,
                edgecolors=style["bg"],
                linewidth=0.65,
                zorder=4.8,
            )

            shot_mask = (
                corner_df.get(
                    "possession_shot", pd.Series(False, index=corner_df.index)
                )
                .fillna(False)
                .astype(bool)
            )
            goal_mask = (
                corner_df.get(
                    "possession_goal", pd.Series(False, index=corner_df.index)
                )
                .fillna(False)
                .astype(bool)
            )
            if shot_mask.any():
                pitch.scatter(
                    pd.to_numeric(corner_df.loc[shot_mask, "end_x"], errors="coerce"),
                    pd.to_numeric(corner_df.loc[shot_mask, "end_y"], errors="coerce"),
                    ax=ax,
                    facecolors="none",
                    edgecolors=style["line"],
                    s=86,
                    linewidth=1.0,
                    zorder=5.2,
                )
            if goal_mask.any():
                pitch.scatter(
                    pd.to_numeric(corner_df.loc[goal_mask, "end_x"], errors="coerce"),
                    pd.to_numeric(corner_df.loc[goal_mask, "end_y"], errors="coerce"),
                    ax=ax,
                    c=style["danger"],
                    s=120,
                    marker="*",
                    edgecolors=style["line"],
                    linewidth=0.8,
                    zorder=6,
                )

            _plot_context_note(
                fig,
                "Each hotspot circle is one occupied mini-zone, weighted by the total full corner-sequence xG from deliveries landing in that zone. Bigger and warmer circles mean more threat, not just more raw deliveries. Small pale dots are actual delivery end points, white rings mark shot-ending sequences, and red stars mark goal-ending sequences.",
                style,
            )

    _finalize_goal_zoom_figure(fig, title, style)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=160, facecolor=style["bg"])
    plt.close(fig)
    return output_path


def _plot_corner_player_impact_bar(
    rows: list[dict],
    title: str,
    output_path: Path,
    value_key: str,
    value_label: str,
    style: dict[str, str],
):
    if plt is None:
        return None

    fig, ax = plt.subplots(figsize=(10, 6))
    fig.patch.set_facecolor(style["bg"])
    ax.set_facecolor(style["bg"])

    if not rows:
        ax.text(
            0.5,
            0.5,
            "No data available",
            ha="center",
            va="center",
            transform=ax.transAxes,
            color=style["line"],
        )
    else:
        labels = [row.get("player_name", "Unknown") for row in rows][::-1]
        values = [float(row.get(value_key, 0) or 0) for row in rows][::-1]
        note = None
        colors = [
            style["accent"] if index % 2 == 0 else style["accent_2"]
            for index in range(len(labels))
        ]
        bars = ax.barh(labels, values, color=colors, alpha=0.92)
        max_value = max(max(values, default=0.0), 0.05)
        ax.set_xlim(0, max_value * 1.35)

        for bar, row, value in zip(bars, rows[::-1], values):
            details = []
            if "corners" in row:
                details.append(f"{int(row.get('corners', 0) or 0)} corners")
            if "possession_shot" in row and value_key == "possession_xg":
                details.append(
                    f"{int(row.get('possession_shot', 0) or 0)} shot-ending sequences"
                )
            if "first_shot_xg" in row and value_key == "possession_xg":
                recycled_xg = _recycled_xg_delta(row, "possession_xg", "first_shot_xg")
                if recycled_xg > 0.004:
                    details.append(f"+{recycled_xg:.2f} recycled xG")
            if "shots_after_corner" in row:
                details.append(f"{int(row.get('shots_after_corner', 0) or 0)} shots")
            if "first_shot_xg_after_corner" in row and value_key == "xg_after_corner":
                recycled_xg = _recycled_xg_delta(
                    row, "xg_after_corner", "first_shot_xg_after_corner"
                )
                if recycled_xg > 0.004:
                    details.append(f"+{recycled_xg:.2f} recycled xG")
            if "goals_after_corner" in row:
                details.append(f"{int(row.get('goals_after_corner', 0) or 0)} goals")

            detail_text = (
                f"{value:.2f} | {' | '.join(details)}" if details else f"{value:.2f}"
            )
            ax.text(
                bar.get_width() + (max_value * 0.03),
                bar.get_y() + (bar.get_height() / 2),
                detail_text,
                va="center",
                ha="left",
                color=style["line"],
                fontsize=9,
            )

        if value_key == "possession_xg":
            max_recycled_xg = _max_recycled_xg(rows, "possession_xg", "first_shot_xg")
            note = (
                "All listed takers have zero recycled-shot uplift in this sample, so total corner-sequence xG equals first-shot xG for every bar."
                if max_recycled_xg <= 0.004
                else "A '+ recycled xG' label marks extra threat from later shots after the first attempt in the same corner sequence."
            )
        elif value_key == "xg_after_corner":
            max_recycled_xg = _max_recycled_xg(
                rows, "xg_after_corner", "first_shot_xg_after_corner"
            )
            note = (
                "All listed finishers have zero recycled-shot uplift in this sample, so each bar is entirely first-shot xG."
                if max_recycled_xg <= 0.004
                else "A '+ recycled xG' label marks xG from later shots by the same finisher after the first attempt in that corner sequence."
            )

    ax.set_xlabel(value_label, color=style["line"])
    ax.tick_params(colors=style["line"])
    ax.grid(axis="x", color=style["line"], alpha=0.14)
    for spine in ax.spines.values():
        spine.set_color(style["line"])
    ax.set_title(title, color=style["line"], fontsize=14, pad=10)
    if rows:
        if note:
            fig.tight_layout(rect=(0, 0.09, 1, 1))
            _plot_context_note(fig, note, style)
        else:
            fig.tight_layout()
    else:
        fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=160, facecolor=style["bg"])
    plt.close(fig)
    return output_path


def _plot_corner_xg_method_comparison(
    rows: list[dict],
    title: str,
    output_path: Path,
    style: dict[str, str],
):
    if plt is None:
        return None

    fig, ax = plt.subplots(figsize=(10, 6))
    fig.patch.set_facecolor(style["bg"])
    ax.set_facecolor(style["bg"])

    if not rows:
        ax.text(
            0.5,
            0.5,
            "No data available",
            ha="center",
            va="center",
            transform=ax.transAxes,
            color=style["line"],
        )
    else:
        display_rows = rows[:6][::-1]
        labels = [row.get("player_name", "Unknown") for row in display_rows]
        total_values = [float(row.get("possession_xg", 0) or 0) for row in display_rows]
        first_values = [float(row.get("first_shot_xg", 0) or 0) for row in display_rows]
        recycled_values = [
            max(total_value - first_value, 0.0)
            for total_value, first_value in zip(total_values, first_values)
        ]
        positions = np.arange(len(labels), dtype=float)
        bar_height = 0.56
        max_value = max(total_values + first_values + [0.05])

        first_bars = ax.barh(
            positions,
            first_values,
            height=bar_height,
            color=style["accent_2"],
            alpha=0.9,
            label="First-shot xG",
        )
        recycled_bars = ax.barh(
            positions,
            recycled_values,
            left=first_values,
            height=bar_height,
            color=style["accent"],
            alpha=0.9,
            label="Extra recycled xG after first shot",
        )

        ax.set_yticks(positions, labels=labels)
        ax.set_xlim(0, max_value * 1.35)

        for bar, total_value, recycled_value in zip(
            first_bars,
            total_values,
            recycled_values,
        ):
            label = f"{total_value:.2f} total"
            if recycled_value > 0.004:
                label += f" | +{recycled_value:.2f} recycled"
            else:
                label += " | first-shot only"
            ax.text(
                total_value + (max_value * 0.03),
                bar.get_y() + (bar.get_height() / 2),
                label,
                va="center",
                ha="left",
                color=style["line"],
                fontsize=9,
            )

        ax.legend(
            facecolor=style["bg"],
            edgecolor=style["line"],
            labelcolor=style["line"],
        )

        if max(recycled_values, default=0.0) <= 0.004:
            _plot_context_note(
                fig,
                "No recycled-shot uplift appears in this sample: every plotted taker's total corner-sequence xG is fully explained by the first shot after the corner.",
                style,
            )
        else:
            _plot_context_note(
                fig,
                "Mint bars show first-shot xG and gold add-ons show extra xG from later shots in the same corner sequence, so the split only grows when recycled attacks create additional threat.",
                style,
            )

    ax.set_xlabel("Total corner-sequence xG", color=style["line"])
    ax.tick_params(colors=style["line"])
    ax.grid(axis="x", color=style["line"], alpha=0.14)
    for spine in ax.spines.values():
        spine.set_color(style["line"])
    ax.set_title(title, color=style["line"], fontsize=14, pad=10)
    fig.tight_layout(rect=(0, 0.09, 1, 1))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=160, facecolor=style["bg"])
    plt.close(fig)
    return output_path


def generate_corner_plots(
    *,
    settings,
    team_name: str,
    team_corner: dict,
    opponent_name: str | None,
    opponent_corner: dict,
) -> dict[str, Path]:
    """Generate all Corners section plots and return name -> path."""

    if VerticalPitch is None or plt is None:
        print("mplsoccer or matplotlib missing, skipping corner visualizations.")
        return {}

    style = settings.plot_style
    corner_dir = settings.report_path("corners", "plots")
    corner_dir.mkdir(parents=True, exist_ok=True)

    plots: dict[str, Path] = {}

    def store(name: str, path: Path | None):
        if path is not None:
            plots[name] = path

    store(
        "team_offensive_map",
        _plot_corner_map(
            team_corner.get("offensive_df", pd.DataFrame()),
            f"{team_name} offensive corners",
            corner_dir / "team_offensive_map.png",
            style,
        ),
    )
    store(
        "team_defensive_map",
        _plot_corner_map(
            team_corner.get("defensive_df", pd.DataFrame()),
            f"{team_name} defensive corners faced",
            corner_dir / "team_defensive_map.png",
            style,
        ),
    )
    store(
        "team_target_map",
        _plot_corner_target_map(
            team_corner.get("offensive_df", pd.DataFrame()),
            f"{team_name} corner target map",
            corner_dir / "team_target_map.png",
            style,
        ),
    )
    store(
        "team_danger_end_heatmap",
        _plot_corner_end_threat_heatmap(
            team_corner.get("offensive_df", pd.DataFrame()),
            f"{team_name} corner delivery danger map",
            corner_dir / "team_danger_end_heatmap.png",
            style,
        ),
    )
    store(
        "team_taker_impact",
        _plot_corner_player_impact_bar(
            team_corner.get("offensive_takers", {}).get("top_takers_by_xg_created", []),
            f"{team_name} corner takers by xG created",
            corner_dir / "team_taker_impact.png",
            "possession_xg",
            "xG created from full corner sequences",
            style,
        ),
    )
    store(
        "team_xg_method_comparison",
        _plot_corner_xg_method_comparison(
            team_corner.get("offensive_takers", {}).get("top_takers_by_xg_created", []),
            f"{team_name} corner xG split: first shot vs recycled threat",
            corner_dir / "team_xg_method_comparison.png",
            style,
        ),
    )
    store(
        "team_shooter_impact",
        _plot_corner_player_impact_bar(
            team_corner.get("offensive_shooters", []),
            f"{team_name} finishers after corners by xG",
            corner_dir / "team_shooter_impact.png",
            "xg_after_corner",
            "xG after corners",
            style,
        ),
    )

    if opponent_name:
        store(
            "next_opponent_offensive_map",
            _plot_corner_map(
                opponent_corner.get("offensive_df", pd.DataFrame()),
                f"{opponent_name} offensive corners",
                corner_dir / "next_opponent_offensive_map.png",
                style,
            ),
        )
        store(
            "next_opponent_defensive_map",
            _plot_corner_map(
                opponent_corner.get("defensive_df", pd.DataFrame()),
                f"{opponent_name} defensive corners faced",
                corner_dir / "next_opponent_defensive_map.png",
                style,
            ),
        )
        store(
            "next_opponent_target_map",
            _plot_corner_target_map(
                opponent_corner.get("offensive_df", pd.DataFrame()),
                f"{opponent_name} corner target map",
                corner_dir / "next_opponent_target_map.png",
                style,
            ),
        )
        store(
            "next_opponent_danger_end_heatmap",
            _plot_corner_end_threat_heatmap(
                opponent_corner.get("offensive_df", pd.DataFrame()),
                f"{opponent_name} corner delivery danger map",
                corner_dir / "next_opponent_danger_end_heatmap.png",
                style,
            ),
        )
        store(
            "next_opponent_taker_impact",
            _plot_corner_player_impact_bar(
                opponent_corner.get("offensive_takers", {}).get(
                    "top_takers_by_xg_created", []
                ),
                f"{opponent_name} corner takers by xG created",
                corner_dir / "next_opponent_taker_impact.png",
                "possession_xg",
                "xG created from full corner sequences",
                style,
            ),
        )
        store(
            "next_opponent_xg_method_comparison",
            _plot_corner_xg_method_comparison(
                opponent_corner.get("offensive_takers", {}).get(
                    "top_takers_by_xg_created", []
                ),
                f"{opponent_name} corner xG split: first shot vs recycled threat",
                corner_dir / "next_opponent_xg_method_comparison.png",
                style,
            ),
        )
        store(
            "next_opponent_shooter_impact",
            _plot_corner_player_impact_bar(
                opponent_corner.get("offensive_shooters", []),
                f"{opponent_name} finishers after corners by xG",
                corner_dir / "next_opponent_shooter_impact.png",
                "xg_after_corner",
                "xG after corners",
                style,
            ),
        )

    return plots
