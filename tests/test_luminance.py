import numpy as np
import pytest

from steadyframe.luminance import (
    downsample,
    red_metrics,
    red_value_scalar,
    relative_luminance,
    relative_luminance_scalar,
    uv_chromaticity,
)


@pytest.mark.parametrize(
    "rgb,expected",
    [
        ((0, 0, 0), 0.0),
        ((255, 255, 255), 1.0),
        ((255, 0, 0), 0.2126),
        ((0, 255, 0), 0.7152),
        ((0, 0, 255), 0.0722),
        ((128, 128, 128), 0.21586),  # hand computed: ((128/255+0.055)/1.055)^2.4
        ((10, 10, 10), 0.003035),  # below the 0.04045 knee: (10/255)/12.92
    ],
)
def test_scalar_reference(rgb, expected):
    assert relative_luminance_scalar(*rgb) == pytest.approx(expected, abs=2e-5)


def test_lut_matches_scalar_and_channel_order():
    rng = np.random.default_rng(0)
    rgb = rng.integers(0, 256, size=(7, 5, 3), dtype=np.uint8)
    bgr = rgb[..., ::-1].copy()
    L = relative_luminance(bgr)
    assert L.dtype == np.float32 and L.shape == (7, 5)
    for y in range(7):
        for x in range(5):
            assert L[y, x] == pytest.approx(
                relative_luminance_scalar(*map(int, rgb[y, x])), abs=1e-5
            )
    # a pure red frame in BGR must give 0.2126, not 0.0722
    red = np.zeros((2, 2, 3), np.uint8)
    red[..., 2] = 255
    assert relative_luminance(red)[0, 0] == pytest.approx(0.2126, abs=1e-5)


def test_red_metrics():
    f = np.zeros((1, 3, 3), np.uint8)
    f[0, 0] = (0, 0, 255)  # pure red (BGR)
    f[0, 1] = (90, 90, 220)  # near red, not saturated
    f[0, 2] = (255, 255, 255)
    ratio, value = red_metrics(f)
    assert ratio[0, 0] == pytest.approx(1.0)
    assert value[0, 0] == pytest.approx(320.0)
    r1, v1 = red_value_scalar(220, 90, 90)
    assert ratio[0, 1] == pytest.approx(r1, abs=1e-4) and r1 < 0.8
    assert value[0, 1] == pytest.approx(v1, abs=1e-2)
    assert ratio[0, 2] == pytest.approx(1 / 3, abs=1e-4)
    assert value[0, 2] == 0.0


def test_uv_white_is_d65():
    f = np.full((1, 1, 3), 255, np.uint8)
    uv = uv_chromaticity(f)[0, 0]
    assert uv[0] == pytest.approx(0.1978, abs=2e-3)
    assert uv[1] == pytest.approx(0.4683, abs=2e-3)


def test_downsample_is_box_average():
    m = np.zeros((4, 4), np.float32)
    m[:2, :2] = 1.0
    g = downsample(m, 2, 2)
    assert g.shape == (2, 2)
    assert g[0, 0] == 1.0 and g[1, 1] == 0.0
