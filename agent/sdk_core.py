"""Zero-cost agent loop, built on the Claude Agent SDK.

Unlike agent/core.py (which calls the raw Messages API and needs a billed
ANTHROPIC_API_KEY), this drives the already-installed, already-logged-in
`claude` CLI as a subprocess. It runs under whatever account that CLI is
logged into — on this machine, a Claude Pro subscription — so there's no
API key and no billing involved.

The Agent SDK owns the reasoning loop internally: send the task, Claude
decides whether a tool is needed, the tool runs, the result goes back,
Claude continues or answers. That's conceptually the same loop as
agent/core.py's hand-written version — it's just the SDK's harness
running it instead of our own `while` loop.

Tool availability is deliberately locked down: `tools=[]` disables every
Claude Code built-in tool (Bash, Read, Write, ...), and only our own
calculator tool (registered in agent/sdk_tools.py) is made available via
mcp_servers + allowed_tools. This keeps the milestone's scope — "the agent
can call the one tool we gave it" — intact under this backend too.
"""

import anyio
from claude_agent_sdk import (
    AssistantMessage,
    CLINotFoundError,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ProcessError,
    ResultMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from . import memory, task_state
from .sdk_tools import ALLOWED_TOOL_NAMES, MCP_SERVER_NAME, SERVER

SYSTEM_PROMPT = (
    "You are a focused task-completing agent. You have access to a few tools: "
    "a calculator, a clock (current date/time), and a random number generator. "
    "Use whichever ones a task calls for, in whatever order and combination "
    "makes sense. Once you have everything you need, give a direct final answer."
)

# Typed by the user in chat mode to end the session.
EXIT_COMMANDS = {"exit", "quit", "q"}


class AgentSDKError(Exception):
    """Raised when the Claude Agent SDK / underlying CLI fails to complete a task."""


def _tool_result_text(content) -> str:
    """Flatten a ToolResultBlock's content (str | list[dict] | None) into
    the plain string task_state.record_step wants to persist."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    parts = [block.get("text", "") for block in content if isinstance(block, dict)]
    return "\n".join(p for p in parts if p)


async def _process_turn(client: ClaudeSDKClient, on_event) -> tuple[str, str | None]:
    """Drain one turn's response stream: log text/tool-call events, record
    each completed tool call to task_state as its result arrives, and
    return (final_text, error_message).

    error_message is None on success. If the turn's ResultMessage reports
    is_error, error_message holds the reason and the failure has already
    been recorded via task_state.fail_run — callers decide whether that
    should raise (single-shot) or just be reported (chat mode, so one bad
    turn doesn't end the session).
    """
    pending_tool_calls: dict[str, tuple[str, dict]] = {}
    final_text = ""
    async for message in client.receive_response():
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock) and block.text:
                    on_event(f"Claude: {block.text}")
                    final_text = block.text
                elif isinstance(block, ToolUseBlock):
                    on_event(f"[tool call] {block.name}({block.input})")
                    pending_tool_calls[block.id] = (block.name, block.input)
        elif isinstance(message, UserMessage) and isinstance(message.content, list):
            for block in message.content:
                if isinstance(block, ToolResultBlock):
                    name, tool_input = pending_tool_calls.pop(block.tool_use_id, ("unknown", {}))
                    task_state.record_step(
                        name, tool_input, _tool_result_text(block.content), bool(block.is_error)
                    )
        elif isinstance(message, ResultMessage):
            if message.is_error:
                reason = message.result or "The agent run ended in an error."
                task_state.fail_run(reason)
                return final_text, reason
            if message.result:
                final_text = message.result
    return final_text, None


async def _run_agent_async(user_message: str, on_event) -> str:
    options = ClaudeAgentOptions(
        system_prompt=SYSTEM_PROMPT,
        tools=[],  # disable every Claude Code built-in tool (Bash, Read, Write, ...)
        mcp_servers={MCP_SERVER_NAME: SERVER},
        allowed_tools=ALLOWED_TOOL_NAMES,  # pre-approve our one tool; no permission prompt
    )

    task_state.start_run(user_message)
    async with ClaudeSDKClient(options=options) as client:
        await client.query(user_message)
        final_text, error = await _process_turn(client, on_event)

    if error:
        raise AgentSDKError(error)
    task_state.complete_run(final_text)
    return final_text


def run_agent_sdk(user_message: str, on_event=print) -> str:
    """Synchronous entry point, mirroring agent.core.run_agent's signature."""
    try:
        return anyio.run(_run_agent_async, user_message, on_event)
    except CLINotFoundError as e:
        task_state.fail_run(f"Could not find the Claude Code CLI ('claude'): {e}")
        raise AgentSDKError(
            "Could not find the Claude Code CLI ('claude'). It must be installed "
            "and on PATH, and already logged in."
        ) from e
    except ProcessError as e:
        task_state.fail_run(f"The Claude Code process failed: {e}")
        raise AgentSDKError(f"The Claude Code process failed: {e}") from e


async def _save_session_memory(client: ClaudeSDKClient, prior_memory: str, on_event) -> None:
    """Ask Claude (on the still-open session) to summarize what's worth
    remembering, and persist it to disk for the next chat session.
    """
    prompt = (
        "This chat session is ending. In 2-4 plain-text sentences, write an "
        "updated memory summary of facts, results, and preferences worth "
        "remembering next time"
        + (" — merge this with what you already knew from before" if prior_memory else "")
        + ". Reply with only the summary text, nothing else."
    )
    try:
        await client.query(prompt)
        summary = ""
        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock) and block.text:
                        summary = block.text
        if summary:
            memory.save_memory(summary)
            on_event(f"(Saved memory for next time: {summary})")
    except (ProcessError, CLINotFoundError):
        on_event("(Could not save memory for next time — the session ended before it could summarize.)")


async def _run_chat_async(on_event) -> None:
    """Multi-turn loop: one ClaudeSDKClient session stays open across turns,
    so context (including earlier tool results) persists until the user exits.

    Also bridges context *across* separate chat sessions: a saved summary
    from the previous session (agent/memory.py) is loaded into the system
    prompt at the start, and an updated summary is saved at the end.
    """
    prior_memory = memory.load_memory()
    system_prompt = SYSTEM_PROMPT
    if prior_memory:
        system_prompt += (
            "\n\nContext remembered from earlier sessions with this user:\n" + prior_memory
        )

    options = ClaudeAgentOptions(
        system_prompt=system_prompt,
        tools=[],
        mcp_servers={MCP_SERVER_NAME: SERVER},
        allowed_tools=ALLOWED_TOOL_NAMES,
    )

    on_event("Chat mode — type 'exit' or 'quit' to end the session.")
    if prior_memory:
        on_event(f"(Remembering from before: {prior_memory})")

    had_a_turn = False
    async with ClaudeSDKClient(options=options) as client:
        try:
            while True:
                try:
                    user_message = input("\nYou: ").strip()
                except (EOFError, KeyboardInterrupt):
                    on_event("\nEnding chat session.")
                    return

                if not user_message:
                    continue
                if user_message.lower() in EXIT_COMMANDS:
                    on_event("Ending chat session.")
                    return

                had_a_turn = True
                task_state.start_run(user_message)
                try:
                    await client.query(user_message)
                    final_text, error = await _process_turn(client, on_event)
                    if error:
                        on_event(f"Agent error: {error}")
                    else:
                        task_state.complete_run(final_text)
                except (ProcessError, CLINotFoundError) as e:
                    # A CLI/process failure on this turn shouldn't end the whole
                    # session — report it and go back to prompting, so earlier
                    # turns (and the eventual memory save) aren't lost. Whatever
                    # steps task_state recorded before the crash survive on disk.
                    task_state.fail_run(str(e))
                    on_event(
                        f"[turn failed: {e}] That turn hit a CLI/process error and "
                        "was skipped. The session is still open — try again."
                    )
        finally:
            if had_a_turn:
                await _save_session_memory(client, prior_memory, on_event)


def run_agent_chat_sdk(on_event=print) -> None:
    """Run an interactive multi-turn chat session using the sdk backend.

    Unlike run_agent_sdk (one task in, one answer out, session discarded),
    this keeps a single session open across turns via input() prompts, so
    follow-ups like "multiply that by 10" can refer to earlier results.
    Context also persists *across* separate runs of --chat, via
    agent/memory.py — see _run_chat_async.
    """
    try:
        anyio.run(_run_chat_async, on_event)
    except CLINotFoundError as e:
        raise AgentSDKError(
            "Could not find the Claude Code CLI ('claude'). It must be installed "
            "and on PATH, and already logged in."
        ) from e
    except ProcessError as e:
        raise AgentSDKError(f"The Claude Code process failed: {e}") from e
