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


def test_build_prompt_is_deterministic_and_excludes_ts(tmp_path):
    from crew.agent import build_prompt

    bus = Bus(tmp_path / "bus.db")
    bus.append(run_id="r1", sender="user", recipient="architect",
               kind="idea", subject="s", body="b")
    inbox = bus.unread_for("r1", "architect")
    history = bus.history_for("r1", "architect")
    assert build_prompt(history, inbox) == build_prompt(history, inbox)
    assert "ts" not in build_prompt(history, inbox)


def test_build_prompt_handles_empty_context():
    from crew.agent import build_prompt

    assert "(none yet)" in build_prompt([], [])


def test_build_prompt_keeps_the_plan_after_a_test_failed_bounce(tmp_path):
    """The regression this whole change exists to prevent: on a later turn the
    coder still sees the architect's plan and its own earlier handoff."""
    from crew.agent import build_prompt

    bus = Bus(tmp_path / "bus.db")
    r = "r1"
    bus.append(run_id=r, sender="user", recipient="architect",
               kind="idea", subject="s", body="build fizzbuzz")
    bus.append(run_id=r, sender="architect", recipient="coder",
               kind="plan", subject="plan", body="PLAN: write fizzbuzz.py")
    bus.append(run_id=r, sender="coder", recipient="tester",
               kind="ready_for_test", subject="s", body="ready for you")
    tf = bus.append(run_id=r, sender="tester", recipient="coder",
                    kind="test_failed", subject="s", body="AssertionError line 3")

    inbox = [m for m in bus.messages(r) if m.id == tf]  # coder's only unread this turn
    prompt = build_prompt(bus.history_for(r, "coder"), inbox)

    assert "PLAN: write fizzbuzz.py" in prompt      # architect's plan remembered
    assert "ready for you" in prompt                # coder's own handoff remembered
    context, _, action = prompt.partition("New messages addressed to you")
    assert "AssertionError line 3" in action        # the failure is the action item
    assert "AssertionError line 3" not in context   # not duplicated into context
