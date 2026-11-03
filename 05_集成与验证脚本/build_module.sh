#!/bin/bash
set -euo pipefail
r=/home/huzhen/hdmi_linux_integration_20261102
w=$(find /home/huzhen/zynq_projects/zynq_ov5640/build/tmp/work/plnx_zynq7-xilinx-linux-gnueabi/linux-xlnx -mindepth 1 -maxdepth 1 -type d | head -1)
export PATH="$w/recipe-sysroot-native/usr/bin/arm-xilinx-linux-gnueabi:$w/recipe-sysroot-native/usr/bin:$PATH"
make -C "$r/linux" KERNEL_SRC="$r/kernel-obj" ARCH=arm CROSS_COMPILE=arm-xilinx-linux-gnueabi- -j2
modinfo "$r/linux/gesture_mask_display.ko"
cp "$r/linux/gesture_mask_display.ko" "$r/candidate/"
cp /home/huzhen/linux_stage1_20261030/artifacts/modules/gesture_vga.ko "$r/backup/"
modinfo "$r/backup/gesture_vga.ko"
sha256sum "$r/kernel-obj/Module.symvers" "$r/kernel-obj/.config"
