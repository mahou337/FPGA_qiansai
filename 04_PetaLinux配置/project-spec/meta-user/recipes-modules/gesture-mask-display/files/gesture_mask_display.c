// SPDX-License-Identifier: GPL-2.0
// Linux 4.19, ARMv7. Kernel owns MMIO; no mmap or guessed DDR allocation.
#include <linux/module.h>
#include <linux/platform_device.h>
#include <linux/miscdevice.h>
#include <linux/fs.h>
#include <linux/io.h>
#include <linux/uaccess.h>
#include <linux/mutex.h>
#include <linux/kref.h>
#include <linux/vmalloc.h>
#include <linux/slab.h>
#include <linux/clk.h>
#include <linux/sched.h>
#include <linux/of.h>
#include "gesture_mask_display.h"
#define ID 0x4d534b31
#define BYTES 76800
#define BUSY (BIT(1)|BIT(6))
struct mask_dev {
 struct miscdevice misc;
 void __iomem *io;
 struct clk *clk;
 struct mutex lock;
 struct kref ref;
 bool opened, gone;
 u8 *staging;
};
static void dispose(struct kref *ref)
{
 struct mask_dev *m=container_of(ref,struct mask_dev,ref);
 vfree(m->staging); kfree(m);
}
static int mask_open(struct inode *inode,struct file *file)
{
 struct mask_dev *m=container_of(file->private_data,struct mask_dev,misc);
 int ret=0;
 mutex_lock(&m->lock);
 if(m->gone) ret=-ENODEV;
 else if(m->opened) ret=-EBUSY;
 else {
  kref_get(&m->ref); m->opened=true; file->private_data=m;
  writel(1,m->io+0x20); readl(m->io+8); // queued blank, never wait for vsync
 }
 mutex_unlock(&m->lock);
 return ret;
}
static int mask_release(struct inode *inode,struct file *file)
{
 struct mask_dev *m=file->private_data;
 mutex_lock(&m->lock);
 if(!m->gone) { writel(1,m->io+0x20); readl(m->io+8); }
 m->opened=false;
 mutex_unlock(&m->lock); kref_put(&m->ref,dispose); return 0;
}
// ARMv7 memcpy_toio() in 4.19 uses byte stores with per-byte barriers.
// Upload four pixels per ordered 32-bit Device-memory transaction instead.
// No Python loop or syscall per pixel; one frame write(), one final barrier.
static void upload_frame(void __iomem *dst,const u8 *src)
{
 const __le32 *words=(const __le32 *)src; // vzalloc is word aligned
 unsigned int i;
 for(i=0;i<BYTES/4;i++) {
  writel_relaxed(le32_to_cpu(words[i]),dst+i*4);
  if((i&255)==255) cond_resched(); // allow higher-priority control work to run
 }
}
static ssize_t mask_write(struct file *file,const char __user *buf,size_t count,loff_t *pos)
{
 struct mask_dev *m=file->private_data;
 u32 status,offset,errors;
 ssize_t ret;
 if(count!=BYTES) return -EMSGSIZE;
 if(!mutex_trylock(&m->lock)) return -EAGAIN;
 if(m->gone) { ret=-ENODEV; goto out; }
 status=readl(m->io+8);
 if(!(status&1) || (status&BUSY)) { ret=-EAGAIN; goto out; }
 if(copy_from_user(m->staging,buf,BYTES)) { ret=-EFAULT; goto out; }
 offset=(status&BIT(2)) ? 0x20000:0x40000; // opposite of front bank
 errors=readl(m->io+0x18);
 writel(1,m->io+0x10); // BEGIN, reset byte-coverage tracker
 upload_frame(m->io+offset,m->staging);
 wmb(); // publish all bytes before commit; readback drains posted transactions
 if(readl(m->io+0x10)!=19200 || readl(m->io+0x18)!=errors) { ret=-EIO; goto out; }
 writel(1,m->io+4); readl(m->io+8);
 ret=BYTES; // uploaded/queued, NOT a promise of completed scanout
out:
 mutex_unlock(&m->lock); return ret;
}
static long mask_ioctl(struct file *file,unsigned int cmd,unsigned long arg)
{
 struct mask_dev *m=file->private_data;
 struct gesture_mask_status st={0};
 u32 mode;
 long ret=0;
 if(!mutex_trylock(&m->lock)) return -EAGAIN;
 if(m->gone) { ret=-ENODEV; goto out; }
 switch(cmd) {
 case GESTURE_MASK_STATUS:
  st.identity=readl(m->io); st.status=readl(m->io+8);
  st.dimensions=readl(m->io+0xc); st.bytes=readl(m->io+0x1c);
  st.swaps=readl(m->io+0x14); st.errors=readl(m->io+0x18);
  if(copy_to_user((void __user *)arg,&st,sizeof(st))) ret=-EFAULT;
  break;
 case GESTURE_MASK_MODE:
  if(copy_from_user(&mode,(void __user *)arg,sizeof(mode))) { ret=-EFAULT; break; }
  if(mode==0) { writel(1,m->io+0x20); readl(m->io+8); }
  else if(mode!=2) ret=-EINVAL; // mode1 only via a complete write()
  else if((readl(m->io+8)&(BUSY|1))!=1) ret=-EAGAIN;
  else { writel(2,m->io+4); readl(m->io+8); }
  break;
 default:ret=-ENOTTY;
 }
out:
 mutex_unlock(&m->lock); return ret;
}
static const struct file_operations mask_fops={
 .owner=THIS_MODULE,.open=mask_open,.release=mask_release,.write=mask_write,
 .unlocked_ioctl=mask_ioctl,.llseek=no_llseek,
};
static int mask_probe(struct platform_device *pdev)
{
 struct mask_dev *m;
 struct resource *r;
 int ret;
 m=kzalloc(sizeof(*m),GFP_KERNEL);
 if(!m) return -ENOMEM;
 mutex_init(&m->lock); kref_init(&m->ref);
 m->staging=vzalloc(BYTES);
 if(!m->staging) { ret=-ENOMEM; goto fail; }
 r=platform_get_resource(pdev,IORESOURCE_MEM,0);
 if(!r || resource_size(r)!=0x80000) { ret=-EINVAL; goto fail; }
 m->io=devm_ioremap_resource(&pdev->dev,r);
 if(IS_ERR(m->io)) { ret=PTR_ERR(m->io); goto fail; }
 m->clk=devm_clk_get(&pdev->dev,"s_axi_aclk");
 if(IS_ERR(m->clk)) { ret=PTR_ERR(m->clk); goto fail; }
 ret=clk_prepare_enable(m->clk); if(ret) goto fail;
 if(readl(m->io)!=ID || readl(m->io+0xc)!=0x00f00140 || readl(m->io+0x1c)!=BYTES) {
  ret=-ENODEV; goto clock_fail;
 }
 m->misc.minor=MISC_DYNAMIC_MINOR; m->misc.name="gesture-mask-display";
 m->misc.fops=&mask_fops; m->misc.parent=&pdev->dev; m->misc.mode=0600;
 writel(1,m->io+0x20); readl(m->io+8);
 ret=misc_register(&m->misc); if(ret) goto clock_fail;
 platform_set_drvdata(pdev,m);
 dev_info(&pdev->dev,"MSK1 320x240 uint8 double BRAM, no IRQ, no DDR DMA\n");
 return 0;
clock_fail:clk_disable_unprepare(m->clk);
fail:kref_put(&m->ref,dispose);return ret;
}
static int mask_remove(struct platform_device *pdev)
{
 struct mask_dev *m=platform_get_drvdata(pdev);
 misc_deregister(&m->misc);
 mutex_lock(&m->lock);
 writel(1,m->io+0x20); readl(m->io+8); m->gone=true;
 mutex_unlock(&m->lock);
 clk_disable_unprepare(m->clk); kref_put(&m->ref,dispose); return 0;
}
static const struct of_device_id mask_of_match[]={
 {.compatible="hellofpga,mask-display-1.0"},{},
};
MODULE_DEVICE_TABLE(of,mask_of_match);
static struct platform_driver mask_driver={
 .probe=mask_probe,.remove=mask_remove,
 .driver={.name="gesture-mask-display",.of_match_table=mask_of_match},
};
module_platform_driver(mask_driver);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Smart ZYNQ isolated BRAM mask display, MSK1 ABI");
