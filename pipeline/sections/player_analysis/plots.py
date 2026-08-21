"""Player-analysis radar plots.

Follows the same visual style as market/plots.py:
  - Left-aligned bold title + muted subtitle at the top
  - Polar matplotlib radar (no PyPizza)
  - Filled polygon, outline, scatter dots at vertices
  - Bordered footer panel with contextual text

Calling convention:

    player = make_player_radar_input(player_profile, advanced_stats)
    build_player_radar(
        players=[player],
        stat_keys=["average.goals", "average.xgShot", "percent.aerialDuelsWon"],
        stat_labels=["Goals/90", "xG/90", "Aerial won %"],
        benchmarks=loaded_benchmarks["benchmarks"],
        output_path=Path("reports/player_analysis/plots/player_123.png"),
        style=settings.plot_style,
        title="Player Radar",
        subtitle="L. Brahim | Jönköpings Södra",
    )

Up to two players are supported. The second is rendered as a comparison
overlay in the accent_2 colour.

Each stat is converted to a 0-100 percentile score against the player's own
position-group benchmark so the rings always represent Q1 / Q2 / Q3 / max
for the correct peer group.  Raw values are listed in the footer.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from textwrap import fill

import numpy as np

try:
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap
    from matplotlib.patches import Rectangle
except Exception:
    plt = None
    LinearSegmentedColormap = None
    Rectangle = None

from pipeline.sections.player_analysis.metrics import bucket_player_position

# Extend the shared palette with panel colours (mirrors market/plots.py)
_PANEL = "#0b3427"
_HIGHLIGHT = "#ffdc6e"

# Categorical team palette for dark surface #002418.
# First 8 are validated (OKLCH L 0.48–0.67, CVD ΔE ≥ 8 adjacent, normal-vision ≥ 15).
# Extended to 20 hues to cover leagues with many teams; secondary encoding
# (direct player-name labels + legend) is always present, so all-pairs CVD
# relaxation applies for slots 9–20.
_TEAM_PALETTE = [
    "#3987e5",  #  1 blue
    "#d95926",  #  2 orange
    "#199e70",  #  3 green
    "#c98500",  #  4 amber
    "#d55181",  #  5 magenta
    "#9085e9",  #  6 violet
    "#e66767",  #  7 red
    "#1e94ad",  #  8 teal
    # Extended hues — evenly distributed to maximise visual separation
    "#40bce8",  #  9 sky blue
    "#a8c83c",  # 10 lime
    "#e87c3c",  # 11 deep orange
    "#3cc4a0",  # 12 mint
    "#b840c4",  # 13 purple
    "#e8c040",  # 14 gold
    "#6068d4",  # 15 indigo
    "#e04896",  # 16 rose
    "#44ac5c",  # 17 forest green
    "#60cce0",  # 18 light cyan
    "#d46c2c",  # 19 sienna
    "#8848c8",  # 20 deep violet
]


# ---------------------------------------------------------------------------
# Internal: stat helpers
# ---------------------------------------------------------------------------

def _get_stat_value(stats: dict, stat_key: str) -> float | None:
    """Extract a value from a player's advanced-stats dict by dotted key."""
    group, _, field = stat_key.partition(".")
    section = stats.get(group)
    if not isinstance(section, dict):
        return None
    value = section.get(field)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _to_percentile(value: float, benchmark: dict) -> float:
    """Convert a raw stat value to a 0-100 percentile score.

    Piecewise linear interpolation:
        raw  : [   0,   q1,   q2,   q3,  max ]
        score: [   0,   25,   50,   75,  100 ]

    Values above max are capped at 100 so they never escape the radar.
    """
    q1 = float(benchmark["q1"])
    q2 = float(benchmark["q2"])
    q3 = float(benchmark["q3"])
    max_val = float(benchmark["max"])

    if max_val <= 0 or value <= 0:
        return 0.0
    if value >= max_val:
        return 100.0

    breakpoints = [0.0, q1, q2, q3, max_val]
    targets = [0.0, 25.0, 50.0, 75.0, 100.0]

    for i in range(len(breakpoints) - 1):
        lo, hi = breakpoints[i], breakpoints[i + 1]
        if hi <= lo:
            continue
        if lo <= value <= hi:
            t = (value - lo) / (hi - lo)
            return targets[i] + t * (targets[i + 1] - targets[i])

    return 100.0


def _format_stat_value(value: float, stat_key: str) -> str:
    if stat_key.startswith("percent."):
        return f"{value:.1f}%"
    return f"{value:.2f}" if abs(value) < 10 else f"{value:.1f}"


def _position_benchmarks_for(player: dict, benchmarks: dict) -> dict:
    position = bucket_player_position(player.get("position_code"))
    return benchmarks.get(position or "") or {}


def _mixed_positions(players: list[dict]) -> bool:
    """Return True when players span more than one position group."""
    buckets = {bucket_player_position(p.get("position_code")) for p in players} - {None}
    return len(buckets) > 1


def _stat_benchmarks_for(player: dict, benchmarks: dict, use_general: bool) -> dict:
    """Return the flat {stat_key: benchmark} dict to use for this player."""
    if use_general:
        return benchmarks.get("general") or {}
    return _position_benchmarks_for(player, benchmarks)


def _resolve_player_data(
    player: dict,
    stat_keys: list[str],
    benchmarks: dict,
    use_general: bool = False,
) -> tuple[list[float], list[float]]:
    """Return (raw_values, percentile_scores) for every stat_key."""
    stat_bm = _stat_benchmarks_for(player, benchmarks, use_general)
    raw_values: list[float] = []
    pct_scores: list[float] = []

    for stat_key in stat_keys:
        raw = _get_stat_value(player["stats"], stat_key)
        raw_val = raw if raw is not None else 0.0
        raw_values.append(raw_val)

        bm = stat_bm.get(stat_key)
        pct_scores.append(_to_percentile(raw_val, bm) if bm and raw is not None else 0.0)

    return raw_values, pct_scores


# ---------------------------------------------------------------------------
# Internal: figure layout helpers (mirrors market/plots.py)
# ---------------------------------------------------------------------------

def _add_header(fig, title: str, subtitle: str, style: dict, *, enabled: bool = True):
    if not enabled:
        return
    fig.text(0.05, 0.945, title,
             color=style["text"], fontsize=30, fontweight="bold",
             ha="left", va="top")
    fig.text(0.05, 0.893, subtitle,
             color=style["muted"], fontsize=14,
             ha="left", va="top")


def _add_footer(footer_ax, lines: list[str], style: dict, width: int = 110):
    footer_ax.add_patch(Rectangle(
        (0.0, 0.0), 1.0, 1.0,
        transform=footer_ax.transAxes,
        facecolor=_PANEL,
        edgecolor=style["line"],
        linewidth=1.0,
        alpha=0.82,
    ))
    footer_ax.text(
        0.018, 0.84,
        fill("\n".join(line for line in lines if line), width=width),
        color=style["text"], fontsize=10.0,
        ha="left", va="top",
        transform=footer_ax.transAxes,
    )


def _save(fig, output_path: Path) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=220, facecolor=fig.get_facecolor())
    plt.close(fig)
    return output_path


# ---------------------------------------------------------------------------
# Internal: radar drawing
# ---------------------------------------------------------------------------

def _draw_radar_series(ax, angles: list[float], pct_scores: list[float],
                       line_color: str, fill_color: str, dot_color: str):
    values = pct_scores + [pct_scores[0]]
    ax.plot(angles, values, color=line_color, linewidth=2.5)
    ax.fill(angles, values, color=fill_color, alpha=0.28)
    ax.scatter(angles[:-1], values[:-1], color=dot_color, s=75, zorder=5)


# ---------------------------------------------------------------------------
# Internal: report builder
# ---------------------------------------------------------------------------

def _primary_position(advanced_stats: dict) -> str | None:
    """Return the position name where the player spent the highest share of time."""
    positions = advanced_stats.get("positions")
    if not isinstance(positions, list) or not positions:
        return None
    best = max(positions, key=lambda p: p.get("percent", 0))
    return (best.get("position") or {}).get("name")


def _primary_position_code(advanced_stats: dict) -> str | None:
    """Return the uppercased position code for the player's primary position."""
    positions = advanced_stats.get("positions")
    if not isinstance(positions, list) or not positions:
        return None
    best = max(positions, key=lambda p: p.get("percent", 0))
    code = (best.get("position") or {}).get("code")
    return code.upper() if code else None


def _player_display_name(player: dict) -> str:
    """Return 'A. Name (CODE)' for use in plot labels."""
    name = player.get("name", "")
    code = _primary_position_code(player.get("stats") or {})
    return f"{name} ({code})" if code else name
    


def _build_report(
    players: list[dict],
    stat_keys: list[str],
    stat_labels: list[str],
    benchmarks: dict,
    player_raws: list[list[float]],
    player_pcts: list[list[float]],
    use_general: bool,
) -> dict:
    player_entries = []
    for j, player in enumerate(players):
        adv = player["stats"]
        stat_bm = _stat_benchmarks_for(player, benchmarks, use_general)

        stat_entries = []
        for i, (stat_key, label) in enumerate(zip(stat_keys, stat_labels)):
            bm = stat_bm.get(stat_key) or {}
            stat_entries.append({
                "key": stat_key,
                "label": label,
                "raw": player_raws[j][i],
                "percentile": round(player_pcts[j][i], 2),
                "benchmark": {
                    "q1": bm.get("q1"),
                    "q2": bm.get("q2"),
                    "q3": bm.get("q3"),
                    "max": bm.get("max"),
                    "sample_size": bm.get("sample_size"),
                },
            })

        player_entries.append({
            "player_id": player.get("player_id"),
            "name": player.get("name"),
            "team_id": player.get("team_id"),
            "team_name": player.get("team_name"),
            "position": _primary_position(adv),
            "position_group": bucket_player_position(player.get("position_code")),
            "games": (adv.get("total") or {}).get("matches"),
            "stats": stat_entries,
        })

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "benchmark_scope": "general" if use_general else "position",
        "players": player_entries,
    }


# ---------------------------------------------------------------------------
# Public helper: assemble player input from cached data
# ---------------------------------------------------------------------------

def make_player_radar_input(
    player_profile: dict,
    advanced_stats: dict,
    team_name: str | None = None,
) -> dict:
    """Build a player dict for build_player_radar from raw cached data.

    player_profile : a player record from competition_*_players.json
    advanced_stats : the "stats" value from the player's advancedstats cache file
    team_name      : optional team name (not stored in the player profile cache)
    """
    name = (
        player_profile.get("shortName")
        or player_profile.get("name")
        or f"Player {player_profile.get('wyId', '')}"
    )
    positions = advanced_stats.get("positions") or []
    primary_code = None
    if positions:
        primary = max(positions, key=lambda p: p.get("percent", 0))
        primary_code = ((primary.get("position") or {}).get("code") or "").lower() or None

    return {
        "player_id": player_profile.get("wyId"),
        "name": name,
        "position_code": primary_code,  # e.g. "cf", "lb" — used for benchmark bucket lookup
        "team_id": player_profile.get("currentTeamId"),
        "team_name": team_name,
        "stats": advanced_stats,
    }


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------

