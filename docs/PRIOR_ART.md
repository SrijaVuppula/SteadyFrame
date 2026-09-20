# Prior art

Detection of photosensitive hazards in video is not new. This table is what we found on
2026-09-20 (details and links in NOTES.md). Our contribution is the closed loop:
localise, choose the least invasive fix, apply, re-verify with the same analyzer, escalate or
ask a human, explain. Nothing more than that is claimed.

| Tool | Licence / access | Detects | Localises in space? | Remediates? | Verifies its own fix? | Notes |
|---|---|---|---|---|---|---|
| Harding FPA (Cambridge Research Systems) | commercial | luminance flash, red flash, patterns | no (frame-level verdict) | no | n/a | broadcast reference implementation of Ofcom / ITU-R BT.1702 |
| PEAT (Trace Center, U. Maryland) | free download, closed source; prohibited for content produced commercially for broadcast, film, home entertainment, games; Windows | luminance flash, red flash | no | no | n/a | based on the PSEe engine (Cambridge Research Systems); last major update 2010s |
| EA IRIS | BSD-3-Clause, C++ on OpenCV (unpinned) | luminance flash, red flash, patterns | no (frame-level CSV) | no | n/a | fails at > 3 flashes/s, "extended failure" at 2-3 flashes/s over 5 s; also an Unreal plugin |
| Apple VideoFlashingReduction | MIT; Swift / MATLAB / Mathematica | flashing risk score | no | yes, global dimming of the whole frame | no | reference for the iOS/macOS "Dim Flashing Lights" setting |
| Flikcer (arXiv 2108.09491) | Chrome extension, research | luminance flash | no | yes, dims/blocks in the browser | no | web video only |
| **SteadyFrame** | Apache-2.0 | luminance flash, red flash, (experimental) patterns | **yes**, per-cell grid, regions per hazard segment | **yes**, six strategies from regional temporal smoothing to a warning card | **yes**, every candidate is re-analysed; whole file re-verified | agent picks strategy and parameters from the analyzer's measurements; human approval for invasive fixes |

## Baseline decision

IRIS is the only open detector with a comparable rule set. It is a C++/vcpkg project and does
not build inside our Python toolchain, so `eval/detection.py` accepts an optional
`--iris-csv-dir` with IRIS output on the same clips and compares per-second verdicts when
present. Without it the detection evaluation is against synthetic ground truth only, and the
report says so.
