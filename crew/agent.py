"""One agent = one role + one SDK query per turn."""

from __future__ import annotations

from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKError, ResultMessage, query

from crew.bus import Bus, Msg
from crew.roles import Role
from crew.tools import build_crew_server


def build_prompt(history: list[Msg], inbox: list[Msg]) -> str:
    """Stable conversation prefix + volatile unread suffix.

    `history` is everything the agent is party to (from the bus). The unread
    `inbox` is the tail of that history; we drop it from the context section so
    it isn't duplicated, keeping the context a byte-stable, cacheable prefix and
    the unread a clearly-marked action list.
    """
    unread_ids = {m.id for m in inbox}
    context = [m for m in history if m.id not in unread_ids]
    lines = ["Conversation so far (context, oldest first):"]
    lines += [m.to_prompt() for m in context] or ["(none yet)"]
    lines += ["", "New messages addressed to you — act on these now:"]
    lines += [m.to_prompt() for m in inbox]
    return "\n".join(lines)


def build_options(role: Role, bus: Bus, run_id: str, workspace: Path) -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        model=role.model,
        effort=role.effort,
        system_prompt=role.system_prompt,
        cwd=str(workspace),
        allowed_tools=list(role.allowed_tools),
        mcp_servers={"crew": build_crew_server(bus, run_id, role.name)},
        setting_sources=[],  # isolation: no user/project CLAUDE.md or settings
        permission_mode="bypassPermissions",  # sandbox dir; see spec Windows caveat
        max_turns=role.max_turns,
        max_budget_usd=role.max_budget_usd,
    )


class CrewAgent:
    def __init__(self, role: Role, bus: Bus, run_id: str, workspace: Path) -> None:
        self.role = role
        self.name = role.name
        self._bus = bus
        self._run_id = run_id
        self._workspace = workspace

    async def run_turn(self, inbox: list[Msg]) -> float:
        bus = self._bus
        bus.set_status(self.name, self.role.working_status)
        cost = 0.0
        try:
            options = build_options(self.role, bus, self._run_id, self._workspace)
            prompt = build_prompt(bus.history_for(self._run_id, self.name), inbox)
            async for message in query(prompt=prompt, options=options):
                if isinstance(message, ResultMessage) and message.total_cost_usd:
                    cost = message.total_cost_usd
        except ClaudeSDKError as exc:
            bus.append(
                run_id=self._run_id, sender=self.name, recipient="manager",
                kind="flag", subject=f"{self.name} turn failed",
                body=f"{type(exc).__name__}: {exc}",
            )
        finally:
            # Tools may have moved status to awaiting_human/done — don't clobber.
            if bus.get_status(self.name) == self.role.working_status:
                bus.set_status(self.name, "idle")
        return cost
