"""Benchmark the analysis workload on this host.

    python -m bench.run --out bench/results [--label c8g-cool] [--reps 10] [--price-per-hour 0.153]

Identical workload on every configuration: the analyzer (`steadyframe.analyzer.FlashAnalyzer`)
on three deterministic 1280x720 clips, reported twice: decode excluded (frames preloaded,
pure OpenCV/NumPy analysis) and decode included (cv2.VideoCapture in the loop). Plus a
per-operation micro-benchmark of the OpenCV calls the analyzer spends its time in, and a
cProfile of one analysis run so the share of time inside cv2 functions is visible.

Evidence of *which* OpenCV executed: version, `cv2.__file__`, the full build information,
the loaded shared libraries (from /proc/self/maps: look for libopencv / kleidicv), CPU
features, instance type from IMDS when on EC2. Nothing here tunes one configuration
differently from another.
"""

from __future__ import annotations

import argparse
import cProfile
import io
import json
import os
import platform
import pstats
import statistics
import subprocess
import time
import urllib.request
from pathlib import Path

import cv2
import numpy as np

from steadyframe import __version__
from steadyframe.analyzer import FlashAnalyzer
from steadyframe.io.video import open_video
from steadyframe.profiles import get_profile

CLIPS = Path(__file__).resolve().parent / "clips"


def make_clips(seed: int = 7) -> list[Path]:
    """Three 720p clips: a region strobe on texture, a red strobe, a clean panning texture."""
    from synth.generate import render_clip

    CLIPS.mkdir(exist_ok=True)
    cfgs = [
        {
            "name": "bench_strobe",
            "width": 1280,
            "height": 720,
            "fps": 30,
            "duration_s": 4.0,
            "background": {"kind": "texture"},
            "events": [
                {
                    "kind": "flash",
                    "freq_hz": 6.0,
                    "low_L": 0.05,
                    "delta_L": 0.5,
                    "start_s": 0.5,
                    "end_s": 3.5,
                    "region": {"x": 0.3, "y": 0.3, "w": 0.4, "h": 0.4},
                }
            ],
        },
        {
            "name": "bench_red",
            "width": 1280,
            "height": 720,
            "fps": 30,
            "duration_s": 4.0,
            "background": {"kind": "gradient"},
            "events": [
                {
                    "kind": "flash",
                    "freq_hz": 5.0,
                    "low": "darkred",
                    "high": "red",
                    "start_s": 0.5,
                    "end_s": 3.5,
                }
            ],
        },
        {
            "name": "bench_clean",
            "width": 1280,
            "height": 720,
            "fps": 30,
            "duration_s": 4.0,
            "background": {"kind": "moving"},
        },
    ]
    out = []
    for c in cfgs:
        render_clip(c, CLIPS, seed)
        out.append(CLIPS / f"{c['name']}.mp4")
    return out


def env_info() -> dict:
    info = {
        "steadyframe": __version__,
        "opencv_version": cv2.__version__,
        "opencv_file": cv2.__file__,
        "opencv_threads": cv2.getNumThreads(),
        "cpu_features": cv2.getCPUFeaturesLine(),
        "python": platform.python_version(),
        "machine": platform.machine(),
        "system": platform.platform(),
        "cpu_count": os.cpu_count(),
        "numpy": np.__version__,
    }
    try:
        cpuinfo = Path("/proc/cpuinfo").read_text()
        for key in ("model name", "CPU implementer", "CPU part", "Hardware"):
            for line in cpuinfo.splitlines():
                if line.lower().startswith(key.lower()):
                    info[f"cpu_{key.replace(' ', '_').lower()}"] = line.split(":", 1)[1].strip()
                    break
    except Exception:
        pass
    try:
        maps = Path("/proc/self/maps").read_text()
        libs = sorted(
            {
                line.split()[-1]
                for line in maps.splitlines()
                if ("opencv" in line.lower() or "kleidi" in line.lower() or "cv2" in line.lower())
                and "/" in line
            }
        )
        info["loaded_libraries"] = libs
        info["kleidicv_loaded"] = any("kleidi" in lib.lower() for lib in libs)
    except Exception:
        info["loaded_libraries"] = []
    build = cv2.getBuildInformation()
    info["build_information"] = build
    info["build_has_kleidicv"] = "kleidi" in build.lower()
    try:
        req = urllib.request.Request(
            "http://169.254.169.254/latest/api/token",
            method="PUT",
            headers={"X-aws-ec2-metadata-token-ttl-seconds": "30"},
        )
        token = urllib.request.urlopen(req, timeout=1).read().decode()
        r = urllib.request.Request(
            "http://169.254.169.254/latest/meta-data/instance-type",
            headers={"X-aws-ec2-metadata-token": token},
        )
        info["ec2_instance_type"] = urllib.request.urlopen(r, timeout=1).read().decode()
    except Exception:
        info["ec2_instance_type"] = None
    try:
        info["ami_id"] = (
            subprocess.run(["cat", "/etc/image-id"], capture_output=True, text=True).stdout.strip()
            or None
        )
    except Exception:
        info["ami_id"] = None
    return info


