"""Package the existing first-stage Linux integration inputs; does not build Linux."""
from pathlib import Path
import ast
import hashlib
import io
import json
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'deliverables' / 'linux_stage1_handoff'
HARDWARE = ROOT / 'deliverables' / 'board_test_delivery'
EXPECTED = {
    'system.hdf': '1ca63e2794e0e02a26dd5351a3917fbeedc5623fbd18188f4a8a03ac39903042',
    'system.bit': '47a9ff8681c5c43ab23e362c4d318db78021dc2fc9f5716acb1fe695f566b02d',
}
def sha(data):
    return hashlib.sha256(data).hexdigest()
def text(rel, content):
    p = OUT / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content.strip() + '\n', encoding='utf-8', newline='\n')
def copy(src, rel):
    p = OUT / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, p)

for name, digest in EXPECTED.items():
    assert sha((HARDWARE / name).read_bytes()) == digest, name
with zipfile.ZipFile(HARDWARE / 'system.hdf') as hdf:
    assert hdf.testzip() is None
    bits = [n for n in hdf.namelist() if n.endswith('.bit')]
    assert len(bits) == 1
    assert hdf.read(bits[0]) == (HARDWARE / 'system.bit').read_bytes()
OUT.mkdir(parents=True, exist_ok=True)
for p in sorted(HARDWARE.rglob('*')):
    if p.is_file():
        copy(p, Path('hardware') / p.relative_to(HARDWARE))
source_files = [
    'linux/gesture_vga.c', 'linux/gesture_uapi.h', 'linux/gesture-vga.dtsi', 'linux/Makefile',
    'ps/hardware.py', 'ps/hardware_vga.py', 'ps/camera_probe.py',
    'config/ov5640_vga_rgb565.json', 'config/ov5640_qvga_rgb565.json',
    'sdk/camera_diag.c', 'sdk/ov5640_vga_regs.h',
    'tests/test_vga.py', 'docs/REGISTER_MAP.md',
]
for rel in source_files:
    copy(ROOT / rel, Path('source') / rel)
for rel in ['pl/gesture_camera_vga.v', 'pl/dvp_snapshot.v', 'pl/gesture_capture_axi.v',
            'scripts/create_vivado_vga.tcl', 'scripts/create_sdk_vga.tcl']:
    copy(ROOT / rel, Path('reference_hardware') / rel)
for app in ['gesture_fsbl', 'camera_diag']:
    copy(ROOT / 'build/sdk_vga' / app / 'Debug' / (app + '.elf'),
         Path('reference_standalone') / (app + '.elf'))

