`timescale 1ns/1ps
// AXI4-Lite snapshot peripheral. No streaming FIFO and no DDR DMA coherency.
module gesture_capture_axi #(parameter WIDTH=320, HEIGHT=240)(
 (* X_INTERFACE_PARAMETER="ASSOCIATED_BUSIF s_axi, ASSOCIATED_RESET s_axi_aresetn" *)
 input wire s_axi_aclk,
 (* X_INTERFACE_PARAMETER="POLARITY ACTIVE_LOW" *) input wire s_axi_aresetn,
 input wire [17:0] s_axi_awaddr, input wire [2:0] s_axi_awprot,
 input wire s_axi_awvalid, output wire s_axi_awready,
 input wire [31:0] s_axi_wdata, input wire [3:0] s_axi_wstrb,
 input wire s_axi_wvalid, output wire s_axi_wready,
 output reg [1:0] s_axi_bresp=0, output reg s_axi_bvalid=0, input wire s_axi_bready,
 input wire [17:0] s_axi_araddr, input wire [2:0] s_axi_arprot,
 input wire s_axi_arvalid, output wire s_axi_arready,
 output reg [31:0] s_axi_rdata=0, output reg [1:0] s_axi_rresp=0,
 output reg s_axi_rvalid=0, input wire s_axi_rready,
 input wire cam_pclk, cam_vsync, cam_href, input wire [7:0] cam_data,
 output wire cam_reset_n, cam_pwdn, inout wire cam_scl, cam_sda
);
 localparam WORDS=WIDTH*HEIGHT/2;
 (* ram_style="block" *) reg [31:0] frame_mem [0:WIDTH*HEIGHT/2-1];
 reg [3:0] control=4'b0010;
 assign cam_reset_n=control[0]; assign cam_pwdn=control[1];
 wire scl_in,sda_in;
 IOBUF scl_buf(.I(1'b0),.T(!control[2]),.O(scl_in),.IO(cam_scl));
 IOBUF sda_buf(.I(1'b0),.T(!control[3]),.O(sda_in),.IO(cam_sda));
 (* ASYNC_REG="TRUE" *) reg [1:0] scl_sync=3, sda_sync=3;
 (* ASYNC_REG="TRUE" *) reg [2:0] done_sync=0;
 // The bus is only consumed after completion; it stays frozen until the next request.
 // Data has two settling stages, notification has three (one additional margin cycle).
 (* ASYNC_REG="TRUE" *) reg [36:0] metadata_stage1=0, metadata_stage2=0;
 reg request_toggle=0, busy=0, frame_valid=0;
 reg [3:0] last_error=0;
 reg [31:0] sequence=0, words=0;
 wire done_toggle, capture_good, mem_we;
 wire [3:0] capture_error;
 wire [31:0] capture_words,mem_data;
 wire [31:0] mem_addr;
 dvp_snapshot #(.WIDTH(WIDTH),.HEIGHT(HEIGHT)) capture(
  .pclk(cam_pclk),.reset_n(s_axi_aresetn),.request_toggle(request_toggle),
  .vsync(cam_vsync),.href(cam_href),.data(cam_data),
  .done_toggle(done_toggle),.frame_good(capture_good),.error_code(capture_error),.word_count(capture_words),
  .mem_we(mem_we),.mem_addr(mem_addr),.mem_data(mem_data));
 always @(posedge cam_pclk) if(mem_we) frame_mem[mem_addr]<=mem_data;
 reg [15:0] read_index=0;
 reg [31:0] ram_q=0;
 always @(posedge s_axi_aclk) ram_q<=frame_mem[read_index];
 reg aw_pending=0,w_pending=0;
 reg [17:0] awaddr=0;
 reg [31:0] wdata=0;
 reg [3:0] wstrb=0;
 reg [1:0] read_state=0;
 assign s_axi_awready=!aw_pending && !s_axi_bvalid;
 assign s_axi_wready=!w_pending && !s_axi_bvalid;
 assign s_axi_arready=read_state==0 && !s_axi_rvalid;
 always @(posedge s_axi_aclk) begin
  if(!s_axi_aresetn) begin
   control<=2; request_toggle<=0; busy<=0; frame_valid<=0;
   last_error<=0; sequence<=0; words<=0; done_sync<=0; metadata_stage1<=0; metadata_stage2<=0; scl_sync<=3; sda_sync<=3;
   aw_pending<=0; w_pending<=0; s_axi_bvalid<=0; s_axi_bresp<=0;
   read_state<=0; s_axi_rvalid<=0; s_axi_rresp<=0; s_axi_rdata<=0; read_index<=0;
  end else begin
   scl_sync<={scl_sync[0],scl_in}; sda_sync<={sda_sync[0],sda_in};
   done_sync<={done_sync[1:0],done_toggle};
   metadata_stage1<={capture_good,capture_error,capture_words};
   metadata_stage2<=metadata_stage1;
   // Bundled completion metadata stays stable until the next request.
   if(busy && done_sync[2]==request_toggle) begin
    busy<=0; words<=metadata_stage2[31:0]; last_error<=metadata_stage2[35:32];
    frame_valid<=metadata_stage2[36];
    sequence<=sequence+1;
   end
   if(s_axi_bvalid && s_axi_bready) s_axi_bvalid<=0;
   if(s_axi_awvalid && s_axi_awready) begin awaddr<=s_axi_awaddr; aw_pending<=1; end
   if(s_axi_wvalid && s_axi_wready) begin wdata<=s_axi_wdata; wstrb<=s_axi_wstrb; w_pending<=1; end
   if(aw_pending && w_pending && !s_axi_bvalid) begin
    aw_pending<=0; w_pending<=0; s_axi_bvalid<=1; s_axi_bresp<=0;
    if(awaddr==18'h4) begin
      if(busy) s_axi_bresp<=2;
      else if(wstrb[0]) begin control<=wdata[3:0]; frame_valid<=0; end
    end else if(awaddr==18'h8) begin
      if(wstrb[0] && wdata[0]) begin
        if(busy || !control[0] || control[1]) s_axi_bresp<=2;
        else begin request_toggle<=!request_toggle; busy<=1; frame_valid<=0; last_error<=0; end
      end
    end else s_axi_bresp<=2;
   end
   if(s_axi_rvalid && s_axi_rready) s_axi_rvalid<=0;
   if(s_axi_arvalid && s_axi_arready) begin
    s_axi_rresp<=0;
    if(s_axi_araddr[1:0]!=0) begin
      s_axi_rresp<=2; s_axi_rdata<=0; s_axi_rvalid<=1;
    end else if(s_axi_araddr>=18'h1000 && s_axi_araddr<18'h1000+WORDS*4) begin
      if(busy || !frame_valid) begin s_axi_rresp<=2; s_axi_rdata<=0; s_axi_rvalid<=1; end
      else begin read_index<=(s_axi_araddr-18'h1000)>>2; read_state<=1; end
    end else begin
      s_axi_rvalid<=1;
      case(s_axi_araddr)
       'h00: s_axi_rdata<=32'h47535431;
       'h04: s_axi_rdata<={28'b0,control};
       'h0c: s_axi_rdata<={20'b0,last_error,3'b0,sda_sync[1],scl_sync[1],(last_error!=0),busy,frame_valid};
       'h10: s_axi_rdata<=sequence;
       'h14: s_axi_rdata<=words;
       'h18: s_axi_rdata<=(HEIGHT<<16)|WIDTH;
       default: begin s_axi_rdata<=0; s_axi_rresp<=2; end
      endcase
    end
   end else if(read_state==1) read_state<=2;
   else if(read_state==2) begin s_axi_rdata<=ram_q; s_axi_rvalid<=1; read_state<=0; end
  end
 end
endmodule
