"""Separation of duties enforced by a permission callback, not by the prompt.

The tester's role text says it never fixes the coder's code. Role text is a
request. This is the part that is not.

What this replaced was worse than nothing: the tester was given `Write` but not
`Edit`, and the README called that enforcement. `Write` replaces a file wholesale,
so it is a *more* complete patch than `Edit` — the tool that was removed was the
weaker of the two. A guard that inspects the path is the actual constraint.

What this deliberately does not do is guard `Bash`. A shell is a universal write
primitive: `echo x > app/calc.py` defeats any path check, and pattern-matching
commands to look like a guarantee would be exactly the theatre this module exists
to remove. The tester needs Bash to run pytest, so Bash stays open and the README
says so. An unenforceable boundary named honestly is worth more than an enforced
one that is claimed falsely.
"""

from __future__ import annotations

#: Tools that create or modify a file. Anything not here is a read, a search, or
#: an MCP call, and none of those can patch an implementation.
WRITE_TOOLS = frozenset({"Write", "Edit", "MultiEdit", "NotebookEdit"})

#: Where a role is allowed to write, relative to the workspace. The tester may
#: only author tests; everything else is the coder's to change.
WRITE_SCOPES: dict[str, tuple[str, ...]] = {
    "tester": ("tests",),
}

#: Where a role is *forbidden* to write. Two mechanisms rather than one because
#: the two constraints are genuinely different shapes: the tester is confined to
#: one directory, while the coder may write anywhere **except** one -- and an
#: allowlist cannot express "everywhere else" without enumerating a project's
#: whole layout in advance.
#:
#: The coder entry is the mirror of the tester's, and the half that was missing
#: until 2026-08-28. Stopping the tester from patching implementation while
#: leaving the coder free to rewrite the tests defeats the same separation from
#: the other side, and it is the easier side to reach for: the coder is told to
#: "fix exactly what the tester reported", and a failing assertion is the most
#: direct thing to edit.
WRITE_DENIED: dict[str, tuple[str, ...]] = {
    "coder": ("tests",),
}

#: Tool inputs spell the target differently depending on the tool.
_PATH_KEYS = ("file_path", "path", "notebook_path")


def _split(text: str) -> list[str]:
    """Path components, either separator. An agent on Windows emits both, and a
    guard that understands only one is a guard with a documented bypass."""
    return [c for c in text.replace("\\", "/").split("/") if c not in ("", ".")]


def _normalise(parts: list[str]) -> list[str] | None:
    """Resolve `..` textually; None if it climbs above the root."""
    out: list[str] = []
    for part in parts:
        if part == "..":
            if not out:
                return None
            out.pop()
        else:
            out.append(part)
    return out


def _relative_parts(raw: str, workspace: str) -> tuple[str, ...] | None:
    """The target as workspace-relative parts, or None if it escapes.

    Textual rather than filesystem-resolving on purpose: the path being judged
    usually does not exist yet, and `Path.resolve()` on a missing file is not a
    security boundary anyway.
    """
    root = _normalise(_split(workspace)) or []
    absolute = raw.startswith(("/", "\\")) or raw.replace("\\", "/").split("/")[0].endswith(":")
    parts = _normalise(_split(raw))
    if parts is None:
        return None

    if absolute:
        if parts[:len(root)] != root:
            return None  # absolute, and not under the workspace
        return tuple(parts[len(root):])
    return tuple(parts)


def check_tool(role_name: str, tool_name: str, tool_input: dict, workspace: str) -> str | None:
    """A refusal reason, or None to allow.

    The two halves fail in opposite directions on purpose, because "I could not
    parse this path" means opposite things to each:

    - an **allowlist** (tester) fails *closed*. An unparseable target has not
      been shown to be inside `tests/`, and a guard that waves through what it
      does not understand is the failure it exists to prevent;
    - a **denylist** (coder) fails *open*. An unparseable target has not been
      shown to be inside `tests/` either -- and here that is the permissive
      reading. Failing closed would block the coder from writing anything the
      parser did not recognise, which is most of its job.

    A call naming no path at all is refused for both. That is a malformed write,
    not an ambiguous one.
    """
    scope = WRITE_SCOPES.get(role_name)
    denied = WRITE_DENIED.get(role_name)
    if (scope is None and denied is None) or tool_name not in WRITE_TOOLS:
        return None

    raw = next((tool_input[k] for k in _PATH_KEYS if tool_input.get(k)), None)
    if not raw:
        where = "/, ".join(scope) if scope else "/, ".join(denied or ())
        return (f"{role_name}'s writes are scoped around {where}/, and this "
                f"{tool_name} call names no path to check")

    parts = _relative_parts(str(raw), workspace)

    if denied is not None:
        # A path that cannot be resolved is allowed here rather than denied: for a
        # denylist, unparseable means "not shown to be inside the forbidden
        # directory". Failing closed on a denylist would block the coder from
        # writing anything the parser did not understand, which is most of its job.
        if parts and parts[0] in denied:
            return (f"{role_name} may not write under {'/, '.join(denied)}/. Refusing to "
                    f"{tool_name} {raw}. Fix the code the test is failing on, not the test.")
        if scope is None:
            return None

    if parts is None or not parts or parts[0] not in scope:
        # ASCII only: this string is surfaced to a console that may be cp1252,
        # and an em-dash in an error path is how you turn a refusal into a crash.
        return (f"{role_name} may only write under {'/, '.join(scope)}/. Refusing to "
                f"{tool_name} {raw}. Report the failure to the coder instead of fixing it.")
    return None
