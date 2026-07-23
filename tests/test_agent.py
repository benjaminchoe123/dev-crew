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