text('00_README_FIRST.md', r'''
# 第一阶段 Linux 集成资料包

目的：转发给另一台 Linux 开发电脑，在其已经完成的 Linux / Python / NumPy / OpenCV 系统上补齐驱动、测试程序和启动集成。
本包是开发输入资料，不是可以直接写入 SD 卡的完整系统镜像。

## 接手顺序

1. 解压本包，阅读本文件和 `01_LINUX_TASK_PROMPT.md`。
2. 在 Linux 开发机执行 `sha256sum -c SHA256SUMS` 核对传输完整性。
3. 结合 `02_INPUTS_AND_DELIVERABLES.md` 核对该电脑已有的系统工程、内核构建资料和工具链。
4. 根据任务提示词修改、构建、集成，在新的输出目录制作最终启动卡交付。
5. 最终用户按 `03_FIRST_BOARD_ACCEPTANCE.md` 进行实物验收。

## 包内目录

| 目录 | 内容与状态 |
|---|---|
| hardware/ | 原硬件交接包的完整副本：HDF、匹配 bitstream、接线图、配置、寄存器说明、既有验证报告 |
| source/linux/ | Linux 驱动、UAPI、设备树片段、Makefile；尚未针对接手方实际内核编译验收 |
| source/ps/ | VGA 采图、RGB565 解码、SCCB 初始化参考代码；待目标系统适配与实物验证 |
| source/config/ | VGA 相机寄存器表；QVGA 表仅供现有负向单元测试，不能用于当前硬件 |
| source/tests/ | 不需要板卡的 VGA 接口模拟/格式测试，不代表真实采图通过 |
| source/sdk/ | 裸机诊断源码和寄存器头文件，仅供流程参考 |
| reference_standalone/ | 从当前 HDF 构建的 FSBL 和诊断 ELF；已编译、未实物验收，不是 Linux 可执行程序 |
| reference_hardware/ | RTL、硬件创建脚本片段供检查接口；不是完整 Vivado 工程归档，勿直接运行创建脚本重建硬件 |
| PACKAGE_MANIFEST.json | 本包硬件哈希、来源及验证边界 |
| SHA256SUMS | 本包逐文件校验表（不包括校验表自身） |

## bitstream 与启动

本包 `hardware/system.bit` 就是匹配的 bitstream；`hardware/system.hdf` 内嵌的 bitstream 与它完全相同。
HDF 是硬件构建/适配输入，不是烧录到板上的运行文件。
Linux 同学需要将匹配 FSBL、该 bitstream 和配套 U-Boot 集成为合适的 BOOT.BIN，并部署内核、设备树和 rootfs。
验收目标是 SD 卡上电启动自动加载 PL，不要求用户再手工下载 HDF 或 bitstream。
UART0 经 EMIO/PL 接 CH340N，必须在依赖此 UART 或访问采集寄存器之前完成 PL 配置。

## 参考源码的重要说明

`hardware_vga.py` 导入 `hardware.py` 并继承其中 SCCB 方法，所以必须一起部署。
VGA 后端重写了构造、寄存器访问和取帧流程，不需要旧的 `libgesture_mmio.so`。
不要直接实例化旧 `Hardware` 类作为本项目 VGA 后端，不要沿用旧 GST1/BRAM 地址。
`camera_probe.py` 是现有参考程序，并非完整的一键验收工具；接手方需补齐日志、持久存储检查和运行入口。
它的输出目录必须不存在，接手方需为每次测试创建独立目录名。

本次未打包旧 BOOT.BIN/image.ub、历史部署 ZIP 或识别/机械手程序，避免与接手方最新系统混用。
也未提供目标 Linux .ko；必须根据接手方的实际内核构建，不能伪造兼容性。
硬件包内旧文档保留原交付边界；本次新增开发任务以 `01_LINUX_TASK_PROMPT.md` 为准。
''')