def build_player_radar(
    players: list[dict],
    stat_keys: list[str],
    stat_labels: list[str],
    benchmarks: dict,
    output_path: Path,
    style: dict[str, str],
    title: str | None = None,
    subtitle: str | None = None,
    footer_lines: list[str] | None = None,
    show_footer: bool = True,
    show_header: bool = True,
) -> Path:
    """Render a radar for one or two players and save a PNG.

    Parameters
    ----------
    players:
        1 or 2 player dicts from make_player_radar_input().
    stat_keys:
        Dotted benchmark keys e.g. ["average.goals", "percent.aerialDuelsWon"].
    stat_labels:
        Human-readable axis labels aligned with stat_keys.
    benchmarks:
        The "benchmarks" value from competition_*_position_benchmarks.json.
    output_path:
        Destination PNG path.
    style:
        Colour palette from settings.plot_style.
    title:
        Bold main title (top-left).
    subtitle:
        Smaller subtitle below title. Defaults to player name(s).
    footer_lines:
        Lines of text for the footer panel. A default is generated when None.
    show_footer:
        When False the footer panel is omitted and the radar expands to fill
        the freed space. footer_lines is ignored.

    Returns
    -------
    Path  The written output path.
    """
    if plt is None:
        raise RuntimeError("matplotlib is required for radar plots.")
    if not players:
        raise ValueError("At least one player is required.")
    if len(stat_keys) != len(stat_labels):
        raise ValueError("stat_keys and stat_labels must have the same length.")
    if len(players) > 2:
        players = players[:2]

    n = len(stat_keys)
    primary = players[0]
    compare = players[1] if len(players) == 2 else None

    use_general = _mixed_positions(players)

    primary_raw, primary_pct = _resolve_player_data(primary, stat_keys, benchmarks, use_general)
    compare_raw, compare_pct = (
        _resolve_player_data(compare, stat_keys, benchmarks, use_general) if compare else ([], [])
    )

    # --- JSON report (always written alongside the PNG) --------------------
    all_raws = [primary_raw] + ([compare_raw] if compare else [])
    all_pcts = [primary_pct] + ([compare_pct] if compare else [])
    report = _build_report(players, stat_keys, stat_labels, benchmarks, all_raws, all_pcts, use_general)
    report_path = Path(output_path).with_suffix(".json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    angles = np.linspace(0, 2 * np.pi, n, endpoint=False).tolist()
    angles.append(angles[0])   # close the polygon

    # --- Figure layout (mirrors market/plots.py) ---------------------------
    # Axes are inset to leave room for wrapped stat labels outside the ring.
    fig = plt.figure(figsize=(10, 10), facecolor=style["bg"])
    if show_footer and show_header:
        ax = fig.add_axes([0.14, 0.16, 0.72, 0.62], polar=True)
        footer_ax = fig.add_axes([0.05, 0.03, 0.90, 0.10])
        footer_ax.set_facecolor(style["bg"])
        footer_ax.set_xticks([])
        footer_ax.set_yticks([])
        for spine in footer_ax.spines.values():
            spine.set_visible(False)
    elif show_footer and not show_header:
        ax = fig.add_axes([0.14, 0.14, 0.72, 0.79], polar=True)
        footer_ax = fig.add_axes([0.05, 0.03, 0.90, 0.10])
        footer_ax.set_facecolor(style["bg"])
        footer_ax.set_xticks([])
        footer_ax.set_yticks([])
        for spine in footer_ax.spines.values():
            spine.set_visible(False)
    elif not show_footer and show_header:
        ax = fig.add_axes([0.14, 0.16, 0.72, 0.68], polar=True)
        footer_ax = None
    else:  # not show_footer and not show_header
        ax = fig.add_axes([0.14, 0.12, 0.72, 0.83], polar=True)
        footer_ax = None

    ax.set_facecolor(style["bg"])

    # --- Polar axis setup --------------------------------------------------
    ax.set_theta_offset(np.pi / 2)
    ax.set_theta_direction(-1)
    ax.set_ylim(0, 100)
    ax.set_yticks([25, 50, 75, 100])
    ax.set_yticklabels(["25", "50", "75", "100"],
                       color=style["muted"], fontsize=9)
    ax.set_rlabel_position(180 / n)
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels([])   # replaced by manual labels below
    ax.grid(color=style["line"], alpha=0.22)
    ax.spines["polar"].set_color(style["line"])

    # --- Stat labels: wrapped and aligned to each axis ---------------------
    # With theta_offset=pi/2 and theta_direction=-1, the visual angle of a
    # data angle θ is: display = pi/2 - θ.  We use cos/sin of that to pick
    # left/right/center and top/bottom/center alignment per label.
    for angle, label in zip(angles[:-1], stat_labels):
        display = np.pi / 2 - angle
        cos_a, sin_a = np.cos(display), np.sin(display)
        ha = "left" if cos_a > 0.1 else ("right" if cos_a < -0.1 else "center")
        va = "bottom" if sin_a > 0.1 else ("top" if sin_a < -0.1 else "center")
        ax.text(
            angle, 112, fill(label, width=18),
            ha=ha, va=va,
            color=style["text"], fontsize=9,
            clip_on=False,
        )

    # --- Radar series ------------------------------------------------------
    _draw_radar_series(
        ax, angles, primary_pct,
        line_color=_HIGHLIGHT,
        fill_color=style["accent"],
        dot_color=_HIGHLIGHT,
    )
    if compare_pct:
        _draw_radar_series(
            ax, angles, compare_pct,
            line_color=style["accent_2"],
            fill_color=style["accent_2"],
            dot_color=style["accent_2"],
        )

    primary_label = _player_display_name(primary)
    compare_label = _player_display_name(compare) if compare else None

    # --- Header ------------------------------------------------------------
    if title is None:
        title = f"{primary_label} vs {compare_label}" if compare else primary_label
    if subtitle is None:
        if compare:
            t1 = primary.get("team_name") or ""
            t2 = compare.get("team_name") or ""
            subtitle = f"{t1} · {t2}" if t1 or t2 else ""
        else:
            subtitle = primary.get("team_name") or ""

    _add_header(fig, title, subtitle, style, enabled=show_header)

    # --- Footer ------------------------------------------------------------
    if show_footer:
        if footer_lines is None:
            raw_note = "  |  ".join(
                f"{label} {_format_stat_value(val, key)}"
                for label, val, key in zip(stat_labels, primary_raw, stat_keys)
            )
            footer_lines = [
                "What it shows: percentile ranks against the position-group benchmark (all players in the competition at the same position).",
                "Rings mark the Q1 / Q2 / Q3 / max boundaries.  Values above the outer ring are capped at 100.",
            ]
            if compare:
                compare_raw_note = "  |  ".join(
                    f"{label} {_format_stat_value(val, key)}"
                    for label, val, key in zip(stat_labels, compare_raw, stat_keys)
                )
                footer_lines += [
                    f"Raw values ({primary_label}): {raw_note}",
                    f"Raw values ({compare_label}): {compare_raw_note}",
                ]
            else:
                footer_lines.append(f"Raw per-90 values: {raw_note}")

        _add_footer(footer_ax, footer_lines, style)

    # --- Legend for comparison plots ---------------------------------------
    if compare:
        legend_y = 0.128 if show_footer else 0.06
        fig.text(0.08, legend_y, f"● {primary_label}",
                 color=_HIGHLIGHT, fontsize=10, fontweight="bold", va="top")
        fig.text(0.08 + 0.28, legend_y, f"● {compare_label}",
                 color=style["accent_2"], fontsize=10, fontweight="bold", va="top")

    return _save(fig, output_path)


# ---------------------------------------------------------------------------
# ↑ build_player_radar ends here
# ---------------------------------------------------------------------------
# Position-map plot
# ---------------------------------------------------------------------------

# (x, y) on a 100×100 custom pitch — attacking direction is left→right.
# x=0 is the defensive goal line, x=100 is the attacking goal line.
# y=0 is the bottom touchline, y=100 is the top touchline.
_POSITION_COORDS: dict[str, tuple[float, float]] = {
    # Goalkeeper
    "gk":    (5,  50),
    # Centre backs (flat back 4 / back 3)
    "cb":    (18, 50),
    "rcb":   (18, 35),
    "lcb":   (18, 65),
    "rcb3":  (18, 28),
    "lcb3":  (18, 72),
    # Full backs / wing backs
    "rb":    (22, 16),
    "lb":    (22, 84),
    "rb5":   (22, 16),
    "lb5":   (22, 84),
    "rwb":   (35, 10),
    "lwb":   (35, 90),
    # Defensive midfielders
    "dmf":   (38, 50),
    "rdmf":  (38, 36),
    "ldmf":  (38, 64),
    # Central midfielders
    "cmf":   (50, 50),
    "rcmf":  (48, 36),
    "lcmf":  (48, 64),
    "rcmf3": (50, 36),
    "lcmf3": (50, 64),
    # Attacking midfielders
    "amf":   (62, 50),
    "ramf":  (60, 34),
    "lamf":  (60, 66),
    # Wide forwards / wingers
    "rw":    (68, 12),
    "lw":    (68, 88),
    "rwf":   (72, 16),
    "lwf":   (72, 84),
    # Forwards
    "ss":    (74, 50),
    "cf":    (82, 50),
}


def build_player_position_map(
    player: dict,
    output_path: Path,
    style: dict[str, str],
    title: str = None,
    subtitle: str | None = None,
    show_footer: bool = True,
    show_header: bool = True,
) -> Path:
    """Render a full-pitch position-distribution map for one player.

    Each position the player has appeared in is drawn as a circle on the pitch.
    Circle size and colour intensity both scale with the percentage of time
    spent at that position.

    Parameters
    ----------
    player:
        A player dict from make_player_radar_input().
    output_path:
        Destination PNG path.
    style:
        Colour palette from settings.plot_style.
    title:
        Bold main title (top-left).
    subtitle:
        Smaller muted subtitle. Defaults to "Name (Team)".
    show_footer:
        When False the footer panel is omitted and the pitch expands downward.
    """
    try:
        from mplsoccer import VerticalPitch as _VPitch
    except Exception as exc:
        raise RuntimeError("mplsoccer is required for position map plots.") from exc

    if plt is None:
        raise RuntimeError("matplotlib is required for position map plots.")

    positions = (player.get("stats") or {}).get("positions") or []
    if not positions:
        raise ValueError(f"No position data found for player {player.get('name')}.")

    # --- Resolve coordinates and filter to known codes ---------------------
    entries: list[tuple[float, float, float, str, str]] = []  # x, y, pct, code, name
    for pos_entry in positions:
        pos = pos_entry.get("position") or {}
        code = (pos.get("code") or "").lower()
        name = pos.get("name") or code.upper()
        pct = float(pos_entry.get("percent") or 0)
        if pct <= 0:
            continue
        coords = _POSITION_COORDS.get(code)
        if coords is None:
            continue
        entries.append((*coords, pct, code, name))

    if not entries:
        raise ValueError(f"No mappable position codes found for player {player.get('name')}.")

    # --- Figure layout -----------------------------------------------------
    fig = plt.figure(figsize=(10, 14), facecolor=style["bg"])
    if show_footer and show_header:
        pitch_ax = fig.add_axes([0.05, 0.14, 0.90, 0.74])
        footer_ax = fig.add_axes([0.05, 0.03, 0.90, 0.09])
        footer_ax.set_facecolor(style["bg"])
        footer_ax.set_xticks([])
        footer_ax.set_yticks([])
        for spine in footer_ax.spines.values():
            spine.set_visible(False)
    elif show_footer and not show_header:
        pitch_ax = fig.add_axes([0.05, 0.14, 0.90, 0.82])
        footer_ax = fig.add_axes([0.05, 0.03, 0.90, 0.09])
        footer_ax.set_facecolor(style["bg"])
        footer_ax.set_xticks([])
        footer_ax.set_yticks([])
        for spine in footer_ax.spines.values():
            spine.set_visible(False)
    elif not show_footer and show_header:
        pitch_ax = fig.add_axes([0.05, 0.05, 0.90, 0.83])
        footer_ax = None
    else:  # not show_footer and not show_header
        pitch_ax = fig.add_axes([0.05, 0.03, 0.90, 0.95])
        footer_ax = None

    # --- Pitch (vertical — GK at bottom, attackers at top) ----------------
    pitch = _VPitch(
        pitch_type="custom",
        pitch_length=100,
        pitch_width=100,
        pitch_color=style["bg"],
        line_color=style["line"],
        linewidth=1.4,
        goal_type="box",
        spot_type="square",
        corner_arcs=True,
        line_zorder=3,
    )
    pitch.draw(ax=pitch_ax)

    # --- Position circles --------------------------------------------------
    # VerticalPitch axes layout after pitch.draw():
    #   matplotlib x-axis (horizontal) = pitch WIDTH (lateral), with
    #     y=0 (Wyscout right flank) mapping to the RIGHT side, so we mirror
    #     with (100 - y) to get left flank on the left — same convention
    #     used by build_player_action_heatmap.
    #   matplotlib y-axis (vertical)   = pitch LENGTH (depth), 0=GK at
    #     bottom, 100=CF at top. No inversion needed.
    # Therefore: axes_x = 100 - y,  axes_y = x
    max_pct = max(pct for *_, pct, _, _ in entries)

    for x, y, pct, code, name in entries:
        intensity = pct / max_pct          # 0.0 → 1.0 relative to this player's most-played
        alpha = 0.35 + 0.65 * intensity    # 0.35 at minimum, 1.0 at max
        size = 800 + 4200 * (pct / 100)   # scales from ~800 (tiny) to ~5000 (100 %)

        ax_x = y         # VerticalPitch x-axis is already inverted (100 left, 0 right)
        ax_y = x         # depth → vertical axis (GK=0=bottom, CF=100=top)

        pitch_ax.scatter(
            ax_x, ax_y,
            s=size,
            color=style["accent"],
            alpha=alpha,
            edgecolors=style["line"],
            linewidth=1.2,
            zorder=4,
        )
        pitch_ax.text(
            ax_x, ax_y,
            f"{pct:.0f}%",
            color=style["bg"],
            fontsize=16,
            fontweight="bold",
            ha="center",
            va="center",
            zorder=5,
        )
        # Code label just below the circle: decrease ax_y (toward GK end).
        pitch_ax.text(
            ax_x, ax_y - 7,
            code.upper(),
            color=style["text"],
            fontsize=16,
            ha="center",
            va="center",
            zorder=5,
            bbox={
                "boxstyle": "round,pad=0.2",
                "facecolor": _PANEL,
                "edgecolor": "none",
                "alpha": 0.75,
            },
        )

    # --- Header ------------------------------------------------------------
    if title is None:
        title = f"{_player_display_name(player)} - Position"
    if subtitle is None:
        team = player.get("team_name")
        subtitle = f"{team}" if team else _player_display_name(player)

    _add_header(fig, title, subtitle, style, enabled=show_header)

    # --- Footer ------------------------------------------------------------
    if show_footer:
        pos_summary = "  ·  ".join(
            f"{name} {pct:.0f}%"
            for _, _, pct, _, name in sorted(entries, key=lambda e: -e[2])
        )
        _add_footer(
            footer_ax,
            [
                "What it shows: share of minutes played at each position in the current season.",
                f"Circle size and colour intensity reflect time spent. Positions played: {pos_summary}",
            ],
            style,
            width=130,
        )

    return _save(fig, output_path)


# ---------------------------------------------------------------------------
# Pizza plot
# ---------------------------------------------------------------------------

def build_player_pizza(
    players: list[dict],
    stat_keys: list[str],
    stat_labels: list[str],
    benchmarks: dict,
    output_path: Path,
    style: dict[str, str],
    title: str = None,
    subtitle: str | None = None,
    footer_lines: list[str] | None = None,
    show_footer: bool = True,
    show_header: bool = True,
) -> Path:
    """Render a percentile pizza chart for one or two players and save a PNG.

    Parameters mirror build_player_radar() exactly. Uses mplsoccer PyPizza
    internally; the same color palette, header, footer, and JSON report logic
    as the radar apply here.

    Parameters
    ----------
    players:
        1 or 2 player dicts from make_player_radar_input().
    stat_keys:
        Dotted benchmark keys e.g. ["average.goals", "percent.aerialDuelsWon"].
    stat_labels:
        Human-readable slice labels aligned with stat_keys.
    benchmarks:
        The "benchmarks" value from competition_*_position_benchmarks.json.
    output_path:
        Destination PNG path.
    style:
        Colour palette from settings.plot_style.
    title:
        Bold main title (top-left).
    subtitle:
        Smaller subtitle below title. Defaults to player name(s).
    footer_lines:
        Lines of text for the footer panel. A default is generated when None.
    show_footer:
        When False the footer panel is omitted and the pizza expands upward.

    Returns
    -------
    Path  The written output path.
    """
    try:
        from mplsoccer import PyPizza
    except Exception as exc:
        raise RuntimeError("mplsoccer is required for pizza plots.") from exc

    if plt is None:
        raise RuntimeError("matplotlib is required for pizza plots.")
    if not players:
        raise ValueError("At least one player is required.")
    if len(stat_keys) != len(stat_labels):
        raise ValueError("stat_keys and stat_labels must have the same length.")
    if len(players) > 2:
        players = players[:2]

    n = len(stat_keys)
    primary = players[0]
    compare = players[1] if len(players) == 2 else None
    use_general = _mixed_positions(players)

    primary_raw, primary_pct = _resolve_player_data(primary, stat_keys, benchmarks, use_general)
    compare_raw, compare_pct = (
        _resolve_player_data(compare, stat_keys, benchmarks, use_general) if compare else ([], [])
    )

    # --- JSON report (always alongside the PNG) ----------------------------
    all_raws = [primary_raw] + ([compare_raw] if compare else [])
    all_pcts = [primary_pct] + ([compare_pct] if compare else [])
    report = _build_report(players, stat_keys, stat_labels, benchmarks, all_raws, all_pcts, use_general)
    report_path = Path(output_path).with_suffix(".json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    bg = style["bg"]
    line = style["line"]
    text_col = style["text"]
    accent = style["accent"]
    accent_2 = style["accent_2"]

    baker = PyPizza(
        params=stat_labels,
        background_color=bg,
        straight_line_color=line,
        straight_line_lw=1,
        last_circle_color=line,
        last_circle_lw=2.5,
        other_circle_lw=0.7,
        other_circle_color=line,
    )

    # --- Figure layout (mirrors build_player_radar) ------------------------
    # Larger figure gives each label slice more physical space so text
    # doesn't overlap even with 12-13 stats.
    fig = plt.figure(figsize=(13, 13), facecolor=bg)
    if show_footer and show_header:
        pizza_ax = fig.add_axes([0.10, 0.12, 0.80, 0.70], polar=True)
        footer_ax = fig.add_axes([0.05, 0.03, 0.90, 0.08])
        footer_ax.set_facecolor(bg)
        footer_ax.set_xticks([])
        footer_ax.set_yticks([])
        for spine in footer_ax.spines.values():
            spine.set_visible(False)
    elif show_footer and not show_header:
        pizza_ax = fig.add_axes([0.10, 0.10, 0.80, 0.84], polar=True)
        footer_ax = fig.add_axes([0.05, 0.03, 0.90, 0.08])
        footer_ax.set_facecolor(bg)
        footer_ax.set_xticks([])
        footer_ax.set_yticks([])
        for spine in footer_ax.spines.values():
            spine.set_visible(False)
    elif not show_footer and show_header:
        pizza_ax = fig.add_axes([0.10, 0.12, 0.80, 0.76], polar=True)
        footer_ax = None
    else:  # not show_footer and not show_header (report mode)
        pizza_ax = fig.add_axes([0.10, 0.06, 0.80, 0.90], polar=True)
        footer_ax = None

    # --- Pizza (PyPizza draws onto our axes) --------------------------------
    pct_primary = [round(v, 1) for v in primary_pct]
    if compare:
        pct_compare = [round(v, 1) for v in compare_pct]
        baker.make_pizza(
            pct_primary,
            compare_values=pct_compare,
            ax=pizza_ax,
            color_blank_space=[_PANEL] * n,
            slice_colors=[accent] * n,
            value_colors=[bg] * n,
            value_bck_colors=[accent] * n,
            compare_colors=[accent_2] * n,
            compare_value_colors=[bg] * n,
            compare_value_bck_colors=[accent_2] * n,
            blank_alpha=1.0,
            kwargs_slices=dict(edgecolor=line, zorder=2, linewidth=0.8),
            kwargs_compare=dict(edgecolor=line, zorder=2, linewidth=0.8),
            kwargs_params=dict(color=text_col, fontsize=12, va="center"),
            kwargs_values=dict(color=bg, fontsize=10, fontweight="bold"),
            kwargs_compare_values=dict(color=bg, fontsize=12, fontweight="bold"),
        )
    else:
        baker.make_pizza(
            pct_primary,
            ax=pizza_ax,
            color_blank_space=[_PANEL] * n,
            slice_colors=[accent] * n,
            value_colors=[bg] * n,
            value_bck_colors=[accent] * n,
            blank_alpha=1.0,
            kwargs_slices=dict(edgecolor=line, zorder=2, linewidth=0.8),
            kwargs_params=dict(color=text_col, fontsize=12, va="center"),
            kwargs_values=dict(color=bg, fontsize=10, fontweight="bold"),
        )

    # Hide per-slice value number badges.
    for t in baker.get_value_texts():
        t.set_visible(False)
    for t in baker.get_compare_value_texts():
        t.set_visible(False)

    # --- Header ------------------------------------------------------------
    primary_label = _player_display_name(primary)
    compare_label = _player_display_name(compare) if compare else None

    if title is None:
        title = f"{primary_label} vs {compare_label}" if compare else primary_label
    if subtitle is None:
        if compare:
            t1 = primary.get("team_name") or ""
            t2 = compare.get("team_name") or ""
            subtitle = f"{t1} · {t2}" if t1 or t2 else ""
        else:
            subtitle = primary.get("team_name") or ""

    _add_header(fig, title, subtitle, style, enabled=show_header)

    # --- Footer ------------------------------------------------------------
    if show_footer:
        if footer_lines is None:
            raw_note = "  |  ".join(
                f"{label} {_format_stat_value(val, key)}"
                for label, val, key in zip(stat_labels, primary_raw, stat_keys)
            )
            footer_lines = [
                "What it shows: percentile ranks against the position-group benchmark (all players in the competition at the same position).",
                "Rings mark the Q1 / Q2 / Q3 / max boundaries.  Values above the outer ring are capped at 100.",
            ]
            if compare:
                compare_raw_note = "  |  ".join(
                    f"{label} {_format_stat_value(val, key)}"
                    for label, val, key in zip(stat_labels, compare_raw, stat_keys)
                )
                footer_lines += [
                    f"Raw values ({primary_label}): {raw_note}",
                    f"Raw values ({compare_label}): {compare_raw_note}",
                ]
            else:
                footer_lines.append(f"Raw per-90 values: {raw_note}")

        _add_footer(footer_ax, footer_lines, style)

    # --- Legend for comparison plots ---------------------------------------
    if compare:
        legend_y = 0.128 if show_footer else 0.06
        fig.text(0.08, legend_y, f"● {primary_label}",
                 color=_HIGHLIGHT, fontsize=10, fontweight="bold", va="top")
        fig.text(0.08 + 0.28, legend_y, f"● {compare_label}",
                 color=accent_2, fontsize=10, fontweight="bold", va="top")

    return _save(fig, output_path)


# ---------------------------------------------------------------------------
# Generic half-pitch map (template)
# ---------------------------------------------------------------------------

def build_player_pitch_map(
    player: dict,
    output_path: Path,
    style: dict[str, str],
    *,
    scatter_layers: "list[dict] | None" = None,
    arrow_layers: "list[dict] | None" = None,
    stats_line: str,
    legend_items: "list[tuple[str, str, str]]",
    title: str | None = None,
    subtitle: str | None = None,
    footer_lines: list[str] | None = None,
    show_footer: bool = True,
    show_header: bool = True,
) -> Path:
    """Render a vertical half-pitch map for one player and save a PNG.

    This is the generic template. Callers prepare the data and call this
    function; see build_player_shot_map for a worked example.

    Parameters
    ----------
    player:
        Player dict from make_player_radar_input().
    output_path:
        Destination PNG path.
    style:
        Colour palette from settings.plot_style.
    scatter_layers:
        Each entry is a dict passed straight to pitch.scatter (after popping
        ``x`` and ``y``). Keys: ``x``, ``y``, and any pitch.scatter kwargs
        (``s``, ``color``, ``facecolors``, ``edgecolors``, ``alpha``,
        ``zorder``, …). Empty arrays are silently skipped.
    arrow_layers:
        Each entry is a dict passed straight to pitch.arrows (after popping
        ``xstart``, ``ystart``, ``xend``, ``yend``). Any pitch.arrows kwargs
        (``color``, ``width``, ``headwidth``, ``alpha``, ``zorder``, …).
        Empty arrays are silently skipped.
    stats_line:
        Single-line summary rendered between the header and the legend,
        e.g. "34 Shots  ·  5 Goals  ·  3.21 xG".
    legend_items:
        List of (marker_char, hex_color, label) tuples, one per category.
        Positions are distributed evenly across the figure width.
    title:
        Bold main title. Defaults to the player's display name.
    subtitle:
        Muted subtitle. Defaults to the player's team name.
    show_footer:
        When False the footer panel is omitted and the pitch expands downward.
    """
    try:
        from mplsoccer import VerticalPitch
    except Exception as exc:
        raise RuntimeError("mplsoccer is required for pitch map plots.") from exc

    if plt is None:
        raise RuntimeError("matplotlib is required for pitch map plots.")

    bg = style["bg"]
    line_col = style["line"]
    muted = style["muted"]

    # --- Figure layout -------------------------------------------------------
    fig = plt.figure(figsize=(10, 11), facecolor=bg)
    if show_footer and show_header:
        pitch_ax = fig.add_axes([0.03, 0.13, 0.94, 0.66])
        footer_ax = fig.add_axes([0.05, 0.03, 0.90, 0.08])
        footer_ax.set_facecolor(bg)
        footer_ax.set_xticks([])
        footer_ax.set_yticks([])
        for spine in footer_ax.spines.values():
            spine.set_visible(False)
    elif show_footer and not show_header:
        pitch_ax = fig.add_axes([0.03, 0.13, 0.94, 0.82])
        footer_ax = fig.add_axes([0.05, 0.03, 0.90, 0.08])
        footer_ax.set_facecolor(bg)
        footer_ax.set_xticks([])
        footer_ax.set_yticks([])
        for spine in footer_ax.spines.values():
            spine.set_visible(False)
    elif not show_footer and show_header:
        pitch_ax = fig.add_axes([0.03, 0.03, 0.94, 0.76])
        footer_ax = None
    else:  # not show_footer and not show_header
        pitch_ax = fig.add_axes([0.03, 0.03, 0.94, 0.94])
        footer_ax = None

    # --- Pitch ---------------------------------------------------------------
    pitch = VerticalPitch(
        pitch_type="custom",
        pitch_length=100,
        pitch_width=100,
        half=True,
        pitch_color=bg,
        line_color=line_col,
        linewidth=1.5,
        goal_type="box",
        corner_arcs=True,
        pad_left=-1.2,
        pad_right=-1.2,
        pad_top=0.3,
        pad_bottom=1.5,
        line_zorder=3,
    )
    pitch.draw(ax=pitch_ax)

    # --- Scatter layers ------------------------------------------------------
    # Mirror y (100 - y) to correct VerticalPitch's CW rotation which puts
    # y=0 on the right instead of the left.
    for layer in (scatter_layers or []):
        layer = dict(layer)
        x = layer.pop("x")
        y = 100 - layer.pop("y")
        if hasattr(x, "__len__") and len(x) == 0:
            continue
        pitch.scatter(x, y, ax=pitch_ax, **layer)

    # --- Arrow layers --------------------------------------------------------
    for layer in (arrow_layers or []):
        layer = dict(layer)
        xstart = layer.pop("xstart")
        ystart = 100 - layer.pop("ystart")
        xend = layer.pop("xend")
        yend = 100 - layer.pop("yend")
        if hasattr(xstart, "__len__") and len(xstart) == 0:
            continue
        pitch.arrows(xstart, ystart, xend, yend, ax=pitch_ax, **layer)

    # --- Header --------------------------------------------------------------
    if title is None:
        title = _player_display_name(player)
    if subtitle is None:
        subtitle = player.get("team_name") or ""

    _add_header(fig, title, subtitle, style, enabled=show_header)

    # Force layout so mplsoccer's equal-aspect adjustment settles before we
    # query the actual axes bounds for positioning.
    fig.canvas.draw()
    pos = pitch_ax.get_position()

    if show_header:
        # Subtitle sits at y=0.893 (fontsize 14, va="top"); approximate its bottom.
        header_bottom = 0.893 - 14 / 72 / 11
        pitch_top = pos.y1
        gap = header_bottom - pitch_top
        stats_y = header_bottom - gap / 3
        legend_y_fig = header_bottom - 2 * gap / 3
    else:
        # No header — place stats/legend in the gap between figure top and pitch top.
        pitch_top = pos.y1
        fig_top = 0.98
        gap = fig_top - pitch_top
        stats_y = fig_top - gap / 3
        legend_y_fig = fig_top - 2 * gap / 3

    legend_y_axes = (legend_y_fig - pos.y0) / pos.height

    # --- Stats line ----------------------------------------------------------
    fig.text(
        0.5, stats_y, stats_line,
        color=muted, fontsize=18, ha="center", va="center",
    )

    # --- Legend --------------------------------------------------------------
    n = len(legend_items)
    xs = [i / (n + 1) for i in range(1, n + 1)]
    for (marker, color, label), x in zip(legend_items, xs):
        pitch_ax.text(
            x, legend_y_axes, f"{marker}  {label}",
            transform=pitch_ax.transAxes,
            color=color, fontsize=13, ha="center", va="center",
            fontweight="bold", clip_on=False,
        )

    # --- Footer --------------------------------------------------------------
    if show_footer and footer_ax is not None:
        _add_footer(footer_ax, footer_lines or [], style, width=115)

    return _save(fig, output_path)


# ---------------------------------------------------------------------------
# Shot map (wrapper around build_player_pitch_map)
# ---------------------------------------------------------------------------

def build_player_shot_map(
    player: dict,
    shots_df: "pd.DataFrame",
    output_path: Path,
    style: dict[str, str],
    title: str | None = None,
    subtitle: str | None = None,
    footer_lines: list[str] | None = None,
    show_footer: bool = True,
    show_header: bool = True,
) -> Path:
    """Render a shot map for one player. Wraps build_player_pitch_map."""
    try:
        import pandas as pd
    except Exception as exc:
        raise RuntimeError("pandas is required for shot map plots.") from exc

    if shots_df is None or (hasattr(shots_df, "empty") and shots_df.empty):
        raise ValueError(f"No shot data provided for player {player.get('name')}.")

    muted = style["muted"]
    accent_2 = style["accent_2"]
    line_col = style["line"]

    off_target = shots_df[~shots_df["on_target"] & ~shots_df["is_goal"]]
    on_target_saved = shots_df[shots_df["on_target"] & ~shots_df["is_goal"]]
    goals = shots_df[shots_df["is_goal"]]

    def _size(df):
        return 120 + df["xg"].clip(lower=0.01) * 2000

    scatter_layers = [
        {
            "x": off_target["x"], "y": off_target["y"],
            "s": _size(off_target),
            "facecolors": "none", "edgecolors": muted,
            "linewidth": 1.5, "alpha": 0.75, "zorder": 4,
        },
        {
            "x": on_target_saved["x"], "y": on_target_saved["y"],
            "s": _size(on_target_saved),
            "color": accent_2, "edgecolors": line_col,
            "linewidth": 1.0, "alpha": 0.88, "zorder": 5,
        },
        {
            "x": goals["x"], "y": goals["y"],
            "s": _size(goals),
            "color": _HIGHLIGHT, "edgecolors": line_col,
            "linewidth": 1.0, "alpha": 0.97, "zorder": 6,
        },
    ]

    total = len(shots_df)
    n_goals = int(shots_df["is_goal"].sum())
    total_xg = shots_df["xg"].sum()

    stats_line = f"{total} Shots  ·  {n_goals} Goals  ·  {total_xg:.2f} xG"
    legend_items = [
        ("●", _HIGHLIGHT, "Goal"),
        ("●", accent_2,   "On target (saved)"),
        ("○", muted,      "Off target / blocked"),
    ]

    if footer_lines is None and show_footer:
        box_shots = int(shots_df["inside_box"].sum()) if "inside_box" in shots_df.columns else 0
        n_on_target = int(shots_df["on_target"].sum())
        footer_lines = [
            "What it shows: all shots taken by this player in the current season.",
            "Marker size = xG.  ● Goals  ● On target (saved)  ○ Off target / blocked.",
            f"Shots: {total}  |  Goals: {n_goals}  |  xG: {total_xg:.2f}  |  Box shots: {box_shots}  |  On target: {n_on_target}",
        ]

    if title is None:
        title = f"{_player_display_name(player)} - Shots"

    return build_player_pitch_map(
        player=player,
        output_path=output_path,
        style=style,
        scatter_layers=scatter_layers,
        stats_line=stats_line,
        legend_items=legend_items,
        title=title,
        subtitle=subtitle,
        footer_lines=footer_lines,
        show_footer=show_footer,
        show_header=show_header,
    )


# ---------------------------------------------------------------------------
# Assist / key-pass map (wrapper around build_player_pitch_map)
# ---------------------------------------------------------------------------

def build_player_assist_map(
    player: dict,
    key_passes_df: "pd.DataFrame",
    output_path: Path,
    style: dict[str, str],
    title: str | None = None,
    subtitle: str | None = None,
    footer_lines: list[str] | None = None,
    show_footer: bool = True,
    show_header: bool = True,
) -> Path:
    """Render a key-pass / assist map for one player. Wraps build_player_pitch_map.

    Each marker is the origin of the pass (where the player was standing).
    Assists (passes that led to a goal) are highlighted; other key passes
    (shot assists without a goal) are shown in the secondary accent colour.
    """
    try:
        import pandas as pd
    except Exception as exc:
        raise RuntimeError("pandas is required for assist map plots.") from exc

    if key_passes_df is None or (hasattr(key_passes_df, "empty") and key_passes_df.empty):
        raise ValueError(f"No key-pass data provided for player {player.get('name')}.")

    accent_2 = style["accent_2"]

    assists = key_passes_df[key_passes_df["is_assist"]]
    key_passes = key_passes_df[~key_passes_df["is_assist"]]

    arrow_layers = [
        {
            "xstart": key_passes["x"], "ystart": key_passes["y"],
            "xend": key_passes["end_x"], "yend": key_passes["end_y"],
            "color": accent_2, "width": 1.5, "headwidth": 4,
            "headlength": 4, "alpha": 0.75, "zorder": 4,
        },
        {
            "xstart": assists["x"], "ystart": assists["y"],
            "xend": assists["end_x"], "yend": assists["end_y"],
            "color": _HIGHLIGHT, "width": 2.0, "headwidth": 5,
            "headlength": 5, "alpha": 0.95, "zorder": 5,
        },
    ]

    n_assists = len(assists)
    n_key_passes = len(key_passes)
    stats_line = f"{n_key_passes + n_assists} Key Passes  ·  {n_assists} Assists"
    legend_items = [
        ("→", _HIGHLIGHT, "Assist"),
        ("→", accent_2,   "Key pass"),
    ]

    if footer_lines is None and show_footer:
        footer_lines = [
            "What it shows: all key passes and assists by this player in the current season.",
            "Arrow goes from pass origin to pass destination (where the shot was taken).",
            f"Key passes: {n_key_passes + n_assists}  |  Assists (led to goal): {n_assists}",
        ]

    if title is None:
        title = f"{_player_display_name(player)} - Key passes"

    return build_player_pitch_map(
        player=player,
        output_path=output_path,
        style=style,
        arrow_layers=arrow_layers,
        stats_line=stats_line,
        legend_items=legend_items,
        title=title,
        subtitle=subtitle,
        footer_lines=footer_lines,
        show_footer=show_footer,
        show_header=show_header,
    )


# ---------------------------------------------------------------------------
# Dribble map (wrapper around build_player_pitch_map)
# ---------------------------------------------------------------------------

def build_player_dribble_map(
    player: dict,
    dribbles_df: "pd.DataFrame",
    output_path: Path,
    style: dict[str, str],
    title: str | None = None,
    subtitle: str | None = None,
    footer_lines: list[str] | None = None,
    show_footer: bool = True,
    show_header: bool = True,
) -> Path:
    """Render a dribble map for one player. Wraps build_player_pitch_map.

    Each dot is one dribble attempt. Successful (kept possession) are filled
    in the highlight colour; unsuccessful are hollow in the muted colour.
    """
    if dribbles_df is None or (hasattr(dribbles_df, "empty") and dribbles_df.empty):
        raise ValueError(f"No dribble data provided for player {player.get('name')}.")

    muted = style["muted"]

    successful = dribbles_df[dribbles_df["successful"]]
    unsuccessful = dribbles_df[~dribbles_df["successful"]]

    arrow_layers = [
        {
            "xstart": unsuccessful["x"], "ystart": unsuccessful["y"],
            "xend": unsuccessful["end_x"], "yend": unsuccessful["end_y"],
            "color": muted, "width": 1.5, "headwidth": 4,
            "headlength": 4, "alpha": 0.65, "zorder": 4,
        },
        {
            "xstart": successful["x"], "ystart": successful["y"],
            "xend": successful["end_x"], "yend": successful["end_y"],
            "color": _HIGHLIGHT, "width": 2.0, "headwidth": 5,
            "headlength": 5, "alpha": 0.90, "zorder": 5,
        },
    ]

    n_total = len(dribbles_df)
    n_success = len(successful)
    pct = round(100 * n_success / n_total) if n_total else 0
    stats_line = f"{n_success}/{n_total} Successful  ·  {pct}%"
    legend_items = [
        ("→", _HIGHLIGHT, "Successful"),
        ("→", muted,      "Unsuccessful"),
    ]

    if footer_lines is None and show_footer:
        footer_lines = [
            "What it shows: all dribble attempts by this player in the current season.",
            "Arrow goes from dribble start to the location of the next event.",
            f"Attempts: {n_total}  |  Successful: {n_success}  |  Success rate: {pct}%",
        ]

    if title is None:
        title = f"{_player_display_name(player)} - Dribbles"

    return build_player_pitch_map(
        player=player,
        output_path=output_path,
        style=style,
        arrow_layers=arrow_layers,
        stats_line=stats_line,
        legend_items=legend_items,
        title=title,
        subtitle=subtitle,
        footer_lines=footer_lines,
        show_footer=show_footer,
        show_header=show_header,
    )


# ---------------------------------------------------------------------------
# Pass heatmap (standalone — full Pitch, not VerticalPitch template)
# ---------------------------------------------------------------------------

def _add_colorbar_local(fig, mappable, rect, label: str, style: dict):
    cax = fig.add_axes(rect)
    cax.set_facecolor(style["bg"])
    colorbar = fig.colorbar(mappable, cax=cax)
    colorbar.outline.set_edgecolor(style["line"])
    colorbar.ax.yaxis.set_tick_params(color=style["text"], labelcolor=style["text"])
    colorbar.ax.set_ylabel(label, color=style["text"], fontsize=9.5)
    import matplotlib.pyplot as _plt
    _plt.setp(colorbar.ax.get_yticklabels(), color=style["text"], fontsize=8.5)
    return colorbar


def build_player_pass_heatmap(
    player: dict,
    passes_df: "pd.DataFrame",
    output_path: Path,
    style: dict[str, str],
    title: str | None = None,
    subtitle: str | None = None,
    footer_lines: list[str] | None = None,
    show_footer: bool = True,
    show_header: bool = True,
    *,
    _x_col: str = "x",
    _y_col: str = "y",
    _colorbar_label: str = "Passes per zone",
) -> Path:
    """Render a pass-origin heatmap for one player and save a PNG.

    Uses a full horizontal pitch (not a half-pitch) to show where on the
    field the player tends to receive and distribute the ball.

    Parameters
    ----------
    player:
        Player dict from make_player_radar_input().
    passes_df:
        DataFrame from load_player_passes() — must have x, y, accurate columns.
    output_path:
        Destination PNG path.
    style:
        Colour palette from settings.plot_style.
    title:
        Bold main title. Defaults to player display name.
    subtitle:
        Muted subtitle. Defaults to team name.
    footer_lines:
        Text for the footer panel. Auto-generated when None.
    show_footer:
        When False the footer panel is omitted.
    """
    try:
        from mplsoccer import VerticalPitch
    except Exception as exc:
        raise RuntimeError("mplsoccer is required for pass heatmap plots.") from exc

    if plt is None:
        raise RuntimeError("matplotlib is required for pass heatmap plots.")

    if passes_df is None or (hasattr(passes_df, "empty") and passes_df.empty):
        raise ValueError(f"No pass data provided for player {player.get('name')}.")

    bg = style["bg"]
    line_col = style["line"]
    accent_2 = style["accent_2"]

    # --- Figure layout (portrait — matches action heatmap) -------------------
    fig = plt.figure(figsize=(9, 13), facecolor=bg)
    if show_footer and show_header:
        pitch_ax = fig.add_axes([0.05, 0.13, 0.90, 0.73])
        footer_ax = fig.add_axes([0.05, 0.03, 0.90, 0.08])
        footer_ax.set_facecolor(bg)
        footer_ax.set_xticks([])
        footer_ax.set_yticks([])
        for spine in footer_ax.spines.values():
            spine.set_visible(False)
    elif show_footer and not show_header:
        pitch_ax = fig.add_axes([0.05, 0.13, 0.90, 0.83])
        footer_ax = fig.add_axes([0.05, 0.03, 0.90, 0.08])
        footer_ax.set_facecolor(bg)
        footer_ax.set_xticks([])
        footer_ax.set_yticks([])
        for spine in footer_ax.spines.values():
            spine.set_visible(False)
    elif not show_footer and show_header:
        pitch_ax = fig.add_axes([0.05, 0.03, 0.90, 0.83])
        footer_ax = None
    else:  # not show_footer and not show_header
        pitch_ax = fig.add_axes([0.05, 0.02, 0.90, 0.96])
        footer_ax = None

    # --- Pitch (vertical, matching action heatmap) ---------------------------
    pitch = VerticalPitch(
        pitch_type="custom",
        pitch_length=100,
        pitch_width=100,
        pitch_color=bg,
        line_color=line_col,
        linewidth=1.4,
        goal_type="box",
        corner_arcs=True,
        line_zorder=3,
    )
    pitch.draw(ax=pitch_ax)

    # --- Heatmap & labels — single source of truth: np.histogram2d ----------
    # Both the coloured rectangles and the % text use the exact same bin edges
    # so colours and numbers are guaranteed to align.
    # VerticalPitch axes: x-axis (horizontal) = lateral (100 - Wyscout y),
    #                     y-axis (vertical)   = depth (Wyscout x).
    import matplotlib.patheffects as _pe
    import numpy as _np

    _N_LAT, _N_DEP = 5, 6          # 5 columns left→right, 6 rows goal→goal
    _lat_edges = _np.linspace(0, 100, _N_LAT + 1)
    _dep_edges = _np.linspace(0, 100, _N_DEP + 1)
    _lat_centers = (_lat_edges[:-1] + _lat_edges[1:]) / 2
    _dep_centers = (_dep_edges[:-1] + _dep_edges[1:]) / 2

    _x_data = (100 - passes_df[_y_col]).values
    _y_data = passes_df[_x_col].values
    # _counts[xi, yi]: lateral bin xi × depth bin yi  →  shape (N_LAT, N_DEP)
    _counts, _, _ = _np.histogram2d(_x_data, _y_data, bins=[_lat_edges, _dep_edges])
    n_total_pre = int(_counts.sum())

    # Colour grid: pcolormesh expects C[row, col] = C[yi, xi]  →  transpose
    cmap = LinearSegmentedColormap.from_list(
        "j_sodra_heat",
        [bg, _PANEL, accent_2, _HIGHLIGHT],
    )
    pitch_ax.pcolormesh(
        _lat_edges, _dep_edges, _counts.T,
        cmap=cmap, alpha=0.96, zorder=2,
    )
    # Cell borders that match the pitch line colour
    for xe in _lat_edges:
        pitch_ax.axvline(xe, color=bg, linewidth=0.8, zorder=3)
    for ye in _dep_edges:
        pitch_ax.axhline(ye, color=bg, linewidth=0.8, zorder=3)

    for xi in range(_N_LAT):
        for yi in range(_N_DEP):
            count = int(_counts[xi, yi])
            if count == 0:
                continue
            pct_val = count / n_total_pre * 100
            label = "<1%" if pct_val < 1 else f"{pct_val:.0f}%"
            pitch_ax.text(
                _lat_centers[xi], _dep_centers[yi], label,
                ha="center", va="center",
                fontsize=16, fontweight="bold",
                color=style["text"], zorder=5,
                path_effects=[_pe.withStroke(linewidth=2.0, foreground=bg)],
            )

    # --- Attacking direction label -------------------------------------------
    pitch_ax.text(
        0.5, -0.06, "Attacking  ↑",
        transform=pitch_ax.transAxes,
        color=style["muted"], fontsize=15, ha="center", va="top",
        clip_on=False,
    )

    # --- Header --------------------------------------------------------------
    if title is None:
        title = f"{_player_display_name(player)} - Pass start"
    if subtitle is None:
        subtitle = player.get("team_name") or ""

    _add_header(fig, title, subtitle, style, enabled=show_header)

    # --- Footer --------------------------------------------------------------
    n_total = len(passes_df)
    n_accurate = int(passes_df["accurate"].sum()) if "accurate" in passes_df.columns else 0
    acc_pct = round(100 * n_accurate / n_total) if n_total else 0

    if show_footer and footer_ax is not None:
        if footer_lines is None:
            footer_lines = [
                "What it shows: all passes attempted by this player in the current season, binned by origin zone.",
                "Brighter squares indicate zones where the player passes from most frequently.",
                f"Total passes: {n_total}  |  Accurate: {n_accurate}  |  Accuracy: {acc_pct}%",
            ]
        _add_footer(footer_ax, footer_lines, style, width=130)

    return _save(fig, output_path)


def build_player_action_heatmap(
    player: dict,
    actions_df: "pd.DataFrame",
    output_path: Path,
    style: dict[str, str],
    title: str | None = None,
    subtitle: str | None = None,
    footer_lines: list[str] | None = None,
    show_footer: bool = True,
    show_header: bool = True,
) -> Path:
    """Render a smooth KDE heatmap of open-play actions for one player.

    Uses a full vertical pitch and kernel density estimation for a smooth
    density surface, matching the style of commercial player heatmaps.

    Parameters
    ----------
    player:
        Player dict from make_player_radar_input().
    actions_df:
        DataFrame from load_player_open_play_actions() — x, y, event_type.
    output_path:
        Destination PNG path.
    style:
        Colour palette from settings.plot_style.
    title:
        Bold main title. Defaults to player display name.
    subtitle:
        Muted subtitle. Defaults to "Team · N Open Play Actions".
    show_footer:
        When False the footer panel is omitted.
    """
    try:
        from mplsoccer import VerticalPitch
    except Exception as exc:
        raise RuntimeError("mplsoccer is required for action heatmap plots.") from exc

    if plt is None:
        raise RuntimeError("matplotlib is required for action heatmap plots.")

    if actions_df is None or (hasattr(actions_df, "empty") and actions_df.empty):
        raise ValueError(f"No action data provided for player {player.get('name')}.")

    bg = style["bg"]
    line_col = style["line"]

    # --- Figure layout (portrait) --------------------------------------------
    fig = plt.figure(figsize=(9, 13), facecolor=bg)
    if show_footer and show_header:
        pitch_ax = fig.add_axes([0.05, 0.13, 0.90, 0.73])
        footer_ax = fig.add_axes([0.05, 0.03, 0.90, 0.08])
        footer_ax.set_facecolor(bg)
        footer_ax.set_xticks([])
        footer_ax.set_yticks([])
        for spine in footer_ax.spines.values():
            spine.set_visible(False)
    elif show_footer and not show_header:
        pitch_ax = fig.add_axes([0.05, 0.13, 0.90, 0.83])
        footer_ax = fig.add_axes([0.05, 0.03, 0.90, 0.08])
        footer_ax.set_facecolor(bg)
        footer_ax.set_xticks([])
        footer_ax.set_yticks([])
        for spine in footer_ax.spines.values():
            spine.set_visible(False)
    elif not show_footer and show_header:
        pitch_ax = fig.add_axes([0.05, 0.03, 0.90, 0.83])
        footer_ax = None
    else:  # not show_footer and not show_header
        pitch_ax = fig.add_axes([0.05, 0.02, 0.90, 0.96])
        footer_ax = None

    # --- Pitch ---------------------------------------------------------------
    pitch = VerticalPitch(
        pitch_type="custom",
        pitch_length=100,
        pitch_width=100,
        pitch_color=bg,
        line_color=line_col,
        linewidth=1.4,
        goal_type="box",
        corner_arcs=True,
        line_zorder=3,
    )
    pitch.draw(ax=pitch_ax)

    # --- KDE heatmap: bg → panel → yellow ------------------------------------
    cmap = LinearSegmentedColormap.from_list(
        "j_sodra_action",
        [(0.0, bg), (0.25, _PANEL), (1.0, _HIGHLIGHT)],
    )
    # Mirror y so that the left flank (y≈0 in Wyscout) appears on the LEFT
    # of the vertical display. mplsoccer's VerticalPitch rotates CW which
    # puts y=0 on the right — flipping corrects this.
    pitch.kdeplot(
        actions_df["x"],
        100 - actions_df["y"],
        ax=pitch_ax,
        cmap=cmap,
        fill=True,
        levels=100,
        thresh=0,
        alpha=0.88,
        zorder=2,
    )

    # --- Attacking direction label -------------------------------------------
    pitch_ax.text(
        0.5, -0.06, "Attacking  ↑",
        transform=pitch_ax.transAxes,
        color=style["muted"], fontsize=15, ha="center", va="top",
        clip_on=False,
    )

    # --- Header --------------------------------------------------------------
    n_actions = len(actions_df)
    if title is None:
        title = f"{_player_display_name(player)} - Heatmap"
    if subtitle is None:
        team = player.get("team_name") or ""
        subtitle = f"{team}  ·  {n_actions:,} Open Play Actions"

    _add_header(fig, title, subtitle, style, enabled=show_header)

    # --- Footer --------------------------------------------------------------
    if show_footer and footer_ax is not None:
        if footer_lines is None:
            footer_lines = [
                "What it shows: kernel density of all open-play actions (passes, shots, duels, touches) in the current season.",
                "Set pieces (corners, free kicks, goal kicks, throw-ins, penalties) are excluded. Brighter zones = higher activity.",
            ]
        _add_footer(footer_ax, footer_lines, style, width=115)

    return _save(fig, output_path)


def build_player_pass_end_heatmap(
    player: dict,
    passes_df: "pd.DataFrame",
    output_path: Path,
    style: dict[str, str],
    title: str | None = None,
    subtitle: str | None = None,
    footer_lines: list[str] | None = None,
    show_footer: bool = True,
    show_header: bool = True,
) -> Path:
    """Render a pass-destination heatmap for one player and save a PNG.

    Shows where the player's passes land rather than where they originate.
    Requires passes_df from load_player_passes() which includes end_x/end_y.
    """
    if title is None:
        title = f"{_player_display_name(player)} - Pass end"

    n_total = len(passes_df)
    n_accurate = int(passes_df["accurate"].sum()) if "accurate" in passes_df.columns else 0
    acc_pct = round(100 * n_accurate / n_total) if n_total else 0

    if footer_lines is None and show_footer:
        footer_lines = [
            "What it shows: all pass destinations for this player in the current season, binned by landing zone.",
            "Brighter squares indicate zones the player tends to find with their passes.",
            f"Total passes: {n_total}  |  Accurate: {n_accurate}  |  Accuracy: {acc_pct}%",
        ]

    return build_player_pass_heatmap(
        player=player,
        passes_df=passes_df,
        output_path=output_path,
        style=style,
        title=title,
        subtitle=subtitle,
        footer_lines=footer_lines,
        show_footer=show_footer,
        show_header=show_header,
        _x_col="end_x",
        _y_col="end_y",
        _colorbar_label="Pass destinations per zone",
    )


# ---------------------------------------------------------------------------
# Scatter plot — league-wide, one dot per player
# ---------------------------------------------------------------------------

def build_scatter_plot(
    players_data: list[dict],
    x_label: str,
    y_label: str,
    output_path: Path,
    style: dict[str, str],
    title: str | None = None,
    subtitle: str | None = None,
    footer_lines: list[str] | None = None,
    show_footer: bool = True,
    highlight_team: str | None = None,
    show_header: bool = True,
) -> Path:
    """Render a league-wide scatter plot with one dot per player, coloured by team.

    Each player is represented by a single coloured square marker. Labels show
    the player's name in the text token; the square colour carries team identity.
    An optional highlight_team gets the project's yellow accent and a larger marker.

    Parameters
    ----------
    players_data:
        List of dicts with keys:
            name  — player display name
            team  — team name (determines colour group)
            x     — x-axis value
            y     — y-axis value
    x_label:
        Human-readable x-axis label.
    y_label:
        Human-readable y-axis label.
    output_path:
        Destination PNG path.
    style:
        Colour palette from settings.plot_style.
    """
    if plt is None:
        raise RuntimeError("matplotlib is required for scatter plots.")
    if not players_data:
        raise ValueError("players_data must not be empty.")

    import matplotlib.patheffects as _pe
    from itertools import cycle as _cycle
    from matplotlib.lines import Line2D

    bg       = style["bg"]
    line_col = style["line"]
    text_col = style["text"]
    muted    = style["muted"]

    # Assign a unique colour to each team in order of first appearance.
    # highlight_team always gets _HIGHLIGHT. All other teams draw from
    # _TEAM_PALETTE (20 distinct hues); if there are even more teams the
    # palette cycles so no two adjacent teams ever share a colour.
    teams = list(dict.fromkeys(p["team"] for p in players_data))
    palette_no_hl = [c for c in _TEAM_PALETTE if c != _HIGHLIGHT]
    _color_cycle = _cycle(palette_no_hl)
    team_color: dict[str, str] = {}
    for team in teams:
        if team == highlight_team:
            team_color[team] = _HIGHLIGHT
        else:
            team_color[team] = next(_color_cycle)

    # --- Figure layout -------------------------------------------------------
    fig = plt.figure(figsize=(15, 10), facecolor=bg)
    # Reserve right strip for the team legend
    if show_footer and show_header:
        ax = fig.add_axes([0.07, 0.16, 0.72, 0.72])
        footer_ax = fig.add_axes([0.05, 0.03, 0.90, 0.10])
        footer_ax.set_facecolor(bg)
        footer_ax.set_xticks([])
        footer_ax.set_yticks([])
        for spine in footer_ax.spines.values():
            spine.set_visible(False)
    elif show_footer and not show_header:
        ax = fig.add_axes([0.07, 0.16, 0.72, 0.80])
        footer_ax = fig.add_axes([0.05, 0.03, 0.90, 0.10])
        footer_ax.set_facecolor(bg)
        footer_ax.set_xticks([])
        footer_ax.set_yticks([])
        for spine in footer_ax.spines.values():
            spine.set_visible(False)
    elif not show_footer and show_header:
        ax = fig.add_axes([0.07, 0.08, 0.72, 0.82])
        footer_ax = None
    else:  # not show_footer and not show_header
        ax = fig.add_axes([0.07, 0.06, 0.72, 0.92])
        footer_ax = None

    legend_ax = fig.add_axes([0.81, 0.20, 0.17, 0.60])
    legend_ax.set_facecolor(bg)
    for spine in legend_ax.spines.values():
        spine.set_visible(False)
    legend_ax.set_xticks([])
    legend_ax.set_yticks([])

    # --- Main axes styling ---------------------------------------------------
    ax.set_facecolor(bg)
    for spine in ax.spines.values():
        spine.set_edgecolor(line_col)
        spine.set_linewidth(0.8)
        spine.set_alpha(0.4)
    ax.tick_params(colors=muted, labelsize=8.5)
    ax.set_xlabel(x_label, color=muted, fontsize=10.5, labelpad=8)
    ax.set_ylabel(y_label, color=muted, fontsize=10.5, labelpad=8)
    ax.grid(color=line_col, alpha=0.12, linewidth=0.6, zorder=0)

    # --- Scatter markers ------------------------------------------------------
    # highlight_team → star (★), all others → square (■).
    # highlight_team gets the project yellow + a larger marker to stand out.
    for p in players_data:
        col = team_color[p["team"]]
        is_hl = p["team"] == highlight_team
        ax.scatter(
            p["x"], p["y"],
            color=col,
            s=380 if is_hl else 55,
            marker="*" if is_hl else "o",
            zorder=5 if is_hl else 4,
            edgecolors=bg, linewidths=1.2 if is_hl else 0.8,
        )

    # --- Player name labels (adjustText for collision avoidance) -------------
    # Names are in the muted text token; the square marker carries team identity.
    texts = []
    for p in players_data:
        t = ax.text(
            p["x"], p["y"], p["name"],
            color=text_col, fontsize=7, va="center", zorder=6,
            path_effects=[_pe.withStroke(linewidth=1.8, foreground=bg)],
        )
        texts.append(t)

    try:
        from adjustText import adjust_text as _adjust_text
        _adjust_text(
            texts,
            x=[p["x"] for p in players_data],
            y=[p["y"] for p in players_data],
            ax=ax,
            arrowprops=dict(arrowstyle="-", color=muted, lw=0.5, alpha=0.5),
            expand=(1.2, 1.4),
            force_text=(0.3, 0.5),
            force_points=(0.2, 0.3),
        )
    except Exception:
        pass  # fall back to raw placement if adjustText unavailable

    # --- Team legend (right panel) -------------------------------------------
    # highlight_team uses ● (circle); all others use ■ (square).
    n_teams = len(teams)
    step = 0.95 / max(n_teams, 1)
    for i, team in enumerate(teams):
        col = team_color[team]
        y_pos = 0.97 - i * step
        marker_char = "★" if team == highlight_team else "●"
        legend_ax.text(0.05, y_pos, marker_char, color=col, fontsize=10,
                       transform=legend_ax.transAxes, va="center")
        legend_ax.text(0.25, y_pos, team, color=text_col, fontsize=8,
                       transform=legend_ax.transAxes, va="center")

    # --- Header --------------------------------------------------------------
    if title is None:
        title = f"{x_label} vs {y_label}"
    _add_header(fig, title, "", style, enabled=show_header)

    # --- Footer --------------------------------------------------------------
    if show_footer and footer_ax is not None:
        if footer_lines is None:
            footer_lines = [
                "Each point represents one player. Colour and ■ swatch indicate team. Values are per 90 minutes (minimum minutes threshold applied).",
            ]
        _add_footer(footer_ax, footer_lines, style)

    return _save(fig, output_path)


# ---------------------------------------------------------------------------
# Player report — self-contained HTML with all plots embedded
# ---------------------------------------------------------------------------

import base64 as _base64
import tempfile as _tempfile
import urllib.request as _urllib_request


def _png_to_b64(path: Path) -> str:
    return _base64.b64encode(path.read_bytes()).decode()


def _fetch_image_b64(url: str, timeout: int = 5) -> str | None:
    """Fetch an image URL and return a data URI, or None on failure."""
    try:
        req = _urllib_request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with _urllib_request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
        mime = "image/png" if url.lower().endswith(".png") else "image/jpeg"
        return f"data:{mime};base64,{_base64.b64encode(data).decode()}"
    except Exception:
        return None


def _initials_svg(name: str) -> str:
    """SVG circle with player initials — used when no real photo is available."""
    parts = name.strip().split()
    initials = "".join(p[0].upper() for p in parts[:2]) if parts else "?"
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="110" height="110">'
        '<circle cx="55" cy="55" r="55" fill="#0b3427"/>'
        f'<text x="55" y="55" dominant-baseline="central" text-anchor="middle" '
        f'fill="#ffdc6e" font-size="36" font-family="system-ui,sans-serif" '
        f'font-weight="800">{initials}</text>'
        "</svg>"
    )
    return f"data:image/svg+xml;base64,{_base64.b64encode(svg.encode()).decode()}"


def _report_html(
    player_name: str,
    team: str,
    position: str,
    nationality: str,
    photo_src: str,
    plots: dict,
    *,
    shirt_number: int | None = None,
    height: int | None = None,
    foot: str | None = None,
    date_of_birth: str | None = None,
    team_logo_src: str | None = None,
    positions_data: list[dict] | None = None,   # list of {code, name, percent, minutes}
) -> str:
    """Assemble the full HTML string for the player report."""

    def _card(key: str, label: str = "", extra_class: str = "") -> str:
        b64 = plots.get(key)
        inner = (
            f'<img src="data:image/png;base64,{b64}" alt="{label}">'
            if b64 else
            f'<div class="missing">{label or key} — no data</div>'
        )
        lbl = f'<p class="card-label">{label}</p>' if label else ""
        cls = f"card {extra_class}".strip() if extra_class else "card"
        return f'<div class="{cls}">{lbl}{inner}</div>'

    # Positions breakdown card (pure HTML, no image)
    def _positions_card() -> str:
        rows_data = sorted(positions_data or [], key=lambda p: -p["percent"])
        if not rows_data:
            return ""
        rows_html = ""
        for row in rows_data:
            code    = (row.get("code") or "").upper()
            name    = row.get("name") or code
            pct     = row.get("percent") or 0
            mins    = row.get("minutes")
            bar_w   = max(4, int(pct))
            mins_td = f'<td>{int(mins):,} min</td>' if mins is not None else "<td>—</td>"
            rows_html += (
                f"<tr>"
                f'<td style="text-align:left;font-weight:700">{code}</td>'
                f"{mins_td}"
                f"<td>{pct:.0f}%</td>"
                f"</tr>"
            )
        table = (
            '<table class="pos-table">'
            "<thead><tr><th>Position</th><th>Minutes</th><th>%</th></tr></thead>"
            f"<tbody>{rows_html}</tbody>"
            "</table>"
        )
        return f'<div class="card" style="margin-top:16px"><p class="card-label">Time by Position</p>{table}</div>'

    scatter_html = (
        '<section class="section"><h2 class="section-title">League Context</h2>'
        f'<div class="grid-1">{_card("scatter")}</div></section>'
        if plots.get("scatter") else ""
    )

    # Compute age from date_of_birth
    age_str = ""
    if date_of_birth:
        try:
            from datetime import date
            dob = date.fromisoformat(date_of_birth)
            today = date.today()
            age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
            age_str = f"{age} yrs"
        except Exception:
            pass

    # Build header chips — only render chips that have data
    def _chip(icon: str, value: str | None) -> str:
        if not value:
            return ""
        return f'<span class="chip">{icon} <strong>{value}</strong></span>'

    height_str = f"{height} cm" if height else None
    foot_str   = f"{foot} foot" if foot else None

    chips = "".join([
        _chip("⚽", position),
        _chip("📏", height_str),
        _chip("🦶", foot_str),
        _chip("🌍", nationality),
        _chip("🎂", age_str or None),
    ])

    # Team logo — shown on the right of the header
    team_logo_html = (
        f'<img class="team-logo" src="{team_logo_src}" alt="{team}">'
        if team_logo_src
        else f'<span class="team-name-fallback">{team}</span>'
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{player_name} — Player Report</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  :root {{
    --bg:     #002418;
    --panel:  #0b3427;
    --panel2: #0f3d2e;
    --text:   #ffffff;
    --muted:  #7a9e8e;
    --accent: #ffdc6e;
    --border: rgba(255,255,255,0.07);
    --r:      12px;
  }}
  body {{
    background: var(--bg);
    color: var(--text);
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
    padding: 28px 32px;
    max-width: 1600px;
    margin: 0 auto;
  }}
  /* Header */
  .header {{
    display: flex;
    align-items: center;
    gap: 28px;
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: var(--r);
    padding: 24px 32px;
    margin-bottom: 22px;
  }}
  .header-left {{ display: flex; align-items: center; gap: 28px; flex: 1; min-width: 0; }}
  .photo-wrap {{
    position: relative;
    flex-shrink: 0;
    width: 110px;
    height: 110px;
  }}
  .photo {{
    width: 110px; height: 110px;
    border-radius: 50%;
    object-fit: cover;
    border: 2.5px solid var(--accent);
    background: var(--panel2);
    display: block;
  }}
  .shirt-badge {{
    position: absolute;
    bottom: 2px; right: 2px;
    background: var(--accent);
    color: #002418;
    font-size: 0.72rem;
    font-weight: 800;
    border-radius: 99px;
    padding: 1px 6px;
    line-height: 1.6;
    white-space: nowrap;
  }}
  .player-name {{
    font-size: 2.4rem;
    font-weight: 800;
    letter-spacing: -0.02em;
    line-height: 1.1;
  }}
  .player-meta {{
    margin-top: 10px;
    display: flex;
    gap: 18px;
    flex-wrap: wrap;
    align-items: center;
  }}
  .chip {{
    display: flex;
    align-items: center;
    gap: 5px;
    font-size: 0.85rem;
    color: var(--muted);
    background: rgba(255,255,255,0.05);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 3px 10px;
  }}
  .chip strong {{ color: var(--text); font-weight: 600; }}
  .team-logo {{
    width: 100px; height: 100px;
    object-fit: contain;
    flex-shrink: 0;
    opacity: 0.92;
    filter: drop-shadow(0 2px 8px rgba(0,0,0,0.4));
  }}
  .team-name-fallback {{
    font-size: 1rem; font-weight: 700; color: var(--muted);
  }}
  /* Section */
  .section {{ margin-bottom: 20px; }}
  .section-title {{
    font-size: 0.72rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    color: var(--muted);
    margin-bottom: 10px;
    padding-left: 2px;
  }}
  /* Cards */
  .card {{
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: var(--r);
    overflow: hidden;
  }}
  .card img {{ width: 100%; display: block; }}
  .card-label {{
    font-size: 1rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.09em;
    color: var(--text);
    padding: 14px 16px 6px;
    text-align: center;
  }}
  .missing {{
    display: flex; align-items: center; justify-content: center;
    height: 120px;
    color: var(--muted); font-size: 0.85rem;
  }}
  /* Position breakdown table */
  .pos-table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 0.88rem;
  }}
  .pos-table th {{
    font-size: 0.7rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--muted);
    text-align: left;
    padding: 8px 14px 6px;
    border-bottom: 1px solid var(--border);
  }}
  .pos-table th:not(:first-child) {{ text-align: right; }}
  .pos-table td {{
    padding: 9px 14px;
    border-bottom: 1px solid var(--border);
    color: var(--text);
  }}
  .pos-table td:not(:first-child) {{ text-align: right; color: var(--muted); }}
  .pos-table td:last-child {{ color: var(--accent); font-weight: 700; }}
  .pos-table tr:last-child td {{ border-bottom: none; }}
  .pos-bar-cell {{ position: relative; }}
  .pos-bar {{
    display: inline-block;
    height: 6px;
    background: var(--accent);
    border-radius: 3px;
    opacity: 0.55;
    vertical-align: middle;
    margin-right: 6px;
  }}
  /* Grids */
  .grid-1  {{ display: grid; grid-template-columns: 1fr; gap: 16px; }}
  .grid-2  {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
  .grid-3  {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 16px; align-items: start; }}
  .span-2  {{ grid-column: span 2; }}
  @media (max-width: 860px) {{
    .grid-2,.grid-3 {{ grid-template-columns: 1fr; }}
    .span-2         {{ grid-column: span 1; }}
  }}
