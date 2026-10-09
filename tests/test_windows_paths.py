"""Native Windows path checks; skipped on every other operating system.

Passing Linux tests is not a claim that these native Windows checks passed.
Run this file on Windows (or inspect the Windows CI result) for that evidence.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from agentsearch import SearchConfig, SearchEngine


@unittest.skipUnless(os.name == "nt", "Requires a native Windows filesystem")
class NativeWindowsPathTests(unittest.TestCase):
    def test_drive_path_with_spaces_unicode_and_both_separators(self) -> None:
        with tempfile.TemporaryDirectory(prefix="AgentSearch Windows ") as temporary:
            base = Path(temporary).resolve()
            root = base / "Mémoires 雪"
            root.mkdir()
            path = root / "learning receipt.txt"
            path.write_text("windows_path_payload\n", encoding="utf-8")
            with SearchEngine(
                base / "index.sqlite3", SearchConfig(roots=(str(root),))
            ) as engine:
                engine.index()
                self.assertIn(
                    path,
                    {Path(hit["path"]) for hit in engine.search("learning receipt")["hits"]},
                )
                self.assertIn("windows_path_payload", engine.read(str(path))["text"])
                self.assertIn("windows_path_payload", engine.read(path.as_posix())["text"])

    def test_parent_traversal_cannot_leave_configured_root(self) -> None:
        with tempfile.TemporaryDirectory(prefix="AgentSearch Windows ") as temporary:
            base = Path(temporary).resolve()
            root = base / "allowed"
            root.mkdir()
            outside = base / "outside.txt"
            outside.write_text("outside\n", encoding="utf-8")
            with SearchEngine(
                base / "index.sqlite3", SearchConfig(roots=(str(root),))
            ) as engine:
                engine.index()
                with self.assertRaises(ValueError):
                    engine.read(str(root / ".." / outside.name))


if __name__ == "__main__":
    unittest.main()

@unittest.skipUnless(os.name == 'nt', 'Requires native Windows and PowerShell')
class NativeWindowsLauncherTests(unittest.TestCase):
    def _exercise(self, executable):
        import json
        import shutil
        import subprocess
        if not executable:
            self.skipTest('This PowerShell executable is not installed.')
        package = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix='AgentSearch launcher ') as t:
            destination = Path(t)/'package'; destination.mkdir()
            shutil.copy2(package/'AgentSearch.ps1', destination/'AgentSearch.ps1')
            shutil.copytree(package/'agentsearch', destination/'agentsearch', ignore=shutil.ignore_patterns('__pycache__'))
            root = Path(t)/'Mémoires 雪'; root.mkdir()
            (root/'checkpoint.txt').write_text('launcher_payload\n', encoding='utf-8')
            actions = [('Setup', ['-Root', str(root)]), ('Index', []),
                       ('Search', ['-Query', 'checkpoint']), ('Grep', ['-Query', 'launcher_payload']),
                       ('Check', []), ('Index', ['-Force']), ('Status', [])]
            for action, extra in actions:
                import sys
                result = subprocess.run([executable, '-NoLogo', '-NoProfile', '-NonInteractive',
                                         '-ExecutionPolicy', 'Bypass', '-File', str(destination/'AgentSearch.ps1'),
                                         '-PythonExecutable', sys.executable, '-Action', action, *extra], capture_output=True, text=True, encoding='utf-8', timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                payload = json.loads(result.stdout.strip())
                self.assertTrue(payload['ok'])
                if action == 'Search':
                    self.assertEqual(len(payload['hits']), 1)
                if action == 'Grep':
                    self.assertEqual(len(payload['files']), 1)

    def test_windows_powershell_51_launcher(self):
        import shutil
        self._exercise(shutil.which('powershell.exe'))

    def test_windows_powershell_7_launcher(self):
        import shutil
        self._exercise(shutil.which('pwsh.exe'))
