import os
from pathlib import Path

import pytest

from context_vis.domain import ContextVisModel
from context_vis.hermes_adapter import HermesContextAdapter
from context_vis.repository import ContextVisRepository
from context_vis.service import ContextVisService
from hermes_state import SessionDB


def _service(
    home: Path,
) -> tuple[SessionDB, ContextVisRepository, ContextVisService, int]:
    db = SessionDB(home / "state.db")
    db.create_session("atomic-dispositions", "cli")
    db.append_message("atomic-dispositions", "user", "one")
    db.append_message("atomic-dispositions", "assistant", "two")
    db.append_message("atomic-dispositions", "user", "three")
    repository = ContextVisRepository(home)
    revision = repository.save(
        "atomic-dispositions",
        ContextVisModel().to_dict(),
        "hermes-msg:3",
    )
    service = ContextVisService(
        HermesContextAdapter(db, "atomic-dispositions", home),
        repository,
    )
    return db, repository, service, revision


def _snapshots(
    home: Path,
    repository: ContextVisRepository,
) -> tuple[dict, bytes, bytes]:
    model, _last = repository.load("atomic-dispositions")
    assert model is not None
    pin_bytes = (
        home / "context-vis" / "pins" / "atomic-dispositions.json"
    ).read_bytes()
    drop_bytes = (
        home / "context-vis" / "drops" / "atomic-dispositions.json"
    ).read_bytes()
    return model, pin_bytes, drop_bytes


def test_stale_revision_leaves_model_and_both_files_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: an already committed keep/drop disposition pair.
    db, repository, service, revision = _service(tmp_path)
    service.request_preserve(
        ["hermes-msg:1"],
        revision,
        ["hermes-msg:2"],
    )
    before = _snapshots(tmp_path, repository)
    monkeypatch.setattr(
        os,
        "replace",
        lambda *_args: pytest.fail("stale CAS must not replace disposition files"),
    )

    # When: a stale client attempts to replace both wholesale sets.
    with pytest.raises(RuntimeError, match="revision_conflict"):
        service.request_preserve(
            ["hermes-msg:3"],
            revision,
            ["hermes-msg:1"],
        )

    # Then: neither durable surface observes the rejected transaction.
    assert _snapshots(tmp_path, repository) == before
    db.close()
    repository.close()


def test_second_replace_failure_rolls_back_files_and_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: an existing transaction and a one-shot failure on its second replace.
    db, repository, service, revision = _service(tmp_path)
    committed = service.request_preserve(
        ["hermes-msg:1"],
        revision,
        ["hermes-msg:2"],
    )
    before = _snapshots(tmp_path, repository)
    real_replace = os.replace
    calls = 0

    def fail_second(source: str | Path, destination: str | Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected second replace failure")
        real_replace(source, destination)

    monkeypatch.setattr(os, "replace", fail_second)

    # When: the pin replace succeeds but the drop replace fails.
    with pytest.raises(OSError, match="injected second replace failure"):
        service.request_preserve(
            ["hermes-msg:3"],
            committed["model"]["revision"],
            ["hermes-msg:1"],
        )

    # Then: rollback restores model/files and removes every staged temp file.
    assert _snapshots(tmp_path, repository) == before
    assert sorted(
        path.name
        for directory in ("pins", "drops")
        for path in (tmp_path / "context-vis" / directory).iterdir()
        if path.is_file()
    ) == [
        "atomic-dispositions.json",
        "atomic-dispositions.json",
    ]
    db.close()
    repository.close()