text('01_LINUX_TASK_PROMPT.md', r'''
# 可直接复制给 Linux 编程助手的任务提示词

请基于本包和这台电脑上已经准备好的 Linux 系统、启动镜像及 Python/NumPy/OpenCV，实施第一阶段软件适配、构建和 SD 卡启动集成。实际修改文件并生成交付，不要只给方案。

## 目标

板卡 Smart ZYNQ SL V1.1，XC7Z020-CLG484-1；硬件由 Vivado/SDK 2019.1 导出。
从 SD 卡启动后自动配置匹配的 PL，电脑通过 UART Type-C 看到测试消息；读取采集模块和 OV5640 ID；采集至少三张彩条和三张真实图像，保存为电脑可打开的 640×480 PNG/BMP。正常关机取卡后可在电脑查看图片。
本阶段不做四指识别、机械手控制、实时预览或串口图片传输。

## 先检查资料，不假定路径或系统版本

本包解压目录作为工作入口，全部输入均通过相对路径取得，不需要访问原作者 Windows 的 D: 盘。
先读 `00_README_FIRST.md`、`hardware/HARDWARE_HANDOFF.md`、`hardware/REGISTER_MAP.md`、配置和原理图接线说明。
读取 `source/linux/`、`source/ps/`、`source/config/`、`source/sdk/`。必要时查看 `reference_hardware/` 接口实现。
驱动与设备树是参考实现；不能将“源码存在”当成“目标系统已验证”。
核对本电脑的实际系统工程、最终内核、配置、构建输出、模块版本信息、交叉工具链、sysroot、rootfs、启动文件及 SD 分区。
不要因为 Vivado 版本就猜定内核版本。保留已经完成的环境，避免无理由升级内核或重装 OpenCV。
发现必要输入缺失时，先查找已有资料；仍缺失则准确报告并完成独立工作。不能伪造编译、驱动或测试成功。

## 硬件约定（须与 HDF 和文档复核）

- 采集寄存器 0x40000000–0x4003FFFF；ID 0x47535432（GST2）。
- AXI DMA 0x40400000–0x4040FFFF；Simple S2MM，无 SG。
- 每帧 640×480 RGB565，共 614400 字节、153600 个 32 位字。
- 软件触发完整帧快照，经异步 FIFO、DMA、PS HP0 写 DDR；不是已实现的 V4L2 连续视频接口。
- 通过 PL 寄存器实现开漏 SCCB、RESET/PWDN；不是默认 PS I2C。软件执行传感器初始化。
- 模块自带 24MHz XVCLK；目标 PCLK 42MHz，实际时序待板上验证。不要新增 PL XCLK。
- 参考 RGB565 排列和采集完成条件以 REGISTER_MAP、RTL 和配置表为准。
- UART0 经 EMIO，TX=L17、RX=M17，板载 CH340N 接 UART Type-C；115200/8N1/无流控。
- Linux 串口设备名按设备树确认，不假定 /dev/ttyPS0。使用前必须加载匹配 PL。
- 当前硬件未启用以太网或 PS USB，不依赖 SSH、USB 摄像头或网络下载完成首轮验收。

## 工作一：设备树与驱动

针对实际目标内核检查、修改并编译 `source/linux/gesture_vga.c` 及 UAPI。
合并设备树片段，检查父总线地址表示、reg、compatible、FCLK0/时钟引用、驱动探测和节点创建。
不为轮询设计虚构中断。编译设备树，不能只交付未经集成的片段。
明确 DMA 资源唯一所有者：沿用自定义驱动控制 DMA 时，不能让另一个 xilinx_dma 驱动绑定相同寄存器。
采用内核 DMA API 分配缓冲并管理一致性，核对 DMA 地址宽度和 CPU/DMA 地址差异，禁止任意固定 DDR 地址取帧。
实现独占/并发控制、超时、异常恢复和清晰错误信息。按完整协议验证字数、完成计数、帧有效性及 DMA 状态。
DMA 未停止时不得释放其仍可访问的内存；停止失败须阻止不安全重试并报告复位需求。
禁止驱动运行期间用 /dev/mem、SDK 或重新配置 PL 并发修改资源。
检查 .ko 架构、vermagic、目标内核符号及实际加载条件。不能用不匹配构建结果冒充兼容模块。
若选择不同驱动接口，必须同步修改用户态程序及所有说明。

## 工作二：初始化、采图和 UART 测试程序

优先复用 source/ps/hardware_vga.py、hardware.py、camera_probe.py 与 VGA 配置表。
hardware.py 中的 SCCB 方法是依赖，不能漏部署；不要调用其中旧 GST1 构造/取帧后端，不需要 libgesture_mmio.so。
实现统一测试入口（例如 run_camera_test.sh），先核对驱动和 GST2，再读 OV5640 ID=0x5640、执行初始化和关键寄存器回读。
开启彩条采三帧，关闭彩条等待稳定后采三帧真实图像，正确解释 RGB565 字节顺序并保存 PNG/BMP。
核对现有 Python 语法支持、NumPy/OpenCV 和编码能力；必要时兼容现有环境，不无理由升级。
每次测试记录阶段、返回码、帧序号、字节数、耗时、图片路径；区分程序执行成功与图像内容人工验收。
通过用户串口登录终端的 stdout 输出测试日志并同步落盘。第一轮保留控制台/getty，不关闭唯一操作入口，不争抢串口输入。
建议输出：[TEST] BEGIN、GST2_ID、OV5640_ID、COLORBAR_SAVED、FRAME_SAVED、CAPTURE_PASS/FAIL、END。
这些仅是格式，真实条件满足后才可打印 PASS，不得用生成的假图代替相机图像。

## 工作三：SD 卡持久存储和启动集成

检查实际 SD 分区及挂载；输出不得落到临时 rootfs/tmpfs。
优先保存到 Windows 读卡器可直接读取的 FAT 分区独立测试目录。挂载路径必须验证，不假定 /boot 是 SD 卡。
不覆盖启动文件；检查空间、可写性，使用每次唯一目录（不依赖有效 RTC），保存日志、图像和摘要并确保落盘。
说明正常关机后断电取卡流程；不默认自动关机。
HDF 是构建输入而非烧录文件。优先将匹配 FSBL、hardware/system.bit 和配套 U-Boot 打包成 BOOT.BIN，由 SD 启动早期配置 PL。
提供的 reference_standalone/gesture_fsbl.elf 来自当前 HDF，已编译但未实物验收；可审查后复用或重建，记录采用依据。
核对 DDR/PS 初始化、SD 启动和 UART；不要盲用旧 BOOT.BIN，更不能假定 Linux 启动后才配置 PL 也能获得当前 UART 通路。
用实际版本工具构建，不机械套用其他版本命令；不是 ZynqMP，不添加无关 PMUFW/ATF。
保留原系统，新的输出目录生成 boot/rootfs/模块/应用及需要的启动脚本。
交付完整可部署 SD 镜像，或完整分区材料、rootfs 及经过检查的制作脚本。真正写卡/格式化前确认目标盘，不猜测设备名。

## 检查、交付和验收

完成可行的驱动编译、设备树编译、脚本检查、RGB565 转换测试和启动文件组成检查。
可运行 `python3 -m unittest discover -s source/tests -p test_vga.py -v`；这是离线模拟测试，不是实物采集证明。
交付最终源码/补丁、实际模块与设备树、配置、测试入口、启动产物、完整 SD 制作材料、哈希、中文操作说明和状态表。
状态表必须区分已写代码、已编译、待上板、阻塞。没有实际内核构建或硬件测试不能声称已完成。
没有资料导致无法生成 BOOT.BIN/模块/完整镜像时，明确列出缺失项，不把半成品称为可启动完整系统。
板上验收顺序：启动和 UART → GST2 → OV5640 ID/配置 → 彩条 → 真实图像 → 正常关机 → 电脑读卡看图片 → 再启动复测。
本次不需要手动烧录 HDF，默认也不需要另接 JTAG 下载 bitstream；JTAG 仅作为必要时的排查手段。
请检查现有输入后直接实施，不要反复询问已经确定的目标。
''')

