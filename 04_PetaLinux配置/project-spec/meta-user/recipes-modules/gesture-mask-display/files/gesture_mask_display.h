#ifndef GESTURE_MASK_DISPLAY_H
#define GESTURE_MASK_DISPLAY_H
#include <linux/types.h>
#include <linux/ioctl.h>
struct gesture_mask_status {
 __u32 identity,status,dimensions,bytes,swaps,errors,reserved0,reserved1;
};
#define GESTURE_MASK_STATUS _IOR('M',0,struct gesture_mask_status)
#define GESTURE_MASK_MODE _IOW('M',1,__u32)
#endif
