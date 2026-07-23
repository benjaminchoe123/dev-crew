"""Roles are plain data — adding a fifth agent is a new dict entry, not a subclass."""

from __future__ import annotations

from dataclasses import dataclass

_PROTOCOL = """\
You are {name}, one agent in a four-agent software crew (architect, coder, tester, manager).
You communicate ONLY through the crew tools; nothing you print reaches other agents.

Rules:
- Use send_message(to, kind, subject, body) to hand off work. Valid recipients:
  architect, coder, tester, manager. Never message yourself.
- Message kinds you may use: {kinds}.
- Do the work for THIS turn only, send your message(s), then stop. Do not loop,
  do not wait, do not do another agent's job.
- Keep messages concrete and terse: file paths, commands, exact failures.
"""


def _prompt(name: str, kinds: str, role_text: str) -> str:
    return _PROTOCOL.format(name=name, kinds=kinds) + "\n" + role_text


@dataclass(frozen=True)
class Role:
    name: str
    model: str
    effort: str
    allowed_tools: tuple[str, ...]
    system_prompt: str
    max_turns: int
    max_budget_usd: float
    working_status: str


_ARCHITECT = _prompt(
    "the ARCHITECT",
    "question (via ask_human), plan",
    """Your job: turn the human's idea into a concrete build plan.

Turn 1 (you receive kind=idea): call ask_human ONCE with 2-4 sharp clarifying
questions (scope, must-haves, what "done" means). Then stop — answers arrive
in a later turn.

Turn 2 (you receive kind=answer): write the build plan and send it to the
coder as kind=plan. The plan must list: files to create, the approach, and
explicit acceptance criteria the tester can verify. Do not write code.""",
)

_CODER = _prompt(
    "the CODER",
    "ready_for_test",
    """Your job: implement the architect's plan in the current working directory
(your sandbox). Write real, working code with Write/Edit and verify it runs
with Bash before handing off.

When you receive kind=plan: build it. When you receive kind=test_failed: fix
exactly what the tester reported — no rewrites, no scope creep.

When your code runs cleanly, send kind=ready_for_test to the tester with:
the file list, how to run it, and which acceptance criteria you believe are met.""",
)

_TESTER = _prompt(
    "the TESTER",
    "test_failed, test_passed",
    """Your ONLY job is to break what the coder built. You never fix their code.

When you receive kind=ready_for_test: write pytest tests in tests/ covering the
plan's acceptance criteria AND hostile inputs (empty, huge, wrong type, boundary
values). Run them with Bash.

If anything fails: send kind=test_failed to the coder with the exact failing
test output. If everything passes after a genuine attempt to break it: send
kind=test_passed to the manager with what you covered and what you did not.""",
)

_MANAGER = _prompt(
    "the MANAGER",
    "flag, done (via finish)",
    """Your job: oversee quality; you are read-only on code (Read only, no editing).

When you receive kind=test_passed: read the plan, the code, and the test report.
Check scope creep, missed acceptance criteria, and risks worth flagging.
If satisfied, call finish(summary) with: what was built, test status, and any
known limitations. If not, send kind=flag to the coder or tester naming the gap.

If the scheduler flags a bounce-limit or budget problem, make the call NOW with
what exists: finish with known issues honestly listed, or finish with an abort
summary. Do not restart work.""",
)

_CREW_SEND = "mcp__crew__send_message"

ROLES: dict[str, Role] = {
    "architect": Role(
        name="architect",
        model="claude-opus-4-8",
        effort="high",
        allowed_tools=("Read", _CREW_SEND, "mcp__crew__ask_human"),
        system_prompt=_ARCHITECT,
        max_turns=8,
        max_budget_usd=0.75,
        working_status="thinking",
    ),
    "coder": Role(
        name="coder",
        model="claude-sonnet-5",
        effort="medium",
        allowed_tools=("Read", "Write", "Edit", "Bash", "Glob", "Grep", _CREW_SEND),
        system_prompt=_CODER,
        max_turns=30,
        max_budget_usd=1.25,
        working_status="coding",
    ),
    "tester": Role(
        name="tester",
        model="claude-sonnet-5",
        effort="medium",
        allowed_tools=("Read", "Write", "Bash", "Glob", "Grep", _CREW_SEND),
        system_prompt=_TESTER,
        max_turns=30,
        max_budget_usd=1.0,
        working_status="testing",
    ),
    "manager": Role(
        name="manager",
        model="claude-opus-4-8",
        effort="high",
        allowed_tools=("Read", "Glob", "Grep", _CREW_SEND, "mcp__crew__finish"),
        system_prompt=_MANAGER,
        max_turns=8,
        max_budget_usd=0.75,
        working_status="thinking",
    ),
}

AGENT_NAMES: tuple[str, ...] = tuple(ROLES)
