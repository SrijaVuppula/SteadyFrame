"""Agent versus fixed policy on the same clips.

    python -m eval.agent_vs_fixed [--provider heuristic|bedrock] [--only substr]

Compares post-verification success, quality retention, iterations per segment, wall-clock
latency and (for Bedrock) tokens and cost. Lists every clip where the agent did worse.

`heuristic` is the deterministic stand-in that follows the same tool protocol and uses the
analyzer's parameter hints; it runs offline and is what CI reproduces. `bedrock` needs AWS
credentials and STEADYFRAME_BEDROCK_MODEL_ID; its results are written to a separate file
and are the ones the report quotes for the live agent.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from steadyframe.agent.providers import load_config, make_provider

from .common import RESULTS, header, load_suite, md_table, write
from .remediation import run


def compare(fixed: dict, agent: dict) -> tuple[list[dict], list[dict]]:
    rows, worse = [], []
    by_clip = {r["clip"]: r for r in agent["rows"]}
    for f in fixed["rows"]:
        a = by_clip.get(f["clip"])
        if a is None:
            continue
        row = {
            "clip": f["clip"],
            "fixed_status": f["status"],
            "agent_status": a["status"],
            "fixed_iter": f["iter_per_seg"],
            "agent_iter": a["iter_per_seg"],
            "fixed_ssim_in": f["ssim_inside"],
            "agent_ssim_in": a["ssim_inside"],
            "fixed_strategies": f["strategies"],
            "agent_strategies": a["strategies"],
            "fixed_runtime_s": f["runtime_s"],
            "agent_runtime_s": a["runtime_s"],
            "agent_turns": (a.get("llm") or {}).get("turns"),
            "agent_tokens": ((a.get("llm") or {}).get("input_tokens") or 0)
            + ((a.get("llm") or {}).get("output_tokens") or 0),
            "agent_fallback": (a.get("llm") or {}).get("fallback"),
        }
        rows.append(row)
        if (
            (a["status"] != "passed" and f["status"] == "passed")
            or (a["ssim_inside"] or 0) < (f["ssim_inside"] or 0) - 0.01
            or a["iter_per_seg"] > f["iter_per_seg"]
        ):
            worse.append(row)
    return rows, worse


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default="heuristic", choices=["heuristic", "bedrock"])
    ap.add_argument("--only")
    args = ap.parse_args(argv)
    gts = load_suite(include_variants=False)
    if args.only:
        gts = [g for g in gts if args.only in g["clip"]]
    RESULTS.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="sf-avf-"))
    fixed = run(gts, "fixed", workroot=root)
    provider = make_provider(args.provider)
    agent = run(gts, "agent", provider=provider, workroot=root)
    cfg = load_config()["bedrock"]
    price_in, price_out = (
        float(cfg.get("price_per_1k_input_usd") or 0),
        float(cfg.get("price_per_1k_output_usd") or 0),
    )
    tokens_in = sum((r.get("llm") or {}).get("input_tokens") or 0 for r in agent["rows"])
    tokens_out = sum((r.get("llm") or {}).get("output_tokens") or 0 for r in agent["rows"])
    cost = tokens_in / 1000 * price_in + tokens_out / 1000 * price_out
    rows, worse = compare(fixed, agent)
    name = "agent_vs_fixed" if args.provider == "heuristic" else "agent_vs_fixed_bedrock"
    label = f"agent[{args.provider}]"
    md = header(f"Agent vs fixed: {args.provider}")
    md += md_table(
        [
            {
                "metric": "post-verify success rate",
                "fixed": fixed["success_rate"],
                label: agent["success_rate"],
            },
            {
                "metric": "mean iterations / segment",
                "fixed": fixed["mean_iterations_per_segment"],
                label: agent["mean_iterations_per_segment"],
            },
            {
                "metric": "mean SSIM inside regions",
                "fixed": fixed["mean_ssim_inside"],
                label: agent["mean_ssim_inside"],
            },
            {
                "metric": "mean SSIM outside regions",
                "fixed": fixed["mean_ssim_outside"],
                label: agent["mean_ssim_outside"],
            },
            {
                "metric": "mean |dL| inside regions",
                "fixed": fixed["mean_dL_inside"],
                label: agent["mean_dL_inside"],
            },
            {
                "metric": "mean runtime per clip (s)",
                "fixed": fixed["mean_runtime_s"],
                label: agent["mean_runtime_s"],
            },
            {
                "metric": "approvals requested",
                "fixed": fixed["approvals_requested"],
                label: agent["approvals_requested"],
            },
            {
                "metric": "model turns (total)",
                "fixed": 0,
                label: sum((r.get("llm") or {}).get("turns") or 0 for r in agent["rows"]),
            },
            {"metric": "tokens in / out", "fixed": "-", label: f"{tokens_in} / {tokens_out}"},
            {"metric": "LLM cost (USD, from config prices)", "fixed": 0.0, label: cost},
            {
                "metric": "fallbacks to fixed policy",
                "fixed": "-",
                label: sum(1 for r in agent["rows"] if (r.get("llm") or {}).get("fallback")),
            },
        ],
        ["metric", "fixed", label],
        {"fixed": "{:.3f}", label: "{:.3f}"},
    )
    md += (
        "\nStrategy usage, fixed: "
        + json.dumps(fixed["strategy_usage"])
        + "; agent: "
        + json.dumps(agent["strategy_usage"])
        + "\n\n"
    )
    if args.provider == "heuristic":
        md += (
            "The heuristic provider is a deterministic stand-in for the model that follows the same tool protocol and uses the "
            "analyzer's parameter hints (`parameter_hints` in `get_segment_detail`). What it shows is the value of "
            "measurement-driven parameter selection and regional-first escalation over fixed defaults, not the value of an LLM. "
            "The live Bedrock comparison is in `agent_vs_fixed_bedrock.md` when it has been run.\n\n"
        )
    md += "## Per clip\n\n" + md_table(
        rows,
        [
            "clip",
            "fixed_status",
            "agent_status",
            "fixed_iter",
            "agent_iter",
            "fixed_ssim_in",
            "agent_ssim_in",
            "fixed_strategies",
            "agent_strategies",
            "agent_turns",
            "agent_fallback",
        ],
        {"fixed_iter": "{:.1f}", "agent_iter": "{:.1f}"},
    )
    md += "\n## Where the agent was worse\n\n"
    md += (
        (
            "\n".join(
                f"- `{w['clip']}`: fixed {w['fixed_status']} ({w['fixed_strategies']}, {w['fixed_iter']:.1f} it/seg, ssim_in {w['fixed_ssim_in']:.3f}) vs agent {w['agent_status']} ({w['agent_strategies']}, {w['agent_iter']:.1f} it/seg, ssim_in {(w['agent_ssim_in'] or 0):.3f})"
                for w in worse
            )
            + "\n"
        )
        if worse
        else "None on this run.\n"
    )
    write(
        name,
        md,
        {
            "provider": args.provider,
            "fixed": {k: v for k, v in fixed.items() if k != "rows"},
            "agent": {k: v for k, v in agent.items() if k != "rows"},
            "rows": rows,
            "worse": worse,
            "cost_usd": cost,
        },
    )
    print(md.split("## Per clip")[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
