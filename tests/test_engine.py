"""Behavioral checks against a real, isolated filesystem and SQLite index.

These tests exercise user-visible retrieval and scope boundaries. They do not
assert a particular SQL schema, ranking formula, or transient indexing count.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from agentsearch import SearchConfig, SearchEngine


class EngineBehaviorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="agentsearch-tests-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.root = self.base / "authorized project"
        self.root.mkdir()
        self.db = self.base / "search.sqlite3"
        self.config = SearchConfig(roots=(str(self.root),))
        self.engine = SearchEngine(self.db, config=self.config)
        self.addCleanup(self.engine.close)

    def write(self, relative: str, text: str) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def search_paths(self, query: str, **kwargs: object) -> set[Path]:
        result = self.engine.search(query, **kwargs)
        return {Path(hit["path"]) for hit in result["hits"]}

    def grep_paths(self, pattern: str, **kwargs: object) -> set[Path]:
        result = self.engine.grep(pattern, **kwargs)
        return {Path(item["path"]) for item in result["files"]}

    def test_add_change_rename_delete_and_reopen(self) -> None:
        original = self.write("receipts/initial_receipt.md", "alpha_payload\n")
        self.engine.index()
        self.assertIn(original, self.search_paths("initial_receipt"))
        self.assertIn(original, self.grep_paths("alpha_payload"))

        original.write_text("replacement_payload\n", encoding="utf-8")
        # Ensure deterministic metadata detection even on filesystems with
        # coarse write timestamp behavior.
        timestamp = original.stat().st_mtime_ns + 2_000_000_000
        os.utime(original, ns=(timestamp, timestamp))
        self.engine.index()
        self.assertNotIn(original, self.grep_paths("alpha_payload"))
        self.assertIn(original, self.grep_paths("replacement_payload"))

        renamed = original.with_name("renamed_receipt.md")
        original.rename(renamed)
        added = self.write("receipts/added_receipt.md", "new_file_payload\n")
        self.engine.index()
        paths = self.search_paths("receipt")
        self.assertNotIn(original, paths)
        self.assertIn(renamed, paths)
        self.assertIn(added, paths)

        # Reopen with no supplied configuration: persisted roots must be used.
        self.engine.close()
        self.engine = SearchEngine(self.db)
        self.addCleanup(self.engine.close)
        self.assertIn(renamed, self.grep_paths("replacement_payload"))
        renamed.unlink()
        self.engine.index()
        self.assertNotIn(renamed, self.search_paths("receipt"))
        self.assertNotIn(renamed, self.grep_paths("replacement_payload"))
        self.assertIn(added, self.grep_paths("new_file_payload"))

    def test_adjacent_transposition_finds_filename(self) -> None:
        expected = self.write("experiments/calibration.py", "value = 1\n")
        self.write("experiments/measurements.py", "value = 2\n")
        self.engine.index()
        self.assertIn(expected, self.search_paths("calibratoin"))

    def test_unicode_and_spaces_survive_search_and_read(self) -> None:
        expected = self.write("Mémoires 雪/receipt café.md", "Café au lait — 雪\n")
        self.engine.index()
        self.assertIn(expected, self.search_paths("receipt café"))
        self.assertIn(expected, self.grep_paths("雪"))
        result = self.engine.read(str(expected))
        self.assertIn("Café au lait — 雪", result["text"])

    def test_unicode_casefold_expansion_keeps_source_snippet_accurate(self) -> None:
        expected = self.write("unicode_casefold.txt", "ß" * 450 + " needle_payload Straße\n")
        self.engine.index()
        result = self.engine.grep("needle_payload")
        matches = [item for item in result["files"] if Path(item["path"]) == expected]
        self.assertEqual(1, len(matches))
        self.assertTrue(any("needle_payload" in hit["text"] for hit in matches[0]["matches"]))
        self.assertIn(expected, self.grep_paths("STRASSE"))
        self.assertNotIn(expected, self.grep_paths("STRASSE", case_sensitive=True))

    def test_utf16_with_bom_is_decoded_as_text(self) -> None:
        expected = self.root / "powershell_generated.txt"
        expected.write_bytes("checkpoint_version = 4\nCafé 雪\n".encode("utf-16"))
        self.engine.index()
        self.assertIn(expected, self.grep_paths("checkpoint_version"))
        self.assertIn("Café 雪", self.engine.read(str(expected))["text"])

    def test_literal_substring_punctuation_case_and_short_patterns(self) -> None:
        expected = self.write(
            "source.py",
            "prefixAlphaBetaSuffix\nvalue = 'a+b[c]'\nxy\nUPPERCASE\n",
        )
        self.write("other.py", "axbcccc\nordinary words\n")
        self.engine.index()
        self.assertEqual({expected}, self.grep_paths("phaBet"))
        self.assertEqual({expected}, self.grep_paths("a+b[c]"))
        self.assertEqual({expected}, self.grep_paths("xy"))
        self.assertEqual({expected}, self.grep_paths("uppercase"))
        self.assertEqual(set(), self.grep_paths("uppercase", case_sensitive=True))
        self.assertEqual({expected}, self.grep_paths("UPPERCASE", case_sensitive=True))

    def test_fresh_grep_reconciles_changed_and_new_files(self) -> None:
        changed = self.write("learning/state.txt", "old_checkpoint\n")
        self.engine.index()
        changed.write_text("new_checkpoint_payload\n", encoding="utf-8")
        added = self.write("learning/new_receipt.txt", "new_checkpoint_payload\n")
        self.assertEqual(
            {changed, added},
            self.grep_paths("new_checkpoint_payload", fresh=True),
        )

    def test_indexed_candidates_are_verified_against_current_content(self) -> None:
        changed = self.write("receipt.txt", "old_evidence_token\n")
        self.engine.index()
        changed.write_text("replacement evidence\n", encoding="utf-8")
        # An old posting can nominate a path, but must not manufacture the
        # old matching text after the file has changed.
        self.assertNotIn(changed, self.grep_paths("old_evidence_token"))
        self.assertIn("replacement evidence", self.engine.read(str(changed))["text"])

    def test_subdirectory_scope_and_extension_isolate_results(self) -> None:
        selected = self.write("team_a/receipt.py", "scoped_payload\n")
        self.write("team_a/receipt.md", "scoped_payload\n")
        self.write("team_b/receipt.py", "scoped_payload\n")
        self.engine.index()
        scope = str(self.root / "team_a")
        self.assertEqual({selected}, self.search_paths("receipt", scope=scope, ext="py"))
        self.assertEqual({selected}, self.grep_paths("scoped_payload", scope=scope, ext="py"))

    def test_outside_scope_and_read_are_rejected(self) -> None:
        outside = self.base / "private.txt"
        outside.write_text("not authorized\n", encoding="utf-8")
        self.engine.index()
        with self.assertRaises(ValueError):
            self.engine.read(str(outside))
        with self.assertRaises(ValueError):
            self.engine.search("private", scope=str(self.base))
        with self.assertRaises(ValueError):
            self.engine.grep("authorized", scope=str(self.base))

    def test_symlink_does_not_escape_authorized_root(self) -> None:
        outside_dir = self.base / "outside"
        outside_dir.mkdir()
        outside = outside_dir / "classified_receipt.txt"
        outside.write_text("outside_unique_payload\n", encoding="utf-8")
        link = self.root / "linked_receipt.txt"
        directory_link = self.root / "linked_directory"
        try:
            link.symlink_to(outside)
            directory_link.symlink_to(outside_dir, target_is_directory=True)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"Creating symlinks is unavailable: {error}")
        self.engine.index()
        self.assertEqual(set(), self.grep_paths("outside_unique_payload", fresh=True))
        with self.assertRaises(ValueError):
            self.engine.read(str(link))
        with self.assertRaises(ValueError):
            self.engine.read(str(directory_link / outside.name))

    def test_deleted_candidate_is_not_returned_as_content_evidence(self) -> None:
        deleted = self.write("temporary.txt", "deleted_unique_payload\n")
        self.engine.index()
        deleted.unlink()
        self.assertNotIn(deleted, self.grep_paths("deleted_unique_payload"))

    def test_temporarily_missing_root_marks_incomplete_without_mass_deletion(self) -> None:
        retained = self.write("retained_receipt.txt", "retained_payload\n")
        self.engine.index()
        before = self.engine.status()["files"]
        offline = self.base / "temporarily_offline"
        self.root.rename(offline)
        try:
            result = self.engine.index()
            self.assertFalse(result["complete"])
            self.assertTrue(result["warnings"])
            self.assertEqual(before, self.engine.status()["files"])
        finally:
            offline.rename(self.root)
        self.assertTrue(self.engine.index()["complete"])
        self.assertIn(retained, self.grep_paths("retained_payload"))

    def test_read_line_and_character_limits(self) -> None:
        path = self.write("bounded.txt", "first\nsecond\nthird\nfourth\n")
        self.engine.index()
        result = self.engine.read(str(path), start_line=2, max_lines=2)
        self.assertIn("second", result["text"])
        self.assertIn("third", result["text"])
        self.assertNotIn("first", result["text"])
        self.assertNotIn("fourth", result["text"])
        clipped = self.engine.read(str(path), max_chars=5)
        self.assertLessEqual(len(clipped["text"]), 5)
        for kwargs in ({"start_line": 0}, {"max_lines": 0}, {"max_chars": 0}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.engine.read(str(path), **kwargs)


class CoverageBoundaryTests(unittest.TestCase):
    def test_excluded_large_and_binary_files_have_distinct_coverage(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentsearch-coverage-") as temporary:
            base = Path(temporary).resolve()
            root = base / "root"
            (root / "vendor").mkdir(parents=True)
            excluded = root / "vendor" / "excluded_secret.txt"
            excluded.write_text("excluded_payload", encoding="utf-8")
            large = root / "large_ledger.txt"
            large.write_text("large_payload " * 40, encoding="utf-8")
            binary = root / "binary_receipt.bin"
            binary.write_bytes(b"\x00binary_payload\xff\x00")
            small = root / "small_receipt.txt"
            small.write_text("small_payload", encoding="utf-8")
            config = SearchConfig(
                roots=(str(root),), exclude_dirs=("vendor",), max_file_bytes=128
            )
            with SearchEngine(base / "index.sqlite3", config=config) as engine:
                engine.index()
                names = lambda query: {Path(hit["path"]) for hit in engine.search(query)["hits"]}
                content = lambda pattern: {
                    Path(item["path"]) for item in engine.grep(pattern)["files"]
                }
                self.assertEqual(set(), names("excluded_secret"))
                self.assertEqual(set(), content("excluded_payload"))
                self.assertIn(large, names("large_ledger"))
                self.assertNotIn(large, content("large_payload"))
                self.assertIn(binary, names("binary_receipt"))
                self.assertNotIn(binary, content("binary_payload"))
                self.assertEqual({small}, content("small_payload"))
                with self.assertRaises(ValueError):
                    engine.read(str(excluded))


if __name__ == "__main__":
    unittest.main()
