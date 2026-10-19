#!/usr/bin/env bash
# Run the benchmark on a fresh EC2 instance and copy the result back.
#
#   bench/remote.sh <host> <label> [--cool] [--price 0.1234]
#
# <host>  ssh target (ubuntu@ec2-...). Ubuntu 24.04 assumed (COOL AMI is Ubuntu 24.04).
# --cool  use the AMI's OpenCV (COOL) instead of the PyPI wheel: everything but the wheel goes
#         into the vendor's venv /opt/cool/venvs/python_3.11 (the pinned numpy only if the
#         AMI's cv2 works with it), and the run stops unless cv2 resolves under /opt/cool and
#         is 5.x. The harness records its build info and library paths as evidence.
# --price on-demand USD/hour of the instance (+ COOL software price/hour if the listing has one)
set -euo pipefail
HOST=$1; LABEL=$2; shift 2
COOL=0; PRICE=""
while [ $# -gt 0 ]; do
  case $1 in
    --cool) COOL=1;;
    --price) PRICE=$2; shift;;
  esac; shift
done
REPO=$(cd "$(dirname "$0")/.." && pwd)
rsync -az --exclude .venv --exclude data --exclude web/node_modules --exclude .git "$REPO/" "$HOST:~/steadyframe/"
ssh "$HOST" "COOL=$COOL LABEL=$(printf %q "$LABEL") PRICE=$(printf %q "$PRICE") bash -s" <<'REMOTE'
set -euo pipefail
cd ~/steadyframe
sudo apt-get update -qq && sudo apt-get install -y -qq python3-venv python3-pip rsync >/dev/null
if [ "$COOL" = "1" ]; then
  # the vendor's venv carries the AMI's OpenCV; install around it, never over it
  COOL_VENV=/opt/cool/venvs/python_3.11
  if [ ! -x "$COOL_VENV/bin/python" ]; then
    echo "FATAL: $COOL_VENV/bin/python not found; is this the COOL AMI?" >&2
    exit 1
  fi
  set +u
  . "$COOL_VENV/bin/activate"
  set -u
  PY="$COOL_VENV/bin/python"
  SUDO=""
  [ -w "$COOL_VENV" ] || SUDO=sudo
  "$PY" -c "import cv2, numpy; print('AMI OpenCV', cv2.__version__, cv2.__file__, 'numpy', numpy.__version__)"
  VENV_NUMPY=$("$PY" -c "import numpy; print(numpy.__version__)")
  "$PY" -m pip --version >/dev/null 2>&1 || $SUDO "$PY" -m ensurepip --upgrade
  $SUDO "$PY" -m pip install -q --upgrade pip
  grep -v -i '^opencv' requirements.lock > /tmp/req.txt
  $SUDO "$PY" -m pip install -q -r /tmp/req.txt
  CV2_SMOKE="import cv2, numpy; cv2.resize(numpy.zeros((8, 8), numpy.float32), (4, 4))"
  if "$PY" -c "$CV2_SMOKE"; then
    echo "numpy: pinned $("$PY" -c "import numpy; print(numpy.__version__)") (the AMI's cv2 works with it)"
  else
    echo "numpy: the AMI's cv2 does not work with the pinned numpy; restoring the venv's numpy $VENV_NUMPY"
    $SUDO "$PY" -m pip install -q "numpy==$VENV_NUMPY"
    "$PY" -c "$CV2_SMOKE"
    echo "numpy: venv $VENV_NUMPY"
  fi
  $SUDO "$PY" -m pip install -q -e . --no-deps
  [ -z "$SUDO" ] || sudo chown -R "$(id -u):$(id -g)" ~/steadyframe
  "$PY" - <<'COOLCHECK'
import sys
import cv2
print("COOL check: cv2", cv2.__version__, "at", cv2.__file__)
if not cv2.__file__.startswith("/opt/cool/"):
    sys.exit("FATAL: cv2 resolves to " + cv2.__file__ + ", not under /opt/cool")
if not cv2.__version__.startswith("5."):
    sys.exit("FATAL: cv2 under /opt/cool is " + cv2.__version__ + ", not OpenCV 5")
COOLCHECK
else
  python3 -m venv .venv
  PY=.venv/bin/python
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install -q -r requirements.lock
  .venv/bin/pip install -q -e . --no-deps
fi
"$PY" -m bench.run --out bench/results --label "$LABEL" --reps 10 ${PRICE:+--price-per-hour $PRICE}
REMOTE
mkdir -p "$REPO/bench/results"
rsync -az "$HOST:~/steadyframe/bench/results/$LABEL.json" "$HOST:~/steadyframe/bench/results/$LABEL.buildinfo.txt" "$REPO/bench/results/"
echo "result: bench/results/$LABEL.json"
