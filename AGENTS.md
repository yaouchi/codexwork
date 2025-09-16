# Repository Guidelines

## Project Structure & Module Organization
- Keep production code under `src/`, grouping behavior-specific modules inside `src/agents/` and shared helpers in `src/core/`.
- Mirror agent names between code and tests (e.g., `src/agents/router.py` pairs with `tests/agents/test_router.py`).
- Store reusable workflows or prompts in `assets/` and update inline docs when adding new files.
- Scripts that wire agents together belong in `scripts/` (for example `scripts/run_local.py`).

## Git Repository Setup
- Central remote is `https://github.com/yaouchi/codexwork`; add it via `git remote add origin https://github.com/yaouchi/codexwork` in fresh clones.
- Use `main` as the default branch: `git branch -m main` after `git init`, then `git fetch origin` followed by `git pull origin main --allow-unrelated-histories` when bootstrapping.
- Create topic branches as `feature/<summary>` or `fix/<issue-number>` and push with `git push -u origin <branch>`.

## Build, Test, and Development Commands
- `python -m venv .venv && source .venv/bin/activate` sets up a local environment; keep it isolated from system Python.
- `pip install -r requirements.txt` installs runtime dependencies; commit any lockfile updates alongside feature work.
- `ruff check src tests` runs linting and quick static analysis; fix any autofixable hints with `ruff check --fix`.
- `pytest` executes the full test suite; use `pytest -k agent_name` when iterating on a specific component.

## Coding Style & Naming Conventions
- Follow PEP 8 with 4-space indentation; type hints are mandatory on public functions.
- Use descriptive module names (e.g., `planner_service.py`) and snake_case for functions and variables.
- Format code with `black src tests`; CI rejects unformatted changes.
- Centralize config defaults in `src/core/config.py`; avoid scattering magic numbers.

## Testing Guidelines
- Write unit tests in `tests/` mirroring the package tree; name files `test_<module>.py`.
- Favor deterministic fixtures; when randomness is unavoidable, seed via `tests/conftest.py`.
- New features require test coverage and, when possible, regression tests replicating prior bugs.
- Capture integration scenarios with `tests/integration/`; run them locally using `pytest tests/integration -m "not slow"`.

## Commit & Pull Request Guidelines
- Use Conventional Commit prefixes (`feat:`, `fix:`, `docs:`, etc.) to keep history searchable.
- Squash WIP commits before opening a PR; each PR should describe scope, testing performed, and any follow-up tasks.
- Link related issues in the PR description (`Closes #123`) and attach screenshots for UI-affecting work.
- Request review from another agent owner when touching `src/agents/` and update AGENTS.md if workflow expectations change.

## Communication Guidelines
- すべてのコードレビュー、PR 説明、コメント返信は日本語で行うこと。
- 英語資料を参照した場合でも、日本語で要約してチームに共有し、転記元のリンクを添付すること。
