# ARM MTD compatibility report

## Status (2026-10-02)

Source changes and regression tests are implemented. ELF parser/ABI
self-tests and whitespace validation passed on Windows. Native C tests,
cross-compilation and new-binary ADB smoke tests have NOT run: this host
has no usable WSL distribution, Linux container runtime or native Linux
compiler. No new binaries or their SHA256 sums have been delivered.
The GitHub Actions workflow contains the native and cross-build steps;
no remote run was dispatched and no changes were published.

## Reference files

Both desktop files are ELF32 little-endian ARM EABI5 with soft-float flags,
PT_INTERP `/lib/ld-uClibc.so.0` and DT_NEEDED `libc.so.0`. Embedded strings
identify version 1.5.2 and Chinese messages. Their apparent roles differ
from their filenames:

| Desktop filename | Evidence | Apparent role | SHA256 |
| --- | --- | --- | --- |
| flash_erase | NAND image/page/OOB messages; Thomas Gleixner copyright | nandwrite | C3363208E0FBD7BE44F62453666D9F443F305DE34F12511F9AE96FA97DEA2C78 |
| nandwrite | JFFS2 cleanmarker messages; Arcom copyright | flash_erase | 2315CEA4F93063B4A8D26893EEC8F9BFD5C9829E0EF77DA191CE914F2D7072C4 |

This is string/header evidence, not full behavioral equivalence testing.
Old files were not executed. New tools use standard upstream names and
English interfaces. Existing upstream options and NAND write mechanisms
are retained; no claim of byte-for-byte legacy output compatibility is made.

## Connected device: read-only observations

ADB serial `1234567890ABCDEF`, hardware `TSP ZX297520V3`, ARMv7,
Linux `3.4.110-rt140`, root shell. Loader and libc symlinks resolve to
uClibc 0.9.33.2. Sysfs reports NOR for all six partitions, erasesize 32768,
writesize 256 and oobsize 0.

| Partition | Name | Size (bytes) |
| --- | --- | --- |
| mtd0 | zloader | 32768 |
| mtd1 | nvrofs | 229376 |
| mtd2 | uboot | 163840 |
| mtd3 | imagefs | 4390912 |
| mtd4 | rootfs | 3178496 |
| mtd5 | userdata | 393216 |

imagefs and nvrofs are mounted read-only; userdata is mounted read-write.
No device partition was erased or written. This machine cannot establish
NAND write compatibility. The checked-in libc symbol list is an existing
baseline and has not been independently regenerated from this device.

## Acceptance still required

- Run native file-model and libmtd ioctl tests on Linux.
- Build and strip both ARM tools; pass ELF/symbol gates; retain hashes and logs.
- Run the provided non-erasing ADB smoke script on those exact artifacts.
- Physical NOR erase, NAND writing, ECC and raw/OOB remain explicitly untested.

Matching ABI or loader name alone does not guarantee compatibility with
every device. ARMv5TE is the build instruction-set target, not an assertion
that all ARMv6/ARMv7 firmware supplies the same libc/kernel interfaces.
