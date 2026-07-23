import anyio

from crew.bus import Bus
from crew.scheduler import Scheduler
from tests.fakes import FakeAgent


def seed(bus, run_id="r1"):
    bus.append(run_id=run_id, sender="user", recipient="architect",
               kind="idea", subject="idea", body="build fizzbuzz")


def send(bus, run_id, frm, to, kind, body="x"):
    def action(_inbox):
        bus.append(run_id=run_id, sender=frm, recipient=to,
                   kind=kind, subject=kind, body=body)
    return action


def finish(bus, run_id, frm="manager"):
    def action(_inbox):
        bus.append(run_id=run_id, sender=frm, recipient="run",
                   kind="done", subject="done", body="shipped")
        bus.set_status(frm, "done")
    return action


def ask(bus, run_id, frm="architect"):
    def action(_inbox):
        bus.append(run_id=run_id, sender=frm, recipient="user",
                   kind="question", subject="q", body="scope?")
        bus.set_status(frm, "awaiting_human")
    return action


def make_crew(bus, run_id, scripts):
    return {
        name: FakeAgent(name, bus, run_id, scripts.get(name, []))
        for name in ("architect", "coder", "tester", "manager")
    }


def test_happy_path_reaches_finished(tmp_path):
    bus = Bus(tmp_path / "bus.db")
    seed(bus)
    scripts = {
        "architect": [send(bus, "r1", "architect", "coder", "plan")],
        "coder": [send(bus, "r1", "coder", "tester", "ready_for_test")],
        "tester": [send(bus, "r1", "tester", "manager", "test_passed")],
        "manager": [finish(bus, "r1")],
    }
    sched = Scheduler(bus, "r1", make_crew(bus, "r1", scripts))
    result = anyio.run(sched.run)
    assert result.status == "finished"
    assert result.agent_turns == 4
    assert result.total_cost_usd > 0


def test_ask_human_pauses_and_resumes(tmp_path):
    bus = Bus(tmp_path / "bus.db")
    seed(bus)
    answers = []

    def human(question: str) -> str:
        answers.append(question)
        return "small scope please"

    scripts = {
        "architect": [ask(bus, "r1"), send(bus, "r1", "architect", "coder", "plan")],
        "coder": [send(bus, "r1", "coder", "tester", "ready_for_test")],
        "tester": [send(bus, "r1", "tester", "manager", "test_passed")],
        "manager": [finish(bus, "r1")],
    }
    sched = Scheduler(bus, "r1", make_crew(bus, "r1", scripts), human_input=human)
    result = anyio.run(sched.run)
    assert result.status == "finished"
    assert answers == ["scope?"]
    got = bus.messages("r1", kind="answer")
    assert len(got) == 1 and got[0].recipient == "architect"


def test_manager_brake_fires_after_n_failures(tmp_path):
    bus = Bus(tmp_path / "bus.db")
    seed(bus)
    r = "r1"
    scripts = {
        "architect": [send(bus, r, "architect", "coder", "plan")],
        # coder and tester bounce forever
        "coder": [send(bus, r, "coder", "tester", "ready_for_test", body=f"v{i}")
                  for i in range(10)],
        "tester": [send(bus, r, "tester", "coder", "test_failed", body=f"fail{i}")
                   for i in range(10)],
        "manager": [finish(bus, r)],
    }
    sched = Scheduler(bus, r, make_crew(bus, r, scripts), brake_after=3)
    result = anyio.run(sched.run)
    assert result.status == "finished"  # manager was force-woken and finished
    flags = bus.messages(r, kind="flag", recipient="manager")
    assert any(f.sender == "scheduler" for f in flags)


def test_turn_cap_stops_run(tmp_path):
    bus = Bus(tmp_path / "bus.db")
    seed(bus)
    r = "r1"
    scripts = {
        "architect": [send(bus, r, "architect", "coder", "plan")],
        "coder": [send(bus, r, "coder", "tester", "ready_for_test", body=f"v{i}")
                  for i in range(50)],
        "tester": [send(bus, r, "tester", "coder", "test_failed", body=f"f{i}")
                   for i in range(50)],
        "manager": [],  # never finishes
    }
    sched = Scheduler(bus, r, make_crew(bus, r, scripts), turn_cap=6, brake_after=99)
    result = anyio.run(sched.run)
    assert result.status == "turn_cap"
    assert result.agent_turns <= 6


def test_budget_flag_then_manager_closeout(tmp_path):
    bus = Bus(tmp_path / "bus.db")
    seed(bus)
    r = "r1"
    scripts = {
        "architect": [send(bus, r, "architect", "coder", "plan")],
        "coder": [send(bus, r, "coder", "tester", "ready_for_test", body=f"v{i}")
                  for i in range(50)],
        "tester": [send(bus, r, "tester", "coder", "test_failed", body=f"f{i}")
                   for i in range(50)],
        "manager": [finish(bus, r)],
    }
    crew = make_crew(bus, r, scripts)
    for a in crew.values():
        a._cost = 1.0  # blow the budget fast
    sched = Scheduler(bus, r, crew, budget_usd=2.5, brake_after=99)
    result = anyio.run(sched.run)
    assert result.status == "finished"
    flags = bus.messages(r, kind="flag", recipient="manager")
    assert any("budget" in f.subject for f in flags)


def test_stalled_when_no_one_runnable(tmp_path):
    bus = Bus(tmp_path / "bus.db")
    seed(bus)
    # Architect consumes the idea but sends nothing.
    scripts = {"architect": [lambda _inbox: None]}
    sched = Scheduler(bus, "r1", make_crew(bus, "r1", scripts))
    result = anyio.run(sched.run)
    assert result.status == "stalled"
