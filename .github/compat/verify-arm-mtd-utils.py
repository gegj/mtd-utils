#!/usr/bin/env python3
"""验证交叉编译出来的 nandwrite / flash_erase 能不能在目标设备上加载运行。

背景：这类设备（ZTE/高通 MDM 随身 WiFi 等）的 /tmp 很小，不能静态链接（静态要 ~1MB，
动态只要 35~45KB），所以产物必须"动态 + 只依赖设备上真实存在的 libc"。历史上踩过的坑：

  1. uClibc 变体：NEEDED 里带了 uClibc-ng 的 loader `ld-uClibc.so.1`，而设备只有
     `ld-uClibc.so.0` -> loader 报 `can't load library 'ld-uClibc.so.1'`（退出码仍是 0！）；
  2. 引用了 `gnu_dev_major` / `gnu_dev_minor`（经典 uClibc 0.9.33.2 的 libc 没这两个符号）
     -> `symbol 'gnu_dev_major': can't resolve symbol`；
  3. 开了栈保护 -> 引用 `__stack_chk_guard`，经典 uClibc 上同样不存在。

本脚本把这些检查固化成 CI 门禁，不通过就让构建失败，避免再发布"装得上跑不起来"的二进制。

检查项：
  - ELF32 / ARM；
  - PT_INTERP 匹配目标设备的 loader 路径（正则，由 workflow 的 matrix 给出）；
  - 每条 DT_NEEDED 都匹配期望的 libc（正则，由 matrix 给出）；
    注意：glibc 与 musl 的产物本来就会带各自的 loader，这是正常的；
    只有 uClibc 变体要求"NEEDED 里绝不能出现 ld-uClibc.so.1"（设备上根本没有这个 soname）；
  - 体积上限（误编成静态会大一个数量级）；
  - 可选符号门禁：强未定义符号必须全部存在于目标设备 libc 的导出符号表里（weak 忽略，
    因为 uClibc 的 loader 容忍 weak 未解析），并禁止出现指定的黑名单符号；
  - 附带信息：产物依赖的最低 glibc 符号版本（glibc 变体用，判断设备 glibc 是否够新）。
"""

import argparse
import re
import subprocess
import sys

INTERP_PATTERN = re.compile(r"Requesting program interpreter:\s*(\S+?)\]?\s*$")
NEEDED_PATTERN = re.compile(r"\(NEEDED\)\s+Shared library: \[([^\]]+)\]")
GLIBC_VERSION_PATTERN = re.compile(r"@GLIBC_([0-9]+(?:\.[0-9]+)*)")


# ---------------------------------------------------------------- readelf 输出解析（纯函数，便于自测）

def parse_interp(readelf_program_headers):
    for line in readelf_program_headers.splitlines():
        match = INTERP_PATTERN.search(line)
        if match:
            return match.group(1)
    return None


def parse_needed(readelf_dynamic):
    return NEEDED_PATTERN.findall(readelf_dynamic)


def parse_undefined_symbols(readelf_dyn_syms):
    """返回 {符号名: 绑定属性}，只含 Ndx == UND 的动态符号。

    典型行（readelf --dyn-syms -W）：
        3: 00000000     0 FUNC    GLOBAL DEFAULT  UND ioctl
        4: 00000000     0 NOTYPE  WEAK   DEFAULT  UND _ITM_registerTMCloneTable
        5: 00000000     0 FUNC    GLOBAL DEFAULT  UND __cxa_finalize@GLIBC_2.1.3 (2)
    """
    result = {}
    for line in readelf_dyn_syms.splitlines():
        parts = line.split()
        if "UND" not in parts:
            continue
        index = parts.index("UND")
        if index + 1 >= len(parts) or len(parts) < 5:
            continue
        name = parts[index + 1].split("@")[0]
        if name:
            result[name] = parts[4]
    return result


def parse_glibc_versions(readelf_dyn_syms):
    """返回产物引用到的 glibc 符号版本集合，例如 {(2, 34), (2, 4)}。"""
    return {
        tuple(int(part) for part in match.group(1).split("."))
        for match in GLIBC_VERSION_PATTERN.finditer(readelf_dyn_syms)
    }


# ---------------------------------------------------------------- 实际读取

