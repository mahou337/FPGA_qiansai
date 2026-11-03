# Smart ZYNQ SL schematic p2/p10: PS UART0 via EMIO -> PL -> CH340N.
set_property PACKAGE_PIN L17 [get_ports uart_tx]
set_property PACKAGE_PIN M17 [get_ports uart_rx]
set_property IOSTANDARD LVCMOS33 [get_ports {uart_tx uart_rx}]
# User-specified 42 MHz camera PCLK; XVCLK is supplied by the module at 24 MHz.
create_clock -name cam_pclk -period 23.809524 [get_ports cam_pclk]
