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
    from matplotlib.patches import Rectangle
except Exception:
    plt = None
    Rectangle = None

from pipeline.analytics import bucket_player_position

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
             color=style["text"], fontsize=24, fontweight="bold",
             ha="left", va="top")
    fig.text(0.05, 0.905, subtitle,
             color=style["muted"], fontsize=11.5,
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
    role = player_profile.get("role") or {}
    name = (
        player_profile.get("shortName")
        or player_profile.get("name")
        or f"Player {player_profile.get('wyId', '')}"
    )
    return {
        "player_id": player_profile.get("wyId"),
        "name": name,
        "position_code": role.get("code2"),   # "GK" / "DF" / "MD" / "FW" — used for benchmark lookup
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
    title: str = "Player Radar",
    subtitle: str | None = None,
    footer_lines: list[str] | None = None,
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
    fig = plt.figure(figsize=(10, 10), facecolor=style["bg"])
    ax = fig.add_axes([0.08, 0.14, 0.84, 0.68], polar=True)
    footer_ax = fig.add_axes([0.05, 0.03, 0.90, 0.10])

    ax.set_facecolor(style["bg"])
    footer_ax.set_facecolor(style["bg"])
    footer_ax.set_xticks([])
    footer_ax.set_yticks([])
    for spine in footer_ax.spines.values():
        spine.set_visible(False)

    # --- Polar axis setup --------------------------------------------------
    ax.set_theta_offset(np.pi / 2)
    ax.set_theta_direction(-1)
    ax.set_ylim(0, 100)
    ax.set_yticks([25, 50, 75, 100])
    ax.set_yticklabels(["25", "50", "75", "100"],
                       color=style["muted"], fontsize=9)
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(stat_labels, color=style["text"], fontsize=11)
    ax.grid(color=style["line"], alpha=0.22)
    ax.spines["polar"].set_color(style["line"])

    # --- Radar series ------------------------------------------------------
    _draw_radar_series(
        ax, angles, primary_pct,
        line_color=_HIGHLIGHT,
        fill_color=style["accent"],
        dot_color=style["accent_2"],
    )
    if compare_pct:
        _draw_radar_series(
            ax, angles, compare_pct,
            line_color=style["accent_2"],
            fill_color=style["accent_2"],
            dot_color=_HIGHLIGHT,
        )

    primary_label = _player_display_name(primary)
    compare_label = _player_display_name(compare) if compare else None

    # --- Header ------------------------------------------------------------
    if subtitle is None:
        if compare:
            subtitle = f"{primary_label} vs {compare_label}"
        else:
            subtitle = primary_label

    _add_header(fig, title, subtitle, style)

    # --- Footer ------------------------------------------------------------
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
        fig.text(0.08, 0.128, f"● {primary_label}",
                 color=_HIGHLIGHT, fontsize=10, fontweight="bold", va="top")
        fig.text(0.08 + 0.28, 0.128, f"● {compare_label}",
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
    title: str = "Position Map",
    subtitle: str | None = None,
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
        Smaller muted subtitle. Defaults to the player display name.
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
    pitch_ax = fig.add_axes([0.05, 0.14, 0.90, 0.74])
    footer_ax = fig.add_axes([0.05, 0.03, 0.90, 0.09])

    footer_ax.set_facecolor(style["bg"])
    footer_ax.set_xticks([])
    footer_ax.set_yticks([])
    for spine in footer_ax.spines.values():
        spine.set_visible(False)

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
            name,
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
    if subtitle is None:
        subtitle = _player_display_name(player)

    _add_header(fig, title, subtitle, style)

    # --- Footer ------------------------------------------------------------
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
