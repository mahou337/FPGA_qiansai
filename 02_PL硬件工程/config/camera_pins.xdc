# User supplied Smart ZYNQ SL V1.1 wiring, 2026-10-29.
# User confirmed FPGA bank/module IO and SCCB pull-ups at 3.3 V on 2026-10-29.
set_property PACKAGE_PIN G16 [get_ports {cam_vsync}]
set_property PACKAGE_PIN F16 [get_ports {cam_href}]
set_property PACKAGE_PIN D20 [get_ports {cam_pclk}]
set_property PACKAGE_PIN D18 [get_ports {cam_data[0]}]
set_property PACKAGE_PIN E15 [get_ports {cam_data[1]}]
set_property PACKAGE_PIN D15 [get_ports {cam_data[2]}]
set_property PACKAGE_PIN D16 [get_ports {cam_data[3]}]
set_property PACKAGE_PIN D17 [get_ports {cam_data[4]}]
set_property PACKAGE_PIN C15 [get_ports {cam_data[5]}]
set_property PACKAGE_PIN B15 [get_ports {cam_data[6]}]
set_property PACKAGE_PIN C20 [get_ports {cam_data[7]}]
set_property PACKAGE_PIN G15 [get_ports {cam_scl}]
set_property PACKAGE_PIN E16 [get_ports {cam_sda}]
set_property PACKAGE_PIN C19 [get_ports {cam_rst_n}]
set_property PACKAGE_PIN A17 [get_ports {cam_pwdn}]

set_property IOSTANDARD LVCMOS33 [get_ports {cam_pclk cam_vsync cam_href cam_data[*] cam_scl cam_sda cam_rst_n cam_pwdn}]
