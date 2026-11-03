# Copy to camera_pins.xdc and fill actual wiring; this template is not loaded.
# BY P2: 1 GND, 2 3V3, 3 SCL, 4 VSYNC, 5 SDA, 6 HREF,
# 7 D0, 8 RESETB, 9 D2, 10 D1, 11 D4, 12 D3, 13 D6,
# 14 D5, 15 PCLK, 16 D7, 17 PWDN, 18 FLASH (unused).
# P2 has NO XCLK; module has onboard 24 MHz oscillator.
# Choose clock-capable PL pin for PCLK. Verify module DOVDD/IO voltage first.
# set_property PACKAGE_PIN <actual_ball> [get_ports cam_pclk]
# set_property PACKAGE_PIN <actual_ball> [get_ports {cam_data[0]}]
# ... assign all 8 data bits, vsync, href, reset_n, pwdn, scl, sda.
# set_property IOSTANDARD <electrically_verified_standard> [get_ports {cam_*}]
# Include min/max input delays for data/HREF/VSYNC relative to cam_pclk,
# sensor launch edge, measured PCLK and board skew. See timing notes.
# set_input_delay -clock cam_pclk -max <ns> [get_ports {cam_data[*] cam_href cam_vsync}]
# set_input_delay -clock cam_pclk -min <ns> [get_ports {cam_data[*] cam_href cam_vsync}]
