set root [file normalize [file join [file dirname [info script]] ..]]
read_verilog [glob $root/pl/*.v]
synth_design -top gesture_capture_axi -part xc7z020clg484-1 -mode out_of_context
create_clock -name axi_clk -period 20 [get_ports s_axi_aclk]
create_clock -name cam_pclk -period 41.667 [get_ports cam_pclk]
report_utilization -file $root/build/capture_utilization.rpt
report_timing_summary -file $root/build/capture_synth_timing.rpt
report_cdc -details -file $root/build/capture_cdc.rpt
write_checkpoint -force $root/build/capture_synth.dcp
