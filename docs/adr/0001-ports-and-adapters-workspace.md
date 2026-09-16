# 0001. Ports and adapters, as a uv workspace

Date: 2026-09-16

Status: Accepted

## Context

CIP has to run against three very different environments: a laptop with no
network access during tests and development (offline), a local machine
running real services like ollama (local), and eventually managed cloud
services (cloud). Business logic that hard-codes any one of these becomes
impossible to test cheaply and expensive to port later.

At the same time the codebase has clear seams - document ingestion,
retrieval, tool execution, agent orchestration, evaluation, an HTTP API -
that don't all need to depend on each other, and some of which (retrieval
and ingestion; the API and evaluation) are genuine peers with no reason to
import one another.

## Decision

Structure the codebase as ports and adapters, one Python distribution
package per architectural layer, in a single uv workspace:

- `cip-core` defines ports as `Protocol`s and depends on nothing else in
  the codebase. Every other package depends on it, directly or
  transitively.
- `cip-retrieval` and `cip-ingestion` sit one layer up, depend only on
  core, and do not depend on each other.
- `cip-tools` sits above those; `cip-agents` above tools.
- `cip-api` and `cip-evaluation` both depend on agents and are peers of
  each other.
- `cip-bootstrap` is the composition root: the only package allowed to
  import concrete adapters from more than one other package. It exposes
  one cached factory per port (`inference()`, `vector_store()`), each
  branching on `CIP_RUN_MODE` and returning the port, never the concrete
  class. Each factory imports its adapter inside the arm that selects it,
  so importing the registry pulls in nothing for a mode this process will
  not run.

Adapters satisfy ports structurally (`Protocol`, `runtime_checkable`) and
never inherit from them - so a package can implement a port without
depending on `cip-core` for anything but the shape it's matching.

The layering is enforced mechanically with import-linter (`.importlinter`)
rather than left as a convention someone can accidentally break.

## Consequences

Adding a capability means deciding which layer it belongs to, which is
friction by design - it's meant to be a deliberate choice, not a default.
A change that legitimately needs to cross layers (say, evaluation calling
retrieval directly) requires either moving it through the layer that's
supposed to own it or revisiting this decision, not a quick import.

Every package needs its own `pyproject.toml`, `py.typed` marker and
workspace wiring in the root `pyproject.toml` - more files than a single
flat package, in exchange for `uv sync` installing exactly what's declared
and import-linter having real module boundaries to check.

Offline testing is cheap: `cip-bootstrap` wires `FixtureInference` and
in-memory adapters for `CIP_RUN_MODE=offline`, so the test suite never
touches a network. `local` and `cloud` arms raise `NotImplementedError`
naming the adapter that is missing, which is a deliberate, visible gap
rather than a silent fallback.

The run-mode branch is repeated once per factory rather than living in a
single function, and `functools.cache` means the first call to each
factory fixes its answer for the life of the process. Tests that need a
different run mode have to call `cache_clear()`, which is the price of
callers being able to ask for one port without constructing the rest.
