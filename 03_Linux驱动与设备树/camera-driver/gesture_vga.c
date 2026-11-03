/* VGA snapshot driver: owns both the capture registers and AXI DMA S2MM.
 * Target compiled API: Linux 4.19.0-xilinx-v2019.1 ARMv7. Build against the EXACT board kernel.
 * No guessed physical DDR address, /dev/mem RAM mapping, or userspace DMA.
 */
#include <linux/module.h>
#include <linux/platform_device.h>
#include <linux/of.h>
#include <linux/clk.h>
#include <linux/dma-mapping.h>
#include <linux/miscdevice.h>
#include <linux/fs.h>
#include <linux/uaccess.h>
#include <linux/mutex.h>
#include <linux/io.h>
#include <linux/iopoll.h>
#include <linux/delay.h>
#include <linux/slab.h>
#include <linux/ktime.h>
#include <linux/sched/signal.h>
#include "gesture_uapi.h"
#define FRAME_BYTES (640U * 480U * 2U)
#define DMA_CR 0x30
#define DMA_SR 0x34
#define DMA_ADDR 0x48
#define DMA_LEN 0x58
#define DMA_ERRORS 0x70
struct gesture_dev {
 struct device *dev;
 void __iomem *cap, *dma;
 struct clk *clk;
 struct miscdevice misc;
 struct mutex lock;
 void *frame;
 dma_addr_t frame_dma;
 bool opened, ready, broken;
 struct gesture_status last;
};
/* Halt production first, then use DMA's own reset to complete/abort its bus work.
 * Never assert DMA external reset while transactions are outstanding. */
