# How we would like patches made

## Size and scope of a fix

- As narrow as the bug allows. Fix the root cause where it lives, and when several call sites share it, fix it in the
  shared helper (for example `docsgpt/security/`) and not at each call site.
- No refactoring, renaming, reformatting or dependency changes that the fix does not need.
- Keep the behaviour of valid requests unchanged. If a fix has to change the API, a setting's default or the
  database schema, say so in the report.
- A schema change is a new Alembic migration under `docsgpt/alembic/versions/`; never edit an existing one.

## Code style

- Backend: Python 3.12, PEP 8, lines of at most 120 characters, type hints on arguments and return values, and it
  must pass `ruff check .`.
- Docstrings are Google style and short: one line where one line is enough.
- Few comments: only where the code is not obvious, saying why and not what.
- Frontend and widget: TypeScript that passes the existing ESLint and Prettier setup (`npm run lint` in `frontend/`).
  Every user-visible string in `frontend/` is a `t()` key in all eight locales under `frontend/src/locale/`.
- Dependencies are declared in `pyproject.toml` and locked in `uv.lock`; never edit `docsgpt/requirements*.txt` by
  hand.

## Tests

- Add a regression test that fails before the fix and passes after it, in the nearest existing file under `tests/`
  (security helpers in `tests/security/`, routes in `tests/api/`, parsers in `tests/parser/`).
- Database tests use the `pg_conn` fixture and roll back. A test that commits needs `@pytest.mark.fresh_db`.
- Tests must not sleep or reach the network: patch sleeps and retry back-off and assert the attempt count.
- Frontend tests are Vitest files next to the code (`*.test.ts`).

## Branch and commit message

- Against the `main` branch, as one commit.
- Conventional Commits subject in the imperative, lower case, without a full stop: `fix(parser): reject archive
  entries that escape the extraction directory`.
- No description of the vulnerability beyond what the code change shows; the details stay in the private report.
