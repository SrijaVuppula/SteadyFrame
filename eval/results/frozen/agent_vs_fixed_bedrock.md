# Agent vs fixed: bedrock

Generated 2026-09-21 17:07 UTC by `python -m eval.agent_vs_fixed` at git `5467f11`, steadyframe 0.1.0, **OpenCV 5.0.0** (arm64, CPython 3.11.15).

| metric | fixed | agent[bedrock] |
|---|---|---|
| post-verify success rate | 1.000 | 1.000 |
| mean iterations / segment | 1.100 | 1.040 |
| mean SSIM inside regions | 0.861 | 0.882 |
| mean SSIM outside regions | 1.000 | 1.000 |
| mean |dL| inside regions | 0.150 | 0.134 |
| mean runtime per clip (s) | 1.894 | 21.731 |
| approvals requested | 1 | 1 |
| model turns (total) | 0 | 170 |
| tokens in / out | - | 932017 / 16337 |
| LLM cost (USD, from config prices) | 0.000 | 0.000 |
| fallbacks to fixed policy | - | 0 |

Strategy usage, fixed: {"S1": 24, "S3": 3, "S5": 1, "S2": 1}; agent: {"S1": 15, "S4": 14}

## Per clip

| clip | fixed_status | agent_status | fixed_iter | agent_iter | fixed_ssim_in | agent_ssim_in | fixed_strategies | agent_strategies | agent_turns | agent_fallback |
|---|---|---|---|---|---|---|---|---|---|---|
| a_sweep_11x11cells.mp4 | passed | passed | 1.0 | 1.0 | 0.870 | 0.877 | S1 | S1 | 6 | None |
| a_sweep_21x16cells.mp4 | passed | passed | 1.0 | 1.0 | 0.852 | 0.860 | S1 | S1 | 6 | None |
| a_sweep_full.mp4 | passed | passed | 1.0 | 1.0 | 0.812 | 0.825 | S1 | S4 | 6 | None |
| b_area_26pct.mp4 | passed | passed | 1.0 | 1.0 | 0.896 | 0.900 | S1 | S1 | 6 | None |
| b_dark_0p79.mp4 | passed | passed | 1.0 | 1.0 | 0.937 | 0.937 | S1 | S4 | 6 | None |
| b_delta_0p11.mp4 | passed | passed | 1.0 | 1.0 | 0.953 | 0.995 | S1 | S4 | 6 | None |
| b_rate_3p5hz.mp4 | passed | passed | 1.0 | 1.0 | 0.849 | 0.846 | S1 | S4 | 6 | None |
| b_rate_4hz.mp4 | passed | passed | 1.0 | 1.0 | 0.845 | 0.843 | S1 | S4 | 6 | None |
| f_sweep_10.mp4 | passed | passed | 1.0 | 1.0 | 0.873 | 0.895 | S1 | S1 | 6 | None |
| f_sweep_15.mp4 | passed | passed | 1.0 | 1.0 | 0.851 | 0.885 | S1 | S1 | 6 | None |
| f_sweep_4.mp4 | passed | passed | 1.0 | 1.0 | 0.865 | 0.864 | S1 | S1 | 6 | None |
| f_sweep_6.mp4 | passed | passed | 1.0 | 1.0 | 0.864 | 0.947 | S1 | S4 | 6 | None |
| m_gradient_bg_strobe.mp4 | passed | passed | 1.0 | 1.0 | 0.858 | 0.863 | S1 | S1 | 6 | None |
| m_strobe_on_moving_bg.mp4 | passed | passed | 1.0 | 1.0 | 0.807 | 0.827 | S1 | S1 | 6 | None |
| m_two_segments.mp4 | passed | passed | 1.0 | 1.0 | 0.877 | 0.893 | S1,S1 | S1,S1 | 10 | None |
| r_red_strobe_full.mp4 | passed | passed | 1.0 | 1.5 | 0.740 | 0.812 | S1,S3 | S4,S4 | 13 | None |
| r_red_strobe_region.mp4 | passed | passed | 1.0 | 1.5 | 0.883 | 0.896 | S1,S3 | S1,S1 | 12 | None |
| r_red_to_white.mp4 | passed | passed | 2.5 | 1.0 | 0.785 | 0.801 | S5,S3 | S4,S4 | 9 | None |
| v_720p_16x9.mp4 | passed | passed | 1.0 | 1.0 | 0.907 | 0.913 | S1 | S1 | 6 | None |
| v_fps_24.mp4 | passed | passed | 1.0 | 1.0 | 0.849 | 0.944 | S1 | S4 | 6 | None |
| v_fps_25.mp4 | passed | passed | 1.0 | 1.0 | 0.853 | 0.862 | S1 | S1 | 6 | None |
| v_fps_60.mp4 | passed | passed | 2.0 | 1.0 | 0.858 | 0.854 | S2 | S1 | 6 | None |
| v_vertical_9x16.mp4 | passed | passed | 1.0 | 1.0 | 0.840 | 0.849 | S1 | S4 | 6 | None |
| w_ramp_6hz.mp4 | passed | passed | 1.0 | 1.0 | 0.917 | 0.931 | S1 | S4 | 6 | None |
| w_sine_6hz.mp4 | passed | passed | 1.0 | 1.0 | 0.898 | 0.921 | S1 | S4 | 6 | None |

## Where the agent was worse

- `r_red_strobe_full.mp4`: fixed passed (S1,S3, 1.0 it/seg, ssim_in 0.740) vs agent passed (S4,S4, 1.5 it/seg, ssim_in 0.812)
- `r_red_strobe_region.mp4`: fixed passed (S1,S3, 1.0 it/seg, ssim_in 0.883) vs agent passed (S1,S1, 1.5 it/seg, ssim_in 0.896)
