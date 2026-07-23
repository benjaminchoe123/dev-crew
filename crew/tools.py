"""Crew tools: agent communication is just tool use.

The impls are plain async functions (unit-testable, no SDK). build_crew_server
wraps them per-agent so `sender` can never be spoofed by the model.
"""

from __future__ import annotations

from claude_agent_sdk import create_sdk_mcp_server, tool
from claude_agent_sdk.types import McpSdkServerConfig

from crew.bus import Bus
from crew.roles import AGENT_NAMES


async def send_message_impl(bus: Bus, run_id: str, agent: str, args: dict) -> str:
    missing = [k for k in ("to", "kind", "subject", "body") if not args.get(k)]
    if missing:
        return f"ERROR: missing required argument(s): {', '.join(missing)}"
    to, kind, subject, body = args["to"], args["kind"], args["subject"], args["body"]
    if to == agent:
        return "ERROR: you cannot message yourself."
    if to not in AGENT_NAMES:
        return f"ERROR: unknown recipient '{to}'. Valid: {', '.join(AGENT_NAMES)}"
    if bus.has_duplicate(run_id, agent, to, kind, body):
        return "ERROR: identical message already sent. Do not repeat yourself."
    mid = bus.append(
        run_id=run_id, sender=agent, recipient=to, kind=kind, subject=subject, body=body
    )
    return f"Message {mid} delivered to {to}. End your turn when your work is done."


async def ask_human_impl(bus: Bus, run_id: str, agent: str, args: dict) -> str:
    questions = (args.get("questions") or "").strip()
    if not questions:
        return "ERROR: 'questions' is required."
    bus.append(
        run_id=run_id, sender=agent, recipient="user", kind="question",
        subject="clarifying questions", body=questions,
    )
    bus.set_status(agent, "awaiting_human")
    return (
        "Questions delivered to the human. End your turn now; the answers will "
        "arrive in your inbox as a kind=answer message."
    )


async def finish_impl(bus: Bus, run_id: str, agent: str, args: dict) -> str:
    summary = (args.get("summary") or "").strip()
    if not summary:
        return "ERROR: 'summary' is required."
    bus.append(
        run_id=run_id, sender=agent, recipient="run", kind="done",
        subject="run complete", body=summary,
    )
    bus.set_status(agent, "done")
    return "Run marked complete. End your turn."


def _text(result: str) -> dict:
    return {"content": [{"type": "text", "text": result}]}


def build_crew_server(bus: Bus, run_id: str, agent_name: str) -> McpSdkServerConfig:
    """Bind the crew tools to (bus, run, agent) — sender identity is structural."""

    @tool(
        "send_message",
        "Send a message to another crew agent. This is the ONLY way to hand off work.",
        {"to": str, "kind": str, "subject": str, "body": str},
    )
    async def send_message(args: dict) -> dict:
        return _text(await send_message_impl(bus, run_id, agent_name, args))

    @tool(
        "ask_human",
        "Ask the human operator clarifying questions (architect only, once, at kickoff).",
        {"questions": str},
    )
    async def ask_human(args: dict) -> dict:
        return _text(await ask_human_impl(bus, run_id, agent_name, args))

    @tool(
        "finish",
        "Declare the run complete with a final summary (manager only).",
        {"summary": str},
    )
    async def finish(args: dict) -> dict:
        return _text(await finish_impl(bus, run_id, agent_name, args))

    return create_sdk_mcp_server(name="crew", tools=[send_message, ask_human, finish])
