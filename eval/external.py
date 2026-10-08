"""Detection and remediation on openly licensed clips that this project did not generate.

    make real                -> downloads the clips listed in data/SOURCES.md to data/real/
    python -m eval.external  -> eval/results/external.{md,json}, fig_external_apple.png

Labels live in data/external.yaml and come from three places, none of them this analyzer:

- EA IRIS test videos, scored against IRIS's own expected per-frame logs. IRIS applies the
  area rule to the whole screen, so the `broadcast` profile is the like-for-like comparison;
  `wcag` is reported too. IRIS's extended-failure rule (sustained flashing over five seconds,
  from the broadcast guidance) is not implemented here and is listed separately.
- Apple's VideoFlashingReduction test clip, labelled by synth/reference.py on the frame-mean
  relative luminance after checking that the flashing is spatially uniform.
- Intel IoT DevKit camera footage as calm controls (every second labelled pass).

Every file is checked against the sha256 recorded with its label before it is scored.
Remediation runs the fixed policy and the heuristic agent on every clip with a failing label
(approvals auto-granted and counted, as in eval/remediation.py).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import statistics
import tempfile
from pathlib import Path

import matplotlib
import yaml

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from steadyframe.io.video import open_video  # noqa: E402
from steadyframe.luminance import relative_luminance  # noqa: E402
from steadyframe.profiles import get_profile  # noqa: E402
from steadyframe.remediate.pipeline import fix_file  # noqa: E402
from synth import reference  # noqa: E402

from .common import (  # noqa: E402
    RESULTS,
    ROOT,
    cached_analysis,
    header,
    interval_iou,
    md_table,
    prf,
    write,
)

REAL = ROOT / "data" / "real"
LABELS = ROOT / "data" / "external.yaml"
PROFILES = ("wcag", "broadcast")
IRIS_FAIL, IRIS_EXTENDED = 3, 2


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def find(cid: str) -> Path | None:
    hits = [p for p in REAL.glob(f"{cid}.*") if p.suffix not in (".sha256", ".csv")]
    return hits[0] if hits else None


# ---------------------------------------------------------------------------- labels
def iris_codes(path: Path) -> list[int]:
    """Per-frame IRIS result, worst of luminance and red (0 pass .. 3 flash failure)."""
    rows = [r for r in csv.reader(path.read_text().splitlines()) if r]
    head = [h.strip() for h in rows[0]]
    if "FlashLuminanceFailedFrame" in head:
        li, ri = head.index("FlashLuminanceFailedFrame"), head.index("FlashRedFailedFrame")
        return [max(int(r[li]), int(r[ri])) for r in rows[1:]]
    # older log layout: one FlashFailedFrames column, 2 = flash failure
    fi = head.index("FlashFailedFrames")
    return [IRIS_FAIL if int(r[fi]) == 2 else int(r[fi]) for r in rows[1:]]


def frame_mean_reference(path: Path, profile_name: str) -> dict:
    """Reference rules on the frame-mean luminance; also the worst quadrant deviation."""
    prof = get_profile(profile_name)
    vals, times, dev = [], [], 0.0
    for _i, t, frame in open_video(str(path)):
        lum = relative_luminance(frame)
        h, w = lum.shape
        m = float(lum.mean())
        quads = (lum[: h // 2, : w // 2], lum[: h // 2, w // 2 :], lum[h // 2 :, : w // 2])
        quads += (lum[h // 2 :, w // 2 :],)
        dev = max(dev, max(abs(float(q.mean()) - m) for q in quads))
        vals.append(m)
        times.append(t)
    flags = [v < prof.dark_state_max for v in vals]
    r = reference.evaluate(vals, flags, times, 1.0, prof)
    return {
        "t": times,
        "mean_L": vals,
        "fail": r.fail_frames,
        "per_second": reference.per_second(times, r.fail_frames, r.warn_frames),
        "intervals": intervals(times, r.fail_frames),
        "max_quadrant_deviation": dev,
    }


def intervals(times: list[float], flags: list[bool]) -> list[tuple[float, float]]:
    out, start = [], None
    dt = (times[1] - times[0]) if len(times) > 1 else 0.0
    for t, f in zip(times, flags, strict=True):
        if f and start is None:
            start = t
        if not f and start is not None:
            out.append((start, t))
            start = None
    if start is not None:
        out.append((start, times[-1] + dt))
    return out


def label_for(c: dict, fps: float, n_frames: int) -> dict:
    """Per-frame fail flags, per-second labels and the clip label for one entry."""
    if c["label"] == "iris_log":
        ref = REAL / f"{c['reference']}.csv"
        if sha256(ref) != c["reference_sha256"]:
            raise SystemExit(f"{ref.name}: checksum differs from data/external.yaml")
        codes = iris_codes(ref)
        times = [i / fps for i in range(len(codes))]
        fail = [x == IRIS_FAIL for x in codes]
        n_sec = int(times[-1]) + 1 if times else 0
        per_second = ["pass"] * n_sec
        for t, f in zip(times, fail, strict=True):
            if f:
                per_second[int(t)] = "fail"
        return {
            "times": times,
            "fail": fail,
            "per_second": per_second,
            "verdict": "fail" if any(fail) else "pass",
            "extended": any(x == IRIS_EXTENDED for x in codes),
            "warnings": sum(1 for x in codes if x == 1),
            "source": "IRIS expected log",
        }
    if c["label"] == "frame_mean_ref":
        return {"deferred": True}  # computed per profile in evaluate_clip
    if c["label"] == "pass":
        n_sec = int((n_frames - 1) / fps) + 1 if n_frames else 0
        return {
            "times": [i / fps for i in range(n_frames)],
            "fail": [False] * n_frames,
            "per_second": ["pass"] * n_sec,
            "verdict": "pass",
            "extended": False,
            "source": "calm footage, inspected",
        }
    raise SystemExit(f"unknown label kind {c['label']!r}")


# ---------------------------------------------------------------------------- scoring
def evaluate_clip(c: dict, path: Path) -> dict:
    out = {"id": c["id"], "set": c["set"], "label_kind": c["label"], "profiles": {}}
    for prof in PROFILES:
        res = cached_analysis(path, profile=prof)
        fps = res["video"]["fps"]
        n = res["video"]["frames_analyzed"]
        lab = label_for(c, fps, n)
        if lab.get("deferred"):
            ref = frame_mean_reference(path, prof)
            if ref["max_quadrant_deviation"] > c["uniform_tol"]:
                raise SystemExit(f"{c['id']}: flashing is not uniform; frame-mean label refused")
            lab = {
                "times": ref["t"],
                "fail": ref["fail"],
                "per_second": ref["per_second"],
                "verdict": "fail" if any(ref["fail"]) else "pass",
                "extended": False,
                "intervals": ref["intervals"],
                "max_quadrant_deviation": ref["max_quadrant_deviation"],
                "mean_L": ref["mean_L"],
                "source": "reference rules on frame-mean luminance",
            }
            out["uniformity"] = ref["max_quadrant_deviation"]
        got_ps = [s["verdict"] for s in res["per_second"]]
        k = min(len(got_ps), len(lab["per_second"]))
        tp = sum(1 for i in range(k) if lab["per_second"][i] == "fail" and got_ps[i] == "fail")
        fp = sum(1 for i in range(k) if lab["per_second"][i] != "fail" and got_ps[i] == "fail")
        fn = sum(1 for i in range(k) if lab["per_second"][i] == "fail" and got_ps[i] != "fail")
        fails = [s for s in res["segments"] if s["verdict"] == "fail"]
        # label fail frames that lie inside one of our segments, and segments that contain one
        lab_fail_t = [t for t, f in zip(lab["times"], lab["fail"], strict=True) if f]
        covered = sum(1 for t in lab_fail_t if any(s["start_s"] <= t < s["end_s"] for s in fails))
        seg_hits = sum(1 for s in fails if any(s["start_s"] <= t < s["end_s"] for t in lab_fail_t))
        ious = []
        for iv in lab.get("intervals", []):
            spans = [(s.get("detected_s", s["start_s"]), s["end_s"]) for s in fails]
            ious.append(max((interval_iou(iv, sp) for sp in spans), default=0.0))
        ps = res["per_second"]
        out["profiles"][prof] = {
            "label": lab["verdict"],
            "label_extended": lab["extended"],
            "got": res["verdict"],
            "agree": lab["verdict"] == res["verdict"],
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "seconds": k,
            "label_fail_frames": len(lab_fail_t),
            "label_fail_frames_covered": covered,
            "segments": len(fails),
            "segments_with_label_fail": seg_hits,
            "failing_span_iou": statistics.mean(ious) if ious else None,
            "max_cell_rate_hz": max((s["max_flash_rate_hz"] for s in ps), default=0.0),
            "max_window_area_over_rate": max((s["max_area_fraction"] for s in ps), default=0.0),
            "realtime_factor": res["stats"]["realtime_factor"],
            "frames": res["video"]["frames_analyzed"],
            "resolution": f"{res['video']['width']}x{res['video']['height']}",
            "fps": round(fps, 2),
            "label_source": lab["source"],
        }
        if prof == "wcag" and "mean_L" in lab:
            out["_plot"] = {"t": lab["times"], "L": lab["mean_L"], "ref": lab["intervals"]}
            out["_plot"]["ours"] = [(s["start_s"], s["end_s"]) for s in fails]
    return out


def remediate(path: Path, policy: str, workroot: Path) -> dict:
    wd = workroot / policy / path.stem
    rep = fix_file(
        path,
        wd / "safe.mp4",
        policy=policy,
        workdir=wd,
        report_path=wd / "report.json",
        approve_all=True,
    )
    n_att = sum(len(s["attempts"]) for s in rep["segments"])
    q = rep.get("quality") or {}
    return {
        "status": rep["status"],
        "after": (rep.get("after") or {}).get("verdict"),
        "segments": len(rep["segments"]),
        "attempts": n_att,
        "iter_per_seg": n_att / max(1, len(rep["segments"])),
        "strategies": ",".join(s["strategy"] or "-" for s in rep["segments"]),
        "approvals": sum(1 for s in rep["segments"] if s.get("approval")),
        "ssim_inside": q.get("ssim_inside"),
        "runtime_s": rep["runtime_s"],
    }


def figure(clip: dict, dst: Path) -> None:
    p = clip["_plot"]
    fig, ax = plt.subplots(figsize=(10, 3.6))
    ax.plot(p["t"], p["L"], lw=0.7, color="#3a5a8c", label="frame-mean relative luminance")
    for i, (a, b) in enumerate(p["ref"]):
        ax.axvspan(
            a,
            b,
            ymin=0.5,
            ymax=1.0,
            color="#d98c1f",
            alpha=0.35,
            lw=0,
            label="reference: failing frames" if i == 0 else None,
        )
    for i, (a, b) in enumerate(p["ours"]):
        ax.axvspan(
            a,
            b,
            ymin=0.0,
            ymax=0.5,
            color="#b8312f",
            alpha=0.25,
            lw=0,
            label="SteadyFrame: segments" if i == 0 else None,
        )
    ax.set_xlabel("time (s)")
    ax.set_ylabel("L")
    ax.set_title(f"{clip['id']}: reference labels (top band) vs analyzer segments (bottom band)")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.22), ncol=3, fontsize=8, frameon=False)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(dst, dpi=110)
    plt.close(fig)


# ---------------------------------------------------------------------------- main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-remediation", action="store_true")
    a = ap.parse_args(argv)
    entries = yaml.safe_load(LABELS.read_text())["clips"]
    clips, missing = [], []
    for c in entries:
        path = find(c["id"])
        if path is None:
            missing.append(c["id"])
            continue
        if sha256(path) != c["sha256"]:
            raise SystemExit(f"{path.name}: checksum differs from data/external.yaml")
        print(f"{c['id']}: analysing")
        r = evaluate_clip(c, path)
        r["_path"] = path
        clips.append(r)
    if not clips:
        print("no external clips in data/real; run `make real` first (skipped)")
        return 0

    summary: dict = {"n_clips": len(clips), "missing": missing, "by_profile": {}}
    for prof in PROFILES:
        rows = [c["profiles"][prof] for c in clips]
        tp, fp, fn = (sum(r[k] for r in rows) for k in ("tp", "fp", "fn"))
        iris = [c["profiles"][prof] for c in clips if c["set"] == "iris"]
        controls = [c["profiles"][prof] for c in clips if c["set"] == "intel"]
        summary["by_profile"][prof] = {
            "clip_agreement": sum(r["agree"] for r in rows),
            "per_second": prf(tp, fp, fn),
            "iris_agreement": sum(r["agree"] for r in iris),
            "iris_clips": len(iris),
            "iris_fail_frames": sum(r["label_fail_frames"] for r in iris),
            "iris_fail_frames_covered": sum(r["label_fail_frames_covered"] for r in iris),
            "control_fp_seconds": sum(r["fp"] for r in controls),
            "control_seconds": sum(r["seconds"] for r in controls),
            "control_max_cell_rate_hz": max((r["max_cell_rate_hz"] for r in controls), default=0),
            "control_max_window_area": max(
                (r["max_window_area_over_rate"] for r in controls), default=0
            ),
        }
    summary["iris_extended_only"] = [
        c["id"]
        for c in clips
        if c["profiles"]["broadcast"]["label_extended"]
        and c["profiles"]["broadcast"]["label"] == "pass"
    ]
    summary["n_iris_extended_only"] = len(summary["iris_extended_only"])
    summary["n_iris_hazard_clips"] = sum(
        1 for c in clips if c["set"] == "iris" and c["profiles"]["broadcast"]["label"] == "fail"
    )
    summary["n_controls"] = sum(1 for c in clips if c["set"] == "intel")
    apple = next((c for c in clips if c["set"] == "apple"), None)
    if apple:
        w = apple["profiles"]["wcag"]
        summary["apple"] = {
            "max_quadrant_deviation": apple["uniformity"],
            "failing_span_iou": w["failing_span_iou"],
            "segments": w["segments"],
            "agree": w["agree"],
        }
        figure(apple, RESULTS / "fig_external_apple.png")
    summary["n_hazard_clips"] = sum(1 for c in clips if c["profiles"]["wcag"]["label"] == "fail")
    summary["control_minutes"] = round(
        sum(
            c["profiles"]["wcag"]["frames"] / c["profiles"]["wcag"]["fps"]
            for c in clips
            if c["set"] == "intel"
        )
        / 60,
        1,
    )
    summary["control_hours"] = round(
        sum(
            c["profiles"]["wcag"]["frames"] / c["profiles"]["wcag"]["fps"]
            for c in clips
            if c["set"] == "intel"
        )
        / 3600,
        3,
    )

    remediation: dict = {}
    if not a.no_remediation:
        work = Path(tempfile.mkdtemp(prefix="sf-external-"))
        for policy in ("fixed", "heuristic"):
            rows = []
            for c in clips:
                if c["profiles"]["wcag"]["label"] != "fail":
                    continue
                print(f"{c['id']}: remediating ({policy})")
                rows.append({"clip": c["id"], **remediate(c["_path"], policy, work)})
            remediation[policy] = {
                "n": len(rows),
                "passed": sum(1 for r in rows if r["status"] == "passed"),
                "mean_iterations_per_segment": statistics.mean(r["iter_per_seg"] for r in rows)
                if rows
                else None,
                "approvals": sum(r["approvals"] for r in rows),
                "rows": rows,
            }
    summary["remediation"] = remediation

    md = header("External: openly licensed clips")
    md += (
        "Clips from EA IRIS's test set (BSD-3-Clause), Apple's VideoFlashingReduction sample "
        "(MIT) and Intel's IoT DevKit sample videos (CC BY 4.0). Sources, pinned URLs and "
        "licences: `data/SOURCES.md`; labels and checksums: `data/external.yaml`. No label "
        "comes from this analyzer.\n\n"
    )
    if missing:
        md += f"Not downloaded (skipped): {', '.join(missing)}\n\n"
    md += "## Summary\n\n"
    srows = []
    for prof in PROFILES:
        s = summary["by_profile"][prof]
        srows.append(
            {
                "profile": prof,
                "clip verdicts agree": f"{s['clip_agreement']}/{len(clips)}",
                "IRIS clips agree": f"{s['iris_agreement']}/{s['iris_clips']}",
                "IRIS fail frames inside a segment": f"{s['iris_fail_frames_covered']}/{s['iris_fail_frames']}",
                "per-second P / R / F1": f"{s['per_second']['precision']:.3f} / {s['per_second']['recall']:.3f} / {s['per_second']['f1']:.3f}",
                "control seconds flagged": f"{s['control_fp_seconds']}/{s['control_seconds']}",
            }
        )
    md += md_table(srows, list(srows[0].keys()))
    if summary["iris_extended_only"]:
        md += (
            "\nIRIS reports an *extended failure* (sustained flashing at four or more "
            "transitions a second for four of five seconds, from the broadcast guidance) on "
            f"{', '.join('`' + x + '`' for x in summary['iris_extended_only'])}, with no flash "
            "failure. SteadyFrame does not implement that rule: those clips pass here and pass "
            "under IRIS's flash rule too. Counted as agreement on the flash rule, listed as a gap.\n"
        )
    if apple:
        md += (
            f"\nApple clip: flashing is spatially uniform (worst quadrant deviation from the frame "
            f"mean {apple['uniformity']:.4f}), so the reference rules on the frame mean are a valid "
            f"label. Mean IoU of the reference's failing intervals with the analyzer's failing "
            f"spans (`detected_s`..`end_s`): {summary['apple']['failing_span_iou']:.3f}.\n\n"
            "![](fig_external_apple.png)\n"
        )
    md += (
        f"\nControls: {summary['control_hours'] * 60:.1f} minutes of camera footage. Moving "
        "objects make single cells flash briefly (highest cell-level rate "
        f"{summary['by_profile']['wcag']['control_max_cell_rate_hz']:.1f} Hz), but the cells over "
        "the rate never cover more than "
        f"{summary['by_profile']['wcag']['control_max_window_area']:.1%} of a 10-degree window "
        "(the rule is 25%).\n"
    )
    for prof in PROFILES:
        md += f"\n## Per clip, profile `{prof}`\n\n"
        rows = [{"clip": c["id"], "set": c["set"], **c["profiles"][prof]} for c in clips]
        md += md_table(
            rows,
            [
                "clip",
                "set",
                "label",
                "got",
                "agree",
                "tp",
                "fp",
                "fn",
                "label_fail_frames",
                "label_fail_frames_covered",
                "max_cell_rate_hz",
                "max_window_area_over_rate",
                "resolution",
                "fps",
                "realtime_factor",
            ],
            {
                "max_cell_rate_hz": "{:.1f}",
                "max_window_area_over_rate": "{:.3f}",
                "realtime_factor": "{:.1f}",
                "fps": "{:.2f}",
            },
        )
    if remediation:
        md += "\n## Remediation on the clips with a failing label (`wcag`)\n\n"
        for policy, r in remediation.items():
            md += (
                f"**{policy}**: {r['passed']}/{r['n']} pass whole-file re-verification, "
                f"{r['mean_iterations_per_segment']:.2f} attempts per segment, "
                f"{r['approvals']} approval request(s) (auto-granted offline).\n\n"
            )
            md += md_table(
                r["rows"],
                [
                    "clip",
                    "status",
                    "after",
                    "segments",
                    "attempts",
                    "strategies",
                    "approvals",
                    "ssim_inside",
                    "runtime_s",
                ],
                {"runtime_s": "{:.1f}"},
            )
            md += "\n"
    for c in clips:
        c.pop("_path", None)
        c.pop("_plot", None)
    write("external", md, {**summary, "clips": clips})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
