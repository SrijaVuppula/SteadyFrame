# Standards and thresholds

Everything the analyzer measures is traceable to a quoted sentence here. Values live in
`steadyframe/profiles.py`; this file explains where each one comes from and what we decided
when the text was ambiguous.

## 1. WCAG 2.2, Success Criterion 2.3.1 Three Flashes or Below Threshold (Level A)

Source: https://www.w3.org/TR/WCAG22/#three-flashes-or-below-threshold (text read from the
w3c/wcag repository, `guidelines/sc/20/three-flashes-or-below-threshold.html`, 2026-09-20).

> Web pages do not contain anything that flashes more than three times in any one second
> period, or the flash is below the general flash and red flash thresholds.

### 1.1 Definition: general flash and red flash thresholds

Source: https://www.w3.org/TR/WCAG22/#dfn-general-flash-and-red-flash-thresholds

> a flash or rapidly changing image sequence is below the threshold (i.e., content passes) if
> any of the following are true:
>
> - there are no more than three general flashes and / or no more than three red flashes
>   within any one-second period; or
> - the combined area of flashes occurring concurrently occupies no more than a total of .006
>   steradians within any 10 degree visual field on the screen (25% of any 10 degree visual
>   field on the screen) at typical viewing distance
>
> where:
>
> - A general flash is defined as a pair of opposing changes in relative luminance of 10% or
>   more of the maximum relative luminance (1.0) where the relative luminance of the darker
>   image is below 0.80; and where "a pair of opposing changes" is an increase followed by a
>   decrease, or a decrease followed by an increase, and
> - A red flash is defined as any pair of opposing transitions involving a saturated red
>
> Exception: Flashing that is a fine, balanced, pattern such as white noise or an alternating
> checkerboard pattern with "squares" smaller than 0.1 degree (of visual field at typical
> viewing distance) on a side does not violate the thresholds.
>
> Note: For general software or web content, using a 341 x 256 pixel rectangle anywhere on the
> displayed screen area when the content is viewed at 1024 x 768 pixels will provide a good
> estimate of a 10 degree visual field for standard screen sizes and viewing distances (e.g.,
> 15-17 inch screen at 22-26 inches). [...]
>
> Note: A transition is the change in relative luminance (or relative luminance/color for red
> flashing) between adjacent peaks and valleys in a plot of relative luminance (or relative
> luminance/color for red flashing) measurement against time. A flash consists of two opposing
> transitions.
>
> Note: The new working definition in the field for "pair of opposing transitions involving a
> saturated red" (from WCAG 2.2) is a pair of opposing transitions where, one transition is
> either to or from a state with a value R/(R + G + B) that is greater than or equal to 0.8,
> and the difference between states is more than 0.2 (unitless) in the CIE 1976 UCS
> chromaticity diagram. [ISO 9241-391]

### 1.2 Definition: relative luminance

Source: https://www.w3.org/TR/WCAG22/#dfn-relative-luminance

> For the sRGB colorspace, the relative luminance of a color is defined as
> L = 0.2126 * R + 0.7152 * G + 0.0722 * B where R, G and B are defined as:
> if RsRGB <= 0.04045 then R = RsRGB/12.92 else R = ((RsRGB+0.055)/1.055) ^ 2.4
> (same for G and B), and RsRGB = R8bit/255 etc.

### 1.3 Our implementation decisions (profile `wcag`)

| Item | Decision | Why |
|---|---|---|
| Transition | accumulated change between successive local extrema of the per-cell luminance signal, counted once when it first reaches **>= 0.10** and the darker extremum is **< 0.80** | "adjacent peaks and valleys", not adjacent frames; a ramp over several frames is one transition |
| Reversal hysteresis | a run reverses when the signal moves against it by more than `reversal_eps` (0.02 by default) | codec noise must not split a slow fade into many tiny runs |
| Flash count | transitions in the trailing 1.0 s window, timestamps not frame indices; **fail when > 6 transitions** (more than three flashes) | a flash is two opposing transitions; consecutive counted transitions alternate by construction |
| `conservative` | additionally *warns* at exactly 6 transitions (three flashes) in a second | three flashes passes WCAG; the warning is for authors who want margin |
| Area | per-cell flashing mask (cells with > 6 transitions in the window), box-filtered with a window of 341/1024 x 256/768 of the frame; **area condition met when any window fraction > 0.25** | literal reading of "25% of any 10 degree visual field" |
| Verdict | `fail` at any frame where the flash-rate condition and the area condition both hold; `warn` for conservative hits; `pass` otherwise | WCAG passes if *either* condition is satisfied, so a failure needs both |
| Red saturation | linear R/(R+G+B) >= 0.8 | WCAG 2.2 note |
| Red transition | change in `max(0, R_lin - G_lin - B_lin) * 320` of **> 20** between extrema, where at least one extremum is saturated red | this is the PEAT / IRIS working rule the spec asks for; the u'v' distance (> 0.2) from the WCAG 2.2 note is also computed and reported as `red_uv_delta` |
| Fine patterns exception | not implemented; we do not exempt white-noise-like flashing | conservative; noted as a limitation |
| Analysis grid | 64 x 48 cells by default (INTER_AREA box average of pixel luminance) | temporal logic per cell; sensitivity to grid size is measured in `eval/robustness.py` |

The 341 x 256 rectangle is 1/3 x 1/3 of a 1024 x 768 frame, so on a 64 x 48 grid the window is
21 x 16 cells. On other aspect ratios we scale each side independently (`341/1024 * W`,
`256/768 * H`), which follows the WCAG note; note this makes the window a fixed *fraction* of the
frame rather than a fixed angle, which is only exact for a full-screen 4:3 viewport.

## 2. ITU-R BT.1702 / Ofcom guidance (profile `broadcast`)

Sources: ITU-R BT.1702-2 "Guidance for the reduction of photosensitive epileptic seizures
caused by television" and Ofcom Broadcasting Code Annex 1 "Guidance notes on flashing images
and regular patterns in television". The PDFs could not be fetched from my machine
(see NOTES.md); the values below are as summarised by Epilepsy Action, the ASA and the
ACM TACCESS 2024 gap analysis (10.1145/3694790). **TODO: paste the exact Annex 1 wording here.**

Reported rules:

- A potentially harmful flash is a change in luminance of 20 cd/m2 or more where the darker
  image is below 160 cd/m2 (screen luminance).
- Isolated single, double or triple flashes are acceptable; a sequence of flashes is not
  permitted when the flashing exceeds three flashes in any one second.
- The area rule is the flashing area exceeding one quarter (25%) of the displayed screen area.
- Regular patterns: more than five light-dark pairs of stripes in any orientation, high
  contrast, occupying more than 25% of the screen; stationary patterns are permitted only if
  they last no more than half a second, patterns that flash or change direction are not.

Implementation: same transition machine as `wcag`, but the area test is the fraction of the
*whole frame* that is flashing (> 0.25). Absolute cd/m2 cannot be recovered from an sRGB
video without a display model, so the transition threshold stays at 0.10 relative luminance;
the report says so. The pattern detector (`pattern.py`, experimental) implements the
"more than five light-dark pairs, > 25% of the screen, > 0.5 s" rule on the luminance map.

## 3. What the tool does not claim

It checks video against the published thresholds above. It does not certify content, does not
model individual sensitivity, and does not know the viewer's display brightness or distance.
See `docs/RESPONSIBLE_USE.md`.
