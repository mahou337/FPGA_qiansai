# Executed after create_vivado_vga.tcl. Fail closed on intended hardware invariants.
set f [open $root/build/uart1_bd_checks.txt w]
proc require_ps {key expected} {
 global f
 set actual [get_property CONFIG.$key [get_bd_cells ps7]]
 puts $f "$key=$actual"
 if {$actual ne $expected} {error "$key: expected $expected, got $actual"}
}
foreach {key value} {
 PCW_UART0_PERIPHERAL_ENABLE 1 PCW_UART0_UART0_IO EMIO
 PCW_UART0_GRP_FULL_ENABLE 0 PCW_UART0_BAUD_RATE 115200
 PCW_UART1_PERIPHERAL_ENABLE 1 PCW_UART1_UART1_IO EMIO
 PCW_UART1_GRP_FULL_ENABLE 0 PCW_UART_PERIPHERAL_FREQMHZ 100
 PCW_FPGA0_PERIPHERAL_FREQMHZ 50 PCW_USE_S_AXI_HP0 1
 PCW_S_AXI_HP0_DATA_WIDTH 64 PCW_USE_M_AXI_GP0 1
 PCW_UIPARAM_DDR_BUS_WIDTH {16 Bit}
 PCW_UIPARAM_DDR_PARTNO {MT41K256M16 RE-125}
 PCW_SD0_PERIPHERAL_ENABLE 1 PCW_SD0_SD0_IO {MIO 40 .. 45}
 PCW_SD0_GRP_CD_ENABLE 1 PCW_SD0_GRP_CD_IO {MIO 47}
 PCW_ENET0_PERIPHERAL_ENABLE 0 PCW_ENET1_PERIPHERAL_ENABLE 0
 PCW_USB0_PERIPHERAL_ENABLE 0 PCW_USB1_PERIPHERAL_ENABLE 0
} {require_ps $key $value}
foreach {port pin direction} {
 uart_tx UART0_TX O uart_rx UART0_RX I
 uart1_tx UART1_TX O uart1_rx UART1_RX I
} {
 set p [get_bd_ports $port]
 set n [get_bd_nets -of_objects $p]
 if {[llength $p]!=1 || [llength $n]!=1} {error "Missing port/net: $port"}
 if {[get_property DIR $p] ne $direction} {error "Wrong direction: $port"}
 set target [get_bd_pins ps7/$pin]
 if {[lsearch -exact [get_bd_pins -of_objects $n] $target]<0} {error "Wrong connection: $port"}
 puts $f "$port -> ps7/$pin net=$n dir=$direction"
}
validate_bd_design
puts $f "BD UART checks PASS; complete baseline diff is in separate verification report."
close $f
