set root [file normalize [file join [file dirname [info script]] ..]]
create_project gesture_vga $root/build/vivado_vga -part xc7z020clg484-1 -force
set_property target_language Verilog [current_project]
add_files [glob $root/pl/*.v]
set_property ip_repo_paths [list $root/ip] [current_project]
update_ip_catalog
create_bd_design system
create_bd_cell -type ip -vlnv xilinx.com:ip:processing_system7:5.5 ps7
set BOARD_CONFIG_REVIEWED 0
set BOARD_CONFIG_VERIFIED 0
set BOARD_CONFIG_SOURCE {unverified scaffold}
if {[file exists $root/config/board_verified.tcl]} {
 source $root/config/board_verified.tcl
} elseif {[file exists $root/config/board_reference.tcl]} {
 source $root/config/board_reference.tcl
 set BOARD_CONFIG_REVIEWED 1
 puts "Using imported BRAM board reference; physical validation is still pending."
} else {
 source $root/config/board_unverified.tcl
 puts "WARNING: DDR configuration is a synthesis scaffold; not validated for boot."
}
set_property -dict [list CONFIG.PCW_USE_S_AXI_HP0 {1} CONFIG.PCW_S_AXI_HP0_DATA_WIDTH {64} CONFIG.PCW_USE_M_AXI_GP0 {1} CONFIG.PCW_EN_CLK0_PORT {1} \
 CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ {50} CONFIG.PCW_EN_RST0_PORT {1} \
 CONFIG.PCW_UART0_PERIPHERAL_ENABLE {1} CONFIG.PCW_UART1_PERIPHERAL_ENABLE {1} \
 CONFIG.PCW_UART0_UART0_IO {EMIO} CONFIG.PCW_UART0_GRP_FULL_ENABLE {0} \
 CONFIG.PCW_UART1_UART1_IO {EMIO} CONFIG.PCW_UART1_GRP_FULL_ENABLE {0}] [get_bd_cells ps7]
make_bd_intf_pins_external [get_bd_intf_pins ps7/DDR]
make_bd_intf_pins_external [get_bd_intf_pins ps7/FIXED_IO]
create_bd_cell -type module -reference gesture_camera_vga capture
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_interconnect:2.1 axi
set_property CONFIG.NUM_MI {3} [get_bd_cells axi]
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
foreach pin {cam_pclk cam_vsync cam_href cam_data cam_rst_n cam_pwdn cam_scl cam_sda} {
 set port [make_bd_pins_external [get_bd_pins capture/$pin]]
 if {$pin eq "cam_reset_n"} {set_property name cam_rst_n [get_bd_ports ${pin}_0]} else {set_property name $pin [get_bd_ports ${pin}_0]}
}
create_bd_port -dir O uart_tx
create_bd_port -dir I uart_rx
connect_bd_net [get_bd_ports uart_tx] [get_bd_pins ps7/UART0_TX]
connect_bd_net [get_bd_ports uart_rx] [get_bd_pins ps7/UART0_RX]

# Dedicated PS UART1 through EMIO for the external servo adapter.
# UART0 console pins, clock and baud preset remain unchanged.
create_bd_port -dir O uart1_tx
create_bd_port -dir I uart1_rx
connect_bd_net [get_bd_ports uart1_tx] [get_bd_pins ps7/UART1_TX]
connect_bd_net [get_bd_ports uart1_rx] [get_bd_pins ps7/UART1_RX]
# Full VGA -> async FIFO -> AXI DMA S2MM -> PS DDR through HP0.
create_bd_cell -type ip -vlnv xilinx.com:ip:axis_data_fifo:2.0 camera_fifo
set_property -dict [list CONFIG.TDATA_NUM_BYTES {4} CONFIG.HAS_TKEEP {1} CONFIG.HAS_TLAST {1} CONFIG.IS_ACLK_ASYNC {1} CONFIG.FIFO_DEPTH {2048}] [get_bd_cells camera_fifo]
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_dma:7.1 dma
set_property -dict [list CONFIG.c_include_sg {0} CONFIG.c_include_mm2s {0} CONFIG.c_include_s2mm {1} CONFIG.c_sg_length_width {23} CONFIG.c_m_axi_s2mm_data_width {64} CONFIG.c_s2mm_burst_size {16}] [get_bd_cells dma]
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_interconnect:2.1 memory_axi
set_property CONFIG.NUM_MI {1} [get_bd_cells memory_axi]
connect_bd_intf_net [get_bd_intf_pins capture/m_axis] [get_bd_intf_pins camera_fifo/S_AXIS]
connect_bd_intf_net [get_bd_intf_pins camera_fifo/M_AXIS] [get_bd_intf_pins dma/S_AXIS_S2MM]
connect_bd_intf_net [get_bd_intf_pins axi/M01_AXI] [get_bd_intf_pins dma/S_AXI_LITE]
connect_bd_intf_net [get_bd_intf_pins dma/M_AXI_S2MM] [get_bd_intf_pins memory_axi/S00_AXI]
connect_bd_intf_net [get_bd_intf_pins memory_axi/M00_AXI] [get_bd_intf_pins ps7/S_AXI_HP0]
connect_bd_net [get_bd_ports cam_pclk] [get_bd_pins camera_fifo/s_axis_aclk]
connect_bd_net [get_bd_pins ps7/FCLK_CLK0] [get_bd_pins camera_fifo/m_axis_aclk] \
 [get_bd_pins axi/M01_ACLK] [get_bd_pins dma/s_axi_lite_aclk] [get_bd_pins dma/m_axi_s2mm_aclk] \
 [get_bd_pins memory_axi/ACLK] [get_bd_pins memory_axi/S00_ACLK] [get_bd_pins memory_axi/M00_ACLK] [get_bd_pins ps7/S_AXI_HP0_ACLK]
connect_bd_net [get_bd_pins reset/interconnect_aresetn] [get_bd_pins axi/M01_ARESETN] \
 [get_bd_pins memory_axi/ARESETN] [get_bd_pins memory_axi/S00_ARESETN] [get_bd_pins memory_axi/M00_ARESETN]
# FIFO reset aborts the old packet. DMA uses its software reset after the stream is stopped.
# Keep DMA/interconnect alive to drain in-flight DDR transactions before a DMA buffer is freed.
connect_bd_net [get_bd_pins capture/stream_resetn] [get_bd_pins camera_fifo/s_axis_aresetn]
connect_bd_net [get_bd_pins reset/peripheral_aresetn] [get_bd_pins dma/axi_resetn]
assign_bd_address -offset 0x40000000 -range 0x00040000 -target_address_space [get_bd_addr_spaces ps7/Data] [get_bd_addr_segs capture/s_axi/reg0]
assign_bd_address -offset 0x40400000 -range 0x00010000 -target_address_space [get_bd_addr_spaces ps7/Data] [get_bd_addr_segs dma/S_AXI_LITE/Reg]
assign_bd_address -offset 0x00000000 -range 0x20000000 -target_address_space [get_bd_addr_spaces dma/Data_S2MM] [get_bd_addr_segs ps7/S_AXI_HP0/HP0_DDR_LOWOCM]

# Isolated mask display: GP0 register/BRAM uploads only, no new DDR or IRQ traffic.
create_bd_cell -type module -reference mask_display_axi mask_display
create_bd_cell -type module -reference mask_display_clocks display_clock
create_bd_cell -type ip -vlnv digilentinc.com:ip:rgb2dvi:1.4 hdmi_encoder
set_property -dict [list CONFIG.kGenerateSerialClk {false} CONFIG.kRstActiveHigh {false}] [get_bd_cells hdmi_encoder]
connect_bd_intf_net [get_bd_intf_pins axi/M02_AXI] [get_bd_intf_pins mask_display/s_axi]
connect_bd_net [get_bd_pins ps7/FCLK_CLK0] [get_bd_pins axi/M02_ACLK] [get_bd_pins mask_display/s_axi_aclk] [get_bd_pins display_clock/clk_in1]
connect_bd_net [get_bd_pins reset/interconnect_aresetn] [get_bd_pins axi/M02_ARESETN]
connect_bd_net [get_bd_pins reset/peripheral_aresetn] [get_bd_pins mask_display/s_axi_aresetn] [get_bd_pins display_clock/resetn]
connect_bd_net [get_bd_pins display_clock/clk_out1] [get_bd_pins mask_display/pixel_clk] [get_bd_pins hdmi_encoder/PixelClk]
connect_bd_net [get_bd_pins display_clock/clk_out2] [get_bd_pins hdmi_encoder/SerialClk]
connect_bd_net [get_bd_pins display_clock/locked] [get_bd_pins mask_display/display_locked] [get_bd_pins hdmi_encoder/aRst_n]
foreach {src dst} {video_data vid_pData video_de vid_pVDE video_hs vid_pHSync video_vs vid_pVSync} {
 connect_bd_net [get_bd_pins mask_display/$src] [get_bd_pins hdmi_encoder/$dst]
}
foreach {pin port} {TMDS_Clk_p hdmi_clk_p TMDS_Clk_n hdmi_clk_n TMDS_Data_p hdmi_data_p TMDS_Data_n hdmi_data_n} {
 make_bd_pins_external [get_bd_pins hdmi_encoder/$pin]
 set_property name $port [get_bd_ports ${pin}_0]
}
assign_bd_address -offset 0x43C00000 -range 0x00080000 -target_address_space [get_bd_addr_spaces ps7/Data] [get_bd_addr_segs mask_display/s_axi/reg0]

# Metadata for forwarded TMDS clock; physical generation is in mask_display_clocks.
set_property CONFIG.FREQ_HZ 25200000 [get_bd_pins {hdmi_encoder/TMDS_Clk_p hdmi_encoder/TMDS_Clk_n}]
set_property CONFIG.FREQ_HZ 25200000 [get_bd_ports {hdmi_clk_p hdmi_clk_n}]

validate_bd_design
save_bd_design
set bd [get_files system.bd]
generate_target all $bd
make_wrapper -files $bd -top
add_files $root/build/vivado_vga/gesture_vga.srcs/sources_1/bd/system/hdl/system_wrapper.v
set_property top system_wrapper [current_fileset]
add_files -fileset constrs_1 $root/config/known_board.xdc
if {[file exists $root/config/camera_pins.xdc]} {add_files -fileset constrs_1 $root/config/camera_pins.xdc}
if {[file exists $root/config/timing_verified.xdc]} {add_files -fileset constrs_1 $root/config/timing_verified.xdc}
add_files -fileset constrs_1 $root/config/uart1_emio.xdc
add_files -fileset constrs_1 $root/config/hdmi_output.xdc
update_compile_order -fileset sources_1
set fp [open $root/build/vga_board_validation.txt w]
puts $fp "BOARD_CONFIG_SOURCE=$BOARD_CONFIG_SOURCE"
puts $fp "BOARD_CONFIG_VERIFIED=$BOARD_CONFIG_VERIFIED"
puts $fp "Camera pin map present: [file exists $root/config/camera_pins.xdc]"
puts $fp "No bitstream/boot image created. DDR/IO/timing and actual device must be verified."
close $fp
puts "Created $root/build/vivado_vga/gesture_vga.xpr"
