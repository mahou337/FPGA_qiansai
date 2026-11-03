`timescale 1ns/1ps
// VGA packet source. External async AXIS FIFO and S2MM DMA write a full frame to DDR.
module gesture_camera_vga #(parameter WIDTH=640, HEIGHT=480)(
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
 (* X_INTERFACE_INFO="xilinx.com:signal:clock:1.0 cam_pclk CLK" *)
 (* X_INTERFACE_PARAMETER="ASSOCIATED_BUSIF m_axis, ASSOCIATED_RESET stream_resetn, FREQ_HZ 42000000" *)
 input wire cam_pclk,
 input wire cam_vsync, cam_href, input wire [7:0] cam_data,
 output wire cam_rst_n, cam_pwdn, inout wire cam_scl, cam_sda,
 output wire stream_resetn,
 (* X_INTERFACE_INFO="xilinx.com:interface:axis:1.0 m_axis TDATA" *) output reg [31:0] m_axis_tdata=0,
 (* X_INTERFACE_INFO="xilinx.com:interface:axis:1.0 m_axis TVALID" *) output reg m_axis_tvalid=0,
 (* X_INTERFACE_INFO="xilinx.com:interface:axis:1.0 m_axis TREADY" *) input wire m_axis_tready,
 (* X_INTERFACE_INFO="xilinx.com:interface:axis:1.0 m_axis TLAST" *) output reg m_axis_tlast=0,
 (* X_INTERFACE_INFO="xilinx.com:interface:axis:1.0 m_axis TKEEP" *) output wire [3:0] m_axis_tkeep
);
 localparam WORDS=WIDTH*HEIGHT/2;
 reg [4:0] control=5'b10010;
 assign cam_rst_n=control[0]; assign cam_pwdn=control[1];
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
 // One PCLK reset synchronizer serves capture, elastic output and FIFO input.
 reg stream_reset_req_n=0;
 // Register reset before crossing domains; no combinational reset tree.
 always @(posedge s_axi_aclk)
  if(!s_axi_aresetn) stream_reset_req_n<=0;
  else stream_reset_req_n<=!control[4];
 assign m_axis_tkeep=4'hf;
 reg overflow=0;
 wire capture_done_raw, capture_good, mem_we;
 reg done_toggle=0;
 reg [36:0] published_metadata=0;
 wire [3:0] capture_error;
 wire [31:0] capture_words,mem_data;
 wire [31:0] mem_addr;
 dvp_snapshot #(.WIDTH(WIDTH),.HEIGHT(HEIGHT)) capture(
  .pclk(cam_pclk),.reset_n(stream_reset_req_n),.pclk_reset_n(stream_resetn),.request_toggle(request_toggle),
  .vsync(cam_vsync),.href(cam_href),.data(cam_data),
  .done_toggle(capture_done_raw),.frame_good(capture_good),.error_code(capture_error),.word_count(capture_words),
  .mem_we(mem_we),.mem_addr(mem_addr),.mem_data(mem_data));
 // Register status AND its notification in the same source clock cycle.
 // This prevents combinational status logic from crossing and preserves the
 // one destination-cycle margin of the 3-stage notification / 2-stage bus.
 always @(posedge cam_pclk) begin
  if(!stream_resetn) begin done_toggle<=0; published_metadata<=0; end
  else begin
   done_toggle<=capture_done_raw;
   published_metadata<={capture_good && !overflow,(overflow ? 4'd5 : capture_error),capture_words};
  end
 end
 // Elastic output register: never change a pending beat under backpressure.
 // DVP cannot pause. Any lost word invalidates the frame; reset before retry.
 always @(posedge cam_pclk) begin
  if(!stream_resetn) begin
   m_axis_tvalid<=0; m_axis_tlast<=0; m_axis_tdata<=0; overflow<=0;
  end else begin
   if(m_axis_tvalid && m_axis_tready) m_axis_tvalid<=0;
   if(mem_we && !overflow) begin
    if(!m_axis_tvalid || m_axis_tready) begin
     m_axis_tdata<=mem_data; m_axis_tlast<=(mem_addr==WORDS-1); m_axis_tvalid<=1;
    end else overflow<=1;
   end
  end
 end
 reg aw_pending=0,w_pending=0;
 reg [17:0] awaddr=0;
 reg [31:0] wdata=0;
 reg [3:0] wstrb=0;
 
 assign s_axi_awready=!aw_pending && !s_axi_bvalid;
 assign s_axi_wready=!w_pending && !s_axi_bvalid;
 assign s_axi_arready=!s_axi_rvalid;
 always @(posedge s_axi_aclk) begin
  if(!s_axi_aresetn) begin
   control<=18; request_toggle<=0; busy<=0; frame_valid<=0;
   last_error<=0; sequence<=0; words<=0; done_sync<=0; metadata_stage1<=0; metadata_stage2<=0; scl_sync<=3; sda_sync<=3;
   aw_pending<=0; w_pending<=0; s_axi_bvalid<=0; s_axi_bresp<=0;
   s_axi_rvalid<=0; s_axi_rresp<=0; s_axi_rdata<=0;
  end else begin
   scl_sync<={scl_sync[0],scl_in}; sda_sync<={sda_sync[0],sda_in};
   done_sync<={done_sync[1:0],done_toggle};
   metadata_stage1<=published_metadata;
   metadata_stage2<=metadata_stage1;
   // Bundled completion metadata stays stable until the next request.
   if(busy && !control[4] && done_sync[2]==request_toggle) begin
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
      if(busy && !(wstrb[0] && wdata[4])) s_axi_bresp<=2;
      else if(wstrb[0]) begin control<=wdata[4:0]; frame_valid<=0; end
    end else if(awaddr==18'h8) begin
      if(wstrb[0] && wdata[0]) begin
        if(busy || !control[0] || control[1] || control[4]) s_axi_bresp<=2;
        else begin request_toggle<=!request_toggle; busy<=1; frame_valid<=0; last_error<=0; end
      end
    end else s_axi_bresp<=2;
   end
   if(s_axi_rvalid && s_axi_rready) s_axi_rvalid<=0;
   if(s_axi_arvalid && s_axi_arready) begin
    s_axi_rresp<=0;
    if(s_axi_araddr[1:0]!=0) begin
      s_axi_rresp<=2; s_axi_rdata<=0; s_axi_rvalid<=1;
    end else begin
      s_axi_rvalid<=1;
      case(s_axi_araddr)
       'h00: s_axi_rdata<=32'h47535432;
       'h04: s_axi_rdata<={27'b0,control};
       'h0c: s_axi_rdata<={20'b0,last_error,3'b0,sda_sync[1],scl_sync[1],(last_error!=0),busy,frame_valid};
       'h10: s_axi_rdata<=sequence;
       'h14: s_axi_rdata<=words;
       'h18: s_axi_rdata<=(HEIGHT<<16)|WIDTH;
       default: begin s_axi_rdata<=0; s_axi_rresp<=2; end
      endcase
    end
   end
   if(control[4]) begin
    request_toggle<=0; busy<=0; frame_valid<=0; words<=0; last_error<=0;
    done_sync<=0; metadata_stage1<=0; metadata_stage2<=0;
   end
  end
 end
endmodule
