# Run with SDK 2019.1 xsct.bat AFTER a verified system.hdf exists.
set root [file normalize [file join [file dirname [info script]] ..]]
set hdf $root/build/system.hdf
if {![file exists $hdf]} {error "No verified HDF; run hardware implementation first"}
setws $root/build/sdk
createhw -name gesture_hw -hwspec $hdf
createapp -name camera_diag -hwproject gesture_hw -proc ps7_cortexa9_0 -os standalone -lang C -app {Empty Application}
importsources -name camera_diag -path $root/sdk
projects -build
