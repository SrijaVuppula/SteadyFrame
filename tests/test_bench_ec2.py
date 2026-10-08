"""The EC2 benchmark launcher can't be exercised without AWS; check what it would send."""

from bench.ec2 import CONFIGS, main, user_data

URLS = {
    k: f"https://example.invalid/{k}?X-Amz-Signature=a&b=c"
    for k in ("src_url", "json_url", "buildinfo_url", "log_url")
}


def test_user_data_stock_installs_the_pinned_wheel_and_uploads_results():
    ud = user_data("c7i.xlarge-stock", False, 10, 0.1785, URLS)
    assert ud.startswith("#!/bin/bash")
    assert "{" not in ud.replace("put() {", "").replace("finish() {", "")
    assert '[ "0" = "1" ]' in ud
    assert "--label c7i.xlarge-stock --reps 10 --price-per-hour 0.1785" in ud
    # presigned URLs carry & and must reach curl intact
    assert "'https://example.invalid/json_url?X-Amz-Signature=a&b=c'" in ud
    assert "shutdown -h now" in ud


def test_user_data_cool_keeps_the_ami_opencv():
    ud = user_data("c8g.xlarge-cool", True, 3, None, URLS)
    assert '[ "1" = "1" ]' in ud and "--system-site-packages" in ud
    assert "grep -v -i '^opencv' requirements.lock" in ud
    assert "--price-per-hour" not in ud


def test_dry_run_needs_no_credentials(capsys):
    for cfg in CONFIGS:
        assert main(["--config", cfg, "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "c8g.xlarge (arm64)" in out and "c7i.xlarge (amd64)" in out
