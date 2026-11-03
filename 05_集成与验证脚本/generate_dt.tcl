set r /home/huzhen/hdmi_linux_integration_20261102
hsi set_repo_path $r/device-tree-xlnx
set hw [hsi open_hw_design $r/handoff_original/hardware/system.hdf]
hsi create_sw_design device-tree -os device_tree -proc ps7_cortexa9_0
hsi generate_target -dir $r/generated-dt
hsi close_hw_design $hw
exit
