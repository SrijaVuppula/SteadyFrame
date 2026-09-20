# Real-world clip sources

Small hand-labelled set of openly licensed clips for the real-world sanity check. Nothing
here is redistributed; `python -m synth.fetch_real` downloads each file to `data/real/`
and the label sits next to it. Every entry needs: URL, licence, author, why it is here,
and a per-second verdict written by hand with `steadyframe analyze --plot` as an aid.

I could not get to Wikimedia Commons, Internet Archive or Pexels, so this
list is a template I still have to fill in. Rules: CC0 / CC BY / CC BY-SA / Pexels
licence only; no well-known copyrighted seizure-inducing clips; concert lighting, emergency
vehicle lights, game footage with a permissive licence, and calm control clips.

| id | url | licence | author | content | expected | notes |
|---|---|---|---|---|---|---|
| (example) real_concert_01 | https://commons.wikimedia.org/wiki/File:... | CC BY 4.0 | ... | stage strobes, 12 s | fail | label file: data/real/real_concert_01.gt.json |

Label format: same as the synthetic ground truth (`steadyframe/schema.py` GROUND_TRUTH_SCHEMA)
with `generator: {"version": "manual"}` and `notes` describing how the per-second verdicts
were decided.
