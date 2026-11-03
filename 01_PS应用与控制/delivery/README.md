# 路径裕量30raw + 拇指增加约20度弯曲版（2026-11-02）

基于hand_final_closed2_20261102。用户要求扩大路径边界并使拇指更弯曲20度。
路径裕量独立设置PATH_MARGIN_RAW=30（原15）；实际路径允许区间同时裁剪到逐舵机全行程反馈范围。全行程反馈裕量仍15、到位/静止偏差仍15。
ID3起点189、目标418的有效路径变为159..433，反馈168可通过；158越出路径仍停机，434越出全行程反馈范围仍停机。反向移动不代表故障已修复，0.8秒无进展及总期限仍执行。
拇指奇数7弯曲减raw、偶数8弯曲增raw。20度量化为68raw（19.921875度）：ID7从263改195；ID8从796改864。此为用户授权的计算增量，不是新实测端点，不得标为带载验收通过。
全部伸直raw不变：584 404 418 602 439 576 440 582。
全部弯曲raw：206 769 90 989 128 895 195 864。除拇指外其余六舵机不变。
依据：ACTIVE_ENDPOINTS.json、原始closed_observed_094229.json和THUMB_INCREMENT_REQUEST.json。原始测量记录不改。
拇指新全行程反馈范围ID7=180..455，ID8=567..879。不能将路径裕量30当作扩大全局反馈或到位误差。
保持MaxSpeed=5（977）、4.5～7.6V、负载<700、温度<55、UART校验超时、故障释放、ARM非预期移动>3raw保护。识别源码/配置不变。
新拇指增加行程尚未实机带载验证；可能仍触发负载或路径保护，不得反复重启或强扳。固定台架、清空运动区域、备好断电开关后才手动授权。
启动：sh /mnt/sdcard/hand_final_thumb20_path30_20261102/run_follow.sh
FOLLOW_FINAL授权；Q回车/Ctrl+C释放退出。旧版保留，不自启，不改固件。
以下为历史资料，旧拇指端点及旧路径裕量不适用于本版。

---
# 新弯曲端点独立版（2026-11-02）

本版基于hand_final_speed5_margin15_v76_20261102，按用户最新确认数据更新8个弯曲端点，伸直端点不变。
ID：       1   2   3   4   5   6   7   8
伸直raw：584 404 418 602 439 576 440 582
弯曲raw：206 769  90 989 128 895 263 796
权威当前端点文件ACTIVE_ENDPOINTS.json；原始用户快照closed_observed_094229.json。旧open_closed_observed_214705.json和旧确认文件仅保留作历史记录，不覆盖当前弯曲端点。
LIMITS由新端点逐舵机生成，不裁剪、不强制对称、不使用±100度旧范围。行程/路径反馈裕量±15raw，到位误差±15raw。
反馈允许范围ID1..8依次为191..599、389..784、75..433、587..1004、113..454、561..910、248..455、567..811。
MaxSpeed=5（977）、4.5～7.6V窗口及负载、温度、UART、运动故障和释放保护保留；识别源码/配置不变。
输入位序拇/食/中/无名，1伸直0弯曲。单帧/PENDING即时目标策略不变，无新确认等待或自动动作。
用户快照全部torque=0；新端点是用户确认的静态位置，不代表新全行程带载验证通过。
尤其新拇指行程比旧版收窄：若启动位置仍在旧弯曲107/887，会被新反馈范围拒绝。不会自动回零/越界拉回，不应绕过保护。
启动：sh /mnt/sdcard/hand_final_closed2_20261102/run_follow.sh
FOLLOW_FINAL授权，Q回车/Ctrl+C释放退出。新程序实机联动尚未验收。旧程序独立保留，不改BOOT/设备树，不自启。
以下为历史说明，旧弯曲raw不适用于本版。

---
# 电压上限7.6V独立版（2026-11-02）

基于hand_final_speed5_margin15_20261102，仅按用户最新要求修改电压反馈软件窗口为4.5～7.6V（包含边界）。
所有8个舵机统一执行：7.6V通过，超过7.6V、低于4.5V或非有限值仍故障。实际检查与CONTROL_POLICY日志共用VOLTAGE_WINDOW，避免保留隐藏7.5V门槛。
软件上限变化不是调整物理电源，也不代表改变或验证厂商额定电压。
MaxSpeed=5（寄存器977）、实测端点、行程/路径反馈裕量±15raw、到位误差±15raw均不变。
负载<700、温度<55、UART校验超时、运动故障、异常退出释放及ARM非预期位移检查保留。识别源码和配置不变，未解决既有识别不稳定或通信问题。
本次用户日志ID2：反馈405/目标404、7.6V、17℃、负载0已加入回归；新程序尚未实机验收。
启动：sh /mnt/sdcard/hand_final_speed5_margin15_v76_20261102/run_follow.sh
FOLLOW_FINAL授权；Q回车或Ctrl+C释放退出。手动启动，无开机动作；旧版本保留。
以下历史版本的7.5V上限不适用于本版，以本节及程序实际配置为准。

