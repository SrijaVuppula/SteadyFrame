"""Detection evaluation on the synthetic suite.

    python -m eval.detection            -> eval/results/detection.{md,json}

Metrics: clip verdict accuracy, per-second (window-level) precision/recall/F1 with `fail`
as the positive class, boundary-case table, hazard-type agreement, temporal IoU of
detected segments against the ground-truth event intervals, spatial IoU of regions.
Compression variants are excluded here (see eval/robustness.py).
"""

from __future__ import annotations

import statistics

from .common import box_iou, cached_analysis, header, interval_iou, load_suite, md_table, prf, write


def evaluate(gts: list[dict]) -> dict:
    rows: list[dict] = []
    fp = fn = 0
    tp = 0
    boundary = []
    t_ious, s_ious = [], []
    type_ok = 0
    for gt in gts:
        res = cached_analysis(gt["_path"], detect_patterns=gt["expected_type"] == "pattern")
        got = res["verdict"]
        exp = gt["expected_verdict"]
        ps_exp = gt["per_second"]
        ps_got = [s["verdict"] for s in res["per_second"]]
        n = min(len(ps_exp), len(ps_got))
        c_tp = sum(1 for i in range(n) if ps_exp[i] == "fail" and ps_got[i] == "fail")
        c_fp = sum(1 for i in range(n) if ps_exp[i] != "fail" and ps_got[i] == "fail")
        c_fn = sum(1 for i in range(n) if ps_exp[i] == "fail" and ps_got[i] != "fail")
        tp, fp, fn = tp + c_tp, fp + c_fp, fn + c_fn
        det_types = {s["type"] for s in res["segments"] if s["verdict"] == "fail"}
        types_match = set(gt.get("expected_types", [])) == det_types
        type_ok += types_match
        # localisation against the GT event intervals / regions
        clip_t, clip_s = [], []
        for g in gt["segments"]:
            cands = [s for s in res["segments"] if s["type"] == g["type"]]
            if not cands:
                clip_t.append(0.0)
                clip_s.append(0.0)
                continue
            best = max(
                cands,
                key=lambda s: interval_iou((s["start_s"], s["end_s"]), (g["start_s"], g["end_s"])),
            )
            clip_t.append(
                interval_iou((best["start_s"], best["end_s"]), (g["start_s"], g["end_s"]))
            )
            clip_s.append(max(box_iou(r, g["region"]) for r in best["regions"]))
        t_ious += clip_t
        s_ious += clip_s
        row = {
            "clip": gt["clip"],
            "expected": exp,
            "got": got,
            "ok": "yes" if exp == got else "**NO**",
            "types_ok": "yes" if types_match else "no",
            "sec_tp": c_tp,
            "sec_fp": c_fp,
            "sec_fn": c_fn,
            "t_iou": statistics.mean(clip_t) if clip_t else float("nan"),
            "s_iou": statistics.mean(clip_s) if clip_s else float("nan"),
            "rtf": res["stats"]["realtime_factor"],
        }
        rows.append(row)
        if gt.get("boundary_case"):
            boundary.append(
                {
                    "clip": gt["clip"],
                    "case": gt["boundary_case"],
                    "expected": exp,
                    "got": got,
                    "ok": row["ok"],
                }
            )
    acc = sum(1 for r in rows if r["expected"] == r["got"]) / len(rows)
    return {
        "n_clips": len(rows),
        "clip_accuracy": acc,
        "type_agreement": type_ok / len(rows),
        "per_second": prf(tp, fp, fn),
        "temporal_iou_mean": statistics.mean(t_ious) if t_ious else None,
        "spatial_iou_mean": statistics.mean(s_ious) if s_ious else None,
        "boundary_correct": sum(1 for b in boundary if b["expected"] == b["got"]),
        "boundary_total": len(boundary),
        "rows": rows,
        "boundary": boundary,
        "misses": [r for r in rows if r["expected"] != r["got"]],
    }


def main() -> int:
    gts = load_suite(include_variants=False)
    data = evaluate(gts)
    md = header("Detection: synthetic suite")
    md += (
        f"- Clips: **{data['n_clips']}**, clip-level verdict accuracy **{data['clip_accuracy']:.3f}**, "
        f"hazard-type agreement {data['type_agreement']:.3f}\n"
        f"- Per-second (window-level) with `fail` positive: precision **{data['per_second']['precision']:.3f}**, "
        f"recall **{data['per_second']['recall']:.3f}**, F1 **{data['per_second']['f1']:.3f}** "
        f"(tp={data['per_second']['tp']}, fp={data['per_second']['fp']}, fn={data['per_second']['fn']})\n"
        f"- Boundary cases correct: **{data['boundary_correct']}/{data['boundary_total']}**\n"
        f"- Localisation: mean temporal IoU {data['temporal_iou_mean']:.3f}, mean spatial IoU {data['spatial_iou_mean']:.3f} "
        f"(against ground-truth event intervals and regions; the analyzer's segment end includes the up-to-1 s tail of the trailing window, which lowers temporal IoU by design)\n\n"
    )
    md += "## Boundary cases\n\n" + md_table(
        data["boundary"], ["clip", "case", "expected", "got", "ok"]
    )
    md += "\n## All clips\n\n" + md_table(
        data["rows"],
        [
            "clip",
            "expected",
            "got",
            "ok",
            "types_ok",
            "sec_tp",
            "sec_fp",
            "sec_fn",
            "t_iou",
            "s_iou",
            "rtf",
        ],
        {"rtf": "{:.1f}"},
    )
    if data["misses"]:
        md += (
            "\n## Misses\n\n"
            + "\n".join(
                f"- `{m['clip']}`: expected {m['expected']}, got {m['got']}" for m in data["misses"]
            )
            + "\n"
        )
    else:
        md += "\n## Misses\n\nNone on this run.\n"
    write("detection", md, data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
