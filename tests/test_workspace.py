import re

from crew.workspace import create_workspace, new_run_id


def test_run_id_shape():
    rid = new_run_id()
    assert re.fullmatch(r"\d{8}-\d{6}-[0-9a-f]{4}", rid)


def test_run_ids_unique():
    assert new_run_id() != new_run_id()


def test_create_workspace(tmp_path):
    ws = create_workspace(tmp_path, "20260723-000000-abcd")
    assert ws.is_dir() and ws == tmp_path / "20260723-000000-abcd"
