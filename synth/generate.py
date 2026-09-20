"""Synthetic hazard clip generator with ground truth.

    python -m synth.generate --config synth/suite.yaml --out data/synthetic --seed 1234

Every clip is described in YAML (see suite.yaml). The generator renders the frames with
NumPy/OpenCV, writes them with `steadyframe.io.video.VideoWriter`, and writes a
`<clip>.gt.json` next to it with the expected verdict computed by `synth/reference.py`
(an independent 1-D implementation of the rules) and the analytic area condition.

WARNING: the output is deliberately hazardous flashing content. It is gitignored. Do not
play it in a normal viewer. See data/synthetic/WARNING.md.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
import yaml

from steadyframe import __version__
from steadyframe.io import ffmpeg as ff
from steadyframe.io.video import VideoWriter
from steadyframe.luminance import red_value_scalar, relative_luminance_scalar
from steadyframe.profiles import get_profile
from steadyframe.schema import SCHEMA_VERSION, validate_ground_truth

from . import reference

DEFAULTS = {
    "width": 320,
    "height": 240,
    "fps": 30,
    "duration_s": 5.0,
    "codec": "h264",
    "crf": 18,
    "background": {"kind": "flat", "gray": 40},
    "profile": "wcag",
}

# ------------------------------------------------------------------ colour helpers

_GRAY_L = np.array([relative_luminance_scalar(g, g, g) for g in range(256)])


def gray_for_luminance(L: float, *, side: str = "nearest") -> int:
    """8-bit gray whose relative luminance is nearest to L (or at most / at least L)."""
    if side == "nearest":
        return int(np.argmin(np.abs(_GRAY_L - L)))
    if side == "below":
        cands = np.where(_GRAY_L <= L)[0]
        return int(cands[-1]) if len(cands) else 0
    cands = np.where(_GRAY_L >= L)[0]
    return int(cands[0]) if len(cands) else 255


def pick_gray_pair(
    low_L: float, delta: float, *, above_threshold: bool | None = None, threshold: float = 0.10
) -> tuple[int, int]:
    """Two grays with luminance difference as close to ``delta`` as 8-bit allows.

    If ``above_threshold`` is given, guarantee the *achieved* delta lands on that side of
    ``threshold`` (boundary cases must not be ruined by quantisation)."""
    lo = gray_for_luminance(low_L)
    target = _GRAY_L[lo] + delta
    hi = int(np.argmin(np.abs(_GRAY_L - target)))
    if above_threshold is True:
        while _GRAY_L[hi] - _GRAY_L[lo] < threshold + 1e-9 and hi < 255:
            hi += 1
    elif above_threshold is False:
        while _GRAY_L[hi] - _GRAY_L[lo] >= threshold - 1e-9 and hi > lo:
            hi -= 1
    return lo, hi


def parse_color(spec) -> tuple[int, int, int]:
    """YAML colour -> (r, g, b) 8-bit."""
    if isinstance(spec, int):
        return spec, spec, spec
    if isinstance(spec, (list, tuple)) and len(spec) == 3:
        return int(spec[0]), int(spec[1]), int(spec[2])
    if isinstance(spec, dict) and "L" in spec:
        g = gray_for_luminance(float(spec["L"]))
        return g, g, g
    if isinstance(spec, str):
        named = {
            "black": (0, 0, 0),
            "white": (255, 255, 255),
            "red": (255, 0, 0),
            "darkred": (60, 0, 0),
        }
        return named[spec]
    raise ValueError(f"bad colour {spec!r}")


# ------------------------------------------------------------------ waveforms


def waveform(kind: str, phase: np.ndarray) -> np.ndarray:
    """phase in cycles (float) -> 0..1 modulation."""
    phase = np.round(
        phase, 9
    )  # snap so 0.49999999 from t*f rounding does not shift an edge by a frame
    frac = phase - np.floor(phase)
    if kind == "square":
        return (frac < 0.5).astype(np.float64)
    if kind == "sine":
        return 0.5 - 0.5 * np.cos(2 * np.pi * frac)
    if kind == "ramp":  # sawtooth: slow rise, instant drop
        return frac
    if kind == "triangle":
        return 1.0 - np.abs(2.0 * frac - 1.0)
    raise ValueError(kind)


# ------------------------------------------------------------------ backgrounds


class Background:
    def __init__(self, cfg: dict, w: int, h: int, rng: np.random.Generator):
        self.kind = cfg.get("kind", "flat")
        self.w, self.h = w, h
        self.cfg = cfg
        self.rng = rng
        if self.kind == "flat":
            g = int(cfg.get("gray", 40))
            self.base = np.full((h, w, 3), g, np.uint8)
        elif self.kind == "gradient":
            lo, hi = int(cfg.get("lo", 20)), int(cfg.get("hi", 200))
            ramp = np.linspace(lo, hi, w, dtype=np.float32)
            self.base = np.repeat(np.tile(ramp, (h, 1))[..., None], 3, axis=2).astype(np.uint8)
        elif self.kind in ("texture", "moving"):
            # smooth seeded noise, roughly natural-image statistics (1/f-ish)
            small = rng.random((h // 8 + 2, w // 8 + 2, 3)).astype(np.float32)
            tex = cv2.resize(small, (w * 2, h * 2), interpolation=cv2.INTER_CUBIC)
            tex = cv2.GaussianBlur(tex, (0, 0), 3)
            lo, hi = int(cfg.get("lo", 30)), int(cfg.get("hi", 180))
            tex = (tex - tex.min()) / max(1e-6, tex.max() - tex.min())
            self.big = (lo + tex * (hi - lo)).astype(np.uint8)
            self.base = self.big[:h, :w]
            self.speed = float(cfg.get("speed_px_s", 40.0))
        else:
            raise ValueError(self.kind)

    def frame(self, t: float) -> np.ndarray:
        if self.kind == "moving":
            dx = int(t * self.speed) % self.w
            dy = int(t * self.speed * 0.5) % self.h
            return self.big[dy : dy + self.h, dx : dx + self.w].copy()
        return self.base.copy()


# ------------------------------------------------------------------ events


def region_px(region: dict, w: int, h: int) -> tuple[int, int, int, int]:
    x0 = int(round(region["x"] * w))
    y0 = int(round(region["y"] * h))
    x1 = int(round((region["x"] + region["w"]) * w))
    y1 = int(round((region["y"] + region["h"]) * h))
    return x0, y0, max(x1, x0 + 1), max(y1, y0 + 1)


def render_clip(cfg: dict, out_dir: Path, seed: int, *, force: bool = False) -> dict:
    cfg = {**DEFAULTS, **cfg}
    name = cfg["name"]
    w, h, fps = int(cfg["width"]), int(cfg["height"]), float(cfg["fps"])
    n = int(round(cfg["duration_s"] * fps))
    ext = "mp4"
    path = out_dir / f"{name}.{ext}"
    gt_path = out_dir / f"{name}.gt.json"
    profile = get_profile(cfg["profile"])

    clip_seed = int(hashlib.sha256(f"{seed}:{name}".encode()).hexdigest()[:8], 16)
    rng = np.random.default_rng(clip_seed)
    bg = Background(cfg["background"], w, h, rng)
    times = [i / fps for i in range(n)]

    events = cfg.get("events", [])
    # ideal per-event signals for the reference implementation
    ev_states: list[dict] = []
    for ev in events:
        ev = dict(ev)
        kind = ev.get("kind", "flash")
        if kind == "flash":
            lo_c, hi_c = _flash_colors(ev)
            ev["_lo"], ev["_hi"] = lo_c, hi_c
        ev_states.append(ev)

    frames_written = 0
    if force or not path.exists():
        writer = VideoWriter(path, w, h, fps, codec=cfg["codec"], crf=int(cfg["crf"]))
        for i, t in enumerate(times):
            frame = bg.frame(t)
            for ev in ev_states:
                _apply_event(frame, ev, t, w, h, rng, i)
            writer.write(frame)
            frames_written += 1
        writer.close()

    gt = ground_truth(cfg, ev_states, times, profile)
    gt["clip"] = path.name
    gt["generator"] = {"version": __version__, "seed": seed, "clip_seed": clip_seed}
    validate_ground_truth(gt)
    gt_path.write_text(json.dumps(gt, indent=2))

    variants = []
    for crf in cfg.get("crf_variants", []) or []:
        vpath = out_dir / f"{name}__crf{crf}.mp4"
        if force or not vpath.exists():
            ff.transcode(path, vpath, crf=int(crf), preset="medium")
        vgt = copy.deepcopy(gt)
        vgt["clip"] = vpath.name
        vgt["params"]["variant_crf"] = int(crf)
        (out_dir / f"{name}__crf{crf}.gt.json").write_text(json.dumps(vgt, indent=2))
        variants.append(vpath.name)
    return {
        "clip": path.name,
        "frames": frames_written or n,
        "variants": variants,
        "expected": gt["expected_verdict"],
    }


def _flash_colors(ev: dict) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """Resolve the low/high colours of a flash event, honouring boundary constraints."""
    if "low_L" in ev:
        side = ev.get("delta_side")  # "above" / "below" / None
        lo, hi = pick_gray_pair(
            float(ev["low_L"]),
            float(ev["delta_L"]),
            above_threshold={"above": True, "below": False}.get(side),
        )
        return (lo, lo, lo), (hi, hi, hi)
    return parse_color(ev.get("low", "black")), parse_color(ev.get("high", "white"))


def _apply_event(
    frame: np.ndarray, ev: dict, t: float, w: int, h: int, rng: np.random.Generator, i: int
) -> None:
    kind = ev.get("kind", "flash")
    start, end = float(ev.get("start_s", 0.0)), float(ev.get("end_s", 1e9))
    if not (start <= t < end):
        return
    region = ev.get("region", {"x": 0, "y": 0, "w": 1, "h": 1})
    x0, y0, x1, y1 = region_px(region, w, h)
    if kind == "flash":
        f = float(ev.get("freq_hz", 5.0))
        s = float(waveform(ev.get("waveform", "square"), np.array([(t - start) * f]))[0])
        lo, hi = ev["_lo"], ev["_hi"]
        rgb = tuple(int(round(lo[c] + (hi[c] - lo[c]) * s)) for c in range(3))
        frame[y0:y1, x0:x1] = (rgb[2], rgb[1], rgb[0])
    elif kind == "fill":  # static fill (scene cuts are alternating fills)
        r, g, b = parse_color(ev["color"])
        frame[y0:y1, x0:x1] = (b, g, r)
    elif kind == "fade":  # linear fade between two colours over the event
        a, b_ = parse_color(ev["from"]), parse_color(ev["to"])
        u = (t - start) / max(1e-9, end - start)
        rgb = tuple(int(round(a[c] + (b_[c] - a[c]) * u)) for c in range(3))
        frame[y0:y1, x0:x1] = (rgb[2], rgb[1], rgb[0])
    elif kind == "stripes":  # regular high-contrast pattern
        pairs = int(ev.get("pairs", 8))
        lo, hi = parse_color(ev.get("low", "black")), parse_color(ev.get("high", "white"))
        xs = np.arange(x1 - x0)
        period = max(2, (x1 - x0) // pairs)
        band = ((xs // (period // 2)) % 2).astype(bool)
        row = np.where(band[:, None], np.array(hi[::-1], np.uint8), np.array(lo[::-1], np.uint8))
        if ev.get("orientation", "vertical") == "horizontal":
            ys = np.arange(y1 - y0)
            period = max(2, (y1 - y0) // pairs)
            band = ((ys // (period // 2)) % 2).astype(bool)
            col = np.where(
                band[:, None], np.array(hi[::-1], np.uint8), np.array(lo[::-1], np.uint8)
            )
            frame[y0:y1, x0:x1] = col[:, None, :]
        else:
            frame[y0:y1, x0:x1] = row[None, :, :]
    else:
        raise ValueError(kind)


def _event_signal(
    ev: dict, times: list[float]
) -> tuple[list[float], list[bool], list[float], list[bool]]:
    """Ideal per-frame (L, dark_flag, red_value, red_flag) of the event's region."""
    L, dark, rv, rf = [], [], [], []
    start, end = float(ev.get("start_s", 0.0)), float(ev.get("end_s", 1e9))
    lo, hi = ev["_lo"], ev["_hi"]
    f = float(ev.get("freq_hz", 5.0))
    wf = ev.get("waveform", "square")
    bg_rgb = None
    for t in times:
        if start <= t < end:
            s = float(waveform(wf, np.array([(t - start) * f]))[0])
            rgb = tuple(int(round(lo[c] + (hi[c] - lo[c]) * s)) for c in range(3))
        else:
            rgb = (
                bg_rgb or lo
            )  # outside the event the region shows background; use lo as a stand-in
        L.append(relative_luminance_scalar(*rgb))
        ratio, val = red_value_scalar(*rgb)
        rv.append(val)
        rf.append(ratio >= 0.8)
    dark = [x < 0.80 for x in L]
    return L, dark, rv, rf