</style>
</head>
<body>

<header class="header">
  <div class="header-left">
    <div class="photo-wrap">
      <img class="photo" src="{photo_src}" alt="{player_name}">
      {f'<span class="shirt-badge">#{shirt_number}</span>' if shirt_number else ''}
    </div>
    <div>
      <div class="player-name">{player_name}</div>
      <div class="player-meta">{chips}</div>
    </div>
  </div>
  {team_logo_html}
</header>

<section class="section">
  <h2 class="section-title">Profile &amp; Position</h2>
  <div class="grid-3">
    {_card("pizza", extra_class="span-2")}
    <div>
      {_card("position_map")}
      {_positions_card()}
    </div>
  </div>
</section>

<section class="section">
  <h2 class="section-title">On-Ball Actions</h2>
  <div class="grid-3">
    {_card("shot_map",    "Shots")}
    {_card("assist_map",  "Key Passes &amp; Assists")}
    {_card("dribble_map", "Dribbles")}
  </div>
</section>

<section class="section">
  <h2 class="section-title">Movement &amp; Distribution</h2>
  <div class="grid-3">
    {_card("action_heatmap", "Action Heatmap")}
    {_card("pass_start",     "Pass Origin")}
    {_card("pass_end",       "Pass Destination")}
  </div>
</section>

