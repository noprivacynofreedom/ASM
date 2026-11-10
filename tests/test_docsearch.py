"""Regression tests for cached document retrieval."""
import tempfile
import unittest
from pathlib import Path

import _paths  # noqa: F401  (shipped code first on sys.path)
import docsearch


class DocumentSearchTests(unittest.TestCase):
    def setUp(self):
        project_root = Path(__file__).resolve().parents[1]
        self.temp = tempfile.TemporaryDirectory(dir=project_root)
        self.folder = Path(self.temp.name)
        docsearch._cache.pop(str(self.folder), None)

    def tearDown(self):
        docsearch._cache.pop(str(self.folder), None)
        self.temp.cleanup()

    def test_ranks_chunks_by_matching_terms_and_returns_requested_count(self):
        (self.folder / "guide.md").write_text(
            "Model cache stores reusable results.",
            encoding="utf-8",
        )
        (self.folder / "notes.txt").write_text(
            "A short note about model loading and retrieval.", encoding="utf-8"
        )

        results = docsearch.search(str(self.folder), "model loading", k=1)

        self.assertEqual(len(results), 1)
        self.assertEqual(Path(results[0]["file"]).name, "notes.txt")

    def test_cached_postings_refresh_when_a_document_changes(self):
        source = self.folder / "guide.md"
        source.write_text("The first document describes uniqueamber retrieval.", encoding="utf-8")
        self.assertEqual(docsearch.search(str(self.folder), "uniqueamber")[0]["file"], str(source))

        source.write_text("The second document describes indexing uniqueamber.", encoding="utf-8")
        results = docsearch.search(str(self.folder), "uniqueamber")

        self.assertEqual(len(results), 1)
        self.assertIn("indexing", results[0]["text"])

    def test_empty_or_unknown_queries_return_no_results(self):
        (self.folder / "guide.md").write_text("Document retrieval uses an index.", encoding="utf-8")

        self.assertEqual(docsearch.search(str(self.folder), "the and of"), [])
        self.assertEqual(docsearch.search(str(self.folder), "nonexistentterm"), [])


if __name__ == "__main__":
    unittest.main()
