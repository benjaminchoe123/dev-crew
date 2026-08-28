"""Separation of duties, actually enforced.

The README claimed the tester "cannot quietly patch the coder's implementation"
because it has `Write` but not `Edit`. That was wrong in the worst direction:
`Write` replaces a file wholesale, so it is a *more* complete patch than `Edit`,
not a lesser one. The claim was instruction-following dressed up as enforcement.

These pin the enforcement that replaced it: a permission callback that scopes the
tester's file writes to tests/. What it deliberately does NOT do is guard Bash —
see test_bash_is_not_guarded_and_that_is_documented_not_hidden.
"""

import pytest

from crew.guards import check_tool
from crew.roles import ROLES

WS = "/work"


def test_tester_may_write_inside_its_scope():
    assert check_tool("tester", "Write", {"file_path": "tests/test_thing.py"}, WS) is None


def test_tester_may_not_write_implementation_code():
    reason = check_tool("tester", "Write", {"file_path": "app/calc.py"}, WS)
    assert reason and "tests" in reason


def test_tester_may_not_edit_implementation_code_either():
    assert check_tool("tester", "Edit", {"file_path": "app/calc.py"}, WS) is not None


def test_write_is_guarded_not_just_edit():
    """The original bug. Write overwrites a whole file, so guarding only Edit
    guards the weaker of the two operations."""
    assert check_tool("tester", "Write", {"file_path": "app/calc.py"}, WS) is not None


def test_a_path_climbing_out_of_tests_is_denied():
    assert check_tool("tester", "Write",
                      {"file_path": "tests/../app/calc.py"}, WS) is not None


def test_an_absolute_path_outside_the_workspace_is_denied():
    assert check_tool("tester", "Write", {"file_path": "C:/Windows/evil.py"}, WS) is not None


def test_a_nested_test_file_is_allowed():
    assert check_tool("tester", "Write",
                      {"file_path": "tests/unit/test_deep.py"}, WS) is None


def test_reading_is_never_restricted():
    """The tester must read the implementation to test it."""
    assert check_tool("tester", "Read", {"file_path": "app/calc.py"}, WS) is None


def test_the_coder_is_unrestricted_because_writing_code_is_its_job():
    assert check_tool("coder", "Write", {"file_path": "app/calc.py"}, WS) is None


def test_the_manager_has_no_write_tools_so_needs_no_scope():
    """Enforced one level up, by allowed_tools. Asserted here so that removing
    it from the tool list is a test failure rather than a silent regression."""
    for tool in ("Write", "Edit", "Bash"):
        assert tool not in ROLES["manager"].allowed_tools


def test_bash_is_not_guarded_and_that_is_documented_not_hidden():
    """A shell is a universal write primitive: `echo x > app/calc.py` defeats any
    path check, and pattern-matching commands to pretend otherwise would be the
    same theatre this fix removed. The tester needs Bash to run pytest, so Bash
    stays open and the README says so rather than implying a guarantee that does
    not exist.
    """
    assert check_tool("tester", "Bash", {"command": "echo x > app/calc.py"}, WS) is None


def test_an_unknown_tool_is_allowed_rather_than_blocked_by_surprise():
    assert check_tool("tester", "SomeFutureTool", {"file_path": "app/x.py"}, WS) is None


@pytest.mark.parametrize("field", ["file_path", "path", "notebook_path"])
def test_the_path_is_found_whatever_the_tool_calls_it(field):
    assert check_tool("tester", "Write", {field: "app/calc.py"}, WS) is not None


def test_a_write_with_no_path_at_all_is_denied_rather_than_waved_through():
    """Unparseable input must not become an allow. A guard that fails open is
    the failure mode it exists to prevent."""
    assert check_tool("tester", "Write", {}, WS) is not None


def test_an_absolute_path_inside_the_workspace_is_allowed():
    """Agents routinely emit absolute paths. Denying a legitimate one would push
    the tester back toward Bash, which is the unguarded route."""
    assert check_tool("tester", "Write", {"file_path": "/work/tests/test_x.py"}, WS) is None


def test_an_absolute_implementation_path_inside_the_workspace_is_denied():
    assert check_tool("tester", "Write", {"file_path": "/work/app/calc.py"}, WS) is not None


def test_windows_separators_are_understood_too():
    """A guard that understands one separator is a guard with a documented bypass."""
    assert check_tool("tester", "Write", {"file_path": r"tests\test_x.py"}, WS) is None
    assert check_tool("tester", "Write", {"file_path": r"app\calc.py"}, WS) is not None


# --- the mirror image -------------------------------------------------------
# Yesterday's fix stopped the tester patching implementation code. It left the
# other half open: the coder has unrestricted Write and Edit, so it can rewrite
# the tester's tests until they pass. That is the same defeat of the separation,
# from the other side, and arguably the easier one to reach for -- the coder's
# role text tells it to "fix exactly what the tester reported", and a failing
# assertion is the most direct thing to edit.

def test_the_coder_may_not_edit_the_tests_that_judge_it():
    assert check_tool("coder", "Edit", {"file_path": "tests/test_calc.py"}, WS) is not None


def test_the_coder_may_not_overwrite_a_test_file_either():
    assert check_tool("coder", "Write", {"file_path": "tests/test_calc.py"}, WS) is not None


def test_the_coder_may_still_write_implementation_code():
    assert check_tool("coder", "Write", {"file_path": "app/calc.py"}, WS) is None


def test_the_coder_is_stopped_by_an_absolute_path_into_tests_too():
    assert check_tool("coder", "Write", {"file_path": "/work/tests/test_calc.py"}, WS) is not None


def test_a_path_climbing_into_tests_is_denied_for_the_coder():
    assert check_tool("coder", "Write", {"file_path": "app/../tests/test_calc.py"}, WS) is not None


def test_a_file_merely_named_like_a_test_outside_tests_is_fine():
    """The boundary is the directory, not the filename. A coder writing
    `app/testing_utils.py` is doing its job."""
    assert check_tool("coder", "Write", {"file_path": "app/testing_utils.py"}, WS) is None


def test_the_coders_bash_is_no_more_guarded_than_the_testers():
    assert check_tool("coder", "Bash", {"command": "rm tests/test_calc.py"}, WS) is None


def test_the_two_halves_fail_in_opposite_directions_on_an_unparseable_path():
    """Not an inconsistency -- the same ambiguity means opposite things to an
    allowlist and a denylist. Pinned so nobody "fixes" one to match the other."""
    climbing = {"file_path": "../../outside.py"}
    assert check_tool("tester", "Write", climbing, WS) is not None   # closed
    assert check_tool("coder", "Write", climbing, WS) is None        # open


def test_a_write_naming_no_path_is_refused_for_the_coder_too():
    """Malformed, not ambiguous: a Write with no target cannot succeed anyway."""
    assert check_tool("coder", "Write", {}, WS) is not None
