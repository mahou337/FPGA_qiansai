#!/bin/bash
set -euo pipefail
r=/home/huzhen/hdmi_linux_integration_20261102
mkdir -p "$r/integrated-dt"
cp -a "$r/generated-dt/." "$r/integrated-dt/"
cp /home/huzhen/linux_stage1_20261030/build/device-tree/system-user.dtsi "$r/integrated-dt/"
cp /home/huzhen/linux_stage1_20261030/build/device-tree/system-conf.dtsi "$r/integrated-dt/"
cat >> "$r/integrated-dt/system-user.dtsi" <<'EOF'
/ { gesture-hand,hardware-id = "uart1-emio-f18-e18-20261101"; };
&uart1 {
 status = "okay";
 cts-override;
 /delete-property/ device_type;
 /delete-property/ port-number;
};
/* Amend the actual HSI-generated node; no duplicate 0x43c00000 node. */
&mask_display {
 compatible = "hellofpga,mask-display-1.0";
 reg = <0x43c00000 0x00080000>;
 clocks = <&clkc 15>;
 clock-names = "s_axi_aclk";
 status = "okay";
};
EOF
printf '
/include/ "system-user.dtsi"
' >> "$r/integrated-dt/system-top.dts"
w=$(find /home/huzhen/zynq_projects/zynq_ov5640/build/tmp/work/plnx_zynq7-xilinx-linux-gnueabi/linux-xlnx -mindepth 1 -maxdepth 1 -type d | head -1)
export PATH="$w/recipe-sysroot-native/usr/bin/arm-xilinx-linux-gnueabi:$w/recipe-sysroot-native/usr/bin:$PATH"
dtc=/home/huzhen/zynq_projects/zynq_ov5640/build/tmp/sysroots-components/x86_64/dtc-native/usr/bin/dtc
arm-xilinx-linux-gnueabi-gcc -E -P -x assembler-with-cpp -nostdinc -undef -D__DTS__ -I "$r/integrated-dt" "$r/integrated-dt/system-top.dts" > "$r/integrated-dt/system-top.pre.dts"
"$dtc" -I dts -O dtb -i "$r/integrated-dt" -o "$r/candidate/system.dtb" "$r/integrated-dt/system-top.pre.dts"
"$dtc" -I dtb -O dts -o "$r/candidate/system.dts" "$r/candidate/system.dtb"
cp "$r/integrated-dt/system-user.dtsi" "$r/petalinux_project/project-spec/meta-user/recipes-bsp/device-tree/files/"
