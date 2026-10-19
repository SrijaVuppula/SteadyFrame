"""`make demo`: the whole loop on this machine, with no credentials and no cloud account.

    python -m service.demo [--out demo]

Renders the three sample clips the web app offers (two hazardous, one clean), then for each
runs the same commands a user would: ``steadyframe analyze``, ``steadyframe fix`` with the
offline planner (the heuristic stand-in that speaks the agent's tool protocol), and
``steadyframe verify`` on the output against the verification record. Everything lands in
``demo/`` (gitignored). The rendered originals flash by design: open the plots, the stills
and the records, not the input clips.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

from steadyframe.cli import main as cli

from .samples import SAMPLES, generate


def run(cmd: list[str]) -> int:
    print("$ steadyframe " + " ".join(cmd), flush=True)
    return cli(cmd)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="demo")
    args = ap.parse_args(argv)
    out = Path(args.out)
    shutil.rmtree(out, ignore_errors=True)
    (out / "clips").mkdir(parents=True)
    (out / ".gitignore").write_text("*\n")
    t0 = time.perf_counter()
    clips = generate(out / "clips")
    print(f"rendered {len(clips)} sample clips into {out / 'clips'} (do not play them)\n")
    rows = []
    for clip, meta in zip(clips, SAMPLES, strict=True):
        d = out / clip.stem
        d.mkdir()
        print(f"== {meta['name']}: {meta['description']}")
        rc_a = run(["analyze", str(clip), "--json", str(d / "analysis.json"), "--plot", str(d / "before.png"), "--vtt", str(d / "hazards.vtt")])  # fmt: skip
        rc_f = run(
            [
                "fix", str(clip), "--policy", "heuristic", "-o", str(d / "safe.mp4"),
                "--report", str(d / "report.json"), "--trace", str(d / "trace.jsonl"),
                "--record", str(d / "record.json"), "--plot", str(d / "before_after.png"),
            ]
        )  # fmt: skip
        rc_v = run(["verify", str(d / "safe.mp4"), "--record", str(d / "record.json")])
        rep = json.loads((d / "report.json").read_text())
        rows.append(
            {
                "clip": clip.name,
                "before": rep["before"]["verdict"],
                "status": rep["status"],
                "after": (rep.get("after") or {}).get("verdict"),
                "strategies": ",".join(s.get("strategy") or "-" for s in rep["segments"]) or "-",
                "record_holds": rc_v == 0,
                "exit_codes": [rc_a, rc_f, rc_v],
            }
        )
        print()
    print(f"done in {time.perf_counter() - t0:.0f} s\n")
    print(f"{'clip':28s} {'before':7s} {'status':12s} {'after':6s} {'fix':8s} record")
    for r in rows:
        print(
            f"{r['clip']:28s} {r['before']:7s} {r['status']:12s} {str(r['after']):6s} "
            f"{r['strategies']:8s} {'holds' if r['record_holds'] else 'DOES NOT HOLD'}"
        )
    print(
        f"\nOpen {out}/<clip>/record.html (verification record), before_after.png (luminance "
        "before and after) and hazards.vtt (viewer warning track).\n"
        "Web UI on this machine, still no credentials: docker compose up --build, then "
        "http://localhost:8080 (the same live demo page as the deployed site)."
    )
    ok = all(r["record_holds"] and r["status"] in ("passed", "no_hazards") for r in rows)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
