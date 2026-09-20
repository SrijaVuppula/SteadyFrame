"""Per-cell transition state machine shared by general and red flash detection.

A *transition* is the accumulated change between successive local extrema of a signal
(WCAG: "adjacent peaks and valleys in a plot ... against time"), counted once when the
change first reaches ``delta`` and at least one of the two extrema satisfies the state
flag (dark for luminance, saturated red for red). Runs reverse with a small hysteresis so
codec noise does not fragment a slow fade.

Everything is vectorised over a grid of cells with NumPy; no per-pixel Python loops.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np


@dataclass
class TransitionEvent:
    t: float
    mask: np.ndarray  # bool grid: cells that completed a transition at time t
    magnitude: np.ndarray  # float grid: |change| for those cells (0 elsewhere)


class TransitionTracker:
    """Streams one grid per frame, emits per-frame transition masks."""

    def __init__(self, shape: tuple[int, int], delta: float, reversal_eps: float):
        self.shape = shape
        self.delta = float(delta)
        self.eps = float(reversal_eps)
        self.direction = np.zeros(shape, dtype=np.int8)  # +1 up, -1 down, 0 unknown
        self.start_ext = np.zeros(shape, dtype=np.float32)  # value at the start of the run
        self.start_flag = np.zeros(shape, dtype=bool)  # state flag at the run start
        self.run_ext = np.zeros(shape, dtype=np.float32)  # most extreme value in the run
        self.run_flag = np.zeros(shape, dtype=bool)  # state flag at run_ext
        self.counted = np.zeros(shape, dtype=bool)  # this run already produced a transition
        self.prev_sign = np.zeros(shape, dtype=np.int8)  # sign of the last counted transition
        self._first = True

    def push(self, value: np.ndarray, flag: np.ndarray, t: float) -> TransitionEvent:
        value = value.astype(np.float32, copy=False)
        if self._first:
            self.start_ext[...] = value
            self.run_ext[...] = value
            self.start_flag[...] = flag
            self.run_flag[...] = flag
            self._first = False
            return TransitionEvent(t, np.zeros(self.shape, bool), np.zeros(self.shape, np.float32))

        d = value - self.run_ext
        up = self.direction == 1
        down = self.direction == -1
        unknown = self.direction == 0

        # Reversal: the signal moved against the run by more than eps (or first movement).
        rev_up = (down & (d > self.eps)) | (unknown & (d > self.eps))
        rev_down = (up & (d < -self.eps)) | (unknown & (d < -self.eps))
        reversed_ = rev_up | rev_down
        if reversed_.any():
            # the old run's extremum becomes the new run's start
            self.start_ext[reversed_] = self.run_ext[reversed_]
            self.start_flag[reversed_] = self.run_flag[reversed_]
            self.run_ext[reversed_] = value[reversed_]
            self.run_flag[reversed_] = flag[reversed_]
            self.counted[reversed_] = False
            self.direction[rev_up] = 1
            self.direction[rev_down] = -1

        # Continue: extend the run extremum in the run direction.
        cont_up = (self.direction == 1) & (value > self.run_ext) & ~reversed_
        cont_down = (self.direction == -1) & (value < self.run_ext) & ~reversed_
        cont = cont_up | cont_down
        if cont.any():
            self.run_ext[cont] = value[cont]
            self.run_flag[cont] = flag[cont]

        # A transition completes when the accumulated swing first reaches delta and either
        # extremum satisfies the state flag.
        swing = np.abs(self.run_ext - self.start_ext)
        ok_flag = self.start_flag | self.run_flag
        new = (~self.counted) & (self.direction != 0) & (swing >= self.delta) & ok_flag
        self.counted |= new
        if new.any():
            self.prev_sign[new] = self.direction[new]
        mag = np.where(new, swing, 0.0).astype(np.float32)
        return TransitionEvent(t, new, mag)


class WindowCounter:
    """Counts per-cell transitions inside a trailing time window using timestamps."""

    def __init__(self, shape: tuple[int, int], window_s: float):
        self.window_s = float(window_s)
        self.count = np.zeros(shape, dtype=np.int32)
        self._events: deque[tuple[float, np.ndarray]] = deque()

    def push(self, ev: TransitionEvent) -> np.ndarray:
        if ev.mask.any():
            self._events.append((ev.t, ev.mask))
            self.count += ev.mask
        # drop events older than the window: (t - window, t]
        cutoff = ev.t - self.window_s + 1e-6  # tolerance for frame-quantised timestamps
        while self._events and self._events[0][0] <= cutoff:
            _, m = self._events.popleft()
            self.count -= m
        return self.count

    def oldest_time(self, cells: np.ndarray, default: float) -> float:
        """Time of the oldest in-window transition touching any of ``cells``."""
        for t, m in self._events:
            if (m & cells).any():
                return t
        return default
