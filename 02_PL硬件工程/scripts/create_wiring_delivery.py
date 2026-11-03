"""Create the source-checked wiring diagram and hardware handoff files."""
from pathlib import Path
import csv, hashlib, json, re, shutil, zipfile
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.colors import HexColor, white
ROOT=Path(__file__).resolve().parents[1]
WS=ROOT.parent
OUT=ROOT/'deliverables/board_test_delivery'
PDFDIR=WS/'output/pdf'
OUT.mkdir(parents=True,exist_ok=True)
PDFDIR.mkdir(parents=True,exist_ok=True)
pdfmetrics.registerFont(TTFont('CN','C:/Windows/Fonts/simhei.ttf'))
# P2 pin, signal, U13 pin, FPGA ball, RTL port, direction with camera on left.
rows=[
 (1,'GND',35,'—','', 'ground'),(2,'3.3V',37,'—','', 'left'),
 (3,'SIO_C / SCL',33,'G15','cam_scl','left'),(4,'VSYNC',34,'G16','cam_vsync','right'),
 (5,'SIO_D / SDA',31,'E16','cam_sda','both'),(6,'HREF',32,'F16','cam_href','right'),
 (7,'D0',29,'D18','cam_data[0]','right'),(8,'RESETB',30,'C19','cam_rst_n','left'),
 (9,'D2',27,'D15','cam_data[2]','right'),(10,'D1',28,'E15','cam_data[1]','right'),
 (11,'D4',25,'D17','cam_data[4]','right'),(12,'D3',26,'D16','cam_data[3]','right'),
 (13,'D6',23,'B15','cam_data[6]','right'),(14,'D5',24,'C15','cam_data[5]','right'),
 (15,'PCLK',21,'D20','cam_pclk','right'),(16,'D7',22,'C20','cam_data[7]','right'),
 (17,'PWDN',19,'A17','cam_pwdn','left'),(18,'OV-FLASH',None,'—','', 'none')]
xdc=(ROOT/'config/camera_pins.xdc').read_text(encoding='utf-8')
expected={port:ball for ball,port in re.findall(r'PACKAGE_PIN\s+(\w+)\s+\[get_ports\s+\{([^}]+)\}',xdc)}
actual={r[4]:r[3] for r in rows if r[4]}
assert actual==expected,(actual,expected)
u13={19:'A17',21:'D20',22:'C20',23:'B15',24:'C15',25:'D17',26:'D16',27:'D15',28:'E15',29:'D18',30:'C19',31:'E16',32:'F16',33:'G15',34:'G16'}
assert all(u13[r[2]]==r[3] for r in rows if r[4])
assert len({r[2] for r in rows if r[2]})==17
NAVY=HexColor('#17324D');BLUE=HexColor('#176B9B');GREEN=HexColor('#13796A');RED=HexColor('#BD382E');GRAY=HexColor('#526171');LIGHT=HexColor('#EEF3F7');AMBER=HexColor('#8A5300')
pdf=PDFDIR/'Smart_ZYNQ_SL_OV5640_wiring.pdf'
c=canvas.Canvas(str(pdf),pagesize=(595.28,841.89))
c.setTitle('Smart ZYNQ SL / OV5640 上板接线图（匹配 GST2 HDF）')
def text(x,y,s,size=10,color=NAVY):
 c.setFillColor(color);c.setFont('CN',size);c.drawString(x,y,s)
def line(x1,y1,x2,y2,color=BLUE,width=1):
 c.setStrokeColor(color);c.setLineWidth(width);c.line(x1,y1,x2,y2)
def arrow(x1,x2,y,mode,color=BLUE):
 line(x1,y,x2,y,color,1.5)
 if mode in ('right','both'):
  line(x2,y,x2-6,y+3,color);line(x2,y,x2-6,y-3,color)
 if mode in ('left','both'):
  line(x1,y,x1+6,y+3,color);line(x1,y,x1+6,y-3,color)
def box(x,y,w,h,title,lines):
 c.setFillColor(LIGHT);c.roundRect(x,y,w,h,8,fill=1,stroke=0)
 text(x+12,y+h-23,title,13)
 for i,s in enumerate(lines):text(x+12,y+h-43-i*17,s,9.5,GRAY)
