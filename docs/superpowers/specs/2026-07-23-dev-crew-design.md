# Dev Crew — Design Spec

**Status:** draft for review · **Date:** 2026-07-23 · **Sub-project:** runtime (sub-project 1 of 2)

## Context

Big Ben wants to build autonomous AI agents that "do work and communicate on their own,"
and watch them do it in a visual mission-control room. The concrete first build is a
**software dev crew**: drop in an idea, and four agents — Architect, Coder, Tester, Manager —
plan it, build it, try to break it, and sign off, mostly unattended. The stated meta-goal is
learning agent design deliberately, so the design favors legible mechanisms over cleverness.

The overall effort is two sub-projects that meet at one seam:
1. **The crew runtime** (this spec) — the agents, their message bus, and the scheduler.
2. **The mission-control GUI** (later, its own spec) — an Obsidian plugin that renders the bus.

They connect only through the bus. This spec covers the runtime, and treats the GUI as a set
of forward-compatibility constraints the runtime must satisfy — nothing more.

Runtime target: **Claude Agent SDK, Python 3.12**, at `C:\Claude\research-crew\`. Zero-config
auth is confirmed working (the SDK inherits the Claude Code login). SDK is `claude-agent-sdk
0.2.126`.

## Goals

- Four agents that communicate agent-to-agent over a shared log and converge on working code.
- One human touch-point: the Architect asks clarifying questions at kickoff, then the crew
  runs unattended.
- Every run is legible, replayable, and bounded in cost.
- The bus is structured so the future GUI is a read-only renderer over it — no rewrite.

## Non-goals (explicitly out of scope for this spec)

- The mission-control GUI (sub-project 2).
- Working inside real/existing projects — the crew builds only in an isolated sandbox.
- Multi-run memory or a persistent agent "org" — each run is self-contained.
- Human steering mid-run beyond the kickoff questions.

## Architecture

The **message bus is the single source of truth.** Agents don't call each other; they append
messages to the bus and read messages addressed to them. The scheduler decides who runs next
purely from the bus. The GUI (later) reads the same bus. There is no second event system.

```
run.py ──▶ Scheduler ──▶ Agent ×4 ──▶ Claude Agent SDK (query / tools)
              │             │
              └──────┬──────┘
                     ▼
               Bus (SQLite, append-only)
                     │
              ┌──────┴───────┐
              ▼              ▼
        terminal view   Obsidian GUI (sub-project 2)
        (rich, phase 1)
