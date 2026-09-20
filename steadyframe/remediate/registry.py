"""Strategy registry. S4 is S1/S2/S3 with a full-frame mask, expressed as scope=global."""

from __future__ import annotations

from dataclasses import replace

from . import s1_temporal, s2_swing, s3_red, s5_hold, s6_card
from .base import Processor, StrategySpec

S4_SPEC = StrategySpec(
    id="S4",
    name="global smoothing",
    invasiveness=3,
    applies_to=("general", "red"),
    scope="global",
    requires_approval=False,
    params={
        "base": {
            "default": "S1",
            "doc": "which regional strategy to apply to the whole frame: S1, S2 or S3",
        },
        **{f"{k}": v for k, v in s1_temporal.SPEC.params.items()},
        **{f"{k}": v for k, v in s2_swing.SPEC.params.items()},
        **{f"{k}": v for k, v in s3_red.SPEC.params.items()},
    },
    doc="S1/S2/S3 applied to the whole frame for large-area hazards",
)

SPECS: dict[str, StrategySpec] = {
    "S1": s1_temporal.SPEC,
    "S2": s2_swing.SPEC,
    "S3": s3_red.SPEC,
    "S4": S4_SPEC,
    "S5": s5_hold.SPEC,
    "S6": s6_card.SPEC,
}

_CLASSES = {
    "S1": s1_temporal.S1,
    "S2": s2_swing.S2,
    "S3": s3_red.S3,
    "S5": s5_hold.S5,
    "S6": s6_card.S6,
}


def make_processor(
    strategy: str, params: dict | None, width: int, height: int, fps: float
) -> tuple[Processor, StrategySpec, dict]:
    spec = SPECS[strategy]
    p = spec.clamp(params)
    if strategy == "S4":
        base = str(p.get("base", "S1"))
        if base not in ("S1", "S2", "S3"):
            raise ValueError(f"S4 base must be S1/S2/S3, got {base}")
        base_spec = SPECS[base]
        bp = base_spec.clamp(p)
        proc = _CLASSES[base](base_spec, bp, width, height, fps)
        return proc, replace(spec, scope="global"), {"base": base, **bp}
    return _CLASSES[strategy](spec, p, width, height, fps), spec, p


def describe() -> list[dict]:
    """Strategy catalogue for the agent prompt and the UI."""
    return [
        {
            "id": s.id,
            "name": s.name,
            "invasiveness": s.invasiveness,
            "applies_to": list(s.applies_to),
            "scope": s.scope,
            "requires_approval": s.requires_approval,
            "params": s.params,
            "doc": s.doc,
        }
        for s in SPECS.values()
    ]
