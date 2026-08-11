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

If the previous run (sdk backend) never finished, pass --resume to be
offered a chance to continue it in the same Claude session (with its
completed tool calls already in context) instead of starting fresh —
sdk backend only. Without --resume, an incomplete run is only reported,
not acted on.

Usage:
    python main.py "What is 15% of 240, plus 30?"
    python main.py --backend api "What is 15% of 240, plus 30?"
    python main.py                      (then type the task when prompted)
    python main.py --chat               (interactive multi-turn session)
    python main.py --resume             (offers to continue an incomplete run)
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
    parser.add_argument(
        "--resume",
        action="store_true",
        help=(
            "If a previous run stopped incomplete, offer to resume it in the "
            "same Claude session instead of starting fresh (sdk backend only)."
        ),
    )
    args = parser.parse_args()

    resume_session_id = None
    resume_task = None

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
            if not args.resume:
                print("(Run again with --resume to continue it.)\n")
            else:
                session_id = incomplete.get("session_id")
                if not session_id:
                    print(
                        "Can't resume — no Claude session was captured for that "
                        "run (it likely crashed before completing a step). "
                        "Starting fresh.\n"
                    )
                else:
                    choice = input("Resume this run? [y/N]: ").strip().lower()
                    if choice in ("y", "yes"):
                        resume_session_id = session_id
                        resume_task = incomplete.get("task")
                    else:
                        print("Starting a new run instead.\n")

    if args.chat:
        if args.backend != "sdk":
            print("Chat mode is only available with the sdk backend.")
            return 1

        from agent.sdk_core import AgentSDKError, run_agent_chat_sdk

        try:
            run_agent_chat_sdk(resume_session_id=resume_session_id, resume_task=resume_task)
        except AgentSDKError as e:
            print(f"Agent SDK error: {e}")
            return 1
        return 0

    if resume_session_id:
        # Continuing a previous run, not starting a new one — don't ask for
        # (or require) a fresh task; the resumed session already has it.
        task = (
            "Continue the task from where you left off and give a final "
            "answer, or continue using tools if more steps are needed."
        )
    else:
        task = " ".join(args.task) if args.task else input("Enter a task for the agent: ").strip()
        if not task:
            print("No task given.")
            return 1

    if args.backend == "sdk":
        from agent.sdk_core import AgentSDKError, run_agent_sdk

        try:
            answer = run_agent_sdk(task, resume_session_id=resume_session_id)
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