```

## Components

### 1. Bus — `crew/bus.py`

SQLite, append-only. Two tables.

- **`messages`** (never updated or deleted — this is what makes runs replayable):
  `id INTEGER PRIMARY KEY AUTOINCREMENT`, `run_id`, `ts`, `sender`, `recipient`, `thread_id`,
  `kind` (e.g. `plan`, `ready_for_test`, `test_failed`, `test_passed`, `question`, `answer`,
  `flag`, `done`), `body`.
- **`agent_state`**: `name`, `status` (`idle` / `thinking` / `coding` / `testing` /
  `awaiting_human` / `done`), `updated_at`. Mutable; the one place the GUI reads "what is each
  agent doing right now."

The bus lives **outside** the run sandbox so a Coder's file tools can never touch it.

**Determinism is a cost requirement, not a nicety.** Message rows are serialized into agent
prompts with sorted keys and no timestamps in the cached prefix — otherwise prompt caching
(the crew's whole cost model) silently breaks. See Cost Controls.

### 2. Roles — `crew/roles.py`

Roles are plain data, not subclasses. Adding a fifth agent is a dict entry.

| Agent | Model | Tools | Purpose |
|---|---|---|---|
| Architect | `claude-opus-4-8` | read, `ask_human`, `send_message` | Reads the idea, asks the human 2–4 questions, waits, writes the build plan, hands it to the Coder |
| Coder | `claude-sonnet-5` | read, write, edit, bash, `send_message` | Implements the plan in the sandbox; pings the Tester when ready |
| Tester | `claude-sonnet-5` | read, write, bash, `send_message` | *Only* breaks things — writes tests, runs them, hunts edge cases; bounces failures to the Coder, "clean" to the Manager |
| Manager | `claude-opus-4-8` | read, `send_message`, `finish` | Overseer/quality gate; flags risk & scope creep; makes the ship/not-yet call; is the brake on the Tester↔Coder loop. **Read-only on code.** |

Each role entry: `name`, `model`, `effort`, `allowed_tools`, `system_prompt`. One model per
agent for the whole run (caches are model-scoped).

### 3. Agent — `crew/agent.py`

One `Agent` class wrapping an SDK session. Its turn:

1. Read unread inbox messages from the bus (recipient == self).
2. Set `agent_state.status` to its working state.
3. Call `claude_agent_sdk.query(prompt=<serialized inbox>, options=ClaudeAgentOptions(...))`.
4. Its tool calls (`send_message`, `ask_human`, `finish`, plus built-in file/bash) become new
   bus rows / state changes.
5. Set status back to `idle` (or `awaiting_human` / `done`).

Grounded in the real SDK surface (verified): `ClaudeAgentOptions` carries `model`, `cwd`
(sandbox scoping), `allowed_tools` / `disallowed_tools` (Coder vs Tester capabilities),
`system_prompt`, `max_turns`, `max_budget_usd` (a built-in per-query cost cap — used as a
guard), `betas`, and `tools` (custom in-process tools).

### 4. Custom tools — `crew/tools.py`

`send_message`, `ask_human`, and `finish` are custom SDK tools built with the SDK's `tool`
decorator + `create_sdk_mcp_server` (verified exports). Communication is *just tool use*, so
the SDK's tool loop does the plumbing and every message is a structured object (sender /
recipient / thread) — exactly the shape the GUI needs to animate one agent contacting another.

- `send_message(to, kind, subject, body)` → append a `messages` row.
- `ask_human(questions)` → append a `question` row, set status `awaiting_human`, block that
  agent until an `answer` row appears. **The only non-autonomous point.**
- `finish(summary)` → mark the run complete (Manager only).

File tools (read/write/edit) and `bash` are the SDK built-ins, scoped to the sandbox via `cwd`
and gated per-agent via `allowed_tools`.

### 5. Scheduler — `crew/scheduler.py`

The turn loop and every guard.

- **Runnable rule:** an agent is runnable when it has unread inbox messages. No messages → no
  work → the run drains naturally. Runnable agents execute concurrently.
- **Termination:** `finish()` is called, or nothing is runnable, or a hard guard trips.
- **Guards:**
  - Global **turn cap** and **token/cost budget** (the latter partly via `max_budget_usd` per
    query, plus a run-level tally from each `ResultMessage.total_cost_usd`).
  - **No self-messages, no duplicate sends** — the two cheapest ways a crew wastes money.
  - **Manager brake:** after *N* Tester↔Coder bounce rounds on the same thread, the scheduler
    force-wakes the Manager to make a real call — ship-with-known-issues, escalate to the
    human, or abort. The role Big Ben asked for *is* the governor on the riskiest loop.
  - **Budget-exceeded** forces the Manager to close out with whatever exists, rather than the
    run dying with nothing.

### 6. Workspace — `crew/workspace.py`

Each run builds in `runs/<run_id>/`. Coder/Tester tools are `cwd`-scoped there and cannot
reach the bus DB or the user's real projects. Garbage-collected on request, not automatically
(a failed run is worth inspecting).

### 7. Output — `crew/report.py`

On `finish()`, the Manager's summary + a pointer to the run's sandbox are written to the vault
as a run record (`Brain/03-resources/` or a dedicated runs log — TBD in the plan).

## Data flow — one run

1. `run.py "idea"` → seeds a `messages` row addressed to the Architect.
2. Architect runs → `ask_human(questions)` → status `awaiting_human`, run blocks.
3. Big Ben answers in the terminal → `answer` row → Architect resumes → writes `plan` to Coder.
4. Coder runs → writes files in the sandbox → `ready_for_test` to Tester.
5. Tester runs → writes/runs tests → `test_failed` to Coder **or** `test_passed` to Manager.
6. Loop 4–5 until pass, or the Manager brake trips after *N* rounds.
7. Manager runs → flags anything, makes the call → `finish(summary)`.
8. Scheduler sees no runnable agents / `finish` → writes the run record, exits.

## Cost controls

Cost is a first-class design constraint (see `[[Saving-Tokens-and-Cost]]`), because a naive
crew is 5–10× more expensive than a careful one.

- **Prompt caching is the whole ballgame** — each agent's stable system prompt sits first, the
  volatile inbox last, so the growing history is a cacheable prefix at ~0.1× on re-reads. This
  is why the bus serializes deterministically (sorted keys, no timestamps in the prefix).
- **One model per agent** — switching models mid-run throws the cache away.
- **`effort` per role** — judgment roles (Architect, Manager) at `high`; Coder/Tester at
  `medium`, dialed by observation.
- **Task budget / `max_budget_usd`** — a ceiling the loop respects, pairing with the Manager
  brake so the Tester↔Coder cycle can't run up the bill.

Estimated cost with caching on: **~$0.50–$2 per medium-complexity run.** Web search barely
factors in (the dev crew doesn't browse).

## Error handling

- **Agent/query failure** (`ClaudeSDKError` subclasses: CLI-not-found, process, auth) → log to
  the bus as a `flag`, surface to the Manager; don't crash the run.
- **Tool failure** (a bash command errors, a test file won't run) → returned to the calling
  agent as a normal tool result so it can adapt, exactly as the SDK's loop expects.
- **Runaway loop** → the turn cap and Manager brake catch it; budget-exceeded forces a graceful
  close.
- **Sandbox containment** → `cwd` scoping + per-role `allowed_tools` + role prompts +
  turn/budget caps. NOTE (Windows): the SDK's OS-level bash sandboxing is macOS/Linux
  only, so Bash is not hard-jailed here — the Coder/Tester run with bypassPermissions
  inside a throwaway dir on a personal machine. Acceptable for learning; revisit
  (WSL/container) before pointing the crew at anything real.

## Testing

- **`FakeAgent`** returns scripted tool calls instead of hitting the API. The scheduler, bus,
  termination rules, and every guard are testable **with zero API calls and zero dollars** —
  which matters most for the failure mode "runaway loop burns budget."
- Then one real end-to-end smoke run on a trivial idea ("build a FizzBuzz with tests"), asserting
  the full Architect→Coder→Tester→Manager path and a bounded cost.
- Toolchain matches the pipeline: `pytest`, `ruff` (line-length 100, `F,E,W,I,B,UP`).

## GUI seam (forward-compatibility constraints)

The runtime must guarantee, so sub-project 2 is a pure renderer:
- `messages` is append-only and pollable by `id` (`SELECT * FROM messages WHERE id > ?`).
- `agent_state.status` always reflects current activity, including `awaiting_human`.
- Every message carries `sender` + `recipient` (a walk animation, station to station) and
  `thread_id` (grouping a conversation).
- No push, no IPC — the GUI polls the SQLite file the crew writes.

## Open questions (non-blocking)

- The exact Manager-brake threshold *N* (start at 3, tune).
- Whether the Claude Code subscription's terms cover programmatic Agent SDK use for anything
  *shipped* (see `[[Making-Money-With-Claude-Code]]`) — irrelevant to building/learning.
- Per-agent control of inherited global CLAUDE.md context (the smoke test got greeted as "Big
  Ben," so agents inherit it unless scoped via `system_prompt` / settings sources).

## Rough build order (detailed sequencing → implementation plan)

bus → roles → custom tools → agent → scheduler + guards → terminal (`rich`) view → smoke run.
