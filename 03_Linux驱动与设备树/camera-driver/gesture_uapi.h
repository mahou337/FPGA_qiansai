#ifndef GESTURE_UAPI_H
#define GESTURE_UAPI_H
#include <linux/types.h>
#include <linux/ioctl.h>
struct gesture_reg { __u32 offset; __u32 value; };
#define GESTURE_REG_READ _IOWR('G', 0, struct gesture_reg)
#define GESTURE_REG_WRITE _IOW('G', 1, struct gesture_reg)
#define GESTURE_CAPTURE _IOW('G', 2, __u32)
/* Fixed-width 48-byte ABI: valid on the 32-bit ARM board without pointers. */
struct gesture_status {
 __u32 abi_version, capture_status, sequence, words;
 __u32 dma_status, dma_length, elapsed_us;
 __s32 result;
 __u32 frame_bytes, broken, dma_control, reserved;
};
#define GESTURE_GET_STATUS _IOR('G', 3, struct gesture_status)
#endif
