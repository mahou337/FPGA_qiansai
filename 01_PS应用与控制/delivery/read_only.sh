#!/bin/sh
set -eu
base=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
export PYTHONDONTWRITEBYTECODE=1
python3 -B "$base/verify_files.py"
exec python3 -B "$base/app/ps/hand_worker.py" --probe
