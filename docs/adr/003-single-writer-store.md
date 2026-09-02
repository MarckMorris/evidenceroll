# ADR-003: Ship a single-writer control plane in v0.1.0

**Status:** accepted with migration boundary  
**Date:** 2026-09-02

## Context

An executable local proof must require no external database. SQLite provides transactional joins,
unique constraints and a durable audit record with almost no setup. It does not provide a safe
shared writable volume for horizontally scaled controller replicas.

## Decision

Version `0.1.0` supports one EvidenceRoll writer. Kubernetes enforces one replica, `Recreate`, and a
`ReadWriteOnce` PVC. Release revisions still use optimistic concurrency to protect concurrent
threads, manual calls and an in-process reconciler.

## Consequences

- Local, Docker and one-replica Kubernetes paths run the same persistence code.
- Controller HA and multi-region writes are explicitly outside the release claim.
- Remote inference services can scale independently.
- A future store interface should move events to PostgreSQL, use transactional outbox semantics,
  acquire per-release leases, and preserve the current conflict/idempotency contract.

## Migration acceptance criteria

1. PostgreSQL integration tests run against an actual server.
2. Two reconcilers cannot commit the same revision.
3. prediction and feedback idempotency hold under concurrent writers.
4. preserve the existing atomic audit-event and release-transition contract.
5. load and failover tests publish measured limits.
