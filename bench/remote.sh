#!/usr/bin/env bash
# Run the benchmark on a fresh EC2 instance and copy the result back.
#
#   bench/remote.sh <host> <label> [--cool] [--price 0.1234]
#
# <host>  ssh target (ubuntu@ec2-...). Ubuntu 24.04 assumed (COOL AMI is Ubuntu 24.04).
# --cool  use the AMI's preinstalled OpenCV (COOL) instead of the PyPI wheel. The harness then
#         imports whatever `python3 -c "import cv2"` finds on the AMI and records its build info
#         and library paths as evidence.
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
ssh "$HOST" bash -s <<REMOTE
set -euo pipefail
cd ~/steadyframe
sudo apt-get update -qq && sudo apt-get install -y -qq python3-venv python3-pip rsync >/dev/null
if [ "$COOL" = "1" ]; then
  # keep the AMI's OpenCV: create the venv with system site packages and install everything but the wheel
  python3 -m venv --system-site-packages .venv
  .venv/bin/pip install -q --upgrade pip
  grep -v -i opencv requirements.lock > /tmp/req.txt
  .venv/bin/pip install -q -r /tmp/req.txt
  .venv/bin/pip install -q -e . --no-deps
  .venv/bin/python -c "import cv2; print('COOL cv2', cv2.__version__, cv2.__file__)"
else
  python3 -m venv .venv
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install -q -r requirements.lock
  .venv/bin/pip install -q -e . --no-deps
fi
.venv/bin/python -m bench.run --out bench/results --label "$LABEL" --reps 10 ${PRICE:+--price-per-hour $PRICE}
REMOTE
mkdir -p "$REPO/bench/results"
rsync -az "$HOST:~/steadyframe/bench/results/$LABEL.json" "$HOST:~/steadyframe/bench/results/$LABEL.buildinfo.txt" "$REPO/bench/results/"
echo "result: bench/results/$LABEL.json"
