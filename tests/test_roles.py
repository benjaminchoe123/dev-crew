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
