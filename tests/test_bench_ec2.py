"""The EC2 benchmark launcher can't be exercised without AWS; check what it would send."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from bench.ec2 import CONFIGS, COOL_CHECK, COOL_VENV, ROOT, main, user_data

URLS = {
    k: f"https://example.invalid/{k}?X-Amz-Signature=a&b=c"
    for k in ("src_url", "json_url", "buildinfo_url", "log_url")
}


def test_user_data_stock_installs_the_pinned_wheel_and_uploads_results():
    ud = user_data("c7i.xlarge-stock", False, 10, 0.1785, URLS)
    assert ud.startswith("#!/bin/bash")
    assert "{" not in ud.replace("put() {", "").replace("finish() {", "")
    assert '[ "0" = "1" ]' in ud
    assert "python3 -m venv .venv\n" in ud
    assert ".venv/bin/pip install -q -r requirements.lock" in ud
    assert "--label c7i.xlarge-stock --reps 10 --price-per-hour 0.1785" in ud
    # presigned URLs carry & and must reach curl intact
    assert "'https://example.invalid/json_url?X-Amz-Signature=a&b=c'" in ud
    assert "shutdown -h now" in ud


def test_user_data_cool_installs_into_the_vendor_venv():
    ud = user_data("c8g.xlarge-cool", True, 3, None, URLS)
    assert "{" not in ud.replace("put() {", "").replace("finish() {", "")
    assert '[ "1" = "1" ]' in ud
    assert COOL_VENV == "/opt/cool/venvs/python_3.11"
    assert f"COOL_VENV={COOL_VENV}\n" in ud
    assert '. "$COOL_VENV/bin/activate"' in ud and 'PY="$COOL_VENV/bin/python"' in ud
    # no separate venv on top of the system python any more
    assert "--system-site-packages" not in ud
    assert "grep -v -i '^opencv' requirements.lock" in ud
    assert '"$PY" -m pip install -q -r /tmp/req.txt' in ud
    # pinned numpy first, the venv's own numpy back if the AMI's cv2 does not work with it
    assert ud.index('VENV_NUMPY=$("$PY"') < ud.index("-r /tmp/req.txt")
    assert '"$PY" -m pip install -q "numpy==$VENV_NUMPY"' in ud
    assert 'echo "numpy: venv $VENV_NUMPY"' in ud
    assert '"$PY" -m pip install -q -e . --no-deps' in ud
    # the /opt/cool + 5.x check runs after every install and before the benchmark
    assert COOL_CHECK in ud
    assert ud.index("-e . --no-deps") < ud.index(COOL_CHECK) < ud.index('"$PY" -m bench.run')
    assert '"$PY" -m bench.run --out /opt/sf/out --label c8g.xlarge-cool --reps 3\n' in ud
    assert "--price-per-hour" not in ud


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
@pytest.mark.parametrize("cool", [False, True])
def test_user_data_is_valid_bash(cool):
    ud = user_data("c8g.xlarge-cool" if cool else "c8g.xlarge-stock", cool, 10, 0.1, URLS)
    r = subprocess.run(["bash", "-n"], input=ud, text=True, capture_output=True)
    assert r.returncode == 0, r.stderr


def _cool_check(tmp_path, version: str, file: str | None):
    """Run COOL_CHECK against a stand-in cv2 module; file=None keeps its real (tmp) path."""
    src = f"__version__ = {version!r}\n"
    if file:
        src += f"__file__ = {file!r}\n"
    (tmp_path / "cv2.py").write_text(src)
    env = {**os.environ, "PYTHONPATH": str(tmp_path)}
    return subprocess.run(
        [sys.executable, "-c", COOL_CHECK], env=env, text=True, capture_output=True
    )


COOL_CV2 = "/opt/cool/venvs/python_3.11/lib/python3.11/site-packages/cv2/__init__.py"


def test_cool_check_accepts_opencv5_under_opt_cool(tmp_path):
    r = _cool_check(tmp_path, "5.0.0", COOL_CV2)
    assert r.returncode == 0, r.stderr
    assert f"COOL check: cv2 5.0.0 at {COOL_CV2}" in r.stdout


def test_cool_check_fails_when_cv2_is_not_under_opt_cool(tmp_path):
    r = _cool_check(tmp_path, "5.0.0", None)  # e.g. the PyPI wheel in site-packages
    assert r.returncode != 0
    assert "FATAL: cv2 resolves to" in r.stderr and "not under /opt/cool" in r.stderr


def test_cool_check_fails_on_opencv4_under_opt_cool(tmp_path):
    r = _cool_check(tmp_path, "4.10.0", COOL_CV2)
    assert r.returncode != 0
    assert "not OpenCV 5" in r.stderr


def test_dry_run_needs_no_credentials(capsys):
    for cfg in CONFIGS:
        assert main(["--config", cfg, "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "c8g.xlarge (arm64)" in out and "c7i.xlarge (amd64)" in out
    assert "<COOL AMI id from the Marketplace listing: pass --ami>" in out
    assert f"OpenCV: the AMI's, from {COOL_VENV}" in out


def test_dry_run_cool_with_ami(capsys):
    assert main(["--config", "c8g.xlarge-cool", "--dry-run", "--ami", "ami-0123456789abcdef0"]) == 0
    out = capsys.readouterr().out
    assert "config c8g.xlarge-cool: c8g.xlarge (arm64), AMI ami-0123456789abcdef0" in out
    assert "COOL_VENV=/opt/cool/venvs/python_3.11\n" in out
    assert '. "$COOL_VENV/bin/activate"' in out


def test_remote_sh_runs_the_same_cool_setup():
    sh = Path(ROOT, "bench", "remote.sh").read_text()
    assert COOL_CHECK in sh  # same /opt/cool + 5.x check, verbatim
    assert f"COOL_VENV={COOL_VENV}\n" in sh and '. "$COOL_VENV/bin/activate"' in sh
    assert '"numpy==$VENV_NUMPY"' in sh and "--system-site-packages" not in sh
