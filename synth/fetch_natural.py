"""Natural footage for eval/natural.py: download, check, transcode, and label with EA IRIS.

    python -m synth.fetch_natural [--freeze] [--only id,id]      (make natural)

For every clip in data/natural.yaml (Wikimedia Commons, openly licensed):

1. download it to data/natural/src/ and check the Commons SHA-1, then the recorded SHA-256;
2. transcode it once to H.264 (data/natural/<id>.mp4, no audio, same size and frame rate,
   near-lossless CRF 14, single-threaded so the output is reproducible) with the pinned ffmpeg
   from imageio-ffmpeg; both tools read this same file;
3. run EA IRIS 1.1.0 (the official Ubuntu example app, BSD-3-Clause) on the transcode in an
   x86-64 Linux container and keep its per-frame CSV and result JSON as the label.

IRIS is checked first against its own expected logs for three of its test videos (fetched from
the IRIS repository at a pinned commit); a mismatch stops the run. `--freeze` writes the
checksums of a first run into data/natural.yaml; afterwards any difference is an error.
Needs Docker for IRIS (IRIS_IMAGE, any x86-64 glibc Linux image; default debian:bookworm-slim).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data" / "natural.yaml"
OUT = ROOT / "data" / "natural"
UA = {"User-Agent": "SteadyFrame-eval/0.1 (github.com/SrijaVuppula/SteadyFrame)"}
IRIS_TESTS = (
    "https://raw.githubusercontent.com/electronicarts/IRIS/"
    "d96978ac1107f3463b77f69a9c1b1ec5d45291a0/test/Iris.Tests/data"
)
IRIS_CHECK = ("3Hz_6s", "2Hz_6s", "flashStripes")
TRANSCODE = ["-an", "-sn", "-map_metadata", "-1", "-c:v", "libx264", "-preset", "medium"]
TRANSCODE += ["-crf", "14", "-pix_fmt", "yuv420p", "-threads", "1", "-x264-params", "threads=1"]


def digest(p: Path, algo: str = "sha256") -> str:
    h = hashlib.new(algo)
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(url: str, dst: Path, tries: int = 8) -> Path:
    """Download once, politely: Wikimedia answers 429 to bursts, so wait as it asks and retry."""
    if dst.exists():
        return dst
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".part")
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
                with tmp.open("wb") as f:
                    shutil.copyfileobj(r, f)
            break
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == tries - 1:
                raise
            time.sleep(float(e.headers.get("Retry-After") or 0) or 30 * (attempt + 1))
    tmp.rename(dst)
    time.sleep(3)  # one file at a time, with a pause, as Wikimedia's robot policy asks
    return dst


def ffmpeg() -> str:
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def transcode(src: Path, dst: Path) -> None:
    if dst.exists():
        return
    tmp = dst.with_name(dst.stem + ".part.mp4")
    subprocess.run(
        [ffmpeg(), "-v", "error", "-y", "-i", str(src), *TRANSCODE, str(tmp)], check=True
    )
    tmp.rename(dst)


# ---------------------------------------------------------------------------- IRIS


def iris_app(spec: dict) -> Path:
    d = OUT / "iris"
    app = d / "IrisApp"
    if not app.exists():
        tgz = fetch(spec["url"], d / Path(spec["url"]).name)
        if digest(tgz) != spec["sha256"]:
            raise SystemExit(f"{tgz.name}: checksum differs from data/natural.yaml")
        with tarfile.open(tgz) as t:
            t.extractall(d, filter="data")
    return app


def run_iris(video: Path) -> tuple[Path, Path]:
    """IRIS on one file; returns (framedata.csv, result.json). The app writes Results/<name>/."""
    image = os.environ.get("IRIS_IMAGE", "debian:bookworm-slim")
    work = OUT / "iris"
    stage = work / "in" / video.name
    stage.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(video, stage)
    res = work / "Results" / video.name
    shutil.rmtree(res, ignore_errors=True)
    cmd = [
        "docker",
        "run",
        "--rm",
        "--platform",
        "linux/amd64",
        "-v",
        f"{work}:/iris",
        "-w",
        "/iris",
    ]
    cmd += [image, "./IrisApp", "-v", f"in/{video.name}", "-j", "true"]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    stage.unlink()
    return res / "framedata.csv", res / "result.json"


def frame_codes(csv_path: Path) -> list[int]:
    """Per-frame IRIS result from the app's CSV: worst of luminance and red (0..3)."""
    rows = [r for r in csv.reader(csv_path.read_text().splitlines()) if r]
    head = [h.strip() for h in rows[0]]
    li, ri = head.index("LuminanceFrameResult"), head.index("RedFrameResult")
    return [max(int(r[li]), int(r[ri])) for r in rows[1:]]


