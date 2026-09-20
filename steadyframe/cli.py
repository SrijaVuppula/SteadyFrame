"""Command line interface.

steadyframe analyze input.mp4 [--profile wcag|broadcast] [--json out.json] [--plot out.png]
steadyframe fix input.mp4 --policy fixed|agent -o safe.mp4 --report report.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import OPENCV_VERSION, __version__


def _add_analyze(sub):
    p = sub.add_parser("analyze", help="analyze a video for photosensitive hazards")
    p.add_argument("input")
    p.add_argument("--profile", default="wcag", choices=["wcag", "broadcast"])
    p.add_argument(
        "--conservative", action="store_true", help="also warn at exactly three flashes per second"
    )
    p.add_argument("--grid", default=None, help="analysis grid WxH, default 64x48")
    p.add_argument(
        "--patterns", action="store_true", help="enable the experimental pattern detector"
    )
    p.add_argument("--json", dest="json_out", default=None)
    p.add_argument("--plot", default=None, help="write a luminance-over-time PNG")
    p.add_argument("--backend", default="auto", choices=["auto", "opencv", "ffmpeg"])
    p.add_argument("--quiet", action="store_true")
    p.set_defaults(func=cmd_analyze)


def _add_fix(sub):
    p = sub.add_parser("fix", help="remediate hazards and verify the result")
    p.add_argument("input")
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--report", default=None)
    p.add_argument(
        "--policy",
        default="fixed",
        choices=["fixed", "agent", "heuristic"],
        help="agent = Bedrock model; heuristic = deterministic stand-in following the same tool protocol",
    )
    p.add_argument("--profile", default="wcag", choices=["wcag", "broadcast"])
    p.add_argument("--trace", default=None, help="trace.jsonl path (default next to the report)")
    p.add_argument("--workdir", default=None)
    p.add_argument("--max-iterations", type=int, default=4)
    p.add_argument(
        "--approve-all",
        action="store_true",
        help="auto-approve human-approval requests (offline use)",
    )
    p.add_argument("--no-llm", action="store_true", help="alias for --policy fixed")
    p.add_argument("--plot", default=None, help="before/after luminance PNG")
    p.set_defaults(func=cmd_fix)


def cmd_analyze(args) -> int:
    from .analyzer import analyze_file
    from .schema import validate_analysis

    grid = tuple(int(x) for x in args.grid.lower().split("x")) if args.grid else None
    result = analyze_file(
        args.input,
        profile=args.profile,
        conservative=args.conservative,
        grid=grid,
        detect_patterns=args.patterns,
        backend=args.backend,
    )
    validate_analysis(result)
    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(json.dumps(result, indent=2))
    if args.plot:
        from .plot import plot_analysis

        plot_analysis(result, args.plot)
    if not args.quiet:
        v = result["video"]
        print(f"steadyframe {__version__} / OpenCV {OPENCV_VERSION}")
        print(
            f"{Path(args.input).name}: {v['width']}x{v['height']} @ {v['fps']:.3f} fps, {v['frames_analyzed']} frames, profile {args.profile}"
        )
        print(
            f"verdict: {result['verdict'].upper()}   ({result['stats']['realtime_factor']}x realtime)"
        )
        for s in result["segments"]:
            r = s["regions"][0]
            print(
                f"  {s['id']} {s['type']:8s} {s['verdict']:4s} {s['start_s']:7.2f}-{s['end_s']:7.2f}s "
                f"rate={s['peak_flash_rate_hz']:.1f}Hz area={s['max_area_fraction']:.2f} dL={s['max_delta_L']:.2f} "
                f"region=({r['x']:.2f},{r['y']:.2f},{r['w']:.2f},{r['h']:.2f}) sev={s['severity_score']:.2f}"
            )
    return 0 if result["verdict"] != "fail" else 2


def cmd_fix(args) -> int:
    from .remediate.pipeline import fix_file

    policy = "fixed" if args.no_llm else args.policy
    report = fix_file(
        args.input,
        args.output,
        policy=policy,
        profile=args.profile,
        report_path=args.report,
        trace_path=args.trace,
        workdir=args.workdir,
        max_iterations=args.max_iterations,
        approve_all=args.approve_all,
        plot_path=args.plot,
    )
    print(f"steadyframe {__version__} / OpenCV {OPENCV_VERSION}")
    print(
        f"status: {report['status']}  policy={report['policy']}  iterations={report['iterations']}  runtime={report['runtime_s']:.1f}s"
    )
    for s in report["segments"]:
        print(
            f"  {s['segment_id']} {s['type']:8s} -> {s['outcome']:18s} strategy={s.get('strategy')} attempts={len(s.get('attempts', []))}"
        )
    return 0 if report["status"] in ("passed", "no_hazards") else 3


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="steadyframe", description=__doc__)
    ap.add_argument(
        "--version",
        action="version",
        version=f"steadyframe {__version__} (OpenCV {OPENCV_VERSION})",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    _add_analyze(sub)
    _add_fix(sub)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
