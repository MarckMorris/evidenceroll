# Contributing

## Development

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
./scripts/verify.sh
```

## Change requirements

- Add tests for every behavior change and failure path.
- Keep missing evidence fail-closed.
- Add a new ADR for changes to promotion semantics, event identity, audit integrity, or storage
  guarantees.
- Never present synthetic benchmark results as real-world model evidence.
- Update the project walkthrough when user-visible workflow changes.
- Do not add secrets, production features, labels, model binaries or customer identifiers.

## Pull requests

Describe the problem, invariant affected, tests run, migration/rollback plan, security impact, and
documentation changes. Small, reviewable changes are preferred.