def check_iris() -> list[dict]:
    """Run the app on three IRIS test videos and compare with IRIS's own expected logs."""
    from eval.external import iris_codes

    out = []
    for name in IRIS_CHECK:
        vid = fetch(f"{IRIS_TESTS}/TestVideos/{name}.mp4", OUT / "iris" / "check" / f"{name}.mp4")
        exp = fetch(
            f"{IRIS_TESTS}/ExpectedVideoLogFiles/{name}_RELATIVE.csv",
            OUT / "iris" / "check" / f"{name}_expected.csv",
        )
        got_csv, _ = run_iris(vid)
        got, want = frame_codes(got_csv), iris_codes(exp)
        fail_same = [g == 3 for g in got] == [w == 3 for w in want]
        out.append(
            {
                "video": name,
                "frames": len(got),
                "codes_identical": got == want,
                "flash_fail_frames_identical": fail_same,
                "flash_fail_frames": sum(g == 3 for g in got),
            }
        )
        if not fail_same:
            raise SystemExit(f"IRIS app disagrees with IRIS's expected log on {name}")
    return out


# ---------------------------------------------------------------------------- main


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--freeze", action="store_true", help="record the checksums of this run")
    ap.add_argument("--only", help="comma-separated clip ids")
    a = ap.parse_args(argv)
    man = yaml.safe_load(MANIFEST.read_text())
    only = set(a.only.split(",")) if a.only else None
    iris_app(man["iris"])
    check = check_iris()
    (OUT / "iris_check.json").write_text(json.dumps(check, indent=1))
    print("IRIS app vs IRIS's expected logs:", json.dumps(check))
    frozen = {}
    for c in man["clips"]:
        if only and c["id"] not in only:
            continue
        ext = Path(c["url"]).suffix
        src = fetch(c["url"], OUT / "src" / f"{c['id']}{ext}")
        if digest(src, "sha1") != c["sha1"]:
            raise SystemExit(f"{src.name}: not the Commons file version recorded (sha1)")
        mp4 = OUT / f"{c['id']}.mp4"
        transcode(src, mp4)
        csv_path, res_json = run_iris(mp4)
        shutil.copyfile(csv_path, OUT / f"{c['id']}.iris.csv")
        shutil.copyfile(res_json, OUT / f"{c['id']}.iris.json")
        sums = {
            "sha256": digest(src),
            "mp4_sha256": digest(mp4),
            "iris_sha256": digest(OUT / f"{c['id']}.iris.csv"),
        }
        for k, v in sums.items():
            if c.get(k) and c[k] != v and not a.freeze:
                raise SystemExit(f"{c['id']}: {k} differs from data/natural.yaml")
        frozen[c["id"]] = sums
        verdict = json.loads(res_json.read_text()).get("OverallResult")
        print(f"{c['id']}: {src.stat().st_size / 1e6:.1f} MB, IRIS {verdict}")
    if a.freeze:
        text = MANIFEST.read_text()
        for cid, sums in frozen.items():
            block = re.search(rf"  - id: {re.escape(cid)}\n(?:    .*\n)+", text)
            assert block, cid
            new = block.group(0)
            for k, v in sums.items():
                new = re.sub(rf"    {k}: .*\n", f"    {k}: {v}\n", new)
            text = text.replace(block.group(0), new)
        MANIFEST.write_text(text)
        print(f"froze checksums for {len(frozen)} clips in {MANIFEST.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
