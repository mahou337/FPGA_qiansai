# Explicit hardware readiness gate. No overrides to NSTD/UCIO DRC severity.
set root [file normalize [file join [file dirname [info script]] ..]]
if {![file exists $root/config/board_verified.tcl]} {error "Missing validated board PS/DDR preset"}
if {![file exists $root/config/camera_pins.xdc]} {error "Missing actual camera wiring and electrical/timing constraints"}
# Rebuild from current reviewed configuration; do not trust stale projects.
source $root/scripts/create_vivado.tcl
if {!$BOARD_CONFIG_VERIFIED} {error "Board preset has not been verified"}
launch_runs synth_1 -jobs 2
wait_on_run synth_1
if {[get_property PROGRESS [get_runs synth_1]] ne "100%"} {error "Synthesis failed"}
open_run synth_1
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
close_design
add_files -fileset constrs_1 $root/config/timing_verified.xdc
launch_runs impl_1 -to_step route_design -jobs 2
wait_on_run impl_1
if {[get_property PROGRESS [get_runs impl_1]] ne "100%"} {error "Implementation failed"}
open_run impl_1
report_timing_summary -file $root/build/implemented_timing.rpt
report_drc -file $root/build/implemented_drc.rpt
report_cdc -details -file $root/build/implemented_cdc.rpt
set setup [get_timing_paths -delay_type max -max_paths 1]
set hold [get_timing_paths -delay_type min -max_paths 1]
if {[llength $setup]==0 || [llength $hold]==0} {error "No timing paths; inspect constraints"}
if {[get_property SLACK $setup]<0 || [get_property SLACK $hold]<0} {error "Timing not closed"}
write_bitstream -force $root/build/system.bit
write_hwdef -force -file $root/build/system.hwdef
write_sysdef -force -hwdef $root/build/system.hwdef -bitfile $root/build/system.bit -file $root/build/system.hdf
puts "Exported hardware; bootloader/Linux image and physical tests are still required."
