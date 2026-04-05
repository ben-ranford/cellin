"""Regression tests for eval asset loading hardening."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from cellin.evals import assets


def test_load_memory_records_rejects_traversal_outside_evals_tree() -> None:
    with pytest.raises(ValueError, match="outside"):
        assets.load_memory_records("../pyproject.toml")


def test_load_memory_corpus_rejects_corpus_name_traversal() -> None:
    with pytest.raises(ValueError, match="outside"):
        assets.load_memory_corpus("../fixtures/dreaming/atlas_corpus")


def test_load_envelope_corpus_rejects_corpus_name_traversal() -> None:
    with pytest.raises(ValueError, match="outside"):
        assets.load_envelope_corpus("../fixtures/dreaming/atlas_corpus")


def test_load_memory_corpus_schema_validation_raises_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(assets, "_load_corpus_json", lambda _: {"unexpected": "mapping"})

    with pytest.raises(ValueError, match="JSON list"):
        assets.load_memory_corpus("project_memory")


def test_load_envelope_corpus_schema_validation_raises_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        assets,
        "_load_corpus_json",
        lambda _: [
            {
                "envelope_id": "bad-envelope",
                "modality": "text",
                "payload": "payload",
                "source_id": "source",
                "source_type": "fixture",
                "observed_at": "2026-04-01T10:00:00+00:00",
                "metadata": "not-a-mapping",
            }
        ],
    )

    with pytest.raises(ValueError, match="metadata has invalid type"):
        assets.load_envelope_corpus("multimodal_artifacts")


def test_schema_validation_still_fails_under_python_optimized_mode(tmp_path: Path) -> None:
    corpus_root = tmp_path / "evals" / "corpora"
    corpus_root.mkdir(parents=True)
    (corpus_root / "bad_memory.json").write_text(
        json.dumps({"unexpected": "mapping"}),
        encoding="utf-8",
    )
    (corpus_root / "bad_envelope.json").write_text(
        json.dumps(
            [
                {
                    "envelope_id": "bad-envelope",
                    "modality": "text",
                    "payload": "payload",
                    "source_id": "source",
                    "source_type": "fixture",
                    "observed_at": "2026-04-01T10:00:00+00:00",
                    "metadata": "not-a-mapping",
                }
            ]
        ),
        encoding="utf-8",
    )
    script = f"""
from pathlib import Path
from cellin.evals import assets

assets._repo_root = lambda: Path({str(tmp_path)!r})

def expect_failure(callable_):
    try:
        callable_()
    except ValueError:
        return
    raise RuntimeError("expected ValueError")

expect_failure(lambda: assets.load_memory_records("evals/corpora/bad_memory.json"))
expect_failure(lambda: assets.load_envelope_corpus("bad_envelope"))
"""
    env = dict(os.environ)
    src_path = str(Path(__file__).resolve().parents[2] / "src")
    current_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        src_path if not current_pythonpath else f"{src_path}{os.pathsep}{current_pythonpath}"
    )
    result = subprocess.run(
        [sys.executable, "-O", "-c", script],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0, result.stderr
