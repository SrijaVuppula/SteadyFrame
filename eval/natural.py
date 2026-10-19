"""Natural footage: SteadyFrame against EA IRIS on real light sources that flash.

    make natural              -> data/natural/ (download, transcode, IRIS labels)
    python -m eval.natural    -> eval/results/natural.{md,json}, fig_natural.png

Seventeen openly licensed Wikimedia Commons clips of things that really flash: police cars, fire
engines and ambulances, club lights, a phone's LED effects, a neon sign, crossing beacons,
lightning and fireworks (`data/natural.yaml`). The label for every frame is EA IRIS 1.1.0's
result on the same H.264 transcode SteadyFrame reads; none comes from this analyzer. IRIS
applies the area rule to the whole screen, so `broadcast` is the like-for-like profile; `wcag`
(25% of any 10-degree window, stricter for small bright regions) is reported too.

Every clip that fails under either tool is then repaired by the fixed policy and the heuristic
agent (approvals auto-granted and counted, as in eval/remediation.py). SteadyFrame re-verifies
the whole repaired file, and IRIS checks the repaired file as well: a second, independent
re-verification of the repair.
"""

from __future__ import annotations

import argparse
import csv
import shutil
import statistics
import tempfile
from collections import deque
from pathlib import Path

import matplotlib
import yaml

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from steadyframe.area import AreaChecker  # noqa: E402
from steadyframe.flash import TransitionTracker  # noqa: E402
from steadyframe.io.video import open_video  # noqa: E402
from steadyframe.luminance import grid_maps  # noqa: E402
from steadyframe.profiles import get_profile  # noqa: E402
from steadyframe.remediate.pipeline import fix_file  # noqa: E402
from synth.fetch_natural import MANIFEST, OUT, digest, frame_codes, run_iris  # noqa: E402

from .common import RESULTS, cached_analysis, header, md_table, prf, write  # noqa: E402

PROFILES = ("broadcast", "wcag")
FAIL, EXTENDED = 3, 2


def iris_label(csv_path: Path) -> dict:
    rows = [r for r in csv.reader(csv_path.read_text().splitlines()) if r]
    head = [h.strip() for h in rows[0]]
    ti = head.index("TimeStamp")

    def secs(ts: str) -> float:
        h, m, s = ts.split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)

    times = [secs(r[ti]) for r in rows[1:]]
    codes = frame_codes(csv_path)
    fail = [c == FAIL for c in codes]
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
        "extended": any(c == EXTENDED for c in codes),
        "warning_frames": sum(c == 1 for c in codes),
    }


def score(res: dict, lab: dict) -> dict:
    got = [s["verdict"] for s in res["per_second"]]
    k = min(len(got), len(lab["per_second"]))
    tp = sum(1 for i in range(k) if lab["per_second"][i] == "fail" and got[i] == "fail")
    fp = sum(1 for i in range(k) if lab["per_second"][i] != "fail" and got[i] == "fail")
    fn = sum(1 for i in range(k) if lab["per_second"][i] == "fail" and got[i] != "fail")
    segs = [s for s in res["segments"] if s["verdict"] == "fail"]
    lab_t = [t for t, f in zip(lab["times"], lab["fail"], strict=True) if f]
    covered = sum(1 for t in lab_t if any(s["start_s"] - 0.05 <= t < s["end_s"] for s in segs))
    return {
        "label": lab["verdict"],
        "got": res["verdict"],
        "agree": (lab["verdict"] == "fail") == (res["verdict"] == "fail"),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "seconds": k,
        "label_fail_frames": len(lab_t),
        "covered": covered,
        "segments": [
            {k: s[k] for k in ("id", "type", "start_s", "end_s", "peak_flash_rate_hz")}
            | {"area": s.get("max_area_fraction")}
            for s in segs
        ],
        "max_cell_rate_hz": max((s["max_flash_rate_hz"] for s in res["per_second"]), default=0),
        "max_area_over_rate": max((s["max_area_fraction"] for s in res["per_second"]), default=0),
        "realtime_factor": res["stats"]["realtime_factor"],
    }


