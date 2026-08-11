"""Tests for the chat-mode plumbing in agent/sdk_core.py.

These check the pieces that don't require a live `claude` CLI session —
exit-command recognition and that the entry point is wired up correctly.
The interactive loop itself (_run_chat_async) drives a real ClaudeSDKClient
and is exercised manually via `python main.py --chat`, not here.

Run with:
    python -m unittest discover -s tests -v
"""

import unittest

from agent.sdk_core import EXIT_COMMANDS, run_agent_chat_sdk


class ChatModeTests(unittest.TestCase):
    def test_exit_commands_are_recognized(self):
        self.assertIn("exit", EXIT_COMMANDS)
        self.assertIn("quit", EXIT_COMMANDS)
        self.assertIn("q", EXIT_COMMANDS)

    def test_run_agent_chat_sdk_is_callable(self):
        self.assertTrue(callable(run_agent_chat_sdk))


if __name__ == "__main__":
    unittest.main()
