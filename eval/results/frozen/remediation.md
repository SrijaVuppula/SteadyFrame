# Remediation: fixed policy

Generated 2026-09-20 01:16 UTC by `python -m eval.remediation` at git `31b6cdd`, steadyframe 0.1.0, **OpenCV 5.0.0** (x86_64, CPython 3.11.15).

- Clips with hazards: **25**; post-verification pass rate **1.000** (25/25)
- Mean iterations per segment **1.10**; approvals requested 1 (auto-granted in this offline run)
- Quality retention: SSIM outside regions **1.0000**, inside regions 0.860, mean |dL| inside 0.149
- Runtime: mean 4.7 s per clip, 1.61x realtime for the full analyze+fix+verify loop (320x240 clips)
- Strategy usage: S1: 24, S2: 1, S3: 3, S5: 1

## Per clip

| clip | status | segments | accepted | attempts | approvals | strategies | ssim_outside | ssim_inside | dL_inside | runtime_s |
|---|---|---|---|---|---|---|---|---|---|---|
| a_sweep_11x11cells.mp4 | passed | 1 | 1 | 1 | 0 | S1 | 1.0000 | 0.869 | 0.095 | 3.3 |
| a_sweep_21x16cells.mp4 | passed | 1 | 1 | 1 | 0 | S1 | 1.0000 | 0.851 | 0.134 | 3.2 |
| a_sweep_full.mp4 | passed | 1 | 1 | 1 | 0 | S1 | 1.0000 | 0.808 | 0.268 | 3.1 |
| b_area_26pct.mp4 | passed | 1 | 1 | 1 | 0 | S1 | 1.0000 | 0.896 | 0.070 | 3.2 |
| b_dark_0p79.mp4 | passed | 1 | 1 | 1 | 0 | S1 | 1.0000 | 0.937 | 0.146 | 3.1 |
| b_delta_0p11.mp4 | passed | 1 | 1 | 1 | 0 | S1 | 1.0000 | 0.953 | 0.077 | 3.1 |
| b_rate_3p5hz.mp4 | passed | 1 | 1 | 1 | 0 | S1 | 1.0000 | 0.849 | 0.238 | 3.0 |
| b_rate_4hz.mp4 | passed | 1 | 1 | 1 | 0 | S1 | 1.0000 | 0.845 | 0.237 | 3.0 |
| f_sweep_10.mp4 | passed | 1 | 1 | 1 | 0 | S1 | 1.0000 | 0.871 | 0.130 | 3.2 |
| f_sweep_15.mp4 | passed | 1 | 1 | 1 | 0 | S1 | 1.0000 | 0.849 | 0.137 | 3.3 |
| f_sweep_4.mp4 | passed | 1 | 1 | 1 | 0 | S1 | 1.0000 | 0.863 | 0.144 | 3.1 |
| f_sweep_6.mp4 | passed | 1 | 1 | 1 | 0 | S1 | 1.0000 | 0.862 | 0.138 | 3.4 |
| m_gradient_bg_strobe.mp4 | passed | 1 | 1 | 1 | 0 | S1 | 1.0000 | 0.857 | 0.135 | 3.2 |
| m_strobe_on_moving_bg.mp4 | passed | 1 | 1 | 1 | 0 | S1 | 0.9992 | 0.806 | 0.132 | 3.8 |
| m_two_segments.mp4 | passed | 2 | 2 | 2 | 0 | S1,S1 | 1.0000 | 0.877 | 0.104 | 5.5 |
| r_red_strobe_full.mp4 | passed | 2 | 2 | 2 | 1 | S1,S3 | 1.0000 | 0.740 | 0.093 | 6.8 |
| r_red_strobe_region.mp4 | passed | 2 | 2 | 2 | 0 | S1,S3 | 1.0000 | 0.877 | 0.052 | 6.1 |
| r_red_to_white.mp4 | passed | 2 | 2 | 5 | 0 | S5,S3 | 1.0000 | 0.786 | 0.396 | 11.4 |
| v_720p_16x9.mp4 | passed | 1 | 1 | 1 | 0 | S1 | 1.0000 | 0.905 | 0.108 | 27.2 |
| v_fps_24.mp4 | passed | 1 | 1 | 1 | 0 | S1 | 1.0000 | 0.847 | 0.139 | 1.8 |
| v_fps_25.mp4 | passed | 1 | 1 | 1 | 0 | S1 | 1.0000 | 0.851 | 0.141 | 1.8 |
| v_fps_60.mp4 | passed | 1 | 1 | 2 | 0 | S2 | 1.0000 | 0.856 | 0.134 | 7.0 |
| v_vertical_9x16.mp4 | passed | 1 | 1 | 1 | 0 | S1 | 1.0000 | 0.836 | 0.224 | 1.7 |
| w_ramp_6hz.mp4 | passed | 1 | 1 | 1 | 0 | S1 | 1.0000 | 0.915 | 0.101 | 2.0 |
| w_sine_6hz.mp4 | passed | 1 | 1 | 1 | 0 | S1 | 1.0000 | 0.897 | 0.153 | 2.1 |

## Unresolved

None: every hazard segment was fixed and the whole file re-verified.
