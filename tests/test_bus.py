"""Bus: append-only messages, cursor-based unread, agent status, determinism."""
import json

from crew.bus import Bus


def make_bus(tmp_path):
    return Bus(tmp_path / "bus.db")


def test_append_and_read_roundtrip(tmp_path):
    bus = make_bus(tmp_path)
    mid = bus.append(run_id="r1", sender="user", recipient="architect",
                     kind="idea", subject="fizzbuzz", body="Build fizzbuzz")
    msgs = bus.messages("r1")
    assert [m.id for m in msgs] == [mid]
    m = msgs[0]
    assert (m.sender, m.recipient, m.kind, m.subject, m.body, m.thread_id) == (
        "user", "architect", "idea", "fizzbuzz", "Build fizzbuzz", "main")
    assert m.ts  # timestamp recorded


def test_unread_respects_cursor(tmp_path):
    bus = make_bus(tmp_path)
    a = bus.append(run_id="r1", sender="user", recipient="architect",
                   kind="idea", subject="s", body="b1")
    assert [m.id for m in bus.unread_for("r1", "architect")] == [a]
    bus.advance_cursor("architect", a)
    assert bus.unread_for("r1", "architect") == []
    b = bus.append(run_id="r1", sender="coder", recipient="architect",
                   kind="question", subject="s", body="b2")
    assert [m.id for m in bus.unread_for("r1", "architect")] == [b]


def test_unread_filters_by_recipient(tmp_path):
    bus = make_bus(tmp_path)
    bus.append(run_id="r1", sender="user", recipient="architect",
               kind="idea", subject="s", body="b")
    assert bus.unread_for("r1", "coder") == []


def test_history_for_includes_sent_and_received_in_order(tmp_path):
    bus = make_bus(tmp_path)
    a = bus.append(run_id="r1", sender="architect", recipient="coder",
                   kind="plan", subject="s", body="p")
    b = bus.append(run_id="r1", sender="coder", recipient="tester",
                   kind="ready_for_test", subject="s", body="r")
    c = bus.append(run_id="r1", sender="tester", recipient="coder",
                   kind="test_failed", subject="s", body="f")
    assert [m.id for m in bus.history_for("r1", "coder")] == [a, b, c]


def test_history_for_excludes_other_agents_private_traffic(tmp_path):
    bus = make_bus(tmp_path)
    bus.append(run_id="r1", sender="tester", recipient="manager",
               kind="test_passed", subject="s", body="ok")
    assert bus.history_for("r1", "coder") == []


def test_history_for_scoped_by_run(tmp_path):
    bus = make_bus(tmp_path)
    bus.append(run_id="r1", sender="architect", recipient="coder",
               kind="plan", subject="s", body="p1")
    bus.append(run_id="r2", sender="architect", recipient="coder",
               kind="plan", subject="s", body="p2")
    assert [m.body for m in bus.history_for("r1", "coder")] == ["p1"]


def test_status_default_and_set(tmp_path):
    bus = make_bus(tmp_path)
    assert bus.get_status("coder") == "idle"
    bus.set_status("coder", "coding")
    assert bus.get_status("coder") == "coding"


def test_has_duplicate(tmp_path):
    bus = make_bus(tmp_path)
    bus.append(run_id="r1", sender="coder", recipient="tester",
               kind="ready_for_test", subject="s", body="same")
    assert bus.has_duplicate("r1", "coder", "tester", "ready_for_test", "same")
    assert not bus.has_duplicate("r1", "coder", "tester", "ready_for_test", "different")


def test_count_kind(tmp_path):
    bus = make_bus(tmp_path)
    for _ in range(2):
        bus.append(run_id="r1", sender="tester", recipient="coder",
                   kind="test_failed", subject="s", body="x")
    assert bus.count_kind("r1", "test_failed") == 2
    assert bus.count_kind("r1", "test_passed") == 0


def test_messages_filter_by_kind(tmp_path):
    bus = make_bus(tmp_path)
    bus.append(run_id="r1", sender="manager", recipient="run",
               kind="done", subject="s", body="shipped")
    bus.append(run_id="r1", sender="user", recipient="architect",
               kind="idea", subject="s", body="b")
    assert [m.kind for m in bus.messages("r1", kind="done")] == ["done"]


def test_to_prompt_is_deterministic_and_excludes_ts(tmp_path):
    bus = make_bus(tmp_path)
    mid = bus.append(run_id="r1", sender="user", recipient="architect",
                     kind="idea", subject="s", body="b")
    m = bus.messages("r1")[0]
    payload = json.loads(m.to_prompt())
    assert "ts" not in payload
    assert list(payload.keys()) == sorted(payload.keys())
    assert payload["id"] == mid


def test_bus_has_no_update_or_delete_api():
    banned = {"update_message", "delete_message", "edit_message"}
    assert not banned & set(dir(Bus))
