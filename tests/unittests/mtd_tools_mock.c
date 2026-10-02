/* File-backed MTD test double. Only linked into regression executables. */
#include <errno.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <libmtd.h>
#include <mtd/mtd-user.h>

static int selected(const char *name, int eb)
{
	const char *value = getenv(name);
	return value && atoi(value) == eb;
}

libmtd_t __wrap_libmtd_open(void)
{
	return (void *)1;
}

void __wrap_libmtd_close(libmtd_t desc)
{
	(void)desc;
}

int __wrap_mtd_get_dev_info(libmtd_t desc, const char *node,
			   struct mtd_dev_info *mtd)
{
	const char *type = getenv("MOCK_TYPE");
	(void)desc;
	(void)node;
	memset(mtd, 0, sizeof(*mtd));
	mtd->type = type && !strcmp(type, "nor") ? MTD_NORFLASH : MTD_NANDFLASH;
	mtd->size = 16384;
	mtd->eb_size = 4096;
	mtd->eb_cnt = 4;
	mtd->min_io_size = 512;
	mtd->oob_size = mtd->type == MTD_NORFLASH ? 0 : 16;
	mtd->oobavail = 8;
	mtd->bb_allowed = mtd->type != MTD_NORFLASH;
	mtd->writable = 1;
	return 0;
}

int __wrap_mtd_is_bad(const struct mtd_dev_info *mtd, int fd, int eb)
{
	(void)fd;
	if (mtd->type == MTD_NORFLASH) {
		errno = EOPNOTSUPP;
		return -1;
	}
	return selected("MOCK_BAD", eb);
}

int __wrap_mtd_unlock(const struct mtd_dev_info *mtd, int fd, int eb)
{
	(void)mtd;
	(void)fd;
	if (selected("MOCK_UNLOCK_FAIL", eb)) {
		errno = EIO;
		return -1;
	}
	return 0;
}

int __wrap_mtd_unlock_multi(const struct mtd_dev_info *mtd, int fd,
			   int eb, int blocks)
{
	int i;
	for (i = eb; i < eb + blocks; i++)
		if (__wrap_mtd_unlock(mtd, fd, i))
			return -1;
	return 0;
}

int __wrap_mtd_erase(libmtd_t desc, const struct mtd_dev_info *mtd,
		     int fd, int eb)
{
	unsigned char buf[4096];
	(void)desc;
	if (selected("MOCK_ERASE_FAIL", eb)) {
		errno = EIO;
		return -1;
	}
	memset(buf, 0xff, sizeof(buf));
	return pwrite(fd, buf, sizeof(buf), (off_t)eb * mtd->eb_size) == sizeof(buf) ? 0 : -1;
}

int __wrap_mtd_erase_multi(libmtd_t desc, const struct mtd_dev_info *mtd,
			   int fd, int eb, int blocks)
{
	int i;
	if (getenv("MOCK_BULK_FAIL")) {
		errno = EOPNOTSUPP;
		return -1;
	}
	for (i = eb; i < eb + blocks; i++)
		if (__wrap_mtd_erase(desc, mtd, fd, i))
			return -1;
	return 0;
}

int __wrap_mtd_write(libmtd_t desc, const struct mtd_dev_info *mtd,
		     int fd, int eb, int offs, void *data, int len,
		     void *oob, int ooblen, uint8_t mode)
{
	(void)desc;
	(void)oob;
	(void)ooblen;
	(void)mode;
	if (selected("MOCK_WRITE_FAIL", eb)) {
		errno = EINVAL;
		return -1;
	}
	if (!len)
		return 0;
	return pwrite(fd, data, len, (off_t)eb * mtd->eb_size + offs) == len ? 0 : -1;
}
