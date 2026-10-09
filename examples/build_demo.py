"""Create deterministic sample files only under this example's demo folder."""

from __future__ import annotations

import json
from pathlib import Path


DEMO_ROOT = Path(__file__).resolve().parent / "demo"

DEMO_FILES = {
    "README.md": (
        "# AgentSearch demonstration corpus\n\n"
        "These files are synthetic examples, not real training or execution receipts.\n"
        "Try filename search for calibratoin, content search for checkpoint_version,\n"
        "and a bounded read of source/checkpoint.py.\n"
    ),
    "source/checkpoint.py": (
        '"""Small, deliberately non-executable checkpoint example."""\n\n'
        "checkpoint_version = 3\n"
        "receipt_policy = 'verify before promotion'\n\n"
        "def describe_checkpoint():\n"
        "    return {'version': checkpoint_version, 'policy': receipt_policy}\n"
    ),
    "source/calibration.py": (
        '"""Filename typo demonstration: calibratoin should find calibration."""\n\n'
        "calibration_label = 'synthetic demonstration only'\n"
    ),
    "docs/continuity notes.md": (
        "# Continuity notes\n\n"
        "A search result supplies evidence for the next reasoning step.\n"
        "Use a fresh content search after changes when you need the index reconciled.\n"
        "Use a bounded read to inspect the exact file before changing it.\n"
    ),
    "docs/café_雪.txt": "Unicode paths and content: café, naïve, 雪.\n",
    "receipts/receipt_0001.json": json.dumps(
        {
            "kind": "synthetic_example",
            "checkpoint_version": 3,
            "decision": "review_required",
            "evidence": "This record demonstrates search; it proves no learning claim.",
        },
        ensure_ascii=False,
        indent=2,
    ) + "\n",
}


def build_demo() -> Path:
    """Write the known demo files without touching any external project."""
    if DEMO_ROOT.is_symlink():
        raise ValueError(f"Refusing a symlinked demonstration directory: {DEMO_ROOT}")
    DEMO_ROOT.mkdir(parents=True, exist_ok=True)
    for relative, content in DEMO_FILES.items():
        destination = DEMO_ROOT / relative
        for component in (destination, *destination.parents):
            if component == DEMO_ROOT.parent:
                break
            if component.is_symlink():
                raise ValueError(f"Refusing a symlinked demonstration path: {component}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
    return DEMO_ROOT


if __name__ == "__main__":
    print(build_demo())
