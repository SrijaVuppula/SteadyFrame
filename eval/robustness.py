"""Robustness: verdict stability versus H.264 CRF, analysis grid size, frame rate and
resolution/aspect ratio.

    python -m eval.robustness           -> eval/results/robustness.{md,json} + figures
"""

from __future__ import annotations

import json
import statistics

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from .common import (  # noqa: E402
    RESULTS,
    cached_analysis,
    header,
    interval_iou,
    load_suite,
    md_table,
    write,
)

GRIDS = [(32, 24), (48, 36), (64, 48), (96, 72), (128, 96)]


def crf_section(gts: list[dict]) -> tuple[str, dict]:
    by_base: dict[str, dict] = {}
    for gt in gts:
        by_base.setdefault(gt["_base"], {})["variant" if gt["_variant"] else "base"] = None
    rows = []
    for gt in gts:
        if not gt["_variant"]:
            continue
        base = next(g for g in gts if not g["_variant"] and g["_base"] == gt["_base"])
        r0 = cached_analysis(base["_path"])
        r1 = cached_analysis(gt["_path"])
        ps0 = [s["verdict"] for s in r0["per_second"]]
        ps1 = [s["verdict"] for s in r1["per_second"]]
        agree = sum(a == b for a, b in zip(ps0, ps1, strict=False)) / max(1, len(ps0))
        tiou = []
        for s0 in r0["segments"]:
            c = [s for s in r1["segments"] if s["type"] == s0["type"]]
            tiou.append(
                max(
                    (
                        interval_iou((s["start_s"], s["end_s"]), (s0["start_s"], s0["end_s"]))
                        for s in c
                    ),
                    default=0.0,
                )
            )
        rows.append(
            {
                "clip": gt["clip"],
                "crf": gt["params"].get("variant_crf"),
                "expected": gt["expected_verdict"],
                "got": r1["verdict"],
                "base_got": r0["verdict"],
                "sec_agreement": agree,
                "seg_t_iou": statistics.mean(tiou) if tiou else 1.0,
                "max_delta_shift": abs(
                    max((s["max_delta_L"] for s in r1["segments"]), default=0)
                    - max((s["max_delta_L"] for s in r0["segments"]), default=0)
                ),
            }
        )
    ok = sum(r["got"] == r["expected"] for r in rows)
    md = f"## H.264 compression (CRF)\n\n{ok}/{len(rows)} re-encoded variants keep the expected verdict.\n\n"
    md += md_table(
        rows,
        [
            "clip",
            "crf",
            "expected",
            "got",
            "base_got",
            "sec_agreement",
            "seg_t_iou",
            "max_delta_shift",
        ],
    )
    return md, {"rows": rows, "correct": ok, "total": len(rows)}


def grid_section(gts: list[dict]) -> tuple[str, dict]:
    subset = [
        g
        for g in gts
        if not g["_variant"]
        and (g["clip"].startswith(("b_", "n_", "a_", "r_")) or g["clip"].startswith("m_"))
    ]
    rows = []
    flips = {g: 0 for g in GRIDS}
    per_grid_rtf = {g: [] for g in GRIDS}
    for gt in subset:
        row = {"clip": gt["clip"], "expected": gt["expected_verdict"]}
        for g in GRIDS:
            res = cached_analysis(gt["_path"], grid=g)
            row[f"{g[0]}x{g[1]}"] = res["verdict"] + (
                "" if res["verdict"] == gt["expected_verdict"] else " (!)"
            )
            flips[g] += res["verdict"] != gt["expected_verdict"]
            per_grid_rtf[g].append(res["stats"]["realtime_factor"])
        rows.append(row)
    summary = [
        {
            "grid": f"{g[0]}x{g[1]}",
            "wrong_verdicts": flips[g],
            "of": len(subset),
            "median_rtf": statistics.median(per_grid_rtf[g]),
        }
        for g in GRIDS
    ]
    md = "## Analysis grid size\n\nSame clips analysed with different cell grids (default 64x48). "
    md += "Boundary clips are aligned to the 64x48 grid, so coarser grids can split a region edge across cells; that is the quantisation effect the table exposes.\n\n"
    md += (
        md_table(summary, ["grid", "wrong_verdicts", "of", "median_rtf"], {"median_rtf": "{:.1f}"})
        + "\n"
    )
    md += md_table(rows, ["clip", "expected"] + [f"{g[0]}x{g[1]}" for g in GRIDS])
    fig, ax = plt.subplots(figsize=(6, 3))
    ax.bar([s["grid"] for s in summary], [s["wrong_verdicts"] for s in summary], color="#1c7ed6")
    ax.set_ylabel("wrong verdicts")
    ax.set_title(f"grid sensitivity ({len(subset)} clips)")
    fig.tight_layout()
    fig.savefig(RESULTS / "fig_grid_sensitivity.png", dpi=110)
    plt.close(fig)
    return md, {"summary": summary, "rows": rows}


