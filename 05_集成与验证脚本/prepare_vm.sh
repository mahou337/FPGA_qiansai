#!/bin/bash
set -euo pipefail
r=/home/huzhen/hdmi_linux_integration_20261102
k=/home/huzhen/linux_stage1_20261030/build/kernel-obj
cp -a --reflink=auto "$k" "$r/kernel-obj"
find /home/huzhen/linux_stage1_20261030 -name gesture_vga.ko -print > "$r/evidence/camera_module_locations.txt"
sha256sum "$k/Module.symvers" "$k/.config" "$k/arch/arm/boot/zImage" > "$r/evidence/kernel_baseline.sha256"
find "$r/backup" -type f -print0 | sort -z | xargs -0 sha256sum > "$r/evidence/backup.sha256"
cp -a /home/huzhen/zynq_projects/zynq_ov5640/.petalinux "$r/petalinux_project/"
source /home/huzhen/petalinux/2019.1/settings.sh
cd "$r/petalinux_project"
petalinux-config --get-hw-description="$r/handoff_original/hardware" --oldconfig > "$r/logs/hardware_import.log" 2>&1
