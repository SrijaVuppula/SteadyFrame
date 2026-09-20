"""SteadyFrame: photosensitive-hazard analysis and remediation for video, on OpenCV 5."""

import cv2

__version__ = "0.1.0"

OPENCV_VERSION = cv2.__version__
if not OPENCV_VERSION.startswith("5."):
    raise ImportError(
        f"SteadyFrame requires OpenCV 5.x, found {OPENCV_VERSION}. "
        "Install opencv-python-headless==5.0.0.93 (see requirements.lock)."
    )


def opencv_build_summary() -> dict:
    """Small dict of build facts we print in every report and benchmark."""
    info = cv2.getBuildInformation()
    summary = {"version": OPENCV_VERSION, "file": cv2.__file__}
    for key in ("FFMPEG", "Parallel framework", "Intel IPP", "KleidiCV", "NEON", "Baseline"):
        for line in info.splitlines():
            s = line.strip()
            if s.startswith(key + ":"):
                summary[key.lower().replace(" ", "_")] = s.split(":", 1)[1].strip()
                break
    return summary
