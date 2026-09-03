from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from evidenceroll.domain import PredictionRecord, ReleaseStage
from evidenceroll.store import (
    FeedbackConflictError,
    NotFoundError,
    SQLiteStore,
    TransitionConflictError,
)


def record(release_id: str) -> PredictionRecord:
    return PredictionRecord(
        id="pred-one",
        release_id=release_id,
        entity_id="customer-1",
        observed_at="2026-09-02T12:00:00+00:00",
        release_stage=ReleaseStage.SHADOW,
        features={"x": 1.0},
        served_version="champion",
        champion_score=0.2,
        challenger_score=0.3,
        champion_prediction=0,
        challenger_prediction=0,
        champion_latency_ms=1.0,
        challenger_latency_ms=1.2,
        request_hash="a" * 64,
    )


def test_feedback_is_idempotent_but_conflicts_fail(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "events.db")
    release = store.create_release("champion", "challenger", "release-one")
    store.add_prediction(record(release.id))
    assert store.add_feedback("pred-one", 1) is False
    assert store.add_feedback("pred-one", 1) is True
    with pytest.raises(FeedbackConflictError):
        store.add_feedback("pred-one", 0)


def test_release_transition_uses_optimistic_revision(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "events.db")
    release = store.create_release("champion", "challenger", "release-one")
    updated = store.update_release(
        release.id,
        ReleaseStage.CANARY,
        10,
        "start_canary",
        expected_revision=0,
    )
    assert updated.revision == 1
    with pytest.raises(TransitionConflictError):
        store.update_release(
            release.id,
            ReleaseStage.PROMOTED,
            100,
            "promote",
            expected_revision=0,
        )


def test_transition_and_audit_event_are_atomic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = SQLiteStore(tmp_path / "events.db")
    release = store.create_release("champion", "challenger", "release-one")

    def fail_audit(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("injected audit failure")

    monkeypatch.setattr(store, "_insert_audit", fail_audit)
    with pytest.raises(RuntimeError, match="injected audit failure"):
        store.update_release(
            release.id,
            ReleaseStage.CANARY,
            10,
            "start_canary",
            expected_revision=0,
            audit_event_type="release.decision",
            audit_payload={"action": "start_canary"},
        )
    unchanged = store.get_release(release.id)
    assert unchanged.stage is ReleaseStage.SHADOW
    assert unchanged.revision == 0


def test_audit_chain_detects_database_tampering(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "events.db", audit_hmac_key="test-key")
    release = store.create_release("champion", "challenger", "release-one")
    store.append_audit(release.id, "test.event", {"value": 1})
    assert store.verify_audit_chain(release.id)["valid"] is True
    with store._connection() as connection:
        connection.execute("UPDATE audit_events SET payload_json = '{\"value\":2}' WHERE id = 2")
        connection.commit()
    result = store.verify_audit_chain(release.id)
    assert result["valid"] is False
    assert result["failed_event_id"] == 2


def test_missing_objects_are_not_silently_created(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "events.db")
    with pytest.raises(NotFoundError):
        store.get_release("missing")
    with pytest.raises(NotFoundError):
        store.add_feedback("missing", 1)


def test_legacy_database_is_migrated_to_nullable_shadow_columns(tmp_path: Path) -> None:
    """A 0.1.0 database keeps its rows when the pending-shadow columns are introduced."""
    database = tmp_path / "legacy.db"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE releases (
            id TEXT PRIMARY KEY, champion_version TEXT NOT NULL,
            challenger_version TEXT NOT NULL, stage TEXT NOT NULL,
            canary_weight INTEGER NOT NULL, created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL, last_decision TEXT, revision INTEGER NOT NULL);
        CREATE TABLE predictions (
            id TEXT PRIMARY KEY, release_id TEXT NOT NULL REFERENCES releases(id),
            entity_id TEXT NOT NULL, observed_at TEXT NOT NULL, release_stage TEXT NOT NULL,
            features_json TEXT NOT NULL, served_version TEXT NOT NULL,
            champion_score REAL NOT NULL, challenger_score REAL NOT NULL,
            champion_prediction INTEGER NOT NULL, challenger_prediction INTEGER NOT NULL,
            champion_latency_ms REAL NOT NULL, challenger_latency_ms REAL NOT NULL,
            request_hash TEXT NOT NULL);
        CREATE TABLE feedback (
            prediction_id TEXT PRIMARY KEY REFERENCES predictions(id),
            label INTEGER NOT NULL CHECK(label IN (0, 1)), observed_at TEXT NOT NULL);
        INSERT INTO releases VALUES
            ('rel-legacy', 'champion', 'challenger', 'shadow', 0,
             '2026-09-02T12:00:00+00:00', '2026-09-02T12:00:00+00:00', NULL, 0);
        INSERT INTO predictions VALUES
            ('pred-legacy', 'rel-legacy', 'customer-1', '2026-09-02T12:00:00+00:00', 'shadow',
             '{"x":1.0}', 'champion', 0.2, 0.3, 0, 0, 1.0, 1.2, 'hash-legacy');
        INSERT INTO feedback VALUES ('pred-legacy', 1, '2026-09-02T12:30:00+00:00');
        """
    )
    connection.commit()
    connection.close()

    store = SQLiteStore(database)
    stored = store.get_prediction("pred-legacy")
    assert stored is not None
    assert stored["pending_role"] is None
    assert stored["challenger_score"] == 0.3
    assert len(store.observations("rel-legacy", ReleaseStage.SHADOW)) == 1

    with pytest.raises(NotFoundError):
        store.complete_shadow_score("pred-legacy", "challenger", 0.4, 0, 1.0)
