#!/bin/bash
set -euo pipefail
r=/home/huzhen/hdmi_linux_integration_20261102
cd "$r"
for mode in off mock missing; do
 bash /home/huzhen/linux_stage2_20261030/tools/target_python.sh -B scripts/replay_actual.py --mode "$mode" > "logs/replay_$mode.log" 2>&1
done
