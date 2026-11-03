#!/bin/bash
set -euo pipefail
r=/home/huzhen/hdmi_linux_integration_20261102
cd "$r"
arm=/home/huzhen/linux_stage2_20261030/tools/target_python.sh
bash "$arm" -B scripts/prepare_replay_input.py
bash "$arm" -B ps_display/replay_benchmark.py --factory actual_adapter:make_recognizer --frames evidence/replay-input/replay.npy --rounds 3 --output evidence/adapter_off.json > logs/adapter_off.log 2>&1
set +e
bash "$arm" -B ps_display/replay_benchmark.py --factory actual_adapter:make_recognizer --frames evidence/replay-input/replay.npy --rounds 3 --output evidence/adapter_device_missing.json --hdmi > logs/adapter_device_missing.log 2>&1
rc=$?
set -e
echo "Missing-device benchmark expected rc=1, actual=$rc" > evidence/adapter_missing_exit.txt
[ "$rc" = 1 ]
