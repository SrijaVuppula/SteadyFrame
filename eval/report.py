"""Render the technical report from its template and the frozen evaluation results.

    python -m eval.report [--results eval/results/frozen]

Every number in docs/report/REPORT.md comes from a JSON file written by an eval or bench
script; the template only has placeholders like {{detection.per_second.f1:.3f}}. Missing
results render as "n/a (not run)" so a partially evaluated build is visibly partial.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "docs" / "report" / "REPORT.template.md"
OUT = ROOT / "docs" / "report" / "REPORT.md"
FIG = ROOT / "docs" / "report" / "figures"

PH = re.compile(r"\{\{([\w.\-\[\]\"]+)(?::([^}]+))?\}\}")


def lookup(data: dict, path: str):
    """a.b[0].c and a["key.with.dots"].c"""
    cur = data
    for tok in re.findall(r'\["([^"]+)"\]|\[(\d+)\]|([\w\-]+)', path):
        quoted, index, name = tok
        if quoted:
            cur = cur[quoted]
        elif index:
            cur = cur[int(index)]
        else:
            cur = cur[name]
    return cur


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=str(ROOT / "eval" / "results" / "frozen"))
    ap.add_argument("--bench", default=str(ROOT / "bench" / "results"))
    a = ap.parse_args(argv)
    res = Path(a.results)
    data: dict = {}
    for p in list(res.glob("*.json")) + list(Path(a.bench).glob("*.json")):
        try:
            data[p.stem.replace("-", "_")] = json.loads(p.read_text())
        except Exception:
            pass
    missing = []

    def sub(m: re.Match) -> str:
        key, fmt = m.group(1), m.group(2)
        try:
            v = lookup(data, key)
        except Exception:
            missing.append(key)
            return "n/a (not run)"
        if fmt and isinstance(v, (int, float)):
            return format(v, fmt)
        return str(v)

    text = PH.sub(sub, TEMPLATE.read_text())
    FIG.mkdir(parents=True, exist_ok=True)
    for png in (
        list(res.glob("*.png"))
        + list(Path(a.bench).glob("*.png"))
        + list((res / "failures").glob("*.png"))
    ):
        shutil.copyfile(png, FIG / png.name)
    for svg in (ROOT / "docs" / "diagrams").glob("*.svg"):
        shutil.copyfile(svg, FIG / svg.name)
    OUT.write_text(text)
    print(
        f"wrote {OUT.relative_to(ROOT)}; {len(missing)} placeholder(s) without data"
        + (": " + ", ".join(sorted(set(missing))) if missing else "")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
