# After physical board validation, save a reviewed copy as board_verified.tcl.
# board_reference.tcl already imports the user's BRAM example.
# Review actual DDR/device, SD boot and I/O voltage against the board.
source [file join [file dirname [info script]] board_reference.tcl]
# Record the physical validation evidence here before enabling the next line.
# set BOARD_CONFIG_VERIFIED 1
error "Template only: record board validation before enabling bitstream build"
