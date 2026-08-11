"""The core agent loop: reason, call a tool if needed, repeat, answer.

This is the framework-free version of an "agentic loop":
1. Send the conversation + available tools to Claude.
2. If Claude's stop_reason is "tool_use", run the requested tool(s) and
   send the result(s) back.
3. Repeat until Claude stops asking for tools, or we hit the safety cap.

This module never imports a specific tool — it only knows about
agent.tools.SCHEMAS and agent.tools.REGISTRY, so new tools never require
changes here.
"""

import json

import anthropic

from . import config
from .client import get_client
from .tools import SCHEMAS, REGISTRY


class AgentError(Exception):
    """Raised when the agent cannot produce an answer."""


def _run_tool(name: str, tool_input: dict) -> tuple[str, bool]:
    """Execute a tool by name. Returns (result_text, is_error)."""
    fn = REGISTRY.get(name)
    if fn is None:
        return f"Error: unknown tool '{name}'.", True
    try:
        return str(fn(**tool_input)), False
    except Exception as e:
        return f"Error running tool '{name}': {e}", True


def run_agent(user_message: str, on_event=print) -> str:
    """Run the agent loop for a single user task and return the final answer.

    `on_event(str)` is called for progress updates (tool calls, intermediate
    text) — pass a no-op (e.g. `lambda _: None`) to silence it.

    Raises AgentError on API failures or if no final answer is reached
    within config.MAX_ITERATIONS tool-call rounds.
    """
    client = get_client()
    messages = [{"role": "user", "content": user_message}]

    for _ in range(config.MAX_ITERATIONS):
        try:
            response = client.messages.create(
                model=config.MODEL,
                max_tokens=config.MAX_TOKENS,
                tools=SCHEMAS,
                messages=messages,
            )
        except anthropic.AuthenticationError:
            raise AgentError("Authentication failed — check your ANTHROPIC_API_KEY.")
        except anthropic.RateLimitError:
            raise AgentError("Rate limited by the API. Wait a moment and try again.")
        except anthropic.APIConnectionError:
            raise AgentError("Could not reach the Anthropic API. Check your network connection.")
        except anthropic.APIStatusError as e:
            raise AgentError(f"API error ({e.status_code}): {e.message}")

        for block in response.content:
            if block.type == "text" and block.text:
                on_event(f"Claude: {block.text}")

        if response.stop_reason != "tool_use":
            return next((b.text for b in response.content if b.type == "text"), "")

        # Claude asked for one or more tool calls: record its turn, run each
        # tool, and send all results back together in a single user turn.
        messages.append({"role": "assistant", "content": response.content})

        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                on_event(f"[tool call] {block.name}({json.dumps(block.input)})")
                result_text, is_error = _run_tool(block.name, block.input)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_text,
                        "is_error": is_error,
                    }
                )
        messages.append({"role": "user", "content": tool_results})

    raise AgentError(
        f"Agent did not reach a final answer within {config.MAX_ITERATIONS} tool-call rounds."
    )
