#!/bin/bash
set -euo pipefail
r=/home/huzhen/hdmi_linux_integration_20261102
[ -d "$r/device-tree-xlnx/.git" ] || git clone --no-hardlinks /home/huzhen/zynq_projects/zynq_ov5640/build/downloads/git2/github.com.xilinx.device-tree-xlnx.git "$r/device-tree-xlnx"
git -C "$r/device-tree-xlnx" checkout 73e546e312
DISPLAY=${DISPLAY:-:0} /home/huzhen/petalinux/2019.1/tools/xsct/bin/xsct "$r/scripts/generate_dt.tcl"