def load_frames(path: Path) -> tuple[list[tuple[float, np.ndarray]], dict]:
    r = open_video(path)
    frames = [(t, f) for _i, t, f in r]
    return frames, r.meta.to_dict()


def analyze_frames(frames, meta, profile) -> float:
    an = FlashAnalyzer(profile, meta["width"], meta["height"], meta["fps"], keep_grid_history=False)
    t0 = time.perf_counter()
    for t, f in frames:
        an.push(f, t)
    an.finish()
    return time.perf_counter() - t0


def analyze_file_timed(path: Path, profile) -> float:
    r = open_video(path)
    m = r.meta
    an = FlashAnalyzer(profile, m.width, m.height, m.fps, keep_grid_history=False)
    t0 = time.perf_counter()
    for _i, t, f in r:
        an.push(f, t)
    an.finish()
    return time.perf_counter() - t0


def stats(xs: list[float]) -> dict:
    xs = sorted(xs)
    return {
        "median": statistics.median(xs),
        "min": xs[0],
        "max": xs[-1],
        "p25": xs[len(xs) // 4],
        "p75": xs[(3 * len(xs)) // 4],
        "n": len(xs),
    }


def micro(frame: np.ndarray, reps: int) -> dict:
    """Per-op timings (ms) for the calls the analyzer is made of, on one 720p frame."""
    from steadyframe.luminance import SRGB_TO_LINEAR_LUT

    lum = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
    mask = (np.random.default_rng(0).random((48, 64)) > 0.7).astype(np.float32)
    ops = {
        "cv2.LUT (sRGB->linear, 720p x3ch)": lambda: cv2.LUT(frame, SRGB_TO_LINEAR_LUT),
        "cv2.transform (weighted sum -> luminance)": lambda: cv2.transform(
            cv2.LUT(frame, SRGB_TO_LINEAR_LUT), np.array([[0.0722, 0.7152, 0.2126]], np.float32)
        ),
        "cv2.resize INTER_AREA 1280x720 -> 64x48": lambda: cv2.resize(
            lum, (64, 48), interpolation=cv2.INTER_AREA
        ),
        "cv2.resize INTER_AREA 1280x720 -> 256x192": lambda: cv2.resize(
            lum, (256, 192), interpolation=cv2.INTER_AREA
        ),
        "cv2.boxFilter 21x16 on 64x48 mask": lambda: cv2.boxFilter(
            mask, -1, (21, 16), normalize=True, borderType=cv2.BORDER_CONSTANT
        ),
        "cv2.GaussianBlur 11x11 s1.5 on 720p gray": lambda: cv2.GaussianBlur(lum, (11, 11), 1.5),
        "cv2.GaussianBlur sigma 25 on 720p mask": lambda: cv2.GaussianBlur(lum, (0, 0), 25),
        "cv2.connectedComponentsWithStats 64x48": lambda: cv2.connectedComponentsWithStats(
            (mask > 0).astype(np.uint8), connectivity=8
        ),
        "cv2.accumulateWeighted 720p float": lambda: cv2.accumulateWeighted(
            frame.astype(np.float32), acc, 0.1
        ),
        "cv2.dft 256x192": lambda: cv2.dft(
            cv2.resize(lum, (256, 192), interpolation=cv2.INTER_AREA), flags=cv2.DFT_COMPLEX_OUTPUT
        ),
    }
    acc = frame.astype(np.float32)
    out = {}
    for name, fn in ops.items():
        fn()
        ts = []
        for _ in range(reps):
            t0 = time.perf_counter()
            fn()
            ts.append((time.perf_counter() - t0) * 1000)
        out[name] = stats(ts)
    return out


def profile_run(frames, meta, profile) -> dict:
    pr = cProfile.Profile()
    pr.enable()
    analyze_frames(frames, meta, profile)
    pr.disable()
    s = io.StringIO()
    ps = pstats.Stats(pr, stream=s).sort_stats("tottime")
    ps.print_stats(25)
    total = ps.total_tt
    cv_time = 0.0
    for (file, _line, func), (_cc, _nc, tt, _ct, _callers) in ps.stats.items():
        # cv2's C functions show up as bare "<resize>" entries (no module prefix), unlike
        # "{built-in method builtins.max}" or "{method 'reduce' of ...}"
        if (
            file == "~"
            and func.startswith("{")
            and "built-in method" not in func
            and "method '" not in func
        ):
            cv_time += tt
    return {
        "total_s": total,
        "time_in_cv2_builtins_s": cv_time,
        "fraction_in_cv2": cv_time / total if total else None,
        "top": s.getvalue(),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="bench/results")
    ap.add_argument(
        "--label", default=None, help="e.g. c8g.xlarge-cool, c8g.xlarge-stock, c7i.xlarge-stock"
    )
    ap.add_argument("--reps", type=int, default=10)
    ap.add_argument(
        "--price-per-hour",
        type=float,
        default=None,
        help="on-demand USD/h of this instance (+ COOL software price if any)",
    )
    ap.add_argument("--threads", type=int, default=None, help="cv2.setNumThreads")
    args = ap.parse_args(argv)
    if args.threads is not None:
        cv2.setNumThreads(args.threads)
    info = env_info()
    label = (
        args.label
        or f"{info.get('ec2_instance_type') or platform.node()}-{'cool' if info['build_has_kleidicv'] else 'stock'}"
    )
    print(
        f"steadyframe bench: OpenCV {cv2.__version__} at {cv2.__file__} on {info['machine']} ({info.get('ec2_instance_type') or 'not EC2'}); kleidicv in build: {info['build_has_kleidicv']}"
    )
    clips = make_clips()
    profile = get_profile("wcag")
    results = {
        "label": label,
        "env": info,
        "reps": args.reps,
        "clips": {},
        "price_per_hour_usd": args.price_per_hour,
    }
    all_rtf_excl, all_rtf_incl = [], []
    for clip in clips:
        frames, meta = load_frames(clip)
        n = len(frames)
        dur = n / meta["fps"]
        analyze_frames(frames, meta, profile)  # warm-up, discarded
        excl = [analyze_frames(frames, meta, profile) for _ in range(args.reps)]
        analyze_file_timed(clip, profile)
        incl = [analyze_file_timed(clip, profile) for _ in range(args.reps)]
        dec = [b - a for a, b in zip(excl, incl, strict=True)]
        rec = {
            "frames": n,
            "duration_s": dur,
            "resolution": f"{meta['width']}x{meta['height']}",
            "decode_excluded_s": stats(excl),
            "decode_included_s": stats(incl),
            "decode_only_est_s": stats(dec),
            "fps_excluded": n / statistics.median(excl),
            "fps_included": n / statistics.median(incl),
            "realtime_factor_excluded": dur / statistics.median(excl),
            "realtime_factor_included": dur / statistics.median(incl),
        }
        all_rtf_excl.append(rec["realtime_factor_excluded"])
        all_rtf_incl.append(rec["realtime_factor_included"])
        results["clips"][clip.name] = rec
        print(
            f"  {clip.name}: {rec['fps_excluded']:.1f} fps analysis-only, {rec['fps_included']:.1f} fps with decode ({rec['realtime_factor_included']:.1f}x realtime)"
        )
        if clip.name == "bench_strobe.mp4":
            results["micro_ms"] = micro(frames[0][1], max(20, args.reps * 5))
            results["profile"] = profile_run(frames, meta, profile)
    results["summary"] = {
        "median_realtime_factor_excluded": statistics.median(all_rtf_excl),
        "median_realtime_factor_included": statistics.median(all_rtf_incl),
        "usd_per_video_hour_excluded": (args.price_per_hour / statistics.median(all_rtf_excl))
        if args.price_per_hour
        else None,
        "usd_per_video_hour_included": (args.price_per_hour / statistics.median(all_rtf_incl))
        if args.price_per_hour
        else None,
    }
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{label}.json").write_text(json.dumps(results, indent=2))
    (out / f"{label}.buildinfo.txt").write_text(info["build_information"])
    print(
        f"wrote {out / (label + '.json')}; fraction of analysis time inside cv2 built-ins: {results['profile']['fraction_in_cv2']:.2f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
