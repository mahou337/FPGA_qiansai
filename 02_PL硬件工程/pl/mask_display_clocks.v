`timescale 1ns/1ps
// Branch from unchanged FCLK0=50MHz. No new primary clock constraint.
// VCO 50/5*63=630MHz; pixel=630/25=25.2, serial=630/5=126MHz.
module mask_display_clocks(
 (* X_INTERFACE_PARAMETER="FREQ_HZ 50000000" *) input wire clk_in1,
 (* X_INTERFACE_PARAMETER="POLARITY ACTIVE_LOW" *) input wire resetn,
 (* X_INTERFACE_PARAMETER="FREQ_HZ 25200000" *) output wire clk_out1,
 (* X_INTERFACE_PARAMETER="FREQ_HZ 126000000" *) output wire clk_out2,
 output wire locked);
 wire fb,fb_buf,pixel_raw,serial_raw;
 MMCME2_BASE #(.BANDWIDTH("OPTIMIZED"),.CLKIN1_PERIOD(20.0),
  .DIVCLK_DIVIDE(5),.CLKFBOUT_MULT_F(63.0),.CLKOUT0_DIVIDE_F(25.0),
  .CLKOUT1_DIVIDE(5),.STARTUP_WAIT("FALSE")) mmcm (
  .CLKIN1(clk_in1),.CLKFBIN(fb_buf),.RST(~resetn),.PWRDWN(1'b0),
  .CLKFBOUT(fb),.CLKOUT0(pixel_raw),.CLKOUT1(serial_raw),.LOCKED(locked));
 BUFG feedback_buffer(.I(fb),.O(fb_buf));
 BUFG pixel_buffer(.I(pixel_raw),.O(clk_out1));
 BUFG serial_buffer(.I(serial_raw),.O(clk_out2));
endmodule