def fps_res_section(gts: list[dict]) -> tuple[str, dict]:
    rows = []
    for gt in gts:
        if not gt["clip"].startswith("v_") or gt["_variant"]:
            continue
        res = cached_analysis(gt["_path"])
        rows.append(
            {
                "clip": gt["clip"],
                "fps": gt["params"]["fps"],
                "size": f"{gt['params']['width']}x{gt['params']['height']}",
                "expected": gt["expected_verdict"],
                "got": res["verdict"],
                "peak_rate_hz": max(
                    (s["peak_flash_rate_hz"] for s in res["segments"]), default=0.0
                ),
                "rtf": res["stats"]["realtime_factor"],
            }
        )
    md = "## Frame rate, resolution, aspect ratio\n\n" + md_table(
        rows,
        ["clip", "fps", "size", "expected", "got", "peak_rate_hz", "rtf"],
        {"rtf": "{:.1f}", "peak_rate_hz": "{:.1f}"},
    )
    return md, {"rows": rows}


def freq_section(gts: list[dict]) -> tuple[str, dict]:
    rows = []
    for gt in gts:
        if not gt["clip"].startswith("f_sweep") or gt["_variant"]:
            continue
        res = cached_analysis(gt["_path"])
        rows.append(
            {
                "true_hz": gt["params"]["events"][0]["freq_hz"],
                "measured_hz": max(
                    (s["peak_flash_rate_hz"] for s in res["segments"]),
                    default=max(res["timeline"]["general_rate_hz"]),
                ),
                "verdict": res["verdict"],
                "expected": gt["expected_verdict"],
            }
        )
    rows.sort(key=lambda r: r["true_hz"])
    fig, ax = plt.subplots(figsize=(5, 3.2))
    ax.plot([r["true_hz"] for r in rows], [r["measured_hz"] for r in rows], "o-", color="#1c7ed6")
    ax.plot([0, 16], [0, 16], ls=":", color="#868e96")
    ax.axhline(3, color="#d9480f", lw=0.8, ls="--", label="limit 3/s")
    ax.set_xlabel("true flash frequency (Hz)")
    ax.set_ylabel("measured peak flashes/s")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(RESULTS / "fig_frequency_sweep.png", dpi=110)
    plt.close(fig)
    md = "## Frequency sweep\n\n![](fig_frequency_sweep.png)\n\n" + md_table(
        rows,
        ["true_hz", "measured_hz", "expected", "verdict"],
        {"measured_hz": "{:.1f}", "true_hz": "{:.1f}"},
    )
    return md, {"rows": rows}


def main() -> int:
    gts = load_suite(include_variants=True)
    RESULTS.mkdir(parents=True, exist_ok=True)
    md = header("Robustness: compression, grid, fps, resolution")
    data = {}
    for fn in (crf_section, grid_section, fps_res_section, freq_section):
        part, d = fn(gts)
        md += part + "\n"
        data[fn.__name__.replace("_section", "")] = d
    write("robustness", md, data)
    (RESULTS / "robustness_summary.json").write_text(
        json.dumps(
            {
                "crf_correct": data["crf"]["correct"],
                "crf_total": data["crf"]["total"],
                "grid": data["grid"]["summary"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
