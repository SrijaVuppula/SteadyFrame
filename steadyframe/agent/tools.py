"""The job toolbox: the six tools both the fixed policy and the LLM agent call.

The model never sees pixels. Everything it reasons over is produced by the OpenCV 5
analyzer (segment measurements, verify verdicts, quality metrics)."""

from __future__ import annotations

import json
import shutil
import time
import uuid
from pathlib import Path

import numpy as np

from .. import __version__, opencv_build_summary
from ..analyzer import analyze_file
from ..io.video import open_video
from ..profiles import Profile, get_profile
from ..remediate.registry import SPECS, describe
from ..remediate.renderer import Plan, render
from ..schema import SCHEMA_VERSION
from .trace import Trace

VERIFY_PAD_S = 1.0


class ToolError(Exception):
    """Raised for bad tool arguments; reported back to the caller, never crashes the job."""


class BudgetExhausted(ToolError):
    pass


class ApprovalPending(Exception):
    """Job must pause for a human decision."""

    def __init__(self, segment_id: str, request: dict):
        super().__init__(f"approval pending for {segment_id}")
        self.segment_id = segment_id
        self.request = request


class Job:
    def __init__(
        self,
        video: str | Path,
        workdir: str | Path,
        *,
        profile: str | Profile = "wcag",
        job_id: str | None = None,
        max_iterations_per_segment: int = 4,
        max_iterations_total: int = 24,
        approval_min_ssim: float = 0.75,
        trace: Trace | None = None,
        decisions: dict | None = None,
        approve_all: bool = False,
        margin_s: float = 0.5,
        detect_patterns: bool = False,
    ):
        self.video = Path(video)
        self.workdir = Path(workdir)
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.profile = profile if isinstance(profile, Profile) else get_profile(profile)
        self.job_id = job_id or uuid.uuid4().hex[:12]
        self.max_iter_seg = max_iterations_per_segment
        self.max_iter_total = max_iterations_total
        self.approval_min_ssim = approval_min_ssim
        self.trace = trace or Trace(self.workdir / "trace.jsonl", self.job_id)
        self.decisions = dict(decisions or {})
        self.approve_all = approve_all
        self.margin_s = margin_s
        self.detect_patterns = detect_patterns
        self.state_path = self.workdir / "job.json"
        self.state: dict = {
            "job_id": self.job_id,
            "video": str(self.video),
            "profile": self.profile.name,
            "status": "created",
            "analysis": None,
            "segments": {},  # id -> {status, plan, attempts, candidates, approval}
            "iterations": 0,
            "created": time.time(),
        }
        if self.state_path.exists():
            self.state = json.loads(self.state_path.read_text())
            self.job_id = self.state["job_id"]
            self.trace.log(
                "job",
                "resumed",
                segments={k: v["status"] for k, v in self.state["segments"].items()},
            )
            self._apply_pending_decisions()
        self._analysis_cache: dict[str, dict] = {}

    # ------------------------------------------------------------------ persistence
    def _apply_pending_decisions(self) -> None:
        """On resume, hand each pending approval request its human decision (used once)."""
        for sid, st in self.state["segments"].items():
            if st["status"] != "pending_approval":
                continue
            decision = self.decisions.pop(sid, None)
            if decision is None and self.approve_all:
                opts = (st.get("approval") or {}).get("options") or [{}]
                decision = {
                    "approved": True,
                    "candidate_id": opts[0].get("candidate_id"),
                    "by": "approve_all",
                }
            if decision is None:
                continue
            st["approval"]["decision"] = decision
            self.trace.decision("human_approval", segment_id=sid, decision=decision)
            if decision.get("approved"):
                st["status"] = "open"
            elif st["approval"].get("last_resort"):
                st["status"] = "unresolved"
            else:
                st["status"] = "open"
                st.setdefault("rejected_candidates", []).append(
                    decision.get("candidate_id")
                    or (st["approval"].get("options") or [{}])[0].get("candidate_id")
                )
        self.state["status"] = "analyzed"
        self.save()

    def save(self) -> None:
        self.state_path.write_text(json.dumps(self.state, indent=1, default=str))

    def seg(self, segment_id: str) -> dict:
        try:
            return self.state["segments"][segment_id]
        except KeyError as e:
            raise ToolError(f"unknown segment {segment_id!r}; call analyze_video first") from e

    def _tool(self, name: str, args: dict, fn, *, by: str = "policy"):
        self.trace.tool_call(name, args, iteration=self.state["iterations"], by=by)
        try:
            res = fn()
        except ApprovalPending:
            raise
        except ToolError as e:
            self.trace.tool_result(name, {}, error=str(e), iteration=self.state["iterations"])
            raise
        except Exception as e:
            self.trace.tool_result(
                name, {}, error=f"{type(e).__name__}: {e}", iteration=self.state["iterations"]
            )
            raise ToolError(f"{name} failed: {type(e).__name__}: {e}") from e
        self.trace.tool_result(name, res, iteration=self.state["iterations"])
        self.save()
        return res

    # ------------------------------------------------------------------ tools
    def analyze_video(self, *, by: str = "policy") -> dict:
        def run():
            if self.state["analysis"] is None:
                res, an = analyze_file(
                    str(self.video),
                    profile=self.profile,
                    keep_grid_history=True,
                    return_analyzer=True,
                    detect_patterns=self.detect_patterns,
                )
                self.state["analysis"] = res
                for s in res["segments"]:
                    series = an.region_series(s["regions"][0]) if s["regions"] else []
                    self.state["segments"][s["id"]] = {
                        "segment": s,
                        "status": "open",
                        "plan": None,
                        "attempts": [],
                        "candidates": {},
                        "approval": None,
                        "region_series": _downsample(series, 240),
                        "region_series_t": _downsample(res["timeline"]["t"], 240),
                    }
                self.state["status"] = "analyzed"
            res = self.state["analysis"]
            return {
                "job_id": self.job_id,
                "verdict": res["verdict"],
                "video": {
                    k: res["video"].get(k)
                    for k in (
                        "width",
                        "height",
                        "fps",
                        "frames_analyzed",
                        "duration_analyzed_s",
                        "has_audio",
                    )
                },
                "profile": self.profile.name,
                "segments": [
                    _brief(s, self.state["segments"][s["id"]]["status"]) for s in res["segments"]
                ],
                "strategies": describe(),
            }

        return self._tool("analyze_video", {}, run, by=by)

    def get_segment_detail(self, segment_id: str, *, by: str = "policy") -> dict:
        def run():
            st = self.seg(segment_id)
            s = st["segment"]
            series = st["region_series"]
            applicable = [sp.id for sp in SPECS.values() if s["type"] in sp.applies_to]
            return {
                **s,
                "status": st["status"],
                "duration_s": round(s["end_s"] - s["start_s"], 3),
                "region_area_fraction_of_frame": round(
                    sum(r["w"] * r["h"] for r in s["regions"]), 4
                ),
                "region_luminance": {
                    "t": st["region_series_t"],
                    "L": series,
                    "min": round(min(series), 4) if series else None,
                    "max": round(max(series), 4) if series else None,
                },
                "applicable_strategies": applicable,
                "parameter_hints": parameter_hints(
                    s, self.profile, self.state["analysis"]["video"]["fps"]
                ),
                "attempts": st["attempts"],
                "iterations_left_for_segment": max(0, self.max_iter_seg - len(st["attempts"])),
                "iterations_left_total": max(0, self.max_iter_total - self.state["iterations"]),
            }

        return self._tool("get_segment_detail", {"segment_id": segment_id}, run, by=by)

    def apply_remediation(
        self, segment_id: str, strategy: str, params: dict | None = None, *, by: str = "policy"
    ) -> dict:
        def run():
            st = self.seg(segment_id)
            s = st["segment"]
            if strategy not in SPECS:
                raise ToolError(f"unknown strategy {strategy!r}; choose from {sorted(SPECS)}")
            if s["type"] not in SPECS[strategy].applies_to:
                raise ToolError(f"{strategy} does not apply to {s['type']} hazards")
            if len(st["attempts"]) >= self.max_iter_seg:
                raise BudgetExhausted(f"segment {segment_id}: {self.max_iter_seg} attempts used")
            if self.state["iterations"] >= self.max_iter_total:
                raise BudgetExhausted(f"job: {self.max_iter_total} attempts used")
            self.state["iterations"] += 1
            cand_id = f"{segment_id}-c{len(st['attempts']) + 1}"
            plan = Plan(
                segment_id,
                s["type"],
                s["start_s"],
                s["end_s"],
                s["regions"],
                strategy,
                dict(params or {}),
                margin_s=self.margin_s,
            )
            others = [
                Plan.from_dict(o["plan"])
                for k, o in self.state["segments"].items()
                if k != segment_id and o["status"] == "accepted" and o["plan"]
            ]
            lo = max(0.0, plan.active_start - VERIFY_PAD_S)
            hi = plan.active_end + VERIFY_PAD_S
            out = self.workdir / f"{cand_id}.mp4"
            info = render(
                self.video,
                out,
                others + [plan],
                range_s=(lo, hi),
                quality_for=segment_id,
                keep_audio=False,
            )
            rec = {
                "candidate_id": cand_id,
                "segment_id": segment_id,
                "strategy": strategy,
                "params": info["plans"][-1]["params"],
                "scope": info["plans"][-1]["scope"],
                "path": str(out),
                "range_s": [lo, hi],
                "quality": info["quality"],
                "verified": None,
            }
            st["candidates"][cand_id] = rec
            st["attempts"].append(
                {
                    "candidate_id": cand_id,
                    "strategy": strategy,
                    "params": rec["params"],
                    "verified": None,
                }
            )
            return {k: v for k, v in rec.items() if k != "path"}

        return self._tool(
            "apply_remediation",
            {"segment_id": segment_id, "strategy": strategy, "params": params or {}},
            run,
            by=by,
        )

    def verify_candidate(self, candidate_id: str, *, by: str = "policy") -> dict:
        def run():
            st, rec = self._candidate(candidate_id)
            s = st["segment"]
            res = analyze_file(
                rec["path"], profile=self.profile, detect_patterns=self.detect_patterns
            )
            t0 = rec["range_s"][0]
            same_type = [
                x for x in res["segments"] if x["type"] == s["type"] and x["verdict"] == "fail"
            ]
            other = [
                x for x in res["segments"] if x["type"] != s["type"] and x["verdict"] == "fail"
            ]
            q = rec["quality"] or {}
            spec = SPECS[rec["strategy"]]
            low_quality = (
                q.get("ssim_overall") is not None and q["ssim_overall"] < self.approval_min_ssim
            )
            requires_approval = spec.requires_approval or low_quality
            passes = not same_type
            reason = (
                f"no remaining {s['type']} hazard in the re-analysed segment"
                if passes
                else "still failing: "
                + ", ".join(
                    f"{x['type']} {x['peak_flash_rate_hz']}Hz area {x['max_area_fraction']}"
                    for x in same_type
                )
            )
            v = {
                "candidate_id": candidate_id,
                "verdict": res["verdict"],
                "passes_for_type": passes,
                "remaining_same_type": [_shift(x, t0) for x in same_type],
                "remaining_other_types": [_shift(x, t0) for x in other],
                "quality": q,
                "requires_approval": requires_approval,
                "approval_reason": f"strategy {spec.id} always needs approval"
                if spec.requires_approval
                else (
                    f"ssim {q.get('ssim_overall', 0):.3f} below {self.approval_min_ssim:.2f}"
                    if low_quality
                    else None
                ),
                "reason": reason,
                "opencv": opencv_build_summary()["version"],
            }
            rec["verified"] = v
            for a in st["attempts"]:
                if a["candidate_id"] == candidate_id:
                    a["verified"] = {
                        "passes_for_type": passes,
                        "verdict": res["verdict"],
                        "ssim_overall": q.get("ssim_overall"),
                        "requires_approval": requires_approval,
                    }
            return v

        return self._tool("verify_candidate", {"candidate_id": candidate_id}, run, by=by)

    def request_human_approval(
        self,
        segment_id: str,
        reason: str,
        options: list[dict] | None = None,
        *,
        last_resort: bool = False,
        by: str = "policy",
    ) -> dict:
        def run():
            st = self.seg(segment_id)
            req = {
                "segment_id": segment_id,
                "reason": reason,
                "options": options or [],
                "last_resort": last_resort,
                "requested_at": time.time(),
                "decision": None,
            }
            decision = self.decisions.pop(segment_id, None)
            if decision is None and self.approve_all:
                decision = {
                    "approved": True,
                    "candidate_id": (options or [{}])[0].get("candidate_id"),
                    "by": "approve_all",
                }
            st["approval"] = req
            if decision is not None:
                req["decision"] = decision
                self.trace.decision("human_approval", segment_id=segment_id, decision=decision)
                if decision.get("approved"):
                    st["status"] = "open"
                elif last_resort:
                    st["status"] = "unresolved"
                else:
                    st["status"] = "open"
                    st.setdefault("rejected_candidates", []).append(
                        decision.get("candidate_id") or (options or [{}])[0].get("candidate_id")
                    )
                return {
                    "status": "approved" if decision.get("approved") else "rejected",
                    "decision": decision,
                }
            st["status"] = "pending_approval"
            self.state["status"] = "needs_approval"
            self.save()
            raise ApprovalPending(segment_id, req)

        return self._tool(
            "request_human_approval",
            {
                "segment_id": segment_id,
                "reason": reason,
                "options": options or [],
                "last_resort": last_resort,
            },
            run,
            by=by,
        )

    def accept_candidate(self, candidate_id: str, *, by: str = "policy") -> dict:
        def run():
            st, rec = self._candidate(candidate_id)
            v = rec.get("verified")
            if not v:
                raise ToolError("verify_candidate must run before accept_candidate")
            if not v["passes_for_type"]:
                raise ToolError(
                    "candidate did not pass verification; try another strategy or parameters"
                )
            if v["requires_approval"]:
                appr = st.get("approval") or {}
                d = appr.get("decision") or {}
                if not (d.get("approved") and (d.get("candidate_id") in (None, candidate_id))):
                    raise ToolError(
                        "this candidate needs human approval: call request_human_approval first"
                    )
            plan = Plan(
                st["segment"]["id"],
                st["segment"]["type"],
                st["segment"]["start_s"],
                st["segment"]["end_s"],
                st["segment"]["regions"],
                rec["strategy"],
                rec["params"],
                margin_s=self.margin_s,
            )
            st["plan"] = plan.to_dict()
            st["status"] = "accepted"
            st["accepted_candidate"] = candidate_id
            self.trace.decision(
                "accept",
                segment_id=st["segment"]["id"],
                candidate_id=candidate_id,
                strategy=rec["strategy"],
                params=rec["params"],
            )
            return {
                "ok": True,
                "segment_id": st["segment"]["id"],
                "strategy": rec["strategy"],
                "params": rec["params"],
            }

        return self._tool("accept_candidate", {"candidate_id": candidate_id}, run, by=by)

    def finalize(
        self, output: str | Path, *, by: str = "policy", plot_path: str | Path | None = None
    ) -> dict:
        def run():
            plans = [
                Plan.from_dict(o["plan"])
                for o in self.state["segments"].values()
                if o["status"] == "accepted" and o["plan"]
            ]
            output_p = Path(output)
            output_p.parent.mkdir(parents=True, exist_ok=True)
            before = self.state["analysis"]
            if not plans and not self.state["segments"]:
                shutil.copyfile(self.video, output_p)
                after = before
                info = {"frames": before["video"]["frames_analyzed"], "audio_remuxed": False}
            else:
                info = render(self.video, output_p, plans, keep_audio=True)
                after = analyze_file(
                    str(output_p), profile=self.profile, detect_patterns=self.detect_patterns
                )
            unresolved = [k for k, o in self.state["segments"].items() if o["status"] != "accepted"]
            if after["verdict"] == "fail":
                status = "failed_verification"
            elif unresolved:
                status = (
                    "needs_approval"
                    if any(
                        self.state["segments"][k]["status"] == "pending_approval"
                        for k in unresolved
                    )
                    else "failed_verification"
                )
            elif not self.state["segments"]:
                status = "no_hazards"
            else:
                status = "passed"
            self.state["status"] = status
            self.state["output"] = str(output_p)
            self.state["after"] = {
                "verdict": after["verdict"],
                "segments": after["segments"],
                "per_second": after["per_second"],
            }
            # frame-count / sync check
            n_out = sum(1 for _ in open_video(output_p))
            sync_ok = n_out == before["video"]["frames_analyzed"]
            if plot_path:
                from ..plot import plot_analysis

                plot_analysis(
                    before,
                    plot_path,
                    after=after,
                    title=f"{self.video.name}: before {before['verdict']} / after {after['verdict']}",
                )
            self.trace.decision(
                "finalize",
                status=status,
                after_verdict=after["verdict"],
                frames_out=n_out,
                sync_ok=sync_ok,
            )
            return {
                "status": status,
                "output": str(output_p),
                "after_verdict": after["verdict"],
                "remaining_segments": [_brief(s, "fail") for s in after["segments"]],
                "frames_out": n_out,
                "frames_in": before["video"]["frames_analyzed"],
                "sync_ok": sync_ok,
                "audio_remuxed": info.get("audio_remuxed", False),
                "unresolved": unresolved,
            }

        return self._tool("finalize", {"output": str(output)}, run, by=by)

    # ------------------------------------------------------------------ report
    def report(self, policy: str, runtime_s: float, *, error: str | None = None) -> dict:
        before = self.state.get("analysis") or {}
        segs = []
        qual = []
        for sid, o in self.state["segments"].items():
            acc = o.get("accepted_candidate")
            q = o["candidates"].get(acc, {}).get("quality") if acc else None
            if q:
                qual.append(q)
            segs.append(
                {
                    "segment_id": sid,
                    "type": o["segment"]["type"],
                    "start_s": o["segment"]["start_s"],
                    "end_s": o["segment"]["end_s"],
                    "outcome": {"accepted": "accepted", "pending_approval": "needs_approval"}.get(
                        o["status"], "unresolved"
                    ),
                    "strategy": (o["plan"] or {}).get("strategy"),
                    "params": (o["plan"] or {}).get("params"),
                    "attempts": o["attempts"],
                    "approval": o.get("approval"),
                    "quality": q,
                }
            )
        agg = None
        if qual:
            agg = {
                k: float(np.mean([q[k] for q in qual if q.get(k) is not None]))
                for k in ("ssim_overall", "ssim_inside", "ssim_outside", "mean_abs_dL_inside")
                if any(q.get(k) is not None for q in qual)
            }
        status = self.state.get("status", "error")
        if error:
            status = "error"
        elif status not in ("passed", "failed_verification", "needs_approval", "no_hazards"):
            status = (
                "error"
                if status == "created"
                else "needs_approval"
                if status == "needs_approval"
                else "failed_verification"
            )
        return {
            "schema_version": SCHEMA_VERSION,
            "tool": {
                "name": "steadyframe",
                "version": __version__,
                "opencv": opencv_build_summary(),
            },
            "input": {
                "path": str(self.video),
                **{
                    k: before.get("video", {}).get(k)
                    for k in ("width", "height", "fps", "frames_analyzed", "duration_analyzed_s")
                },
            },
            "output": {"path": self.state.get("output")},
            "policy": policy,
            "status": status,
            "error": error,
            "before": {
                "verdict": before.get("verdict"),
                "segments": before.get("segments", []),
                "per_second": before.get("per_second", []),
            },
            "after": self.state.get("after"),
            "segments": segs,
            "quality": agg,
            "trace_path": str(self.trace.path) if self.trace.path else None,
            "iterations": self.state["iterations"],
            "runtime_s": round(runtime_s, 3),
            "job_id": self.job_id,
            "pending_approvals": [
                o["approval"]
                for o in self.state["segments"].values()
                if o["status"] == "pending_approval"
            ],
        }

    # ------------------------------------------------------------------ helpers
    def _candidate(self, candidate_id: str) -> tuple[dict, dict]:
        for st in self.state["segments"].values():
            if candidate_id in st["candidates"]:
                return st, st["candidates"][candidate_id]
        raise ToolError(f"unknown candidate {candidate_id!r}")

    def open_segments(self) -> list[str]:
        return [k for k, o in self.state["segments"].items() if o["status"] == "open"]


