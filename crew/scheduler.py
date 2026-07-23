"""The turn loop and every guard. An agent runs when it has unread mail."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import anyio

from crew.bus import Bus


@dataclass
class RunResult:
    status: str  # finished | turn_cap | budget_closed | stalled
    total_cost_usd: float
    agent_turns: int


class Scheduler:
    def __init__(
        self,
        bus: Bus,
        run_id: str,
        agents: dict[str, object],
        *,
        turn_cap: int = 24,
        budget_usd: float = 5.0,
        brake_after: int = 3,
        human_input: Callable[[str], str] | None = None,
        on_round: Callable[[int, float], None] | None = None,
    ) -> None:
        self._bus = bus
        self._run_id = run_id
        self._agents = agents
        self._turn_cap = turn_cap
        self._budget = budget_usd
        self._brake_after = brake_after
        self._human_input = human_input or (lambda q: input(f"\n[crew] {q}\n> "))
        self._on_round = on_round or (lambda _round, _cost: None)

    async def run(self) -> RunResult:
        bus, run_id = self._bus, self._run_id
        cost = 0.0
        turns = 0
        round_no = 0
        braked = False
        budget_flagged = False
        manager_turns_after_budget = 0

        while True:
            round_no += 1

            if bus.messages(run_id, kind="done"):
                return RunResult("finished", cost, turns)

            # Human-in-the-loop: answer any pending questions.
            for name in self._agents:
                if bus.get_status(name) == "awaiting_human":
                    questions = bus.messages(run_id, kind="question")
                    mine = [q for q in questions if q.sender == name]
                    answer = self._human_input(mine[-1].body if mine else "(no question)")
                    bus.append(
                        run_id=run_id, sender="user", recipient=name,
                        kind="answer", subject="answers", body=answer,
                    )
                    bus.set_status(name, "idle")

            # Manager brake: too many test_failed bounces -> force a call.
            if not braked and bus.count_kind(run_id, "test_failed") >= self._brake_after:
                braked = True
                bus.append(
                    run_id=run_id, sender="scheduler", recipient="manager",
                    kind="flag", subject="bounce limit reached",
                    body=(
                        f"{bus.count_kind(run_id, 'test_failed')} test_failed bounces. "
                        "Review now: finish with known issues, or abort with a summary."
                    ),
                )

            # Budget guard.
            if not budget_flagged and cost >= self._budget:
                budget_flagged = True
                bus.append(
                    run_id=run_id, sender="scheduler", recipient="manager",
                    kind="flag", subject="budget exceeded",
                    body=f"Run cost ${cost:.2f} >= budget ${self._budget:.2f}. "
                         "Finish immediately with whatever exists.",
                )

            runnable = [
                name
                for name, _agent in self._agents.items()
                if bus.get_status(name) not in ("done", "awaiting_human")
                and bus.unread_for(run_id, name)
                and not (budget_flagged and name != "manager")
            ]

            if not runnable:
                if any(bus.get_status(n) == "awaiting_human" for n in self._agents):
                    continue  # answered next round
                return RunResult("stalled", cost, turns)

            if turns + len(runnable) > self._turn_cap:
                return RunResult("turn_cap", cost, turns)

            if budget_flagged:
                manager_turns_after_budget += 1
                if manager_turns_after_budget > 3:
                    return RunResult("budget_closed", cost, turns)

            costs: dict[str, float] = {}

            async def one_turn(name: str, results: dict[str, float]) -> None:
                inbox = bus.unread_for(run_id, name)
                if not inbox:
                    results[name] = 0.0
                    return
                bus.advance_cursor(name, inbox[-1].id)
                results[name] = await self._agents[name].run_turn(inbox)

            async with anyio.create_task_group() as tg:
                for name in runnable:
                    tg.start_soon(one_turn, name, costs)

            turns += len(runnable)
            cost += sum(costs.values())
            self._on_round(round_no, cost)