def footer(page):
 line(32,39,563,39,HexColor('#CCD6DF'))
 text(32,25,'匹配 Vivado 2019.1 / GST2 / 640×480 RGB565 / 当前交付 bitstream',8,GRAY)
 text(515,25,f'{page} / 2',9,GRAY)
text(32,800,'OV5640 → Smart ZYNQ SL',22)
text(32,775,'逐线接线图  |  摄像头 P2（2×9）接板卡 U13 / BANK35（2×20）',11)
text(32,751,'只适用于所提供的 BY_OV5640 V1.1 P2 定义；实际模块必须核对针 1。',10,AMBER)
text(32,734,'下图是电气连接关系，不代表插头实物朝向；不要将 18 针排线直接套接 U13。',9.3,GRAY)
c.setFillColor(NAVY);c.roundRect(32,688,531,29,4,fill=1,stroke=0)
text(43,698,'摄像头 P2 针 / 信号',11,white);text(270,698,'方向',11,white);text(363,698,'板卡 U13 针',11,white);text(468,698,'FPGA 球位',11,white)
for i,(pin,sig,bpin,ball,port,direction) in enumerate(rows):
 y=671-i*25
 if i%2==0:
  c.setFillColor(LIGHT);c.rect(32,y-8,531,25,fill=1,stroke=0)
 col=RED if pin==2 else GRAY if pin in (1,18) else GREEN if pin in (3,5,8,17) else BLUE
 text(44,y,f'{pin:02d}   {sig}',11,col)
 if direction=='none':text(259,y,'不连接',10,GRAY)
 else:arrow(242,337,y+3,direction,col)
 text(376,y,f'{bpin:02d}' if bpin else '—',12,col);text(480,y,ball,11,col)
text(32,204,'接线前核对',12)
text(32,184,'① 先断电。P2-1 接 U13-35（GND），P2-2 接 U13-37（3.3V）。',10)
text(32,165,'② U13-39 / 40 是 5V，不用于摄像头 P2 电源或信号。',10,RED)
text(32,146,'③ 数据线按 D0…D7 名称逐根连接；P2 的数据位并非连续顺序排列。',10)
text(32,127,'④ P2-18 是 FLASH，本设计不使用；模块自带 24MHz XVCLK，无外接 XCLK。',9.7)
text(32,108,'⑤ RESETB、PWDN 由 FPGA 控制，不另接固定高低电平。',10)
text(32,89,'依据：板卡原理图 PDF 第9页、相机 SCH 第1页及本工程 camera_pins.xdc。',9,GRAY)
text(32,70,'本图已与 XDC 逐项校验；尚未完成实物接线与摄像头出图验收。',9,AMBER)
footer(1);c.showPage()
text(32,800,'上板连接与方向核对',22)
text(32,775,'开发板供电 / JTAG / USB 串口 / SD 卡 / 摄像头',11)
box(32,614,157,117,'电脑',['Vivado / SDK 2019.1','JTAG：加载、调试','串口工具：115200 8N1'])
box(254,614,309,117,'Smart ZYNQ SL',['板上 JTAG 接口 ← 匹配的下载器','板载 CH340N 对应 USB 串口接口 ← USB 数据线','U13 / BANK35 → 按第1页逐根接 OV5640'])
arrow(194,247,683,'both');arrow(194,247,651,'both')
text(32,586,'板卡电源：按该板原厂电源接口及额定规格供电；USB 串口线不作供电依据。',9.7)
text(32,566,'Linux 启动：使用软件侧制作的匹配 SD 启动介质，并按原厂说明设置启动模式。',9.7)
text(32,546,'裸机测试：可通过 JTAG 下载当前 bitstream 和 SDK 诊断程序，不依赖 Linux。',9.7)
box(32,444,531,79,'串口路径（已经在板内连接，无需另接 L17 / M17）',[
 'PS UART0 → EMIO → PL：TX=L17 / RX=M17 → 板载 CH340N → 电脑 USB',
 '须先加载匹配 bitstream 才能使用这一路串口；本次不接机械手或舵机电源。'])
