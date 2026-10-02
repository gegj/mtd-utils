# 交叉编译兼容层（.github/compat）

这套东西只为一件事：**用现代的 Bootlin uClibc-ng 工具链，编出能在"经典 uClibc 0.9.33.x"
设备上直接跑的 nandwrite / flash_erase**，而且必须是动态链接（不能静态：部分设备 `/tmp` 极小，
静态要 ~1MB，动态只要 35~45KB）。

## 当年踩的坑（三条，缺一条就"装得上、跑不起来"）

| 现象 | 原因 | 处理 |
|---|---|---|
| `can't load library 'ld-uClibc.so.1'` | uClibc-ng 的 `libc.so` 链接脚本里有 `AS_NEEDED(ld-uClibc.so.1)`，产物的 `DT_NEEDED` 因此多出这条；设备上只有 `ld-uClibc.so.0` | 构建时自建 `libc.so`（`INPUT ( <sysroot>/lib/libc.so.0 )`）并加到 `-L` 最前面，让 `-lc` 只链共享 libc，`NEEDED` 只剩 `libc.so.0` |
| `symbol 'gnu_dev_major': can't resolve symbol` | uClibc-ng 的 `<sys/sysmacros.h>` 把 `major()/minor()` 映射到 `gnu_dev_major()/gnu_dev_minor()` 这两个函数，而经典 uClibc 0.9.33.2 的 `libc.so.0` 不导出它们 | `compat/sys/sysmacros.h` 用纯位运算重定义 `major()/minor()/makedev()`，用 `-I .github/compat` 优先命中（**不能用 `-include`**：源码 `common.h` 之后还会 include 系统头，会把宏改回去） |
| `__stack_chk_guard` 找不到 | 工具链默认开了栈保护（Buildroot 常用 `-fstack-protector-strong`），设备 libc 没有这个数据符号 | 编译加 `-fno-stack-protector`（`__stack_chk_fail` 设备是有的，只差 guard 变量） |

> 顺带说明：`__register_frame_info` / `__deregister_frame_info` / `_ITM_*` 这几个是 **weak** 未定义符号，
> uClibc 的 loader 容忍 weak（设备上能正常跑的厂商 `MTDWriter` 就带着 unresolved 的 weak 符号），
> 所以门禁脚本对 weak 放行，只卡"强未定义符号"。

## 门禁

`verify-arm-mtd-utils.py` 在每个变体编译完成后运行，检查：

1. ELF32 / ARM；
2. `PT_INTERP` 匹配目标设备 loader（uClibc 变体必须是 `/lib/ld-uClibc.so.0`）；
3. 每条 `DT_NEEDED` 都匹配期望的 libc（uClibc 变体绝不允许出现 `ld-uClibc.so.1`）；
4. 体积 < 200KB（一旦误编成静态会大一个数量级，立刻失败）；
5. uClibc 变体额外做**符号门禁**：所有强未定义符号都必须出现在
   `uclibc-0.9.33.2-dynsyms.txt`（从真机 `/lib/libuClibc-0.9.33.2.so` 导出的动态符号表）里，
   并禁止出现 `gnu_dev_major` / `gnu_dev_minor` / `__stack_chk_guard`。

`uclibc-0.9.33.2-dynsyms.txt` 是"目标设备到底能提供哪些符号"的白名单，来自一台真实设备
（ZTE/高通 MDM 随身 WiFi）。换了别的目标机型，把对应设备的 `libc.so.0` 拉下来重新生成这份清单即可：

```bash
adb pull /lib/libuClibc-0.9.33.2.so libc.so.0
readelf --dyn-syms -W libc.so.0 | awk '$7 != "UND" && $8 != "" { print $8 }' | sed 's/@.*//' | sort -u \
  > .github/compat/uclibc-0.9.33.2-dynsyms.txt
```

## 本地复现同一条构建命令

```bash
export CC=arm-buildroot-linux-uclibcgnueabi-gcc
export CFLAGS="-Os -marm -march=armv5te -mfloat-abi=soft -ffunction-sections -fdata-sections -fno-stack-protector"
export CPPFLAGS="-I$PWD/.github/compat"
mkdir -p .compat-lib && printf 'INPUT ( %s/lib/libc.so.0 )\n' "$($CC -print-sysroot)" > .compat-lib/libc.so
export LDFLAGS="-Wl,--gc-sections -Wl,--dynamic-linker=/lib/ld-uClibc.so.0 -L$PWD/.compat-lib"
./autogen.sh && ./configure --host=arm-buildroot-linux-uclibcgnueabi --without-jffs --without-ubifs \
  --without-zlib --without-xattr --without-lzo --without-zstd --without-selinux --without-crypto \
  --without-tests --without-lsmtd --disable-ubihealthd
make -j"$(nproc)" flash_erase nandwrite
python3 .github/compat/verify-arm-mtd-utils.py \
  --binaries flash_erase nandwrite \
  --interp-re '^/lib/ld-uClibc\.so\.0$' --needed-re '^libc\.so\.0$' \
  --symbol-gate .github/compat/uclibc-0.9.33.2-dynsyms.txt \
  --forbid-symbols gnu_dev_major gnu_dev_minor __stack_chk_guard
```
