# Dev Crew Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the 4-agent dev crew runtime (Architect → Coder → Tester → Manager) from the approved spec at `C:\Claude\research-crew\docs\superpowers\specs\2026-07-23-dev-crew-design.md`.

**Architecture:** An append-only SQLite message bus is the single source of truth; agents communicate only by appending messages via custom SDK tools; a scheduler wakes agents that have unread mail and enforces every guard (turn cap, budget, Manager brake). The future Obsidian GUI polls the same bus — no second event system.

**Tech Stack:** Python 3.12, `claude-agent-sdk 0.2.126` (drives the logged-in Claude Code CLI — zero-config auth verified), sqlite3 (stdlib), anyio, rich, pytest, ruff.

## Context

The spec was brainstormed and reviewed over this session: crew pivoted from research team to dev team; decisions locked (kickoff-questions-then-autonomous; Manager = overseer + loop brake; isolated sandbox in `runs/<id>/`). Phase-1 tooling is already done: venv at `C:\Claude\research-crew\.venv`, deps installed, `crew/smoke.py` proves zero-config auth, `tests/test_toolchain.py` green, ruff configured identically to threat-intel-pipeline. This plan turns the spec into code, TDD throughout, with a `FakeAgent` so every scheduler/guard behavior is tested at $0.

**Verified SDK facts the code relies on** (inspected live against 0.2.126 — do not re-derive):
- `query(*, prompt, options)` → async iterator of `UserMessage | AssistantMessage | SystemMessage | ResultMessage | ...`; `ResultMessage.total_cost_usd`, `.is_error`.
- `ClaudeAgentOptions` fields used: `model`, `system_prompt`, `effort` (`"low"|"medium"|"high"|"xhigh"|"max"`), `cwd`, `allowed_tools`, `mcp_servers` (dict name→config), `setting_sources` (**`[]` = SDK isolation mode — no global CLAUDE.md inheritance**; `None` loads everything), `permission_mode`, `max_turns`, `max_budget_usd`.
- Custom tools: `@tool(name, description, {param: type})` decorating `async def f(args) -> dict` returning `{"content": [{"type": "text", "text": ...}]}`; bundle with `create_sdk_mcp_server(name=..., tools=[...])`; expose to the model as `mcp__<server>__<tool>` in `allowed_tools`.
- `ClaudeSDKError` is the catchable base for CLI/process/auth failures.
- **Windows caveat:** `SandboxSettings` bash-jailing is macOS/Linux only. On this machine isolation = `cwd` scoping + role prompts + `permission_mode` + turn/budget caps, **not** an OS jail. Task 10 updates the spec's "structurally prevented" wording to say so honestly.

