# Load800 bounded warning guard - 2026-11-02

User authorized load hard threshold800 and a revised fault decision, preserving
all other guards. Prior release thumb OPEN7=508/OPEN8=514, CLOSED7=195/8=864,
speed5rad/s parameter and arrival-deadline fix remain unchanged.

Policy:
- Feedback load_raw>=800 immediately faults at the software check. Negative values
  still fault. This is not a mechanical torque rating or internal servo setting.
- Before ARM (torque mask0), feedback>=750 still refuses motion; no high-load start.
- During enabled operation,750..799 begins a per-servo100ms warning window.
- A sampled return below750 before the deadline clears that window and logs the
  measured duration, peak and position delta. It does not average or discard peaks.
- No clear sample before the deadline means fault on next guard check, even if a
  late sample is low. This is conservative sampled evidence, not a continuous-load
  measurement. Frequent sampling gaps may still cause a stop.
- Deadline checks occur before inspections, after feedback reads and before goal/
  speed writes. They cover every warned ID, not only the servo being queried.
- Retargeting, repeated high readings and another servo's low reading do not reset
  the timer. Release clears guard state and verifies torque-off as before.
- Warning state is bounded to8 servos; no sleeps/retry loops/extra UART reads added.
-100ms is a conservative software trial budget, NOT a manufacturer-approved
  overload time. Linux scheduling and serial calls mean this is NOT a hard
  real-time guarantee. Physical power cutoff must remain available.

Temperature55, voltage outside4.5..7.6V, no-progress/total timeout, path limits,
communication faults, manual FOLLOW_FINAL and fault torque release are unchanged.
The prior load840 and voltage7.7 examples STILL fault by design. This patch does
not claim to solve those reported events or authorize continued force at840.

Runtime files changed: hand_endpoints.py, hand_final.py and hand_worker.py (policy
log only). All recognition/camera/display/servo endpoint and bus sources unchanged.
Logging adds LOAD_WARNING_STARTED/CLEARED and warning evidence in fault snapshots.
No servo EEPROM,BOOT.BIN,image.ub or rootfs changes are part of this patch.

Tests: Linux host189 run182 pass7 skipped; ARM/Python3.5 user-mode QEMU200 run199
pass1 skipped. Includes21 new guard tests and full prior regressions. One old
threshold750 immediate-fault test was updated to800; startup750 still refuses ARM.
No physical actuator test has been performed.

Existing startup command/manual token unchanged. First test must be short, empty,
secured and attended; stop for hard-stop contact or sustained force. Ctrl+C requests
release; cut servo power if unconfirmed. Shut Linux down before removing the card.
Historical LOAD750_NOTE/ARRIVAL_FIX_NOTE records retain their original thresholds;
this document states the current candidate policy and supersedes those limits.
