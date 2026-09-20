import cv2

import steadyframe


def test_opencv_is_5():
    assert cv2.__version__.startswith("5.")
    assert steadyframe.OPENCV_VERSION == cv2.__version__


def test_build_summary_has_version():
    s = steadyframe.opencv_build_summary()
    assert s["version"].startswith("5.")
    assert "ffmpeg" in s
