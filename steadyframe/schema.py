"""JSON schemas for analysis.json, remediation report.json and synthetic ground truth."""

from __future__ import annotations

import jsonschema

SCHEMA_VERSION = "1.0"

_BBOX = {
    "type": "object",
    "properties": {
        "x": {"type": "number", "minimum": 0, "maximum": 1},
        "y": {"type": "number", "minimum": 0, "maximum": 1},
        "w": {"type": "number", "minimum": 0, "maximum": 1},
        "h": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["x", "y", "w", "h"],
}

VERDICT = {"type": "string", "enum": ["pass", "warn", "fail"]}

SEGMENT = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "type": {"type": "string", "enum": ["general", "red", "pattern"]},
        "verdict": VERDICT,
        "start_frame": {"type": "integer", "minimum": 0},
        "end_frame": {"type": "integer", "minimum": 0},
        "start_s": {"type": "number", "minimum": 0},
        "end_s": {"type": "number", "minimum": 0},
        "peak_flash_rate_hz": {"type": "number", "minimum": 0},
        "max_area_fraction": {"type": "number", "minimum": 0, "maximum": 1},
        "max_delta_L": {"type": "number", "minimum": 0},
        "regions": {"type": "array", "items": _BBOX},
        "severity_score": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": [
        "id",
        "type",
        "verdict",
        "start_frame",
        "end_frame",
        "start_s",
        "end_s",
        "peak_flash_rate_hz",
        "max_area_fraction",
        "max_delta_L",
        "regions",
        "severity_score",
    ],
}

ANALYSIS_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "SteadyFrame analysis",
    "type": "object",
    "properties": {
        "schema_version": {"type": "string"},
        "tool": {"type": "object"},
        "video": {"type": "object"},
        "profile": {"type": "object"},
        "verdict": VERDICT,
        "per_second": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "second": {"type": "integer", "minimum": 0},
                    "verdict": VERDICT,
                    "general": VERDICT,
                    "red": VERDICT,
                    "pattern": VERDICT,
                    "max_flash_rate_hz": {"type": "number"},
                    "max_area_fraction": {"type": "number"},
                },
                "required": ["second", "verdict", "general", "red"],
            },
        },
        "segments": {"type": "array", "items": SEGMENT},
        "timeline": {"type": "object"},
        "stats": {"type": "object"},
    },
    "required": ["schema_version", "tool", "video", "profile", "verdict", "per_second", "segments"],
}

GROUND_TRUTH_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "SteadyFrame synthetic ground truth",
    "type": "object",
    "properties": {
        "schema_version": {"type": "string"},
        "clip": {"type": "string"},
        "generator": {"type": "object"},
        "params": {"type": "object"},
        "expected_verdict": VERDICT,
        "expected_type": {"type": "string", "enum": ["none", "general", "red", "pattern"]},
        "per_second": {"type": "array", "items": VERDICT},
        "segments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string"},
                    "start_s": {"type": "number"},
                    "end_s": {"type": "number"},
                    "region": _BBOX,
                    "flash_rate_hz": {"type": "number"},
                },
                "required": ["type", "start_s", "end_s", "region"],
            },
        },
        "boundary_case": {"type": ["string", "null"]},
        "notes": {"type": "string"},
    },
    "required": [
        "schema_version",
        "clip",
        "params",
        "expected_verdict",
        "expected_type",
        "per_second",
        "segments",
    ],
}

REPORT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "SteadyFrame remediation report",
    "type": "object",
    "properties": {
        "schema_version": {"type": "string"},
        "tool": {"type": "object"},
        "input": {"type": "object"},
        "output": {"type": "object"},
        "policy": {"type": "string"},
        "status": {
            "type": "string",
            "enum": ["passed", "failed_verification", "needs_approval", "no_hazards", "error"],
        },
        "before": {"type": "object"},
        "after": {"type": ["object", "null"]},
        "segments": {"type": "array"},
        "quality": {"type": ["object", "null"]},
        "trace_path": {"type": ["string", "null"]},
        "iterations": {"type": "integer"},
        "runtime_s": {"type": "number"},
    },
    "required": [
        "schema_version",
        "tool",
        "input",
        "policy",
        "status",
        "before",
        "segments",
        "iterations",
        "runtime_s",
    ],
}


def validate_analysis(doc: dict) -> None:
    jsonschema.validate(doc, ANALYSIS_SCHEMA)


def validate_ground_truth(doc: dict) -> None:
    jsonschema.validate(doc, GROUND_TRUTH_SCHEMA)


def validate_report(doc: dict) -> None:
    jsonschema.validate(doc, REPORT_SCHEMA)
