"""Unit tests for DreamDiff round-trip serialisation and dream CLI subcommands."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from pytest import CaptureFixture

import cellin.cli.app as app_module
from cellin.cli.app import main
from cellin.cli.config import DEFAULT_CONFIG_FILENAME
from cellin.core import (
    DecayState,
    DreamArtifact,
    EdgeKind,
    MemoryAtom,
    MemoryEdge,
    MemoryKind,
    Modality,
    Provenance,
    RetrievalStats,
)
from cellin.dreaming.models import DreamDiff, DreamEdgeChange, DreamMemoryChange, DreamRunResult
from cellin.runtime.storage import StorageConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 10, 12, 0, 0, tzinfo=UTC)


def _atom(memory_id: str, trust_score: float = 1.0, archived: bool = False) -> MemoryAtom:
    return MemoryAtom(
        memory_id=memory_id,
        kind=MemoryKind.ATOM,
        text=f"{memory_id} text",
        provenance=Provenance(source_id=memory_id, source_type="test"),
        modality=Modality.TEXT,
        created_at=_NOW,
        observed_at=_NOW,
        trust_score=trust_score,
        decay=DecayState(archived=archived),
        retrieval=RetrievalStats(),
    )


def _edge(edge_id: str, source: str = "a", target: str = "b") -> MemoryEdge:
    return MemoryEdge(
        edge_id=edge_id,
        source_id=source,
        target_id=target,
        kind=EdgeKind.SUPPORTS,
        provenance=Provenance(source_id=edge_id, source_type="test"),
        created_at=_NOW,
    )


def _make_diff() -> DreamDiff:
    before_atom = _atom("mem-a", trust_score=0.9)
    after_atom = _atom("mem-a", trust_score=0.6)
    archived_atom = _atom("mem-b", archived=True)
    edge = _edge("edge-1")

    return DreamDiff(
        run_id="run-test-001",
        strategy_name="abstraction",
        created_at=_NOW,
        memory_changes=(
            DreamMemoryChange(memory_id="mem-a", before=before_atom, after=after_atom),
            DreamMemoryChange(memory_id="mem-b", before=None, after=archived_atom),
        ),
        edge_changes=(DreamEdgeChange(edge_id="edge-1", before=None, after=edge),),
        notes={"test": True},
    )


# ---------------------------------------------------------------------------
# Round-trip tests
# ---------------------------------------------------------------------------


def test_dream_diff_from_dict_round_trip_equality() -> None:
    original = _make_diff()
    d = original.to_dict()
    restored = DreamDiff.from_dict(d)

    assert restored.run_id == original.run_id
    assert restored.strategy_name == original.strategy_name
    assert restored.created_at == original.created_at
    assert len(restored.memory_changes) == len(original.memory_changes)
    assert len(restored.edge_changes) == len(original.edge_changes)
    assert restored.notes == original.notes


def test_dream_diff_from_dict_preserves_memory_change_fields() -> None:
    original = _make_diff()
    restored = DreamDiff.from_dict(original.to_dict())

    mem_a = restored.memory_changes[0]
    assert mem_a.memory_id == "mem-a"
    assert mem_a.before is not None
    assert mem_a.after is not None
    assert mem_a.before.trust_score == pytest.approx(0.9)
    assert mem_a.after.trust_score == pytest.approx(0.6)


def test_dream_diff_from_dict_preserves_edge_change_fields() -> None:
    original = _make_diff()
    restored = DreamDiff.from_dict(original.to_dict())

    edge_change = restored.edge_changes[0]
    assert edge_change.edge_id == "edge-1"
    assert edge_change.before is None
    assert edge_change.after is not None
    assert edge_change.after.source_id == "a"
    assert edge_change.after.target_id == "b"


def test_dream_diff_from_dict_preserves_none_before() -> None:
    original = _make_diff()
    restored = DreamDiff.from_dict(original.to_dict())

    mem_b = restored.memory_changes[1]
    assert mem_b.memory_id == "mem-b"
    assert mem_b.before is None
    assert mem_b.after is not None
    assert mem_b.after.decay.archived is True


def test_dream_diff_to_dict_round_trip_is_json_stable() -> None:
    original = _make_diff()
    serialised = json.dumps(original.to_dict(), sort_keys=True)
    restored = DreamDiff.from_dict(json.loads(serialised))
    assert json.dumps(restored.to_dict(), sort_keys=True) == serialised


# ---------------------------------------------------------------------------
# CLI dream inspect tests
# ---------------------------------------------------------------------------


def test_cli_dream_inspect_prints_summary(tmp_path: Path, capsys: CaptureFixture[str]) -> None:
    diff = _make_diff()
    diff_path = tmp_path / "diff.json"
    diff_path.write_text(json.dumps(diff.to_dict(), indent=2), encoding="utf-8")

    exit_code = main(["dream", "inspect", str(diff_path)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "run_id=run-test-001" in output
    assert "strategy=abstraction" in output
    assert "memory_changes=2" in output
    assert "edge_changes=1" in output
    assert "archived_count=1" in output
    assert "mem-b" in output


def test_cli_dream_inspect_shows_trust_adjusted_ids(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    diff = _make_diff()
    diff_path = tmp_path / "diff.json"
    diff_path.write_text(json.dumps(diff.to_dict(), indent=2), encoding="utf-8")

    main(["dream", "inspect", str(diff_path)])
    output = capsys.readouterr().out

    # mem-a has trust_score changed from 0.9 to 0.6
    assert "trust_adjusted_count=1" in output
    assert "mem-a" in output


# ---------------------------------------------------------------------------
# CLI dream rollback tests
# ---------------------------------------------------------------------------


def test_cli_dream_rollback_calls_runner_rollback(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    workspace = tmp_path / "workspace"
    config_path = workspace / DEFAULT_CONFIG_FILENAME
    main(["init", "--workspace", str(workspace)])
    capsys.readouterr()

    diff = _make_diff()
    diff_path = tmp_path / "diff.json"
    diff_path.write_text(json.dumps(diff.to_dict(), indent=2), encoding="utf-8")

    rollback_called_with = []

    def fake_rollback(self: object, d: DreamDiff) -> None:
        rollback_called_with.append(d)

    with patch.object(app_module.DreamRunner, "rollback", fake_rollback):
        exit_code = main(
            [
                "dream",
                "rollback",
                "--config",
                str(config_path),
                "--diff-file",
                str(diff_path),
            ]
        )

    output = capsys.readouterr().out

    assert exit_code == 0
    assert len(rollback_called_with) == 1
    assert rollback_called_with[0].run_id == "run-test-001"
    assert "rolled back run_id=run-test-001" in output


def test_cli_dream_run_writes_diff_out(tmp_path: Path, capsys: CaptureFixture[str]) -> None:
    """Verify --diff-out writes a JSON file when a dream run produces a result."""
    workspace = tmp_path / "workspace"
    config_path = workspace / DEFAULT_CONFIG_FILENAME
    diff_path = tmp_path / "out.diff.json"

    main(["init", "--workspace", str(workspace)])
    capsys.readouterr()

    fake_diff = _make_diff()
    fake_artifact = DreamArtifact(
        dream_id="dream-test-001",
        strategy_name="abstraction",
        provenance=Provenance(source_id="test", source_type="test"),
        created_at=_NOW,
        summary="test dream",
        affected_memory_ids=("mem-a",),
    )
    fake_result = DreamRunResult(artifact=fake_artifact, diff=fake_diff)

    def fake_run_strategy(self: object, strategy_name: str, **kwargs: object) -> DreamRunResult:
        return fake_result

    with patch.object(app_module.DreamRunner, "run_strategy", fake_run_strategy):
        exit_code = main(
            [
                "dream",
                "run",
                "--config",
                str(config_path),
                "--strategy",
                "abstraction",
                "--diff-out",
                str(diff_path),
            ]
        )

    output = capsys.readouterr().out

    assert exit_code == 0
    assert diff_path.exists()
    assert f"diff written to {diff_path}" in output
    raw = json.loads(diff_path.read_text(encoding="utf-8"))
    assert raw["run_id"] == "run-test-001"
    assert raw["strategy_name"] == "abstraction"


def test_resolve_eval_storage_config_in_memory() -> None:
    """Verify _resolve_eval_storage_config maps 'in_memory' to the in-memory preset."""
    config = app_module._resolve_eval_storage_config("in_memory")
    assert config is not None
    assert config == StorageConfig.with_in_memory_preset()


def test_eval_run_with_in_memory_backend(tmp_path: Path, capsys: CaptureFixture[str]) -> None:
    """Verify cellin eval run --backend in_memory succeeds and records backend in results."""
    workspace = tmp_path / "workspace"
    config_path = workspace / DEFAULT_CONFIG_FILENAME
    output_path = tmp_path / "eval.json"

    main(["init", "--workspace", str(workspace)])
    capsys.readouterr()

    exit_code = main(
        [
            "eval",
            "run",
            "--suite",
            "smoke",
            "--backend",
            "in_memory",
            "--config",
            str(config_path),
            "--output",
            str(output_path),
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "status=ok" in output
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    ingest_case = next(c for c in payload["cases"] if c["case_id"] == "ingest-multimodal")
    assert ingest_case["backend"] == "in_memory"
