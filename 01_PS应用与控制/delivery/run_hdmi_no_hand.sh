#!/bin/sh
set -eu
base=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
export PYTHONDONTWRITEBYTECODE=1
# No --hand: existing application never constructs HandBridge or opens servo UART.
# Fixed arguments deliberately refuse forwarding arbitrary motion options.
[ "$#" = 0 ] || { echo "No extra arguments accepted" >&2; exit 2; }
python3 -B "$base/verify_files.py"
exec python3 -B "$base/app/launch.py" --hardware --automatic --no-images --hdmi --hdmi-hz 5 --max-mib 256
