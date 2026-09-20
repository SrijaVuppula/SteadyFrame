import numpy as np
import pytest

from steadyframe.area import AreaChecker, window_cells
from steadyframe.profiles import get_profile


def test_window_cells_wcag_default_grid():
    p = get_profile("wcag")
    assert window_cells(p, 64, 48) == (21, 16)
    assert window_cells(get_profile("broadcast"), 64, 48) == (64, 48)


def test_fraction_of_aligned_region():
    p = get_profile("wcag")
    ac = AreaChecker(p, 64, 48)
    mask = np.zeros((48, 64), bool)
    mask[10:19, 20:29] = True  # 9x9 = 81 cells of a 336-cell window
    assert ac.max_fraction(mask) == pytest.approx(81 / 336, abs=1e-6)
    assert not ac.exceeds(mask)
    mask[:] = False
    mask[10:21, 20:28] = True  # 8x11 = 88 cells
    assert ac.max_fraction(mask) == pytest.approx(88 / 336, abs=1e-6)
    assert ac.exceeds(mask)


def test_two_distant_regions_do_not_add_up_in_window_mode():
    p = get_profile("wcag")
    ac = AreaChecker(p, 64, 48)
    mask = np.zeros((48, 64), bool)
    mask[0:8, 0:8] = True
    mask[40:48, 56:64] = True
    assert ac.max_fraction(mask) == pytest.approx(64 / 336, abs=1e-6)
    # but they do in screen mode
    ac2 = AreaChecker(get_profile("broadcast"), 64, 48)
    assert ac2.max_fraction(mask) == pytest.approx(128 / (64 * 48), abs=1e-6)


def test_full_frame_is_one():
    ac = AreaChecker(get_profile("wcag"), 64, 48)
    assert ac.max_fraction(np.ones((48, 64), bool)) == pytest.approx(1.0)
    assert ac.max_fraction(np.zeros((48, 64), bool)) == 0.0
