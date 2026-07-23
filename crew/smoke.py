"""Auth + connectivity smoke test.

The load-bearing check from the tooling plan: does the Claude Agent SDK run with
*zero* auth configuration by inheriting the already-logged-in Claude Code CLI
session? If this prints a reply, no ANTHROPIC_API_KEY and no `ant` profile is
needed. If it raises an auth/CLI error, that's the signal to set one up.

Run:  python -m crew.smoke
"""

from __future__ import annotations

import anyio
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKError,
    ResultMessage,
    TextBlock,
    query,
)


async def _run() -> int:
    # Haiku, one turn, tiny prompt — keeps the auth probe as cheap as possible.
    options = ClaudeAgentOptions(
        model="claude-haiku-4-5",
        max_turns=1,
        system_prompt="You are a smoke test. Reply with exactly one short sentence.",
    )

    reply_text: list[str] = []
    cost_usd: float | None = None

    async for message in query(prompt="Say hello in one short sentence.", options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    reply_text.append(block.text)
        elif isinstance(message, ResultMessage):
            cost_usd = message.total_cost_usd

    if not reply_text:
        print("FAIL: connected but got no assistant text back.")
        return 1

    print("OK — the SDK ran with zero auth config.")
    print(f"  reply: {''.join(reply_text).strip()}")
    if cost_usd is not None:
        print(f"  cost:  ${cost_usd:.5f}")
    print("\nZero-config auth works. No `ant` install needed.")
    return 0


def main() -> int:
    try:
        return anyio.run(_run)
    except ClaudeSDKError as exc:
        # Auth failure, CLI-not-found, or process error all land here.
        print(f"FAIL: the SDK could not run ({type(exc).__name__}): {exc}")
        print(
            "\nZero-config auth did NOT work. Set up credentials before proceeding —\n"
            "see phase 1 'Auth' in the tooling plan (ant login or ANTHROPIC_API_KEY)."
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
