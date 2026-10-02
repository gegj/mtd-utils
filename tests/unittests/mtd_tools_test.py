#!/usr/bin/env python3
"""Run real CLI code against a file-backed libmtd test double on Linux.

Run from a configured native build directory containing libmtd.a.
This models tool control flow, not kernel, ECC or physical NAND behavior.
"""
import os
from pathlib import Path
import subprocess
import tempfile


def main():
    root = Path(__file__).resolve().parents[2]
    build = Path.cwd()
    wraps = ["libmtd_open", "libmtd_close", "mtd_get_dev_info", "mtd_is_bad",
             "mtd_unlock", "mtd_unlock_multi", "mtd_erase", "mtd_erase_multi", "mtd_write"]
    with tempfile.TemporaryDirectory(prefix="mtd-tools-test-") as tmp:
        tmp = Path(tmp)
        for name, source in [("flash_erase", "misc-utils"), ("nandwrite", "nand-utils")]:
            subprocess.run(["gcc", "-D_GNU_SOURCE", "-std=gnu99",
                            "-I" + str(root / "include"), "-include", str(build / "include/config.h"),
                            str(root / source / (name + ".c")),
                            str(root / "tests/unittests/mtd_tools_mock.c"),
                            str(build / "libmtd.a"),
                            *["-Wl,--wrap=" + symbol for symbol in wraps],
                            "-o", str(tmp / name)], check=True)
        device = tmp / "device"
        image = tmp / "image"
        payload = bytes(range(256)) * 3
        image.write_bytes(payload)

        def run(name, args, success=True, **settings):
            device.write_bytes(bytes(16384))
            env = {key: value for key, value in os.environ.items() if not key.startswith("MOCK_")}
            env.update({"MOCK_" + key: str(value) for key, value in settings.items()})
            result = subprocess.run([str(tmp / name), *[str(arg) for arg in args]],
                                    env=env, capture_output=True, text=True)
            assert (result.returncode == 0) == success, (args, result.stdout, result.stderr)
            return device.read_bytes(), result

        for name in ("flash_erase", "nandwrite"):
            _, result = run(name, ["--help"])
            assert "Usage: " + name in result.stdout
            _, result = run(name, ["--version"])
            assert name + " (mtd-utils)" in result.stdout

        for flash_type in ("nor", "nand"):
            data, _ = run("flash_erase", [device, 0, 0], TYPE=flash_type)
            assert data == b"\xff" * 16384
        data, _ = run("flash_erase", [device, 0, 3], BAD=1)
        assert data[:4096] == b"\xff" * 4096 and data[4096:8192] == bytes(4096)
        assert data[8192:12288] == b"\xff" * 4096
        for setting in ("ERASE_FAIL", "UNLOCK_FAIL"):
            data, _ = run("flash_erase", ["-u", device, 0, 3], success=False, **{setting: 1})
            assert data[4096:8192] == bytes(4096)
            assert data[8192:12288] == b"\xff" * 4096
        run("flash_erase", ["-j", device, 0, 3], success=False, WRITE_FAIL=1)
        run("flash_erase", ["-j", device, 0, 0], success=False, WRITE_FAIL=1)
        data, _ = run("flash_erase", [device, 0, 0], BULK_FAIL=1)
        assert data == b"\xff" * 16384
        data, _ = run("nandwrite", ["-p", device, image])
        assert data[:768] == payload and data[768:1024] == b"\xff" * 256
        data, _ = run("nandwrite", ["-p", device, image], BAD=0)
        assert data[:4096] == bytes(4096) and data[4096:4864] == payload
        data, result = run("nandwrite", ["-p", device, image], success=False, TYPE="nor")
        assert "not a NAND device" in result.stderr and data == bytes(16384)
        run("nandwrite", ["-p", device, image], success=False, WRITE_FAIL=0)
        run("nandwrite", [device, image], success=False)
        image.write_bytes(bytes(16896))
        data, _ = run("nandwrite", [device, image], success=False)
        assert data == bytes(16384)
    print("MTD CLI file-model regression tests passed")


if __name__ == "__main__":
    main()
