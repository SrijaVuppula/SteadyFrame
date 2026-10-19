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

One command per configuration, no SSH: `bench/ec2.py` launches the instance, passes it
presigned S3 URLs in its user-data, waits for the result and terminates the instance (see
its docstring). It needs AWS credentials (the deploy user) and the storage bucket name that
`make deploy` printed (`BucketName`).

    B=<BucketName>
    .venv/bin/python -m bench.ec2 --config c7i.xlarge-stock --bucket $B --price <USD/h>
    .venv/bin/python -m bench.ec2 --config c8g.xlarge-stock --bucket $B --price <USD/h>
    .venv/bin/python -m bench.ec2 --config c8g.xlarge-cool  --bucket $B --price <USD/h + 0.01 COOL> --ami <COOL AMI id>
    .venv/bin/python -m bench.compare bench/results/*.json --out bench/results/comparison.md
    make freeze     # re-renders the report with the new table

`--dry-run` prints the plan and the user-data without touching AWS (for COOL, pass `--ami`
to see the real id in the plan). Each run takes about 10 minutes of instance time, so the
three cost well under a dollar.

### COOL: subscription and AMI id

Once per account, signed in to the AWS console as the account that runs the benchmark:

1. Open the AMI listing "Cloud Optimized OpenCV For AWS Graviton4":
   https://aws.amazon.com/marketplace/pp/prodview-fdvbfiewzuehs
2. "Continue to Subscribe", accept the terms, and wait until the subscription shows as
   active.
3. "Continue to Configuration": software version "Cloud Optimized OpenCV 3.1" (OpenCV 5.0 on
   Ubuntu 24.04 LTS), region us-east-1. Copy the AMI id shown there; it is the `--ami` value.

The listing has a 7-day free trial; after it the software is billed per hour of use, 0.01
USD/hour on c8g.xlarge, on top of the instance's EC2 price. Pass `--price` as the instance's
on-demand price plus 0.01 even inside the trial, so the USD per video-hour is the
steady-state cost.

On the COOL AMI the launcher follows the listing's usage instructions: it activates the
vendor's venv `/opt/cool/venvs/python_3.11` and installs into it everything in
`requirements.lock` except `opencv-python-headless`, then the package with `--no-deps`. The
pinned numpy stays if the AMI's cv2 works with it; otherwise the venv's own numpy is put
back. The log (`bench/results/<label>.ec2.log`) says which (`numpy: pinned ...` or
`numpy: venv ...`), and the JSON's `env.numpy` has the version. Before the benchmark starts
the run stops with `FATAL: ...` (non-zero, in the uploaded log) unless `cv2.__file__` is under
`/opt/cool` and `cv2.__version__` starts with `5.`, so a COOL row can never be the stock wheel
by accident. Evidence in `<label>.json`: `env.opencv_file` (under `/opt/cool`),
`env.build_information` / `env.build_has_kleidicv` (also `<label>.buildinfo.txt`), and
`env.loaded_libraries` / `env.kleidicv_loaded` from `/proc/self/maps`. A KleidiCV linked
statically into the OpenCV libraries does not show up as a library of its own; the build
information still lists it. Near its end the log has one `evidence:` line summarising
these.

Prices are on-demand us-east-1 at the time of the run: check them on the day and record
them, with the COOL software price and the OpenCV version string the COOL run prints, in
`docs/NOTES.md`.

With SSH access to an instance you launched yourself, `bench/remote.sh` does the same over
ssh/rsync (with `--cool`: the same vendor venv, numpy fallback and `/opt/cool` check):

    bench/remote.sh ubuntu@<host> c8g.xlarge-cool --cool --price <USD/h>

`make bench` runs the same harness on the current machine (label defaults to hostname).

## What we report

Median and p25/p75 latency per clip, fps, realtime factor, USD per video-hour
(`price_per_hour / realtime_factor`), the per-op table, and the cv2 time fraction. If COOL
gives no speedup on this workload we say so and look at the per-op table to say why.
