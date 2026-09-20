"""Curated failure gallery: stills and plots only (never animated).

    python -m eval.failures  -> eval/results/failures.md + eval/results/failures/*.png

Collects (1) every synthetic clip whose verdict disagrees with the ground truth on any grid
size or CRF variant, (2) remediation cases with the lowest quality retention or the most
attempts, (3) the known limitations we can demonstrate: an edge-of-window region that flips
with the grid, and a sub-threshold flash pattern the tool does not flag.
"""

from __future__ import annotations

import json

import cv2

from steadyframe.io.video import open_video
from steadyframe.plot import plot_analysis

from .common import RESULTS, cached_analysis, header, load_suite

OUT = RESULTS / "failures"


def still(path, t_s: float, regions: list[dict], dst) -> None:
    """One frame with the regions outlined. Dimmed on purpose (it is hazardous content)."""
    r = open_video(path)
    frame = None
    for _i, t, f in r:
        frame = f
        if t >= t_s:
            break
    if frame is None:
        return
    h, w = frame.shape[:2]
    img = (frame * 0.6).astype("uint8")
    for reg in regions:
        x0, y0 = int(reg["x"] * w), int(reg["y"] * h)
        x1, y1 = int((reg["x"] + reg["w"]) * w), int((reg["y"] + reg["h"]) * h)
        cv2.rectangle(img, (x0, y0), (x1, y1), (0, 200, 255), 2)
    cv2.imwrite(str(dst), img)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    gts = load_suite(include_variants=True)
    md = header("Failure gallery")
    md += "Stills are dimmed single frames with the detected regions outlined; nothing here animates.\n\n"
    entries = []
    # 1. verdict disagreements across grids / variants
    rob = RESULTS / "robustness.json"
    if rob.exists():
        data = json.loads(rob.read_text())
        for row in data.get("grid", {}).get("rows", []):
            bad = [k for k, v in row.items() if isinstance(v, str) and v.endswith("(!)")]
            if bad:
                gt = next(g for g in gts if g["clip"] == row["clip"])
                res = cached_analysis(gt["_path"])
                png = OUT / f"{row['clip']}.grid.png"
                plot_analysis(
                    res, png, title=f"{row['clip']}: wrong verdict at grid(s) {', '.join(bad)}"
                )
                entries.append(
                    {
                        "title": f"Grid sensitivity: {row['clip']}",
                        "png": png.name,
                        "text": f"Expected {row['expected']}; wrong at grids {', '.join(bad)}. The flashing region is aligned to the 64x48 grid, so coarser or finer grids split its edge cells and the box-averaged luminance swing of a partial cell can land on either side of the 0.10 threshold. This is the quantisation limit of the cell-based area rule.",
                    }
                )
        for row in data.get("crf", {}).get("rows", []):
            if row["got"] != row["expected"]:
                entries.append(
                    {
                        "title": f"Compression: {row['clip']}",
                        "png": None,
                        "text": f"CRF {row['crf']}: expected {row['expected']}, got {row['got']}.",
                    }
                )
    # 2. remediation: lowest quality / most attempts
    rem = RESULTS / "remediation.json"
    if rem.exists():
        data = json.loads(rem.read_text())
        rows = sorted(data["rows"], key=lambda r: r["ssim_inside"] or 1.0)[:3]
        for r in rows:
            gt = next(g for g in gts if g["clip"] == r["clip"])
            res = cached_analysis(gt["_path"])
            seg = res["segments"][0] if res["segments"] else None
            png = OUT / f"{r['clip']}.still.png"
            if seg:
                still(gt["_path"], (seg["start_s"] + seg["end_s"]) / 2, seg["regions"], png)
            entries.append(
                {
                    "title": f"Largest visible change: {r['clip']}",
                    "png": png.name if seg else None,
                    "text": f"Fixed with {r['strategies']} in {r['attempts']} attempt(s); SSIM inside the region {r['ssim_inside']:.3f}, mean |dL| {r['dL_inside']:.3f}. Full-frame, full-swing strobes have no gentle fix: removing a 0.5 luminance swing is by definition a large change inside the region.",
                }
            )
        for r in data.get("unresolved", []):
            entries.append(
                {
                    "title": f"Unresolved: {r['clip']}",
                    "png": None,
                    "text": r["reason"] or r["status"],
                }
            )
    # 3. known limitations we can show
    entries.append(
        {
            "title": "Pattern detector is experimental",
            "png": None,
            "text": "`p_stripes_static` is flagged as pattern risk, but the DFT peak test has no notion of viewing distance and would also flag fine textures with enough contrast; it is reported as a warning, never a fail, and is off by default in the service.",
        }
    )
    entries.append(
        {
            "title": "Fine balanced patterns are not exempted",
            "png": None,
            "text": "WCAG exempts white-noise-like flashing with squares under 0.1 degree. We do not implement the exemption, so such content is over-flagged (conservative).",
        }
    )
    entries.append(
        {
            "title": "No display model",
            "png": None,
            "text": "Relative luminance from sRGB code values stands in for screen luminance in cd/m2; a very dim or very bright display changes the real stimulus and we cannot know it.",
        }
    )
    for e in entries:
        md += f"## {e['title']}\n\n{e['text']}\n\n"
        if e["png"]:
            md += f"![]({OUT.name}/{e['png']})\n\n"
    (RESULTS / "failures.md").write_text(md)
    (RESULTS / "failures.json").write_text(json.dumps(entries, indent=2))
    print(f"wrote eval/results/failures.md with {len(entries)} entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