---
# MaxSpeed=5 + 行程反馈裕量±15raw 独立版（2026-11-02）

本版基于hand_final_speed7_20261102，只按用户要求修改速度及反馈/路径裕量，识别源码和配置保持不变。
全部8个舵机双向速度参数5.0 rad/s，沿用现有驱动转换，寄存器46写977（03 D1）；不是实测速度。
目标端点不变，普通运动目标不得超出各舵机实测两端。反馈范围为每个实测区间外扩±15raw，到位/静止目标容差仍±15raw。
运动路径两端的反馈裕量同样使用15raw，不留下旧3raw路径起点限制；仍与全行程反馈范围取交集。
当前位置ARM seed仍保留写入前后异常位移>3raw的保护：这是启动时非预期运动检查，不是运动目标的到位或行程裕量。
ID5目标439、反馈443应通过；ID5全局反馈范围238..454，455必须故障。端点439不会被改成454。
负载<700、温度<55、4.5～7.5V、UART超时校验、0.8秒无进展、运动总超时及故障释放均保留。负载750仍会停机，不保证降速就能消除该故障。
识别稳定性问题及此前UART故障未修复；本版高速度实际运动/扩大裕量实机尚未验收。不要佩戴或接触运动区域。
启动：sh /mnt/sdcard/hand_final_speed5_margin15_20261102/run_follow.sh
授权词FOLLOW_FINAL；Q回车或Ctrl+C释放退出；不自启、不更改固件和启动文件。
下面为历史说明，历史速度7和±3raw反馈裕量不适用于本版。

---
# MaxSpeed=7 独立版（2026-11-02）

本版基于 hand_final_tol15_20261101，仅调整速度链和相关提示，不修改识别算法。
按本机 AmazingHand_Demo.py 的 MaxSpeed=7 参数语义设置全部8舵机双向速度为7.0 rad/s；复用rustypot 1.10.0 Velocity::to_raw转换，写寄存器46的值1368（大端05 58），不裁剪成1023、不写0/无限速。
这是软件速度参数，不代表舵机能够达到7 rad/s；本机参考库Velocity::from_raw有0x3ff掩码，本版不使用该函数测量速度，不能据此声称已验证固件物理速度。启动写入后仍逐项读回寄存器检查，不匹配立即故障退出。
相对上一版参数提高28倍；未验证高速度实机安全、到位时间或实际角速度。
±15raw到位/静止目标容差、逐舵机端点与±3raw行程安全裕量、4.5～7.5V、温度/负载/通信/路径保护保留。
运动总超时继续由当前配置速度计算，保留2秒余量及0.8秒无进展故障；没有关闭故障检测。
识别稳定性问题、此前ID1路径故障及UART响应超时尚未解决。本版不得宣称已修复这些问题或通过实机联动验收。
启动：sh /mnt/sdcard/hand_final_speed7_20261102/run_follow.sh
明确授权词仍为FOLLOW_FINAL；手动运行，不自启。台架固定、手部区域无人接触且断电开关可及时操作时才授权；不得将机械手戴在人体上测试。
回退：sh /mnt/sdcard/hand_final_tol15_20261101/run_follow.sh
下面是旧版本历史说明；旧0.25rad/s与速度raw48不适用于本版。

---
# User-requested arrival tolerance: +/-15 raw (4.39453125 degrees)

Release: hand_final_tol15_20261101
After deployment, run:
    sh /mnt/sdcard/hand_final_tol15_20261101/run_follow.sh
Authorize with FOLLOW_FINAL. Q+Enter or Ctrl+C releases and exits.

Arrival and stationary target-error tolerance are now BOTH inclusive +/-15raw.
The target-end path check admits that arrival band rather than secretly applying
an old +/-3raw target gate. The per-servo calibrated travel envelope is STILL
unchanged (endpoint min/max plus3raw feedback margin), and the current-position
ARM movement guard is still3raw. This does NOT extend physical commanded travel.
Thus permissible feedback must satisfy BOTH arrival tolerance and safe travel.
All final command values remain the exact user-confirmed endpoints.

