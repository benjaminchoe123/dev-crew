import anyio

from crew.bus import Bus
from crew.tools import ask_human_impl, finish_impl, send_message_impl


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


def test_ask_human_none_value_returns_error(tmp_path):
    bus = Bus(tmp_path / "bus.db")
    out = anyio.run(lambda: ask_human_impl(bus, "r1", "architect", {"questions": None}))
    assert out.startswith("ERROR")
    assert bus.messages("r1") == []


def test_finish_none_value_returns_error(tmp_path):
    bus = Bus(tmp_path / "bus.db")
    out = anyio.run(lambda: finish_impl(bus, "r1", "manager", {"summary": None}))
    assert out.startswith("ERROR")
    assert bus.messages("r1") == []
