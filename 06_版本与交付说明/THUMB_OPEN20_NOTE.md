# Thumb straight endpoint offset - 2026-11-02

User explicitly authorized each thumb servo to extend approx20 servo degrees
beyond the previous straight endpoint. Quantization round(20*1024/300)=68raw,
actual commanded offset19.921875 degrees per servo, NOT measured finger angle.

ID7 OPEN:440->508 (+68). ID8 OPEN:582->514 (-68).
CLOSED remains ID7=195, ID8=864. Other six endpoints unchanged.
LIMITS are derived from OPEN/CLOSED: ID7 becomes195..508, ID8 becomes514..864.
The existing feedback margin15raw still applies beyond these requested endpoints.
This intentionally extends commanded travel. No physical limit/clearance or loaded
motion validation has been performed. A value inside0..1023 is not a mechanical
safety guarantee. Stop immediately for hard-stop contact or sustained force.

Speed5rad/s parameter, load<750, temperature<55, voltage checks, path margin,
arrival fix, fault torque release, UART1 and manual FOLLOW_FINAL remain unchanged.
No servo EEPROM/internal safety settings or BOOT.BIN/image.ub/rootfs changes.

ACTIVE_ENDPOINTS.json records the new OPEN values and a separate hash-linked
THUMB_OPEN_INCREMENT_REQUEST.json. Historical observation records and previous
closed-direction adjustment records are preserved, not rewritten as measurements.
This note supersedes old straight endpoint440/582 statements in previous docs.

Startup remains run_hdmi_follow.sh with interactive FOLLOW_FINAL. Test briefly
with an empty, secured hand and physical servo-power cutoff available. No automatic
startup motion. Ctrl+C requests release; cut servo power if release is unconfirmed.

Rollback restores hand_endpoints.py, ACTIVE_ENDPOINTS.json and both SHA256SUMS
from the rollback directory as a version set. Remove the added delivery request
record only when rolling back, to satisfy the old complete-file manifest.
