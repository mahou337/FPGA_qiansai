SUMMARY = "Isolated 320x240 BRAM mask display for Smart ZYNQ"
LICENSE = "GPLv2"
LIC_FILES_CHKSUM = "file://gesture_mask_display.c;beginline=1;endline=1;md5=50d2ba0afecd20f74c12a4bdbcfcfe61"
inherit module
SRC_URI = "file://Makefile file://gesture_mask_display.c file://gesture_mask_display.h"
S = "${WORKDIR}"
# No autoload until matching bitstream/DT have been verified on candidate boot.
