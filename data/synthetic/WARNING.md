# WARNING: flashing content

Everything generated into this directory by `make synth` is *deliberately hazardous*
test material: high-rate luminance and saturated-red strobes rendered to trigger the
analyzer. Do not open these files in a normal video player, do not embed them in
docs, and do not upload them anywhere.

They are not committed to git (see `.gitignore`); only the generator in `synth/`
and its config are versioned. Regenerate with `make synth`.

If you need to look at one, use the CLI plot instead of playing the clip:

    steadyframe analyze data/synthetic/<clip>.mp4 --plot out.png
