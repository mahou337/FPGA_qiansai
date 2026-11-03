`timescale 1ns/1ps
// Two 76800-byte independent-clock BRAM banks. No DDR master or camera dependency.
module mask_display_axi(
 (* X_INTERFACE_PARAMETER="ASSOCIATED_BUSIF s_axi, ASSOCIATED_RESET s_axi_aresetn" *) input wire s_axi_aclk,
 (* X_INTERFACE_PARAMETER="POLARITY ACTIVE_LOW" *) input wire s_axi_aresetn,
 input wire [18:0] s_axi_awaddr, input wire [2:0] s_axi_awprot,
 input wire s_axi_awvalid, output wire s_axi_awready,
 input wire [31:0] s_axi_wdata, input wire [3:0] s_axi_wstrb,
 input wire s_axi_wvalid, output wire s_axi_wready,
 output reg [1:0] s_axi_bresp=0, output reg s_axi_bvalid=0, input wire s_axi_bready,
 input wire [18:0] s_axi_araddr, input wire [2:0] s_axi_arprot,
 input wire s_axi_arvalid, output wire s_axi_arready,
 output reg [31:0] s_axi_rdata=0, output reg [1:0] s_axi_rresp=0,
 output reg s_axi_rvalid=0, input wire s_axi_rready,
 (* X_INTERFACE_PARAMETER="FREQ_HZ 25200000" *) input wire pixel_clk,
 input wire display_locked,
 output reg [23:0] video_data=0, output reg video_de=0, video_hs=1, video_vs=1
);
 localparam WORDS=19200;
 wire drst_n=s_axi_aresetn & display_locked;
 (* ASYNC_REG="TRUE" *) reg [2:0] sys_release=0, pix_release=0;
 always @(posedge s_axi_aclk or negedge drst_n) if(!drst_n) sys_release<=0; else sys_release<={sys_release[1:0],1'b1};
 always @(posedge pixel_clk or negedge drst_n) if(!drst_n) pix_release<=0; else pix_release<={pix_release[1:0],1'b1};
 wire srst_n=sys_release[2], prst_n=pix_release[2];
 reg req_toggle=0, req_bank=1; reg [1:0] req_mode=0;
 reg ack_toggle=0, pix_front=0; reg [1:0] pix_mode=0;
 (* ASYNC_REG="TRUE" *) reg [2:0] ack_sync=0, req_sync=0;
 (* ASYNC_REG="TRUE" *) reg [2:0] mail_s1=0, mail_s2=0;
 reg busy=0, front=0; reg [1:0] mode=0;
 reg blank_pending=0;
 reg uploading=0; reg [14:0] filled=0; reg [3:0] partial=0;
 reg [31:0] swaps=0, errors=0;
 reg aw_pending=0,w_pending=0; reg [18:0] awaddr=0;
 reg [31:0] wdata=0; reg [3:0] wstrb=0;
 assign s_axi_awready=s_axi_aresetn && !aw_pending && !s_axi_bvalid;
 assign s_axi_wready=s_axi_aresetn && !w_pending && !s_axi_bvalid;
 assign s_axi_arready=s_axi_aresetn && !s_axi_rvalid;
 wire write_go=aw_pending && w_pending && !s_axi_bvalid;
 wire bank0_addr=(awaddr>=19'h20000 && awaddr<19'h32c00);
 wire bank1_addr=(awaddr>=19'h40000 && awaddr<19'h52c00);
 wire [14:0] write_index=awaddr[16:2];
 // BEGIN resets sequential-byte coverage; COMMIT is rejected until all bytes exist.
 wire mem_ok=write_go && uploading && !busy && !blank_pending &&
   ((bank0_addr && front) || (bank1_addr && !front)) && write_index==filled && filled<WORDS;
 (* ram_style="block" *) reg [31:0] bank0 [0:WORDS-1];
 (* ram_style="block" *) reg [31:0] bank1 [0:WORDS-1];
 // Register all physical BRAM write controls with NO asynchronous reset.
 // Coverage/commit control is one cycle ahead; AXI response sequencing leaves
 // the final physical write complete before a subsequent COMMIT is accepted.
 reg [3:0] ram_we0=0,ram_we1=0; reg [14:0] ram_wa=0; reg [31:0] ram_wd=0;
 always @(posedge s_axi_aclk) begin
  ram_we0<=(srst_n && mem_ok && bank0_addr) ? wstrb:4'b0;
  ram_we1<=(srst_n && mem_ok && bank1_addr) ? wstrb:4'b0;
  ram_wa<=write_index; ram_wd<=wdata;
 end
 genvar b;
 generate for(b=0;b<4;b=b+1) begin: byte_lanes
 always @(posedge s_axi_aclk) begin
  if(ram_we0[b]) bank0[ram_wa][b*8+:8]<=ram_wd[b*8+:8];
  if(ram_we1[b]) bank1[ram_wa][b*8+:8]<=ram_wd[b*8+:8];
 end
 end endgenerate
 always @(posedge s_axi_aclk) begin
  if(!s_axi_aresetn) begin
   req_toggle<=0; req_bank<=1; req_mode<=0; ack_sync<=0; busy<=0; front<=0; mode<=0;
   blank_pending<=0; uploading<=0; filled<=0; partial<=0; swaps<=0; errors<=0;
   aw_pending<=0; w_pending<=0; s_axi_bvalid<=0; s_axi_bresp<=0;
   s_axi_rvalid<=0; s_axi_rresp<=0; s_axi_rdata<=0;
  end else begin
   // AXI remains responsive even if the display MMCM never locks or loses lock.
   // Only display ownership/protocol resets; accepted bus responses are retained.
   if(!srst_n) begin
    req_toggle<=0; req_bank<=1; req_mode<=0; ack_sync<=0; busy<=0; front<=0; mode<=0;
    blank_pending<=0; uploading<=0; filled<=0; partial<=0; swaps<=0; errors<=0;
   end else begin
   ack_sync<={ack_sync[1:0],ack_toggle};
   if(busy && ack_sync[2]==req_toggle) begin
    busy<=0; mode<=req_mode; if(req_mode==1) begin front<=req_bank; swaps<=swaps+1; end
   end
   if(blank_pending && !busy) begin
    req_mode<=0; req_bank<=front; req_toggle<=~req_toggle; busy<=1; blank_pending<=0; uploading<=0;
   end
   end
   if(s_axi_bvalid && s_axi_bready) s_axi_bvalid<=0;
   if(s_axi_awready && s_axi_awvalid) begin awaddr<=s_axi_awaddr; aw_pending<=1; end
   if(s_axi_wready && s_axi_wvalid) begin wdata<=s_axi_wdata; wstrb<=s_axi_wstrb; w_pending<=1; end
   if(write_go) begin
    aw_pending<=0; w_pending<=0; s_axi_bvalid<=1; s_axi_bresp<=0;
    if(!srst_n) begin
     // Ignore writes while READY=0; no DECERR/SLVERR that could abort the CPU.
     // Coverage resets to zero, so the driver cannot publish a partial upload.
    end else if(bank0_addr || bank1_addr) begin
     if(mem_ok) begin
      if((partial | wstrb)==4'hf) begin filled<=filled+1; partial<=0; end
      else partial<=partial | wstrb;
     end else begin s_axi_bresp<=2; errors<=errors+1; end
    end else if(awaddr==19'h20 && wstrb==15 && wdata==1) blank_pending<=1;
    else if(awaddr==19'h10 && wstrb==15 && wdata==1 && !busy && !blank_pending) begin
     uploading<=1; filled<=0; partial<=0;
    end else if(awaddr==19'h04 && wstrb==15 && !busy && !blank_pending && wdata<=2 &&
       (wdata!=1 || (uploading && filled==WORDS && partial==0))) begin
     req_mode<=wdata[1:0]; req_bank<=~front; req_toggle<=~req_toggle; busy<=1; uploading<=0;
    end else begin s_axi_bresp<=2; errors<=errors+1; end
   end
   if(s_axi_rvalid && s_axi_rready) s_axi_rvalid<=0;
   if(s_axi_arready && s_axi_arvalid) begin
    s_axi_rvalid<=1; s_axi_rresp<=0;
    case(s_axi_araddr)
     'h00:s_axi_rdata<=32'h4d534b31; // MSK1 interface version1
     'h04:s_axi_rdata<={30'b0,mode};
     'h08:s_axi_rdata<={25'b0,blank_pending,uploading,mode,front,busy,srst_n};
     'h0c:s_axi_rdata<=32'h00f00140; // height240 width320
     'h10:s_axi_rdata<={13'b0,partial,filled};
     'h14:s_axi_rdata<=swaps;
     'h18:s_axi_rdata<=errors;
     'h1c:s_axi_rdata<=76800;
     default:begin s_axi_rdata<=0; s_axi_rresp<=2; end
    endcase
   end
  end
 end
 reg [9:0] x=0,y=0;
 wire active=(x<640 && y<480);
 wire [14:0] row={6'b0,y[9:1]};
 wire [14:0] read_index=active ? ((row<<6)+(row<<4)+{8'b0,x[9:3]}) : 15'b0;
 reg [31:0] q0,q1;
 reg [1:0] lane=0; reg de_q=0,hs_q=1,vs_q=1;
 reg [23:0] bars_q=0; reg front_q=0; reg [1:0] mode_q=0;
 always @(posedge pixel_clk) begin q0<=bank0[read_index]; q1<=bank1[read_index]; end
 wire [31:0] selected=front_q ? q1:q0;
 wire [7:0] gray=selected >> (lane*8);
 // Data mailbox has two settling stages; request has a third stage.
 // Source holds it until acknowledgement. Only change bank inside vertical blank.
 always @(posedge pixel_clk) begin
  if(!prst_n) begin
   x<=0; y<=0; req_sync<=0; mail_s1<=0; mail_s2<=0;
   ack_toggle<=0; pix_front<=0; pix_mode<=0;
   video_data<=0; video_de<=0; video_hs<=1; video_vs<=1;
   de_q<=0; hs_q<=1; vs_q<=1; lane<=0; front_q<=0; mode_q<=0; bars_q<=0;
  end else begin
   req_sync<={req_sync[1:0],req_toggle};
   mail_s1<={req_mode,req_bank}; mail_s2<=mail_s1;
   if(x==0 && y==480 && req_sync[2]!=ack_toggle) begin
    pix_mode<=mail_s2[2:1]; if(mail_s2[2:1]==1) pix_front<=mail_s2[0]; ack_toggle<=req_sync[2];
   end
   if(x==799) begin x<=0; if(y==524) y<=0; else y<=y+1; end else x<=x+1;
   lane<=x[2:1]; front_q<=pix_front; mode_q<=pix_mode;
   de_q<=active; hs_q<=!(x>=656 && x<752); vs_q<=!(y>=490 && y<492);
   // RGB ordering for Digilent is R,B,G. Diagnostic only; mode1 always uses BRAM.
   bars_q<={ {8{x>=320}}, {8{x[6]^y[6]}}, {8{y>=240}} };
   video_de<=de_q; video_hs<=hs_q; video_vs<=vs_q;
   video_data<=!de_q ? 24'b0 : mode_q==1 ? {gray,gray,gray} : mode_q==2 ? bars_q : 24'b0;
  end
 end
endmodule
