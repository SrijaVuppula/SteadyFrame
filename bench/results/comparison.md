# Benchmark comparison

| config | instance | OpenCV | KleidiCV in build | machine | analysis fps (median, 720p) | with decode fps | realtime x (analysis) | realtime x (with decode) | USD / video-hour (with decode) | time in cv2 built-ins |
|---|---|---|---|---|---|---|---|---|---|---|
| local-x86-stock | - | 5.0.0 | no | x86_64 | 633.9 | 420.9 | 20.1 | 13.9 | - | 0.79 |

Per-operation micro-benchmark, median ms on one 1280x720 frame:

| op | local-x86-stock |
|---|---|
| cv2.LUT (sRGB->linear, 720p x3ch) | 0.320 |
| cv2.transform (weighted sum -> luminance) | 1.320 |
| cv2.resize INTER_AREA 1280x720 -> 64x48 | 0.395 |
| cv2.resize INTER_AREA 1280x720 -> 256x192 | 1.513 |
| cv2.boxFilter 21x16 on 64x48 mask | 0.013 |
| cv2.GaussianBlur 11x11 s1.5 on 720p gray | 1.290 |
| cv2.GaussianBlur sigma 25 on 720p mask | 36.662 |
| cv2.connectedComponentsWithStats 64x48 | 0.047 |
| cv2.accumulateWeighted 720p float | 1.599 |
| cv2.dft 256x192 | 1.334 |

Spread (p25..p75 of analysis-only seconds per clip):

- local-x86-stock bench_strobe.mp4: median 0.189 s, p25 0.171, p75 0.196, min 0.170, max 0.200 (n=5)
- local-x86-stock bench_red.mp4: median 0.199 s, p25 0.198, p75 0.205, min 0.196, max 0.207 (n=5)
- local-x86-stock bench_clean.mp4: median 0.202 s, p25 0.201, p75 0.206, min 0.192, max 0.207 (n=5)
