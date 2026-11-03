#!/bin/bash
set -euo pipefail
r=/home/huzhen/hdmi_linux_integration_20261102
cd "$r"
export HAND_TEST_QEMU=1
export DIAG_TEST_PYTHON='["bash","/home/huzhen/linux_stage2_20261030/tools/target_python.sh"]'
bash /home/huzhen/linux_stage2_20261030/tools/target_python.sh -B -m unittest discover -s tests -v > logs/arm_tests.log 2>&1
