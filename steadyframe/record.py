"""Verification record, viewer warning track, and the re-check that backs them.

``record.json`` is the document a reviewer keeps after a fix: the SHA-256 of the input and of
the output, the profile and every threshold it applied, the analyzer and OpenCV build, the
verdict before and after, each segment's measurements and the fix applied to it, any human
decision, and a digest of the record itself. ``record.html`` is the same content as a
printable page.

A record is a claim, not a certificate: ``steadyframe verify`` re-hashes the file and re-runs
the analyzer on it, so anyone with the file and the record can check the claim on their own
machine. That re-check is the point; the digest only shows the record was not edited.

``hazards.vtt`` is a WebVTT track for the *original* video: a cue shortly before and during
every flagged segment, so a player can warn viewers who watch the unmodified version.
"""

from __future__ import annotations

import hashlib
import html
import json
import time
from dataclasses import asdict
from pathlib import Path

from . import __version__, opencv_build_summary
from .profiles import Profile, get_profile

RECORD_VERSION = "1.0"
RECORD_KIND = "steadyframe.verification_record"
WARN_LEAD_S = 3.0

STANDARD_NAMES = {
    "wcag": "WCAG 2.2 success criterion 2.3.1 (general flash and red flash thresholds)",
    "broadcast": "ITU-R BT.1702 / Ofcom guidance on flashing images (area over the whole screen)",
}

STATEMENT = (
    "This record states what SteadyFrame measured. A pass means no segment of the output "
    "exceeds the published thresholds named above as this analyzer implements them "
    "(docs/STANDARDS.md); it is not a certification, not a guarantee that the content is safe "
    "for every viewer, and not medical advice."
)


# ---------------------------------------------------------------- hashing


def sha256_file(path: str | Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while b := f.read(chunk):
            h.update(b)
    return h.hexdigest()


def canonical(doc: dict) -> bytes:
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), default=str).encode()


def record_digest(record: dict) -> str:
    return hashlib.sha256(canonical({k: v for k, v in record.items() if k != "digest"})).hexdigest()


# ---------------------------------------------------------------- record


def thresholds(profile: Profile) -> dict:
    p = asdict(profile)
    keys = (
        "luminance_delta",
        "dark_state_max",
        "red_saturation_ratio",
        "red_delta",
        "window_s",
        "max_flashes_per_window",
        "area_fraction",
        "area_mode",
        "grid_w",
        "grid_h",
        "conservative",
    )
    return {k: p[k] for k in keys}


def _file_entry(path: str | Path | None, name: str | None = None) -> dict | None:
    if not path or not Path(path).is_file():
        return None
    p = Path(path)
    return {"filename": name or p.name, "sha256": sha256_file(p), "bytes": p.stat().st_size}


