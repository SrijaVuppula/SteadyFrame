import json

from steadyframe.cli import main

from .conftest import square_frames


def test_analyze_cli_writes_json_and_plot(tmp_clip, tmp_path, capsys):
    p = tmp_clip(square_frames(90, 30, 6.0, start=0.5))
    out = tmp_path / "a.json"
    png = tmp_path / "a.png"
    rc = main(["analyze", str(p), "--json", str(out), "--plot", str(png)])
    assert rc == 2  # fail -> exit code 2
    doc = json.loads(out.read_text())
    assert doc["verdict"] == "fail" and doc["schema_version"] == "1.0"
    assert doc["tool"]["opencv"]["version"].startswith("5.")
    assert png.exists() and png.stat().st_size > 1000
    assert "FAIL" in capsys.readouterr().out


def test_analyze_cli_pass(tmp_clip):
    p = tmp_clip(square_frames(60, 30, 1.0))
    assert main(["analyze", str(p), "--quiet"]) == 0
