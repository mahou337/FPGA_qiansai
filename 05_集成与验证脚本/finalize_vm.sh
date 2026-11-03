#!/bin/bash
set -euo pipefail
r=/home/huzhen/hdmi_linux_integration_20261102
cp /home/huzhen/linux_stage1_20261030/build/kernel-obj/.config "$r/backup/kernel.config"
cp /home/huzhen/linux_stage1_20261030/build/kernel-obj/Module.symvers "$r/backup/Module.symvers"
cp -a /home/huzhen/linux_stage1_20261030/delivery/source/linux "$r/backup/camera-driver-source"
cp -a /home/huzhen/linux_stage1_20261030/delivery/artifacts/boot "$r/backup/stage1_boot_aux"
mkdir -p "$r/candidate/rootfs-overlay/lib/modules/4.19.0-xilinx-v2019.1/extra"
cp "$r/candidate/gesture_mask_display.ko" "$r/candidate/rootfs-overlay/lib/modules/4.19.0-xilinx-v2019.1/extra/"
recipe="$r/petalinux_project/project-spec/meta-user/recipes-modules/gesture-mask-display"
mkdir -p "$recipe/files"
cp "$r/linux/gesture-mask-display.bb" "$recipe/"
cp "$r/linux/Makefile" "$r/linux/gesture_mask_display.c" "$r/linux/gesture_mask_display.h" "$recipe/files/"
modprobe --dump-modversions "$r/candidate/gesture_mask_display.ko" > "$r/evidence/module_symbol_versions.txt"
file "$r/candidate/gesture_mask_display.ko" > "$r/evidence/module_elf.txt"
find "$r/backup" -type f -print0 | sort -z | xargs -0 sha256sum > "$r/evidence/backup.sha256"
