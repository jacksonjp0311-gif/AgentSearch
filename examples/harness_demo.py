"""Dispatch model-style tool calls without a model, API key, or network call."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path


# This permits `python examples/harness_demo.py` from a source checkout.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agentsearch import SearchConfig, SearchEngine  # noqa: E402
from agentsearch.adapter import AgentSearchAdapter  # noqa: E402
from build_demo import build_demo  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--show-tools", action="store_true", help="Also print the function tool schemas")
    args = parser.parse_args()
    root = build_demo()
    with tempfile.TemporaryDirectory(prefix="agentsearch-harness-demo-") as temporary:
        with SearchEngine(
            Path(temporary) / "index.sqlite3", SearchConfig(roots=(str(root),))
        ) as engine:
            print(json.dumps({"step": "index", "result": engine.index()}, ensure_ascii=False))
            adapter = AgentSearchAdapter(engine)
            if args.show_tools:
                print(json.dumps({"function_tools": adapter.function_tools()}, ensure_ascii=False))
            calls = [
                ("file_search", {"query": "calibratoin", "limit": 3}),
                ("content_search", {"pattern": "checkpoint_version", "limit": 3, "fresh": True}),
                ("read_file", {"path": str(root / "source" / "checkpoint.py"), "max_lines": 20}),
                ("index_status", {}),
            ]
            for name, arguments in calls:
                result = adapter.dispatch(name, arguments)
                print(json.dumps({"tool": name, "arguments": arguments, "result": result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
