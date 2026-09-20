# Agent vs fixed: heuristic

Generated 2026-09-20 01:27 UTC by `python -m eval.agent_vs_fixed` at git `3c6cf81`, steadyframe 0.1.0, **OpenCV 5.0.0** (x86_64, CPython 3.11.15).

| metric | fixed | agent[heuristic] |
|---|---|---|
| post-verify success rate | 1.000 | 1.000 |
| mean iterations / segment | 1.100 | 1.000 |
| mean SSIM inside regions | 0.860 | 0.874 |
| mean SSIM outside regions | 1.000 | 1.000 |
| mean |dL| inside regions | 0.149 | 0.135 |
| mean runtime per clip (s) | 4.731 | 3.473 |
| approvals requested | 1 | 1 |
| model turns (total) | 0 | 167 |
| tokens in / out | - | 0 / 0 |
| LLM cost (USD, from config prices) | 0.000 | 0.000 |
| fallbacks to fixed policy | - | 0 |

Strategy usage, fixed: {"S1": 24, "S3": 3, "S5": 1, "S2": 1}; agent: {"S1": 16, "S4": 10, "S3": 3}

The heuristic provider is a deterministic stand-in for the model that follows the same tool protocol and uses the analyzer's parameter hints (`parameter_hints` in `get_segment_detail`). What it shows is the value of measurement-driven parameter selection and regional-first escalation over fixed defaults, not the value of an LLM. The live Bedrock comparison is in `agent_vs_fixed_bedrock.md` when it has been run.

## Per clip

| clip | fixed_status | agent_status | fixed_iter | agent_iter | fixed_ssim_in | agent_ssim_in | fixed_strategies | agent_strategies | agent_turns | agent_fallback |
|---|---|---|---|---|---|---|---|---|---|---|
| a_sweep_11x11cells.mp4 | passed | passed | 1.0 | 1.0 | 0.869 | 0.877 | S1 | S1 | 6 | None |
| a_sweep_21x16cells.mp4 | passed | passed | 1.0 | 1.0 | 0.851 | 0.859 | S1 | S1 | 6 | None |
| a_sweep_full.mp4 | passed | passed | 1.0 | 1.0 | 0.808 | 0.822 | S1 | S4 | 6 | None |
| b_area_26pct.mp4 | passed | passed | 1.0 | 1.0 | 0.896 | 0.900 | S1 | S1 | 6 | None |
| b_dark_0p79.mp4 | passed | passed | 1.0 | 1.0 | 0.937 | 0.984 | S1 | S4 | 6 | None |
| b_delta_0p11.mp4 | passed | passed | 1.0 | 1.0 | 0.953 | 0.995 | S1 | S4 | 6 | None |
| b_rate_3p5hz.mp4 | passed | passed | 1.0 | 1.0 | 0.849 | 0.847 | S1 | S4 | 6 | None |
| b_rate_4hz.mp4 | passed | passed | 1.0 | 1.0 | 0.845 | 0.843 | S1 | S4 | 6 | None |
| f_sweep_10.mp4 | passed | passed | 1.0 | 1.0 | 0.871 | 0.894 | S1 | S1 | 6 | None |
| f_sweep_15.mp4 | passed | passed | 1.0 | 1.0 | 0.849 | 0.884 | S1 | S1 | 6 | None |
| f_sweep_4.mp4 | passed | passed | 1.0 | 1.0 | 0.863 | 0.863 | S1 | S1 | 6 | None |
| f_sweep_6.mp4 | passed | passed | 1.0 | 1.0 | 0.862 | 0.869 | S1 | S1 | 6 | None |
| m_gradient_bg_strobe.mp4 | passed | passed | 1.0 | 1.0 | 0.857 | 0.862 | S1 | S1 | 6 | None |
| m_strobe_on_moving_bg.mp4 | passed | passed | 1.0 | 1.0 | 0.806 | 0.825 | S1 | S1 | 6 | None |
| m_two_segments.mp4 | passed | passed | 1.0 | 1.0 | 0.877 | 0.893 | S1,S1 | S1,S1 | 10 | None |
| r_red_strobe_full.mp4 | passed | passed | 1.0 | 1.0 | 0.740 | 0.758 | S1,S3 | S4,S3 | 11 | None |
| r_red_strobe_region.mp4 | passed | passed | 1.0 | 1.0 | 0.877 | 0.894 | S1,S3 | S1,S3 | 10 | None |
| r_red_to_white.mp4 | passed | passed | 2.5 | 1.0 | 0.786 | 0.804 | S5,S3 | S4,S3 | 10 | None |
| v_720p_16x9.mp4 | passed | passed | 1.0 | 1.0 | 0.905 | 0.911 | S1 | S1 | 6 | None |
| v_fps_24.mp4 | passed | passed | 1.0 | 1.0 | 0.847 | 0.859 | S1 | S1 | 6 | None |
| v_fps_25.mp4 | passed | passed | 1.0 | 1.0 | 0.851 | 0.861 | S1 | S1 | 6 | None |
| v_fps_60.mp4 | passed | passed | 2.0 | 1.0 | 0.856 | 0.852 | S2 | S1 | 6 | None |
| v_vertical_9x16.mp4 | passed | passed | 1.0 | 1.0 | 0.836 | 0.846 | S1 | S4 | 6 | None |
| w_ramp_6hz.mp4 | passed | passed | 1.0 | 1.0 | 0.915 | 0.930 | S1 | S4 | 6 | None |
| w_sine_6hz.mp4 | passed | passed | 1.0 | 1.0 | 0.897 | 0.920 | S1 | S4 | 6 | None |

## Where the agent was worse

None on this run.
