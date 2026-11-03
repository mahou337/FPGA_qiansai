# User-specified input delays at FPGA pins, 2026-10-29.
# 0x4740[5]=1: sensor updates DVP on PCLK falling edge; capture is rising.
# Both min and max are relative to the falling launch edge, not the sample edge.
set_input_delay -clock [get_clocks cam_pclk] -clock_fall -min 0.000 [get_ports {cam_data[*] cam_href cam_vsync}]
set_input_delay -clock [get_clocks cam_pclk] -clock_fall -max 8.000 [get_ports {cam_data[*] cam_href cam_vsync}]

# Only asynchronous control pins are excluded. Do not false-path DVP data/sync.
set_false_path -from [get_ports {cam_scl cam_sda uart_rx}]
set_false_path -to [get_ports {cam_scl cam_sda cam_rst_n cam_pwdn uart_tx}]

# Bundled metadata is frozen until the next request. Done has three stages,
# metadata two. Bound the bus transport to one 50 MHz destination cycle.
set meta_src [get_cells -hier -filter {NAME =~ */published_metadata_reg*}]
set meta_dst [get_cells -hier -filter {NAME =~ */metadata_stage1_reg*}]
set_max_delay -datapath_only 20.000 -from $meta_src -to $meta_dst
set_bus_skew 20.000 -from $meta_src -to $meta_dst
set_max_delay -datapath_only 20.000 -from [get_cells -hier -filter {NAME =~ */done_toggle_reg}] -to [get_cells -hier -regexp {.*done_sync_reg\[0\]}]
set_max_delay -datapath_only 23.809524 -from [get_cells -hier -filter {NAME =~ */request_toggle_reg}] -to [get_cells -hier -regexp {.*req_sync_reg\[0\]}]
# Asynchronous assertion enters only the common PCLK reset synchronizer.
set_false_path -to [get_pins -hier -filter {NAME =~ */capture/reset_sync_reg*/CLR}]
# Xilinx XPM asynchronous FIFO constraints are supplied by the IP itself.
