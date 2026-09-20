"""Deterministic fixed policy: try strategies in a fixed order with default parameters.

Order per hazard type (least to most invasive):
  general: S1, S2, S4, S5, S6      red: S3, S4(base=S3), S5, S6      pattern: S6

This is both the offline fallback and the baseline the agent is compared against."""

from __future__ import annotations

from .tools import BudgetExhausted, Job, ToolError

ORDER = {
    "general": [("S1", {}), ("S2", {}), ("S4", {"base": "S1"}), ("S5", {}), ("S6", {})],
    "red": [("S3", {}), ("S4", {"base": "S3"}), ("S5", {}), ("S6", {})],
    "pattern": [("S6", {})],
}


def run_fixed_policy(job: Job, *, by: str = "fixed") -> None:
    """Resolve every open segment. Raises ApprovalPending when a human is needed."""
    job.analyze_video(by=by)
    for sid in sorted(job.open_segments(), key=lambda k: job.seg(k)["segment"]["start_s"]):
        _resolve_segment(job, sid, by=by)


def _resolve_segment(job: Job, sid: str, *, by: str) -> None:
    st = job.seg(sid)
    detail = job.get_segment_detail(sid, by=by)
    tried = {a["strategy"] for a in detail["attempts"]}
    # a human approved a candidate while we were paused: accept it and stop
    dec = (st.get("approval") or {}).get("decision") or {}
    if dec.get("approved") and dec.get("candidate_id"):
        cand = st["candidates"].get(dec["candidate_id"])
        if cand and (cand.get("verified") or {}).get("passes_for_type"):
            job.accept_candidate(dec["candidate_id"], by=by)
            return
    order = [(s, p) for s, p in ORDER[st["segment"]["type"]] if s not in tried]
    for strategy, params in order:
        try:
            cand = job.apply_remediation(sid, strategy, params, by=by)
        except BudgetExhausted:
            break
        except ToolError as e:
            job.trace.decision("fixed_policy", segment_id=sid, note=f"skip {strategy}: {e}")
            continue
        v = job.verify_candidate(cand["candidate_id"], by=by)
        if not v["passes_for_type"]:
            job.trace.decision(
                "fixed_policy",
                segment_id=sid,
                note=f"{strategy} still fails ({v['reason']}); escalating",
            )
            continue
        if v["requires_approval"]:
            r = job.request_human_approval(
                sid,
                reason=f"{strategy}: {v['approval_reason']}",
                options=[
                    {
                        "candidate_id": cand["candidate_id"],
                        "strategy": strategy,
                        "params": cand["params"],
                        "quality": v["quality"],
                    }
                ],
                by=by,
            )
            if r["status"] != "approved":
                job.trace.decision(
                    "fixed_policy",
                    segment_id=sid,
                    note="rejected by human; trying the next strategy",
                )
                continue
        job.accept_candidate(cand["candidate_id"], by=by)
        return
    # nothing worked inside the budget: ask a human, offering every candidate we have
    cands = list(st["candidates"].values())
    passing = [c for c in cands if (c.get("verified") or {}).get("passes_for_type")]
    opts = [
        {
            "candidate_id": c["candidate_id"],
            "strategy": c["strategy"],
            "params": c["params"],
            "quality": c["quality"],
            "passes": (c.get("verified") or {}).get("passes_for_type"),
        }
        for c in passing + [c for c in cands if c not in passing]
    ]
    r = job.request_human_approval(
        sid,
        reason="no strategy passed verification within the iteration budget"
        if not passing
        else "only candidates that need approval passed verification",
        options=opts,
        last_resort=True,
        by=by,
    )
    if r["status"] == "approved":
        chosen = r["decision"].get("candidate_id") or (
            passing[0]["candidate_id"] if passing else None
        )
        if chosen and (st["candidates"].get(chosen, {}).get("verified") or {}).get(
            "passes_for_type"
        ):
            job.accept_candidate(chosen, by=by)
        else:
            job.trace.decision(
                "fixed_policy",
                segment_id=sid,
                note="approved candidate does not pass; leaving unresolved",
            )
            st["status"] = "unresolved"
    else:
        st["status"] = "unresolved"
