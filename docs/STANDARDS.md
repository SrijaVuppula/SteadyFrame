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
caused by television" (BT.1702-3, 11/2023, is the version in force) and the Ofcom guidance
note on flashing images and regular patterns, which Ofcom still publishes as the legacy "ITC
Guidance Note for Licensees on Flashing Images and Regular Patterns in Television" (revised
and re-issued July 2001, editorial amendment June 2002). The ofcom.org.uk copy sits behind a
bot check, so the note was read on 2026-10-19 from the Internet Archive's capture of
2023-10-01 (https://web.archive.org/web/20231001095538/https://www.ofcom.org.uk/__data/assets/pdf_file/0021/16248/gn_flash.pdf,
4 pages, SHA-256 `e5b858967a2c0476a49fcf6e06e766ce1f0fe49c4f3bd1aee947a2fad7774ffa`).
The definition, checked word for word against that copy:

> A potentially harmful flash occurs when there is a pair of opposing changes in luminance
> (i.e., an increase in luminance followed by a decrease, or a decrease followed by an
> increase) of 20 candelas per square metre (cd.m-2) or more (see notes 1 and 2). This
> applies only when the screen luminance of the darker image is below 160 cd.m-2.

The rest of the note, by paragraph (paraphrased; short phrases quoted):

- **§3** continues: irrespective of luminance, a transition to or from a saturated red is also
  potentially harmful.
- **§3.1** Isolated single, double or triple flashes are acceptable. A sequence is not permitted
  when *both* (i) the combined area of concurrent flashes occupies more than one quarter of the
  displayed screen area and (ii) there are "more than three flashes within any one-second
  period". Successive flashes whose leading edges are 9 frames or more apart are acceptable
  whatever their brightness or area.
- **§4** Fast cuts are provocative when they make areas of the screen flash; the same limits
  apply.
- **§5, §5.1** A potentially harmful regular pattern has more than five light-dark pairs of
  stripes in any orientation (parallel, radial, curved, or rows of elements such as dots).
  Stationary patterns are not permitted above 40% of the displayed screen; patterns that change
  direction, oscillate, flash or reverse in contrast are not permitted above 25%; in both cases
  only when the darker bars are below 160 cd/m2 and differ from the lighter bars by 20 cd/m2 or
  more. Patterns that flow smoothly across, into or out of the screen in one direction are
  exempt.
- **Notes 1 and 2** Compliance measurements assume a display gamma of 2.2 and the ITU-R BT.500
  home viewing environment, where peak white is 200 cd/m2. Note 3: overscan of about 3.5% of
  picture width or height may be assumed.
- The introduction adds that flashing lasting more than 5 seconds "might constitute a risk"
  even when it complies, because the cumulative risk is unknown.

Ofcom's technical analysis in the 2012 ASA ruling on a Citroën advertisement (A11-164759)
names the same three conditions for a breach: a change in brightness above the defined level,
more than three pairs of opposing changes in any one second, and more than 25% of the screen
area changing in brightness.

Implementation and where it differs from the note:

- Area: same transition machine as `wcag`, but the area test is the fraction of the *whole
  frame* that is flashing (> 0.25). Overscan is not cropped, so a flash at the very edge counts
  slightly more than on a 2001 television.
- Luminance: on the note's own reference display (gamma 2.2, peak white 200 cd/m2), 20 cd/m2 is
  0.10 and 160 cd/m2 is 0.80 of peak white, exactly the WCAG relative-luminance thresholds. The
  `broadcast` profile therefore keeps 0.10 and 0.80. The analyzer linearises with the sRGB
  curve rather than a pure 2.2 power law (the two differ most near black), and a display
  brighter than the reference is not modelled.
- Red: the PEAT/IRIS saturated-red rule from section 1 is applied in both profiles.
- 9-frame rule: not implemented as an exemption. At 25 fps flashes 9 frames apart are at most
  2.8 a second, so they pass the rate rule anyway; at 30 or 60 fps four flashes 0.30 s apart can
  fall in one second, which this tool fails and the note would accept. Stricter, not looser.
- Patterns (`pattern.py`, experimental, off by default): "more than five light-dark pairs,
  > 25% of the screen, > 0.5 s" on the luminance map. The 0.5 s duration comes from the
  secondary summaries cited in NOTES.md, not from the 2001 note, and the detector does not
  separate stationary patterns (40% limit) from moving ones (25%), so stationary patterns
  between 25% and 40% of the screen are over-flagged.
- The 5-second advisory is not a rule here; the viewer warning track (`hazards.vtt`) marks
  every flagged segment regardless.

## 3. What the tool does not claim

It checks video against the published thresholds above. It does not certify content, does not
model individual sensitivity, and does not know the viewer's display brightness or distance.
See `docs/RESPONSIBLE_USE.md`.
