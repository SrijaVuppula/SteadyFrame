"""Structured decision trace: every tool call, result, model turn and decision goes to a
JSONL file (and to an optional sink such as DynamoDB in the service worker)."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path


class Trace:
    def __init__(
        self,
        path: str | Path | None = None,
        job_id: str = "local",
        sink: Callable[[dict], None] | None = None,
        *,
        append: bool = True,
    ):
        self.path = Path(path) if path else None
        self.job_id = job_id
        self.sink = sink
        self.records: list[dict] = []
        self.t0 = time.time()
        self._seq = 0
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if append and self.path.exists():
                # a resumed job keeps its first-run trace and continues the sequence numbers
                try:
                    last = [line for line in self.path.read_text().splitlines() if line.strip()]
                    if last:
                        self._seq = int(json.loads(last[-1]).get("seq", 0))
                except Exception:
                    pass
            else:
                self.path.write_text("")

    def log(self, kind: str, name: str, **fields) -> dict:
        self._seq += 1
        rec = {
            "seq": self._seq,
            "job_id": self.job_id,
            "t_rel_s": round(time.time() - self.t0, 3),
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "kind": kind,
            "name": name,
            **fields,
        }
        self.records.append(rec)
        if self.path:
            with self.path.open("a") as f:
                f.write(json.dumps(rec, default=_default) + "\n")
        if self.sink:
            try:
                self.sink(rec)
            except Exception as e:  # a broken sink must never break the job
                self.records.append(
                    {"seq": self._seq, "kind": "warning", "name": "trace_sink", "error": str(e)}
                )
        return rec

    def tool_call(
        self, name: str, args: dict, *, iteration: int | None = None, by: str = "policy"
    ) -> dict:
        return self.log("tool_call", name, args=args, iteration=iteration, by=by)

    def tool_result(
        self, name: str, result: dict, *, iteration: int | None = None, error: str | None = None
    ) -> dict:
        return self.log(
            "tool_result", name, result=_summarise(result), error=error, iteration=iteration
        )

    def decision(self, name: str, **fields) -> dict:
        return self.log("decision", name, **fields)

    def model(self, name: str, **fields) -> dict:
        return self.log("model", name, **fields)


def _default(o):
    try:
        import numpy as np

        if isinstance(o, np.generic):
            return o.item()
    except Exception:
        pass
    return str(o)


def _summarise(result: dict, limit: int = 60) -> dict:
    """Keep tool results readable in the trace: truncate long lists."""
    out = {}
    for k, v in (result or {}).items():
        if isinstance(v, list) and len(v) > limit:
            out[k] = {"_truncated": True, "n": len(v), "head": v[:10]}
        elif isinstance(v, dict):
            out[k] = _summarise(v, limit)
        else:
            out[k] = v
    return out
