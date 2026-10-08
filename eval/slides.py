"""Results slides for the video, rendered from the frozen results (1920x1080 PNG).

    python -m eval.slides  -> docs/video/slides/01_detection.png ... 05_limits.png

Every number is read from eval/results/frozen/*.json and bench/results/*.json, so the slides
match the report. Re-run after `make freeze` (for example once the EC2 benchmark rows exist).
Stills and plots only; nothing here flashes.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import image as mpimg  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FROZEN = ROOT / "eval" / "results" / "frozen"
BENCH = ROOT / "bench" / "results"
OUT = ROOT / "docs" / "video" / "slides"

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
RULE = "#e4e3df"
ACCENT = "#2a78d6"

plt.rcParams.update(
    {
        "font.family": "sans-serif",
        "font.sans-serif": ["Inter", "Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"],
        "figure.facecolor": SURFACE,
        "axes.facecolor": SURFACE,
        "text.color": INK,
    }
)


def load(name: str) -> dict:
    return json.loads((FROZEN / f"{name}.json").read_text())


def slide(title: str, subtitle: str):
    fig = plt.figure(figsize=(19.2, 10.8), dpi=100)
    fig.text(0.05, 0.9, title, fontsize=46, weight="semibold", color=INK)
    fig.text(0.05, 0.85, subtitle, fontsize=22, color=INK_2)
    fig.add_artist(plt.Line2D([0.05, 0.95], [0.82, 0.82], color=RULE, lw=2))
    fig.text(
        0.05,
        0.03,
        "SteadyFrame · OpenCV 5 · numbers from eval/results/frozen",
        fontsize=14,
        color=INK_2,
    )
    return fig


def tiles(fig, items: list[tuple[str, str, str]], y: float, h: float = 0.22) -> None:
    """Stat tiles: (value, label, note). Values in ink, the accent only as a thin top rule."""
    n = len(items)
    w = 0.9 / n
    for i, (value, label, note) in enumerate(items):
        x = 0.05 + i * w
        fig.add_artist(plt.Line2D([x + 0.005, x + w - 0.02], [y + h, y + h], color=ACCENT, lw=4))
        fig.text(x + 0.005, y + h - 0.085, value, fontsize=64, weight="semibold", color=INK)
        fig.text(x + 0.005, y + h - 0.13, label, fontsize=21, color=INK)
        fig.text(x + 0.005, y + h - 0.17, note, fontsize=16, color=INK_2)


def picture(fig, path: Path, rect: list[float]) -> None:
    if not path.exists():
        return
    ax = fig.add_axes(rect)
    ax.imshow(mpimg.imread(str(path)))
    ax.axis("off")


def save(fig, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / name, facecolor=SURFACE)
    plt.close(fig)
    print(f"wrote {(OUT / name).relative_to(ROOT)}")


def detection() -> None:
    d, r = load("detection"), load("robustness_summary")
    fig = slide(
        "Detection: synthetic suite",
        f"{d['n_clips']} clips generated from a YAML config; ground truth from an independent 1-D implementation of the rules",
    )
    ps = d["per_second"]
    tiles(
        fig,
        [
            (
                f"{round(d['clip_accuracy'] * d['n_clips'])}/{d['n_clips']}",
                "clip verdicts correct",
                "pass / warn / fail",
            ),
            (
                f"{d['boundary_correct']}/{d['boundary_total']}",
                "boundary cases",
                "rate, swing, dark state, area",
            ),
            (f"{ps['f1']:.3f}", "per-second F1", f"{ps['tp']} true positives, {ps['fp']} false"),
            (
                f"{r['crf_correct']}/{r['crf_total']}",
                "H.264 re-encodes",
                "CRF 28 and 35 keep their verdict",
            ),
        ],
        y=0.5,
    )
    picture(fig, FROZEN / "fig_frequency_sweep.png", [0.05, 0.07, 0.9, 0.38])
    save(fig, "01_detection.png")


def external() -> None:
    e = load("external")
    w = e["by_profile"]["wcag"]
    fig = slide(
        "Clips made by other people",
        "EA IRIS test videos (BSD-3), Apple's flashing sample (MIT), Intel camera footage (CC BY 4.0); no label from this analyzer",
    )
    tiles(
        fig,
        [
            (f"{w['clip_agreement']}/{e['n_clips']}", "verdicts match the label", "both profiles"),
            (
                f"{w['iris_agreement']}/{w['iris_clips']}",
                "IRIS's own verdict",
                f"{w['iris_fail_frames_covered']}/{w['iris_fail_frames']} IRIS fail frames inside a segment",
            ),
            (
                f"{w['control_fp_seconds']}/{w['control_seconds']}",
                "control seconds flagged",
                f"{e['control_minutes']:.0f} minutes of camera footage",
            ),
            (
                f"{e['remediation']['fixed']['passed']}/{e['remediation']['fixed']['n']}",
                "hazards fixed",
                "after two bugs these clips found",
            ),
        ],
        y=0.5,
    )
    picture(fig, FROZEN / "fig_external_apple.png", [0.05, 0.07, 0.9, 0.38])
    save(fig, "02_external.png")


def remediation() -> None:
    fx = load("remediation")
    h = load("agent_vs_fixed")["agent"]
    b = load("agent_vs_fixed_bedrock")
    fig = slide(
        "Fix, then verify with the same analyzer",
        f"{fx['n_clips']} failing synthetic clips; a fix counts only if the whole file passes again",
    )
    rows = [
        ("", "fixed policy", "agent, heuristic", "agent, live Bedrock"),
        (
            "whole-file pass rate",
            f"{fx['passed']}/{fx['n_clips']}",
            f"{round(h['success_rate'] * h['n_clips'])}/{h['n_clips']}",
            f"{b['agent']['passed']}/{b['agent']['n_clips']}",
        ),
        (
            "attempts per segment",
            f"{fx['mean_iterations_per_segment']:.2f}",
            f"{h['mean_iterations_per_segment']:.2f}",
            f"{b['agent']['mean_iterations_per_segment']:.2f}",
        ),
        (
            "SSIM inside the hazard",
            f"{fx['mean_ssim_inside']:.3f}",
            f"{h['mean_ssim_inside']:.3f}",
            f"{b['agent']['mean_ssim_inside']:.3f}",
        ),
        (
            "SSIM outside",
            f"{fx['mean_ssim_outside']:.5f}",
            f"{h['mean_ssim_outside']:.5f}",
            f"{b['agent']['mean_ssim_outside']:.5f}",
        ),
        ("model cost, whole suite", "-", "-", f"{b['cost_usd']:.2f} USD"),
    ]
    xs = [0.05, 0.4, 0.6, 0.8]
    for i, row in enumerate(rows):
        y = 0.7 - i * 0.09
        for j, cell in enumerate(row):
            header = i == 0
            fig.text(
                xs[j],
                y,
                cell,
                fontsize=24 if header else 30,
                color=INK_2 if header or j == 0 else INK,
                weight="semibold" if (j > 0 and not header) else "normal",
            )
        if i < len(rows) - 1:
            fig.add_artist(plt.Line2D([0.05, 0.95], [y - 0.03, y - 0.03], color=RULE, lw=1.5))
    fig.text(
        0.05,
        0.12,
        "The model only sees the analyzer's numbers, never pixels. Higher SSIM inside = more of the picture kept.",
        fontsize=20,
        color=INK_2,
    )
    save(fig, "03_remediation.png")


def benchmark() -> None:
    runs = []
    for p in sorted(BENCH.glob("*.json")):
        try:
            d = json.loads(p.read_text())
            runs.append((d["label"], d["summary"]["median_realtime_factor_included"], d))
        except Exception:
            continue
    fig = slide(
        "Throughput: same code, three builds",
        "Analyzer on 1280x720 clips, decode included, median of 10 runs; realtime factor = video seconds per wall second",
    )
    if runs:
        hgt = min(0.5, 0.1 * len(runs) + 0.06)
        ax = fig.add_axes([0.25, 0.74 - hgt, 0.62, hgt])
        labels = [r[0] for r in runs][::-1]
        vals = [r[1] for r in runs][::-1]
        bars = ax.barh(labels, vals, color=ACCENT, height=0.6)
        for bar, v in zip(bars, vals, strict=True):
            ax.text(
                v,
                bar.get_y() + bar.get_height() / 2,
                f"  {v:.1f}x",
                va="center",
                fontsize=24,
                color=INK,
            )
        ax.set_xlim(0, max(vals) * 1.25)
        ax.tick_params(axis="y", labelsize=24, colors=INK, length=0)
        ax.tick_params(axis="x", labelsize=16, colors=INK_2)
        ax.grid(axis="x", color=RULE, lw=1)
        ax.set_axisbelow(True)
        for s in ("top", "right", "left"):
            ax.spines[s].set_visible(False)
        ax.spines["bottom"].set_color(RULE)
        ax.set_xlabel("realtime factor (higher is faster)", fontsize=18, color=INK_2)
    if len(runs) < 3:
        fig.text(
            0.05,
            0.2,
            "EC2 rows appear here after `python -m bench.ec2` (see bench/README.md).",
            fontsize=20,
            color=INK_2,
        )
    save(fig, "04_benchmark.png")


def limits() -> None:
    e = load("external")
    fig = slide(
        "Where it fails",
        "Stated in the report; every item has a test, a figure or a table behind it",
    )
    items = [
        "The area rule is quantised to grid cells: the 24% vs 26% clip flips at some grid sizes.",
        "Full-frame, full-swing strobes have no gentle fix; they go to a human for approval.",
        "Flashing that sits exactly at the limit is treated as one episode, which can cost quality.",
        f"External set is small: {e['n_clips']} clips, no concert or emergency-vehicle footage yet.",
        "No display model: relative luminance from sRGB stands in for cd/m².",
        "The pattern detector is experimental and only warns.",
        "Not a medical device. A pass means the published thresholds were met.",
    ]
    for i, t in enumerate(items):
        fig.text(0.07, 0.72 - i * 0.085, "•", fontsize=30, color=ACCENT)
        fig.text(0.095, 0.72 - i * 0.085, t, fontsize=28, color=INK)
    save(fig, "05_limits.png")


def main() -> int:
    detection()
    external()
    remediation()
    benchmark()
    limits()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
