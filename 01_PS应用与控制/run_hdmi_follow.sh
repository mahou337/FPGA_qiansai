#!/bin/sh
set -eu
base=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
export PYTHONDONTWRITEBYTECODE=1
[ "$#" = 0 ] || { echo "No extra arguments accepted" >&2; exit 2; }
exec python3 -B "$base/start_hdmi_follow.py"
