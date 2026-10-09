"""Explicit filesystem scope and portable configuration for AgentSearch."""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import stat

DEFAULT_EXCLUDES = (".git", "node_modules", "__pycache__", ".venv", "venv", "target", "dist", "build")


def is_reparse(path: Path) -> bool:
    """Treat Windows junctions/reparse points and symbolic links as boundaries."""
    value = path.lstat()
    return stat.S_ISLNK(value.st_mode) or bool(getattr(value, "st_file_attributes", 0) & 0x400)


def expand_windows_alias(path: Path) -> Path:
    """Expand DOS short names without resolving links or junction targets."""
    if os.name != "nt":
        return path
    import ctypes
    from ctypes import wintypes
    function = ctypes.WinDLL("kernel32", use_last_error=True).GetLongPathNameW
    function.argtypes = (wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD)
    function.restype = wintypes.DWORD
    size = function(str(path), None, 0)
    if not size:
        raise ctypes.WinError(ctypes.get_last_error())
    buffer = ctypes.create_unicode_buffer(size)
    result = function(str(path), buffer, size)
    if not result or result >= size:
        raise OSError("Windows path changed while expanding its short name.")
    return Path(buffer.value)


@dataclass(frozen=True)
class SearchConfig:
    roots: tuple[str, ...]
    exclude_dirs: tuple[str, ...] = DEFAULT_EXCLUDES
    max_file_bytes: int = 2 * 1024 * 1024

    def __post_init__(self) -> None:
        if not isinstance(self.roots, (tuple, list)) or not self.roots:
            raise ValueError("At least one explicit root directory is required.")
        if type(self.max_file_bytes) is not int or not 1 <= self.max_file_bytes <= 128 * 1024 * 1024:
            raise ValueError("max_file_bytes must be an integer between 1 and 134217728.")
        normalized: list[str] = []
        for value in self.roots:
            if not isinstance(value, str) or not value.strip():
                raise ValueError("Each root must be a nonempty directory path.")
            path = Path(os.path.expandvars(value)).expanduser().absolute()
            if not path.is_dir() or is_reparse(path):
                raise ValueError(f"Root must be an existing directory, not a link or junction: {path}")
            path = path.resolve()
            if any(path.is_relative_to(Path(existing)) for existing in normalized):
                continue
            normalized = [existing for existing in normalized if not Path(existing).is_relative_to(path)]
            normalized.append(str(path))
        if not isinstance(self.exclude_dirs, (tuple, list)):
            raise ValueError("exclude_dirs must be a list of directory names.")
        excludes: list[str] = []
        for name in self.exclude_dirs:
            if not isinstance(name, str) or not name or name in (".", "..") or "/" in name or "\\" in name:
                raise ValueError("Exclusions must be single directory names, not paths.")
            if name not in excludes:
                excludes.append(name)
        object.__setattr__(self, "roots", tuple(sorted(normalized)))
        object.__setattr__(self, "exclude_dirs", tuple(excludes))

    def to_dict(self) -> dict:
        return {"roots": list(self.roots), "exclude_dirs": list(self.exclude_dirs), "max_file_bytes": self.max_file_bytes}

    @classmethod
    def from_file(cls, path: str | Path) -> "SearchConfig":
        with Path(path).open("r", encoding="utf-8-sig") as stream:
            data = json.load(stream)
        if not isinstance(data, dict):
            raise ValueError("Configuration must be a JSON object.")
        unknown = set(data) - {"roots", "exclude_dirs", "max_file_bytes"}
        if unknown:
            raise ValueError(f"Unknown configuration keys: {', '.join(sorted(unknown))}")
        if "roots" not in data:
            raise ValueError("Configuration requires roots.")
        return cls(**data)
