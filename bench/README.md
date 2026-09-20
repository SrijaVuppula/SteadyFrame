# Benchmark: stock OpenCV 5 on x86, stock OpenCV 5 on Graviton, COOL on Graviton

Same code, same clips, same repetitions on three configurations. Nothing is tuned per
configuration; the only variable is which OpenCV build executes.

| config | instance | OpenCV |
|---|---|---|
| `c7i.xlarge-stock` | c7i.xlarge (x86-64, 4 vCPU) | `opencv-python-headless==5.0.0.93` wheel |
| `c8g.xlarge-stock` | c8g.xlarge (Graviton4, 4 vCPU) | same wheel, aarch64 |
| `c8g.xlarge-cool` | c8g.xlarge from the COOL AMI ("Cloud Optimized OpenCV For AWS Graviton4") | the AMI's OpenCV 5 build with KleidiCV |

## Workload

`bench/run.py` (see its docstring): the analyzer on three 1280x720, 4 s clips, ten
repetitions after one discarded warm-up, reported with and without decode; a per-operation
micro-benchmark of the OpenCV calls involved (`LUT`, `transform`, `resize INTER_AREA`,
`boxFilter`, `GaussianBlur`, `connectedComponentsWithStats`, `accumulateWeighted`, `dft`);
a cProfile of one run giving the fraction of time spent inside cv2 built-ins.

Evidence that a given build executed: the JSON records `cv2.__file__`, the full
`cv2.getBuildInformation()` (also saved as `<label>.buildinfo.txt`), the shared libraries
mapped into the process (grep for `kleidicv`), CPU features, and the EC2 instance type from
IMDS.

## Running it

    bench/remote.sh ubuntu@<c7i host>  c7i.xlarge-stock --price 0.1785
    bench/remote.sh ubuntu@<c8g host>  c8g.xlarge-stock --price 0.1530
    bench/remote.sh ubuntu@<c8g cool>  c8g.xlarge-cool  --cool --price 0.1530   # add the COOL software $/h if the listing charges one
    python -m bench.compare bench/results/*.json --out bench/results/comparison.md

Prices are on-demand us-east-1 at the time of the run: check them on the day and record
them in `docs/NOTES.md`. Terminate the instances afterwards.

`make bench` runs the same harness on the current machine (label defaults to hostname).

## What we report

Median and p25/p75 latency per clip, fps, realtime factor, USD per video-hour
(`price_per_hour / realtime_factor`), the per-op table, and the cv2 time fraction. If COOL
gives no speedup on this workload we say so and look at the per-op table to say why.
