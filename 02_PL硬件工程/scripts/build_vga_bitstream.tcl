# Explicit hardware readiness gate. No overrides to NSTD/UCIO DRC severity.
set root [file normalize [file join [file dirname [info script]] ..]]
# The user authorized the supplied board reference. Physical DDR validation is
# recorded separately; generating a candidate bitstream is not a boot-test claim.
if {![file exists $root/config/board_reference.tcl] && ![file exists $root/config/board_verified.tcl]} {error "Missing reviewed PS/DDR preset"}
if {![file exists $root/config/camera_pins.xdc]} {error "Missing actual camera wiring and electrical/timing constraints"}
# Rebuild from current reviewed configuration; do not trust stale projects.
source $root/scripts/create_vivado_vga.tcl
source $root/scripts/verify_uart1_bd.tcl
if {!$BOARD_CONFIG_VERIFIED && !$BOARD_CONFIG_REVIEWED} {error "Board preset has not been reviewed"}
launch_runs synth_1 -jobs 2
wait_on_run synth_1
if {[get_property PROGRESS [get_runs synth_1]] ne "100%"} {error "Synthesis failed"}
open_run synth_1
foreach pattern {*/published_metadata_reg* */metadata_stage1_reg* */done_toggle_reg */request_toggle_reg} {
 if {[llength [get_cells -hier -filter "NAME =~ $pattern"]] == 0} {error "Missing custom CDC endpoint: $pattern"}
}
foreach p [get_ports -filter {DIRECTION != "INOUT" || NAME =~ "cam_*"}] {
 set name [get_property NAME $p]
 # PS DDR/FIXED_IO have dedicated hard pins, handled by the PS IP.
 if {[string match "DDR*" $name] || [string match "FIXED_IO*" $name]} {continue}
 if {[get_property PACKAGE_PIN $p] eq "" || [get_property IOSTANDARD $p] eq "DEFAULT"} {
  error "Unconstrained physical port $name"
 }
}
# CDC constraints must be reviewed against final clock and I/O timing.
if {![file exists $root/config/timing_verified.xdc]} {error "Missing reviewed timing_verified.xdc (CDC and sensor I/O timing)"}
foreach expression {{.*mask_display/inst/req_toggle_reg} {.*mask_display/inst/ack_toggle_reg} {.*mask_display/inst/mail_s1_reg\[[0-9]+\]}} {
 if {![llength [get_cells -hier -regexp $expression]]} {error "Missing display CDC endpoint: $expression"}
}
close_design
set_property STEPS.OPT_DESIGN.TCL.PRE $root/scripts/display_pre_opt.tcl [get_runs impl_1]

launch_runs impl_1 -to_step route_design -jobs 2
wait_on_run impl_1
if {[get_property PROGRESS [get_runs impl_1]] ne "100%"} {error "Implementation failed"}
open_run impl_1
report_timing_summary -file $root/build/vga_implemented_timing.rpt
report_drc -file $root/build/vga_implemented_drc.rpt
report_utilization -file $root/build/hdmi_utilization.rpt
report_clocks -file $root/build/hdmi_clocks.rpt
report_cdc -details -file $root/build/vga_implemented_cdc.rpt
report_bus_skew -file $root/build/vga_implemented_bus_skew.rpt
report_timing -from [get_ports {cam_data[*] cam_href cam_vsync}] -delay_type min_max -max_paths 20 -file $root/build/vga_camera_io_timing.rpt
write_checkpoint -force $root/build/vga_system_routed.dcp
set setup [get_timing_paths -delay_type max -max_paths 1]
set hold [get_timing_paths -delay_type min -max_paths 1]
if {[llength $setup]==0 || [llength $hold]==0} {error "No timing paths; inspect constraints"}
if {[get_property SLACK $setup]<0 || [get_property SLACK $hold]<0} {error "Timing not closed"}
source $root/scripts/verify_uart1_implemented.tcl
source $root/scripts/verify_hdmi_implemented.tcl
write_bitstream -force $root/build/vga_system.bit
write_hwdef -force -file $root/build/vga_system.hwdef
write_sysdef -force -hwdef $root/build/vga_system.hwdef -bitfile $root/build/vga_system.bit -file $root/build/vga_system.hdf
puts "Exported hardware; bootloader/Linux image and physical tests are still required."
