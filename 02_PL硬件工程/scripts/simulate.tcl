set root [file normalize [file join [file dirname [info script]] ..]]
set sim_name capture_sim
if {$argc>0 && [lindex $argv 0] eq "full"} {set sim_name capture_sim_full}
create_project $sim_name $root/build/$sim_name -part xc7z020clg484-1 -force
add_files [glob $root/pl/*.v]
add_files -fileset sim_1 $root/sim/tb_capture.sv
set_property top tb_capture [get_filesets sim_1]
if {$sim_name eq "capture_sim_full"} {set_property generic {W=320 H=240} [get_filesets sim_1]}
set_property xsim.simulate.runtime 51ms [get_filesets sim_1]
set_property xsim.simulate.log_all_signals false [get_filesets sim_1]
launch_simulation -simset sim_1 -mode behavioral
close_sim
set result_file [file join $root build $sim_name ${sim_name}.sim sim_1 behav xsim simulate.log]
set fp [open $result_file r]
set result [read $fp]
close $fp
if {![string match "*PASS: AXI*" $result] || [string match "*Fatal:*" $result]} {error "RTL test did not pass: $result_file"}
close_project
