from crew.bus import Bus
from crew.run import build_run


def test_build_run_seeds_idea_and_wires_crew(tmp_path):
    bus, sched, run_id, workspace = build_run(
        "build fizzbuzz", base_dir=tmp_path, vault_dir=tmp_path / "vault",
        budget=5.0, turn_cap=24,
    )
    assert isinstance(bus, Bus)
    inbox = bus.unread_for(run_id, "architect")
    assert len(inbox) == 1 and inbox[0].kind == "idea" and inbox[0].body == "build fizzbuzz"
    assert workspace.is_dir()
    assert (tmp_path / "data" / "bus.db").exists()
    # Bus DB must live OUTSIDE the run sandbox.
    assert not str(tmp_path / "data").startswith(str(workspace))