ID4 target602 and measured608 (error+6) is inside the new arrival band, so that
error alone will no longer trigger the no-progress fault. Quiet feedback0.20s is
still used only to classify settled motion; it never delays a new goal.
Single-frame/PENDING triggering, latest-goal replacement, controlled speed0.25rad/s,
voltage4.5..7.5V, UART timeout/checksum, thermal/load, no-progress0.8s OUTSIDE
arrival tolerance, total motion timeout and verified release are retained.
New software tests do not constitute physical acceptance. No recalibration.

## Previous revision background (arrival/stationary +/-3raw is superseded above)

# Final endpoint follower: settle/exit-report fix

Independent release: hand_final_tol15_20261101. This does not replace the old directory.
Run ONLY after this directory has been copied to SD and hash-verified:

    sh /mnt/sdcard/hand_final_tol15_20261101/run_follow.sh

Type FOLLOW_FINAL on the board console to authorize this session. Q+Enter or Ctrl+C stops.
Keep the hand unloaded, secured and clear of people; prepare a physical servo-power cutoff.
No installation, startup action, firmware/BOOT.BIN/image.ub/HDF/device-tree change.

## Confirmed endpoints UNCHANGED
Bit order: thumb, index, middle, ring. 1=straight, 0=bent.
ID:       1   2   3   4   5   6   7   8
Straight: 584 404 418 602 439 576 440 582
Bent:     343 609 197 846 253 826 107 887
Pairs: index1/2, middle3/4, ring5/6, thumb7/8.
No recalibration, symmetry assumption, clipping or zeroing.

## Board fault that motivated this revision
The previous program wrote ID2 from407 to404, a distance of3raw.
It created motion tracking only for distance>3, immediately treating this new
small goal as stationary. Its next error>3 feedback therefore aborted at once.
The actual failing feedback raw was not logged. We do NOT claim it was harmless
jitter or that there cannot also be a physical deviation.
The supplied board log contains two TORQUE_OFF_VERIFIED records after the fault.
The parent's generic release-not-confirmed message was misleading.

## Fix, without changing gesture triggering
Every changed goal gets motion tracking, even at pre-write distance0..3raw.
A first in-tolerance feedback sample no longer immediately means stationary.
ENDPOINT_REACHED now needs <=3raw target error and a quiet measured span<=1raw
for0.20s. This is NONBLOCKING feedback-state qualification, NOT gesture debounce:
- No delay before the final goal is sent.
- New complete LIVE raw, including usable PENDING, still acts on one frame.
- No two-frame or0.75s gesture gate, no initial1111 actuator arming gate.
- New goals replace old goals DURING this feedback observation period.
- No intermediate goals, repeated same-goal writes or wait-until-settled loop.

The position/trajectory envelopes and stationary-drift check are not widened.
A persistent error still trips0.8s no-progress or the per-goal total deadline.
A departure after genuinely settling still trips stationary-drift protection.
Position faults include servo ID, measured raw, target raw, signed error, voltage,
temperature and load. FAULT includes cached feedback/targets BEFORE release.
Release precedes fault logging; diagnostics do not add UART queries on failure.

A final HAND_EXIT acknowledgement now distinguishes:
- fault with all eight torque-off verified: HAND_FAULT_RELEASE_VERIFIED;
- missing/failed release confirmation: HAND_RELEASE_NOT_CONFIRMED, cut servo power.
A fault still returns nonzero. The fix does not hide the original fault.

## Unchanged protections
Speed0.25rad/s (register48); per-servo endpoint bounds with +/-3raw feedback margin;
4.5..7.5V; temperature<55C; load_raw<700; torque mask, goal_time=0, speed and goal
readback; UART35ms response timeout, checksum/ID/length and exclusive ownership;
original ARM/UART1 hardware identity checks; real stream-loss protection;
release on unknown/no-hand, IPC/serial/camera/log faults, EOF and signals.
No-progress0.8s; total deadline2+2*distance_raw/48 seconds; ARM transaction3s.
Optional geometric evidence checks for unknown fingers remain unchanged.
No diagnostic PNGs by default; no hand gesture queues.

Logs: /mnt/sdcard/gesture-tests/run-*/hand_events.jsonl and hand_stderr.log.
Local and simulated tests are NOT physical linkage acceptance.