def concurrency(path: Path, profile_name: str = "broadcast", tol_frames: int = 1) -> dict:
    """Why SteadyFrame and IRIS can disagree on real light, measured per frame.

    IRIS counts a transition when the *average* luminance of the area that changed moves by 0.10.
    SteadyFrame counts transitions in each grid cell, then asks whether the cells over the rate
    cover 25% of the screen (broadcast). When some parts brighten while others darken, their
    changes cancel in an average and add up across cells. Two series, with the analyzer's own
    luminance grid and transition definition:

    - `area`: the share of the screen whose cells complete a transition within `tol_frames` of
      the frame (how much changes at once);
    - `net`: |mean frame-to-frame change| / mean |cell change| (1 = everything moves the same way,
      0 = the changes cancel out). Diagnostic only."""
    prof = get_profile(profile_name)
    tracker = TransitionTracker((prof.grid_h, prof.grid_w), prof.luminance_delta, prof.reversal_eps)
    area = AreaChecker(prof, prof.grid_w, prof.grid_h)
    recent: deque = deque(maxlen=2 * tol_frames + 1)
    t_out, a_out, n_out, prev = [], [], [], None
    for _i, t, frame in open_video(path):
        lum, _r, _v = grid_maps(frame, prof.grid_w, prof.grid_h)
        recent.append(tracker.push(lum, lum < prof.dark_state_max, t).mask)
        t_out.append(t)
        a_out.append(area.max_fraction(np.logical_or.reduce(list(recent))))
        if prev is None:
            n_out.append(None)
        else:
            d = lum.astype(np.float32) - prev
            mag = float(np.abs(d).mean())
            n_out.append(abs(float(d.mean())) / mag if mag > 0.004 else None)
        prev = lum.astype(np.float32)
    return {"t": t_out, "area": a_out, "net": n_out}