def parameter_hints(seg: dict, profile: Profile, fps: float) -> dict:
    """Physics-based starting points derived from the analyzer's measurements.

    S1 is an EMA; a square wave with half-period N frames keeps a fraction
    (1 - r^N) / (1 + r^N) of its swing, r = 1 - alpha. We solve for the alpha that brings
    max_delta_L under the transition threshold with a 10% margin."""
    target = 0.9 * profile.luminance_delta
    delta = max(seg.get("max_delta_L", 0.0), 1e-3)
    rate = max(seg.get("peak_flash_rate_hz", 3.0), 0.5)
    n = max(1.0, fps / (2.0 * rate))
    need = min(1.0, target / delta)  # required residual fraction
    # residual(r) = (1 - r^n)/(1 + r^n) = need  ->  r^n = (1 - need)/(1 + need)
    rn = (1.0 - need) / (1.0 + need)
    r = rn ** (1.0 / n) if rn > 0 else 0.0
    alpha = round(min(0.6, max(0.02, 1.0 - r)), 3)
    return {
        "required_swing_attenuation": round(need, 3),
        "S1": {
            "alpha": alpha,
            "note": "EMA weight giving the required attenuation at the measured flash rate",
        },
        "S2": {"max_swing": round(min(0.2, max(0.02, target - 0.04)), 3), "mean_alpha": 0.02},
        "S5": {"target_hz": 2.5},
        "prefer_regional": seg.get("max_area_fraction", 1.0) < 1.0
        and sum(r["w"] * r["h"] for r in seg.get("regions", [])) < 0.5,
    }


def _brief(s: dict, status: str) -> dict:
    return {
        k: s[k]
        for k in (
            "id",
            "type",
            "verdict",
            "start_s",
            "end_s",
            "peak_flash_rate_hz",
            "max_area_fraction",
            "max_delta_L",
            "regions",
            "severity_score",
        )
    } | {"status": status}


def _shift(seg: dict, t0: float) -> dict:
    return {**seg, "start_s": round(seg["start_s"] + t0, 3), "end_s": round(seg["end_s"] + t0, 3)}


def _downsample(xs: list, n: int) -> list:
    if len(xs) <= n:
        return list(xs)
    idx = np.linspace(0, len(xs) - 1, n).round().astype(int)
    return [xs[i] for i in idx]
