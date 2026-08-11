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
from claude_agent_sdk import ProcessError, ResultMessage

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
    response. Records every connect() so tests can confirm the session
    was opened once, not re-created after the failure.
    """

    enter_count = 0

    def __init__(self, options=None):
        self.options = options
        self.query_calls = []

    async def connect(self):
        type(self).enter_count += 1

    async def disconnect(self):
        pass

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
             patch("agent.memory.save_memory"), \
             patch("agent.task_state.start_run"), \
             patch("agent.task_state.record_step"), \
             patch("agent.task_state.complete_run"), \
             patch("agent.task_state.fail_run") as fail_run:
            anyio.run(sdk_core._run_chat_async, events.append)

        # The simulated CLI crash was recorded to the task ledger, not just
        # logged to the console.
        fail_run.assert_called_once()

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


class _FakeResumeClient:
    """Stands in for ClaudeSDKClient for resume-wiring tests. Records the
    options it was constructed with (so tests can assert `resume=` was set)
    and returns one clean turn — no tool calls — whose ResultMessage carries
    a session_id, so `_process_turn`'s task_state.set_session_id call can be
    exercised without a live CLI.
    """

    instances: list["_FakeResumeClient"] = []

    def __init__(self, options=None):
        self.options = options
        self.query_calls = []
        type(self).instances.append(self)

    # run_agent_sdk (single-shot) still uses `async with ClaudeSDKClient(...)`.
    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.disconnect()
        return False

    # _run_chat_async calls connect()/disconnect() directly, so it can fall
    # back to a fresh (non-resuming) client if a resumed connect() fails.
    async def connect(self):
        pass

    async def disconnect(self):
        pass

    async def query(self, message):
        self.query_calls.append(message)

    async def receive_response(self):
        yield ResultMessage(
            subtype="success",
            duration_ms=1,
            duration_api_ms=1,
            is_error=False,
            num_turns=1,
            session_id="sess-resume-123",
            result="42",
        )


class ResumeWiringTests(unittest.TestCase):
    def setUp(self):
        _FakeResumeClient.instances = []

    def test_run_agent_sdk_resume_sets_resume_option_and_reactivates_the_ledger(self):
        with patch("agent.sdk_core.ClaudeSDKClient", _FakeResumeClient), \
             patch("agent.task_state.reactivate_run") as reactivate_run, \
             patch("agent.task_state.start_run") as start_run, \
             patch("agent.task_state.set_session_id") as set_session_id, \
             patch("agent.task_state.complete_run"):
            sdk_core.run_agent_sdk("continue please", resume_session_id="sess-resume-123")

        self.assertEqual(_FakeResumeClient.instances[0].options.resume, "sess-resume-123")
        reactivate_run.assert_called_once()
        start_run.assert_not_called()
        set_session_id.assert_called_once_with("sess-resume-123")

    def test_run_agent_sdk_without_resume_starts_a_fresh_run_as_before(self):
        with patch("agent.sdk_core.ClaudeSDKClient", _FakeResumeClient), \
             patch("agent.task_state.reactivate_run") as reactivate_run, \
             patch("agent.task_state.start_run") as start_run, \
             patch("agent.task_state.set_session_id"), \
             patch("agent.task_state.complete_run"):
            sdk_core.run_agent_sdk("a fresh task")

        self.assertIsNone(_FakeResumeClient.instances[0].options.resume)
        start_run.assert_called_once_with("a fresh task")
        reactivate_run.assert_not_called()

    def test_run_chat_sdk_resume_sends_one_continuation_query_before_prompting(self):
        inputs = iter(["exit"])
        with patch("agent.sdk_core.ClaudeSDKClient", _FakeResumeClient), \
             patch("builtins.input", side_effect=lambda _prompt: next(inputs)), \
             patch("agent.memory.load_memory", return_value=""), \
             patch("agent.memory.save_memory"), \
             patch("agent.task_state.reactivate_run") as reactivate_run, \
             patch("agent.task_state.set_session_id"), \
             patch("agent.task_state.complete_run"):
            run_agent_chat_sdk(resume_session_id="sess-resume-123", resume_task="what is 2+2?")

        client = _FakeResumeClient.instances[0]
        self.assertEqual(client.options.resume, "sess-resume-123")
        reactivate_run.assert_called_once()
        # The first query sent was the automatic continuation, before the
        # interactive loop even asked for input (the "exit" that followed).
        # A second query follows at session end — that's the unrelated
        # end-of-session memory-summary prompt (had_a_turn is now True).
        self.assertGreaterEqual(len(client.query_calls), 1)
        self.assertIn("Continue the task", client.query_calls[0])

    def test_run_chat_sdk_without_resume_leaves_resume_option_unset(self):
        inputs = iter(["exit"])
        with patch("agent.sdk_core.ClaudeSDKClient", _FakeResumeClient), \
             patch("builtins.input", side_effect=lambda _prompt: next(inputs)), \
             patch("agent.memory.load_memory", return_value=""), \
             patch("agent.memory.save_memory"), \
             patch("agent.task_state.reactivate_run") as reactivate_run:
            run_agent_chat_sdk()

        self.assertIsNone(_FakeResumeClient.instances[0].options.resume)
        reactivate_run.assert_not_called()
        # No turns happened (only "exit" was typed), so no query was sent.
        self.assertEqual(_FakeResumeClient.instances[0].query_calls, [])


class _FakeStaleResumeClient:
    """Simulates a stale/pruned Claude CLI session: connect() fails with a
    ProcessError whenever `resume` is set on its options, succeeds otherwise.
    Every instance is recorded, so tests can confirm _run_chat_async falls
    back to a second, freshly-constructed, non-resuming client rather than
    letting the connect() failure end the whole chat session.
    """

    instances: list["_FakeStaleResumeClient"] = []

    def __init__(self, options=None):
        self.options = options
        self.query_calls = []
        type(self).instances.append(self)

    async def connect(self):
        if self.options.resume:
            raise ProcessError("stale session", exit_code=1, stderr="no such session")

    async def disconnect(self):
        pass

    async def query(self, message):
        self.query_calls.append(message)

    async def receive_response(self):
        return
        yield  # pragma: no cover - presence of yield makes this an async generator


class StaleResumeFallbackTests(unittest.TestCase):
    def setUp(self):
        _FakeStaleResumeClient.instances = []

    def test_a_stale_resume_session_falls_back_to_a_fresh_chat_session(self):
        events = []
        inputs = iter(["exit"])

        with patch("agent.sdk_core.ClaudeSDKClient", _FakeStaleResumeClient), \
             patch("builtins.input", side_effect=lambda _prompt: next(inputs)), \
             patch("agent.memory.load_memory", return_value=""), \
             patch("agent.memory.save_memory"), \
             patch("agent.task_state.reactivate_run") as reactivate_run, \
             patch("agent.task_state.fail_run") as fail_run:
            run_agent_chat_sdk(
                events.append, resume_session_id="stale-sess-id", resume_task="an old task"
            )

        # Two clients were constructed: the failed resume attempt, then the
        # fresh fallback — and the fallback's options carry no resume id.
        self.assertEqual(len(_FakeStaleResumeClient.instances), 2)
        self.assertEqual(_FakeStaleResumeClient.instances[0].options.resume, "stale-sess-id")
        self.assertIsNone(_FakeStaleResumeClient.instances[1].options.resume)

        # The failed connect was recorded to the ledger, not silently dropped.
        fail_run.assert_called_once()
        # Falling back skipped the resume path entirely — no continuation
        # query was sent, and the run was never reactivated.
        reactivate_run.assert_not_called()
        self.assertEqual(_FakeStaleResumeClient.instances[1].query_calls, [])

        # The failure was reported, and the session still ended normally
        # (via "exit"), not by an uncaught exception ending the process.
        self.assertTrue(any("resume failed" in e for e in events))
        self.assertTrue(any("Ending chat session" in e for e in events))

    def test_a_connect_failure_without_resume_still_propagates_as_before(self):
        # No fallback without a resume attempt in play — a plain startup
        # failure (bad CLI install, etc.) should surface exactly as it
        # always has, not be swallowed by the new stale-session handling.
        class _FakeAlwaysFailsClient(_FakeStaleResumeClient):
            async def connect(self):
                raise ProcessError("no claude CLI", exit_code=1, stderr="not found")

        with patch("agent.sdk_core.ClaudeSDKClient", _FakeAlwaysFailsClient), \
             patch("agent.memory.load_memory", return_value=""), \
             patch("agent.task_state.fail_run") as fail_run:
            with self.assertRaises(ProcessError):
                anyio.run(sdk_core._run_chat_async, print)

        fail_run.assert_not_called()
        # Only one connect attempt was made — no fresh fallback client.
        self.assertEqual(len(_FakeStaleResumeClient.instances), 1)


if __name__ == "__main__":
    unittest.main()