static int quiesce(struct gesture_dev *g)
{
 u32 val;
 writel(readl(g->cap + 4) | 16, g->cap + 4);
 readl(g->cap + 4);
 usleep_range(1000, 1500);
 writel(4, g->dma + DMA_CR);
 if (readl_poll_timeout(g->dma + DMA_CR, val, !(val & 4), 10, 100000)) {
  g->broken = true;
  dev_err(g->dev, "DMA reset timed out; board reset required, buffer/clock retained\n");
  return -ETIMEDOUT;
 }
 if (readl_poll_timeout(g->dma + DMA_SR, val, val & BIT(0), 10, 100000)) {
  g->broken = true;
  dev_err(g->dev, "DMA did not halt after reset; board reset required\n");
  return -EIO;
 }
 return 0;
}
static void record_status(struct gesture_dev *g, ktime_t start, int result)
{
 g->last.abi_version = 1;
 g->last.capture_status = readl(g->cap + 12);
 g->last.sequence = readl(g->cap + 16);
 g->last.words = readl(g->cap + 20);
 g->last.dma_status = readl(g->dma + DMA_SR);
 g->last.dma_length = readl(g->dma + DMA_LEN);
 g->last.elapsed_us = min_t(s64, ktime_us_delta(ktime_get(), start), U32_MAX);
 g->last.result = result;
 g->last.frame_bytes = FRAME_BYTES;
 g->last.broken = g->broken;
 g->last.dma_control = readl(g->dma + DMA_CR);
}
static int snapshot(struct gesture_dev *g, u32 timeout_ms)
{
 u32 seq, done_seq, cap, dma;
 unsigned long end;
 int ret;
 ktime_t start = ktime_get();
 g->ready = false;
 if (g->broken) { record_status(g, start, -EIO); return -EIO; }
 if ((readl(g->cap + 4) & 3) != 1) { record_status(g, start, -EIO); return -EIO; }
 ret = quiesce(g);
 if (ret) { record_status(g, start, ret); return ret; }
 /* Reset stays asserted long enough for both FIFO clock domains. PCLK must run. */
 writel(readl(g->cap + 4) & 15, g->cap + 4);
 usleep_range(1000, 1500);
 seq = readl(g->cap + 16);
 dma_wmb();
 writel(1, g->dma + DMA_CR); /* RS, interrupts disabled; bounded polling below */
 writel(lower_32_bits(g->frame_dma), g->dma + DMA_ADDR);
 writel(FRAME_BYTES, g->dma + DMA_LEN); /* length LAST arms reception */
 writel(1, g->cap + 8);
 end = jiffies + msecs_to_jiffies(timeout_ms);
 for (;;) {
  dma = readl(g->dma + DMA_SR);
  /* Sequence is the publication barrier: sample it BEFORE associated status. */
  done_seq = readl(g->cap + 16);
  cap = readl(g->cap + 12);
  if (dma & DMA_ERRORS) { ret = -EIO; break; }
  if (done_seq != seq) {
   if (done_seq != (u32)(seq + 1) || (cap & 7) != 1 || readl(g->cap + 20) != FRAME_BYTES/4) {
    ret = -EBADMSG; break;
   }
   if (dma & BIT(12)) { /* IOC: complete packet committed by DMA */
    if (!(dma & BIT(1)) || readl(g->dma + DMA_LEN) != FRAME_BYTES) {
     ret = -EIO; break;
    }
    dma_rmb();
    record_status(g, start, 0);
    g->ready = true;
    return 0;
   }
  }
  if (signal_pending(current)) { ret = -ERESTARTSYS; break; }
  if (time_after_eq(jiffies, end)) { ret = -ETIMEDOUT; break; }
  usleep_range(500, 1000);
 }
 dev_warn(g->dev, "snapshot error %d cap=%08x dma=%08x\n", ret, cap, dma);
 record_status(g, start, ret); /* preserve fault registers BEFORE reset */
 if (quiesce(g)) {
  g->last.broken = 1;
  g->last.result = -EIO;
  return -EIO;
 }
 return ret;
}
static int gesture_open(struct inode *inode, struct file *file)
{
 struct miscdevice *m = file->private_data;
 struct gesture_dev *g = container_of(m, struct gesture_dev, misc);
 int ret = 0;
 mutex_lock(&g->lock);
 if (g->broken) ret = -EIO;
 else if (g->opened) ret = -EBUSY;
 else { g->opened = true; g->ready = false; file->private_data = g; }
 mutex_unlock(&g->lock);
 return ret;
}
static int gesture_release(struct inode *inode, struct file *file)
{
 struct gesture_dev *g = file->private_data;
 mutex_lock(&g->lock);
 quiesce(g);
 writel(18, g->cap + 4); /* reset low, powerdown high, FIFO held reset */
 g->ready = false; g->opened = false;
 mutex_unlock(&g->lock);
 return 0;
}
static long gesture_ioctl(struct file *file, unsigned int cmd, unsigned long arg)
{
 struct gesture_dev *g = file->private_data;
 struct gesture_reg reg;
 u32 timeout;
 int ret = 0;
 if (mutex_lock_interruptible(&g->lock)) return -ERESTARTSYS;
 switch (cmd) {
 case GESTURE_GET_STATUS:
  if (copy_to_user((void __user *)arg, &g->last, sizeof(g->last))) ret=-EFAULT;
  break;
 case GESTURE_REG_READ:
  if (copy_from_user(&reg, (void __user *)arg, sizeof(reg))) { ret=-EFAULT; break; }
  if ((reg.offset & 3) || reg.offset > 0x18) { ret=-EINVAL; break; }
  reg.value = readl(g->cap + reg.offset);
  if (copy_to_user((void __user *)arg, &reg, sizeof(reg))) ret=-EFAULT;
  break;
 case GESTURE_REG_WRITE:
  if (copy_from_user(&reg, (void __user *)arg, sizeof(reg))) { ret=-EFAULT; break; }
  /* Userspace controls SCCB and sensor pins only; DMA/trigger owned here. */
  if (reg.offset != 4 || (reg.value & ~15U) || g->broken) { ret=-EINVAL; break; }
  g->ready = false;
  writel(reg.value, g->cap + 4); readl(g->cap + 4);
  break;
 case GESTURE_CAPTURE:
  if (copy_from_user(&timeout, (void __user *)arg, sizeof(timeout))) { ret=-EFAULT; break; }
  if (!timeout || timeout > 10000) { ret=-EINVAL; break; }
  ret = snapshot(g, timeout);
  if (!ret) file->f_pos = 0;
  break;
 default: ret=-ENOTTY;
 }
 mutex_unlock(&g->lock);
 return ret;
}
static ssize_t gesture_read(struct file *file, char __user *buf, size_t len, loff_t *pos)
{
 struct gesture_dev *g = file->private_data;
 ssize_t ret;
 if (mutex_lock_interruptible(&g->lock)) return -ERESTARTSYS;
 if (!g->ready) ret=-ENODATA;
 else ret=simple_read_from_buffer(buf, len, pos, g->frame, FRAME_BYTES);
 mutex_unlock(&g->lock);
 return ret;
}
static const struct file_operations gesture_fops = {
 .owner=THIS_MODULE, .open=gesture_open, .release=gesture_release,
 .unlocked_ioctl=gesture_ioctl, .read=gesture_read, .llseek=no_llseek,
};
static int gesture_probe(struct platform_device *pdev)
{
 struct gesture_dev *g;
 int ret;
 g=devm_kzalloc(&pdev->dev, sizeof(*g), GFP_KERNEL);
 if (!g) return -ENOMEM;
 g->dev=&pdev->dev;
 g->cap=devm_ioremap_resource(&pdev->dev, platform_get_resource(pdev, IORESOURCE_MEM, 0));
 if (IS_ERR(g->cap)) return PTR_ERR(g->cap);
 g->dma=devm_ioremap_resource(&pdev->dev, platform_get_resource(pdev, IORESOURCE_MEM, 1));
 if (IS_ERR(g->dma)) return PTR_ERR(g->dma);
 g->clk=devm_clk_get(&pdev->dev, "fclk0");
 if (IS_ERR(g->clk)) return PTR_ERR(g->clk);
 ret=clk_prepare_enable(g->clk);
 if (ret) return ret;
 if (clk_get_rate(g->clk) != 50000000 || readl(g->cap) != 0x47535432 ||
     readl(g->cap+0x18) != ((480U<<16)|640U)) { ret=-ENODEV; goto clock_off; }
 ret=dma_set_mask_and_coherent(&pdev->dev, DMA_BIT_MASK(32));
 if (ret) goto clock_off;
 ret=quiesce(g);
 if (ret) {
  dev_err(g->dev, "probe: DMA unsafe, keep AXI clock until board reset\n");
  return ret;
 }
 g->frame=dma_alloc_coherent(&pdev->dev, FRAME_BYTES, &g->frame_dma, GFP_KERNEL);
 if (!g->frame) { ret=-ENOMEM; goto clock_off; }
 mutex_init(&g->lock);
 g->misc.minor=MISC_DYNAMIC_MINOR;
 g->misc.name="gesture-camera";
 g->misc.fops=&gesture_fops;
 g->misc.parent=&pdev->dev;
 g->misc.mode=0600;
 ret=misc_register(&g->misc);
 if (ret) goto free_frame;
 platform_set_drvdata(pdev, g);
 record_status(g, ktime_get(), -ENODATA);
 /* Fixed PL design: prohibit rmmod even when no fd is open. This also prevents
  * a failed reset during teardown from orphaning a live DMA allocation.
  * Runtime DT removal/reconfiguration is unsupported; reboot to replace. */
 __module_get(THIS_MODULE);
 dev_info(g->dev, "GST2 VGA 640x480, coherent DMA %pad, polling, reboot-only unload\n",
          &g->frame_dma);
 return 0;
free_frame:
 dma_free_coherent(&pdev->dev, FRAME_BYTES, g->frame, g->frame_dma);
clock_off:
 clk_disable_unprepare(g->clk);
 return ret;
}
static int gesture_remove(struct platform_device *pdev)
{
 struct gesture_dev *g=platform_get_drvdata(pdev);
 misc_deregister(&g->misc);
 /* Module owner blocks unload while a descriptor is open; manual unbind disabled. */
 if (!quiesce(g)) {
  dma_free_coherent(&pdev->dev, FRAME_BYTES, g->frame, g->frame_dma);
  clk_disable_unprepare(g->clk);
 } else {
  dev_err(g->dev,"DMA cannot reset: retain DMA buffer and clock until board reset\n");
 }
 return 0;
}
static const struct of_device_id gesture_of[]={{.compatible="linqiao,gesture-vga-1.0"},{}};
MODULE_DEVICE_TABLE(of, gesture_of);
static struct platform_driver gesture_driver={
 .probe=gesture_probe,.remove=gesture_remove,
 .driver={.name="gesture-vga",.of_match_table=gesture_of,.suppress_bind_attrs=true},
};
module_platform_driver(gesture_driver);
MODULE_VERSION("1.1");
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("OV5640 full VGA snapshot with owned AXI DMA coherent buffer");
