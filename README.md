# CIP — Consultation Intelligence Platform

A uv workspace built as ports and adapters (see [ADR 0001](docs/adr/0001-ports-and-adapters-workspace.md)).
`cip-core` defines the system's ports as `Protocol`s and depends on
nothing else here; every other package depends on it, directly or
transitively. Nothing outside `cip-bootstrap` decides which concrete
adapter answers a port - it exposes one cached factory per port, each
branching on `CIP_RUN_MODE`:

```python
from cip.bootstrap import inference, vector_store

store = vector_store()  # InMemoryVectorStore when CIP_RUN_MODE=offline
model = inference()  # FixtureInference when CIP_RUN_MODE=offline
```

## Layout

| Package           | Depends on               | Role                                                          |
| ------------------ | ------------------------- | -------------------------------------------------------------- |
| `packages/core`       | —                          | Ports, domain model, config. Depends on nothing.                |
| `packages/retrieval`  | core                       | Embeddings, vector search, BM25, citation resolver.              |
| `packages/ingestion`  | core                       | Parsing, cleaning and chunking of raw consultation documents.    |
| `packages/tools`      | core                       | The functions an agent can call, exposed over MCP.               |
| `packages/agents`     | core                       | The orchestration loop that calls a model and its tools.         |
| `packages/evaluation` | core                       | Runs recorded scenarios against the agent loop, scores them.     |
| `packages/api`        | core                       | The HTTP surface that exposes the agent loop.                    |
| `packages/bootstrap`  | core, retrieval, agents    | Composition root: wires ports to adapters by run mode.           |

`retrieval` and `ingestion` are peers; so are `api` and `evaluation`. The
legal dependency directions are enforced by [`.importlinter`](.importlinter), not left as a convention.

## Getting started

```sh
uv sync
cp .env.example .env
uv run pytest
```

Tests run with `CIP_RUN_MODE=offline` (set in `tests/conftest.py`), so they
need no network and no local services.

## Local stack

`compose.yaml` is a placeholder for `CIP_RUN_MODE=local` - nothing in the
codebase talks to it yet. `docker compose up` brings up ollama once an
adapter exists to use it.

## Checks

```sh
./scripts/check.sh   # ruff, mypy, import-linter, pytest - what CI runs
```

Or individually:

```sh
uv run ruff check .
uv run mypy packages
uv run lint-imports
uv run pytest
```

## Architecture decisions

Recorded in [`docs/adr/`](docs/adr/), one file per decision, using the
[template](docs/adr/template.md).
