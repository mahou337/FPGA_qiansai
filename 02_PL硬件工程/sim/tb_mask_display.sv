`timescale 1ns/1ps
module tb_mask_display;
 reg clk=0,px=0,rst=0,locked=0;
 always #10 clk=~clk;
 always #19.84127 px=~px;
 reg [18:0] awaddr=0,araddr=0; reg awvalid=0,wvalid=0,arvalid=0;
 reg [31:0] wdata=0; reg [3:0] wstrb=0;
 wire awready,wready,bvalid,arready,rvalid; wire [1:0] bresp,rresp; wire[31:0] rdata;
 reg bready=0,rready=0;
 wire [23:0] rgb; wire de,hs,vs;
 mask_display_axi dut(.s_axi_aclk(clk),.s_axi_aresetn(rst),
 .s_axi_awaddr(awaddr),.s_axi_awprot(3'b0),.s_axi_awvalid(awvalid),.s_axi_awready(awready),
 .s_axi_wdata(wdata),.s_axi_wstrb(wstrb),.s_axi_wvalid(wvalid),.s_axi_wready(wready),
 .s_axi_bresp(bresp),.s_axi_bvalid(bvalid),.s_axi_bready(bready),
 .s_axi_araddr(araddr),.s_axi_arprot(3'b0),.s_axi_arvalid(arvalid),.s_axi_arready(arready),
 .s_axi_rdata(rdata),.s_axi_rresp(rresp),.s_axi_rvalid(rvalid),.s_axi_rready(rready),
 .pixel_clk(px),.display_locked(locked),.video_data(rgb),.video_de(de),.video_hs(hs),.video_vs(vs));
 task wr(input[18:0] a,input[31:0] d,input[3:0] st,input integer skew,input[1:0] response);
 begin
  fork
   begin repeat(skew>0?skew:0) @(negedge clk); awaddr=a;awvalid=1;do @(posedge clk);while(!awready);@(negedge clk);awvalid=0;end
   begin repeat(skew<0?-skew:0) @(negedge clk);wdata=d;wstrb=st;wvalid=1;do @(posedge clk);while(!wready);@(negedge clk);wvalid=0;end
  join
  wait(bvalid); #1;if(bresp!==response) $fatal(1,"WRITE a=%h got=%d expected=%d",a,bresp,response);
  repeat(2) @(negedge clk);if(!bvalid)$fatal(1,"B backpressure lost");bready=1;@(negedge clk);bready=0;
 end endtask
 task rd(input[18:0] a,output[31:0] d);
 begin
  @(negedge clk);araddr=a;arvalid=1;do @(posedge clk);while(!arready);@(negedge clk);arvalid=0;
  wait(rvalid);#1;d=rdata; if(rresp!=0)$fatal(1,"read error");
  repeat(2) @(negedge clk);if(!rvalid || rdata!==d)$fatal(1,"R unstable");rready=1;@(negedge clk);rready=0;
 end endtask
 task idle;
 integer n;reg[31:0]s;
 begin n=0;rd(8,s);while((s&32'h42)!=0)begin repeat(200)@(negedge clk);rd(8,s);n=n+1;if(n>12000)$fatal(1,"ACK timeout");end end
 endtask
 function[7:0] pattern(input integer i,input integer invert);
 integer u,v;
 begin u=i%320;v=i/320;pattern=(((u/7+v/11)%2)^invert)?255:0;end
 endfunction
 integer bank_pattern[0:1];
 task fill(input integer bank,input integer inv);
 integer i,k;reg[31:0]d;reg[18:0]base;
 begin
  base=bank?19'h40000:19'h20000;
  wr('h10,1,15,2,0);wr(4,1,15,-3,2); // partial commit rejected
  // Byte strobes on first word, including unaligned byte addresses.
  for(k=0;k<4;k=k+1) wr(base+k,{4{pattern(k,inv)}},1<<k,k-2,0);
  for(i=1;i<19200;i=i+1)begin
   for(k=0;k<4;k=k+1)d[k*8+:8]=pattern(i*4+k,inv);
   wr(base+i*4,d,15,0,0);
  end
  bank_pattern[bank]=inv;
  wr(4,1,15,1,0);
 end endtask
 reg[23:0]expected=0,next_rgb;reg ed=0,eh=1,ev=1,nd,nh,nv;reg[7:0]g;
 integer checked=0,active_checked=0,swaps_checked=0;reg old_front=0;integer old_x=0,old_y=0;
 always @(posedge px) begin
  if(!dut.prst_n) begin expected=0;ed=0;eh=1;ev=1;end
  else begin
   nd=dut.x<640 && dut.y<480;nh=!(dut.x>=656 && dut.x<752);nv=!(dut.y>=490 && dut.y<492);
   next_rgb=0;
   if(nd && dut.pix_mode==1)begin
    g=pattern((dut.y/2)*320+dut.x/2,bank_pattern[dut.pix_front]);next_rgb={g,g,g};active_checked=active_checked+1;
   end else if(nd && dut.pix_mode==2)next_rgb={{8{dut.x>=320}},{8{dut.x[6]^dut.y[6]}},{8{dut.y>=240}}};
   #1;
   if({de,hs,vs,rgb}!=={ed,eh,ev,expected})$fatal(1,"pixel mismatch x=%d y=%d got=%h exp=%h",dut.x,dut.y,rgb,expected);
   expected=next_rgb;ed=nd;eh=nh;ev=nv;checked=checked+1;
  end
 end
 always @(negedge px)begin
  if(!dut.prst_n)begin old_front=dut.pix_front;old_x=dut.x;old_y=dut.y;end
  else begin
   if(dut.pix_front!=old_front)begin if(old_x!=0 || old_y!=480)$fatal(1,"swap outside blank");swaps_checked=swaps_checked+1;end
   old_front=dut.pix_front;old_x=dut.x;old_y=dut.y;
  end
 end
 reg[31:0]s;integer start_count;
 initial begin
  bank_pattern[0]=0;bank_pattern[1]=0;
  #200;rst=1;locked=1;repeat(20)@(negedge clk);
  rd(0,s);if(s!=32'h4d534b31)$fatal(1,"identity");
  wr(4,1,15,3,2); // no frame
  wr(4,2,15,-3,0);idle();repeat(420000)@(negedge px);
  fill(1,0);wr('h40000,0,15,0,2);idle();
  wr('h40000,0,15,0,2); // cannot overwrite front
  start_count=active_checked;repeat(840000)@(negedge px);if(active_checked-start_count<600000)$fatal(1,"repeat scan failed");
  fill(0,1);idle();repeat(420000)@(negedge px);
  // Blank can queue while a previous mode command is pending; close never waits.
  wr(4,2,15,0,0);wr('h20,1,15,0,0);idle();rd(4,s);if(s!=0)$fatal(1,"queued blank failed");
  locked=0;repeat(10)@(negedge clk);
  rd(0,s);if(s!=32'h4d534b31)$fatal(1,"MMCM loss blocks AXI identity");
  rd(8,s);if(s[0]!=0)$fatal(1,"unlocked reports READY");
  wr(4,2,15,3,0);rd(4,s);if(s!=0)$fatal(1,"unlocked write changed mode");
  locked=1;repeat(20)@(negedge clk);
  rd(4,s);if(s!=0)$fatal(1,"lock loss not black");wr(4,1,15,0,2);
  if(swaps_checked!=2)$fatal(1,"swap count");
  $display("PASS mask display: pixels=%0d mask_pixels=%0d swaps=%0d; AXI skew/backpressure, coverage, ownership, 2x, repeat, blank, reset and unlocked AXI",checked,active_checked,swaps_checked);
  $finish;
 end
 initial begin #200000000;$fatal(1,"global timeout");end
endmodule

