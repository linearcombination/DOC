# Project agent memory

This file is the project's committed home for project-intrinsic agent knowledge: build, test, release, architecture, and sharp-edge notes that should travel with the code.

- Add durable project-specific notes here as they are discovered through real work.

## Sharp edges

- `.env` (repo root) is tracked in git, not gitignored — it is the real deployed config.
  Editing a value there (e.g. `LOCK_TIMEOUT_SECONDS`) changes production behavior once merged
  and deployed; it isn't a separate manual step like a typical gitignored `.env`.
- `backend/doc/domain/resource_lookup.py` is compiled with `mypyc --strict` (see the `mypyc`
  Makefile target) in addition to being `mypy --strict`-checked (`mypy` Makefile target). Changes
  there must pass `mypy --strict` and stay compatible with mypyc's stricter runtime typing.
- Functions decorated `@worker.app.task` (Celery) in this module are, in practice, called
  synchronously as plain functions from FastAPI routes — no call site anywhere uses
  `.delay()`/`.apply_async()`. Since the app is served by multiple gunicorn worker processes
  (`backend/gunicorn.conf.py`), any such function that touches shared filesystem state needs its
  own concurrency safety; the Celery decorator alone buys no serialization.
- Local test runs outside the Docker-based `make unit-tests`/`e2e-tests` targets need a venv with
  `backend/requirements.txt` (+ `pytest`, `mypy`, `black` for dev checks) and `PYTHONPATH=backend`.
  Tests that read pre-cloned/downloaded `en_rg` docx fixtures (e.g.
  `tests/unit/test_resource_lookup_api.py::test_*_rg*_passages`) fail outside that Docker
  environment for lack of those fixtures — a pre-existing environmental gap, not a regression.

## Maintaining this file

Keep this file for knowledge useful to almost every future agent session in this project.
Do not repeat what the codebase already shows; point to the authoritative file or command instead.
Prefer rewriting or pruning existing entries over appending new ones.
When updating this file, preserve this bar for all agents and keep entries concise.
