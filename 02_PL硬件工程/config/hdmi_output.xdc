# Smart ZYNQ SL schematic U33C bank34=3.3V, HDMI output J29.
set_property PACKAGE_PIN N22 [get_ports hdmi_clk_p]
set_property PACKAGE_PIN P22 [get_ports hdmi_clk_n]
set_property PACKAGE_PIN M21 [get_ports {hdmi_data_p[0]}]
set_property PACKAGE_PIN M22 [get_ports {hdmi_data_n[0]}]
set_property PACKAGE_PIN L21 [get_ports {hdmi_data_p[1]}]
set_property PACKAGE_PIN L22 [get_ports {hdmi_data_n[1]}]
set_property PACKAGE_PIN J21 [get_ports {hdmi_data_p[2]}]
set_property PACKAGE_PIN J22 [get_ports {hdmi_data_n[2]}]
set_property IOSTANDARD TMDS_33 [get_ports {hdmi_clk_* hdmi_data_*}]
# CDC mailbox is held until ACK, with 2 data stages and 3 request stages.
# Bound ONLY source -> first synchronizer stage, not subsequent stages or clocks.
set md_src [get_cells -hier -regexp {.*mask_display/inst/(req_toggle_reg|req_bank_reg|req_mode_reg\[[0-9]+\])}]
set md_dst [get_cells -hier -regexp {.*mask_display/inst/(req_sync_reg\[0\]|mail_s1_reg\[[0-9]+\])}]
set md_ack_src [get_cells -hier -regexp {.*mask_display/inst/ack_toggle_reg}]
set md_ack_dst [get_cells -hier -regexp {.*mask_display/inst/ack_sync_reg\[0\]}]
set_max_delay -datapath_only 20.0 -from $md_src -to $md_dst
set_bus_skew 10.0 -from $md_src -to $md_dst
set_max_delay -datapath_only 10.0 -from $md_ack_src -to $md_ack_dst
# Async assertion enters only three-stage reset-release synchronizers.
# Functional reset consumers remain timed. This is not a data-path exception.
set_false_path -to [get_pins -hier -regexp {.*mask_display/inst/(pix_release_reg|sys_release_reg)\[[0-9]+\]/CLR}]
