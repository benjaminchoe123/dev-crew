"""Scripted agents: full crew behavior with zero API calls and zero dollars."""

from __future__ import annotations

from collections.abc import Callable

from crew.bus import Bus, Msg


class FakeAgent:
    def __init__(
        self,
        name: str,
        bus: Bus,
        run_id: str,
        script: list[Callable[[list[Msg]], None]],
        cost_per_turn: float = 0.10,
    ) -> None:
        self.name = name
        self._bus = bus
        self._run_id = run_id
        self._script = list(script)
        self._cost = cost_per_turn

    async def run_turn(self, inbox: list[Msg]) -> float:
        if self._script:
            action = self._script.pop(0)
            action(inbox)
        return self._cost
