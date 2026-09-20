import numpy as np

from steadyframe.flash import TransitionEvent, TransitionTracker, WindowCounter


def run(values, delta=0.10, eps=0.02, flags=None, fps=30.0):
    tr = TransitionTracker((1, 1), delta, eps)
    out = []
    for i, v in enumerate(values):
        fl = np.array([[True]]) if flags is None else np.array([[flags[i]]])
        ev = tr.push(np.array([[v]], np.float32), fl, i / fps)
        if ev.mask[0, 0]:
            out.append((i, float(ev.magnitude[0, 0])))
    return out


def test_square_wave_counts_every_edge():
    vals = [0.1, 0.6] * 10
    ev = run(vals)
    assert [i for i, _ in ev] == list(range(1, 20))
    assert all(abs(m - 0.5) < 1e-6 for _, m in ev)


def test_ramp_counts_once_not_per_frame():
    vals = list(np.linspace(0.1, 0.7, 20)) + [0.7] * 5
    ev = run(vals)
    assert len(ev) == 1
    # counted at the frame where the accumulated swing first reaches 0.10
    i, mag = ev[0]
    assert np.linspace(0.1, 0.7, 20)[i] - 0.1 >= 0.10 - 1e-6
    assert np.linspace(0.1, 0.7, 20)[i - 1] - 0.1 < 0.10


def test_small_wobble_is_not_a_transition():
    vals = [0.3, 0.38, 0.3, 0.39, 0.3, 0.395]
    assert run(vals) == []


def test_noise_does_not_fragment_a_slow_fade():
    rng = np.random.default_rng(1)
    ramp = np.linspace(0.1, 0.9, 60)
    noisy = ramp + rng.normal(0, 0.004, size=60)  # well under the 0.02 hysteresis
    ev = run(list(noisy))
    assert len(ev) == 1


def test_dark_state_rule():
    # both states above 0.80: no transition even with a 0.15 swing
    vals = [0.82, 0.97] * 6
    assert run(vals, flags=[v < 0.80 for v in vals]) == []
    # darker state at 0.79: counts
    vals = [0.79, 0.95] * 6
    assert len(run(vals, flags=[v < 0.80 for v in vals])) == 11


def test_flag_on_either_extremum_is_enough():
    vals = [0.75, 0.9, 0.75, 0.9]
    flags = [True, False, True, False]
    assert len(run(vals, flags=flags)) == 3


def test_window_counter_drops_old_events():
    wc = WindowCounter((1, 1), 1.0)
    m = np.array([[True]])
    for k in range(7):
        c = wc.push(TransitionEvent(k * 0.15, m, np.ones((1, 1), np.float32)))
    assert c[0, 0] == 7  # 0.0 .. 0.9 all inside (t-1, t]
    c = wc.push(TransitionEvent(1.0, np.array([[False]]), np.zeros((1, 1), np.float32)))
    assert c[0, 0] == 6  # the event at exactly t-1.0 is excluded
    c = wc.push(TransitionEvent(2.5, np.array([[False]]), np.zeros((1, 1), np.float32)))
    assert c[0, 0] == 0


def test_window_counter_oldest_time():
    wc = WindowCounter((1, 2), 1.0)
    wc.push(TransitionEvent(0.2, np.array([[True, False]]), np.zeros((1, 2), np.float32)))
    wc.push(TransitionEvent(0.5, np.array([[False, True]]), np.zeros((1, 2), np.float32)))
    assert wc.oldest_time(np.array([[False, True]]), 9.0) == 0.5
    assert wc.oldest_time(np.array([[True, True]]), 9.0) == 0.2
    assert wc.oldest_time(np.array([[False, False]]), 9.0) == 9.0
