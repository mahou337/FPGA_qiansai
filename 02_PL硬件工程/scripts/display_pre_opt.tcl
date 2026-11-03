# Keep Vivado from deriving asynchronous reset-dependent BRAM enables.
# This only excludes the new display banks from optional clock-enable gating.
# Existing camera/AXI power optimization settings remain untouched.
set banks [get_cells -hier -filter {NAME =~ */mask_display/inst/* && REF_NAME =~ RAMB*}]
if {![llength $banks]} {error "No display BRAMs found"}
set_power_opt -exclude_cells $banks
puts "Display BRAM power-gating exclusion: [llength $banks] cells"