def run_readelf(args, path):
    completed = subprocess.run(["readelf"] + args + [path], capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError("readelf %s %s 失败：%s" % (" ".join(args), path, completed.stderr.strip()))
    return completed.stdout


def check_elf_header(path, problems):
    header = run_readelf(["-h"], path)
    if not re.search(r"Class:\s+ELF32", header):
        problems.append("不是 ELF32（可能编成了别的架构）")
    if not re.search(r"Machine:\s+ARM", header):
        problems.append("Machine 不是 ARM")


def load_allowed_symbols(path):
    with open(path, "r", encoding="utf-8") as handle:
        return {line.strip() for line in handle if line.strip() and not line.startswith("#")}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binaries", nargs="+", required=True)
    parser.add_argument("--interp-re", required=True, help="期望的 PT_INTERP 正则")
    parser.add_argument("--needed-re", required=True, help="每条 DT_NEEDED 都必须匹配的正则")
    parser.add_argument("--max-size", type=int, default=204800, help="体积上限（字节），防止误编成静态")
    parser.add_argument("--symbol-gate", help="目标设备 libc 的导出符号清单文件（每行一个）")
    parser.add_argument("--forbid-symbols", nargs="*", default=[], help="禁止出现的未定义符号")
    parser.add_argument("--self-test", action="store_true", help="只跑解析函数的自测，不读 ELF")
    args = parser.parse_args()

    if args.self_test:
        return self_test()

    allowed = None
    if args.symbol_gate:
        allowed = load_allowed_symbols(args.symbol_gate)
        print("符号清单：%s（%d 个符号）" % (args.symbol_gate, len(allowed)))

    failed = False
    for path in args.binaries:
        problems = []
        with open(path, "rb") as handle:
            size = len(handle.read())
        check_elf_header(path, problems)

        interp = parse_interp(run_readelf(["-l"], path))
        if not interp:
            problems.append("没有 PT_INTERP：说明编成了静态链接（本项目的设备空间不允许）")
        elif not re.match(args.interp_re, interp):
            problems.append("PT_INTERP = %s，不匹配 %s" % (interp, args.interp_re))

        needed = parse_needed(run_readelf(["-d"], path))
        if not needed:
            problems.append("没有 DT_NEEDED：说明编成了静态链接")
        for library in needed:
            if not re.match(args.needed_re, library):
                problems.append("DT_NEEDED 含不该依赖的库：%s（期望匹配 %s）" % (library, args.needed_re))

        if size > args.max_size:
            problems.append("体积 %d 字节 > 上限 %d：很可能被编成静态" % (size, args.max_size))

        dyn_syms = run_readelf(["--dyn-syms", "-W"], path)
        undefined = parse_undefined_symbols(dyn_syms)
        for name in args.forbid_symbols:
            if name in undefined:
                problems.append("引用了禁止的符号：%s（目标设备 libc 没有它）" % name)

        if allowed is not None:
            missing = sorted(
                name for name, binding in undefined.items()
                if binding != "WEAK" and name not in allowed
            )
            if missing:
                problems.append(
                    "强未定义符号不在目标设备 libc 导出表里：%s（若确认设备 libc 有，请加入符号清单）"
                    % ", ".join(missing)
                )

        glibc_versions = parse_glibc_versions(dyn_syms)

        print("=" * 72)
        print("%s: %d 字节" % (path, size))
        print("  PT_INTERP  : %s" % (interp or "(无)"))
        print("  DT_NEEDED  : %s" % (", ".join(needed) or "(无)"))
        print("  未定义符号 : %d 个（强 %d / weak %d）" % (
            len(undefined),
            sum(1 for binding in undefined.values() if binding != "WEAK"),
            sum(1 for binding in undefined.values() if binding == "WEAK"),
        ))
        if glibc_versions:
            newest = max(glibc_versions)
            print("  glibc 要求 : >= %s（设备 glibc 低于它会报 version not found）"
                  % ".".join(str(part) for part in newest))
        if problems:
            failed = True
            for problem in problems:
                print("  [失败] %s" % problem)
        else:
            print("  [通过] 可以在目标设备上加载运行")

    if failed:
        print("\n兼容性门禁未通过，按上面的 [失败] 项逐条处理：")
        print("  - DT_NEEDED / PT_INTERP 不符：多半是 workflow 里该变体的 needed_re / interp_re")
        print("    与实际 loader 名不一致（glibc、musl 的产物本来就会带各自的 loader，属正常）")
        print("  - 体积超限：被编成了静态")
        print("  - uClibc 变体的符号问题：检查 -fno-stack-protector / sysmacros shim / 自建 libc.so 链接脚本")
        return 1
    print("\n全部检查通过。")
    return 0


# ---------------------------------------------------------------- 自测

SAMPLE_HEADER = """ELF Header:
  Magic:   7f 45 4c 46 01 01 01 00 00 00 00 00 00 00 00 00
  Class:                             ELF32
  Data:                              2's complement, little endian
  Type:                              DYN (Position-Independent Executable file)
  Machine:                           ARM
"""

SAMPLE_PROGRAM_HEADERS = """Elf file type is DYN (Position-Independent Executable file)
Entry point 0x5c0
There are 9 program headers, starting at offset 52

Program Headers:
  Type           Offset   VirtAddr   PhysAddr   FileSiz MemSiz  Flg Align
  PHDR           0x000034 0x00000034 0x00000034 0x00120 0x00120 R   0x4
  INTERP         0x000154 0x00000154 0x00000154 0x00014 0x00014 R   0x1
      [Requesting program interpreter: /lib/ld-uClibc.so.0]
"""

SAMPLE_DYNAMIC = """Dynamic section at offset 0x2f00 contains 24 entries:
  Tag        Type                         Name/Value
 0x00000001 (NEEDED)                     Shared library: [libc.so.0]
 0x00000001 (NEEDED)                     Shared library: [ld-uClibc.so.1]
 0x0000000c (INIT)                       0x3b8
"""

SAMPLE_DYN_SYMS = """Symbol table '.dynsym' contains 60 entries:
   Num:    Value  Size Type    Bind   Vis      Ndx Name
     0: 00000000     0 NOTYPE  LOCAL  DEFAULT  UND 
     1: 00000000     0 FUNC    GLOBAL DEFAULT  UND __cxa_finalize@GLIBC_2.1.3 (2)
     2: 00000000     0 NOTYPE  WEAK   DEFAULT  UND _ITM_registerTMCloneTable
     3: 00000000     0 FUNC    GLOBAL DEFAULT  UND gnu_dev_major
     4: 00000000     0 FUNC    WEAK   DEFAULT  UND __register_frame_info
     5: 00000000     4 OBJECT  GLOBAL DEFAULT   25 stdout
     6: 00000000     0 FUNC    GLOBAL DEFAULT  UND __stack_chk_guard
     7: 00000000     0 FUNC    GLOBAL DEFAULT  UND __libc_start_main@GLIBC_2.34 (3)
"""


def self_test():
    failures = []

    def expect(label, actual, wanted):
        if actual != wanted:
            failures.append("%s: 期望 %r，实际 %r" % (label, wanted, actual))

    expect("parse_interp", parse_interp(SAMPLE_PROGRAM_HEADERS), "/lib/ld-uClibc.so.0")
    expect("parse_interp(静态)", parse_interp("  INTERP 0x0 0x0 0x0 0x0 0x0 R 0x1"), None)
    expect("parse_needed", parse_needed(SAMPLE_DYNAMIC), ["libc.so.0", "ld-uClibc.so.1"])

    undefined = parse_undefined_symbols(SAMPLE_DYN_SYMS)
    expect("未定义符号集合", sorted(undefined), sorted([
        "__cxa_finalize", "_ITM_registerTMCloneTable", "gnu_dev_major",
        "__register_frame_info", "__stack_chk_guard", "__libc_start_main",
    ]))
    expect("gnu_dev_major 绑定", undefined.get("gnu_dev_major"), "GLOBAL")
    expect("__register_frame_info 绑定", undefined.get("__register_frame_info"), "WEAK")
    expect("已定义符号不进集合", "stdout" in undefined, False)
    expect("glibc 版本解析", parse_glibc_versions(SAMPLE_DYN_SYMS), {(2, 1, 3), (2, 34)})

    if failures:
        for failure in failures:
            print("[自测失败] " + failure)
        return 1
    print("自测通过：readelf 输出解析符合预期。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