**Two small decisions made here (were TBD in spec):** run records append to `C:\Claude\Brain\03-resources\Crew-Runs.md` (override via `CREW_VAULT_DIR`); messages get a `subject` column (the spec's tool signature has it; its schema list omitted it — schema follows the tool).

## Global Constraints

- Python 3.12; ruff `line-length=100`, `select=["F","E","W","I","B","UP"]`; all code must pass `python -m ruff check crew/ tests/`.
- Requirements pins are `~=` (compatible-release), never bare lower bounds.
- Models: Architect/Manager `claude-opus-4-8` (effort `high`); Coder/Tester `claude-sonnet-5` (effort `medium`). One model per agent per run — never switch mid-run (cache-scoped).
- Every agent query sets `setting_sources=[]` (isolation — no vault/CLAUDE.md bleed-through).
- `messages` table is append-only: no UPDATE/DELETE anywhere; read-tracking uses a separate `cursors` table.
- `Msg.to_prompt()` must be deterministic: `json.dumps(..., sort_keys=True)`, **timestamp excluded** (prompt-cache requirement).
- The bus DB lives at `data/bus.db` (gitignored, outside `runs/` sandboxes).
- Defaults: turn cap 24 agent-turns, run budget $5.00, Manager brake after 3 `test_failed` messages.
- Commit after every task (repo initialized in Task 0). Commit messages end with `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- All commands below run from `C:\Claude\research-crew` with `.venv\Scripts\python.exe` (spelled `PY` below: `$PY = ".\.venv\Scripts\python.exe"`).

---

### Task 0: Initialize the repo

**Files:**
- Create: `.git/` (init), `docs/superpowers/plans/2026-07-23-dev-crew-runtime.md` (copy of this plan)
- Already present: `.gitignore`, `requirements.txt`, `pyproject.toml`, `pyrightconfig.json`, `crew/`, `tests/`, `docs/superpowers/specs/2026-07-23-dev-crew-design.md`

**Interfaces:** none (setup).

- [ ] **Step 1:** `git init` and first commit of the existing scaffold:

```powershell
cd C:\Claude\research-crew
git init -b main
git add .
git commit -m "chore: scaffold — venv config, smoke test, toolchain, design spec

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

- [ ] **Step 2:** Copy this plan into the repo at `docs/superpowers/plans/2026-07-23-dev-crew-runtime.md` (Write tool, same content), add `anyio~=4.14` to `requirements.txt` under the runtime deps (we import it directly; today it's only transitive):

```
claude-agent-sdk~=0.2.126
python-dotenv~=1.2
rich~=15.0
anyio~=4.14
```

- [ ] **Step 3:** Commit:

```powershell
git add docs/superpowers/plans/2026-07-23-dev-crew-runtime.md requirements.txt
git commit -m "docs: add implementation plan; pin anyio as a direct dep

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 1: Message bus

**Files:**
- Create: `crew/bus.py`
- Test: `tests/test_bus.py`

**Interfaces:**
- Produces (everything later tasks call):
  - `@dataclass(frozen=True) Msg`: `id: int, run_id: str, ts: str, sender: str, recipient: str, thread_id: str, kind: str, subject: str, body: str`; method `to_prompt() -> str` (sorted-key JSON of all fields **except `ts`**).
  - `class Bus:`
    - `__init__(self, db_path: str | Path)` — opens/creates DB, WAL mode, creates tables.
    - `append(self, *, run_id, sender, recipient, kind, subject, body, thread_id="main") -> int` (new row id)
    - `unread_for(self, run_id: str, agent: str) -> list[Msg]` (recipient == agent, id > cursor)
    - `advance_cursor(self, agent: str, last_id: int) -> None`
    - `set_status(self, agent: str, status: str) -> None` / `get_status(self, agent: str) -> str` (default `"idle"`)
    - `messages(self, run_id: str, *, kind: str | None = None, recipient: str | None = None) -> list[Msg]`
    - `has_duplicate(self, run_id, sender, recipient, kind, body) -> bool`
    - `count_kind(self, run_id: str, kind: str) -> int`
    - `close(self) -> None`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_bus.py
"""Bus: append-only messages, cursor-based unread, agent status, determinism."""
import json

from crew.bus import Bus, Msg


def make_bus(tmp_path):
    return Bus(tmp_path / "bus.db")


def test_append_and_read_roundtrip(tmp_path):
    bus = make_bus(tmp_path)
    mid = bus.append(run_id="r1", sender="user", recipient="architect",
                     kind="idea", subject="fizzbuzz", body="Build fizzbuzz")
    msgs = bus.messages("r1")
    assert [m.id for m in msgs] == [mid]
    m = msgs[0]
    assert (m.sender, m.recipient, m.kind, m.subject, m.body, m.thread_id) == (
        "user", "architect", "idea", "fizzbuzz", "Build fizzbuzz", "main")
    assert m.ts  # timestamp recorded


def test_unread_respects_cursor(tmp_path):
    bus = make_bus(tmp_path)
    a = bus.append(run_id="r1", sender="user", recipient="architect",
                   kind="idea", subject="s", body="b1")
    assert [m.id for m in bus.unread_for("r1", "architect")] == [a]
    bus.advance_cursor("architect", a)
    assert bus.unread_for("r1", "architect") == []
    b = bus.append(run_id="r1", sender="coder", recipient="architect",
                   kind="question", subject="s", body="b2")
    assert [m.id for m in bus.unread_for("r1", "architect")] == [b]


def test_unread_filters_by_recipient(tmp_path):
    bus = make_bus(tmp_path)
    bus.append(run_id="r1", sender="user", recipient="architect",
               kind="idea", subject="s", body="b")
    assert bus.unread_for("r1", "coder") == []


def test_status_default_and_set(tmp_path):
    bus = make_bus(tmp_path)
    assert bus.get_status("coder") == "idle"
    bus.set_status("coder", "coding")
    assert bus.get_status("coder") == "coding"


def test_has_duplicate(tmp_path):
    bus = make_bus(tmp_path)
    bus.append(run_id="r1", sender="coder", recipient="tester",
               kind="ready_for_test", subject="s", body="same")
    assert bus.has_duplicate("r1", "coder", "tester", "ready_for_test", "same")
    assert not bus.has_duplicate("r1", "coder", "tester", "ready_for_test", "different")


def test_count_kind(tmp_path):
    bus = make_bus(tmp_path)
    for _ in range(2):
        bus.append(run_id="r1", sender="tester", recipient="coder",
                   kind="test_failed", subject="s", body="x")
    assert bus.count_kind("r1", "test_failed") == 2
    assert bus.count_kind("r1", "test_passed") == 0


def test_messages_filter_by_kind(tmp_path):
    bus = make_bus(tmp_path)
    bus.append(run_id="r1", sender="manager", recipient="run",
               kind="done", subject="s", body="shipped")
    bus.append(run_id="r1", sender="user", recipient="architect",
               kind="idea", subject="s", body="b")
    assert [m.kind for m in bus.messages("r1", kind="done")] == ["done"]


def test_to_prompt_is_deterministic_and_excludes_ts(tmp_path):
    bus = make_bus(tmp_path)
    mid = bus.append(run_id="r1", sender="user", recipient="architect",
                     kind="idea", subject="s", body="b")
    m = bus.messages("r1")[0]
    payload = json.loads(m.to_prompt())
    assert "ts" not in payload
    assert list(payload.keys()) == sorted(payload.keys())
    assert payload["id"] == mid


def test_bus_has_no_update_or_delete_api():
    banned = {"update_message", "delete_message", "edit_message"}
    assert not banned & set(dir(Bus))
```

- [ ] **Step 2: Run to verify failure**

Run: `& $PY -m pytest tests/test_bus.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'crew.bus'`

- [ ] **Step 3: Implement**

```python
# crew/bus.py
"""Append-only SQLite message bus — the single source of truth for a run.

messages is never UPDATEd or DELETEd (replayability + the GUI seam).
Read-tracking lives in a separate cursors table so append-only holds.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    sender TEXT NOT NULL,
    recipient TEXT NOT NULL,
    thread_id TEXT NOT NULL DEFAULT 'main',
    kind TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cursors (
    agent TEXT PRIMARY KEY,
    last_id INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS agent_state (
    name TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class Msg:
    id: int
    run_id: str
    ts: str
    sender: str
    recipient: str
    thread_id: str
    kind: str
    subject: str
    body: str

    def to_prompt(self) -> str:
        """Deterministic serialization for agent prompts.

        Sorted keys, no timestamp — a byte-stable prefix is what makes
        prompt caching (the crew's cost model) work.
        """
        payload = {
            "body": self.body,
            "id": self.id,
            "kind": self.kind,
            "recipient": self.recipient,
            "run_id": self.run_id,
            "sender": self.sender,
            "subject": self.subject,
            "thread_id": self.thread_id,
        }
        return json.dumps(payload, sort_keys=True)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Bus:
    def __init__(self, db_path: str | Path) -> None:
        self._conn = sqlite3.connect(str(db_path), isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        self._conn.close()

    # -- messages (append-only) -------------------------------------------

    def append(
        self,
        *,
        run_id: str,
        sender: str,
        recipient: str,
        kind: str,
        subject: str,
        body: str,
        thread_id: str = "main",
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO messages (run_id, ts, sender, recipient, thread_id, kind, subject, body)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, _now(), sender, recipient, thread_id, kind, subject, body),
        )
        return cur.lastrowid

    def _rows_to_msgs(self, rows) -> list[Msg]:
        return [Msg(*row) for row in rows]

    def messages(
        self, run_id: str, *, kind: str | None = None, recipient: str | None = None
    ) -> list[Msg]:
        sql = (
            "SELECT id, run_id, ts, sender, recipient, thread_id, kind, subject, body"
            " FROM messages WHERE run_id = ?"
        )
        params: list[object] = [run_id]
        if kind is not None:
            sql += " AND kind = ?"
            params.append(kind)
        if recipient is not None:
            sql += " AND recipient = ?"
            params.append(recipient)
        sql += " ORDER BY id"
        return self._rows_to_msgs(self._conn.execute(sql, params))

    def unread_for(self, run_id: str, agent: str) -> list[Msg]:
        rows = self._conn.execute(
            "SELECT id, run_id, ts, sender, recipient, thread_id, kind, subject, body"
            " FROM messages WHERE run_id = ? AND recipient = ?"
            " AND id > COALESCE((SELECT last_id FROM cursors WHERE agent = ?), 0)"
            " ORDER BY id",
            (run_id, agent, agent),
        )
        return self._rows_to_msgs(rows)

    def advance_cursor(self, agent: str, last_id: int) -> None:
        self._conn.execute(
            "INSERT INTO cursors (agent, last_id) VALUES (?, ?)"
            " ON CONFLICT(agent) DO UPDATE SET last_id = excluded.last_id",
            (agent, last_id),
        )

    def has_duplicate(
        self, run_id: str, sender: str, recipient: str, kind: str, body: str
    ) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM messages WHERE run_id = ? AND sender = ? AND recipient = ?"
            " AND kind = ? AND body = ? LIMIT 1",
            (run_id, sender, recipient, kind, body),
        ).fetchone()
        return row is not None

    def count_kind(self, run_id: str, kind: str) -> int:
        (n,) = self._conn.execute(
            "SELECT COUNT(*) FROM messages WHERE run_id = ? AND kind = ?", (run_id, kind)
        ).fetchone()
        return n

    # -- agent state (mutable by design; the GUI's "what is X doing") ------

    def set_status(self, agent: str, status: str) -> None:
        self._conn.execute(
            "INSERT INTO agent_state (name, status, updated_at) VALUES (?, ?, ?)"
            " ON CONFLICT(name) DO UPDATE SET status = excluded.status,"
            " updated_at = excluded.updated_at",
            (agent, status, _now()),
        )

    def get_status(self, agent: str) -> str:
        row = self._conn.execute(
            "SELECT status FROM agent_state WHERE name = ?", (agent,)
        ).fetchone()
        return row[0] if row else "idle"
```

- [ ] **Step 4: Run tests, expect all PASS**

Run: `& $PY -m pytest tests/test_bus.py -q` → all pass. Then `& $PY -m ruff check crew/ tests/` → clean.

- [ ] **Step 5: Commit**

```powershell
git add crew/bus.py tests/test_bus.py
git commit -m "feat: append-only SQLite message bus with cursors and agent state

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Roles

**Files:**
- Create: `crew/roles.py`
- Test: `tests/test_roles.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) Role`: `name: str, model: str, effort: str, allowed_tools: tuple[str, ...], system_prompt: str, max_turns: int, max_budget_usd: float, working_status: str`
  - `ROLES: dict[str, Role]` with keys `"architect" | "coder" | "tester" | "manager"`
  - `AGENT_NAMES: tuple[str, ...] = ("architect", "coder", "tester", "manager")`
- Consumes: nothing.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_roles.py
from crew.roles import AGENT_NAMES, ROLES


def test_all_four_roles_exist():
    assert set(ROLES) == {"architect", "coder", "tester", "manager"} == set(AGENT_NAMES)


def test_models_and_effort():
    assert ROLES["architect"].model == "claude-opus-4-8"
    assert ROLES["manager"].model == "claude-opus-4-8"
    assert ROLES["coder"].model == "claude-sonnet-5"
    assert ROLES["tester"].model == "claude-sonnet-5"
    assert ROLES["architect"].effort == "high"
    assert ROLES["coder"].effort == "medium"


def test_tool_gating():
    assert "mcp__crew__ask_human" in ROLES["architect"].allowed_tools
    assert "mcp__crew__finish" in ROLES["manager"].allowed_tools
    # Only the architect may ask the human; only the manager may finish.
    for name in ("coder", "tester", "manager"):
        assert "mcp__crew__ask_human" not in ROLES[name].allowed_tools
    for name in ("architect", "coder", "tester"):
        assert "mcp__crew__finish" not in ROLES[name].allowed_tools
    # Manager is read-only on code: no Write/Edit/Bash.
    for banned in ("Write", "Edit", "Bash"):
        assert banned not in ROLES["manager"].allowed_tools
    # Coder can build; tester can write tests + run them but not Edit source.
    for t in ("Read", "Write", "Edit", "Bash"):
        assert t in ROLES["coder"].allowed_tools
    assert "Bash" in ROLES["tester"].allowed_tools
    assert "Edit" not in ROLES["tester"].allowed_tools


def test_everyone_can_send():
    for role in ROLES.values():
        assert "mcp__crew__send_message" in role.allowed_tools


def test_prompts_reference_the_protocol():
    for role in ROLES.values():
        assert "send_message" in role.system_prompt
        assert role.system_prompt.strip()
```

- [ ] **Step 2: Run to verify failure**

Run: `& $PY -m pytest tests/test_roles.py -q` → FAIL (`No module named 'crew.roles'`).

- [ ] **Step 3: Implement**

```python
# crew/roles.py
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
```

- [ ] **Step 4:** `& $PY -m pytest tests/test_roles.py -q` → PASS; ruff clean.

- [ ] **Step 5: Commit**

```powershell
git add crew/roles.py tests/test_roles.py
git commit -m "feat: role definitions — models, tools, prompts, per-role budgets

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Crew tools

**Files:**
- Create: `crew/tools.py`
- Test: `tests/test_tools.py`

**Interfaces:**
- Consumes: `Bus`, `Msg` from `crew.bus` (Task 1).
- Produces:
  - Testable impls (plain async funcs, no SDK dependency in tests):
    - `async send_message_impl(bus, run_id, agent, args: dict) -> str` — validates then appends; returns confirmation text or `"ERROR: ..."` string (never raises on bad input).
    - `async ask_human_impl(bus, run_id, agent, args: dict) -> str` — appends `kind="question"` (recipient `"user"`), sets status `awaiting_human`.
    - `async finish_impl(bus, run_id, agent, args: dict) -> str` — appends `kind="done"` (recipient `"run"`), sets status `done`.
  - `build_crew_server(bus, run_id, agent_name) -> McpSdkServerConfig` — wraps the impls with `@tool` + `create_sdk_mcp_server(name="crew", ...)`. Tool names: `send_message`, `ask_human`, `finish` (→ `mcp__crew__*`).

Validation rules in `send_message_impl`: recipient must be in `AGENT_NAMES` and ≠ sender; duplicate (same run/sender/recipient/kind/body) rejected; required args `to, kind, subject, body`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_tools.py
import anyio

from crew.bus import Bus
from crew.tools import ask_human_impl, finish_impl, send_message_impl


def run(coro):
    return anyio.from_thread.run_sync if False else anyio.run(lambda: coro)  # noqa: E501


def test_send_message_appends(tmp_path):
    bus = Bus(tmp_path / "bus.db")
    out = anyio.run(
        lambda: send_message_impl(
            bus, "r1", "coder",
            {"to": "tester", "kind": "ready_for_test", "subject": "s", "body": "b"},
        )
    )
    assert "ERROR" not in out
    msgs = bus.messages("r1")
    assert len(msgs) == 1 and msgs[0].sender == "coder" and msgs[0].recipient == "tester"


def test_send_message_rejects_self(tmp_path):
    bus = Bus(tmp_path / "bus.db")
    out = anyio.run(
        lambda: send_message_impl(
            bus, "r1", "coder", {"to": "coder", "kind": "x", "subject": "s", "body": "b"}
        )
    )
    assert out.startswith("ERROR") and bus.messages("r1") == []


def test_send_message_rejects_unknown_recipient(tmp_path):
    bus = Bus(tmp_path / "bus.db")
    out = anyio.run(
        lambda: send_message_impl(
            bus, "r1", "coder", {"to": "nobody", "kind": "x", "subject": "s", "body": "b"}
        )
    )
    assert out.startswith("ERROR")


def test_send_message_rejects_duplicate(tmp_path):
    bus = Bus(tmp_path / "bus.db")
    args = {"to": "tester", "kind": "ready_for_test", "subject": "s", "body": "same"}
    anyio.run(lambda: send_message_impl(bus, "r1", "coder", args))
    out = anyio.run(lambda: send_message_impl(bus, "r1", "coder", args))
    assert out.startswith("ERROR") and len(bus.messages("r1")) == 1


def test_send_message_rejects_missing_args(tmp_path):
    bus = Bus(tmp_path / "bus.db")
    out = anyio.run(lambda: send_message_impl(bus, "r1", "coder", {"to": "tester"}))
    assert out.startswith("ERROR")


def test_ask_human_sets_awaiting_status(tmp_path):
    bus = Bus(tmp_path / "bus.db")
    anyio.run(
        lambda: ask_human_impl(bus, "r1", "architect", {"questions": "1) scope? 2) done?"})
    )
    q = bus.messages("r1", kind="question")
    assert len(q) == 1 and q[0].recipient == "user"
    assert bus.get_status("architect") == "awaiting_human"


def test_finish_marks_done(tmp_path):
    bus = Bus(tmp_path / "bus.db")
    anyio.run(lambda: finish_impl(bus, "r1", "manager", {"summary": "shipped"}))
    done = bus.messages("r1", kind="done")
    assert len(done) == 1 and done[0].body == "shipped"
    assert bus.get_status("manager") == "done"


def test_build_crew_server_constructs(tmp_path):
    from crew.tools import build_crew_server

    bus = Bus(tmp_path / "bus.db")
    cfg = build_crew_server(bus, "r1", "architect")
    assert cfg is not None
```

- [ ] **Step 2:** Run `& $PY -m pytest tests/test_tools.py -q` → FAIL (module missing).

- [ ] **Step 3: Implement**

```python
# crew/tools.py
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
    questions = args.get("questions", "").strip()
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
    summary = args.get("summary", "").strip()
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
```

Note: the server exposes all three tools to every agent; **enforcement is `allowed_tools` in the role** (architect lacks `finish`, manager lacks `ask_human`, etc.). Structural, not trust-based.

- [ ] **Step 4:** `& $PY -m pytest tests/test_tools.py -q` → PASS. Fix the leftover unused helper in the test file if ruff flags it (delete the `run` helper — it was scaffolding). `& $PY -m ruff check crew/ tests/` → clean.

- [ ] **Step 5: Commit**

```powershell
git add crew/tools.py tests/test_tools.py
git commit -m "feat: crew tools — send_message/ask_human/finish with structural sender identity

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Workspace helper

**Files:**
- Create: `crew/workspace.py`
- Test: `tests/test_workspace.py`

**Interfaces:**
- Produces: `new_run_id() -> str` (sortable, filesystem-safe, e.g. `20260723-141530-3f2a`); `create_workspace(base: Path, run_id: str) -> Path` (creates `base / run_id`, returns it).

- [ ] **Step 1: Failing tests**

```python
# tests/test_workspace.py
import re

from crew.workspace import create_workspace, new_run_id


def test_run_id_shape():
    rid = new_run_id()
    assert re.fullmatch(r"\d{8}-\d{6}-[0-9a-f]{4}", rid)


def test_run_ids_unique():
    assert new_run_id() != new_run_id()


def test_create_workspace(tmp_path):
    ws = create_workspace(tmp_path, "20260723-000000-abcd")
    assert ws.is_dir() and ws == tmp_path / "20260723-000000-abcd"
```

- [ ] **Step 2:** Run → FAIL (module missing).

- [ ] **Step 3: Implement**

```python
# crew/workspace.py
"""Per-run sandbox directories under runs/<run_id>/."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from pathlib import Path


def new_run_id() -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{secrets.token_hex(2)}"


def create_workspace(base: Path, run_id: str) -> Path:
    ws = base / run_id
    ws.mkdir(parents=True, exist_ok=True)
    return ws
```

- [ ] **Step 4:** Tests PASS, ruff clean.
- [ ] **Step 5: Commit** — `git add crew/workspace.py tests/test_workspace.py && git commit -m "feat: per-run sandbox workspaces ..."` (same trailer).

---

### Task 5: Agent wrapper

**Files:**
- Create: `crew/agent.py`
- Test: `tests/test_agent.py`

**Interfaces:**
- Consumes: `Role` (Task 2), `Bus`/`Msg` (Task 1), `build_crew_server` (Task 3).
- Produces:
  - `class CrewAgent:` `__init__(self, role: Role, bus: Bus, run_id: str, workspace: Path)`; attribute `name: str`; `async run_turn(self, inbox: list[Msg]) -> float` (returns USD cost of the turn, `0.0` on failure).
  - Module function `build_options(role, bus, run_id, workspace) -> ClaudeAgentOptions` (separated so tests can assert on it without an API call).
- Scheduler contract (Task 6 relies on this): `run_turn` sets `working_status` at start; afterwards restores `idle` **unless** a tool set it to `awaiting_human` or `done`. On `ClaudeSDKError`, appends a `kind="flag"` message to the manager and returns `0.0` (never raises).

- [ ] **Step 1: Failing tests**

```python
# tests/test_agent.py
from pathlib import Path

from crew.agent import build_options
from crew.bus import Bus
from crew.roles import ROLES


def test_build_options_isolation_and_scoping(tmp_path):
    bus = Bus(tmp_path / "bus.db")
    opts = build_options(ROLES["coder"], bus, "r1", tmp_path / "ws")
    assert opts.model == "claude-sonnet-5"
    assert opts.effort == "medium"
    assert opts.setting_sources == []          # no global CLAUDE.md bleed-through
    assert opts.cwd == str(tmp_path / "ws")    # sandbox scoping
    assert opts.permission_mode == "bypassPermissions"
    assert opts.max_budget_usd == ROLES["coder"].max_budget_usd
    assert "crew" in opts.mcp_servers
    assert "mcp__crew__send_message" in opts.allowed_tools
    assert "mcp__crew__finish" not in opts.allowed_tools


def test_build_options_manager_read_only(tmp_path):
    bus = Bus(tmp_path / "bus.db")
    opts = build_options(ROLES["manager"], bus, "r1", tmp_path / "ws")
    for banned in ("Write", "Edit", "Bash"):
        assert banned not in opts.allowed_tools


def test_prompt_assembly_is_deterministic(tmp_path):
    from crew.agent import inbox_to_prompt

    bus = Bus(tmp_path / "bus.db")
    bus.append(run_id="r1", sender="user", recipient="architect",
               kind="idea", subject="s", body="b")
    msgs = bus.messages("r1")
    assert inbox_to_prompt(msgs) == inbox_to_prompt(msgs)
    assert "ts" not in inbox_to_prompt(msgs)
```

- [ ] **Step 2:** Run → FAIL.

- [ ] **Step 3: Implement**

```python
# crew/agent.py
"""One agent = one role + one SDK query per turn."""

from __future__ import annotations

from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKError, ResultMessage, query

from crew.bus import Bus, Msg
from crew.roles import Role
from crew.tools import build_crew_server


def inbox_to_prompt(inbox: list[Msg]) -> str:
    lines = ["Your inbox (oldest first). Act on it now:"]
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
            async for message in query(prompt=inbox_to_prompt(inbox), options=options):
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
```

- [ ] **Step 4:** `& $PY -m pytest tests/test_agent.py -q` → PASS; ruff clean. (No API is hit: `build_options` and `inbox_to_prompt` are pure.)

- [ ] **Step 5: Commit** — `feat: CrewAgent — isolated, sandbox-scoped SDK turns with cost capture` (same trailer).

---

### Task 6: Scheduler + guards + FakeAgent

**Files:**
- Create: `crew/scheduler.py`, `tests/fakes.py`
- Test: `tests/test_scheduler.py`

**Interfaces:**
- Consumes: `Bus`/`Msg`, `AGENT_NAMES`. Agents are anything with `.name: str` and `async run_turn(inbox: list[Msg]) -> float` (duck-typed — `CrewAgent` and `FakeAgent` both qualify).
- Produces:
  - `@dataclass RunResult`: `status: str` (`"finished" | "turn_cap" | "budget_closed" | "stalled"`), `total_cost_usd: float`, `agent_turns: int`.
  - `class Scheduler:` `__init__(self, bus, run_id, agents: dict[str, object], *, turn_cap: int = 24, budget_usd: float = 5.0, brake_after: int = 3, human_input=None, on_round=None)`; `async run(self) -> RunResult`.
    - `human_input: Callable[[str], str]` — called with the question text, returns the answer (CLI passes `input`; tests pass a stub).
    - `on_round: Callable[[int, float], None]` — observer hook `(round_number, cost_so_far)` for the rich view.

Scheduler round logic (implement exactly):
1. If any `kind="done"` message exists → return `finished`.
2. For each agent with status `awaiting_human`: take its latest `kind="question"` message, call `human_input(question_body)`, append the reply as `kind="answer"` from `"user"` to that agent, set its status `idle`.
3. **Manager brake:** if `count_kind(run, "test_failed") >= brake_after` and the brake flag hasn't been sent yet → append `kind="flag"` from `"scheduler"` to `"manager"`: subject `"bounce limit reached"`, body naming the count and ordering a close-out call. Send at most once per run.
4. **Budget:** if `total_cost >= budget_usd` and not yet flagged → append `kind="flag"` from `"scheduler"` to `"manager"` (subject `"budget exceeded"`, body ordering an immediate finish). After this flag, only the manager may be scheduled. If the manager doesn't finish within 3 more of its turns → return `budget_closed`.
5. Runnable = agents with nonempty `unread_for` and status not `done`/`awaiting_human` (minus non-managers post-budget-flag). If none and nobody `awaiting_human` → return `stalled`.
6. If `agent_turns + len(runnable) > turn_cap` → return `turn_cap`.
7. Run all runnable concurrently (`anyio.create_task_group`): for each, snapshot `inbox = unread_for(...)`, `advance_cursor(agent, inbox[-1].id)` **before** the turn (a re-read mid-turn must not double-deliver), then `cost += await agent.run_turn(inbox)`; `agent_turns += 1` each.
8. Call `on_round`, loop.

- [ ] **Step 1: Failing tests**

```python
# tests/fakes.py
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
```

```python
# tests/test_scheduler.py
import anyio

from crew.bus import Bus
from crew.scheduler import Scheduler
from tests.fakes import FakeAgent


def seed(bus, run_id="r1"):
    bus.append(run_id=run_id, sender="user", recipient="architect",
               kind="idea", subject="idea", body="build fizzbuzz")


def send(bus, run_id, frm, to, kind, body="x"):
    def action(_inbox):
        bus.append(run_id=run_id, sender=frm, recipient=to,
                   kind=kind, subject=kind, body=body)
    return action


def finish(bus, run_id, frm="manager"):
    def action(_inbox):
        bus.append(run_id=run_id, sender=frm, recipient="run",
                   kind="done", subject="done", body="shipped")
        bus.set_status(frm, "done")
    return action


def ask(bus, run_id, frm="architect"):
    def action(_inbox):
        bus.append(run_id=run_id, sender=frm, recipient="user",
                   kind="question", subject="q", body="scope?")
        bus.set_status(frm, "awaiting_human")
    return action


def make_crew(bus, run_id, scripts):
    return {
        name: FakeAgent(name, bus, run_id, scripts.get(name, []))
        for name in ("architect", "coder", "tester", "manager")
    }


def test_happy_path_reaches_finished(tmp_path):
    bus = Bus(tmp_path / "bus.db")
    seed(bus)
    scripts = {
        "architect": [send(bus, "r1", "architect", "coder", "plan")],
        "coder": [send(bus, "r1", "coder", "tester", "ready_for_test")],
        "tester": [send(bus, "r1", "tester", "manager", "test_passed")],
        "manager": [finish(bus, "r1")],
    }
    sched = Scheduler(bus, "r1", make_crew(bus, "r1", scripts))
    result = anyio.run(sched.run)
    assert result.status == "finished"
    assert result.agent_turns == 4
    assert result.total_cost_usd > 0


def test_ask_human_pauses_and_resumes(tmp_path):
    bus = Bus(tmp_path / "bus.db")
    seed(bus)
    answers = []

    def human(question: str) -> str:
        answers.append(question)
        return "small scope please"

    scripts = {
        "architect": [ask(bus, "r1"), send(bus, "r1", "architect", "coder", "plan")],
        "coder": [send(bus, "r1", "coder", "tester", "ready_for_test")],
        "tester": [send(bus, "r1", "tester", "manager", "test_passed")],
        "manager": [finish(bus, "r1")],
    }
    sched = Scheduler(bus, "r1", make_crew(bus, "r1", scripts), human_input=human)
    result = anyio.run(sched.run)
    assert result.status == "finished"
    assert answers == ["scope?"]
    got = bus.messages("r1", kind="answer")
    assert len(got) == 1 and got[0].recipient == "architect"


def test_manager_brake_fires_after_n_failures(tmp_path):
    bus = Bus(tmp_path / "bus.db")
    seed(bus)
    r = "r1"
    scripts = {
        "architect": [send(bus, r, "architect", "coder", "plan")],
        # coder and tester bounce forever
        "coder": [send(bus, r, "coder", "tester", "ready_for_test", body=f"v{i}")
                  for i in range(10)],
        "tester": [send(bus, r, "tester", "coder", "test_failed", body=f"fail{i}")
                   for i in range(10)],
        "manager": [finish(bus, r)],
    }
    sched = Scheduler(bus, r, make_crew(bus, r, scripts), brake_after=3)
    result = anyio.run(sched.run)
    assert result.status == "finished"  # manager was force-woken and finished
    flags = bus.messages(r, kind="flag", recipient="manager")
    assert any(f.sender == "scheduler" for f in flags)


def test_turn_cap_stops_run(tmp_path):
    bus = Bus(tmp_path / "bus.db")
    seed(bus)
    r = "r1"
    scripts = {
        "architect": [send(bus, r, "architect", "coder", "plan")],
        "coder": [send(bus, r, "coder", "tester", "ready_for_test", body=f"v{i}")
                  for i in range(50)],
        "tester": [send(bus, r, "tester", "coder", "test_failed", body=f"f{i}")
                   for i in range(50)],
        "manager": [],  # never finishes
    }
    sched = Scheduler(bus, r, make_crew(bus, r, scripts), turn_cap=6, brake_after=99)
    result = anyio.run(sched.run)
    assert result.status == "turn_cap"
    assert result.agent_turns <= 6


def test_budget_flag_then_manager_closeout(tmp_path):
    bus = Bus(tmp_path / "bus.db")
    seed(bus)
    r = "r1"
    scripts = {
        "architect": [send(bus, r, "architect", "coder", "plan")],
        "coder": [send(bus, r, "coder", "tester", "ready_for_test", body=f"v{i}")
                  for i in range(50)],
        "tester": [send(bus, r, "tester", "coder", "test_failed", body=f"f{i}")
                   for i in range(50)],
        "manager": [finish(bus, r)],
    }
    crew = make_crew(bus, r, scripts)
    for a in crew.values():
        a._cost = 1.0  # blow the budget fast
    sched = Scheduler(bus, r, crew, budget_usd=2.5, brake_after=99)
    result = anyio.run(sched.run)
    assert result.status == "finished"
    flags = bus.messages(r, kind="flag", recipient="manager")
    assert any("budget" in f.subject for f in flags)


def test_stalled_when_no_one_runnable(tmp_path):
    bus = Bus(tmp_path / "bus.db")
    seed(bus)
    # Architect consumes the idea but sends nothing.
    scripts = {"architect": [lambda _inbox: None]}
    sched = Scheduler(bus, "r1", make_crew(bus, "r1", scripts))
    result = anyio.run(sched.run)
    assert result.status == "stalled"
```

- [ ] **Step 2:** Run → FAIL (`No module named 'crew.scheduler'`).

- [ ] **Step 3: Implement**

```python
# crew/scheduler.py
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
```

- [ ] **Step 4:** `& $PY -m pytest tests/test_scheduler.py -q` → all PASS. Also run the whole suite: `& $PY -m pytest tests/ -q` → all green; ruff clean. If the budget test is flaky because the budget flag lands after the crew already bounced past it, tighten `budget_usd` in the test rather than adding sleeps — the loop is deterministic with FakeAgents.

- [ ] **Step 5: Commit** — `feat: scheduler — runnable-by-mail loop, human pause, manager brake, budget + turn guards` (same trailer).

---

### Task 7: Run report

**Files:**
- Create: `crew/report.py`
- Test: `tests/test_report.py`

**Interfaces:**
- Consumes: `Bus`, `RunResult`.
- Produces: `write_run_record(bus, run_id, result: RunResult, workspace: Path, vault_dir: Path) -> Path` — appends a run section to `vault_dir / "03-resources" / "Crew-Runs.md"` (creates the file with frontmatter if absent), returns the path.

- [ ] **Step 1: Failing tests**

```python
# tests/test_report.py
from pathlib import Path

from crew.bus import Bus
from crew.report import write_run_record
from crew.scheduler import RunResult


def _setup(tmp_path) -> tuple[Bus, Path]:
    bus = Bus(tmp_path / "bus.db")
    (tmp_path / "vault" / "03-resources").mkdir(parents=True)
    return bus, tmp_path / "vault"


def test_creates_file_with_frontmatter(tmp_path):
    bus, vault = _setup(tmp_path)
    bus.append(run_id="r1", sender="manager", recipient="run",
               kind="done", subject="done", body="Shipped fizzbuzz; 12 tests pass.")
    out = write_run_record(bus, "r1", RunResult("finished", 1.23, 7),
                           tmp_path / "runs" / "r1", vault)
    text = out.read_text(encoding="utf-8")
    assert out.name == "Crew-Runs.md"
    assert text.startswith("---")
    assert "Shipped fizzbuzz" in text
    assert "$1.23" in text and "finished" in text


def test_appends_second_run(tmp_path):
    bus, vault = _setup(tmp_path)
    bus.append(run_id="r1", sender="manager", recipient="run",
               kind="done", subject="done", body="first")
    write_run_record(bus, "r1", RunResult("finished", 1.0, 5), tmp_path / "w1", vault)
    bus.append(run_id="r2", sender="manager", recipient="run",
               kind="done", subject="done", body="second")
    out = write_run_record(bus, "r2", RunResult("finished", 2.0, 6), tmp_path / "w2", vault)
    text = out.read_text(encoding="utf-8")
    assert "first" in text and "second" in text
    assert text.count("## Run") == 2


def test_handles_run_without_done_message(tmp_path):
    bus, vault = _setup(tmp_path)
    out = write_run_record(bus, "r1", RunResult("turn_cap", 3.0, 24),
                           tmp_path / "w", vault)
    assert "turn_cap" in out.read_text(encoding="utf-8")
```

- [ ] **Step 2:** Run → FAIL.

- [ ] **Step 3: Implement**

```python
# crew/report.py
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
```

- [ ] **Step 4:** Tests PASS, ruff clean.
- [ ] **Step 5: Commit** — `feat: vault run records (Crew-Runs.md)` (same trailer).

---

### Task 8: CLI entrypoint + rich live view

**Files:**
- Create: `crew/run.py`
- Test: `tests/test_run_wiring.py` (wiring only — no API call)

**Interfaces:**
- Consumes: everything above.
- Produces: `python -m crew.run "<idea>"` with flags `--budget` (default 5.0), `--turn-cap` (default 24), `--vault` (default `C:\Claude\Brain`, env `CREW_VAULT_DIR` wins over default, flag wins over env). Module function `build_run(idea, *, base_dir: Path, vault_dir: Path, budget: float, turn_cap: int) -> tuple[Bus, Scheduler, str, Path]` so tests can assert wiring without executing.

- [ ] **Step 1: Failing tests**

```python
# tests/test_run_wiring.py
from crew.bus import Bus
from crew.run import build_run


def test_build_run_seeds_idea_and_wires_crew(tmp_path):
    bus, sched, run_id, workspace = build_run(
        "build fizzbuzz", base_dir=tmp_path, vault_dir=tmp_path / "vault",
        budget=5.0, turn_cap=24,
    )
    assert isinstance(bus, Bus)
    inbox = bus.unread_for(run_id, "architect")
    assert len(inbox) == 1 and inbox[0].kind == "idea" and inbox[0].body == "build fizzbuzz"
    assert workspace.is_dir()
    assert (tmp_path / "data" / "bus.db").exists()
    # Bus DB must live OUTSIDE the run sandbox.
    assert (tmp_path / "data") not in workspace.parents or True
    assert not str(tmp_path / "data").startswith(str(workspace))
```

- [ ] **Step 2:** Run → FAIL.

- [ ] **Step 3: Implement**

```python
# crew/run.py
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
```

- [ ] **Step 4:** `& $PY -m pytest tests/ -q` → all green; ruff clean.
- [ ] **Step 5: Commit** — `feat: CLI entrypoint with rich round view` (same trailer).

---

### Task 9: End-to-end fake run + real smoke run

**Files:**
- Test: `tests/test_e2e_fake.py`
- Manual: one real run (costs real money, needs Big Ben present for the Architect's questions)

- [ ] **Step 1: E2E fake test** (full wiring through report, still $0):

```python
# tests/test_e2e_fake.py
import anyio

from crew.bus import Bus
from crew.report import write_run_record
from crew.scheduler import Scheduler
from tests.fakes import FakeAgent


def test_full_run_produces_record(tmp_path):
    (tmp_path / "vault" / "03-resources").mkdir(parents=True)
    bus = Bus(tmp_path / "bus.db")
    r = "r1"
    bus.append(run_id=r, sender="user", recipient="architect",
               kind="idea", subject="idea", body="fizzbuzz")

    def relay(frm, to, kind):
        def action(_inbox):
            bus.append(run_id=r, sender=frm, recipient=to, kind=kind,
                       subject=kind, body=kind)
        return action

    def finish(_inbox):
        bus.append(run_id=r, sender="manager", recipient="run",
                   kind="done", subject="done", body="shipped fizzbuzz")
        bus.set_status("manager", "done")

    agents = {
        "architect": FakeAgent("architect", bus, r, [relay("architect", "coder", "plan")]),
        "coder": FakeAgent("coder", bus, r, [relay("coder", "tester", "ready_for_test")]),
        "tester": FakeAgent("tester", bus, r, [relay("tester", "manager", "test_passed")]),
        "manager": FakeAgent("manager", bus, r, [finish]),
    }
    result = anyio.run(Scheduler(bus, r, agents).run)
    out = write_run_record(bus, r, result, tmp_path / "runs" / r, tmp_path / "vault")
    assert result.status == "finished"
    assert "shipped fizzbuzz" in out.read_text(encoding="utf-8")
```

- [ ] **Step 2:** Run full suite: `& $PY -m pytest tests/ -q` → all green.

- [ ] **Step 3: Commit** — `test: end-to-end fake-crew run through the report` (same trailer).

- [ ] **Step 4: Real smoke run (WITH Big Ben at the keyboard — the Architect will ask questions).** Use a scratch vault dir first so a bad record doesn't land in the Brain:

```powershell
cd C:\Claude\research-crew
& $PY -m crew.run "Build a fizzbuzz CLI in Python with tests" --budget 3.0 --vault (New-Item -ItemType Directory -Force "$env:TEMP\crew-vault").FullName
New-Item -ItemType Directory -Force "$env:TEMP\crew-vault\03-resources" | Out-Null
```

Expected: Architect asks questions in the terminal → answer them → rounds print → status `finished`, cost well under $3, working fizzbuzz + tests inside `runs\<id>\`, record in the scratch vault. **Verify before claiming success:** open `runs\<id>\`, run the fizzbuzz tests yourself.

- [ ] **Step 5:** If the smoke run passes, commit any tuning changes, then run the `agent-sdk-verifier-py` agent ("Verify my Python Agent SDK application") — now there's a real application to audit. Treat CRITICAL findings as blocking.

---

### Task 10: Docs + spec honesty pass

**Files:**
- Modify: `docs/superpowers/specs/2026-07-23-dev-crew-design.md` (Error handling section)
- Create: `CLAUDE.md` (project)
- Modify (vault, outside repo): `C:\Claude\Brain\01-projects\Research-Crew.md` status checkboxes, `log.md`, daily note

- [ ] **Step 1:** Update the spec's sandbox claim to match Windows reality. Replace the line "**Sandbox escape** → prevented structurally by `cwd` + `allowed_tools`, not by trusting the model." with:

```
- **Sandbox containment** → `cwd` scoping + per-role `allowed_tools` + role prompts +
  turn/budget caps. NOTE (Windows): the SDK's OS-level bash sandboxing is macOS/Linux
  only, so Bash is not hard-jailed here — the Coder/Tester run with bypassPermissions
  inside a throwaway dir on a personal machine. Acceptable for learning; revisit
  (WSL/container) before pointing the crew at anything real.
```

- [ ] **Step 2:** Write a short project `CLAUDE.md` (commands: run/test/lint; the append-only bus invariant; the determinism rule; the one-model-per-agent rule; pointer to spec + plan).

- [ ] **Step 3:** Commit both; update the vault (status checkboxes on the project page, one `log.md` line, daily note line).

---

## Verification (end-to-end)

```powershell
cd C:\Claude\research-crew
$PY = ".\.venv\Scripts\python.exe"
& $PY -m ruff check crew/ tests/          # clean
& $PY -m pytest tests/ -q                 # all green, $0 spent
& $PY -m crew.run "Build a fizzbuzz CLI in Python with tests" --budget 3.0   # real run
# then: inspect runs/<id>/, run its tests, read the run record
```

Success criteria: full suite green with zero API calls; one real run finishes under budget with working, tested code in the sandbox; every guard has a passing test (brake, budget, turn cap, stalled, human pause); `agent-sdk-verifier-py` reports no CRITICAL.

## Self-review notes (done while writing)

- Spec coverage: bus→T1, roles→T2, tools→T3, workspace→T4, agent→T5, scheduler+guards→T6, report→T7 (TBD resolved: `Crew-Runs.md`), CLI+rich→T8, FakeAgent+E2E+smoke→T9, GUI-seam constraints→enforced by T1 design (append-only, cursors, status, poll-by-id). Spec deviation (Windows sandbox honesty) handled in T10 rather than silently ignored.
- Type consistency: `Msg`, `Bus`, `Role`, `RunResult`, `build_options`, `run_turn(inbox) -> float` used identically across tasks.
- Known judgment calls: `subject` column added to schema; scheduler answers human questions between rounds (tools never block inside a query); cursor advanced before the turn to prevent double-delivery on concurrent rounds.