def build_record(
    report: dict,
    profile: Profile,
    input_path: str | Path,
    output_path: str | Path | None,
    *,
    input_name: str | None = None,
    output_name: str | None = None,
    created_at: str | None = None,
) -> dict:
    """Assemble the record from a remediation report (``fix_file`` output) and the files."""
    before = report.get("before") or {}
    after = report.get("after") or None
    status = report.get("status")
    has_output = status in ("passed", "no_hazards", "failed_verification")
    inp = report.get("input") or {}
    rem = {s["segment_id"]: s for s in report.get("segments") or []}
    segments = []
    for s in before.get("segments", []):
        r = rem.get(s["id"]) or {}
        appr = r.get("approval") or {}
        decision = appr.get("decision") or None
        q = r.get("quality") or {}
        segments.append(
            {
                "id": s["id"],
                "type": s["type"],
                "start_s": s["start_s"],
                "end_s": s["end_s"],
                "peak_flash_rate_hz": s["peak_flash_rate_hz"],
                "max_area_fraction": s["max_area_fraction"],
                "max_delta_L": s["max_delta_L"],
                "regions": s.get("regions", []),
                "outcome": r.get("outcome", "unresolved"),
                "strategy": r.get("strategy"),
                "params": r.get("params"),
                "attempts": len(r.get("attempts") or []),
                "quality": {k: q.get(k) for k in ("ssim_inside", "ssim_outside", "ssim_overall")}
                if q
                else None,
                "human_decision": {
                    k: decision.get(k) for k in ("approved", "candidate_id", "by", "decided_at")
                }
                if decision
                else None,
            }
        )
    ocv = (report.get("tool") or {}).get("opencv") or opencv_build_summary()
    llm = report.get("llm") or None
    record = {
        "kind": RECORD_KIND,
        "record_version": RECORD_VERSION,
        "created_at": created_at or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "tool": {
            "name": "steadyframe",
            "version": (report.get("tool") or {}).get("version", __version__),
            "opencv": {k: ocv.get(k) for k in ("version", "kleidicv", "parallel_framework")},
        },
        "standard": {
            "profile": profile.name,
            "name": STANDARD_NAMES.get(profile.name, profile.name),
            "thresholds": thresholds(profile),
        },
        "input": {
            **(_file_entry(input_path, input_name) or {}),
            **{k: inp.get(k) for k in ("width", "height", "fps", "frames_analyzed")},
            "duration_s": inp.get("duration_analyzed_s"),
        },
        "output": _file_entry(output_path, output_name) if has_output else None,
        "result": {
            "status": status,
            "verdict_before": before.get("verdict"),
            "verdict_after": (after or {}).get("verdict"),
            "segments_flagged": len(before.get("segments", [])),
            "segments_remaining_after": len((after or {}).get("segments", [])) if after else None,
        },
        "segments": segments,
        "decided_by": {
            "policy": report.get("policy"),
            "model_turns": llm.get("turns") if llm else None,
            "fallback": llm.get("fallback") if llm else None,
        },
        # The three PSE fields of the AS-11 UK DPP delivery metadata, in that shape. Which test
        # tools a broadcaster accepts for these fields is the broadcaster's decision.
        "as11_uk_dpp_pse": {
            "PSEPass": "Yes"
            if status in ("passed", "no_hazards")
            else "No"
            if status == "failed_verification"
            else "Not tested",
            "PSEManufacturer": "SteadyFrame (open source)",
            "PSEVersion": f"steadyframe {__version__} / {profile.name} profile",
        },
        "statement": STATEMENT,
        "recheck": "steadyframe verify <output file> --record record.json",
    }
    record["digest"] = record_digest(record)
    return record


def write_record(record: dict, json_path: str | Path, html_path: str | Path | None = None) -> None:
    Path(json_path).parent.mkdir(parents=True, exist_ok=True)
    Path(json_path).write_text(json.dumps(record, indent=2, default=str))
    if html_path:
        Path(html_path).write_text(record_html(record))


# ---------------------------------------------------------------- re-check