text('02_INPUTS_AND_DELIVERABLES.md', r'''
# 接手方输入与最终交付核对表

| 输入 | 本包提供 | 接手方需提供/确认 |
|---|---|---|
| HDF、bit、接线与寄存器说明 | 是 | 校验哈希并据此适配 |
| Linux 驱动/UAPI/DT 片段 | 参考源码 | 目标内核构建与设备树集成 |
| 采图与 SCCB 代码/寄存器表 | 参考源码 | 补齐测试入口、日志、持久存储及上板调试 |
| FSBL | 当前 HDF 的已编译候选和源码构建线索 | 审查复用或针对启动流程重建 |
| U-Boot、内核、rootfs/OpenCV | 否 | 使用本机最新已完成的系统 |
| 内核源码/配置/构建输出/Module.symvers（如需要） | 否 | 必须匹配最终运行内核；不能仅提供任意内核头文件 |
| 交叉工具链、sysroot | 否 | 明确实际路径和版本 |
| 最终 BOOT.BIN、image.ub 或对应启动文件 | 否 | 完成集成后生成 |
| SD 完整镜像/分区部署材料 | 否 | 完成集成后交付 |

最终交付验收清单：
- [ ] 硬件版本及启动文件组成明确；PL 在 UART 和驱动使用前已配置。
- [ ] 内核/DT/驱动版本匹配，模块或内建驱动可用。
- [ ] 初始化及取帧应用已部署，测试命令和登录方式清楚。
- [ ] 图片输出路径真实位于 SD 卡且电脑可读取。
- [ ] 给出 SD 写入/启动说明、备份和校验值。
- [ ] 所有未实物验证项单独标记，未把离线测试当成上板通过。

本阶段允许先检查系统启动再排查相机；不要求识别算法或机械手功能先完成。
''')

text('03_FIRST_BOARD_ACCEPTANCE.md', r'''
# 第一轮实物验收顺序（由 Linux 同学补入最终命令和路径）

本文件是验收表，不表示本包已经包含完成集成的启动卡。
最终 SD 卡来自 Linux 同学完成 01_LINUX_TASK_PROMPT.md 后的交付。

| 顺序 | 操作 | 通过标准 | 失败时优先记录 |
|---|---|---|---|
| 1 | 断电按 wiring.pdf 接相机，核对实物针1、供电和电平；插启动卡、设置经确认的 SD 启动模式 | 接线及启动介质与说明一致 | 实物接线/开关照片 |
| 2 | UART Type-C 接电脑，串口设 115200/8N1/无流控，保存日志，再上电 | 能看到启动输出并登录 | 从上电开始的完整串口日志 |
| 3 | 检查 PL 配置、驱动探测和设备节点 | 设备与当前硬件匹配，GST2=0x47535432 | dmesg、实际设备树及启动版本 |
| 4 | 执行接手方提供的一键测试入口 | SCCB ID=0x5640，初始化/回读通过 | ID、失败寄存器及错误码 |
| 5 | 保存至少三张彩条及三张真实图像 | 字数、状态与帧条件有效，文件写入持久 SD 分区 | DMA/采集状态、日志、输出目录 |
| 6 | 按说明正常关机，等待关闭后断电取卡，电脑读卡 | 图像为 640×480，彩条颜色/行列和真实画面正常 | 原始图片与日志，不仅拍屏幕 |
| 7 | 重新插卡启动并复测 | 能重复采集且不覆盖前次记录 | 第二次日志 |

第一轮 UART 验收是测试消息可见，不要求纯应用协议，不要关闭唯一串口控制台。
不要求串口传图片，不依赖 HDMI、网络或实时预览。
本阶段通过后再安排四指识别和机械手控制。
''')

