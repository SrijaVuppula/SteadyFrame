# Robustness: compression, grid, fps, resolution

Generated 2026-09-20 01:35 UTC by `python -m eval.robustness` at git `8c32e8a`, steadyframe 0.1.0, **OpenCV 5.0.0** (x86_64, CPython 3.11.15).

## H.264 compression (CRF)

16/16 re-encoded variants keep the expected verdict.

| clip | crf | expected | got | base_got | sec_agreement | seg_t_iou | max_delta_shift |
|---|---|---|---|---|---|---|---|
| f_sweep_10__crf28.mp4 | 28 | fail | fail | fail | 1.000 | 1.000 | 0.008 |
| f_sweep_10__crf35.mp4 | 35 | fail | fail | fail | 1.000 | 1.000 | 0.024 |
| f_sweep_15__crf28.mp4 | 28 | fail | fail | fail | 1.000 | 1.000 | 0.014 |
| f_sweep_15__crf35.mp4 | 35 | fail | fail | fail | 1.000 | 1.000 | 0.008 |
| f_sweep_1__crf28.mp4 | 28 | pass | pass | pass | 1.000 | 1.000 | 0 |
| f_sweep_1__crf35.mp4 | 35 | pass | pass | pass | 1.000 | 1.000 | 0 |
| f_sweep_2__crf28.mp4 | 28 | pass | pass | pass | 1.000 | 1.000 | 0 |
| f_sweep_2__crf35.mp4 | 35 | pass | pass | pass | 1.000 | 1.000 | 0 |
| f_sweep_3__crf28.mp4 | 28 | pass | pass | pass | 1.000 | 1.000 | 0 |
| f_sweep_3__crf35.mp4 | 35 | pass | pass | pass | 1.000 | 1.000 | 0 |
| f_sweep_4__crf28.mp4 | 28 | fail | fail | fail | 1.000 | 1.000 | 0.016 |
| f_sweep_4__crf35.mp4 | 35 | fail | fail | fail | 1.000 | 1.000 | 0.032 |
| f_sweep_6__crf28.mp4 | 28 | fail | fail | fail | 1.000 | 1.000 | 0.015 |
| f_sweep_6__crf35.mp4 | 35 | fail | fail | fail | 1.000 | 1.000 | 0.035 |
| m_two_segments__crf28.mp4 | 28 | fail | fail | fail | 1.000 | 1.000 | 0.001 |
| v_720p_16x9__crf28.mp4 | 28 | fail | fail | fail | 1.000 | 1.000 | 0.000 |

## Analysis grid size

Same clips analysed with different cell grids (default 64x48). Boundary clips are aligned to the 64x48 grid, so coarser grids can split a region edge across cells; that is the quantisation effect the table exposes.

| grid | wrong_verdicts | of | median_rtf |
|---|---|---|---|
| 32x24 | 1 | 28 | 57.2 |
| 48x36 | 1 | 28 | 49.3 |
| 64x48 | 0 | 28 | 52.0 |
| 96x72 | 1 | 28 | 41.0 |
| 128x96 | 0 | 28 | 36.5 |

| clip | expected | 32x24 | 48x36 | 64x48 | 96x72 | 128x96 |
|---|---|---|---|---|---|---|
| a_sweep_11x11cells.mp4 | fail | fail | fail | fail | fail | fail |
| a_sweep_21x16cells.mp4 | fail | fail | fail | fail | fail | fail |
| a_sweep_3x3cells.mp4 | pass | pass | pass | pass | pass | pass |
| a_sweep_6x6cells.mp4 | pass | pass | pass | pass | pass | pass |
| a_sweep_full.mp4 | fail | fail | fail | fail | fail | fail |
| b_area_24pct.mp4 | pass | fail (!) | fail (!) | pass | fail (!) | pass |
| b_area_26pct.mp4 | fail | fail | fail | fail | fail | fail |
| b_dark_0p79.mp4 | fail | fail | fail | fail | fail | fail |
| b_dark_0p81.mp4 | pass | pass | pass | pass | pass | pass |
| b_delta_0p09.mp4 | pass | pass | pass | pass | pass | pass |
| b_delta_0p11.mp4 | fail | fail | fail | fail | fail | fail |
| b_rate_3hz.mp4 | pass | pass | pass | pass | pass | pass |
| b_rate_3p5hz.mp4 | fail | fail | fail | fail | fail | fail |
| b_rate_4hz.mp4 | fail | fail | fail | fail | fail | fail |
| m_gradient_bg_strobe.mp4 | fail | fail | fail | fail | fail | fail |
| m_strobe_on_moving_bg.mp4 | fail | fail | fail | fail | fail | fail |
| m_two_segments.mp4 | fail | fail | fail | fail | fail | fail |
| n_moving_texture.mp4 | pass | pass | pass | pass | pass | pass |
| n_near_red_not_saturated.mp4 | pass | pass | pass | pass | pass | pass |
| n_scene_cuts.mp4 | pass | pass | pass | pass | pass | pass |
| n_single_camera_flash.mp4 | pass | pass | pass | pass | pass | pass |
| n_slow_fade.mp4 | pass | pass | pass | pass | pass | pass |
| n_small_strobe_under_area.mp4 | pass | pass | pass | pass | pass | pass |
| n_static_texture.mp4 | pass | pass | pass | pass | pass | pass |
| n_two_distant_strobes.mp4 | pass | pass | pass | pass | pass | pass |
| r_red_strobe_full.mp4 | fail | fail | fail | fail | fail | fail |
| r_red_strobe_region.mp4 | fail | fail | fail | fail | fail | fail |
| r_red_to_white.mp4 | fail | fail | fail | fail | fail | fail |

## Frame rate, resolution, aspect ratio

| clip | fps | size | expected | got | peak_rate_hz | rtf |
|---|---|---|---|---|---|---|
| v_720p_16x9.mp4 | 30 | 1280x720 | fail | fail | 6.0 | 14.0 |
| v_fps_24.mp4 | 24 | 320x240 | fail | fail | 6.0 | 57.5 |
| v_fps_25.mp4 | 25 | 320x240 | fail | fail | 6.0 | 56.1 |
| v_fps_60.mp4 | 60 | 320x240 | fail | fail | 6.0 | 24.7 |
| v_vertical_9x16.mp4 | 30 | 180x320 | fail | fail | 6.0 | 43.2 |

## Frequency sweep

![](fig_frequency_sweep.png)

| true_hz | measured_hz | expected | verdict |
|---|---|---|---|
| 1 | 1.0 | pass | pass |
| 2 | 2.0 | pass | pass |
| 3 | 3.0 | pass | pass |
| 4 | 4.0 | fail | fail |
| 6 | 6.0 | fail | fail |
| 10 | 10.0 | fail | fail |
| 15 | 15.0 | fail | fail |

