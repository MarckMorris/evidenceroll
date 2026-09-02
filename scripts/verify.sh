#!/usr/bin/env bash
set -euo pipefail

python -m ruff check .
python -m ruff format --check .
python -m mypy src
python -m pytest --cov=evidenceroll --cov-report=term-missing
python -m pip_audit --local --skip-editable
python -m build
