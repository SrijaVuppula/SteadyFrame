"""Threshold profiles. Every number here has a quoted source in docs/STANDARDS.md."""

from __future__ import annotations

from dataclasses import dataclass, field, replace


@dataclass(frozen=True)
class Profile:
    name: str
    # general flash
    luminance_delta: float = 0.10  # WCAG: 10% of maximum relative luminance
    dark_state_max: float = 0.80  # WCAG: darker image below 0.80
    # red flash
    red_saturation_ratio: float = 0.8  # WCAG 2.2: R/(R+G+B) >= 0.8
    red_delta: float = 20.0  # PEAT/IRIS working rule on max(0, R-G-B)*320
    # counting
    window_s: float = 1.0
    max_flashes_per_window: int = 3  # "no more than three flashes"
    # area
    area_fraction: float = 0.25
    area_mode: str = "window"  # "window" (10 degree field) or "screen" (whole frame)
    window_frac_w: float = 341.0 / 1024.0
    window_frac_h: float = 256.0 / 768.0
    # pattern (experimental)
    pattern_min_pairs: int = 5
    pattern_min_contrast: float = 0.2
    pattern_area_fraction: float = 0.25
    pattern_min_duration_s: float = 0.5
    # analysis knobs (not standards, but recorded with results)
    grid_w: int = 64
    grid_h: int = 48
    reversal_eps: float = 0.02  # hysteresis before a run counts as reversed (luminance units)
    red_reversal_eps: float = 4.0  # same, in red-metric units (0..320)
    conservative: bool = False  # warn at exactly max_flashes_per_window
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def max_transitions_per_window(self) -> int:
        return 2 * self.max_flashes_per_window

    def with_grid(self, w: int, h: int) -> Profile:
        return replace(self, grid_w=w, grid_h=h)


WCAG = Profile(
    name="wcag",
    notes=("WCAG 2.2 SC 2.3.1; area is any 341x256 window of a 1024x768 viewport",),
)

BROADCAST = Profile(
    name="broadcast",
    area_mode="screen",
    notes=(
        "Ofcom Annex 1 / ITU-R BT.1702; area is 25% of the whole frame",
        "absolute cd/m2 thresholds approximated with the 0.10 relative-luminance rule",
    ),
)

PROFILES: dict[str, Profile] = {p.name: p for p in (WCAG, BROADCAST)}


def get_profile(
    name: str, *, conservative: bool = False, grid: tuple[int, int] | None = None
) -> Profile:
    try:
        p = PROFILES[name]
    except KeyError as e:
        raise ValueError(f"unknown profile {name!r}; choose from {sorted(PROFILES)}") from e
    if conservative:
        p = replace(p, conservative=True)
    if grid:
        p = p.with_grid(*grid)
    return p