def ground_truth(cfg: dict, events: list[dict], times: list[float], profile) -> dict:
    per_sec_type: dict[str, list[str]] = {}
    segments = []
    n_sec = int(times[-1]) + 1 if times else 0
    combined = ["pass"] * n_sec
    expected_type = "none"
    failing_types: set[str] = set()
    for ev in events:
        if ev.get("kind", "flash") != "flash":
            if ev.get("kind") == "stripes" and ev.get("expect_pattern"):
                expected_type = "pattern"
                segments.append(
                    {
                        "type": "pattern",
                        "start_s": float(ev.get("start_s", 0)),
                        "end_s": float(
                            min(
                                ev.get("end_s", times[-1]),
                                times[-1] + 1 / (times[1] - times[0]) if len(times) > 1 else 0,
                            )
                        ),
                        "region": ev.get("region", {"x": 0, "y": 0, "w": 1, "h": 1}),
                    }
                )
            continue
        region = ev.get("region", {"x": 0, "y": 0, "w": 1, "h": 1})
        area = reference.region_window_fraction(region, profile)
        L, dark, rv, rf = _event_signal(ev, times)
        g = reference.evaluate(L, dark, times, area, profile)
        r = reference.evaluate(rv, rf, times, area, profile, red=True)
        for typ, res in (("general", g), ("red", r)):
            ps = reference.per_second(times, res.fail_frames, res.warn_frames)
            cur = per_sec_type.setdefault(typ, ["pass"] * n_sec)
            for s, v in enumerate(ps):
                if v == "fail" or (v == "warn" and cur[s] == "pass"):
                    cur[s] = v
            if any(res.fail_frames):
                failing_types.add(typ)
                fail_t = [t for t, fl in zip(times, res.fail_frames, strict=True) if fl]
                segments.append(
                    {
                        "type": typ,
                        "start_s": float(ev.get("start_s", 0.0)),
                        "end_s": float(min(float(ev.get("end_s", times[-1])), times[-1])),
                        "first_fail_s": round(fail_t[0], 4),
                        "last_fail_s": round(fail_t[-1], 4),
                        "region": region,
                        "flash_rate_hz": float(ev.get("freq_hz", 0.0)),
                        "area_window_fraction": round(area, 4),
                        "delta_L_achieved": round(max(L) - min(L), 4),
                        "dark_state_L": round(min(L), 4),
                    }
                )
    for ps in per_sec_type.values():
        for s, v in enumerate(ps):
            if v == "fail" or (v == "warn" and combined[s] == "pass"):
                combined[s] = v
    if "red" in failing_types:
        expected_type = "red"
    elif "general" in failing_types:
        expected_type = "general"
    verdict = "fail" if "fail" in combined else ("warn" if "warn" in combined else "pass")
    if expected_type == "pattern" and verdict == "pass":
        verdict = "warn"
        combined = [
            "warn"
            if any(
                sg["type"] == "pattern" and sg["start_s"] < s + 1 and sg["end_s"] > s
                for sg in segments
            )
            else c
            for s, c in enumerate(combined)
        ]
    if "expected_verdict" in cfg and cfg["expected_verdict"] != verdict:
        raise AssertionError(
            f"{cfg['name']}: config expects {cfg['expected_verdict']} but the reference says {verdict}"
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "clip": "",
        "params": {k: v for k, v in cfg.items() if k not in ("name",)},
        "expected_verdict": verdict,
        "expected_type": expected_type,
        "expected_types": sorted(failing_types),
        "per_second": combined,
        "per_second_by_type": per_sec_type,
        "segments": segments,
        "boundary_case": cfg.get("boundary_case"),
        "notes": cfg.get("notes", ""),
    }


