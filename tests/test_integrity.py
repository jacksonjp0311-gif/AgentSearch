"""Independent coverage checks for state changes and retrieval boundaries."""
import json
from pathlib import Path
import random
import tempfile
import unittest

from agentsearch import SearchConfig, SearchEngine


class IntegrityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="agentsearch-integrity-")
        self.base = Path(self.tmp.name).resolve()
        self.root = self.base / "root"
        self.root.mkdir()
        self.db = self.base / "state" / "index.sqlite3"
        self.engine = SearchEngine(self.db, SearchConfig((str(self.root),)))

    def tearDown(self):
        self.engine.close()
        self.tmp.cleanup()

    def test_never_indexed_is_an_error_not_a_negative_search(self):
        self.assertIsNone(self.engine.status()["last_index"])
        with self.assertRaises(ValueError):
            self.engine.search("missing")
        with self.assertRaises(ValueError):
            self.engine.grep("missing")

    def test_config_change_requires_reconciliation_and_removes_old_scope(self):
        (self.root / "old.txt").write_text("old evidence", encoding="utf-8")
        self.engine.index()
        other = self.base / "new_root"
        other.mkdir()
        (other / "new.txt").write_text("new evidence", encoding="utf-8")
        with SearchEngine(self.db, SearchConfig((str(other),))) as second:
            with self.assertRaises(ValueError):
                second.search("old")
            self.assertTrue(second.index()["config_reset"])
            self.assertEqual([], second.search("old")["hits"])
            self.assertEqual(1, len(second.search("new")["hits"]))
            with self.assertRaises(ValueError):
                second.read(str(self.root / "old.txt"))
        with self.assertRaises(ValueError):
            self.engine.search("old")

    def test_result_and_aggregate_text_caps_are_visible(self):
        for i in range(30):
            (self.root / f"receipt_{i:03}.txt").write_text(("needle " + "z" * 1200 + "\n") * 5, encoding="utf-8")
        self.engine.index()
        names = self.engine.search("receipt", limit=2)
        self.assertEqual(2, len(names["hits"]))
        self.assertFalse(names["complete"])
        result = self.engine.grep("needle", limit=200, per_file=20, budget_ms=30000)
        count = sum(len(match["text"]) for file in result["files"] for match in file["matches"])
        self.assertLessEqual(count, 32000)
        self.assertFalse(result["complete"])
        self.assertTrue(any("Aggregate" in warning for warning in result["warnings"]))

    def test_literal_index_agrees_with_direct_reads_on_seeded_corpus(self):
        randomizer = random.Random(731)
        vocabulary = ["AlphaBeta", "x%y_z", 'a"b', "Straße", "checkpoint", "雪の記録", "plain"]
        source = {}
        for i in range(40):
            path = self.root / f"file_{i:03}.txt"
            text = "\n".join(" / ".join(randomizer.sample(vocabulary, 3)) for _ in range(4))
            path.write_text(text, encoding="utf-8")
            source[str(path)] = text
        self.engine.index()
        for needle in ["phaBet", "x%y_z", 'a"b', "STRASSE", "SS", "雪の記録", "plain", "absent-token"]:
            for sensitive in (False, True):
                with self.subTest(pattern=needle, case_sensitive=sensitive):
                    expected = {path for path, text in source.items() if (needle in text if sensitive else needle.casefold() in text.casefold())}
                    result = self.engine.grep(needle, case_sensitive=sensitive, limit=200, per_file=20, budget_ms=30000)
                    self.assertEqual(expected, {file["path"] for file in result["files"]})
                    self.assertTrue(result["complete"])
                    for file in result["files"]:
                        for match in file["matches"]:
                            original = source[file["path"]].splitlines()[match["line"] - 1]
                            self.assertEqual(original, match["text"])
        # Searching must not alter the source corpus.
        self.assertEqual(source, {path: Path(path).read_text(encoding="utf-8") for path in source})

    def test_utf8_bom_config_preserves_explicit_scope(self):
        config_file = self.base / "config.json"
        config_file.write_text(json.dumps({"roots": [str(self.root)]}), encoding="utf-8-sig")
        self.assertEqual((str(self.root),), SearchConfig.from_file(config_file).roots)


if __name__ == "__main__":
    unittest.main()
