"""Frame readers and writers.

``open_video`` returns a reader yielding ``(index, t_seconds, frame_bgr)``. The default
backend is ``cv2.VideoCapture`` (OpenCV 5's bundled FFmpeg); if it cannot open the file or
returns no frames we fall back to an ffmpeg rawvideo pipe. Timestamps come from the decoder
(CAP_PROP_POS_MSEC) when they are monotonic, else ``index / fps``.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from . import ffmpeg as ff


@dataclass
class VideoMeta:
    path: str
    width: int
    height: int
    fps: float
    frame_count: int | None
    duration_s: float | None
    has_audio: bool
    backend: str
    codec: str | None = None
    container: str | None = None

    def to_dict(self) -> dict:
        return self.__dict__.copy()


class _CvReader:
    backend = "opencv"

    def __init__(self, path: Path, meta_hint: ff.ProbeInfo | None):
        self.cap = cv2.VideoCapture(str(path))
        if not self.cap.isOpened():
            raise OSError("cv2.VideoCapture could not open the file")
        w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = float(self.cap.get(cv2.CAP_PROP_FPS)) or (meta_hint.fps if meta_hint else 0.0)
        n = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if w <= 0 or h <= 0 or fps <= 0:
            raise OSError("cv2.VideoCapture returned no geometry")
        self.meta = VideoMeta(
            path=str(path),
            width=w,
            height=h,
            fps=fps,
            frame_count=n if n > 0 else None,
            duration_s=(n / fps) if n > 0 else (meta_hint.duration_s if meta_hint else None),
            has_audio=meta_hint.has_audio if meta_hint else False,
            backend=self.backend,
            codec=meta_hint.codec if meta_hint else None,
            container=meta_hint.container if meta_hint else None,
        )

    def __iter__(self) -> Iterator[tuple[int, float, np.ndarray]]:
        idx = 0
        last_t = -1.0
        use_pts = True
        while True:
            ok, frame = self.cap.read()
            if not ok or frame is None:
                break
            t_idx = idx / self.meta.fps
            t = t_idx
            if use_pts:
                # After read(), CAP_PROP_POS_MSEC is the presentation time of the frame just
                # decoded (checked against the FFmpeg backend of the 5.0 wheel). Trust it only
                # while it stays monotonic and close to index/fps; otherwise fall back for good.
                pts = self.cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
                if pts > last_t and abs(pts - t_idx) < 1.0:
                    t = pts
                elif idx > 0:
                    use_pts = False
            if t <= last_t:
                t = t_idx
            last_t = t
            yield idx, t, frame
            idx += 1
        self.cap.release()

    def close(self):
        self.cap.release()


class _PipeReader:
    backend = "ffmpeg-pipe"

    def __init__(self, path: Path, info: ff.ProbeInfo):
        self.path = path
        if info.fps <= 0:
            raise OSError("ffmpeg could not determine fps")
        self.meta = VideoMeta(
            path=str(path),
            width=info.width,
            height=info.height,
            fps=info.fps,
            frame_count=int(round(info.duration_s * info.fps)) if info.duration_s else None,
            duration_s=info.duration_s,
            has_audio=info.has_audio,
            backend=self.backend,
            codec=info.codec,
            container=info.container,
        )
        self.proc: subprocess.Popen | None = None

    def __iter__(self) -> Iterator[tuple[int, float, np.ndarray]]:
        w, h = self.meta.width, self.meta.height
        cmd = ff.extract_frames_cmd(self.path, w, h)
        self.proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=10**7
        )
        assert self.proc.stdout is not None
        nbytes = w * h * 3
        idx = 0
        while True:
            buf = self.proc.stdout.read(nbytes)
            if len(buf) < nbytes:
                break
            frame = np.frombuffer(buf, np.uint8).reshape(h, w, 3)
            yield idx, idx / self.meta.fps, frame
            idx += 1
        self.proc.stdout.close()
        self.proc.wait()

    def close(self):
        if self.proc and self.proc.poll() is None:
            self.proc.kill()


def open_video(path: str | Path, *, backend: str = "auto"):
    """Return a reader with ``.meta`` and iteration over ``(idx, t, frame)``."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    info = None
    try:
        info = ff.probe(path)
    except Exception:
        pass
    if backend in ("auto", "opencv"):
        try:
            return _CvReader(path, info)
        except OSError:
            if backend == "opencv":
                raise
    if info is None:
        info = ff.probe(path)
    return _PipeReader(path, info)


class VideoWriter:
    """Writes BGR frames. ``codec='h264'`` pipes to ffmpeg/libx264, ``'lossless'`` to libx264rgb
    (pixel exact), ``'mp4v'`` uses cv2.VideoWriter directly."""

    def __init__(
        self,
        path: str | Path,
        width: int,
        height: int,
        fps: float,
        *,
        codec: str = "h264",
        crf: int = 18,
        preset: str = "veryfast",
    ):
        self.path = Path(path)
        self.width, self.height, self.fps = int(width), int(height), float(fps)
        self.codec = codec
        self.count = 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if codec in ("h264", "lossless"):
            if codec == "h264":
                enc = [
                    "-c:v",
                    "libx264",
                    "-preset",
                    preset,
                    "-crf",
                    str(crf),
                    "-pix_fmt",
                    "yuv420p",
                ]
            else:  # pixel-exact RGB h264 (libx264rgb, crf 0); decodes through cv2 with zero error
                enc = ["-c:v", "libx264rgb", "-preset", preset, "-crf", "0"]
            cmd = [
                ff.ffmpeg_exe(),
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "bgr24",
                "-s",
                f"{self.width}x{self.height}",
                "-r",
                f"{self.fps:.6f}",
                "-i",
                "-",
                "-an",
                *enc,
                "-movflags",
                "+faststart",
                str(self.path),
            ]
            self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
            self.cv = None
        elif codec in ("mp4v", "raw"):
            fourcc = cv2.VideoWriter_fourcc(*("mp4v" if codec == "mp4v" else "FFV1"))
            self.cv = cv2.VideoWriter(str(self.path), fourcc, self.fps, (self.width, self.height))
            if not self.cv.isOpened():
                raise OSError(f"cv2.VideoWriter could not open {self.path}")
            self.proc = None
        else:
            raise ValueError(f"unknown codec {codec}")

    def write(self, frame: np.ndarray) -> None:
        if frame.shape[1] != self.width or frame.shape[0] != self.height:
            raise ValueError("frame size mismatch")
        if frame.dtype != np.uint8:
            frame = np.clip(frame, 0, 255).astype(np.uint8)
        if self.proc is not None:
            assert self.proc.stdin is not None
            self.proc.stdin.write(np.ascontiguousarray(frame).tobytes())
        else:
            self.cv.write(frame)
        self.count += 1

    def close(self) -> None:
        if self.proc is not None:
            assert self.proc.stdin is not None
            try:
                self.proc.stdin.close()
            except BrokenPipeError:
                pass
            err = self.proc.stderr.read() if self.proc.stderr else b""
            self.proc.wait()
            if self.proc.returncode != 0:
                raise RuntimeError(f"ffmpeg encode failed: {err.decode(errors='replace')[-2000:]}")
            self.proc = None
        elif self.cv is not None:
            self.cv.release()
            self.cv = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
