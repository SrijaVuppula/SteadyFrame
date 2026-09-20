# Detection: synthetic suite

Generated 2026-09-20 01:35 UTC by `python -m eval.detection` at git `8c32e8a`, steadyframe 0.1.0, **OpenCV 5.0.0** (x86_64, CPython 3.11.15).

- Clips: **44**, clip-level verdict accuracy **1.000**, hazard-type agreement 1.000
- Per-second (window-level) with `fail` positive: precision **1.000**, recall **1.000**, F1 **1.000** (tp=107, fp=0, fn=0)
- Boundary cases correct: **17/17**
- Localisation: mean temporal IoU 0.899, mean spatial IoU 0.979 (against ground-truth event intervals and regions; the analyzer's segment end includes the up-to-1 s tail of the trailing window, which lowers temporal IoU by design)

## Boundary cases

| clip | case | expected | got | ok |
|---|---|---|---|---|
| b_area_24pct.mp4 | 9x9 cells = 24.1% of the 21x16 window -> pass | pass | pass | yes |
| b_area_26pct.mp4 | 8x11 cells = 26.2% of the 21x16 window -> fail | fail | fail | yes |
| b_dark_0p79.mp4 | darker state L=0.79 (< 0.80) -> fail | fail | fail | yes |
| b_dark_0p81.mp4 | darker state L=0.81 (>= 0.80) -> pass | pass | pass | yes |
| b_delta_0p09.mp4 | luminance swing 0.09 (< 0.10) -> pass | pass | pass | yes |
| b_delta_0p11.mp4 | luminance swing 0.11 (>= 0.10) -> fail | fail | fail | yes |
| b_rate_3hz.mp4 | exactly three flashes per second -> pass | pass | pass | yes |
| b_rate_3p5hz.mp4 | 3.5 flashes per second -> fail | fail | fail | yes |
| b_rate_4hz.mp4 | 4 flashes per second -> fail | fail | fail | yes |
| n_moving_texture.mp4 | panning texture -> pass | pass | pass | yes |
| n_near_red_not_saturated.mp4 | red with R/(R+G+B)=0.78 and swing 0.084 -> pass (neither rule) | pass | pass | yes |
| n_scene_cuts.mp4 | hard cuts every 0.5 s (1 flash/s) -> pass | pass | pass | yes |
| n_single_camera_flash.mp4 | one 1-frame white flash -> pass | pass | pass | yes |
| n_slow_fade.mp4 | 3 s fade black->white then back -> pass | pass | pass | yes |
| n_small_strobe_under_area.mp4 | 10 Hz strobe covering 10% of the window -> pass (area) | pass | pass | yes |
| n_static_texture.mp4 | static natural-ish texture -> pass | pass | pass | yes |
| n_two_distant_strobes.mp4 | two 15%-of-window strobes in opposite corners -> pass | pass | pass | yes |

## All clips

| clip | expected | got | ok | types_ok | sec_tp | sec_fp | sec_fn | t_iou | s_iou | rtf |
|---|---|---|---|---|---|---|---|---|---|---|
| a_sweep_11x11cells.mp4 | fail | fail | yes | yes | 5 | 0 | 0 | 0.889 | 1.000 | 57.7 |
| a_sweep_21x16cells.mp4 | fail | fail | yes | yes | 5 | 0 | 0 | 0.889 | 1.000 | 46.0 |
| a_sweep_3x3cells.mp4 | pass | pass | yes | yes | 0 | 0 | 0 | nan | nan | 62.3 |
| a_sweep_6x6cells.mp4 | pass | pass | yes | yes | 0 | 0 | 0 | nan | nan | 57.5 |
| a_sweep_full.mp4 | fail | fail | yes | yes | 5 | 0 | 0 | 0.889 | 1.000 | 57.6 |
| b_area_24pct.mp4 | pass | pass | yes | yes | 0 | 0 | 0 | nan | nan | 58.9 |
| b_area_26pct.mp4 | fail | fail | yes | yes | 4 | 0 | 0 | 0.902 | 1.000 | 51.3 |
| b_dark_0p79.mp4 | fail | fail | yes | yes | 4 | 0 | 0 | 0.902 | 1.000 | 49.6 |
| b_dark_0p81.mp4 | pass | pass | yes | yes | 0 | 0 | 0 | nan | nan | 58.5 |
| b_delta_0p09.mp4 | pass | pass | yes | yes | 0 | 0 | 0 | nan | nan | 55.5 |
| b_delta_0p11.mp4 | fail | fail | yes | yes | 4 | 0 | 0 | 0.902 | 1.000 | 49.0 |
| b_rate_3hz.mp4 | pass | pass | yes | yes | 0 | 0 | 0 | nan | nan | 57.1 |
| b_rate_3p5hz.mp4 | fail | fail | yes | yes | 4 | 0 | 0 | 1.000 | 1.000 | 54.9 |
| b_rate_4hz.mp4 | fail | fail | yes | yes | 4 | 0 | 0 | 0.968 | 1.000 | 48.3 |
| f_sweep_1.mp4 | pass | pass | yes | yes | 0 | 0 | 0 | nan | nan | 65.8 |
| f_sweep_10.mp4 | fail | fail | yes | yes | 5 | 0 | 0 | 0.889 | 1.000 | 52.6 |
| f_sweep_15.mp4 | fail | fail | yes | yes | 5 | 0 | 0 | 0.889 | 1.000 | 51.7 |
| f_sweep_2.mp4 | pass | pass | yes | yes | 0 | 0 | 0 | nan | nan | 54.9 |
| f_sweep_3.mp4 | pass | pass | yes | yes | 0 | 0 | 0 | nan | nan | 62.8 |
| f_sweep_4.mp4 | fail | fail | yes | yes | 4 | 0 | 0 | 0.968 | 1.000 | 50.0 |
| f_sweep_6.mp4 | fail | fail | yes | yes | 4 | 0 | 0 | 0.902 | 1.000 | 59.0 |
| m_gradient_bg_strobe.mp4 | fail | fail | yes | yes | 4 | 0 | 0 | 0.889 | 0.950 | 54.1 |
| m_strobe_on_moving_bg.mp4 | fail | fail | yes | yes | 4 | 0 | 0 | 0.692 | 0.945 | 43.9 |
| m_two_segments.mp4 | fail | fail | yes | yes | 7 | 0 | 0 | 0.802 | 0.960 | 52.7 |
| n_moving_texture.mp4 | pass | pass | yes | yes | 0 | 0 | 0 | nan | nan | 44.6 |
| n_near_red_not_saturated.mp4 | pass | pass | yes | yes | 0 | 0 | 0 | nan | nan | 54.5 |
| n_scene_cuts.mp4 | pass | pass | yes | yes | 0 | 0 | 0 | nan | nan | 51.4 |
| n_single_camera_flash.mp4 | pass | pass | yes | yes | 0 | 0 | 0 | nan | nan | 52.8 |
| n_slow_fade.mp4 | pass | pass | yes | yes | 0 | 0 | 0 | nan | nan | 56.9 |
| n_small_strobe_under_area.mp4 | pass | pass | yes | yes | 0 | 0 | 0 | nan | nan | 59.8 |
| n_static_texture.mp4 | pass | pass | yes | yes | 0 | 0 | 0 | nan | nan | 53.5 |
| n_two_distant_strobes.mp4 | pass | pass | yes | yes | 0 | 0 | 0 | nan | nan | 51.0 |
| p_stripes_static.mp4 | warn | warn | yes | yes | 0 | 0 | 0 | 1.000 | 0.640 | 9.3 |
| r_red_strobe_full.mp4 | fail | fail | yes | yes | 4 | 0 | 0 | 0.930 | 1.000 | 41.1 |
| r_red_strobe_region.mp4 | fail | fail | yes | yes | 4 | 0 | 0 | 0.909 | 0.985 | 52.0 |
| r_red_to_white.mp4 | fail | fail | yes | yes | 4 | 0 | 0 | 0.937 | 1.000 | 49.2 |
| v_720p_16x9.mp4 | fail | fail | yes | yes | 3 | 0 | 0 | 0.874 | 0.945 | 13.1 |
| v_fps_24.mp4 | fail | fail | yes | yes | 4 | 0 | 0 | 0.906 | 1.000 | 64.9 |
| v_fps_25.mp4 | fail | fail | yes | yes | 4 | 0 | 0 | 0.900 | 1.000 | 59.3 |
| v_fps_60.mp4 | fail | fail | yes | yes | 4 | 0 | 0 | 0.906 | 1.000 | 26.3 |
| v_vertical_9x16.mp4 | fail | fail | yes | yes | 4 | 0 | 0 | 0.902 | 1.000 | 48.9 |
| w_ramp_6hz.mp4 | fail | fail | yes | yes | 4 | 0 | 0 | 0.874 | 1.000 | 57.2 |
| w_sine_6hz.mp4 | fail | fail | yes | yes | 4 | 0 | 0 | 0.888 | 1.000 | 48.9 |
| w_triangle_2hz.mp4 | pass | pass | yes | yes | 0 | 0 | 0 | nan | nan | 59.2 |

## Misses

None on this run.
