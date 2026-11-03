set root [file normalize [file join [file dirname [info script]] ..]]
open_project $root/build/vivado_vga/gesture_vga.xpr
# Rebuild module-reference output products as well as the top run after RTL edits.
set bd [get_files */system.bd]
open_bd_design $bd
update_compile_order -fileset sources_1
update_module_reference [get_ips system_capture_0]
validate_bd_design
save_bd_design
reset_target all $bd
generate_target all $bd
foreach run [get_runs -filter {IS_SYNTHESIS == 1}] {
    if {[get_property PROGRESS $run] ne "0%"} {reset_run $run}
}
if {[get_property PROGRESS [get_runs synth_1]] ne "0%"} {reset_run synth_1}
launch_runs synth_1 -jobs 2
wait_on_run synth_1
if {[get_property PROGRESS [get_runs synth_1]] ne "100%"} {error "System synthesis failed"}
open_run synth_1
set fp [open $root/build/vga_package_pins.txt w]
foreach name {G16 F16 D20 D18 E15 D15 D16 D17 C15 B15 C20 G15 E16 C19 A17} {
 set pin [get_package_pins $name]
 puts $fp "$name BANK=[get_property BANK $pin] PIN_FUNC=[get_property PIN_FUNC $pin]"
}
close $fp

report_utilization -file $root/build/vga_system_utilization.rpt
report_cdc -details -file $root/build/vga_system_cdc.rpt
report_timing_summary -file $root/build/vga_system_synth_timing.rpt
write_checkpoint -force $root/build/vga_system_synth.dcp
close_project


