# agentic-ai

A hand-built, modular AI agent — no framework — to learn how agents actually work
before reaching for something like LangChain.

There are **two backends**, both driven by the same tools (`calculator`,
`get_current_time`, `random_number`):

| Backend | How it runs | Cost |
|---|---|---|
| `sdk` (default) | Claude Agent SDK, through your already-logged-in `claude` CLI | Free — uses your Claude subscription, no API key |
| `api` | Raw Anthropic Messages API (`agent/core.py`'s hand-written loop) | Needs a billed `ANTHROPIC_API_KEY` |

If you don't have API billing set up, use the default `sdk` backend — it needs no
setup beyond `claude` already being installed and logged in (`claude auth status`
to check).

## Setup

1. Activate the virtual environment:
   ```
   .venv\Scripts\activate
   ```
2. Run the agent (uses the `sdk` backend by default — no API key needed):
   ```
   python main.py "What is 15% of 240, plus 30?"
   ```
   or run it with no arguments to be prompted for a task.
3. For a multi-turn session — where follow-ups like "multiply that by 10" can
   refer to earlier results — use `--chat`:
   ```
   python main.py --chat
   ```
   Type `exit` or `quit` to end the session. Chat mode is currently `sdk`-backend
   only.

### Optional: the `api` backend

Only needed if you want to run the hand-written Messages-API loop directly, which
requires a billed key:

1. Copy `.env.example` to `.env` and add your Anthropic API key
   (get one at https://console.anthropic.com/settings/keys):
   ```
   copy .env.example .env
   ```
2. Run with `--backend api`:
   ```
   python main.py --backend api "What is 15% of 240, plus 30?"
   ```

## Project structure

```
agent/
├── config.py       env loading, model name, safety limits (api backend)
├── client.py       builds the Anthropic API client (api backend)
├── core.py         the hand-written agent loop, raw Messages API (api backend)
├── sdk_tools.py     wraps agent/tools/ for the Claude Agent SDK's custom-tool format
├── sdk_core.py      the agent loop via the Claude Agent SDK (sdk backend)
└── tools/
    ├── __init__.py         registry — touched to register a new tool for the api backend
    ├── calculator.py       the calculator tool — shared by both backends
    ├── get_current_time.py the clock tool — shared by both backends
    └── random_number.py    the random-integer tool — shared by both backends

main.py             CLI entry point (--backend sdk|api, --chat for multi-turn)
tests/
├── test_tools.py      unit tests for the tool layer (no API calls)
└── test_chat_mode.py  unit tests for chat-mode plumbing (no API calls)
```

## How the agent loop works

Both backends implement the same idea — send the task, let Claude decide whether a
tool is needed, run the tool, feed the result back, repeat until there's a final
answer — just via different mechanics:

**`api` backend** (`agent/core.py`) — a loop we wrote ourselves:
1. Send the conversation + the list of available tools to Claude.
2. If Claude's response asks to call a tool, run that tool in Python and send the
   result back.
3. Repeat until Claude answers without requesting another tool call, or a safety
   cap (`MAX_ITERATIONS` in `agent/config.py`) is hit.

`agent/core.py` never references a specific tool by name — it only reads
`agent.tools.SCHEMAS` (what Claude sees) and `agent.tools.REGISTRY` (name → function).

**`sdk` backend** (`agent/sdk_core.py`) — the same loop, run by the Claude Agent
SDK's own harness instead of our `while` loop. We configure it with `tools=[]`
(disables Claude Code's built-in tools — Bash, Read, Write, etc.) plus our own
tools registered as in-process MCP tools (`agent/sdk_tools.py`), so the agent's
capabilities stay identical to the `api` backend: it can do arithmetic and tell
the current time, and nothing else — no filesystem or shell access either way.

**Chat mode** (`run_agent_chat_sdk` / `_run_chat_async` in `agent/sdk_core.py`) —
single-shot mode (above) opens a `ClaudeSDKClient`, sends one task, and discards
the session. Chat mode instead keeps one `ClaudeSDKClient` session open across a
loop of `input()` prompts, so conversation history (including earlier tool
results) persists turn to turn until the user types `exit`/`quit`/`q`. The `api`
backend doesn't have a chat mode yet — see "Next steps".

## Running the tests

```
python -m unittest discover -s tests -v
```

These are pure logic tests against the tool functions and registries — no API
key, no network call, no `claude` CLI invocation. They run identically whether
or not you've set up the `api` backend.

## Adding a new tool

1. Create a module in `agent/tools/`, e.g. `agent/tools/web_search.py`, exposing:
   - `NAME` — the tool's identifier
   - `SCHEMA` — the JSON schema Claude uses to decide when/how to call it
   - `run(**kwargs)` — the implementation
2. Register it for the `api` backend: import it in `agent/tools/__init__.py` and
   add it to `_TOOL_MODULES`.
3. Register it for the `sdk` backend: add a matching `@tool(...)`-wrapped function
   in `agent/sdk_tools.py`, add it to the `SERVER`'s `tools=[...]` list, and add
   its `mcp__local_tools__<name>` entry to `ALLOWED_TOOL_NAMES`.
4. Add tests for it in `tests/test_tools.py`.

Nothing in `core.py`, `sdk_core.py`, or `main.py` needs to change.

## Next steps

- Bring multi-turn chat mode to the `api` backend for parity with `sdk`.
- Once the manual loop makes sense, look at the Anthropic SDK's tool runner
  (`client.beta.messages.tool_runner`), which automates the `api` backend's loop
  for you the same way the Agent SDK automates the `sdk` backend's.
