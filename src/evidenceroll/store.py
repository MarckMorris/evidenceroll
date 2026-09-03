"""SQLite event store for releases, paired predictions, feedback, and audit events."""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from evidenceroll.domain import PredictionRecord, Release, ReleaseStage


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class StoreError(RuntimeError):
    """Base persistence failure."""


class NotFoundError(StoreError):
    """Requested object does not exist."""


class FeedbackConflictError(StoreError):
    """A prediction already has a different label."""


class TransitionConflictError(StoreError):
    """The release changed after evidence was evaluated."""


class IdempotencyConflictError(StoreError):
    """An idempotency key was reused for a different prediction request."""


class SQLiteStore:
    """Transactional store for local operation and one supported controller writer."""

    def __init__(self, path: str | Path, audit_hmac_key: str | None = None) -> None:
        self.path = Path(path)
        self._audit_hmac_key = audit_hmac_key.encode() if audit_hmac_key else None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.Lock()
        self._initialize()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        statements = """
        PRAGMA journal_mode = WAL;
        CREATE TABLE IF NOT EXISTS releases (
            id TEXT PRIMARY KEY,
            champion_version TEXT NOT NULL,
            challenger_version TEXT NOT NULL,
            stage TEXT NOT NULL,
            canary_weight INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_decision TEXT,
            revision INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS predictions (
            id TEXT PRIMARY KEY,
            release_id TEXT NOT NULL REFERENCES releases(id),
            entity_id TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            release_stage TEXT NOT NULL,
            features_json TEXT NOT NULL,
            served_version TEXT NOT NULL,
            champion_score REAL,
            challenger_score REAL,
            champion_prediction INTEGER,
            challenger_prediction INTEGER,
            champion_latency_ms REAL,
            challenger_latency_ms REAL,
            request_hash TEXT NOT NULL,
            pending_role TEXT,
            shadow_error TEXT,
            completed_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_predictions_release_stage
            ON predictions(release_id, release_stage, observed_at);
        CREATE TABLE IF NOT EXISTS feedback (
            prediction_id TEXT PRIMARY KEY REFERENCES predictions(id),
            label INTEGER NOT NULL CHECK(label IN (0, 1)),
            observed_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS audit_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            release_id TEXT NOT NULL REFERENCES releases(id),
            event_type TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            previous_hash TEXT NOT NULL,
            event_hash TEXT NOT NULL,
            hash_algorithm TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_audit_release ON audit_events(release_id, id);
        """
        with self._connection() as connection:
            connection.executescript(statements)
            connection.commit()
        self._migrate_pending_shadow_columns()

    def _migrate_pending_shadow_columns(self) -> None:
        """Rebuild a pre-background-scoring predictions table so the shadow side can be null."""
        connection = sqlite3.connect(self.path, timeout=10.0)
        connection.row_factory = sqlite3.Row
        try:
            columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(predictions)").fetchall()
            }
            if not columns or "pending_role" in columns:
                return
            connection.execute("PRAGMA foreign_keys = OFF")
            connection.executescript(
                """
                BEGIN IMMEDIATE;
                CREATE TABLE predictions_migrated (
                    id TEXT PRIMARY KEY,
                    release_id TEXT NOT NULL REFERENCES releases(id),
                    entity_id TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    release_stage TEXT NOT NULL,
                    features_json TEXT NOT NULL,
                    served_version TEXT NOT NULL,
                    champion_score REAL,
                    challenger_score REAL,
                    champion_prediction INTEGER,
                    challenger_prediction INTEGER,
                    champion_latency_ms REAL,
                    challenger_latency_ms REAL,
                    request_hash TEXT NOT NULL,
                    pending_role TEXT,
                    shadow_error TEXT,
                    completed_at TEXT
                );
                INSERT INTO predictions_migrated
                    (id, release_id, entity_id, observed_at, release_stage, features_json,
                     served_version, champion_score, challenger_score, champion_prediction,
                     challenger_prediction, champion_latency_ms, challenger_latency_ms,
                     request_hash, pending_role, shadow_error, completed_at)
                SELECT id, release_id, entity_id, observed_at, release_stage, features_json,
                       served_version, champion_score, challenger_score, champion_prediction,
                       challenger_prediction, champion_latency_ms, challenger_latency_ms,
                       request_hash, NULL, NULL, observed_at
                FROM predictions;
                DROP TABLE predictions;
                ALTER TABLE predictions_migrated RENAME TO predictions;
                CREATE INDEX IF NOT EXISTS idx_predictions_release_stage
                    ON predictions(release_id, release_stage, observed_at);
                COMMIT;
                """
            )
            connection.execute("PRAGMA foreign_keys = ON")
        finally:
            connection.close()

    def create_release(
        self,
        champion_version: str,
        challenger_version: str,
        release_id: str | None = None,
    ) -> Release:
        now = utc_now()
        identifier = release_id or f"rel-{uuid4().hex[:12]}"
        release = Release(
            id=identifier,
            champion_version=champion_version,
            challenger_version=challenger_version,
            stage=ReleaseStage.SHADOW,
            canary_weight=0,
            created_at=now,
            updated_at=now,
        )
        with self._write_lock, self._connection() as connection:
            try:
                connection.execute(
                    """INSERT INTO releases
                    (id, champion_version, challenger_version, stage, canary_weight,
                     created_at, updated_at, last_decision, revision)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        release.id,
                        release.champion_version,
                        release.challenger_version,
                        release.stage.value,
                        release.canary_weight,
                        release.created_at,
                        release.updated_at,
                        release.last_decision,
                        release.revision,
                    ),
                )
                self._insert_audit(
                    connection, release.id, "release.created", release.to_dict(), now
                )
                connection.commit()
            except sqlite3.IntegrityError as exc:
                raise StoreError(f"release already exists: {identifier}") from exc
        return release

    def get_release(self, release_id: str) -> Release:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM releases WHERE id = ?", (release_id,)
            ).fetchone()
        if row is None:
            raise NotFoundError(f"release not found: {release_id}")
        return self._release_from_row(row)

    def active_release_ids(self) -> list[str]:
        placeholders = (ReleaseStage.SHADOW.value, ReleaseStage.CANARY.value)
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT id FROM releases WHERE stage IN (?, ?) ORDER BY created_at", placeholders
            ).fetchall()
        return [str(row["id"]) for row in rows]

    def update_release(
        self,
        release_id: str,
        stage: ReleaseStage,
        canary_weight: int,
        last_decision: str,
        expected_revision: int,
        *,
        audit_event_type: str | None = None,
        audit_payload: dict[str, Any] | None = None,
    ) -> Release:
        if (audit_event_type is None) != (audit_payload is None):
            raise ValueError("audit_event_type and audit_payload must be provided together")
        now = utc_now()
        with self._write_lock, self._connection() as connection:
            cursor = connection.execute(
                """UPDATE releases SET stage = ?, canary_weight = ?, updated_at = ?,
                   last_decision = ?, revision = revision + 1
                   WHERE id = ? AND revision = ?""",
                (
                    stage.value,
                    canary_weight,
                    now,
                    last_decision,
                    release_id,
                    expected_revision,
                ),
            )
            if cursor.rowcount != 1:
                exists = connection.execute(
                    "SELECT 1 FROM releases WHERE id = ?", (release_id,)
                ).fetchone()
                if exists is None:
                    raise NotFoundError(f"release not found: {release_id}")
                raise TransitionConflictError(
                    f"release {release_id} changed while evidence was evaluated"
                )
            if audit_event_type is not None and audit_payload is not None:
                self._insert_audit(
                    connection,
                    release_id,
                    audit_event_type,
                    audit_payload,
                    now,
                )
            connection.commit()
        return self.get_release(release_id)

    def add_prediction(self, record: PredictionRecord) -> None:
        with self._write_lock, self._connection() as connection:
            try:
                connection.execute(
                    """INSERT INTO predictions
                    (id, release_id, entity_id, observed_at, release_stage, features_json,
                     served_version, champion_score, challenger_score, champion_prediction,
                     challenger_prediction, champion_latency_ms, challenger_latency_ms,
                     request_hash, pending_role, shadow_error, completed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        record.id,
                        record.release_id,
                        record.entity_id,
                        record.observed_at,
                        record.release_stage.value,
                        json.dumps(record.features, sort_keys=True, separators=(",", ":")),
                        record.served_version,
                        record.champion_score,
                        record.challenger_score,
                        record.champion_prediction,
                        record.challenger_prediction,
                        record.champion_latency_ms,
                        record.challenger_latency_ms,
                        record.request_hash,
                        record.pending_role,
                        record.shadow_error,
                        None if record.pending_role else utc_now(),
                    ),
                )
                connection.commit()
            except sqlite3.IntegrityError as exc:
                raise StoreError(f"could not store prediction {record.id}") from exc

    def get_prediction(self, prediction_id: str) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM predictions WHERE id = ?", (prediction_id,)
            ).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["features"] = json.loads(item.pop("features_json"))
        return item

    def complete_shadow_score(
        self,
        prediction_id: str,
        role: str,
        score: float,
        prediction: int,
        latency_ms: float,
    ) -> None:
        """Attach the background-scored side of a pair; only a pending row can be completed."""
        if role not in {"champion", "challenger"}:
            raise ValueError(f"unknown scoring role: {role}")
        query = f"""UPDATE predictions
            SET {role}_score = ?, {role}_prediction = ?, {role}_latency_ms = ?,
                pending_role = NULL, shadow_error = NULL, completed_at = ?
            WHERE id = ? AND pending_role = ?"""
        with self._write_lock, self._connection() as connection:
            cursor = connection.execute(
                query, (score, prediction, latency_ms, utc_now(), prediction_id, role)
            )
            if cursor.rowcount != 1:
                raise NotFoundError(f"no prediction pending {role} scoring: {prediction_id}")
            connection.commit()

    def fail_shadow_score(self, prediction_id: str, message: str) -> None:
        """Mark a pair as permanently incomplete so it never enters an evidence window."""
        with self._write_lock, self._connection() as connection:
            connection.execute(
                "UPDATE predictions SET shadow_error = ? WHERE id = ? AND pending_role IS NOT NULL",
                (message[:500], prediction_id),
            )
            connection.commit()

    def incomplete_prediction_counts(self, release_id: str) -> dict[str, int]:
        """Pairs excluded from evidence: still pending, or abandoned after a scoring failure."""
        with self._connection() as connection:
            row = connection.execute(
                """SELECT
                     SUM(CASE WHEN pending_role IS NOT NULL AND shadow_error IS NULL
                              THEN 1 ELSE 0 END) AS pending,
                     SUM(CASE WHEN shadow_error IS NOT NULL THEN 1 ELSE 0 END) AS failed
                   FROM predictions WHERE release_id = ?""",
                (release_id,),
            ).fetchone()
        return {"pending": int(row["pending"] or 0), "failed": int(row["failed"] or 0)}

    def add_feedback(self, prediction_id: str, label: int) -> bool:
        """Insert feedback; return True when the same feedback already existed."""
        now = utc_now()
        with self._write_lock, self._connection() as connection:
            prediction = connection.execute(
                "SELECT id FROM predictions WHERE id = ?", (prediction_id,)
            ).fetchone()
            if prediction is None:
                raise NotFoundError(f"prediction not found: {prediction_id}")
            existing = connection.execute(
                "SELECT label FROM feedback WHERE prediction_id = ?", (prediction_id,)
            ).fetchone()
            if existing is not None:
                if int(existing["label"]) != label:
                    raise FeedbackConflictError(
                        f"prediction {prediction_id} already has a different label"
                    )
                return True
            connection.execute(
                "INSERT INTO feedback (prediction_id, label, observed_at) VALUES (?, ?, ?)",
                (prediction_id, label, now),
            )
            connection.commit()
        return False

    def release_for_prediction(self, prediction_id: str) -> str:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT release_id FROM predictions WHERE id = ?", (prediction_id,)
            ).fetchone()
        if row is None:
            raise NotFoundError(f"prediction not found: {prediction_id}")
        return str(row["release_id"])

    def observations(self, release_id: str, stage: ReleaseStage) -> list[dict[str, Any]]:
        """Complete pairs only: a half-scored request is not evidence about the release delta."""
        query = """
        SELECT p.*, f.label, f.observed_at AS feedback_at
        FROM predictions AS p
        LEFT JOIN feedback AS f ON f.prediction_id = p.id
        WHERE p.release_id = ? AND p.release_stage = ?
          AND p.pending_role IS NULL AND p.shadow_error IS NULL
          AND p.champion_score IS NOT NULL AND p.challenger_score IS NOT NULL
        ORDER BY p.observed_at, p.id
        """
        with self._connection() as connection:
            rows = connection.execute(query, (release_id, stage.value)).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["features"] = json.loads(item.pop("features_json"))
            result.append(item)
        return result

    def append_audit(self, release_id: str, event_type: str, payload: dict[str, Any]) -> None:
        with self._write_lock, self._connection() as connection:
            self._insert_audit(connection, release_id, event_type, payload, utc_now())
            connection.commit()

    def audit_events(self, release_id: str) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM audit_events WHERE release_id = ? ORDER BY id", (release_id,)
            ).fetchall()
        return [
            {
                "id": int(row["id"]),
                "release_id": str(row["release_id"]),
                "event_type": str(row["event_type"]),
                "payload": json.loads(row["payload_json"]),
                "created_at": str(row["created_at"]),
                "previous_hash": str(row["previous_hash"]),
                "event_hash": str(row["event_hash"]),
                "hash_algorithm": str(row["hash_algorithm"]),
            }
            for row in rows
        ]

    def verify_audit_chain(self, release_id: str) -> dict[str, Any]:
        events = self.audit_events(release_id)
        previous_hash = "0" * 64
        for event in events:
            if event["previous_hash"] != previous_hash:
                return {
                    "valid": False,
                    "event_count": len(events),
                    "failed_event_id": event["id"],
                    "last_hash": previous_hash,
                }
            core = self._audit_core(
                release_id=event["release_id"],
                event_type=event["event_type"],
                payload=event["payload"],
                created_at=event["created_at"],
                previous_hash=previous_hash,
            )
            expected = self._event_hash(core)
            if not hmac.compare_digest(expected, event["event_hash"]):
                return {
                    "valid": False,
                    "event_count": len(events),
                    "failed_event_id": event["id"],
                    "last_hash": previous_hash,
                }
            previous_hash = event["event_hash"]
        return {
            "valid": True,
            "event_count": len(events),
            "failed_event_id": None,
            "last_hash": previous_hash,
            "hash_algorithm": "hmac-sha256" if self._audit_hmac_key else "sha256",
        }

    def _insert_audit(
        self,
        connection: sqlite3.Connection,
        release_id: str,
        event_type: str,
        payload: dict[str, Any],
        created_at: str,
    ) -> None:
        previous = connection.execute(
            "SELECT event_hash FROM audit_events WHERE release_id = ? ORDER BY id DESC LIMIT 1",
            (release_id,),
        ).fetchone()
        previous_hash = str(previous["event_hash"]) if previous else "0" * 64
        core = self._audit_core(release_id, event_type, payload, created_at, previous_hash)
        event_hash = self._event_hash(core)
        connection.execute(
            """INSERT INTO audit_events
            (release_id, event_type, payload_json, created_at, previous_hash, event_hash,
             hash_algorithm) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                release_id,
                event_type,
                json.dumps(payload, sort_keys=True, separators=(",", ":")),
                created_at,
                previous_hash,
                event_hash,
                "hmac-sha256" if self._audit_hmac_key else "sha256",
            ),
        )

    @staticmethod
    def _audit_core(
        release_id: str,
        event_type: str,
        payload: dict[str, Any],
        created_at: str,
        previous_hash: str,
    ) -> bytes:
        canonical = json.dumps(
            {
                "release_id": release_id,
                "event_type": event_type,
                "payload": payload,
                "created_at": created_at,
                "previous_hash": previous_hash,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return canonical.encode()

    def _event_hash(self, core: bytes) -> str:
        if self._audit_hmac_key:
            return hmac.new(self._audit_hmac_key, core, hashlib.sha256).hexdigest()
        return hashlib.sha256(core).hexdigest()

    @staticmethod
    def _release_from_row(row: sqlite3.Row) -> Release:
        return Release(
            id=str(row["id"]),
            champion_version=str(row["champion_version"]),
            challenger_version=str(row["challenger_version"]),
            stage=ReleaseStage(str(row["stage"])),
            canary_weight=int(row["canary_weight"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            last_decision=str(row["last_decision"]) if row["last_decision"] else None,
            revision=int(row["revision"]),
        )