# ------------------------------------------------------------------ main


def expand_suite(suite: dict) -> list[dict]:
    """Expand `sweep:` blocks into concrete clips."""
    clips: list[dict] = []
    for item in suite["clips"]:
        if "sweep" in item:
            key = item["sweep"]["param"]
            labels = item["sweep"].get("labels") or [
                str(v).replace(".", "p") for v in item["sweep"]["values"]
            ]
            for val, label in zip(item["sweep"]["values"], labels, strict=True):
                c = copy.deepcopy(item)
                c.pop("sweep")
                target = c
                for part in key.split(".")[:-1]:
                    if part.isdigit():
                        target = target[int(part)]
                    else:
                        target = target.setdefault(part, {})
                last = key.split(".")[-1]
                if last.isdigit():
                    target[int(last)] = val
                else:
                    target[last] = val
                c["name"] = f"{item['name']}_{label}"
                clips.append(c)
        else:
            clips.append(copy.deepcopy(item))
    return clips


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--config", default="synth/suite.yaml")
    ap.add_argument("--out", default="data/synthetic")
    ap.add_argument("--seed", type=int, default=1234)
    ap.add_argument("--only", help="substring filter on clip names")
    ap.add_argument("--force", action="store_true", help="re-render even if the file exists")
    args = ap.parse_args(argv)
    suite = yaml.safe_load(Path(args.config).read_text())
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if not (out / "WARNING.md").exists():
        (out / "WARNING.md").write_text(
            Path("data/synthetic/WARNING.md").read_text()
            if Path("data/synthetic/WARNING.md").exists()
            else "# WARNING: flashing content\n"
        )
    clips = expand_suite(suite)
    manifest = []
    for cfg in clips:
        if args.only and args.only not in cfg["name"]:
            continue
        info = render_clip(cfg, out, args.seed, force=args.force)
        manifest.append(info)
        print(f"{info['clip']:45s} {info['expected']:5s} frames={info['frames']}")
    (out / "manifest.json").write_text(
        json.dumps({"seed": args.seed, "config": args.config, "clips": manifest}, indent=2)
    )
    print(f"{len(manifest)} clips -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
