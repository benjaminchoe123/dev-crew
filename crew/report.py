"""Write a run record into the Obsidian vault."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from crew.bus import Bus
from crew.scheduler import RunResult

_FRONTMATTER = """---
title: Crew Runs
type: resource
tags: [resource, ai, agents, dev-crew]
created: {today}
updated: {today}
---

# Crew Runs

One section per dev-crew run, appended by crew/report.py.
"""


def write_run_record(
    bus: Bus, run_id: str, result: RunResult, workspace: Path, vault_dir: Path
) -> Path:
    out = vault_dir / "03-resources" / "Crew-Runs.md"
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    if not out.exists():
        out.write_text(_FRONTMATTER.format(today=today), encoding="utf-8")

    done = bus.messages(run_id, kind="done")
    summary = done[-1].body if done else "(no manager summary — run did not finish)"
    flags = bus.messages(run_id, kind="flag")
    flag_lines = "".join(f"\n- `{f.sender}`: {f.subject}" for f in flags) or "\n- none"

    section = (
        f"\n\n## Run {run_id} — {today}\n\n"
        f"- **Status:** {result.status}\n"
        f"- **Cost:** ${result.total_cost_usd:.2f} · **Agent turns:** {result.agent_turns}\n"
        f"- **Workspace:** `{workspace}`\n"
        f"- **Flags:**{flag_lines}\n\n"
        f"**Manager summary:** {summary}\n"
    )
    with out.open("a", encoding="utf-8") as fh:
        fh.write(section)
    return out
