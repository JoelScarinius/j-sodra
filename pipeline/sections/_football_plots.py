from __future__ import annotations

from pathlib import Path
from textwrap import fill

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.patches import Rectangle
from mplsoccer import Pitch, VerticalPitch

from pipeline.settings import PLOT_STYLE

STYLE = {
    **PLOT_STYLE,
    "panel": "#0b3427",
    "panel_alt": "#124735",
    "highlight": "#ffdc6e",
}


def _pitch() -> Pitch:
    return Pitch(
        pitch_type="custom",
        pitch_length=100,
        pitch_width=100,
        pitch_color=STYLE["bg"],
        line_color=STYLE["line"],
        linewidth=1.4,
        goal_type="box",
        spot_type="square",
        corner_arcs=True,
        line_zorder=3,
    )


def _vertical_half_pitch() -> VerticalPitch:
    return VerticalPitch(
        pitch_type="custom",
        pitch_length=100,
        pitch_width=100,
        half=True,
        pitch_color=STYLE["bg"],
        line_color=STYLE["line"],
        linewidth=1.5,
        goal_type="box",
        spot_type="square",
        corner_arcs=True,
        pad_left=-1.2,
        pad_right=-1.2,
        pad_top=1.2,
        pad_bottom=2.5,
        line_zorder=3,
    )


def _apply_canvas(fig, ax):
    fig.patch.set_facecolor(STYLE["bg"])
    ax.set_facecolor(STYLE["bg"])


def _pitch_figure(
    pitch,
    *,
    figsize: tuple[float, float],
    pitch_rect: tuple[float, float, float, float],
    footer_rect: tuple[float, float, float, float],
):
    fig = plt.figure(figsize=figsize, facecolor=STYLE["bg"])
    ax = fig.add_axes(pitch_rect)
    pitch.draw(ax=ax)
    _apply_canvas(fig, ax)

    footer_ax = fig.add_axes(footer_rect)
    footer_ax.set_facecolor(STYLE["bg"])
    footer_ax.set_xticks([])
    footer_ax.set_yticks([])
    for spine in footer_ax.spines.values():
        spine.set_visible(False)
    return fig, ax, footer_ax


def _add_header(fig, title: str, subtitle: str):
    fig.text(
        0.05,
        0.945,
        title,
        color=STYLE["text"],
        fontsize=24,
        fontweight="bold",
        ha="left",
        va="top",
    )
    fig.text(
        0.05,
        0.905,
        subtitle,
        color=STYLE["muted"],
        fontsize=11.5,
        ha="left",
        va="top",
    )


def _add_footer(footer_ax, lines: list[str], width: int = 125):
    footer_ax.add_patch(
        Rectangle(
            (0.0, 0.0),
            1.0,
            1.0,
            transform=footer_ax.transAxes,
            facecolor=STYLE["panel"],
            edgecolor=STYLE["line"],
            linewidth=1.0,
            alpha=0.82,
        )
    )
    footer_ax.text(
        0.018,
        0.84,
        fill("\n".join(line for line in lines if line), width=width),
        color=STYLE["text"],
        fontsize=10.0,
        ha="left",
        va="top",
        transform=footer_ax.transAxes,
    )


def _summary_lines(lines: list[str]) -> str:
    return "\n".join(line for line in lines if line)


def _save(fig, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=220, facecolor=STYLE["bg"])
    plt.close(fig)
    return output_path


def _short_name(name: str) -> str:
    parts = [part for part in str(name).split() if part]
    if len(parts) <= 1:
        return str(name)
    return f"{parts[0][0]}. {parts[-1]}"