def concurrency_summary(c: dict, conc: dict) -> dict:
    """The two measures inside SteadyFrame's broadcast segments and around IRIS's fail frames."""
    segs = c["profiles"]["broadcast"]["segments"]
    iris_t = [t for t, f in zip(c["iris"]["times"], c["iris"]["fail"], strict=True) if f]

    def pick(cond):
        rows = [
            (a, n) for t, a, n in zip(conc["t"], conc["area"], conc["net"], strict=True) if cond(t)
        ]
        nets = sorted(n for _a, n in rows if n is not None)
        return {
            "frames": len(rows),
            "max_concurrent_area": max((a for a, _n in rows), default=None),
            "median_net": nets[len(nets) // 2] if nets else None,
        }

    in_seg = pick(lambda t: any(s["start_s"] <= t < s["end_s"] for s in segs))
    near_iris = pick(lambda t: any(abs(t - u) < 0.5 for u in iris_t))
    return {"in_segments": in_seg, "near_iris_fail": near_iris}


def repair(path: Path, policy: str, work: Path, iris_recheck: bool) -> dict:
    wd = work / policy / path.stem
    out = wd / f"{path.stem}.safe.mp4"
    rep = fix_file(path, out, policy=policy, workdir=wd, report_path=wd / "report.json",
                   approve_all=True)  # fmt: skip
    n_att = sum(len(s["attempts"]) for s in rep["segments"])
    q = rep.get("quality") or {}
    row = {
        "status": rep["status"],
        "after": (rep.get("after") or {}).get("verdict"),
        "broadcast_after": None,
        "segments": len(rep["segments"]),
        "iter_per_seg": n_att / max(1, len(rep["segments"])),
        "strategies": ",".join(s["strategy"] or "-" for s in rep["segments"]),
        "approvals": sum(1 for s in rep["segments"] if s.get("approval")),
        "ssim_inside": q.get("ssim_inside"),
        "ssim_overall": q.get("ssim_overall"),
        "runtime_s": rep["runtime_s"],
        "iris_after": None,
    }
    if out.exists():
        row["broadcast_after"] = cached_analysis(out, profile="broadcast")["verdict"]
        if iris_recheck:
            csv_path, _ = run_iris(out)
            row["iris_after"] = iris_label(csv_path)["verdict"]
            row["iris_after_fail_frames"] = sum(iris_label(csv_path)["fail"])
    return row


def figure(clips: list[dict], dst: Path) -> None:
    hz = [
        c for c in clips if c["iris"]["verdict"] == "fail" or c["profiles"]["wcag"]["got"] == "fail"
    ]
    rows = hz or clips
    fig, ax = plt.subplots(figsize=(10, 0.55 * len(rows) + 1.2))
    for i, c in enumerate(rows):
        y = len(rows) - 1 - i
        t = c["iris"]["times"]
        dt = (t[1] - t[0]) if len(t) > 1 else 0.04
        for tt, f in zip(t, c["iris"]["fail"], strict=True):
            if f:
                ax.add_patch(plt.Rectangle((tt, y + 0.08), dt, 0.38, color="#d98c1f", lw=0))
        for prof, y0, col in (("broadcast", y - 0.04, "#b8312f"), ("wcag", y - 0.42, "#7a3fa0")):
            for s in c["profiles"][prof]["segments"]:
                w = s["end_s"] - s["start_s"]
                ax.add_patch(
                    plt.Rectangle((s["start_s"], y0), w, 0.34, color=col, alpha=0.55, lw=0)
                )
        ax.plot([0, c["duration_s"]], [y - 0.46, y - 0.46], color="#cccccc", lw=0.6)
    ax.set_yticks(range(len(rows)), [c["id"] for c in reversed(rows)], fontsize=8)
    ax.set_xlim(0, max(c["duration_s"] for c in rows))
    ax.set_ylim(-0.6, len(rows) - 0.4)
    ax.set_xlabel("time (s)")
    ax.set_title("IRIS flash-failure frames (top) vs SteadyFrame segments: broadcast, then wcag")
    handles = [plt.Rectangle((0, 0), 1, 1, color=c, alpha=a) for c, a in
               (("#d98c1f", 1), ("#b8312f", 0.55), ("#7a3fa0", 0.55))]  # fmt: skip
    ax.legend(handles, ["IRIS 1.1.0 flash failure", "SteadyFrame broadcast", "SteadyFrame wcag"],
              loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=3, fontsize=8, frameon=False)  # fmt: skip
    fig.tight_layout()
    fig.savefig(dst, dpi=110)
    plt.close(fig)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--no-remediation", action="store_true")
    ap.add_argument("--no-iris-recheck", action="store_true", help="skip IRIS on repaired files")
    a = ap.parse_args(argv)
    man = yaml.safe_load(MANIFEST.read_text())
    clips, missing = [], []
    for c in man["clips"]:
        mp4, lab_csv = OUT / f"{c['id']}.mp4", OUT / f"{c['id']}.iris.csv"
        if not (mp4.exists() and lab_csv.exists()):
            missing.append(c["id"])
            continue
        for p, key in ((mp4, "mp4_sha256"), (lab_csv, "iris_sha256")):
            if c.get(key) and digest(p) != c[key]:
                raise SystemExit(f"{p.name}: checksum differs from data/natural.yaml")
        print(f"{c['id']}: analysing")
        lab = iris_label(lab_csv)
        row = {"id": c["id"], "category": c["category"], "licence": c["licence"], "iris": lab,
               "author": c["author"], "title": c["title"], "_path": mp4, "profiles": {}}  # fmt: skip
        for prof in PROFILES:
            res = cached_analysis(mp4, profile=prof)
            row["profiles"][prof] = score(res, lab)
            v = res["video"]
            row.update(resolution=f"{v['width']}x{v['height']}", fps=round(v["fps"], 2),
                       duration_s=round(v["duration_analyzed_s"], 1))  # fmt: skip
        clips.append(row)
    if not clips:
        print("no natural clips in data/natural; run `make natural` first (skipped)")
        return 0

    summary: dict = {"n_clips": len(clips), "missing": missing, "by_profile": {}}
    summary["minutes"] = round(sum(c["duration_s"] for c in clips) / 60, 1)
    summary["iris_fail_clips"] = [c["id"] for c in clips if c["iris"]["verdict"] == "fail"]
    summary["iris_extended_only"] = [
        c["id"] for c in clips if c["iris"]["extended"] and c["iris"]["verdict"] == "pass"
    ]
    for prof in PROFILES:
        rs = [c["profiles"][prof] for c in clips]
        tp, fp, fn = (sum(r[k] for r in rs) for k in ("tp", "fp", "fn"))
        summary["by_profile"][prof] = {
            "clip_agreement": sum(r["agree"] for r in rs),
            "per_second": prf(tp, fp, fn),
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "seconds": sum(r["seconds"] for r in rs),
            "label_fail_frames": sum(r["label_fail_frames"] for r in rs),
            "covered": sum(r["covered"] for r in rs),
            "fail_clips": [c["id"] for c in clips if c["profiles"][prof]["got"] == "fail"],
            "disagreements": [c["id"] for c in clips if not c["profiles"][prof]["agree"]],
        }
    figure(clips, RESULTS / "fig_natural.png")
    for c in clips:
        b = c["profiles"]["broadcast"]
        if b["fp"] or not b["agree"]:
            print(f"{c['id']}: measuring why the tools differ")
            c["why"] = concurrency_summary(c, concurrency(c["_path"]))
    summary["differences"] = {c["id"]: c["why"] for c in clips if "why" in c}

    remediation: dict = {}
    if not a.no_remediation:
        work = Path(tempfile.mkdtemp(prefix="sf-natural-"))
        todo = [
            c for c in clips
            if c["iris"]["verdict"] == "fail" or c["profiles"]["wcag"]["got"] == "fail"
        ]  # fmt: skip
        for policy in ("fixed", "heuristic"):
            rows = []
            for c in todo:
                print(f"{c['id']}: repairing ({policy})")
                rows.append({"clip": c["id"], **repair(c["_path"], policy, work,
                                                       not a.no_iris_recheck)})  # fmt: skip
            remediation[policy] = {
                "n": len(rows),
                "passed": sum(1 for r in rows if r["status"] == "passed"),
                "broadcast_pass_after": sum(1 for r in rows if r["broadcast_after"] == "pass"),
                "iris_pass_after": sum(1 for r in rows if r["iris_after"] == "pass"),
                "iris_checked": sum(1 for r in rows if r["iris_after"] is not None),
                "approvals": sum(r["approvals"] for r in rows),
                "mean_iterations_per_segment": statistics.mean(r["iter_per_seg"] for r in rows)
                if rows
                else None,
                "rows": rows,
            }
        shutil.rmtree(work, ignore_errors=True)
    summary["remediation"] = remediation

    md = header("Natural: real light sources against EA IRIS")
    md += (
        f"{len(clips)} openly licensed Wikimedia Commons clips ({summary['minutes']} minutes) of "
        "real things that flash. Labels: EA IRIS 1.1.0 (BSD-3-Clause, the official Ubuntu app), "
        "per frame, on the same H.264 transcode SteadyFrame reads; the app first reproduces "
        "IRIS's own expected logs on three of its test videos (`data/natural/iris_check.json`). "
        "Sources, licences, authors and checksums: `data/natural.yaml`. No label comes from this "
        "analyzer.\n\n"
    )
    if missing:
        md += f"Not present (skipped): {', '.join(missing)}\n\n"
    md += "## Detection against IRIS\n\n"
    srows = []
    for prof in PROFILES:
        s = summary["by_profile"][prof]
        ps = s["per_second"]
        srows.append(
            {
                "profile": prof,
                "clip verdicts agree": f"{s['clip_agreement']}/{len(clips)}",
                "IRIS fail frames inside a segment": f"{s['covered']}/{s['label_fail_frames']}",
                "per-second P / R / F1": f"{ps['precision']:.3f} / {ps['recall']:.3f} / {ps['f1']:.3f}",
                "seconds flagged, IRIS pass": f"{s['fp']}/{s['seconds']}",
            }
        )
    md += md_table(srows, list(srows[0].keys())) + "\n"
    md += "![](fig_natural.png)\n\n## Per clip\n\n"
    crow = []
    for c in clips:
        b, w = c["profiles"]["broadcast"], c["profiles"]["wcag"]
        crow.append(
            {
                "clip": c["id"],
                "kind": c["category"],
                "video": f"{c['resolution']} {c['fps']} fps {c['duration_s']} s",
                "IRIS": c["iris"]["verdict"] + (" (extended)" if c["iris"]["extended"] else ""),
                "IRIS fail frames": b["label_fail_frames"],
                "broadcast": b["got"],
                "wcag": w["got"],
                "max cell rate (Hz)": f"{w['max_cell_rate_hz']:.1f}",
                "max area over rate": f"{w['max_area_over_rate']:.2f}",
            }
        )
    md += md_table(crow, list(crow[0].keys())) + "\n"
    if summary["differences"]:
        md += (
            "## Where they differ, and why\n\n"
            "IRIS counts a transition when the *average* luminance of the area that changed moves "
            "by 0.10; SteadyFrame counts transitions in each cell of its 64x48 grid and then asks "
            "whether the cells over the rate cover a quarter of the screen. When some parts of the "
            "picture brighten while others darken (alternating emergency lights, moving disco "
            "spots), the changes cancel in an average and add up across cells. `net` below is "
            "|mean frame-to-frame change| / mean |cell change| on the analyzer's own grid: 1 means "
            "everything moves the same way, 0 that the changes cancel. `at once` is the largest "
            "share of the screen whose cells complete a transition within one frame of each other "
            "(`concurrency()` in this script).\n\n"
        )
        drows = []
        for cid, w in summary["differences"].items():
            c = next(x for x in clips if x["id"] == cid)
            b = c["profiles"]["broadcast"]
            ins, near = w["in_segments"], w["near_iris_fail"]
            fmt = lambda v: "-" if v is None else f"{v:.2f}"  # noqa: E731
            drows.append(
                {
                    "clip": cid,
                    "IRIS / SteadyFrame (broadcast)": f"{b['label']} / {b['got']}",
                    "seconds only SteadyFrame flags": b["fp"],
                    "in SteadyFrame's segments: at once, median net": f"{fmt(ins['max_concurrent_area'])}, {fmt(ins['median_net'])}",
                    "around IRIS's fail frames: at once, median net": f"{fmt(near['max_concurrent_area'])}, {fmt(near['median_net'])}",
                }
            )
        md += md_table(drows, list(drows[0].keys())) + "\n"
        md += (
            "Large areas change at the same moment in both tools' segments, so the difference is "
            "not about concurrency; it is the averaging. Where the changes are coherent IRIS fails "
            "the clip too. Where they cancel, IRIS's average stays under 0.10 and SteadyFrame's "
            "cells do not. Neither reading is a measurement of harm; SteadyFrame's is the "
            "stricter one"
            + (
                ", and it missed no frame IRIS failed.\n\n"
                if summary["by_profile"]["broadcast"]["covered"]
                == summary["by_profile"]["broadcast"]["label_fail_frames"]
                else ".\n\n"
            )
        )
    if remediation:
        md += "## Repair, re-verified by SteadyFrame and by IRIS\n\n"
        rrows = []
        for policy, r in remediation.items():
            for x in r["rows"]:
                rrows.append(
                    {
                        "policy": policy,
                        "clip": x["clip"],
                        "status": x["status"],
                        "strategies": x["strategies"],
                        "approvals": x["approvals"],
                        "SSIM inside": "-"
                        if x["ssim_inside"] is None
                        else f"{x['ssim_inside']:.3f}",
                        "SteadyFrame wcag / broadcast after": f"{x['after']} / {x['broadcast_after']}",
                        "IRIS after": x["iris_after"] or "-",
                    }
                )
        md += md_table(rrows, list(rrows[0].keys())) if rrows else "Nothing to repair.\n"
    write("natural", md, {k: v for k, v in summary.items()} | {
        "clips": [{k: v for k, v in c.items() if not k.startswith("_") and k != "iris"}
                  | {"iris_verdict": c["iris"]["verdict"], "iris_extended": c["iris"]["extended"]}
                  for c in clips]})  # fmt: skip
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
