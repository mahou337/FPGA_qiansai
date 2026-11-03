# Run on the open routed design before bitstream export.
report_io -file $root/build/uart1_implemented_io.rpt
report_utilization -file $root/build/uart1_implemented_utilization.rpt
report_clock_interaction -file $root/build/uart1_clock_interaction.rpt
check_timing -verbose -file $root/build/uart1_check_timing.rpt
set f [open $root/build/uart1_implemented_checks.txt w]
foreach {name ball direction} {uart_tx L17 OUT uart_rx M17 IN uart1_tx F18 OUT uart1_rx E18 IN} {
 set p [get_ports $name]
 foreach {key expected} [list PACKAGE_PIN $ball IOSTANDARD LVCMOS33 DIRECTION $direction] {
  set actual [get_property $key $p]
  puts $f "$name $key=$actual"
  if {$actual ne $expected} {error "$name $key: expected $expected, got $actual"}
 }
 set net [get_nets -of_objects $p]
 puts $f "$name physical_net=$net endpoints=[get_pins -of_objects $net]"
}
puts $f "WNS=[get_property SLACK [get_timing_paths -delay_type max -max_paths 1]]"
puts $f "WHS=[get_property SLACK [get_timing_paths -delay_type min -max_paths 1]]"
# report_drc was run by build_vga_bitstream.tcl; do not downgrade any check.
set errors [get_drc_violations -quiet -filter {SEVERITY == Error}]
puts $f "DRC_ERRORS=[llength $errors]"
if {[llength $errors]} {error "Unresolved DRC errors: $errors"}
puts $f "Routed IO checks PASS; physical UART communication NOT tested."
close $f