text(32,421,'摄像头 P2：逻辑针号对照',13)
text(32,402,'奇偶列按原理图排列。实物正反面可能镜像；必须依据针1标记或通断核对。',9.3,AMBER)
for i in range(9):
 y=378-i*19;left,right=rows[2*i],rows[2*i+1]
 text(45,y,f'{left[0]:02d}  {left[1]}',10);text(260,y,f'{right[0]:02d}  {right[1]}',10)
text(32,197,'电平与模块版本',12)
text(32,179,'当前 FPGA 配置按你确认的 IO / 上拉 3.3V（LVCMOS33）。',9.8)
text(32,161,'但所提供相机 SCH 的 DOVDD 标为 2.8V，SCCB 上拉标为 3.3V。',9.8,AMBER)
text(32,143,'上电前需核对实物模块版本与 IO 电平；3.3V 电源输入不等于所有 IO 均为 3.3V。',9.2,AMBER)
text(32,125,'如实物并非此 BY_OV5640 V1.1 接口，请勿直接照此针号接线。',9.8)
text(32,101,'来源：Smart_ZYNQ_SL_Schematic_20230510.pdf 第2、9页；',9,GRAY)
text(32,85,'BY_OV5640_V1.1 SCH.pdf 第1页；用户确认的电气条件及 camera_pins.xdc。',9,GRAY)
text(32,66,'G16 / D20 等是 FPGA 封装球位，真正接线使用第1页的 U13 针号。',9,GRAY)
footer(2);c.save()
shutil.copyfile(pdf,OUT/pdf.name)
with (OUT/'camera_pinmap.csv').open('w',encoding='utf-8-sig',newline='') as f:
 w=csv.writer(f);w.writerow(['Camera_P2_pin','Signal','Board_U13_pin','FPGA_ball','RTL_port','Direction_camera_left']);w.writerows(rows)
source=ROOT/'deliverables/hardware_handoff'
m=json.loads((source/'manifest.json').read_text(encoding='utf-8'))
for name in ['system.hdf','system.bit']:
 b=(source/name).read_bytes();assert hashlib.sha256(b).hexdigest()==m['files'][name]['sha256'];shutil.copyfile(source/name,OUT/name)
with zipfile.ZipFile(OUT/'system.hdf') as z:assert z.read('vga_system.bit')==(OUT/'system.bit').read_bytes()
shutil.copyfile(ROOT/'docs/HARDWARE_HANDOFF.md',OUT/'HARDWARE_HANDOFF.md')
shutil.copyfile(ROOT/'docs/REGISTER_MAP.md',OUT/'REGISTER_MAP.md')
sources=Path('C:/Users/ZZH/xwechat_files/wxid_0ses04ogm2vf22_272f/msg/file/2026-10')
provenance={'status':'schematic-derived; not physically validated','board_connector':'U13 BANK35','camera_connector':'P2 of BY_OV5640 V1.1','sources':{}}
for path,pages in [(sources/'Smart_ZYNQ_SL_Schematic_20230510.pdf',[2,9]),(sources/'BY_OV5640_V1.1 SCH.pdf',[1]),(ROOT/'config/camera_pins.xdc',[])]:
 provenance['sources'][path.name]={'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'pages_1_based':pages}
(OUT/'wiring_sources.json').write_text(json.dumps(provenance,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
(OUT/'README.txt').write_text('发送给 Linux 开发人员：system.hdf（Vivado 2019.1 硬件平台）。\n匹配 FPGA 配置：system.bit；HDF 内也包含相同 bitstream。\n上板接线：Smart_ZYNQ_SL_OV5640_wiring.pdf，两页。camera_pinmap.csv 可逐线核对。\n板卡接口为 U13 BANK35；相机针号按 BY_OV5640 V1.1 P2。\n请先核对针1、3.3V供电与实际IO电平。未完成实物验收。\n软件侧需对接启动配置、设备树、采集/DMA驱动和SCCB初始化。\n',encoding='utf-8')
print('PDF created:',pdf)
print('15 signal mappings checked against current XDC and U13 schematic mapping.')
