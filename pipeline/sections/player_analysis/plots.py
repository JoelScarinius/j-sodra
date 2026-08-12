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

def _add_header(fig, title: str, subtitle: str, style: dict):
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
    if show_footer:
        ax = fig.add_axes([0.14, 0.16, 0.72, 0.62], polar=True)
        footer_ax = fig.add_axes([0.05, 0.03, 0.90, 0.10])
        footer_ax.set_facecolor(style["bg"])
        footer_ax.set_xticks([])
        footer_ax.set_yticks([])
        for spine in footer_ax.spines.values():
            spine.set_visible(False)
    else:
        ax = fig.add_axes([0.14, 0.16, 0.72, 0.68], polar=True)
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

    _add_header(fig, title, subtitle, style)

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
        from mplsoccer import Pitch
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
    fig = plt.figure(figsize=(14, 9), facecolor=style["bg"])
    if show_footer:
        pitch_ax = fig.add_axes([0.05, 0.14, 0.90, 0.74])
        footer_ax = fig.add_axes([0.05, 0.03, 0.90, 0.09])
        footer_ax.set_facecolor(style["bg"])
        footer_ax.set_xticks([])
        footer_ax.set_yticks([])
        for spine in footer_ax.spines.values():
            spine.set_visible(False)
    else:
        pitch_ax = fig.add_axes([0.05, 0.05, 0.90, 0.83])
        footer_ax = None

    # --- Pitch -------------------------------------------------------------
    pitch = Pitch(
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
    max_pct = max(pct for *_, pct, _, _ in entries)

    for x, y, pct, code, name in entries:
        intensity = pct / max_pct          # 0.0 → 1.0 relative to this player's most-played
        alpha = 0.35 + 0.65 * intensity    # 0.35 at minimum, 1.0 at max
        size = 800 + 4200 * (pct / 100)   # scales from ~800 (tiny) to ~5000 (100 %)

        pitch_ax.scatter(
            x, y,
            s=size,
            color=style["accent"],
            alpha=alpha,
            edgecolors=style["line"],
            linewidth=1.2,
            zorder=4,
        )
        pitch_ax.text(
            x, y,
            f"{pct:.0f}%",
            color=style["bg"],
            fontsize=9,
            fontweight="bold",
            ha="center",
            va="center",
            zorder=5,
        )
        pitch_ax.text(
            x, y - 6,
            code.upper(),
            color=style["text"],
            fontsize=7.5,
            ha="center",
            va="top",
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

    _add_header(fig, title, subtitle, style)

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
    fig = plt.figure(figsize=(10, 10), facecolor=bg)
    if show_footer:
        pizza_ax = fig.add_axes([0.08, 0.14, 0.84, 0.68], polar=True)
        footer_ax = fig.add_axes([0.05, 0.03, 0.90, 0.10])
        footer_ax.set_facecolor(bg)
        footer_ax.set_xticks([])
        footer_ax.set_yticks([])
        for spine in footer_ax.spines.values():
            spine.set_visible(False)
    else:
        pizza_ax = fig.add_axes([0.08, 0.14, 0.84, 0.74], polar=True)
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
            kwargs_params=dict(color=text_col, fontsize=10, va="center"),
            kwargs_values=dict(color=bg, fontsize=9, fontweight="bold"),
            kwargs_compare_values=dict(color=bg, fontsize=9, fontweight="bold"),
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
            kwargs_params=dict(color=text_col, fontsize=10, va="center"),
            kwargs_values=dict(color=bg, fontsize=9, fontweight="bold"),
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

    _add_header(fig, title, subtitle, style)

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
    if show_footer:
        pitch_ax = fig.add_axes([0.03, 0.13, 0.94, 0.66])
        footer_ax = fig.add_axes([0.05, 0.03, 0.90, 0.08])
        footer_ax.set_facecolor(bg)
        footer_ax.set_xticks([])
        footer_ax.set_yticks([])
        for spine in footer_ax.spines.values():
            spine.set_visible(False)
    else:
        pitch_ax = fig.add_axes([0.03, 0.03, 0.94, 0.76])
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

    _add_header(fig, title, subtitle, style)

    # Force layout so mplsoccer's equal-aspect adjustment settles before we
    # query the actual axes bounds for positioning.
    fig.canvas.draw()
    pos = pitch_ax.get_position()

    # Subtitle sits at y=0.893 (fontsize 14, va="top"); approximate its bottom.
    header_bottom = 0.893 - 14 / 72 / 11
    pitch_top = pos.y1

    gap = header_bottom - pitch_top
    stats_y = header_bottom - gap / 3
    legend_y_fig = header_bottom - 2 * gap / 3
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
        from mplsoccer import Pitch
    except Exception as exc:
        raise RuntimeError("mplsoccer is required for pass heatmap plots.") from exc

    if plt is None:
        raise RuntimeError("matplotlib is required for pass heatmap plots.")

    if passes_df is None or (hasattr(passes_df, "empty") and passes_df.empty):
        raise ValueError(f"No pass data provided for player {player.get('name')}.")

    bg = style["bg"]
    line_col = style["line"]
    accent_2 = style["accent_2"]

    # --- Figure layout (landscape) -------------------------------------------
    fig = plt.figure(figsize=(13, 9), facecolor=bg)
    if show_footer:
        pitch_ax = fig.add_axes([0.05, 0.16, 0.85, 0.73])
        footer_ax = fig.add_axes([0.05, 0.03, 0.90, 0.10])
        footer_ax.set_facecolor(bg)
        footer_ax.set_xticks([])
        footer_ax.set_yticks([])
        for spine in footer_ax.spines.values():
            spine.set_visible(False)
    else:
        pitch_ax = fig.add_axes([0.05, 0.05, 0.85, 0.83])
        footer_ax = None

    # --- Pitch ---------------------------------------------------------------
    pitch = Pitch(
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

    # --- Heatmap -------------------------------------------------------------
    cmap = LinearSegmentedColormap.from_list(
        "j_sodra_heat",
        [bg, _PANEL, accent_2, _HIGHLIGHT],
    )
    # Mirror y so left flank (y≈0 in Wyscout) appears at the TOP of the pitch.
    # mplsoccer Pitch() places y=0 at the bottom; 100-y flips this so that
    # left flank is up, right flank is down, attacking runs left→right.
    heat = pitch.bin_statistic(
        passes_df[_x_col],
        100 - passes_df[_y_col],
        statistic="count",
        bins=(18, 12),
    )
    heatmap = pitch.heatmap(heat, ax=pitch_ax, cmap=cmap, edgecolors=bg, alpha=0.96)
    _add_colorbar_local(fig, heatmap, (0.91, 0.20, 0.018, 0.55), _colorbar_label, style)

    # --- Percentage labels inside each non-empty zone ------------------------
    import matplotlib.patheffects as _pe
    stat = heat["statistic"]
    cx = heat["cx"]
    cy = heat["cy"]
    n_total_pre = len(passes_df)
    for r in range(stat.shape[0]):
        for c in range(stat.shape[1]):
            count = stat[r, c]
            if count == 0:
                continue
            pct_val = count / n_total_pre * 100
            label = "1%" if pct_val < 1 else f"{pct_val:.0f}%"
            pitch_ax.text(
                cx[r, c], cy[r, c], label,
                ha="center", va="center",
                fontsize=7.5, fontweight="bold",
                color=style["text"], zorder=5,
                path_effects=[_pe.withStroke(linewidth=1.5, foreground=bg)],
            )

    # --- Attacking direction label -------------------------------------------
    pitch_ax.text(
        0.5, -0.02, "Attacking  →",
        transform=pitch_ax.transAxes,
        color=style["muted"], fontsize=9, ha="center", va="top",
        clip_on=False,
    )

    # --- Header --------------------------------------------------------------
    if title is None:
        title = f"{_player_display_name(player)} - Pass start"
    if subtitle is None:
        subtitle = player.get("team_name") or ""

    _add_header(fig, title, subtitle, style)

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
    if show_footer:
        pitch_ax = fig.add_axes([0.05, 0.13, 0.90, 0.73])
        footer_ax = fig.add_axes([0.05, 0.03, 0.90, 0.08])
        footer_ax.set_facecolor(bg)
        footer_ax.set_xticks([])
        footer_ax.set_yticks([])
        for spine in footer_ax.spines.values():
            spine.set_visible(False)
    else:
        pitch_ax = fig.add_axes([0.05, 0.03, 0.90, 0.83])
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
        0.5, -0.01, "Attacking  ↑",
        transform=pitch_ax.transAxes,
        color=style["muted"], fontsize=9, ha="center", va="top",
        clip_on=False,
    )

    # --- Header --------------------------------------------------------------
    n_actions = len(actions_df)
    if title is None:
        title = f"{_player_display_name(player)} - Heatmap"
    if subtitle is None:
        team = player.get("team_name") or ""
        subtitle = f"{team}  ·  {n_actions:,} Open Play Actions"

    _add_header(fig, title, subtitle, style)

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
        _x_col="end_x",
        _y_col="end_y",
        _colorbar_label="Pass destinations per zone",
    )
