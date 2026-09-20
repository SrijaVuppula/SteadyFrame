"""Turn a trace.jsonl into a readable markdown table that shows how each decision follows
from the previous analyzer result.

    python -m eval.annotate_trace trace.jsonl out.md --title "..." --clip x.mp4
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def annotate(records: list[dict], *, title: str, intro: str = "") -> str:
    lines = [
        f"# {title}",
        "",
        intro,
        "",
        "| seq | kind | what happened | role in the loop |",
        "|---|---|---|---|",
    ]
    prev_verify = None
    for r in records:
        note, why = "", ""
        if r["kind"] == "tool_result" and r["name"] == "verify_candidate" and not r.get("error"):
            v = r["result"]
            prev_verify = v
            note = f"analyzer: passes_for_type={v['passes_for_type']}; {v['reason']}" + (
                f"; needs approval ({v['approval_reason']})" if v.get("requires_approval") else ""
            )
            why = "perception after action"
        elif r["kind"] == "model" and r["name"] == "turn":
            calls = (
                ", ".join(f"{c['name']}({json.dumps(c['input'])})" for c in r["tool_calls"])
                or "(no tool call)"
            )
            note = f"{r.get('text', '')} -> {calls}"
            why = "decision (model)"
            if prev_verify is not None and r["tool_calls"]:
                why = "**follows from the verify result above**"
                prev_verify = None
        elif r["kind"] == "tool_call" and r["name"] == "apply_remediation":
            a = r["args"]
            note = f"render {a['strategy']} {json.dumps(a.get('params', {}))} on {a['segment_id']}"
            why = "action" + (" (fixed policy)" if r.get("by", "").startswith("fixed") else "")
            if prev_verify is not None and r.get("by", "").startswith("fixed"):
                why = "**follows from the verify result above** (fixed policy escalation)"
                prev_verify = None
        elif (
            r["kind"] == "tool_call"
            and r["name"] in ("accept_candidate", "request_human_approval")
            and r.get("by", "").startswith("fixed")
        ):
            note = f"{r['name']} {json.dumps(r['args'])[:120]}"
            why = (
                "**follows from the verify result above**" if prev_verify is not None else "action"
            )
            prev_verify = None
        elif r["kind"] == "tool_result" and r["name"] == "analyze_video" and not r.get("error"):
            segs = r["result"]["segments"]
            note = f"verdict {r['result']['verdict']}, {len(segs)} segment(s): " + "; ".join(
                f"{s['id']} {s['type']} {s['peak_flash_rate_hz']}Hz dL={s['max_delta_L']} area={s['max_area_fraction']}"
                for s in segs
            )
            why = "perception"
        elif (
            r["kind"] == "tool_result" and r["name"] == "get_segment_detail" and not r.get("error")
        ):
            h = r["result"].get("parameter_hints", {})
            note = f"hints: S1 alpha {h.get('S1', {}).get('alpha')}, regional={h.get('prefer_regional')}; attempts so far {len(r['result'].get('attempts', []))}"
            why = "perception"
        elif r["kind"] == "tool_result" and r.get("error"):
            note = f"{r['name']} error: {r['error']}"
            why = "tool error reported back"
        elif r["kind"] == "decision":
            note = json.dumps(
                {
                    k: v
                    for k, v in r.items()
                    if k not in ("seq", "job_id", "t_rel_s", "ts", "kind", "name")
                }
            )[:200]
            why = r["name"]
        elif r["kind"] == "error":
            note = json.dumps(
                {k: v for k, v in r.items() if k not in ("seq", "job_id", "t_rel_s", "ts", "kind")}
            )[:200]
            why = "failure handling"
        else:
            continue
        lines.append(f"| {r['seq']} | {r['kind']} | {note.replace('|', '/')} | {why} |")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("trace")
    ap.add_argument("out")
    ap.add_argument("--title", default="Annotated trace")
    ap.add_argument("--intro", default="")
    a = ap.parse_args(argv)
    recs = [json.loads(line) for line in Path(a.trace).read_text().splitlines() if line.strip()]
    Path(a.out).write_text(annotate(recs, title=a.title, intro=a.intro))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