text('reference_standalone/README.md', r'''
# 裸机参考产物

这两个 ELF 来自现有 Vivado/SDK 2019.1 HDF 硬件平台，已编译，未实物验证。
- gesture_fsbl.elf：匹配硬件的 FSBL 候选。接手方需核对启动流程后再用于 BOOT.BIN，或从 HDF 重建。
- camera_diag.elf：裸机诊断程序，不是 Linux 应用，不可在 Linux 下直接执行，也不能在 Linux 正运行时加载并争用硬件。

源码位于 ../source/sdk/，相关已有构建证据位于 ../hardware/logs/ 与 ../hardware/reports/。
HDF 内还有 PS 初始化信息；不要混用其他硬件导出的初始化文件。
''')

text('reference_hardware/README.md', r'''
# 接口审查用硬件参考

这里只提供 RTL 和创建脚本用于理解实际硬件连接，不是完整可重建工程。
当前硬件入口模块为 gesture_camera_vga，脚本中会列出 DMA/FIFO 等 IP 配置。
gesture_capture_axi/dvp_snapshot 含历史接口，不要把旧 GST1/BRAM 误当作当前接口。
优先使用已交付并核验的 hardware/system.hdf 和 system.bit；本阶段通常不需要改硬件。
不要直接运行这些创建脚本，它们引用的其他工程文件/输出目录不一定在本包内。
''')

manifest = {
    'purpose': 'Linux integration inputs for stage-1 SD image capture and UART message validation',
    'package_date': '2026-10-30',
    'hardware_build_date': '2026-10-29',
    'is_bootable_sd_image': False,
    'hardware_hashes': EXPECTED,
    'hdf_embedded_bit_matches': True,
    'target_linux_driver_built': False,
    'physical_validation': False,
    'source_files': source_files,
    'reference_elf_sha256': {p.name: sha(p.read_bytes()) for p in (OUT/'reference_standalone').glob('*.elf')},
    'notes': ['Existing source copied without modification',
              'No old Linux boot image or obsolete libgesture_mmio.so included',
              'hardware/manifest.json describes original hardware handoff; root manifest describes this bundle'],
}
text('PACKAGE_MANIFEST.json', json.dumps(manifest, ensure_ascii=False, indent=2))
# Parse code without generating __pycache__ or requiring target hardware.
for p in (OUT/'source').rglob('*.py'):
    ast.parse(p.read_text(encoding='utf-8-sig'), filename=str(p))
files = sorted(p for p in OUT.rglob('*') if p.is_file() and p != OUT/'SHA256SUMS')
text('SHA256SUMS', '\n'.join(sha(p.read_bytes()) + '  ' + p.relative_to(OUT).as_posix() for p in files))
archive = OUT.with_suffix('.zip')
with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for p in sorted(OUT.rglob('*')):
        if p.is_file():
            z.write(p, OUT.name + '/' + p.relative_to(OUT).as_posix())
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
    checks = z.read(OUT.name+'/SHA256SUMS').decode('utf-8').splitlines()
    for line in checks:
        digest, rel = line.split('  ', 1)
        assert sha(z.read(OUT.name+'/'+rel)) == digest, rel
    for rel in source_files:
        assert z.read(OUT.name+'/source/'+rel) == (ROOT/rel).read_bytes(), rel
    hdf_data = z.read(OUT.name+'/hardware/system.hdf')
    with zipfile.ZipFile(io.BytesIO(hdf_data)) as hdf:
        assert hdf.read(bits[0]) == z.read(OUT.name+'/hardware/system.bit')
archive.with_suffix('.zip.sha256').write_text(sha(archive.read_bytes())+'  '+archive.name+'\n', encoding='ascii')
print(json.dumps({'zip':str(archive), 'bytes':archive.stat().st_size,
                  'sha256':sha(archive.read_bytes()), 'verified_files':len(checks),
                  'hdf_bit_match':True, 'source_copy_match':True}, indent=2))
