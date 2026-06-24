"""Head-to-head section plots."""

from __future__ import annotations

from pathlib import Path

try:
    import matplotlib.pyplot as plt
except Exception:
    plt = None


def plot_h2h_results(
    *,
    head_to_head_overview: dict,
    team_name: str,
    opponent_name: str,
    output_path: Path,
    style: dict[str, str],
) -> Path | None:
    """Create recent H2H goal-difference plot."""

    if plt is None:
        return None

    meetings = head_to_head_overview.get("meetings", []) if isinstance(head_to_head_overview, dict) else []
    if not meetings:
        return None

    latest = list(reversed(meetings[:6]))
    labels: list[str] = []
    goal_diff: list[int] = []

    for row in latest:
        if row.get("goals_for") is None or row.get("goals_against") is None:
            continue
        labels.append(str(row.get("dateutc") or row.get("season_id") or row.get("label") or "Meeting")[:10])
        goal_diff.append(int(row.get("goals_for") or 0) - int(row.get("goals_against") or 0))

    if not labels:
        return None

    fig, ax = plt.subplots(figsize=(10, 5))
    fig.patch.set_facecolor(style["bg"])
    ax.set_facecolor(style["bg"])

    colors = [
        style["accent_2"] if value > 0 else (style["danger"] if value < 0 else style["muted"])
        for value in goal_diff
    ]
    ax.bar(labels, goal_diff, color=colors, alpha=0.9)
    ax.axhline(0, color=style["line"], linewidth=1.0)
    ax.set_ylabel(f"Goal diff ({team_name} - {opponent_name})", color=style["line"])
    ax.tick_params(colors=style["line"], labelrotation=20)
    for spine in ax.spines.values():
        spine.set_color(style["line"])
    ax.set_title(
        f"{team_name} vs {opponent_name} recent H2H goal difference",
        color=style["line"],
    )
    fig.tight_layout()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=160, facecolor=style["bg"])
    plt.close(fig)
    return output_path


def generate_h2h_plots(*, context, head_to_head_overview: dict) -> dict[str, Path]:
    """Generate all H2H section plots and return name -> path."""

    if not context.opponent_name or not head_to_head_overview.get("found"):
        return {}

    output_path = context.settings.report_path("head_to_head", "plots", "goal_diff_recent.png")
    path = plot_h2h_results(
        head_to_head_overview=head_to_head_overview,
        team_name=context.team_name,
        opponent_name=context.opponent_name,
        output_path=output_path,
        style=context.settings.plot_style,
    )
    return {"goal_diff_recent": path} if path else {}
