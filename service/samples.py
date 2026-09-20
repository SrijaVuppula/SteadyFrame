"""Sample clips offered by GET /samples.

Three short synthetic clips rendered with the same generator as the test suite
(``synth.generate.render_clip``). They are hazardous by design (two of them flash), so
they are generated, never committed, and copied to ``s3://<bucket>/samples/`` at deploy
time. The metadata below is importable without cv2 (the Lambda needs it); ``generate``
imports the generator lazily.

    python -m service.samples --out infra/.samples
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import threading
from pathlib import Path

SAMPLES: list[dict] = [
    {
        "id": "sample_strobe_region",
        "name": "Region strobe (6 Hz)",
        "description": "A 6 Hz square-wave strobe covering the middle half of the frame from "
        "1 s to 4 s over a flat grey background. Fails the general flash rule; a regional "
        "fix (S1) is enough.",
        "hazard_types": ["general"],
        "duration_s": 5,
        "warning": True,
        "config": {
            "name": "sample_strobe_region",
            "width": 320,
            "height": 240,
            "fps": 30,
            "duration_s": 5.0,
            "background": {"kind": "flat", "gray": 60},
            "events": [
                {
                    "kind": "flash",
                    "freq_hz": 6.0,
                    "waveform": "square",
                    "low_L": 0.05,
                    "delta_L": 0.5,
                    "start_s": 1.0,
                    "end_s": 4.0,
                    "region": {"x": 0.25, "y": 0.25, "w": 0.5, "h": 0.5},
                }
            ],
        },
    },
    {
        "id": "sample_red_strobe",
        "name": "Saturated red strobe (5 Hz)",
        "description": "A 5 Hz strobe between dark grey and saturated red on the right side "
        "of the frame from 1 s to 4 s. Fails the red flash rule.",
        "hazard_types": ["red"],
        "duration_s": 5,
        "warning": True,
        "config": {
            "name": "sample_red_strobe",
            "width": 320,
            "height": 240,
            "fps": 30,
            "duration_s": 5.0,
            "background": {"kind": "flat", "gray": 40},
            "events": [
                {
                    "kind": "flash",
                    "freq_hz": 5.0,
                    "waveform": "square",
                    "low": [40, 40, 40],
                    "high": [255, 20, 20],
                    "start_s": 1.0,
                    "end_s": 4.0,
                    "region": {"x": 0.5, "y": 0.25, "w": 0.4, "h": 0.5},
                }
            ],
        },
    },
    {
        "id": "sample_clean",
        "name": "Clean clip (slow fade)",
        "description": "A three second fade from black to white and a static texture. No "
        "flashes; the analyzer should report no hazards.",
        "hazard_types": [],
        "duration_s": 5,
        "warning": False,
        "config": {
            "name": "sample_clean",
            "width": 320,
            "height": 240,
            "fps": 30,
            "duration_s": 5.0,
            "background": {"kind": "texture", "lo": 30, "hi": 200},
            "events": [
                {
                    "kind": "fade",
                    "from": "black",
                    "to": "white",
                    "start_s": 0.5,
                    "end_s": 3.5,
                    "region": {"x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5},
                }
            ],
        },
    },
]

PUBLIC_FIELDS = ("id", "name", "description", "hazard_types", "duration_s", "warning")
_lock = threading.Lock()


def public(sample: dict) -> dict:
    return {k: sample[k] for k in PUBLIC_FIELDS}


def by_id(sample_id: str) -> dict | None:
    for s in SAMPLES:
        if s["id"] == sample_id:
            return s
    return None


def generate(out_dir: str | Path, *, only: list[str] | None = None, seed: int = 1234) -> list[Path]:
    """Render the sample clips into ``out_dir`` (needs cv2 + the synth package)."""
    from synth.generate import render_clip

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for s in SAMPLES:
        if only and s["id"] not in only:
            continue
        render_clip(dict(s["config"]), out, seed)
        paths.append(out / f"{s['id']}.mp4")
    (out / "WARNING.md").write_text(
        "These clips contain deliberately hazardous flashing content used to demonstrate the "
        "analyzer. Do not play them in a normal viewer.\n"
    )
    return paths


def ensure_local(store) -> None:
    """Local mode: render any sample that is missing from the store."""
    from .core import sample_key

    with _lock:
        missing = [s["id"] for s in SAMPLES if not store.exists(sample_key(s["id"]))]
        if not missing:
            return
        with tempfile.TemporaryDirectory(prefix="steadyframe-samples-") as tmp:
            for p in generate(tmp, only=missing):
                store.put_file(sample_key(p.stem), p, "video/mp4")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="infra/.samples")
    ap.add_argument("--seed", type=int, default=1234)
    args = ap.parse_args(argv)
    for p in generate(args.out, seed=args.seed):
        print(p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
