"""Protocol boundaries: rejection, lifecycle, framing, and tool-error visibility."""

from __future__ import annotations

import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from agentsearch.adapter import AgentSearchAdapter, ToolArgumentError
from agentsearch.cli import PACKAGE_ROOT, build_parser
from agentsearch.protocol import (
    MAX_REQUEST_CHARS, MCPServer, handle_json_request, serve_json_lines, serve_mcp,
)


class DummyEngine:
    def __init__(self):
        self.calls = []

    def search(self, **kwargs):
        self.calls.append(("search", kwargs))
        return {"ok": True, "complete": True, "results": [{"path": "Δ/研究.py"}], "warnings": []}

    def grep(self, **kwargs):
        self.calls.append(("grep", kwargs))
        return {"ok": True, "complete": False, "results": [], "warnings": ["budget"]}

    def read(self, **kwargs):
        self.calls.append(("read", kwargs))
        raise PermissionError("Path is outside configured roots.")

    def status(self, **kwargs):
        self.calls.append(("status", kwargs))
        return {"ok": True, "index": {"generation": 1}}


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.engine = DummyEngine()
        self.adapter = AgentSearchAdapter(self.engine)

    @staticmethod
    def initialize(server: MCPServer, version="2025-11-25"):
        result = server.handle({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": version, "capabilities": {},
                       "clientInfo": {"name": "protocol-test", "version": "1"}},
        })
        server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return result

    def test_schema_rejects_mutations_unknown_fields_and_bool_numbers(self):
        invalid = [
            ("index", {}),
            ("file_search", {"query": "x", "limit": True}),
            ("file_search", {"query": "x", "shell": "touch should-not-run"}),
            ("content_search", {"pattern": "x", "regex": True}),
            ("content_search", {"pattern": "x", "budget_ms": 30001}),
            ("read_file", {"path": "x", "max_chars": 64001}),
            ("index_status", {"refresh": True}),
        ]
        for name, arguments in invalid:
            with self.subTest(name=name, arguments=arguments):
                with self.assertRaises(ToolArgumentError):
                    self.adapter.dispatch(name, arguments)
        self.assertEqual(self.engine.calls, [])

    def test_jsonl_recovers_after_bad_and_oversized_request(self):
        stdin = io.StringIO(
            '{bad json}\n' + 'x' * (MAX_REQUEST_CHARS + 10) + '\n'
            + json.dumps({"id": "valid", "op": "search", "query": "研究"}) + '\n'
        )
        stdout = io.StringIO()
        serve_json_lines(self.engine, stdin, stdout, io.StringIO())
        responses = [json.loads(line) for line in stdout.getvalue().splitlines()]
        self.assertEqual(len(responses), 3)
        self.assertFalse(responses[0]["ok"])
        self.assertFalse(responses[1]["ok"])
        self.assertTrue(responses[2]["ok"])
        self.assertEqual(responses[2]["id"], "valid")
        self.assertEqual(responses[2]["results"][0]["path"], "Δ/研究.py")
        self.assertEqual(len(self.engine.calls), 1)

    def test_jsonl_unknown_operation_and_extra_field_do_not_reach_engine(self):
        for request in (
            {"id": 3, "op": "index"},
            {"id": 3, "op": "read", "path": "README.md", "execute": True},
        ):
            result = handle_json_request(self.adapter, request)
            self.assertEqual(result["id"], 3)
            self.assertFalse(result["ok"])
        self.assertEqual(self.engine.calls, [])

    def test_engine_failure_is_not_an_empty_success(self):
        result = self.adapter.dispatch("read_file", {"path": "../private.txt"})
        self.assertFalse(result["ok"])
        self.assertFalse(result["complete"])
        self.assertEqual(result["error"]["code"], "PermissionError")

    def test_tools_cannot_run_before_initialization_or_as_notifications(self):
        server = MCPServer(self.engine)
        response = server.handle({
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "index_status", "arguments": {}},
        })
        self.assertIn("error", response)
        self.initialize(server)
        response = server.handle({
            "jsonrpc": "2.0", "method": "tools/call",
            "params": {"name": "index_status", "arguments": {}},
        })
        self.assertIsNone(response)
        self.assertEqual(self.engine.calls, [])

    def test_mcp_negotiates_supported_and_fallback_versions(self):
        for requested, expected in (
            ("2025-06-18", "2025-06-18"),
            ("2025-11-25", "2025-11-25"),
            ("2099-01-01", "2025-11-25"),
        ):
            with self.subTest(requested=requested):
                server = MCPServer(self.engine)
                result = self.initialize(server, requested)
                self.assertEqual(result["result"]["protocolVersion"], expected)
                self.assertEqual(result["result"]["capabilities"], {"tools": {"listChanged": False}})

    def test_mcp_tool_failure_is_visible_to_model(self):
        server = MCPServer(self.engine)
        self.initialize(server)
        response = server.handle({
            "jsonrpc": "2.0", "id": "read", "method": "tools/call",
            "params": {"name": "read_file", "arguments": {"path": "../private.txt"}},
        })
        self.assertTrue(response["result"]["isError"])
        structured = response["result"]["structuredContent"]
        self.assertFalse(structured["ok"])
        self.assertEqual(json.loads(response["result"]["content"][0]["text"]), structured)

    def test_mcp_stream_returns_only_response_lines_and_retains_partial_flag(self):
        requests = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                        "clientInfo": {"name": "test", "version": "1"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "content_search", "arguments": {"pattern": "x"}}},
            {"jsonrpc": "2.0", "id": 4, "method": "unknown"},
        ]
        stdout = io.StringIO()
        serve_mcp(self.engine, io.StringIO("\n".join(map(json.dumps, requests))), stdout, io.StringIO())
        responses = [json.loads(line) for line in stdout.getvalue().splitlines()]
        self.assertEqual([item["id"] for item in responses], [1, 2, 3, 4])
        self.assertEqual({item["name"] for item in responses[1]["result"]["tools"]},
                         {"file_search", "content_search", "read_file", "verify_evidence", "index_status"})
        self.assertFalse(responses[2]["result"]["structuredContent"]["complete"])
        self.assertEqual(responses[3]["error"]["code"], -32601)

    def test_nan_and_json_rpc_batch_rejected(self):
        stdin = io.StringIO('{"jsonrpc":"2.0","id":NaN,"method":"ping"}\n[]\n')
        stdout = io.StringIO()
        serve_mcp(self.engine, stdin, stdout, io.StringIO())
        responses = [json.loads(line) for line in stdout.getvalue().splitlines()]
        self.assertEqual(responses[0]["error"]["code"], -32700)
        self.assertEqual(responses[1]["error"]["code"], -32600)
        self.assertEqual(self.engine.calls, [])

    def test_global_paths_survive_subcommands_in_either_position(self):
        before = build_parser().parse_args(["--config", "a.json", "--db", "a.sqlite3", "status"])
        after = build_parser().parse_args(["status", "--config", "b.json", "--db", "b.sqlite3"])
        self.assertEqual((before.config, before.db), (Path("a.json"), Path("a.sqlite3")))
        self.assertEqual((after.config, after.db), (Path("b.json"), Path("b.sqlite3")))

    def test_subprocess_cli_jsonl_and_mcp_with_persisted_index(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            root = base / "source with spaces"
            root.mkdir()
            source = root / "研究 calibration.py"
            source.write_text("checkpoint_version = 7\n", encoding="utf-8")
            config, database = base / "search.json", base / "index.sqlite3"
            paths = ["--config", str(config), "--db", str(database)]

            def run(arguments, input_text=None):
                result = subprocess.run(
                    [sys.executable, "-m", "agentsearch", *arguments],
                    cwd=PACKAGE_ROOT, input=input_text, capture_output=True,
                    text=True, encoding="utf-8", timeout=15,
                )
                messages = [json.loads(line) for line in result.stdout.splitlines()]
                return result, messages

            setup, messages = run([*paths, "config", "--root", str(root)])
            self.assertEqual(setup.returncode, 0, setup.stderr)
            self.assertTrue(messages[0]["ok"])
            indexed, messages = run(["index", *paths])
            self.assertEqual(indexed.returncode, 0, indexed.stderr)
            self.assertTrue(messages[0]["ok"])
            self.assertTrue(database.is_file())
            searched, messages = run([*paths, "search", "calibration"])
            self.assertEqual(searched.returncode, 0, searched.stderr)
            self.assertEqual(messages[0]["hits"][0]["path"], str(source))

            # A new process must reuse roots persisted inside SQLite, without
            # the configuration file or any state held by the creating process.
            config.unlink()
            streamed, messages = run(
                ["stdio", *paths],
                json.dumps({"id": "lookup", "op": "grep", "pattern": "checkpoint_version"}) + "\n",
            )
            self.assertEqual(streamed.returncode, 0, streamed.stderr)
            self.assertEqual(messages[0]["id"], "lookup")
            self.assertTrue(messages[0]["ok"])
            self.assertEqual(messages[0]["files"][0]["matches"][0]["line"], 1)

            requests = [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                 "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                            "clientInfo": {"name": "subprocess-test", "version": "1"}}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                 "params": {"name": "read_file", "arguments": {"path": str(source)}}},
            ]
            mcp, messages = run([*paths, "mcp"], "\n".join(map(json.dumps, requests)) + "\n")
            self.assertEqual(mcp.returncode, 0, mcp.stderr)
            self.assertEqual([item["id"] for item in messages], [1, 2])
            self.assertIn("checkpoint_version", messages[1]["result"]["structuredContent"]["text"])
            self.assertFalse(messages[1]["result"]["isError"])

            invalid, messages = run([*paths, "config", "--root", str(base / "missing")])
            self.assertNotEqual(invalid.returncode, 0)
            self.assertEqual(len(messages), 1)
            self.assertFalse(messages[0]["ok"])
            self.assertFalse(config.exists())


if __name__ == "__main__":
    unittest.main()
