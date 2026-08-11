"""Tests for main.py's CLI entry point — specifically that the interactive
input() prompts fail safely (no traceback) when stdin has no data, e.g. a
non-interactive/piped invocation.

Pure logic tests: no network call, no API key, no `claude` CLI invocation —
input() is mocked to raise EOFError directly rather than actually closing
stdin, and agent.task_state.load_incomplete_run is mocked so these don't
depend on whatever is currently in the real (gitignored) task_state.json.

Run with:
    python -m unittest discover -s tests -v
"""

import unittest
from unittest.mock import patch

import main


class MainEOFHandlingTests(unittest.TestCase):
    def test_no_task_and_no_stdin_exits_cleanly_instead_of_crashing(self):
        with patch("sys.argv", ["main.py"]), \
             patch("builtins.input", side_effect=EOFError), \
             patch("agent.task_state.load_incomplete_run", return_value=None):
            result = main.main()

        self.assertEqual(result, 1)

    def test_resume_prompt_with_no_stdin_declines_and_exits_cleanly(self):
        incomplete_run = {
            "task": "an old task",
            "status": "failed",
            "steps": [{"index": 0}],
            "session_id": "some-session-id",
        }
        with patch("sys.argv", ["main.py", "--resume"]), \
             patch("builtins.input", side_effect=EOFError), \
             patch("agent.task_state.load_incomplete_run", return_value=incomplete_run):
            result = main.main()

        # Declining the resume prompt (via EOFError) falls through to the
        # normal task prompt, which also hits EOFError — same clean exit as
        # "no task given," not a crash.
        self.assertEqual(result, 1)


if __name__ == "__main__":
    unittest.main()
