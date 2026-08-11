"""Tests for agent/memory.py — the persistent, cross-session memory store
used by chat mode.

Pure filesystem tests against a temp file — no network call, no API key, no
`claude` CLI invocation.

Run with:
    python -m unittest discover -s tests -v
"""

import json
import tempfile
import unittest
from pathlib import Path

from agent import memory


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._original_file = memory.MEMORY_FILE
        memory.MEMORY_FILE = Path(self._tmpdir.name) / "memory.json"

    def tearDown(self):
        memory.MEMORY_FILE = self._original_file
        self._tmpdir.cleanup()

    def test_load_memory_with_no_file_returns_empty_string(self):
        self.assertEqual(memory.load_memory(), "")

    def test_save_then_load_round_trips_the_summary(self):
        memory.save_memory("The user is named Sai and prefers concise answers.")
        self.assertEqual(
            memory.load_memory(), "The user is named Sai and prefers concise answers."
        )

    def test_load_memory_with_a_corrupt_file_returns_empty_string(self):
        memory.MEMORY_FILE.write_text("not valid json", encoding="utf-8")
        self.assertEqual(memory.load_memory(), "")

    def test_save_memory_records_an_updated_at_timestamp(self):
        memory.save_memory("test summary")
        data = json.loads(memory.MEMORY_FILE.read_text(encoding="utf-8"))
        self.assertIn("updated_at", data)

    def test_save_memory_overwrites_the_previous_summary(self):
        memory.save_memory("first summary")
        memory.save_memory("second summary")
        self.assertEqual(memory.load_memory(), "second summary")


if __name__ == "__main__":
    unittest.main()
