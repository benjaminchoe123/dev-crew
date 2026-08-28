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

#: Where each role is allowed to write, relative to the workspace. A role absent
#: from this map is unrestricted -- writing code is the coder's entire job.
WRITE_SCOPES: dict[str, tuple[str, ...]] = {
    "tester": ("tests",),
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

    Fails *closed*: a write whose target cannot be parsed is denied, because a
    guard that waves through what it does not understand is the failure it exists
    to prevent.
    """
    scope = WRITE_SCOPES.get(role_name)
    if scope is None or tool_name not in WRITE_TOOLS:
        return None

    raw = next((tool_input[k] for k in _PATH_KEYS if tool_input.get(k)), None)
    if not raw:
        return (f"{role_name} may only write under {'/, '.join(scope)}/, and this "
                f"{tool_name} call names no path to check")

    parts = _relative_parts(str(raw), workspace)
    if parts is None or not parts or parts[0] not in scope:
        # ASCII only: this string is surfaced to a console that may be cp1252,
        # and an em-dash in an error path is how you turn a refusal into a crash.
        return (f"{role_name} may only write under {'/, '.join(scope)}/. Refusing to "
                f"{tool_name} {raw}. Report the failure to the coder instead of fixing it.")
    return None
