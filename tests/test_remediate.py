import math
import subprocess

import numpy as np
import pytest

from steadyframe.analyzer import analyze_file
from steadyframe.io import ffmpeg as ff
from steadyframe.io.video import open_video
from steadyframe.luminance import relative_luminance
from steadyframe.remediate import quality
from steadyframe.remediate.mask import blend, region_mask
from steadyframe.remediate.registry import SPECS, describe, make_processor
from steadyframe.remediate.renderer import Plan, render

from .conftest import square_frames


def swing(frames, region=None, skip=60):
    """Steady-state peak-to-peak mean luminance (skips the EMA warm-up transient, which
    the analyzer would count as a single slow transition)."""
    Ls = []
    for f in frames:
        L = relative_luminance(f)
        Ls.append(
            float(
                L.mean()
                if region is None
                else L[region[1] : region[3], region[0] : region[2]].mean()
            )
        )
    return max(Ls[skip:]) - min(Ls[skip:])


def run_proc(strategy, params, frames, fps=30):
    h, w = frames[0].shape[:2]
    proc, spec, p = make_processor(strategy, params, w, h, fps)
    return [proc.process(f, i / fps, True) for i, f in enumerate(frames)]


def test_registry_describe_lists_all_six():
    ids = [d["id"] for d in describe()]
    assert ids == ["S1", "S2", "S3", "S4", "S5", "S6"]
    assert SPECS["S6"].requires_approval and not SPECS["S1"].requires_approval
    assert SPECS["S1"].clamp({"alpha": 5.0})["alpha"] == 0.6  # clamped to max
    assert SPECS["S1"].clamp({"bogus": 1}) == {"alpha": 0.1}


def test_s1_attenuates_a_6hz_strobe_as_predicted():
    frames = square_frames(150, 30, 6.0, lo=(30, 30, 30), hi=(200, 200, 200))
    before = swing(frames)
    out = run_proc("S1", {"alpha": 0.1}, frames)
    after = swing(out)
    r, n = 0.9, 2.5
    predicted = before * (1 - r**n) / (1 + r**n)
    assert after < 0.1 < before
    assert after == pytest.approx(predicted, rel=0.3)


def test_s2_keeps_swing_under_threshold():
    frames = square_frames(210, 30, 6.0, lo=(30, 30, 30), hi=(200, 200, 200))
    out = run_proc("S2", {}, frames)
    # the running mean (alpha 0.02) takes ~3 s to settle; the settling drift is one slow
    # transition for the analyzer, so measure the steady state
    assert swing(out, skip=120) < 0.1


def test_s3_desaturates_red_but_keeps_luminance():
    frames = square_frames(60, 30, 5.0, lo=(0, 0, 60), hi=(0, 0, 255))
    out = run_proc("S3", {"strength": 1.0}, frames)
    from steadyframe.luminance import red_metrics

    ratio, _ = red_metrics(out[1])
    assert ratio.max() < 0.8
    assert relative_luminance(out[1]).mean() == pytest.approx(
        relative_luminance(frames[1]).mean(), abs=0.01
    )


def test_s4_is_global_variant_of_base():
    proc, spec, p = make_processor("S4", {"base": "S2", "max_swing": 0.05}, 64, 48, 30)
    assert spec.scope == "global" and p["base"] == "S2" and p["max_swing"] == 0.05
    with pytest.raises(ValueError):
        make_processor("S4", {"base": "S5"}, 64, 48, 30)


def test_s5_holds_frames_to_target_rate():
    frames = square_frames(90, 30, 15.0)
    out = run_proc("S5", {"target_hz": 2.5}, frames)
    changes = sum(1 for a, b in zip(out[:-1], out[1:], strict=True) if not np.array_equal(a, b))
    assert changes <= 2 * 2.5 * 3 + 1  # at most 2*target_hz changes per second over 3 s


def test_s6_card_has_text_and_passes_frames_outside():
    frames = square_frames(10, 30, 6.0)
    h, w = frames[0].shape[:2]
    proc, _, _ = make_processor("S6", {}, w, h, 30)
    card = proc.process(frames[0], 0.0, True)
    assert card.std() > 0  # text drawn
    assert np.array_equal(proc.process(frames[1], 0.1, False), frames[1])


def test_region_mask_keeps_region_interior_at_one_and_feathers_outward():
    m = region_mask([{"x": 0.25, "y": 0.25, "w": 0.5, "h": 0.5}], 200, 100)
    assert m[25:75, 50:150].min() >= 0.99
    assert m[0, 0] < 0.01
    assert 0.0 < m[24, 100] < 1.0 or m[20, 100] < m[26, 100]
    assert region_mask([{"x": 0, "y": 0, "w": 1, "h": 1}], 20, 10).min() == 1.0


def test_blend_weights():
    a = np.zeros((2, 2, 3), np.uint8)
    b = np.full((2, 2, 3), 200, np.uint8)
    m = np.ones((2, 2), np.float32)
    assert blend(a, b, m, 0.0) is a
    assert blend(a, b, m, 0.5)[0, 0, 0] == 100
    assert blend(a, b, m, 1.0)[0, 0, 0] == 200


# ---------------------------------------------------------------- quality


