"""Shared plotting helpers for dashboard sections."""

from __future__ import annotations

from pathlib import Path
from textwrap import fill

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from mplsoccer import Pitch, VerticalPitch

from pipeline.settings import PLOT_STYLE

STYLE = {
    **PLOT_STYLE,
    "panel": "#0b3427",
    "panel_alt": "#124735",
    "highlight": "#ffdc6e",
}


def pitch() -> Pitch:
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


def vertical_pitch(*, half: bool = False) -> VerticalPitch:
    return VerticalPitch(
        pitch_type="custom",
        pitch_length=100,
        pitch_width=100,
        half=half,
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


def figure_with_footer(
    pitch_obj,
    *,
    figsize: tuple[float, float],
    pitch_rect: tuple[float, float, float, float],
    footer_rect: tuple[float, float, float, float],
):
    fig = plt.figure(figsize=figsize, facecolor=STYLE["bg"])
    ax = fig.add_axes(pitch_rect)
    pitch_obj.draw(ax=ax)
    ax.set_facecolor(STYLE["bg"])

    footer_ax = fig.add_axes(footer_rect)
    footer_ax.set_facecolor(STYLE["bg"])
    footer_ax.set_xticks([])
    footer_ax.set_yticks([])
    for spine in footer_ax.spines.values():
        spine.set_visible(False)
    return fig, ax, footer_ax


def add_header(fig, title: str, subtitle: str):
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
        0.05, 0.905, subtitle, color=STYLE["muted"], fontsize=11.5, ha="left", va="top"
    )


def add_footer(footer_ax, lines: list[str], *, width: int = 125):
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


def save_figure(fig, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=220, facecolor=STYLE["bg"])
    plt.close(fig)
    return output_path
