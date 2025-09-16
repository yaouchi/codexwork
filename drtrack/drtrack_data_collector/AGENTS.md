# Repository Guidelines

## Project Structure & Module Organization
- `main.py` orchestrates runs and selects processors via `JOB_TYPE`; keep it thin and delegate business logic.
- `processors/` hosts task-specific flows (`url_collector.py`, `doctor_info.py`, etc.). Add new jobs here and expose a `run(config, logger)` entry point.
- Shared integrations and utilities belong in `common/` (HTTP, GCS, AI clients, logging). Extend these modules instead of duplicating helpers.
- Centralize defaults and environment parsing in `config.py`; adjust `Config.validate()` whenever new flags are introduced.
- Architecture notes, prompts, and presentations live in `doc/`; keep diagrams or prompt updates in sync with shipped behavior.
- Keep `sql/` and `log/` local; don't commit dumps.

## Build, Test, and Development Commands
- `python -m venv .venv && source .venv/bin/activate` builds the local virtualenv.
- `pip install -r requirements.txt` installs runtime plus optional testing extras.
- `python main.py` runs the collector; set `JOB_TYPE` (`url_collect`, `doctor_info`, `outpatient`, `doctor_info_validation`) and related env vars beforehand.
- `pytest` executes the test suite; limit scope with `pytest -k <module>` while iterating.
- `ruff check common processors` enforces linting; use `--fix` to apply safe edits.
- `black common processors config.py main.py` keeps formatting consistent with CI expectations.

## Coding Style & Naming Conventions
- Follow PEP 8 with 4-space indentation, snake_case names, and descriptive module filenames.
- Type hints and concise docstrings are required on public functions and processor entry points.
- Use `UnifiedLogger` helpers for structured output; avoid `print` in production paths.
- Mirror module names in future tests (e.g., `processors/outpatient.py` → `tests/processors/test_outpatient.py`).

## Testing Guidelines
- Write deterministic `pytest` suites placed under `tests/`, mirroring package layout.
- Mock Gemini, GCS, and network calls with fixtures; seed randomness inside `tests/conftest.py` if needed.
- Cover pagination, retries, encoding detection, and prior incident regressions; run `pytest --maxfail=1 --disable-warnings` before pushing.

## Commit & Pull Request Guidelines
- Use Conventional Commit prefixes (`feat:`, `fix:`, `docs:`) and keep each change focused.
- Summarize scope, linked issues (`Closes #123`), configuration updates, and verification steps in PR descriptions.
- Attach screenshots or logs when output formats change, and request review from an agent owner for edits in `processors/`.
- コードレビュー、PR説明、コメント返信は必ず日本語で行い、参照資料が英語でも日本語で要約して共有してください。

## Configuration & Security Tips
- Supply credentials via environment variables consumed by `Config.from_env`; never commit secrets or API keys.
- Validate new settings inside `Config.validate()` so Cloud Run jobs fail fast on misconfiguration.
- Document operational runbooks and key rotation steps in `doc/` to keep on-call responders aligned.
