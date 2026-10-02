/*
 * 兼容层：<sys/sysmacros.h>
 *
 * 为什么要它：
 *   用 uClibc-ng（例如 Bootlin 的 armv5-eabi--uclibc 工具链）编译时，它的
 *   <sys/sysmacros.h> 会把 major()/minor() 定义成 gnu_dev_major()/gnu_dev_minor()
 *   这两个"函数"，于是二进制里会出现对这两个符号的强引用。
 *   而设备上常见的经典 uClibc 0.9.33.2 的 libc.so.0 并不导出这两个符号
 *   （实测：`/lib/libuClibc-0.9.33.2.so` 的 .dynsym 里没有 gnu_dev_*），
 *   结果是 uClibc 的 loader 直接报 `symbol 'gnu_dev_major': can't resolve symbol` 并退出。
 *
 *   把 major()/minor()/makedev() 换回纯位运算，二进制里就不再有这两个符号引用，
 *   同一份产物既能跑在 uClibc-ng 设备，也能跑在经典 uClibc 0.9.33.x 设备上。
 *
 * 用法（必须用 -I 让本目录排在 sysroot 之前，不能用 -include）：
 *   CPPFLAGS="-I<repo>/.github/compat"
 *   因为源码 common.h 里随后还会 #include <sys/sysmacros.h>，
 *   只要本 shim 在 include 搜索路径里优先命中，就不会再被系统头覆盖。
 *
 * 位运算编码与 glibc 的 __gnu_dev_major/__gnu_dev_minor 一致（值不变，只是不走外部符号）。
 */
#ifndef WIFITOOL_COMPAT_SYS_SYSMACROS_H
#define WIFITOOL_COMPAT_SYS_SYSMACROS_H

#include <sys/types.h>

#define major(dev) ((unsigned int)(((dev) >> 8) & 0xfff))
#define minor(dev) ((unsigned int)(((dev) & 0xff) | (((dev) >> 12) & 0xfff00)))
#define makedev(ma, mi) \
    ((dev_t)((((dev_t)(ma) & 0xfff) << 8) | ((dev_t)(mi) & 0xff) | (((dev_t)(mi) & ~(dev_t)0xff) << 12)))

#endif /* WIFITOOL_COMPAT_SYS_SYSMACROS_H */
