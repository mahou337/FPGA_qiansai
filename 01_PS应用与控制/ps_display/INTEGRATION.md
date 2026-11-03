# 最新应用接入：尚未在本机执行

本机未找到 `hand_final_thumb20_path30_20261102/delivery/app`。不能用旧版 headless.py 冒充。
将本目录 mask_display.py 复制到**最新 app 的独立副本**的 ps 目录；先阅读实际 run.py 的入口、退出和异常路径，再应用下面三个局部改动。不要替换识别算法或 UART 代码。

1. 在现有 argparse 中新增独立参数 `--hdmi` (store_true，默认关闭)、`--hdmi-hz` (float，默认5)。不引用 --no-images。
2. 在主循环外创建一个 `MaskDisplay(enabled=args.hdmi, hz=args.hdmi_hz)`。导入方式按照原包结构使用 `from .mask_display import MaskDisplay` 或 `from mask_display import MaskDisplay`，不能猜原项目的启动方式。
3. 紧接现有 `result, masks, timing = recognizer.process(frame)` 插入：

```python
if display.enabled:
    display.submit(masks.get('final_hand_mask'))
```

不要更改 result、timing 或后续动作逻辑。finally 中调用 `display.close()`，并将 `display.stats()` 合并到原有运行统计（不要逐帧写日志）。如果原程序没有统一 finally，先整理清理路径，保留相机和机械手原有关闭行为。

数组要求 shape=(240,320), dtype=uint8，行序自上向下，无隐式阈值化或缩放。本模块复制为不可变 bytes 后才交给工作线程。旧版代码显示 final_hand_mask 来源是算法最终分割结果；**最新版数值是否只有0/255仍需用实际 app 检查**。仅首次诊断用 np.unique(mask) 检查，不能在每帧主循环增加全图验证。

首次测试只运行 display_test.py；真实识别接入时必须沿用现有禁用机械手的方法。未获授权不可为测试打开 UART 动作。无新图时保持上一帧；退出或设备关闭后最多两个帧边界内变黑。显示不可用仅停用显示，不改变识别结果或触发动作。

本模块不是已应用的补丁。需要整个最新 app 才能完成准确修改、固定回放基准和真实掩膜验收。