{scatter_html}

</body>
</html>"""


def build_player_report(
    player: dict,
    player_profile: dict,
    stat_keys: list[str],
    stat_labels: list[str],
    benchmarks: dict,
    events_dir: Path,
    output_path: Path,
    style: dict[str, str],
    *,
    scatter_players: list[dict] | None = None,
    scatter_x_label: str = "x",
    scatter_y_label: str = "y",
    scatter_title: str | None = None,
    scatter_subtitle: str | None = None,
    highlight_team: str | None = None,
    sofascore_profile: dict | None = None,
) -> Path:
    """Build a self-contained HTML player report and save it to output_path.

    Generates all individual plots internally (pizza, position map, shot map,
    assist map, dribble map, action heatmap, pass start/end heatmaps) in a
    temporary directory, encodes them as base64, and assembles a single dark-
    themed HTML file that requires no external assets.

    An optional scatter section provides league-wide context.

    Parameters
    ----------
    player:
        Player dict from make_player_radar_input().
    player_profile:
        Raw player record from competition_*_players.json.
    stat_keys / stat_labels:
        Stat profile for the pizza chart.
    benchmarks:
        From competition_*_position_benchmarks.json.
    events_dir:
        Directory containing match_*.json event cache files.
    output_path:
        Destination .html path.
    scatter_players:
        Pre-built list of {name, team, x, y} dicts for the league scatter.
        Omit to skip the scatter section.
    highlight_team:
        Team to highlight in the scatter (defaults to player's team).
    """
    from pipeline.sections.player_analysis.metrics import (
        bucket_player_position,
        load_player_dribbles,
        load_player_key_passes,
        load_player_open_play_actions,
        load_player_passes,
        load_player_shots,
    )

    if plt is None:
        raise RuntimeError("matplotlib is required to build player reports.")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    events_dir = Path(events_dir)

    wy_id    = player["player_id"]
    name     = player.get("name", f"Player {wy_id}")
    team     = player.get("team_name") or ""
    pos_code = player.get("position_code") or ""
    pos_label = (
        (bucket_player_position(pos_code) or pos_code or "—")
        .replace("_", " ").title()
    )
    nationality = (
        (player_profile.get("passportArea") or player_profile.get("birthArea") or {})
        .get("name") or "—"
    )

    # Player photo — prefer SofaScore photo, fall back to Wyscout, then initials SVG
    ss = sofascore_profile or {}
    photo_src = ss.get("photo_b64") or None
    if not photo_src:
        raw_url  = player_profile.get("imageDataURL") or player_profile.get("imagePath") or ""
        use_real = raw_url and "ndplayer" not in raw_url
        photo_src = (_fetch_image_b64(raw_url) if use_real else None) or _initials_svg(name)

    # SofaScore-enriched profile fields
    ss_nationality = ss.get("nationality")
    shirt_number   = ss.get("shirt_number")
    height         = ss.get("height")
    foot           = ss.get("foot")
    date_of_birth  = ss.get("date_of_birth")
    nationality    = ss_nationality or nationality
    team_logo_src  = ss.get("team_logo_b64") or None

    # Load event data
    shots_df      = load_player_shots(wy_id, events_dir)
    passes_df     = load_player_passes(wy_id, events_dir)
    key_passes_df = load_player_key_passes(wy_id, events_dir)
    dribbles_df   = load_player_dribbles(wy_id, events_dir)
    actions_df    = load_player_open_play_actions(wy_id, events_dir)

    plots: dict[str, str | None] = {}

    with _tempfile.TemporaryDirectory() as _tmp:
        tmp = Path(_tmp)

        def _run(key: str, fn, **kwargs) -> None:
            try:
                p = fn(**kwargs, output_path=tmp / f"{key}.png",
                        style=style, show_footer=False, show_header=False)
                plots[key] = _png_to_b64(p)
            except Exception as exc:
                print(f"  [report] {key} skipped — {exc}")
                plots[key] = None

        _run("pizza", build_player_pizza,
             players=[player], stat_keys=stat_keys,
             stat_labels=stat_labels, benchmarks=benchmarks)

        _run("position_map", build_player_position_map, player=player)

        if not shots_df.empty:
            _run("shot_map", build_player_shot_map,
                 player=player, shots_df=shots_df)
        else:
            plots["shot_map"] = None

        if not key_passes_df.empty:
            _run("assist_map", build_player_assist_map,
                 player=player, key_passes_df=key_passes_df)
        else:
            plots["assist_map"] = None

        if not dribbles_df.empty:
            _run("dribble_map", build_player_dribble_map,
                 player=player, dribbles_df=dribbles_df)
        else:
            plots["dribble_map"] = None

        if not actions_df.empty:
            _run("action_heatmap", build_player_action_heatmap,
                 player=player, actions_df=actions_df)
        else:
            plots["action_heatmap"] = None

        if not passes_df.empty:
            _run("pass_start", build_player_pass_heatmap,
                 player=player, passes_df=passes_df)
            _run("pass_end", build_player_pass_end_heatmap,
                 player=player, passes_df=passes_df)
        else:
            plots["pass_start"] = plots["pass_end"] = None

        if scatter_players:
            try:
                p = build_scatter_plot(
                    players_data=scatter_players,
                    x_label=scatter_x_label,
                    y_label=scatter_y_label,
                    output_path=tmp / "scatter.png",
                    style=style,
                    title=scatter_title,
                    subtitle=scatter_subtitle,
                    show_footer=False,
                    highlight_team=highlight_team or team,
                )
                plots["scatter"] = _png_to_b64(p)
            except Exception as exc:
                print(f"  [report] scatter skipped — {exc}")
                plots["scatter"] = None
        else:
            plots["scatter"] = None

    # Build positions breakdown list for the sidebar card
    _raw_positions = (player.get("stats") or {}).get("positions") or []
    _total_mins    = ((player.get("stats") or {}).get("total") or {}).get("minutesOnField")
    positions_data: list[dict] = []
    for _pe in _raw_positions:
        _pos  = _pe.get("position") or {}
        _code = (_pos.get("code") or "").lower()
        _name = _pos.get("name") or _code.upper()
        _pct  = float(_pe.get("percent") or 0)
        _mins = round(_total_mins * _pct / 100) if _total_mins else None
        if _pct > 0:
            positions_data.append({"code": _code, "name": _name, "percent": _pct, "minutes": _mins})

    html = _report_html(
        player_name=name,
        team=team,
        position=pos_label,
        nationality=nationality,
        photo_src=photo_src,
        plots=plots,
        shirt_number=shirt_number,
        height=height,
        foot=foot,
        date_of_birth=date_of_birth,
        team_logo_src=team_logo_src,
        positions_data=positions_data,
    )
    output_path.write_text(html, encoding="utf-8")
    return output_path
