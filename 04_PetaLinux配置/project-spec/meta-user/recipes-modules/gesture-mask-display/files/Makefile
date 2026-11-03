ifneq ($(KERNELRELEASE),)
obj-m += gesture_mask_display.o
else
KERNEL_SRC ?= /lib/modules/$(shell uname -r)/build
KDIR ?= $(KERNEL_SRC)
MODULE_DIR := $(shell pwd)
.PHONY: all modules modules_install clean
all: modules
modules:
	$(MAKE) -C $(KDIR) M=$(MODULE_DIR) modules
modules_install:
	$(MAKE) -C $(KDIR) M=$(MODULE_DIR) modules_install
clean:
	$(MAKE) -C $(KDIR) M=$(MODULE_DIR) clean
endif
