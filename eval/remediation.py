"""Remediation evaluation: run the fixed policy on every failing synthetic clip.

    python -m eval.remediation [--policy fixed|agent] [--only substr]

Reports post-verification pass rate, strategy usage, iterations per segment, quality
retention (SSIM outside / inside regions, luminance change), runtime, and lists every
unresolved case with its reason. Results in eval/results/remediation{,_agent}.{md,json}.
"""

from __future__ import annotations

import argparse
import json
import statistics
import tempfile
from collections import Counter
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from steadyframe.remediate.pipeline import fix_file  # noqa: E402

from .common import RESULTS, header, load_suite, md_table, write  # noqa: E402


def run(gts: list[dict], policy: str, provider=None, *, workroot: Path | None = None) -> dict:
    rows = []
    strategies: Counter = Counter()
    for gt in gts:
        if gt["expected_verdict"] != "fail":
            continue
        name = gt["clip"].replace(".mp4", "")
        wd = (workroot or Path(tempfile.mkdtemp(prefix="sf-eval-"))) / policy / name
        out = wd / "safe.mp4"
        rep = fix_file(
            gt["_path"],
            out,
            policy=policy,
            workdir=wd,
            report_path=wd / "report.json",
            approve_all=True,  # offline evaluation: every approval request is granted and counted
            provider=provider,
        )
        n_att = sum(len(s["attempts"]) for s in rep["segments"])
        approvals = sum(1 for s in rep["segments"] if s.get("approval"))
        for s in rep["segments"]:
            if s["strategy"]:
                strategies[s["strategy"]] += 1
        q = rep.get("quality") or {}
        rows.append(
            {
                "clip": gt["clip"],
                "status": rep["status"],
                "segments": len(rep["segments"]),
                "accepted": sum(1 for s in rep["segments"] if s["outcome"] == "accepted"),
                "attempts": n_att,
                "iter_per_seg": n_att / max(1, len(rep["segments"])),
                "approvals": approvals,
                "strategies": ",".join(s["strategy"] or "-" for s in rep["segments"]),
                "ssim_outside": q.get("ssim_outside"),
                "ssim_inside": q.get("ssim_inside"),
                "dL_inside": q.get("mean_abs_dL_inside"),
                "runtime_s": rep["runtime_s"],
                "duration_s": rep["input"]["duration_analyzed_s"],
                "llm": (rep.get("llm") or {}),
                "reason": rep.get("error")
                or (
                    "; ".join(
                        f"{s['segment_id']}: {s['outcome']}"
                        for s in rep["segments"]
                        if s["outcome"] != "accepted"
                    )
                    if rep["status"] != "passed"
                    else ""
                ),
            }
        )
    n = len(rows)
    passed = sum(1 for r in rows if r["status"] == "passed")

    def mean(key):
        vals = [r[key] for r in rows if r.get(key) is not None]
        return statistics.mean(vals) if vals else None

    return {
        "policy": policy,
        "n_clips": n,
        "passed": passed,
        "success_rate": passed / n if n else None,
        "mean_iterations_per_segment": mean("iter_per_seg"),
        "mean_ssim_outside": mean("ssim_outside"),
        "mean_ssim_inside": mean("ssim_inside"),
        "mean_dL_inside": mean("dL_inside"),
        "mean_runtime_s": mean("runtime_s"),
        "mean_realtime_factor": statistics.mean(
            [r["duration_s"] / r["runtime_s"] for r in rows if r["runtime_s"]]
        )
        if rows
        else None,
        "approvals_requested": sum(r["approvals"] for r in rows),
        "strategy_usage": dict(strategies),
        "rows": rows,
        "unresolved": [r for r in rows if r["status"] != "passed"],
    }


def render_md(data: dict, title: str) -> str:
    md = header(title)
    md += (
        f"- Clips with hazards: **{data['n_clips']}**; post-verification pass rate **{data['success_rate']:.3f}** ({data['passed']}/{data['n_clips']})\n"
        f"- Mean iterations per segment **{data['mean_iterations_per_segment']:.2f}**; approvals requested {data['approvals_requested']} (auto-granted in this offline run)\n"
        f"- Quality retention: SSIM outside regions **{data['mean_ssim_outside']:.4f}**, inside regions {data['mean_ssim_inside']:.3f}, mean |dL| inside {data['mean_dL_inside']:.3f}\n"
        f"- Runtime: mean {data['mean_runtime_s']:.1f} s per clip, {data['mean_realtime_factor']:.2f}x realtime for the full analyze+fix+verify loop (320x240 clips)\n"
        f"- Strategy usage: {', '.join(f'{k}: {v}' for k, v in sorted(data['strategy_usage'].items()))}\n\n"
    )
    md += "## Per clip\n\n" + md_table(
        data["rows"],
        [
            "clip",
            "status",
            "segments",
            "accepted",
            "attempts",
            "approvals",
            "strategies",
            "ssim_outside",
            "ssim_inside",
            "dL_inside",
            "runtime_s",
        ],
        {"ssim_outside": "{:.4f}", "runtime_s": "{:.1f}"},
    )
    if data["unresolved"]:
        md += (
            "\n## Unresolved\n\n"
            + "\n".join(
                f"- `{r['clip']}`: {r['status']} ({r['reason']})" for r in data["unresolved"]
            )
            + "\n"
        )
    else:
        md += "\n## Unresolved\n\nNone: every hazard segment was fixed and the whole file re-verified.\n"
    return md


def figure(data: dict, name: str) -> None:
    rows = data["rows"]
    fig, ax = plt.subplots(figsize=(7, 3.2))
    ax.bar(
        range(len(rows)),
        [r["ssim_inside"] or 0 for r in rows],
        color="#1c7ed6",
        label="SSIM inside regions",
    )
    ax.bar(
        range(len(rows)),
        [r["ssim_outside"] or 0 for r in rows],
        color="#2b8a3e",
        alpha=0.5,
        label="SSIM outside regions",
    )
    ax.set_xticks(range(len(rows)))
    ax.set_xticklabels([r["clip"].replace(".mp4", "") for r in rows], rotation=90, fontsize=6)
    ax.set_ylim(0.5, 1.0)
    ax.legend(fontsize=7)
    ax.set_title(f"quality retention, {data['policy']} policy")
    fig.tight_layout()
    fig.savefig(RESULTS / f"fig_{name}_quality.png", dpi=110)
    plt.close(fig)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", default="fixed", choices=["fixed", "agent"])
    ap.add_argument("--only")
    ap.add_argument("--variants", action="store_true", help="include the crf re-encodes")
    args = ap.parse_args(argv)
    gts = load_suite(include_variants=args.variants)
    if args.only:
        gts = [g for g in gts if args.only in g["clip"]]
    RESULTS.mkdir(parents=True, exist_ok=True)
    data = run(gts, args.policy)
    name = "remediation" if args.policy == "fixed" else "remediation_agent"
    figure(data, name)
    write(name, render_md(data, f"Remediation: {args.policy} policy"), data)
    print(json.dumps({k: v for k, v in data.items() if k not in ("rows", "unresolved")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
