"""CLI: python -m crew.run "<idea>" — seeds the bus, runs the crew, writes the record."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import anyio
from rich.console import Console
from rich.table import Table

from crew.agent import CrewAgent
from crew.bus import Bus
from crew.report import write_run_record
from crew.roles import AGENT_NAMES, ROLES
from crew.scheduler import Scheduler
from crew.workspace import create_workspace, new_run_id

console = Console()


def build_run(
    idea: str, *, base_dir: Path, vault_dir: Path, budget: float, turn_cap: int
) -> tuple[Bus, Scheduler, str, Path]:
    data_dir = base_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    bus = Bus(data_dir / "bus.db")
    run_id = new_run_id()
    workspace = create_workspace(base_dir / "runs", run_id)
    bus.append(
        run_id=run_id, sender="user", recipient="architect",
        kind="idea", subject="new idea", body=idea,
    )
    agents = {
        name: CrewAgent(ROLES[name], bus, run_id, workspace) for name in AGENT_NAMES
    }

    def on_round(round_no: int, cost: float) -> None:
        table = Table(title=f"round {round_no} · ${cost:.2f}")
        table.add_column("agent")
        table.add_column("status")
        for name in AGENT_NAMES:
            table.add_row(name, bus.get_status(name))
        console.print(table)

    sched = Scheduler(
        bus, run_id, agents, turn_cap=turn_cap, budget_usd=budget, on_round=on_round
    )
    return bus, sched, run_id, workspace


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the dev crew on an idea.")
    parser.add_argument("idea")
    parser.add_argument("--budget", type=float, default=5.0)
    parser.add_argument("--turn-cap", type=int, default=24)
    parser.add_argument("--vault", default=None)
    args = parser.parse_args()

    vault = Path(args.vault or os.environ.get("CREW_VAULT_DIR", r"C:\Claude\Brain"))
    base = Path(__file__).resolve().parent.parent

    bus, sched, run_id, workspace = build_run(
        args.idea, base_dir=base, vault_dir=vault,
        budget=args.budget, turn_cap=args.turn_cap,
    )
    console.print(f"[bold]run {run_id}[/] · sandbox {workspace}")
    result = anyio.run(sched.run)
    record = write_run_record(bus, run_id, result, workspace, vault)
    console.print(
        f"[bold]{result.status}[/] · ${result.total_cost_usd:.2f} · "
        f"{result.agent_turns} turns · record: {record}"
    )
    return 0 if result.status == "finished" else 1


if __name__ == "__main__":
    raise SystemExit(main())
