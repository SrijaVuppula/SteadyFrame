"""Shared helpers for the evaluation scripts: suite loading, cached analysis, tables."""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import cv2

from steadyframe import __version__, opencv_build_summary
from steadyframe.analyzer import analyze_file

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "synthetic"
RESULTS = ROOT / "eval" / "results"
CACHE = RESULTS / "cache"


def load_suite(*, include_variants: bool = True) -> list[dict]:
    if not DATA.exists() or not list(DATA.glob("*.gt.json")):
        raise SystemExit("no synthetic suite found; run `make synth` first")
    gts = []
    for p in sorted(DATA.glob("*.gt.json")):
        gt = json.loads(p.read_text())
        gt["_path"] = DATA / gt["clip"]
        gt["_variant"] = "__crf" in gt["clip"]
        gt["_base"] = gt["clip"].split("__")[0].replace(".mp4", "")
        if not include_variants and gt["_variant"]:
            continue
        gts.append(gt)
    return gts


def cached_analysis(path: Path, **kw) -> dict:
    """Analyze with an on-disk cache keyed by file digest + parameters + tool version."""
    CACHE.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha256()
    h.update(path.read_bytes()[:1_000_000])
    h.update(str(path.stat().st_size).encode())
    h.update(json.dumps(kw, sort_keys=True).encode())
    h.update(f"{__version__}:{cv2.__version__}:v4".encode())
    cp = CACHE / f"{path.stem}-{h.hexdigest()[:12]}.json"
    if cp.exists():
        return json.loads(cp.read_text())
    res = analyze_file(str(path), **kw)
    cp.write_text(json.dumps(res))
    return res


def git_rev() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=ROOT
        ).stdout.strip()
    except Exception:
        return "unknown"


def header(title: str) -> str:
    ob = opencv_build_summary()
    return (
        f"# {title}\n\n"
        f"Generated {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')} by `python -m eval.{title.split(':')[0].strip().lower().replace(' ', '_')}` "
        f"at git `{git_rev()}`, steadyframe {__version__}, **OpenCV {ob['version']}** "
        f"({platform.machine()}, {platform.python_implementation()} {platform.python_version()}).\n\n"
    )


def md_table(rows: list[dict], cols: list[str], fmt: dict | None = None) -> str:
    fmt = fmt or {}
    out = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for r in rows:
        cells = []
        for c in cols:
            v = r.get(c, "")
            if isinstance(v, float):
                v = fmt.get(c, "{:.3f}").format(v)
            cells.append(str(v))
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out) + "\n"


def interval_iou(a: tuple[float, float], b: tuple[float, float]) -> float:
    inter = max(0.0, min(a[1], b[1]) - max(a[0], b[0]))
    union = max(a[1], b[1]) - min(a[0], b[0])
    return inter / union if union > 0 else 0.0


def box_iou(a: dict, b: dict) -> float:
    ax1, ay1 = a["x"] + a["w"], a["y"] + a["h"]
    bx1, by1 = b["x"] + b["w"], b["y"] + b["h"]
    iw = max(0.0, min(ax1, bx1) - max(a["x"], b["x"]))
    ih = max(0.0, min(ay1, by1) - max(a["y"], b["y"]))
    inter = iw * ih
    union = a["w"] * a["h"] + b["w"] * b["h"] - inter
    return inter / union if union > 0 else 0.0


def prf(tp: int, fp: int, fn: int) -> dict:
    p = tp / (tp + fp) if tp + fp else 1.0
    r = tp / (tp + fn) if tp + fn else 1.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "precision": p, "recall": r, "f1": f}


def write(name: str, md: str, data: dict) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / f"{name}.md").write_text(md)
    (RESULTS / f"{name}.json").write_text(json.dumps(data, indent=2))
    print(f"wrote eval/results/{name}.md and .json")
