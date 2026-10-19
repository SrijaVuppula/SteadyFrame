"""IRIS label parsing for eval/natural.py (the per-frame CSV the IRIS 1.1.0 app writes)."""

from __future__ import annotations

from eval.natural import iris_label

HEAD = (
    "Frame,TimeStamp,AverageLuminance,FlashAreaLuminance,AverageLuminanceDiff,"
    "AverageLuminanceDiffAcc,AverageRed,FlashAreaRed,AverageRedDiff,AverageRedDiffAcc,"
    "LuminanceTransitions,RedTransitions,LuminanceExtendedFailCount,RedExtendedFailCount,"
    "LuminanceFrameResult,RedFrameResult,PatternArea,PatternDetectedLines,PatternFrameResult"
)


def _row(i: int, t: float, lum: int, red: int) -> str:
    return f"{i},00:00:{t:09.6f},0,0%,0,0,0,0%,0,0,0,0,0,0,{lum},{red},0%,0,0 "


def test_iris_label_takes_the_worst_of_luminance_and_red(tmp_path):
    rows = [HEAD]
    codes = [
        (0, 0),
        (1, 0),
        (0, 3),
        (3, 0),
        (2, 0),
        (0, 0),
    ]  # warning, red fail, flash fail, extended
    for i, (lum, red) in enumerate(codes):
        rows.append(_row(i + 1, i * 0.5, lum, red))
    p = tmp_path / "framedata.csv"
    p.write_text("\n".join(rows) + "\n")
    lab = iris_label(p)
    assert lab["fail"] == [False, False, True, True, False, False]
    assert lab["per_second"] == ["pass", "fail", "pass"]  # frames at 1.0 s and 1.5 s fail
    assert lab["verdict"] == "fail" and lab["extended"] and lab["warning_frames"] == 1
    assert lab["times"][3] == 1.5
