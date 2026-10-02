#!/usr/bin/env python3
"""Non-erasing ADB smoke test for newly built tools on the NOR baseline.

Never invokes flash_erase with a device argument. nandwrite is invoked on
NOR only after confirming its rejection using the native regression tests.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import uuid


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--serial", required=True)
    parser.add_argument("--binaries", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    adb = ["adb", "-s", args.serial]
    report = {"serial": args.serial, "tests": [], "physical_flash_operations": "not tested"}

    def command(parts):
        return subprocess.run(adb + parts, capture_output=True, text=True, timeout=60)

    def shell(parts):
        return command(["shell", " ".join(shlex.quote(str(part)) for part in parts)])

    platform = command(["shell", "uname -a; cat /proc/cpuinfo; cat /proc/mtd; "
                        "ls -l /lib/ld-uClibc.so.0 /lib/libc.so.0"])
    if platform.returncode:
        raise RuntimeError(platform.stderr)
    report["platform"] = platform.stdout
    remote = "/tmp/mtd-utils-smoke-" + uuid.uuid4().hex
    created = shell(["mkdir", remote])
    if created.returncode:
        raise RuntimeError(created.stderr)
    try:
        for name in ("flash_erase", "nandwrite"):
            path = args.binaries / name
            report[name + "_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            result = command(["push", str(path), remote + "/" + name])
            if result.returncode:
                raise RuntimeError(result.stderr)
            if shell(["chmod", "700", remote + "/" + name]).returncode:
                raise RuntimeError("chmod failed")
            for option, expected in [("--version", name + " (mtd-utils)"),
                                     ("--help", "Usage: " + name)]:
                result = shell([remote + "/" + name, option])
                passed = result.returncode == 0 and expected in result.stdout
                report["tests"].append({"tool": name, "option": option, "passed": passed,
                                        "stdout": result.stdout, "stderr": result.stderr})
                if not passed:
                    raise RuntimeError(name + " " + option + " did not produce expected output")
            result = shell([remote + "/" + name, remote + "/missing-device", "0", "1"]
                           if name == "flash_erase" else
                           [remote + "/" + name, remote + "/missing-device", "/dev/null"])
            passed = result.returncode != 0 and bool(result.stderr.strip())
            report["tests"].append({"tool": name, "case": "missing device", "passed": passed,
                                    "stdout": result.stdout, "stderr": result.stderr})
            if not passed:
                raise RuntimeError(name + " missing-device test failed")
        # This baseline has NOR only. Never select NAND for this smoke test.
        kind = shell(["cat", "/sys/class/mtd/mtd0/type"])
        if kind.returncode or kind.stdout.strip() != "nor":
            raise RuntimeError("mtd0 is not confirmed NOR; rejection test skipped")
        result = shell([remote + "/nandwrite", "/dev/mtd0", "/dev/null"])
        passed = result.returncode != 0 and "not a NAND device" in result.stderr
        report["tests"].append({"tool": "nandwrite", "case": "NOR rejection", "passed": passed,
                                "stdout": result.stdout, "stderr": result.stderr})
        if not passed:
            raise RuntimeError("NOR rejection failed")
    finally:
        # Remove only the two uploaded binaries and their unique test directory.
        shell(["rm", "-f", remote + "/flash_erase", remote + "/nandwrite"])
        shell(["rmdir", remote])
        args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print("ADB non-erasing smoke tests passed; physical flash operations remain untested")


if __name__ == "__main__":
    main()
