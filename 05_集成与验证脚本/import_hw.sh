#!/bin/bash
set -eo pipefail
r=/home/huzhen/hdmi_linux_integration_20261102
cp -a /home/huzhen/zynq_projects/zynq_ov5640/.petalinux "$r/petalinux_project/"
source /home/huzhen/petalinux/2019.1/settings.sh
cd "$r/petalinux_project"
petalinux-config --get-hw-description="$r/handoff_original/hardware" --oldconfig > "$r/logs/hardware_import_retry.log" 2>&1
