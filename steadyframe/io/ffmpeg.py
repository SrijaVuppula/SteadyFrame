"""ffmpeg helpers. The binary comes from imageio-ffmpeg unless STEADYFRAME_FFMPEG is set."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


def ffmpeg_exe() -> str:
    env = os.environ.get("STEADYFRAME_FFMPEG")
    if env:
        return env
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # pragma: no cover - only when the wheel is missing
        exe = shutil.which("ffmpeg")
        if not exe:
            raise RuntimeError(
                "ffmpeg not found; pip install imageio-ffmpeg or set STEADYFRAME_FFMPEG"
            ) from None
        return exe


@dataclass
class ProbeInfo:
    width: int
    height: int
    fps: float
    duration_s: float | None
    has_audio: bool
    codec: str | None
    container: str | None


_STREAM_RE = re.compile(r"Stream #\d+:\d+.*?: Video: (\w+).*?, (\d{2,5})x(\d{2,5})")
_FPS_RE = re.compile(r"(\d+(?:\.\d+)?) fps")
_DUR_RE = re.compile(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)")
_FMT_RE = re.compile(r"Input #0, ([\w,]+), from")


def probe(path: str | Path) -> ProbeInfo:
    """Parse `ffmpeg -i` (there is no ffprobe in the static bundle)."""
    proc = subprocess.run(
        [ffmpeg_exe(), "-hide_banner", "-i", str(path)], capture_output=True, text=True
    )
    err = proc.stderr
    m = _STREAM_RE.search(err)
    if not m:
        raise ValueError(f"no video stream found in {path}")
    codec, w, h = m.group(1), int(m.group(2)), int(m.group(3))
    fps_m = _FPS_RE.search(err)
    fps = float(fps_m.group(1)) if fps_m else 0.0
    dur = None
    dm = _DUR_RE.search(err)
    if dm:
        dur = int(dm.group(1)) * 3600 + int(dm.group(2)) * 60 + float(dm.group(3))
    fm = _FMT_RE.search(err)
    return ProbeInfo(w, h, fps, dur, "Audio:" in err, codec, fm.group(1) if fm else None)


def run(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    cmd = [ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y", *args]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed ({proc.returncode}): {' '.join(cmd)}\n{proc.stderr[-2000:]}"
        )
    return proc


def transcode(
    src: str | Path,
    dst: str | Path,
    *,
    crf: int = 23,
    preset: str = "medium",
    extra: list[str] | None = None,
) -> None:
    """Re-encode video with libx264 (audio copied). Used by the synth compression variants."""
    run(
        [
            "-i",
            str(src),
            "-c:v",
            "libx264",
            "-preset",
            preset,
            "-crf",
            str(crf),
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "copy",
            *(extra or []),
            str(dst),
        ]
    )


def remux_audio(video_only: str | Path, audio_source: str | Path, dst: str | Path) -> bool:
    """Copy the audio stream(s) of ``audio_source`` onto ``video_only``. Returns False if no audio."""
    if not probe(audio_source).has_audio:
        shutil.copyfile(video_only, dst)
        return False
    run(
        [
            "-i",
            str(video_only),
            "-i",
            str(audio_source),
            "-map",
            "0:v:0",
            "-map",
            "1:a?",
            "-c",
            "copy",
            "-shortest",
            str(dst),
        ]
    )
    return True


def extract_frames_cmd(
    path: str | Path,
    width: int,
    height: int,
    *,
    start_s: float | None = None,
    duration_s: float | None = None,
) -> list[str]:
    cmd = [ffmpeg_exe(), "-hide_banner", "-loglevel", "error"]
    if start_s is not None:
        cmd += ["-ss", f"{start_s:.6f}"]
    cmd += ["-i", str(path)]
    if duration_s is not None:
        cmd += ["-t", f"{duration_s:.6f}"]
    cmd += ["-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{width}x{height}", "-"]
    return cmd


def to_json(obj) -> str:
    return json.dumps(obj, indent=2, sort_keys=False)
