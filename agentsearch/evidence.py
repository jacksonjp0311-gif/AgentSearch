"""Optional content-addressed evidence receipts for local files."""
import hashlib
import os
from pathlib import Path
from .file_identity import identity
from .config import is_reparse


def receipt(path, max_bytes=8_388_608):
    target = Path(path)
    if type(max_bytes) is not int or max_bytes < 1:
        raise ValueError('max_bytes must be a positive integer')
    if is_reparse(target):
        raise ValueError('symlink evidence is unsupported')
    before = target.stat()
    if not target.is_file() or before.st_size > max_bytes:
        raise ValueError('evidence must be a regular file within the size limit')
    digest = hashlib.sha256()
    with target.open('rb') as handle:
        opened = os.fstat(handle.fileno())
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise RuntimeError('file replaced during open')
        total = 0
        while chunk := handle.read(min(65536, max_bytes - total + 1)):
            total += len(chunk)
            if total > max_bytes:
                raise ValueError('evidence grew beyond the size limit')
            digest.update(chunk)
        closed = os.fstat(handle.fileno())
    after = target.stat()
    if (is_reparse(target) or identity(before) != identity(after) or identity(closed) != identity(after)
            or any(getattr(opened, k) != getattr(closed, k) for k in ('st_size', 'st_mtime_ns', 'st_ctime_ns'))):
        raise RuntimeError('file changed during capture')
    return {'path': str(target.resolve()), 'sha256': digest.hexdigest(), 'bytes': after.st_size, 'algorithm': 'sha256'}


def verify_receipt(expected, max_bytes=8_388_608):
    if not isinstance(expected, dict) or not isinstance(expected.get('sha256'), str):
        return False
    try:
        actual = receipt(expected['path'], max_bytes=max_bytes)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError):
        return False
    return actual['sha256'] == expected['sha256'] and actual['bytes'] == expected.get('bytes')
