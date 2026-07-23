from pathlib import Path

from crew.bus import Bus
from crew.report import write_run_record
from crew.scheduler import RunResult


def _setup(tmp_path) -> tuple[Bus, Path]:
    bus = Bus(tmp_path / "bus.db")
    (tmp_path / "vault" / "03-resources").mkdir(parents=True)
    return bus, tmp_path / "vault"


def test_creates_file_with_frontmatter(tmp_path):
    bus, vault = _setup(tmp_path)
    bus.append(run_id="r1", sender="manager", recipient="run",
               kind="done", subject="done", body="Shipped fizzbuzz; 12 tests pass.")
    out = write_run_record(bus, "r1", RunResult("finished", 1.23, 7),
                           tmp_path / "runs" / "r1", vault)
    text = out.read_text(encoding="utf-8")
    assert out.name == "Crew-Runs.md"
    assert text.startswith("---")
    assert "Shipped fizzbuzz" in text
    assert "$1.23" in text and "finished" in text


def test_appends_second_run(tmp_path):
    bus, vault = _setup(tmp_path)
    bus.append(run_id="r1", sender="manager", recipient="run",
               kind="done", subject="done", body="first")
    write_run_record(bus, "r1", RunResult("finished", 1.0, 5), tmp_path / "w1", vault)
    bus.append(run_id="r2", sender="manager", recipient="run",
               kind="done", subject="done", body="second")
    out = write_run_record(bus, "r2", RunResult("finished", 2.0, 6), tmp_path / "w2", vault)
    text = out.read_text(encoding="utf-8")
    assert "first" in text and "second" in text
    assert text.count("## Run") == 2


def test_handles_run_without_done_message(tmp_path):
    bus, vault = _setup(tmp_path)
    out = write_run_record(bus, "r1", RunResult("turn_cap", 3.0, 24),
                           tmp_path / "w", vault)
    assert "turn_cap" in out.read_text(encoding="utf-8")
