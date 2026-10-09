"""Comparable path/descriptor metadata across supported Python/OS versions."""
import os


def identity(info):
    # On Windows, stat can report creation time as ctime while
    # fstat reports change time. Birth time is comparable across both APIs.
    # Keep fstat-before/after ctime checks separately to detect in-read changes.
    stamp = getattr(info, 'st_birthtime_ns', info.st_ctime_ns) if os.name == 'nt' else info.st_ctime_ns
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, stamp