def _ssim_reference(a, b):
    """Slow NumPy SSIM with an explicit 11x11 Gaussian window (sigma 1.5), 'valid' region."""
    a = a.astype(np.float64)
    b = b.astype(np.float64)
    x = np.arange(-5, 6)
    g = np.exp(-(x**2) / (2 * 1.5**2))
    g /= g.sum()
    win = np.outer(g, g)
    H, W = a.shape

    def filt(img):
        out = np.zeros((H - 10, W - 10))
        for i in range(H - 10):
            for j in range(W - 10):
                out[i, j] = (img[i : i + 11, j : j + 11] * win).sum()
        return out

    mu_a, mu_b = filt(a), filt(b)
    saa, sbb, sab = filt(a * a) - mu_a**2, filt(b * b) - mu_b**2, filt(a * b) - mu_a * mu_b
    C1, C2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    return (
        ((2 * mu_a * mu_b + C1) * (2 * sab + C2)) / ((mu_a**2 + mu_b**2 + C1) * (saa + sbb + C2))
    ).mean()


def test_ssim_matches_reference_and_identity():
    rng = np.random.default_rng(3)
    a = rng.integers(0, 256, size=(40, 40), dtype=np.uint8)
    b = np.clip(a.astype(int) + rng.integers(-30, 30, size=(40, 40)), 0, 255).astype(np.uint8)
    ours = quality.ssim_map(a, b)[5:-5, 5:-5].mean()
    assert ours == pytest.approx(_ssim_reference(a, b), abs=2e-3)
    abgr = np.repeat(a[..., None], 3, axis=2)
    assert quality.ssim(abgr, abgr) == pytest.approx(1.0, abs=1e-6)
    assert math.isinf(quality.psnr(abgr, abgr))
    assert quality.psnr(abgr, np.repeat(b[..., None], 3, axis=2)) < 30


def test_quality_accumulator_outside_untouched():
    frames = square_frames(30, 30, 6.0, size=(64, 48), region=(16, 12, 48, 36))
    mask = np.zeros((48, 64), np.float32)
    mask[12:36, 16:48] = 1.0
    q = quality.QualityAccumulator(region_mask=mask)
    for f in frames:
        g = f.copy()
        g[12:36, 16:48] = 100
        q.push(f, g)
    s = q.summary()
    assert s["ssim_outside"] == pytest.approx(1.0, abs=1e-6)
    assert s["psnr_outside_is_lossless"] is True
    assert s["mean_abs_dL_inside"] > 0.05
    assert (
        s["temporal_step_after"] == 0.0 and s["temporal_smoothness_gain"] is None
    )  # constant inside


# ---------------------------------------------------------------- renderer


def test_render_preserves_frames_and_fixes_segment(tmp_clip, tmp_path):
    frames = square_frames(120, 30, 6.0, size=(96, 72), region=(24, 18, 72, 54), start=1.0)
    src = tmp_clip(frames, codec="h264")
    before = analyze_file(str(src))
    seg = before["segments"][0]
    plan = Plan(
        seg["id"], "general", seg["start_s"], seg["end_s"], seg["regions"], "S1", {"alpha": 0.08}
    )
    dst = tmp_path / "out.mp4"
    info = render(src, dst, [plan], quality_for=seg["id"])
    assert info["frames"] == 120
    assert sum(1 for _ in open_video(dst)) == 120
    assert info["quality"]["ssim_outside"] > 0.99
    after = analyze_file(str(dst))
    assert after["verdict"] == "pass"
    # first frames (before the plan's margin) are untouched apart from codec noise
    a = next(iter(open_video(src)))[2]
    b = next(iter(open_video(dst)))[2]
    assert np.abs(a.astype(int) - b.astype(int)).mean() < 3


def test_render_range_and_plan_weights(tmp_clip, tmp_path):
    frames = square_frames(90, 30, 6.0)
    src = tmp_clip(frames)
    plan = Plan(
        "x",
        "general",
        1.0,
        2.0,
        [{"x": 0, "y": 0, "w": 1, "h": 1}],
        "S5",
        {},
        margin_s=0.5,
        fade_s=0.25,
    )
    assert (
        plan.weight(0.4) == 0.0
        and plan.weight(0.625) == pytest.approx(0.5)
        and plan.weight(1.5) == 1.0
    )
    assert plan.weight(2.5) == 0.0 and plan.weight(2.375) == pytest.approx(0.5)
    info = render(src, tmp_path / "c.mp4", [plan], range_s=(0.5, 2.5), keep_audio=False)
    assert info["frames"] == 60 and info["t0"] == pytest.approx(0.5)


def test_audio_is_remuxed_and_in_sync(tmp_clip, tmp_path):
    frames = square_frames(90, 30, 6.0)
    silent = tmp_clip(frames, codec="h264")
    with_audio = tmp_path / "audio.mp4"
    subprocess.run(
        [
            ff.ffmpeg_exe(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(silent),
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=3",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-shortest",
            str(with_audio),
        ],
        check=True,
    )
    assert ff.probe(with_audio).has_audio
    plan = Plan("x", "general", 0.0, 3.0, [{"x": 0, "y": 0, "w": 1, "h": 1}], "S1", {"alpha": 0.08})
    dst = tmp_path / "out.mp4"
    info = render(with_audio, dst, [plan])
    assert info["audio_remuxed"] is True
    p = ff.probe(dst)
    assert p.has_audio
    assert sum(1 for _ in open_video(dst)) == 90
    assert p.duration_s == pytest.approx(3.0, abs=1 / 30 + 0.05)
