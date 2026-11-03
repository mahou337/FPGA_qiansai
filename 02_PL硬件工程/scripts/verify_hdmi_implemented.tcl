# Run on the routed design. Never connect hardware manager or program a device.
set f [open $root/build/hdmi_implemented_checks.txt w]
foreach {name ball} {hdmi_clk_p N22 hdmi_clk_n P22 hdmi_data_p[0] M21 hdmi_data_n[0] M22 hdmi_data_p[1] L21 hdmi_data_n[1] L22 hdmi_data_p[2] J21 hdmi_data_n[2] J22} {
 set p [get_ports $name]
 foreach {key expected} [list PACKAGE_PIN $ball IOSTANDARD TMDS_33 DIRECTION OUT] {
  set actual [get_property $key $p]
  puts $f "$name $key=$actual"
  if {$actual ne $expected} {error "$name $key expected $expected, got $actual"}
 }
}
foreach {name expected} {clk_fpga_0 20.0 pixel_raw 39.68254 serial_raw 7.936508} {
 set c [get_clocks $name]
 if {[llength $c]!=1} {error "Missing/ambiguous clock $name"}
 set period [get_property PERIOD $c]
 puts $f "$name PERIOD_NS=$period"
 if {abs($period-$expected)>0.002} {error "Unexpected clock $name: $period"}
}
set brams [get_cells -hier -filter {NAME =~ */mask_display/inst/* && REF_NAME =~ RAMB*}]
puts $f "DISPLAY_BRAM_PRIMITIVES=[llength $brams]"
if {[llength $brams]==0} {error "Display buffers did not infer BRAM"}
puts $f "WNS=[get_property SLACK [get_timing_paths -delay_type max -max_paths 1]]"
puts $f "WHS=[get_property SLACK [get_timing_paths -delay_type min -max_paths 1]]"
puts $f "Internal timing/routed pin checks only. Sink EDID and electrical TMDS link NOT tested."
puts $f "See check_timing for TMDS no_output_delay and CDC report for qualified asynchronous reset."
close $f
set sf [open $root/build/resolved_project_files.txt w]
foreach fi [get_files -all] {puts $sf $fi}
close $sf
