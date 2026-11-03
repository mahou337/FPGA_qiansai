# Smart ZYNQ SL：真实手部掩膜 HDMI 候选版本

这是现有 OV5640 VGA + PS UART1 平台的独立增量，不是替代相机/识别工程。完整状态见 `docs/FINAL_STATUS.md`，硬件检查见 `docs/verification/hdmi_hardware_verification.json`。

## 数据通路

`masks['final_hand_mask'] (240行×320列 uint8)` → 76,800 字节不可变快照 → Python 单个最新帧槽 → 工作线程一次 write → 内核专属暂存 → AXI GP0 独立 BRAM 双缓冲 → 帧边界交换 → PL 2×复制 → 640×480 / 60Hz → rgb2dvi → J29。

默认最多每秒提交5张，显示扫描每秒60次；没有新图重复前一张，上电/首帧前为黑。无 DDR 显示 DMA、无新中断。不要传原图、重新阈值化结果或 PNG 作为真实掩膜。

## 当前交付边界

- RTL、构建脚本、引脚约束、仿真、Linux驱动源码、DT片段、Python显示组件和独立测试程序在本包内。
- 最新 `hand_final_thumb20_path30_20261102/delivery/app` 不在本电脑；`ps_display/INTEGRATION.md` 是准确接入位置说明，尚未应用到该 app。
- 本机未编译 Linux4.19 模块，未构建候选 BOOT.BIN/image.ub；必须在负责 Linux 的电脑上继续集成。
- 没有连接/配置实体板、SD卡、显示器或机械手；没有实测识别性能。不能据离线通过宣称最终功能验收。
- 硬件 DDC/HPD 未连接，无法由本板获取EDID。640×480 /25.2MHz 是候选标准低开销模式，目标显示器仍待确认。

## 文件入口

| 路径 | 内容 |
|---|---|
| scripts/build_vga_bitstream.tcl | 从本目录源码建立工程、综合、实现、报告、导出 bit/HDF |
| scripts/create_vivado_vga.tcl | 保持原系统并添加显示的 BD 创建脚本 |
| pl/mask_display_axi.v、mask_display_clocks.v | 双缓冲/时序/AXI与显示专用时钟 |
| config/hdmi_output.xdc | 实际J29引脚及局部CDC约束 |
| ip/rgb2dvi | 从用户参考仓库复制的1.4版，许可与局部元数据修改说明保留 |
| linux | Linux4.19模块、UAPI头、Makefile、PetaLinux recipe和DT片段 |
| ps_display | Python3.5兼容显示组件、测试、回放基准和接入说明 |
| docs/HARDWARE_INTERFACE.md | 引脚、寄存器、所有权及复位 |
| docs/LINUX_HANDOFF.md | Linux电脑上继续集成步骤 |
| docs/VALIDATION_ROLLBACK.md | 实板顺序、性能对照和回退 |

## 重建

使用已安装的 Vivado **2019.1**、Zynq-7000器件支持与相应许可。在此目录的独立解压副本执行：

```text
vivado -mode batch -source scripts/build_vga_bitstream.tcl -log build/vivado_hdmi.log -journal build/vivado_hdmi.jou
```

脚本按自身位置解析源码路径，会重建该副本下的 `build/vivado_vga`；不要在唯一归档或原工作版本上运行。HDF输出为 `build/vga_system.hdf`，bit为 `build/vga_system.bit`，交付包内以 `system.hdf/system.bit`命名。工具/IP库不随包分发。生成的XPR、日志可能记录本机绝对路径，重建入口不依赖这些缓存路径。

历史 `scripts/verify_handoff.py` 仅适用于 UART1 增量，HDMI版使用 `verify_hdmi_handoff.py`。历史 ARM编译/接线PDF脚本不是本次显示构建入口，其外部环境不作为重建依赖。
