set root [file normalize [file join [file dirname [info script]] ..]]
set sim_name vga_stream_sim
create_project $sim_name $root/build/$sim_name -part xc7z020clg484-1 -force
add_files [glob $root/pl/*.v]
add_files -fileset sim_1 $root/sim/tb_vga_stream.sv
set_property top tb_vga_stream [get_filesets sim_1]

set_property xsim.simulate.runtime 201ms [get_filesets sim_1]
set_property xsim.simulate.log_all_signals false [get_filesets sim_1]
set_property xsim.simulate.custom_tcl $root/sim/run_vga_stream.tcl [get_filesets sim_1]
launch_simulation -simset sim_1 -mode behavioral
close_sim
set result_file [file join $root build $sim_name ${sim_name}.sim sim_1 behav xsim simulate.log]
set fp [open $result_file r]
set result [read $fp]
close $fp
if {![string match "*PASS: VGA stream*" $result] || [string match "*Fatal:*" $result]} {error "RTL test did not pass: $result_file"}
close_project
