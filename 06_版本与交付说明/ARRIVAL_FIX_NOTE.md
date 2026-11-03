# Arrival-deadline fix, 2026-11-02

Only delivery/app/ps/hand_final.py changes runtime behavior. Original endpoints,
5 rad/s configured speed, 15 raw arrival tolerance, 1 raw quiet span, 0.20 second
quiet qualification, load<700, temperature<55, voltage and travel protections
are unchanged. Existing motion deadlines are not reset.

The previous monitor checked timeout before qualifying arrival. This patch allows
one bounded late acknowledgement ONLY when the quiet window began early enough
to qualify before the original deadline, the previous feedback was before that
deadline, the feedback gap is at most 0.20 second, and the current observation is
at most 0.20 second late. Current feedback must still satisfy the original health,
path and quiet-span checks. No fresh settling window is allowed after deadline.
This is sampled-feedback evidence, not proof of continuous physical stillness.
First late arrival, late-started settling, excessive gaps, jitter and overload
remain faults. In particular load 710 still trips the original load protection.

Last 8 feedback samples per active servo are retained in bounded RAM for fault
reports; no extra UART reads or per-sample SD writes are added. A sample contains
monotonic timestamp, position raw, and load raw. Timeout logs include quiet-window
history and deadline/observed time. A resolved late confirmation includes its lag.

Tests: native Linux 162 run, 155 passed, 7 skipped; ARM Python3.5 user-mode QEMU
173 run, 172 passed, 1 skipped (pseudo-terminal high-baud test covered natively).
12 new regression cases included. Not a physical robot test and not a claim that
the historical fault is solved; its log lacks full feedback history.

Existing manual run_hdmi_follow.sh and FOLLOW_FINAL authorization are unchanged.
No automatic motion. If servo 6 still overloads, do not repeat starts or raise
load thresholds; inspect mechanical load with servo power removed.

Rollback: restore the three changed files from the card rollback directory or
PC backup as one version set: hand_final.py, delivery/SHA256SUMS, root SHA256SUMS.
No BOOT.BIN/image.ub or rootfs changes are needed.
