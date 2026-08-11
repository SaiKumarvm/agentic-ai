"""CLI entry point for the agent.

Two backends are available:

  --backend sdk  (default) Claude Agent SDK, driven through the local `claude`
                 CLI login (your Claude subscription). No API key, no billing.
  --backend api  Raw Messages API via agent.core.run_agent. Needs a billed
                 ANTHROPIC_API_KEY in .env. Kept as the reference
                 implementation of a hand-written agent loop.

Two run modes are available:

  single-shot    One task in, one answer out, process exits. Default.
  --chat         Interactive multi-turn session (sdk backend only) — the
                 agent keeps context across turns, so follow-ups like
                 "multiply that by 10" can refer to earlier results.

Usage:
    python main.py "What is 15% of 240, plus 30?"
    python main.py --backend api "What is 15% of 240, plus 30?"
    python main.py                      (then type the task when prompted)
    python main.py --chat               (interactive multi-turn session)
"""

import argparse
import sys

# Claude's output can contain characters (e.g. emoji) outside the default
# Windows console codepage (cp1252), which would otherwise crash print().
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the agent on a task.")
    parser.add_argument("task", nargs="*", help="The task to give the agent.")
    parser.add_argument(
        "--backend",
        choices=["sdk", "api"],
        default="sdk",
        help=(
            "sdk = Claude Agent SDK via your Claude subscription (default, zero-cost). "
            "api = raw Messages API, needs a billed ANTHROPIC_API_KEY."
        ),
    )
    parser.add_argument(
        "--chat",
        action="store_true",
        help="Start an interactive multi-turn chat session (sdk backend only).",
    )
    args = parser.parse_args()

    if args.backend == "sdk":
        from agent import task_state

        incomplete = task_state.load_incomplete_run()
        if incomplete:
            steps_done = len(incomplete.get("steps", []))
            print(
                f"Note: a previous run ({incomplete.get('status')}) stopped after "
                f"{steps_done} step(s) and never finished — task was: "
                f"{incomplete.get('task')!r}\n"
            )

    if args.chat:
        if args.backend != "sdk":
            print("Chat mode is only available with the sdk backend.")
            return 1

        from agent.sdk_core import AgentSDKError, run_agent_chat_sdk

        try:
            run_agent_chat_sdk()
        except AgentSDKError as e:
            print(f"Agent SDK error: {e}")
            return 1
        return 0

    task = " ".join(args.task) if args.task else input("Enter a task for the agent: ").strip()
    if not task:
        print("No task given.")
        return 1

    if args.backend == "sdk":
        from agent.sdk_core import AgentSDKError, run_agent_sdk

        try:
            answer = run_agent_sdk(task)
        except AgentSDKError as e:
            print(f"Agent SDK error: {e}")
            return 1
    else:
        from agent import AgentError, ConfigError, run_agent

        try:
            answer = run_agent(task)
        except ConfigError as e:
            print(f"Configuration error: {e}")
            return 1
        except AgentError as e:
            print(f"Agent error: {e}")
            return 1

    print(f"\nFinal answer: {answer}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
