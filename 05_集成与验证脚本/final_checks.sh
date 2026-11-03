#!/bin/bash
set -euo pipefail
r=/home/huzhen/hdmi_linux_integration_20261102
cd "$r"
python3 -B -m unittest discover -s tests -v > logs/native_tests_final.log 2>&1
bash scripts/run_arm_tests.sh
bash scripts/run_replay.sh
bash /home/huzhen/linux_stage2_20261030/tools/target_python.sh -B delivery/app/ps/run.py --help > logs/arm_help.log
bash /home/huzhen/linux_stage2_20261030/tools/target_python.sh -B ps_display/replay_benchmark.py --help > logs/arm_benchmark_help.log
bash /home/huzhen/linux_stage2_20261030/tools/target_python.sh -B scripts/target_compatibility.py > logs/target_compatibility.log
