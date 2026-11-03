`timescale 1ns/1ps
// Capture one whole frame after a request. RGB565 high byte first.
// Sync inputs must be positive polarity; PCLK must run during blanking.
module dvp_snapshot #(parameter WIDTH=320, HEIGHT=240)(
 input wire pclk, input wire reset_n, input wire request_toggle,
 input wire vsync, href, input wire [7:0] data,
 output reg done_toggle=0, output reg frame_good=0, output reg [3:0] error_code=0,
 output reg [31:0] word_count=0,
 output wire pclk_reset_n,
 output reg mem_we=0, output reg [31:0] mem_addr=0, output reg [31:0] mem_data=0
);
 localparam WORDS=WIDTH*HEIGHT/2;
 (* ASYNC_REG="TRUE" *) reg [1:0] req_sync=0;
 (* ASYNC_REG="TRUE" *) reg [1:0] reset_sync=0;
 assign pclk_reset_n=reset_sync[1];
 // Only the reset synchronizer sees the asynchronous reset input. Other
 // PCLK-domain registers release reset together through reset_sync[1].
 always @(posedge pclk or negedge reset_n)
   if(!reset_n) reset_sync<=0;
   else reset_sync<={reset_sync[0],1'b1};
 always @(posedge pclk)
   if(!reset_sync[1]) req_sync<=0;
   else req_sync<={req_sync[0],request_toggle};
 reg [1:0] state=0; // idle, wait frame boundary, capture
 reg vs_d=0, hr_d=0;
 reg [15:0] bytes_in_line=0, lines=0;
 reg [7:0] b0=0,b1=0,b2=0;
 always @(posedge pclk) begin
  mem_we<=0;
  if(!reset_sync[1]) begin
   state<=0; done_toggle<=0; frame_good<=0; error_code<=0; word_count<=0;
   bytes_in_line<=0; lines<=0; vs_d<=0; hr_d<=0; mem_addr<=0; mem_data<=0;
  end else begin
   vs_d<=vsync; hr_d<=href;
   case(state)
    0: if(req_sync[1]!=done_toggle) begin
      state<=1; frame_good<=0; word_count<=0; error_code<=0; lines<=0; bytes_in_line<=0;
    end
    1: if(vsync && !vs_d) begin state<=2; hr_d<=0; end
    2: begin
      if(vsync && !vs_d) begin
        // Last HREF must fall before VSYNC (otherwise malformed frame).
        if(href || hr_d || bytes_in_line!=0) error_code<=4;
        else if(lines!=HEIGHT || word_count!=WORDS) error_code<=3;
        frame_good<=!href && !hr_d && bytes_in_line==0 && lines==HEIGHT && word_count==WORDS && error_code==0;
        done_toggle<=req_sync[1]; state<=0;
      end else if(!vsync) begin
        if(href) begin
          if(bytes_in_line<WIDTH*2 && lines<HEIGHT) begin
            case(bytes_in_line[1:0])
             0: b0<=data;
             1: b1<=data;
             2: b2<=data;
             3: begin
               mem_we<=1; mem_addr<=word_count;
               mem_data<={b2,data,b0,b1}; word_count<=word_count+1;
             end
            endcase
          end else error_code<=2;
          if(bytes_in_line!=16'hffff) bytes_in_line<=bytes_in_line+1;
        end else if(hr_d) begin
          if(bytes_in_line!=WIDTH*2) error_code<=1;
          bytes_in_line<=0;
          if(lines!=16'hffff) lines<=lines+1;
        end
      end else if(href) error_code<=4;
    end
   endcase
  end
 end
endmodule
