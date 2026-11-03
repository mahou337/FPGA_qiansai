# Build standalone diagnostics and FSBL against the current implemented hardware.
set root [file normalize [file join [file dirname [info script]] ..]]
set hdf $root/build/vga_system.hdf
if {![file exists $hdf]} {error "Missing HDF; run build_vga_bitstream.tcl first"}
setws $root/build/sdk_vga
if {[llength [getprojects -type hw]] == 0} {
 createhw -name gesture_hw -hwspec $hdf
} else {
 updatehw -hw gesture_hw -newhwspec $hdf
}
set apps [getprojects -type app]
if {[lsearch -exact $apps camera_diag] < 0} {
 createapp -name camera_diag -hwproject gesture_hw -proc ps7_cortexa9_0 -os standalone -lang C -app {Empty Application}
}
if {[lsearch -exact $apps gesture_fsbl] < 0} {
 createapp -name gesture_fsbl -hwproject gesture_hw -proc ps7_cortexa9_0 -os standalone -lang C -app {Zynq FSBL}
}
importsources -name camera_diag -path $root/sdk
projects -build
puts "Built standalone camera diagnostic and FSBL; not board-tested."
