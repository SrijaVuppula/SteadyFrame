"""Verification record, warning track and `steadyframe verify`."""

import json

import pytest

from steadyframe.cli import main
from steadyframe.record import hazard_vtt, record_digest, verify_file, where

from .conftest import square_frames


@pytest.fixture
def fixed(tmp_clip, tmp_path):
    src = tmp_clip(
        square_frames(120, 30, 6.0, size=(96, 72), region=(24, 18, 72, 54), start=1.0),
        codec="h264",
    )
    out = tmp_path / "safe.mp4"
    rc = main(
        [
            "fix",
            str(src),
            "-o",
            str(out),
            "--report",
            str(tmp_path / "report.json"),
            "--record",
            str(tmp_path / "record.json"),
            "--vtt",
            str(tmp_path / "hazards.vtt"),
        ]
    )
    assert rc == 0
    return src, out, json.loads((tmp_path / "record.json").read_text())


def test_record_describes_the_fix(fixed, tmp_path):
    src, out, rec = fixed
    assert rec["kind"] == "steadyframe.verification_record"
    assert rec["result"] == {
        "status": "passed",
        "verdict_before": "fail",
        "verdict_after": "pass",
        "segments_flagged": 1,
        "segments_remaining_after": 0,
    }
    assert rec["input"]["filename"] == src.name and len(rec["input"]["sha256"]) == 64
    assert rec["output"]["filename"] == "safe.mp4"
    assert rec["standard"]["thresholds"]["luminance_delta"] == 0.10
    assert rec["standard"]["thresholds"]["max_flashes_per_window"] == 3
    assert rec["segments"][0]["outcome"] == "accepted" and rec["segments"][0]["strategy"]
    assert rec["as11_uk_dpp_pse"]["PSEPass"] == "Yes"
    assert rec["digest"] == record_digest(rec)
    page = (tmp_path / "record.html").read_text()
    assert "Flash-threshold verification record" in page and rec["digest"] in page
    assert "<video" not in page and "not a certification" in page


def test_verify_holds_for_the_output_and_not_for_anything_else(fixed, tmp_path, capsys):
    src, out, rec = fixed
    assert verify_file(out, rec)["ok"]
    assert main(["verify", str(out), "--record", str(tmp_path / "record.json")]) == 0
    assert "record holds" in capsys.readouterr().out
    # a different file (the hazardous original) fails the hash check
    assert main(["verify", str(src), "--record", str(tmp_path / "record.json")]) == 4
    # an edited record fails its digest and the verdict check
    edited = {**rec, "result": {**rec["result"], "verdict_after": "fail"}}
    res = verify_file(out, edited)
    failed = {c["name"] for c in res["checks"] if not c["ok"]}
    assert failed == {"record digest", "re-analysis verdict"}


def test_warning_track(fixed, tmp_path):
    vtt = (tmp_path / "hazards.vtt").read_text()
    assert vtt.startswith("WEBVTT")
    assert "00:00:01.000 --> " in vtt  # the segment starts with the strobe
    assert "flashes a second" in vtt and "lights ahead, from 0:01.0" in vtt


def test_vtt_cues_do_not_overlap_and_red_is_named():
    segs = [
        {"id": "a", "type": "general", "start_s": 2.0, "end_s": 4.0, "peak_flash_rate_hz": 6.0,
         "regions": [{"x": 0, "y": 0, "w": 1, "h": 1}]},
        {"id": "b", "type": "red", "start_s": 4.5, "end_s": 6.0, "peak_flash_rate_hz": 4.0,
         "regions": [{"x": 0.7, "y": 0.7, "w": 0.2, "h": 0.2}]},
    ]  # fmt: skip
    vtt = hazard_vtt(segs)
    assert "a-ahead" in vtt and "b-ahead" not in vtt  # only 0.5 s between them: no advance cue
    assert "most of the screen" in vtt and "red flashing" in vtt
    assert "bottom-right of the screen" in vtt


def test_where_words():
    assert where([]) == "on screen"
    assert where([{"x": 0.4, "y": 0.4, "w": 0.2, "h": 0.2}]) == "centre of the screen"
    assert where([{"x": 0.0, "y": 0.4, "w": 0.2, "h": 0.2}]) == "left of the screen"
    assert where([{"x": 0.0, "y": 0.0, "w": 0.2, "h": 0.2}]) == "top-left of the screen"


def test_analyze_cli_writes_vtt(tmp_clip, tmp_path):
    p = tmp_clip(square_frames(90, 30, 6.0, start=0.5))
    vtt = tmp_path / "w.vtt"
    assert main(["analyze", str(p), "--quiet", "--vtt", str(vtt)]) == 2
    assert "most of the screen" in vtt.read_text()
