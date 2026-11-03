# Smart ZYNQ SL schematic 2023-05-10, PDF pp2/8/9.
# U13 is the BANK35 20x2 header. These are connector PIN numbers, not ball names.
# TX: FPGA F18 / GPIO_F18_L5P -> U13 pin 4 -> adapter marked TX.
# RX: FPGA E18 / GPIO_E18_L5N <- U13 pin 3 <- adapter marked RX.
# BANK35 VCCO is fixed VCC3V3. U13 pins 35/36 are GND.
# No on-board peripheral connection found on these two nets in this schematic.
# Actual board revision, connector orientation and external cable occupancy
# must still be confirmed before physical connection. No board test performed.
set_property PACKAGE_PIN F18 [get_ports uart1_tx]
set_property PACKAGE_PIN E18 [get_ports uart1_rx]
set_property IOSTANDARD LVCMOS33 [get_ports {uart1_tx uart1_rx}]
# Asynchronous serial signals enter/leave the PS hard UART through EMIO.
# No external clock relationship is imposed; this is not a baud-rate test.
set_false_path -from [get_ports uart1_rx]
set_false_path -to [get_ports uart1_tx]
