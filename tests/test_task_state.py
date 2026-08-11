"""Tests for agent/task_state.py — the persisted, per-run step ledger.

Pure filesystem tests against a temp file — no network call, no API key, no
`claude` CLI invocation.

Run with:
    python -m unittest discover -s tests -v
"""

import json
import tempfile
import unittest
from pathlib import Path

from agent import task_state


class TaskStateTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._original_file = task_state.TASK_STATE_FILE
        task_state.TASK_STATE_FILE = Path(self._tmpdir.name) / "task_state.json"

    def tearDown(self):
        task_state.TASK_STATE_FILE = self._original_file
        self._tmpdir.cleanup()

    def test_load_incomplete_run_with_no_file_returns_none(self):
        self.assertIsNone(task_state.load_incomplete_run())

    def test_a_run_in_progress_is_reported_as_incomplete(self):
        task_state.start_run("what is 2 + 2?")
        incomplete = task_state.load_incomplete_run()
        self.assertIsNotNone(incomplete)
        self.assertEqual(incomplete["status"], "in_progress")
        self.assertEqual(incomplete["task"], "what is 2 + 2?")
        self.assertEqual(incomplete["steps"], [])

    def test_record_step_appends_in_order(self):
        task_state.start_run("multi-step task")
        task_state.record_step("calculator", {"expression": "2+2"}, "4", False)
        task_state.record_step("get_current_time", {}, "2026-08-11 12:00:00", False)

        data = json.loads(task_state.TASK_STATE_FILE.read_text(encoding="utf-8"))
        self.assertEqual(len(data["steps"]), 2)
        self.assertEqual(data["steps"][0]["index"], 0)
        self.assertEqual(data["steps"][0]["tool"], "calculator")
        self.assertEqual(data["steps"][0]["result"], "4")
        self.assertEqual(data["steps"][1]["index"], 1)
        self.assertEqual(data["steps"][1]["tool"], "get_current_time")

    def test_record_step_with_no_run_in_progress_does_not_raise(self):
        # No start_run() called yet — should be a silent no-op, not a crash.
        task_state.record_step("calculator", {"expression": "1+1"}, "2", False)
        self.assertIsNone(task_state.load_incomplete_run())

    def test_complete_run_clears_incomplete_status(self):
        task_state.start_run("what is 2 + 2?")
        task_state.record_step("calculator", {"expression": "2+2"}, "4", False)
        task_state.complete_run("4")

        self.assertIsNone(task_state.load_incomplete_run())
        data = json.loads(task_state.TASK_STATE_FILE.read_text(encoding="utf-8"))
        self.assertEqual(data["status"], "completed")
        self.assertEqual(data["final_answer"], "4")
        # Steps recorded before completion are preserved, not discarded.
        self.assertEqual(len(data["steps"]), 1)

    def test_fail_run_preserves_steps_recorded_before_the_failure(self):
        task_state.start_run("a task that will crash")
        task_state.record_step("calculator", {"expression": "2+2"}, "4", False)
        task_state.fail_run("simulated CLI crash")

        incomplete = task_state.load_incomplete_run()
        self.assertIsNotNone(incomplete)
        self.assertEqual(incomplete["status"], "failed")
        self.assertEqual(incomplete["failure_reason"], "simulated CLI crash")
        self.assertEqual(len(incomplete["steps"]), 1)

    def test_start_run_overwrites_a_previous_run(self):
        task_state.start_run("first task")
        task_state.record_step("calculator", {"expression": "1+1"}, "2", False)
        task_state.complete_run("2")

        task_state.start_run("second task")
        incomplete = task_state.load_incomplete_run()
        self.assertEqual(incomplete["task"], "second task")
        self.assertEqual(incomplete["steps"], [])

    def test_load_incomplete_run_with_a_corrupt_file_returns_none(self):
        task_state.TASK_STATE_FILE.write_text("not valid json", encoding="utf-8")
        self.assertIsNone(task_state.load_incomplete_run())

    def test_record_step_and_complete_run_are_no_ops_with_no_file(self):
        # Defensive: calling these without a prior start_run() (e.g. a bug
        # in a caller) must not raise.
        task_state.complete_run("some answer")
        self.assertIsNone(task_state.load_incomplete_run())


if __name__ == "__main__":
    unittest.main()
