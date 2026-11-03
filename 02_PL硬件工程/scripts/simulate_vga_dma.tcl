set root [file normalize [file join [file dirname [info script]] ..]]
set sim_name vga_dma_sim
if {$argc>0 && [lindex $argv 0] eq "smoke"} {set sim_name vga_dma_smoke}
create_project $sim_name $root/build/$sim_name -part xc7z020clg484-1 -force
add_files [glob $root/pl/*.v]
set iproot $root/build/vivado_vga/gesture_vga.srcs/sources_1/bd/system/ip
read_ip $iproot/system_dma_0/system_dma_0.xci
read_ip $iproot/system_camera_fifo_0/system_camera_fifo_0.xci
add_files -fileset sim_1 $root/sim/tb_vga_dma.sv
set_property top tb_vga_dma [get_filesets sim_1]
if {$sim_name eq "vga_dma_smoke"} {set_property generic {W=128 H=64} [get_filesets sim_1]}
set_property xsim.simulate.runtime 251ms [get_filesets sim_1]
set_property xsim.simulate.log_all_signals false [get_filesets sim_1]
set_property xsim.simulate.custom_tcl $root/sim/run_vga_dma.tcl [get_filesets sim_1]
launch_simulation -simset sim_1 -mode behavioral
close_sim
set fp [open $root/build/$sim_name/${sim_name}.sim/sim_1/behav/xsim/simulate.log r]
set result [read $fp]
close $fp
if {![string match "*PASS: VGA DMA/FIFO*" $result] || [string match "*Fatal:*" $result]} {error "DMA integration test failed"}
close_project
