"""Tests for the chat-mode plumbing in agent/sdk_core.py.

These check the pieces that don't require a live `claude` CLI session —
exit-command recognition, that the entry point is wired up correctly, and
(via a fake ClaudeSDKClient) that a mid-turn ProcessError doesn't end the
whole session. The full end-to-end loop against a real `claude` CLI is
exercised manually via `python main.py --chat`, not here.

Run with:
    python -m unittest discover -s tests -v
"""

import unittest
from unittest.mock import patch

import anyio
from claude_agent_sdk import ProcessError

from agent import sdk_core
from agent.sdk_core import EXIT_COMMANDS, run_agent_chat_sdk


class ChatModeTests(unittest.TestCase):
    def test_exit_commands_are_recognized(self):
        self.assertIn("exit", EXIT_COMMANDS)
        self.assertIn("quit", EXIT_COMMANDS)
        self.assertIn("q", EXIT_COMMANDS)

    def test_run_agent_chat_sdk_is_callable(self):
        self.assertTrue(callable(run_agent_chat_sdk))


class _FakeAsyncClient:
    """Stands in for ClaudeSDKClient. query() always succeeds; the *first*
    receive_response() raises ProcessError mid-stream (simulating the CLI
    subprocess dying during a turn), and later calls return an empty
    response. Records every __aenter__ so tests can confirm the session
    was opened once, not re-created after the failure.
    """

    enter_count = 0

    def __init__(self, options=None):
        self.options = options
        self.query_calls = []

    async def __aenter__(self):
        type(self).enter_count += 1
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def query(self, message):
        self.query_calls.append(message)

    async def receive_response(self):
        if len(self.query_calls) == 1:
            raise ProcessError("simulated crash", exit_code=1, stderr="boom")
        return
        yield  # pragma: no cover - presence of yield makes this an async generator


class ChatModeFailureRecoveryTests(unittest.TestCase):
    def setUp(self):
        _FakeAsyncClient.enter_count = 0

    def test_a_mid_turn_process_error_does_not_end_the_session(self):
        events = []
        inputs = iter(["hello", "still here?", "exit"])

        with patch("agent.sdk_core.ClaudeSDKClient", _FakeAsyncClient), \
             patch("builtins.input", side_effect=lambda _prompt: next(inputs)), \
             patch("agent.memory.load_memory", return_value=""), \
             patch("agent.memory.save_memory"):
            anyio.run(sdk_core._run_chat_async, events.append)

        # The failed turn was reported, not silently swallowed or crashed on.
        self.assertTrue(any("turn failed" in e for e in events))
        # The loop kept prompting past the failure: all three inputs (the
        # failed turn, a turn after it, and the exit command) were consumed.
        self.assertEqual(list(inputs), [])
        # The session ended the normal way (via the exit command), not by
        # an uncaught exception propagating out of _run_chat_async.
        self.assertTrue(any("Ending chat session" in e for e in events))
        # Exactly one ClaudeSDKClient session was opened for the whole
        # run — the failure didn't tear down and recreate the session,
        # i.e. conversation state (the open client) was preserved.
        self.assertEqual(_FakeAsyncClient.enter_count, 1)


if __name__ == "__main__":
    unittest.main()