def _numeric_spatial_rows(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Return rows with finite numeric coordinates for all requested columns."""
    if frame.empty or any(column not in frame.columns for column in columns):
        return frame.head(0).copy()
    result = frame.copy()
    for column in columns:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    finite = np.isfinite(result[columns].to_numpy(dtype=float)).all(axis=1)
    return result.loc[finite].copy()


def _empty_plot(ax, message: str) -> None:
    ax.text(
        50,
        50,
        message,
        color=STYLE["line"],
        fontsize=14,
        ha="center",
        va="center",
        fontweight="bold",
    )


def _draw_arrows(
    pitch,
    ax,
    frame: pd.DataFrame,
    *,
    xstart: str,
    ystart: str,
    xend: str,
    yend: str,
    color: str,
    alpha: float,
    width: float,
    zorder: int,
):
    if frame.empty:
        return
    pitch.arrows(
        frame[xstart],
        frame[ystart],
        frame[xend],
        frame[yend],
        ax=ax,
        color=color,
        alpha=alpha,
        width=width,
        headwidth=4.5,
        headlength=5.0,
        headaxislength=4.2,
        zorder=zorder,
    )


def _add_colorbar(fig, mappable, rect: tuple[float, float, float, float], label: str):
    cax = fig.add_axes(rect)
    cax.set_facecolor(STYLE["bg"])
    colorbar = fig.colorbar(mappable, cax=cax)
    colorbar.outline.set_edgecolor(STYLE["line"])
    colorbar.ax.yaxis.set_tick_params(color=STYLE["text"], labelcolor=STYLE["text"])
    colorbar.ax.set_ylabel(label, color=STYLE["text"], fontsize=9.5)
    plt.setp(colorbar.ax.get_yticklabels(), color=STYLE["text"], fontsize=8.5)
    return colorbar


def plot_progressive_passes(
    dataset, progressive_df: pd.DataFrame, output_path: Path
) -> Path:
    pitch = _pitch()
    fig, ax, footer_ax = _pitch_figure(
        pitch,
        figsize=(14, 10),
        pitch_rect=(0.05, 0.16, 0.86, 0.73),
        footer_rect=(0.05, 0.03, 0.90, 0.10),
    )

    progressive_df = _numeric_spatial_rows(
        progressive_df,
        ["start_x", "start_y", "pass_end_x", "pass_end_y"],
    )
    display_df = progressive_df.head(42).copy()
    secondary_df = display_df.iloc[12:].copy()
    highlight_df = display_df.head(12).copy()

    _draw_arrows(
        pitch,
        ax,
        secondary_df,
        xstart="start_x",
        ystart="start_y",
        xend="pass_end_x",
        yend="pass_end_y",
        color=STYLE["accent_2"],
        alpha=0.28,
        width=0.25,
        zorder=2,
    )
    _draw_arrows(
        pitch,
        ax,
        highlight_df,
        xstart="start_x",
        ystart="start_y",
        xend="pass_end_x",
        yend="pass_end_y",
        color=STYLE["accent"],
        alpha=0.92,
        width=0.38,
        zorder=4,
    )
    if not highlight_df.empty:
        pitch.scatter(
            highlight_df["start_x"],
            highlight_df["start_y"],
            s=28,
            color=STYLE["accent_2"],
            edgecolors=STYLE["line"],
            linewidth=0.6,
            alpha=0.92,
            ax=ax,
            zorder=5,
        )
        pitch.scatter(
            highlight_df["pass_end_x"],
            highlight_df["pass_end_y"],
            s=55 + highlight_df["progression_gain"].clip(lower=0) * 2.2,
            color=STYLE["highlight"],
            edgecolors=STYLE["line"],
            linewidth=0.7,
            alpha=0.94,
            ax=ax,
            zorder=6,
        )

    if progressive_df.empty:
        subtitle = (
            f"{dataset.team_name} | {dataset.competition_label} | {dataset.season_label}"
        )
        _empty_plot(ax, "No located progressive-pass data available")
        _add_header(fig, "Progressive Pass Map", subtitle)
        _add_footer(
            footer_ax,
            [
                "What it shows: located accurate open-play progressive passes in the selected scope.",
                "No valid progressive-pass coordinates are available, so no count, player ranking, or average gain is inferred.",
            ],
            width=130,
        )
        return _save(fig, output_path)

    top_players = (
        progressive_df.groupby("player_name")
        .size()
        .sort_values(ascending=False)
        .head(4)
    )
    final_third_entries = int(progressive_df["pass_end_x"].ge(75).sum())
    subtitle = (
        f"{dataset.team_name} | {dataset.competition_label} | {dataset.season_label}"
    )
    _add_header(fig, "Progressive Pass Map", subtitle)
    _add_footer(
        footer_ax,
        [
            "What it shows: up to 42 of the largest located accurate open-play progressive passes in the selected scope, ranked by forward gain.",
            "Arrow start = pass origin. Arrow head = reception point. Gold arrows are the 12 biggest gains; green arrows are the next 30.",
            f"Scope total: {len(progressive_df)} located progressive passes | Final-third entries: {final_third_entries} | Mean forward gain: {progressive_df['progression_gain'].mean():.1f} pitch points" if not progressive_df.empty else "No located progressive passes are available for this scope.",
            "Most frequent progressive passers: "
            + ", ".join(
                f"{_short_name(name)} ({count})" for name, count in top_players.items()
            ),
        ],
        width=130,
    )
    return _save(fig, output_path)


def plot_defensive_actions(
    dataset, defensive_df: pd.DataFrame, output_path: Path
) -> Path:
    pitch = _pitch()
    fig, ax, footer_ax = _pitch_figure(
        pitch,
        figsize=(14, 10),
        pitch_rect=(0.05, 0.16, 0.86, 0.73),
        footer_rect=(0.05, 0.03, 0.90, 0.10),
    )

    defensive_df = _numeric_spatial_rows(defensive_df, ["start_x", "start_y"])
    if defensive_df.empty:
        _empty_plot(ax, "No located defensive-action data available")
        subtitle = f"{dataset.team_name} | {dataset.competition_label} | {dataset.season_label}"
        _add_header(fig, "Defensive Action Heatmap", subtitle)
        _add_footer(
            footer_ax,
            [
                "What it shows: the locations of provider-classified defensive actions in the selected scope.",
                "No valid defensive-action coordinates are available, so no value is inferred or plotted as zero.",
            ],
        )
        return _save(fig, output_path)
    cmap = LinearSegmentedColormap.from_list(
        "j_sodra_heat",
        [STYLE["bg"], STYLE["panel_alt"], STYLE["accent_2"], STYLE["highlight"]],
    )
    heat = pitch.bin_statistic(
        defensive_df["start_x"],
        defensive_df["start_y"],
        statistic="count",
        bins=(18, 12),
    )
    heatmap = pitch.heatmap(heat, ax=ax, cmap=cmap, edgecolors=STYLE["bg"], alpha=0.96)
    _add_colorbar(fig, heatmap, (0.92, 0.22, 0.018, 0.58), "Defensive actions per zone")

    high_regains = defensive_df[defensive_df["high_regain"]].copy()
    mix = defensive_df.groupby("action_family").size().sort_values(ascending=False)
    average_height = (
        float(defensive_df["start_x"].mean()) if not defensive_df.empty else 0.0
    )
    own_third_share = float(defensive_df["start_x"].le(33.3).mean() * 100.0)
    high_regain_share = float(high_regains.shape[0] / max(len(defensive_df), 1) * 100.0)
    subtitle = (
        f"{dataset.team_name} | {dataset.competition_label} | {dataset.season_label}"
    )
    _add_header(fig, "Defensive Action Heatmap", subtitle)
    _add_footer(
        footer_ax,
        [
            f"What it shows: where {dataset.team_name} made located defensive actions in the selected scope.",
            "Each square counts interceptions, recoveries, defensive duels, clearances, and goalkeeper exits. Brighter squares mean more actions in that zone.",
            f"Total actions: {len(defensive_df)} | Average defensive height: {average_height:.1f}m | High-regain share (x >= 60): {high_regain_share:.0f}% | Own-third share: {own_third_share:.0f}%",
            "Action mix: "
            + ", ".join(f"{label} {count}" for label, count in mix.items()),
        ],
        width=132,
    )
    return _save(fig, output_path)


def plot_pass_network(
    dataset,
    network: dict[str, pd.DataFrame],
    output_path: Path,
) -> Path:
    positions = network.get("positions", pd.DataFrame())
    links = network.get("links", pd.DataFrame())
    passes = network.get("passes", pd.DataFrame())
    meta = network.get("meta", {}) or {}

    pitch = _pitch()
    fig, ax, footer_ax = _pitch_figure(
        pitch,
        figsize=(14, 10),
        pitch_rect=(0.05, 0.16, 0.86, 0.73),
        footer_rect=(0.05, 0.03, 0.90, 0.10),
    )

    if not links.empty:
        merged = links.merge(
            positions[["player_name", "average_x", "average_y"]],
            left_on="player_a",
            right_on="player_name",
            how="left",
        ).rename(columns={"average_x": "x_a", "average_y": "y_a"})
        merged = merged.drop(columns=["player_name"])
        merged = merged.merge(
            positions[["player_name", "average_x", "average_y"]],
            left_on="player_b",
            right_on="player_name",
            how="left",
        ).rename(columns={"average_x": "x_b", "average_y": "y_b"})
        merged = merged.drop(columns=["player_name"])
        scale = max(float(merged["pass_count"].max()), 1.0)
        widths = 1.5 + (merged["pass_count"] / scale) * 7.0
        pitch.lines(
            merged["x_a"],
            merged["y_a"],
            merged["x_b"],
            merged["y_b"],
            lw=widths,
            color=STYLE["accent_2"],
            alpha=0.45,
            ax=ax,
            zorder=2,
        )

    if not positions.empty:
        node_scale = max(float(positions["touches"].max()), 1.0)
        sizes = 220 + (positions["touches"] / node_scale) * 1200
        pitch.scatter(
            positions["average_x"],
            positions["average_y"],
            s=sizes,
            color=STYLE["accent"],
            edgecolors=STYLE["line"],
            linewidth=1.1,
            alpha=0.95,
            ax=ax,
            zorder=4,
        )
        for row in positions.itertuples(index=False):
            label_x = float(row.average_x) + (
                2.1 if float(row.average_x) < 74 else -2.1
            )
            label_y = float(row.average_y) + (
                1.8 if float(row.average_y) <= 50 else -1.8
            )
            ax.text(
                label_x,
                label_y,
                _short_name(row.player_name),
                color=STYLE["text"],
                fontsize=8.7,
                ha="left" if float(row.average_x) < 74 else "right",
                va="center",
                fontweight="bold",
                bbox={
                    "boxstyle": "round,pad=0.18",
                    "facecolor": STYLE["panel"],
                    "edgecolor": "none",
                    "alpha": 0.78,
                },
                zorder=5,
            )

    subtitle = f"{dataset.latest_match_label or dataset.team_name}"
    strongest_link = meta.get("strongest_link") if isinstance(meta, dict) else None
    strongest_text = None
    if isinstance(strongest_link, dict):
        strongest_text = (
            f"Strongest link: {_short_name(strongest_link['player_a'])} - "
            f"{_short_name(strongest_link['player_b'])} ({strongest_link['pass_count']})"
        )
    network_height = meta.get("network_height") if isinstance(meta, dict) else None
    _add_header(fig, "Latest-Match Pass Network", subtitle)
    _add_footer(
        footer_ax,
        [
            "What it shows: accurate open-play passes between the 11 most involved J-Sodra players from the latest match.",
            "Node size = touches. Link width = completed passes between the player pair. Only core links are shown so the network stays readable.",
            f"Accurate open-play passes in scope: {len(passes)} | Core links shown: {len(links)} | Core players shown: {len(positions)}",
            (
                f"Average line height: {float(network_height):.1f}m | {strongest_text}"
                if network_height is not None and strongest_text
                else ""
            )
            or (
                f"Average line height: {float(network_height):.1f}m"
                if network_height is not None
                else strongest_text or ""
            ),
        ],
        width=122,
    )
    return _save(fig, output_path)


def plot_shot_map(dataset, shots_df: pd.DataFrame, output_path: Path) -> Path:
    pitch = _vertical_half_pitch()
    fig, ax, footer_ax = _pitch_figure(
        pitch,
        figsize=(10, 12),
        pitch_rect=(0.08, 0.18, 0.82, 0.68),
        footer_rect=(0.05, 0.03, 0.90, 0.11),
    )

    shots_df = _numeric_spatial_rows(shots_df, ["start_x", "start_y"])
    if shots_df.empty or "goal" not in shots_df.columns or "shot_on_target" not in shots_df.columns:
        _empty_plot(ax, "No located shot data available")
        subtitle = f"{dataset.team_name} | {dataset.competition_label} | {dataset.season_label}"
        _add_header(fig, "Shot Map", subtitle)
        _add_footer(
            footer_ax,
            [
                "What it shows: located shots in the selected scope.",
                "No valid located shot rows are available, so no shot count or xG value is inferred.",
            ],
        )
        return _save(fig, output_path)
    shots_df["goal"] = shots_df["goal"].fillna(False).astype(bool)
    shots_df["shot_on_target"] = shots_df["shot_on_target"].fillna(False).astype(bool)
    shots_df["shot_xg"] = pd.to_numeric(shots_df.get("shot_xg"), errors="coerce")
    non_goals = shots_df[~shots_df["goal"]].copy()
    goals = shots_df[shots_df["goal"]].copy()
    on_target_non_goals = non_goals[non_goals["shot_on_target"]].copy()
    off_target = non_goals[~non_goals["shot_on_target"]].copy()

    if not off_target.empty:
        pitch.scatter(
            off_target["start_x"],
            off_target["start_y"],
            s=115 + off_target["shot_xg"].clip(lower=0.01) * 1800,
            color=STYLE["muted"],
            edgecolors=STYLE["line"],
            linewidth=1.0,
            alpha=0.74,
            ax=ax,
            zorder=3,
        )
    if not on_target_non_goals.empty:
        pitch.scatter(
            on_target_non_goals["start_x"],
            on_target_non_goals["start_y"],
            s=135 + on_target_non_goals["shot_xg"].clip(lower=0.01) * 2100,
            color=STYLE["accent_2"],
            edgecolors=STYLE["line"],
            linewidth=1.1,
            alpha=0.88,
            ax=ax,
            zorder=4,
        )
    if not goals.empty:
        pitch.scatter(
            goals["start_x"],
            goals["start_y"],
            s=170 + goals["shot_xg"].clip(lower=0.01) * 2400,
            color=STYLE["highlight"],
            edgecolors=STYLE["line"],
            linewidth=1.3,
            alpha=0.96,
            ax=ax,
            zorder=5,
        )

    box_shots = (
        int(shots_df["inside_box"].sum()) if "inside_box" in shots_df.columns else 0
    )
    on_target = (
        int(shots_df["shot_on_target"].sum())
        if "shot_on_target" in shots_df.columns
        else 0
    )
    subtitle = (
        f"{dataset.team_name} | {dataset.competition_label} | {dataset.season_label}"
    )
    _add_header(fig, "Shot Map", subtitle)
    _add_footer(
        footer_ax,
        [
            f"What it shows: every located {dataset.team_name} shot in the selected scope.",
            "Circle size = xG. Gold = goals. Bright green = on target without a goal. Dark green = off target or blocked.",
            f"Shots: {len(shots_df)} | Goals: {int(shots_df['goal'].sum())} | Total xG: {shots_df['shot_xg'].sum():.2f} | Box shots: {box_shots} | On target: {on_target}",
            f"Average shot distance: {shots_df['distance'].mean():.1f}m",
        ],
        width=96,
    )
    return _save(fig, output_path)


def plot_dropped_balls(dataset, dropped_df: pd.DataFrame, output_path: Path) -> Path:
    pitch = _pitch()
    fig, ax, footer_ax = _pitch_figure(
        pitch,
        figsize=(14, 10),
        pitch_rect=(0.05, 0.16, 0.86, 0.73),
        footer_rect=(0.05, 0.03, 0.90, 0.10),
    )

    dropped_df = _numeric_spatial_rows(
        dropped_df,
        ["drop_x", "drop_y", "pickup_x", "pickup_y"],
    )
    if dropped_df.empty:
        _empty_plot(ax, "No qualified turnover sequences available")
        subtitle = f"{dataset.team_name} | {dataset.competition_label} | {dataset.season_label}"
        _add_header(fig, "Qualified Turnover Sequences", subtitle)
        _add_footer(
            footer_ax,
            [
                "What it shows: a strict sequence rule for longer open-play possessions ending with an inaccurate pass and a quick located opponent event.",
                "This is not a provider-labelled possession-loss metric. No missing coordinate is plotted as zero.",
            ],
        )
        return _save(fig, output_path)
    cmap = LinearSegmentedColormap.from_list(
        "drop_heat",
        [STYLE["bg"], STYLE["panel_alt"], STYLE["danger"], STYLE["highlight"]],
    )
    heat = pitch.bin_statistic(
        dropped_df["pickup_x"],
        dropped_df["pickup_y"],
        statistic="count",
        bins=(18, 12),
    )
    heatmap = pitch.heatmap(heat, ax=ax, cmap=cmap, edgecolors=STYLE["bg"], alpha=0.92)
    _add_colorbar(fig, heatmap, (0.92, 0.22, 0.018, 0.58), "Opponent pickups per zone")

    featured = dropped_df.head(24)
    _draw_arrows(
        pitch,
        ax,
        featured,
        xstart="drop_x",
        ystart="drop_y",
        xend="pickup_x",
        yend="pickup_y",
        color=STYLE["danger"],
        alpha=0.40,
        width=0.34,
        zorder=3,
    )
    if not featured.empty:
        pitch.scatter(
            featured["drop_x"],
            featured["drop_y"],
            s=24,
            color=STYLE["danger"],
            edgecolors=STYLE["line"],
            linewidth=0.5,
            alpha=0.90,
            ax=ax,
            zorder=4,
        )
    pitch.scatter(
        dropped_df["pickup_x"],
        dropped_df["pickup_y"],
        s=34 + dropped_df["possession_duration"].clip(lower=0) * 2.2,
        color=STYLE["highlight"],
        edgecolors=STYLE["line"],
        linewidth=0.6,
        alpha=0.72,
        ax=ax,
        zorder=5,
    )

    top_loser = (
        dropped_df.groupby("player_name").size().sort_values(ascending=False).head(1)
    )
    top_loser_text = None
    if not top_loser.empty:
        top_loser_text = f"Most frequent drop: {_short_name(top_loser.index[0])} ({int(top_loser.iloc[0])})"

    subtitle = (
        f"{dataset.team_name} | {dataset.competition_label} | {dataset.season_label}"
    )
    _add_header(fig, "Qualified Turnover Sequences", subtitle)
    _add_footer(
        footer_ax,
        [
            f"What it shows: longer {dataset.team_name} open-play possessions ending with an inaccurate pass and a quick located opponent event.",
            "Arrow start = failed-pass end location. Arrow head = the first eligible located opponent event, mirrored into the analysed team's attacking direction. The heatmap counts those opponent-event zones.",
            "Rule: possession lasted at least 8 seconds and 4 events; the opponent event occurred within 8 seconds. This is a derived sequence, not proof of controlled recovery.",
            f"Dropped possessions: {len(dropped_df)} | Opponent pickups in the attacking half: {int(dropped_df['pickup_in_attacking_half'].sum())} | Mean possession before loss: {dropped_df['possession_duration'].mean():.1f}s | Mean pickup delay: {dropped_df['pickup_delay'].mean():.1f}s",
            top_loser_text or "",
        ],
        width=134,
    )
    return _save(fig, output_path)


def plot_player_radar(dataset, radar_payload: dict, output_path: Path) -> Path:
    metrics = radar_payload["metrics"]
    labels = [item["label"] for item in metrics]
    values = [item["percentile"] for item in metrics]
    values.append(values[0])

    angles = np.linspace(0, 2 * np.pi, len(labels), endpoint=False).tolist()
    angles.append(angles[0])

    fig = plt.figure(figsize=(10, 10), facecolor=STYLE["bg"])
    ax = fig.add_axes([0.08, 0.14, 0.84, 0.68], polar=True)
    footer_ax = fig.add_axes([0.05, 0.03, 0.90, 0.10])
    footer_ax.set_facecolor(STYLE["bg"])
    footer_ax.set_xticks([])
    footer_ax.set_yticks([])
    for spine in footer_ax.spines.values():
        spine.set_visible(False)
    ax.set_facecolor(STYLE["bg"])
    ax.set_theta_offset(np.pi / 2)
    ax.set_theta_direction(-1)
    ax.set_ylim(0, 100)
    ax.set_yticks([25, 50, 75, 100])
    ax.set_yticklabels(["25", "50", "75", "100"], color=STYLE["muted"], fontsize=9)
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(labels, color=STYLE["text"], fontsize=11)
    ax.grid(color=STYLE["line"], alpha=0.22)
    ax.spines["polar"].set_color(STYLE["line"])

    ax.plot(angles, values, color=STYLE["highlight"], linewidth=2.5)
    ax.fill(angles, values, color=STYLE["accent"], alpha=0.28)
    ax.scatter(angles[:-1], values[:-1], color=STYLE["accent_2"], s=75, zorder=5)

    player = radar_payload["player"]
    subtitle = f"{player['player_name']} | {dataset.team_name} | compared with {radar_payload['comparison_size']} players"
    _add_header(fig, "Player Radar", subtitle)
    _add_footer(
        footer_ax,
        [
            "What it shows: percentile ranks for the selected player against teammates with enough 2026 match data.",
            f"Eligible comparison floor: {radar_payload['minimum_appearances']} matches with event data | Touches per match: {player['touches_per_match']:.1f}",
            "Raw per-match values: "
            + ", ".join(f"{item['label']} {item['display_value']}" for item in metrics),
        ],
        width=110,
    )
    return _save(fig, output_path)
