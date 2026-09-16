#!/usr/bin/env bash
# Local equivalent of the CI pipeline. Run before pushing.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

echo "== ruff =="
uv run ruff check .

echo "== mypy =="
uv run mypy packages

echo "== import-linter =="
uv run lint-imports

echo "== pytest =="
uv run pytest
