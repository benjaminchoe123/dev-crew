"""Toolchain smoke tests — no API calls, no cost.

Confirms the package imports and the SDK is resolvable in this venv. Real crew
tests come once the design spec is approved; this just proves pytest + the
install are wired up.
"""


def test_crew_package_imports() -> None:
    import crew  # noqa: F401


def test_sdk_is_importable() -> None:
    import claude_agent_sdk

    assert claude_agent_sdk.__version__.startswith("0.2.")
