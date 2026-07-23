# Dev Crew

Autonomous 4-agent software team (Architect → Coder → Tester → Manager) on the Claude
Agent SDK. Agents communicate only via an append-only SQLite message bus; a scheduler
wakes whoever has unread mail and enforces every guard. Spec:
`docs/superpowers/specs/2026-07-23-dev-crew-design.md` · Plan:
`docs/superpowers/plans/2026-07-23-dev-crew-runtime.md`

## Commands

- Run the crew: `python -m crew.run "<idea>"` (flags: `--budget 5.0 --turn-cap 24 --vault <dir>`;
  env `CREW_VAULT_DIR` overrides the default vault, flag overrides env)
- Tests: `python -m pytest tests/ -q` (all $0 — FakeAgents, no API calls)
- Lint: `python -m ruff check crew/ tests/`
- venv: `.venv\Scripts\Activate.ps1`

## Invariants worth not breaking

- The `messages` table is append-only — no UPDATE/DELETE ever. Read-tracking lives in the
  separate `cursors` table. Replayability and the future GUI depend on this.
- `Msg.to_prompt()` is deterministic (sorted keys, no timestamp). Prompt caching — the
  entire cost model — silently breaks if serialization varies byte-to-byte.
- One model per agent per run. Caches are model-scoped; switching mid-run throws them away.
- Every agent runs with `setting_sources=[]` (no global CLAUDE.md bleed-through) and
  `cwd`-scoped to its `runs/<id>/` sandbox.
- The budget guard is a SOFT ceiling checked per round: worst-case spend ≈ budget + one
  round of per-turn `max_budget_usd` caps. Per-turn caps bound the overshoot.
- Windows caveat: the SDK's OS-level bash sandboxing is macOS/Linux only. Coder/Tester run
  with `bypassPermissions` in a throwaway dir — fine for learning; revisit (WSL/container)
  before pointing the crew at anything real.
- Tool gating is structural: who may call `finish`/`ask_human` lives in `roles.py`
  `allowed_tools`, and sender identity is closure-bound in `tools.py` — never trust-based.
