set root [file normalize [file join [file dirname [info script]] ..]]
open_checkpoint $root/build/capture_synth.dcp
report_cdc -details -file $root/build/capture_cdc_details.rpt
