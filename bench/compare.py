"""Merge bench/results/*.json into a comparison table and figure for the report.

python -m bench.compare bench/results/*.json --out bench/results/comparison.md
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--out", default="bench/results/comparison.md")
    a = ap.parse_args(argv)
    runs = [json.loads(Path(f).read_text()) for f in a.files]
    runs = [r for r in runs if "summary" in r]
    lines = [
        "# Benchmark comparison",
        "",
        "| config | instance | OpenCV | KleidiCV in build | machine | analysis fps (median, 720p) | with decode fps | realtime x (analysis) | realtime x (with decode) | USD / video-hour (with decode) | time in cv2 built-ins |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in runs:
        e = r["env"]
        c = r["clips"].get("bench_strobe.mp4", next(iter(r["clips"].values())))
        s = r["summary"]
        cost = s.get("usd_per_video_hour_included")
        lines.append(
            f"| {r['label']} | {e.get('ec2_instance_type') or '-'} | {e['opencv_version']} | {'yes' if e.get('build_has_kleidicv') else 'no'} | {e['machine']} | "
            f"{c['fps_excluded']:.1f} | {c['fps_included']:.1f} | {s['median_realtime_factor_excluded']:.1f} | {s['median_realtime_factor_included']:.1f} | "
            f"{(f'{cost:.4f}') if cost else '-'} | {r['profile']['fraction_in_cv2']:.2f} |"
        )
    lines += [
        "",
        "Per-operation micro-benchmark, median ms on one 1280x720 frame:",
        "",
        "| op | " + " | ".join(r["label"] for r in runs) + " |",
        "|---|" + "---|" * len(runs),
    ]
    ops = list(runs[0]["micro_ms"].keys())
    for op in ops:
        lines.append(
            f"| {op} | "
            + " | ".join(
                f"{r['micro_ms'].get(op, {}).get('median', float('nan')):.3f}" for r in runs
            )
            + " |"
        )
    lines += ["", "Spread (p25..p75 of analysis-only seconds per clip):", ""]
    for r in runs:
        for name, c in r["clips"].items():
            d = c["decode_excluded_s"]
            lines.append(
                f"- {r['label']} {name}: median {d['median']:.3f} s, p25 {d['p25']:.3f}, p75 {d['p75']:.3f}, min {d['min']:.3f}, max {d['max']:.3f} (n={d['n']})"
            )
    Path(a.out).write_text("\n".join(lines) + "\n")
    fig, ax = plt.subplots(figsize=(6, 3.2))
    labels = [r["label"] for r in runs]
    ax.bar(
        labels,
        [
            r["clips"].get("bench_strobe.mp4", next(iter(r["clips"].values())))["fps_excluded"]
            for r in runs
        ],
        color="#1c7ed6",
        label="analysis only",
    )
    ax.bar(
        labels,
        [
            r["clips"].get("bench_strobe.mp4", next(iter(r["clips"].values())))["fps_included"]
            for r in runs
        ],
        color="#2b8a3e",
        alpha=0.6,
        label="with decode",
    )
    ax.set_ylabel("frames / s (720p)")
    ax.legend(fontsize=8)
    ax.set_title("analysis throughput by configuration")
    plt.setp(ax.get_xticklabels(), rotation=15, ha="right", fontsize=8)
    fig.tight_layout()
    fig.savefig(Path(a.out).with_suffix(".png"), dpi=110)
    print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
