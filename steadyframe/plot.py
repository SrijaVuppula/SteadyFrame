"""Luminance-over-time plots with hazard segments shaded. Stills and plots only: no
animated output ever leaves this module (docs/STANDARDS.md and docs/RESPONSIBLE_USE.md)."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

COLORS = {"general": "#d9480f", "red": "#c92a2a", "pattern": "#5f3dc4"}


def plot_analysis(
    result: dict, out: str | Path, *, after: dict | None = None, title: str | None = None
) -> Path:
    tl = result["timeline"]
    fig, axes = plt.subplots(
        2, 1, figsize=(11, 5.5), sharex=True, gridspec_kw={"height_ratios": [2, 1]}
    )
    ax = axes[0]
    ax.plot(tl["t"], tl["mean_L"], color="#1c7ed6", lw=1.2, label="mean relative luminance")
    if after is not None:
        ax.plot(
            after["timeline"]["t"],
            after["timeline"]["mean_L"],
            color="#2b8a3e",
            lw=1.2,
            label="after remediation",
        )
    for seg in result["segments"]:
        ax.axvspan(
            seg["start_s"], seg["end_s"], color=COLORS.get(seg["type"], "#868e96"), alpha=0.18
        )
        ax.text(
            seg["start_s"],
            0.97,
            f"{seg['id']} {seg['type']}",
            fontsize=7,
            va="top",
            color=COLORS.get(seg["type"], "#495057"),
        )
    ax.set_ylim(0, 1)
    ax.set_ylabel("relative luminance")
    ax.legend(loc="lower right", fontsize=8)
    ax.set_title(
        title
        or f"{Path(result['video'].get('path', '')).name}: verdict {result['verdict'].upper()}",
        fontsize=10,
    )

    ax2 = axes[1]
    ax2.plot(
        tl["t"],
        tl["general_rate_hz"],
        color=COLORS["general"],
        lw=1,
        label="general flash rate (Hz, max cell)",
    )
    ax2.plot(tl["t"], tl["red_rate_hz"], color=COLORS["red"], lw=1, ls="--", label="red flash rate")
    lim = result["profile"]["max_flashes_per_window"]
    ax2.axhline(lim, color="#868e96", lw=0.8, ls=":", label=f"limit ({lim}/s)")
    ax2.set_ylabel("flashes / s")
    ax2.set_xlabel("time (s)")
    ax2.legend(loc="upper right", fontsize=7)
    fig.tight_layout()
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=110)
    plt.close(fig)
    return out
