#!/usr/bin/env bash
set -euo pipefail

python -m evidenceroll.cli simulate --scenario healthy --reset
python -m evidenceroll.cli benchmark --output benchmark-results.json