def verify_file(video: str | Path, record: dict, *, backend: str = "auto") -> dict:
    """Re-check a record against a file: digest, file hash, and a fresh analysis.

    Returns {"ok": bool, "checks": [{"name", "ok", "detail"}], "analysis_verdict": ...}."""
    from .analyzer import analyze_file

    checks = []

    def check(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    check(
        "record digest",
        record.get("digest") == record_digest(record),
        "record content matches its digest"
        if record.get("digest") == record_digest(record)
        else "record was edited after it was written",
    )
    target = record.get("output") or record.get("input") or {}
    which = "output" if record.get("output") else "input"
    digest = sha256_file(video)
    check(
        f"{which} sha256",
        digest == target.get("sha256"),
        f"file {digest[:16]}… vs record {str(target.get('sha256'))[:16]}…",
    )
    std = record.get("standard") or {}
    th = std.get("thresholds") or {}
    prof = get_profile(
        std.get("profile", "wcag"),
        conservative=bool(th.get("conservative")),
        grid=(int(th["grid_w"]), int(th["grid_h"])) if th.get("grid_w") else None,
    )
    result = analyze_file(str(video), profile=prof, backend=backend)
    res = record.get("result") or {}
    expected = res.get("verdict_after") if which == "output" else res.get("verdict_before")
    check(
        "re-analysis verdict",
        result["verdict"] == expected,
        f"analyzer now says {result['verdict']}, record says {expected}",
    )
    if which == "output" and res.get("segments_remaining_after") is not None:
        n = len(result["segments"])
        check(
            "remaining segments",
            n == res["segments_remaining_after"],
            f"{n} now vs {res['segments_remaining_after']} in the record",
        )
    return {
        "ok": all(c["ok"] for c in checks),
        "checks": checks,
        "analysis_verdict": result["verdict"],
        "opencv": result["tool"].get("opencv") if isinstance(result.get("tool"), dict) else None,
    }


# ---------------------------------------------------------------- warning track


def _ts(t: float) -> str:
    t = max(0.0, t)
    h, rem = divmod(int(round(t * 1000)), 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def where(regions: list[dict]) -> str:
    """Plain-words screen position of the union of a segment's regions."""
    if not regions:
        return "on screen"
    x0 = min(r["x"] for r in regions)
    y0 = min(r["y"] for r in regions)
    x1 = max(r["x"] + r["w"] for r in regions)
    y1 = max(r["y"] + r["h"] for r in regions)
    if (x1 - x0) * (y1 - y0) >= 0.8:
        return "most of the screen"
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    col = "left" if cx < 1 / 3 else "right" if cx > 2 / 3 else ""
    row = "top" if cy < 1 / 3 else "bottom" if cy > 2 / 3 else ""
    if not col and not row:
        return "centre of the screen"
    return f"{row}{'-' if row and col else ''}{col} of the screen"


def hazard_vtt(segments: list[dict], *, lead_s: float = WARN_LEAD_S) -> str:
    """WebVTT for the original video: an advance cue, then one cue per flagged segment."""
    lines = [
        "WEBVTT",
        "",
        "NOTE",
        "Flashing-content warnings from SteadyFrame for the ORIGINAL video. Times and positions",
        "are the analyzer's measurements; see the verification record for the thresholds.",
        "",
    ]
    prev_end = 0.0
    for s in sorted(segments, key=lambda s: s["start_s"]):
        start, end = float(s["start_s"]), float(s["end_s"])
        kind = "red flashing" if s.get("type") == "red" else "flashing"
        lead_from = max(prev_end, start - lead_s)
        if start - lead_from >= 1.0:  # shorter than a second is not readable
            lines += [
                f"{s['id']}-ahead",
                f"{_ts(lead_from)} --> {_ts(start)}",
                f"[Warning: {kind} lights ahead, from {int(start // 60)}:{start % 60:04.1f}]",
                "",
            ]
        lines += [
            s["id"],
            f"{_ts(start)} --> {_ts(max(end, start + 0.5))}",
            f"[Warning: {kind} lights, {s['peak_flash_rate_hz']:.0f} flashes a second, "
            f"{where(s.get('regions') or [])}]",
            "",
        ]
        prev_end = max(prev_end, end)
    return "\n".join(lines)


# ---------------------------------------------------------------- printable page


def record_html(record: dict) -> str:
    e = html.escape
    res = record.get("result") or {}
    std = record.get("standard") or {}
    th = std.get("thresholds") or {}
    inp = record.get("input") or {}
    out = record.get("output") or {}
    status = res.get("status")
    passed = status in ("passed", "no_hazards")
    headline = (
        "Output meets the thresholds as measured"
        if passed
        else "Output does not meet the thresholds"
        if status == "failed_verification"
        else "No output yet: waiting for a human decision"
        if status == "needs_approval"
        else f"Status: {status}"
    )
    rows = []
    for s in record.get("segments") or []:
        q = s.get("quality") or {}
        d = s.get("human_decision") or {}
        rows.append(
            "<tr>"
            f"<td>{e(s['id'])}</td><td>{e(s['type'])}</td>"
            f"<td>{s['start_s']:.2f}–{s['end_s']:.2f} s</td>"
            f"<td>{s['peak_flash_rate_hz']:.1f}</td><td>{s['max_area_fraction']:.2f}</td>"
            f"<td>{s['max_delta_L']:.2f}</td><td>{e(where(s.get('regions') or []))}</td>"
            f"<td>{e(str(s.get('outcome')))}</td>"
            f"<td>{e(str(s.get('strategy') or '–'))} {e(json.dumps(s.get('params') or {}))}</td>"
            f"<td>{s.get('attempts', 0)}</td>"
            f"<td>{'' if q.get('ssim_inside') is None else format(q['ssim_inside'], '.3f')}</td>"
            f"<td>{e(('approved' if d.get('approved') else 'rejected') + ' by ' + str(d.get('by'))) if d else '–'}</td>"
            "</tr>"
        )
    thr = "".join(f"<tr><th>{e(k)}</th><td>{e(str(v))}</td></tr>" for k, v in th.items())
    ocv = (record.get("tool") or {}).get("opencv") or {}
    dec = record.get("decided_by") or {}

    def file_row(label: str, f: dict) -> str:
        if not f:
            return f"<tr><th>{label}</th><td colspan='2'>none</td></tr>"
        return (
            f"<tr><th>{label}</th><td>{e(str(f.get('filename')))} ({f.get('bytes')} bytes)</td>"
            f"<td><code>{e(str(f.get('sha256')))}</code></td></tr>"
        )

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Verification record {e(str(out.get("filename") or inp.get("filename")))}</title>
<style>
:root{{--fg:#1d1d1f;--muted:#555;--line:#d0d0d0;--ok:#1f6f3a;--bad:#a61b1b;--bg:#fff;--panel:#f5f5f5}}
body{{font:14px/1.5 system-ui,sans-serif;max-width:980px;margin:24px auto;padding:0 16px;color:var(--fg);background:var(--bg)}}
h1{{font-size:22px;margin:0 0 4px}} h2{{font-size:16px;margin:24px 0 6px}}
table{{border-collapse:collapse;width:100%;margin:6px 0}} th,td{{border:1px solid var(--line);padding:4px 6px;text-align:left;vertical-align:top}}
th{{background:var(--panel);font-weight:600}} code{{font-size:12px;word-break:break-all}}
.badge{{display:inline-block;padding:6px 10px;border-radius:4px;font-weight:700;color:#fff;background:{
        "var(--ok)" if passed else "var(--bad)"
    }}}
.muted{{color:var(--muted)}} .note{{border:1px solid var(--line);background:var(--panel);padding:8px 12px;margin-top:20px}}
@media print{{body{{margin:0}} .badge{{-webkit-print-color-adjust:exact;print-color-adjust:exact}}}}
</style></head><body>
<h1>Flash-threshold verification record</h1>
<p class="muted">{e(str(std.get("name")))} · recorded {e(str(record.get("created_at")))} ·
steadyframe {e(str((record.get("tool") or {}).get("version")))} on OpenCV {
        e(str(ocv.get("version")))
    }{
        (" with KleidiCV " + e(str(ocv.get("kleidicv"))))
        if ocv.get("kleidicv") not in (None, "", "NO")
        else ""
    }</p>
<p><span class="badge">{e(headline)}</span></p>
<p>Before: <b>{e(str(res.get("verdict_before")))}</b>, {
        res.get("segments_flagged")
    } segment(s) flagged.
After: <b>{e(str(res.get("verdict_after")))}</b>{
        (", " + str(res.get("segments_remaining_after")) + " segment(s) remaining")
        if res.get("segments_remaining_after") is not None
        else ""
    }. Decided by: {e(str(dec.get("policy")))}{
        (", " + str(dec.get("model_turns")) + " model turns") if dec.get("model_turns") else ""
    }{(", fallback: " + e(str(dec.get("fallback")))) if dec.get("fallback") else ""}.</p>
<h2>Files</h2>
<table><tbody>{file_row("Input", inp)}{file_row("Output", out)}</tbody></table>
<p class="muted">Input: {inp.get("width")}x{inp.get("height")} at {inp.get("fps")} fps, {
        inp.get("frames_analyzed")
    } frames.</p>
<h2>Segments flagged in the input</h2>
<table><thead><tr><th>id</th><th>type</th><th>time</th><th>flashes/s</th><th>area</th><th>max ΔL</th><th>where</th><th>outcome</th><th>fix</th><th>attempts</th><th>SSIM inside</th><th>human decision</th></tr></thead>
<tbody>{"".join(rows) or '<tr><td colspan="12">none</td></tr>'}</tbody></table>
<h2>Thresholds applied</h2>
<table><tbody>{thr}</tbody></table>
<h2>Delivery metadata</h2>
<p>In the shape of the AS-11 UK DPP PSE fields (the broadcaster decides which test tools it
accepts): {
        " · ".join(
            f"<b>{e(k)}</b> {e(str(v))}" for k, v in (record.get("as11_uk_dpp_pse") or {}).items()
        )
    }</p>
<h2>Check this record yourself</h2>
<p><code>{e(str(record.get("recheck")))}</code> re-hashes the file and re-runs the analyzer; it
exits 0 only if the file is the one recorded here and the verdict is unchanged.</p>
<p class="muted">Record digest (SHA-256 of the record without this field): <code>{
        e(str(record.get("digest")))
    }</code></p>
<div class="note">{e(str(record.get("statement")))}</div>
</body></html>
"""


__all__ = [
    "build_record",
    "write_record",
    "verify_file",
    "hazard_vtt",
    "record_html",
    "sha256_file",
    "record_digest",
]
