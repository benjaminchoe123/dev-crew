import anyio

from crew.bus import Bus
from crew.report import write_run_record
from crew.scheduler import Scheduler
from tests.fakes import FakeAgent


def test_full_run_produces_record(tmp_path):
    (tmp_path / "vault" / "03-resources").mkdir(parents=True)
    bus = Bus(tmp_path / "bus.db")
    r = "r1"
    bus.append(run_id=r, sender="user", recipient="architect",
               kind="idea", subject="idea", body="fizzbuzz")

    def relay(frm, to, kind):
        def action(_inbox):
            bus.append(run_id=r, sender=frm, recipient=to, kind=kind,
                       subject=kind, body=kind)
        return action

    def finish(_inbox):
        bus.append(run_id=r, sender="manager", recipient="run",
                   kind="done", subject="done", body="shipped fizzbuzz")
        bus.set_status("manager", "done")

    agents = {
        "architect": FakeAgent("architect", bus, r, [relay("architect", "coder", "plan")]),
        "coder": FakeAgent("coder", bus, r, [relay("coder", "tester", "ready_for_test")]),
        "tester": FakeAgent("tester", bus, r, [relay("tester", "manager", "test_passed")]),
        "manager": FakeAgent("manager", bus, r, [finish]),
    }
    result = anyio.run(Scheduler(bus, r, agents).run)
    out = write_run_record(bus, r, result, tmp_path / "runs" / r, tmp_path / "vault")
    assert result.status == "finished"
    assert "shipped fizzbuzz" in out.read_text(encoding="utf-8")
