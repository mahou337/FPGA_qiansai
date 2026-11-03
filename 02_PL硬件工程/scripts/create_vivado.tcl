set root [file normalize [file join [file dirname [info script]] ..]]
create_project gesture_zynq $root/build/vivado -part xc7z020clg484-1 -force
set_property target_language Verilog [current_project]
add_files [glob $root/pl/*.v]
create_bd_design system
create_bd_cell -type ip -vlnv xilinx.com:ip:processing_system7:5.5 ps7
set BOARD_CONFIG_VERIFIED 0
set BOARD_CONFIG_SOURCE {unverified scaffold}
if {[file exists $root/config/board_verified.tcl]} {
 source $root/config/board_verified.tcl
} elseif {[file exists $root/config/board_reference.tcl]} {
 source $root/config/board_reference.tcl
 puts "Using imported BRAM board reference; physical validation is still pending."
} else {
 source $root/config/board_unverified.tcl
 puts "WARNING: DDR configuration is a synthesis scaffold; not validated for boot."
}
set_property -dict [list CONFIG.PCW_USE_M_AXI_GP0 {1} CONFIG.PCW_EN_CLK0_PORT {1} \
 CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ {50} CONFIG.PCW_EN_RST0_PORT {1} \
 CONFIG.PCW_UART0_PERIPHERAL_ENABLE {1} CONFIG.PCW_UART1_PERIPHERAL_ENABLE {0} \
 CONFIG.PCW_UART0_UART0_IO {EMIO} CONFIG.PCW_UART0_GRP_FULL_ENABLE {0}] [get_bd_cells ps7]
make_bd_intf_pins_external [get_bd_intf_pins ps7/DDR]
make_bd_intf_pins_external [get_bd_intf_pins ps7/FIXED_IO]
create_bd_cell -type module -reference gesture_capture_axi capture
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_interconnect:2.1 axi
set_property CONFIG.NUM_MI {1} [get_bd_cells axi]
create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset:5.0 reset
create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant:1.1 one
set_property CONFIG.CONST_VAL {1} [get_bd_cells one]
connect_bd_intf_net [get_bd_intf_pins ps7/M_AXI_GP0] [get_bd_intf_pins axi/S00_AXI]
connect_bd_intf_net [get_bd_intf_pins axi/M00_AXI] [get_bd_intf_pins capture/s_axi]
connect_bd_net [get_bd_pins ps7/FCLK_CLK0] [get_bd_pins ps7/M_AXI_GP0_ACLK] \
 [get_bd_pins axi/ACLK] [get_bd_pins axi/S00_ACLK] [get_bd_pins axi/M00_ACLK] \
 [get_bd_pins capture/s_axi_aclk] [get_bd_pins reset/slowest_sync_clk]
connect_bd_net [get_bd_pins ps7/FCLK_RESET0_N] [get_bd_pins reset/ext_reset_in]
connect_bd_net [get_bd_pins one/dout] [get_bd_pins reset/dcm_locked]
connect_bd_net [get_bd_pins reset/interconnect_aresetn] [get_bd_pins axi/ARESETN] [get_bd_pins axi/S00_ARESETN] [get_bd_pins axi/M00_ARESETN]
connect_bd_net [get_bd_pins reset/peripheral_aresetn] [get_bd_pins capture/s_axi_aresetn]
foreach pin {cam_pclk cam_vsync cam_href cam_data cam_reset_n cam_pwdn cam_scl cam_sda} {
 set port [make_bd_pins_external [get_bd_pins capture/$pin]]
 if {$pin eq "cam_reset_n"} {set_property name cam_rst_n [get_bd_ports ${pin}_0]} else {set_property name $pin [get_bd_ports ${pin}_0]}
}
create_bd_port -dir O uart_tx
create_bd_port -dir I uart_rx
connect_bd_net [get_bd_ports uart_tx] [get_bd_pins ps7/UART0_TX]
connect_bd_net [get_bd_ports uart_rx] [get_bd_pins ps7/UART0_RX]
assign_bd_address -offset 0x40000000 -range 0x00040000 -target_address_space [get_bd_addr_spaces ps7/Data] [get_bd_addr_segs capture/s_axi/Reg]
validate_bd_design
save_bd_design
set bd [get_files system.bd]
generate_target all $bd
make_wrapper -files $bd -top
add_files $root/build/vivado/gesture_zynq.srcs/sources_1/bd/system/hdl/system_wrapper.v
set_property top system_wrapper [current_fileset]
add_files -fileset constrs_1 $root/config/known_board.xdc
if {[file exists $root/config/camera_pins.xdc]} {add_files -fileset constrs_1 $root/config/camera_pins.xdc}
update_compile_order -fileset sources_1
set fp [open $root/build/board_validation.txt w]
puts $fp "BOARD_CONFIG_SOURCE=$BOARD_CONFIG_SOURCE"
puts $fp "BOARD_CONFIG_VERIFIED=$BOARD_CONFIG_VERIFIED"
puts $fp "Camera pin map present: [file exists $root/config/camera_pins.xdc]"
puts $fp "No bitstream/boot image created. DDR/IO/timing and actual device must be verified."
close $fp
puts "Created $root/build/vivado/gesture_zynq.xpr"
