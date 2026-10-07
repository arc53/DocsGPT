# Welcome to DocsGPT Contributing Guidelines

Thank you for choosing to contribute to DocsGPT! We are all very grateful! 

# We accept different types of contributions

📣 **Discussions** - Engage in conversations, start new topics, or help answer questions.

🐞 **Issues** - This is where we keep track of tasks. It could be bugs, fixes or suggestions for new features.

🛠️ **Pull requests** - Suggest changes to our repository, either by working on existing issues or adding new features.

📚 **Documentation** - The docs site lives in [`docs/`](https://github.com/arc53/DocsGPT/tree/main/docs) and is published at [docs.docsgpt.cloud](https://docs.docsgpt.cloud). See [`docs/README.md`](docs/README.md) to run it locally.


## 🐞 Issues and Pull requests

- We value contributions in the form of discussions or suggestions. We recommend taking a look at existing issues and our [roadmap](https://github.com/orgs/arc53/projects/2).


- If you're interested in contributing code, here are some important things to know:

- We have a frontend built on React (Vite) and a backend in Python.

> **Required for every PR:** Please attach screenshots or a short screen
> recording that shows the working version of your changes. This makes the
> requirement visible to reviewers and helps them quickly verify what you are
> submitting.

  
Before creating issues, please check out how the latest version of our app looks and works by launching it via [Quickstart](https://github.com/arc53/DocsGPT#quickstart) the version on our live demo is slightly modified with login. Your issues should relate to the version you can launch via [Quickstart](https://github.com/arc53/DocsGPT#quickstart).

### 👨‍💻 If you're interested in contributing code, here are some important things to know:

For instructions on setting up a development environment, please refer to our [Development Deployment Guide](https://docs.docsgpt.cloud/Deploying/Development-Environment).

**Prerequisites:**

- **Python 3.12** (`pyproject.toml` requires 3.12 or newer; CI runs 3.12).
- **[uv](https://docs.astral.sh/uv/)** (recommended): `uv sync` installs the locked dependencies, the test tools and the `docsgpt` command. pip works too; see the guide.
- **Node.js 22** for the frontend (`frontend/.nvmrc`).
- **Docker**, or your own PostgreSQL and Redis, to run the app: `docker compose -f deployment/docker-compose-dev.yaml up -d` starts both.
- **PostgreSQL server binaries** (`pg_ctl`, `initdb`) to run the backend tests; see [Running the tests](#running-the-tests).

Tech Stack Overview:

- 🌐 Frontend: Built with React (Vite) ⚛️,

- 🖥 Backend: Developed in Python 🐍

### 🌐 Frontend Contributions (⚛️ React, Vite)

*   **Design:** Follow [`frontend/DESIGN.md`](frontend/DESIGN.md): compose the parts in `frontend/src/components/ui/`, pick their look with props, and use the theme tokens. `npm run lint` enforces its rules, and `npm run lint:design` summarises the design-rule findings by rule and by file.
*   **Coding Style:** We follow a strict coding style enforced by ESLint and Prettier. Please ensure your code adheres to the configuration provided in our repository's `frontend/eslint.config.js` and `frontend/prettier.config.cjs` files.  We recommend configuring your editor with ESLint and Prettier to help with this.
* **Component Structure:** Strive for small, reusable components.  Favor functional components and hooks over class components where possible.
* **State Management** If you need to add stores, please use Redux.
* **Translations:** Every user-visible string, attributes such as `aria-label`, `placeholder`, `title` and `alt` included, goes through `t()` with a key in all seven locale files under `frontend/src/locale/` (`de`, `en`, `es`, `jp`, `ru`, `zh`, `zh-TW`). Admin pages stay English.
* **Checks:** From `frontend/`, run `npm run lint`, `npm test` and `npm run build` before opening a PR.

### 🖥 Backend Contributions (🐍 Python)

- Review our issues and contribute to [`/docsgpt`](https://github.com/arc53/DocsGPT/tree/main/docsgpt) 
- All new code should be covered with unit tests ([pytest](https://github.com/pytest-dev/pytest)). Please find tests under [`/tests`](https://github.com/arc53/DocsGPT/tree/main/tests) folder.
- Before submitting your Pull Request, ensure it can be queried after ingesting some test data.
- **Coding Style:** We adhere to the [PEP 8](https://www.python.org/dev/peps/pep-0008/) style guide for Python code, with lines up to 120 characters. Run `ruff check .` before submitting; CI runs the same lint. Most of the tree is not `ruff format` clean, so don't run `ruff format` over whole files: format only the lines you change.
- **Type Hinting:**  Please use type hints for all function arguments and return values. This improves code readability and helps catch errors early.  Example:

    ```python
    def my_function(name: str, count: int) -> list[str]:
        ...
    ```
- **Docstrings:**  All functions and classes should have docstrings explaining their purpose, parameters, and return values.  We prefer the [Google style docstrings](https://sphinxcontrib-napoleon.readthedocs.io/en/latest/example_google.html). Example:

    ```python
    def my_function(name: str, count: int) -> list[str]:
        """Does something with a name and a count.

        Args:
            name: The name to use.
            count: The number of times to do it.

        Returns:
            A list of strings.
        """
        ...
    ```
  
### Editor setup

Some configuration is shared by every editor, so you rarely need to set anything up by hand:

- [`.editorconfig`](https://editorconfig.org) holds the whitespace rules (4 spaces for Python, 2 for TypeScript/JSON/YAML, LF line endings, final newline). Most editors read it natively or through a plugin.
- `[tool.pyright]` in `pyproject.toml` points Pyright, basedpyright and Pylance at the `.venv` created by `uv sync` and at the repository root for imports.
- `.ruff.toml`, `frontend/eslint.config.js` and `frontend/prettier.config.cjs` are picked up by the matching editor integrations.

Editor-specific configuration that is tracked:

- **VS Code:** `.vscode/launch.json` has debug targets for the API, the Celery worker and the frontend.
- **Zed:** open the repository root (not `frontend/`). `.zed/settings.json` configures the language servers and formatters, `.zed/tasks.json` adds tasks (`task: spawn`) for the dev services, the API, the worker, the frontend, tests and linting, and `.zed/debug.json` adds debug targets (`debugger: start`). Python files are not formatted on save because most of the tree is not `ruff format` clean; frontend files are, with ESLint fixes followed by Prettier, as in the pre-commit hook. Project settings cannot install extensions, so if you want the matching syntax support add this to your own Zed settings:

    ```json
    {
      "auto_install_extensions": {
        "dockerfile": true,
        "docker-compose": true,
        "toml": true,
        "mdx": true
      }
    }
    ```

Personal preferences belong in your user settings; `.vscode/settings.json` and any other file under `.zed/` are ignored by git.

### Running the tests

Install the test dependencies first. `uv sync` installs them with the `dev` group; with pip, run `pip install -r tests/requirements.txt` next to `docsgpt/requirements.txt`. `pytest-cov` is required, because `pytest.ini` always passes `--cov`. `tests/requirements.txt` also installs the docling extra so its parser tests run; with uv, use `uv sync --extra docling` for the same coverage.

The database tests do not use your running Postgres. `pytest-postgresql` starts a throwaway cluster with `pg_ctl`, so the PostgreSQL server binaries must be on your `PATH` (or reachable through `pg_config --bindir`):

- **macOS:** `brew install postgresql@16`, then `export PATH="$(brew --prefix postgresql@16)/bin:$PATH"` (the formula is keg-only). [Postgres.app](https://postgresapp.com) works too; add its `bin` directory to `PATH`.
- **Debian/Ubuntu:** `sudo apt install postgresql`, then `export PATH="/usr/lib/postgresql/16/bin:$PATH"` (use the installed version number). The package also starts a server on port 5432, which clashes with the dev compose Postgres; the tests only need the binaries, so you can stop it with `sudo systemctl disable --now postgresql`.
- Anywhere else, point the plugin at `pg_ctl` with `--postgresql-exec=/path/to/pg_ctl`.

Then run the suite from the repository root:

```shell
python -m pytest            # or: uv run pytest
python -m pytest -n auto    # in parallel, as CI does
python -m pytest tests/api  # one area while you work
```

On **macOS**, set `KMP_DUPLICATE_LIB_OK=TRUE` (for example `KMP_DUPLICATE_LIB_OK=TRUE python -m pytest`). `faiss-cpu` and `torch` each ship their own OpenMP runtime, and loading both into one process aborts the interpreter with `OMP: Error #15`; Linux and CI are not affected.

### Backend and UI contribution workflows

**Changing the database schema.** The schema is managed by Alembic, in `docsgpt/alembic/versions/`, with one numbered file per revision (`0043_wiki_outside_edits.py`, and so on).

1. Copy the latest revision to `00NN_<slug>.py` with the next number. Set `revision` to the file name without `.py`, and `down_revision` to the previous revision's ID.
2. Write both `upgrade()` and `downgrade()`, and make them safe to re-run (`IF NOT EXISTS` / `IF EXISTS`), as the existing revisions do.
3. Mirror the change in the table definitions in `docsgpt/storage/db/models.py`, and read or write the new columns through a repository in `docsgpt/storage/db/repositories/`.
4. Add a round-trip test, `tests/storage/db/test_migration_00NN.py`, next to the existing ones.

The app applies pending revisions on start (`AUTO_MIGRATE`, on by default); `docsgpt migrate` applies them by hand.

**Adding a setting.** Settings are Pydantic fields in `docsgpt/core/settings/`, one module per domain. Add the field to the group it belongs to, with a `description` (a test fails without one), then regenerate the docs reference:

```shell
python -m docsgpt.core.settings.reference --write
```

That rewrites `docs/content/Deploying/Settings-Reference.mdx`; commit it with your change. `tests/core/test_settings.py` fails while the checked-in page is stale. If operators will commonly set the new value, also add a commented example to `.env-template`.

**Adding or changing a REST route.** REST routes are documented in the docs site from the flask-restx Swagger document; after adding or changing a route, regenerate the docs snapshot with `python -m docsgpt.api.reference --write` (CI fails if `docs/data/swagger.json` is stale). The [REST API Reference](https://docs.docsgpt.cloud/API/reference) page renders that snapshot.

**Adding UI text.** Add the key to all seven files in `frontend/src/locale/`, not only `en.json`; see Frontend Contributions above.

**End-to-end tests.** The Playwright suite in [`tests/e2e/`](tests/e2e/README.md) drives the whole app, with a mock LLM, against a disposable `docsgpt_e2e` database. `scripts/e2e/up.sh` starts the stack natively (mock LLM, API, worker and Vite on their own ports), `scripts/e2e/down.sh` stops it, and `scripts/e2e/bake_template.sh` builds the template database that `reset_db.sh` clones before each run. The scripts expect PostgreSQL on `127.0.0.1:5432` with a `postgres` superuser (set `PG_SUPERUSER` to use another) and a `docsgpt` role (password `docsgpt`), Redis on `127.0.0.1:6379` with `redis-cli` on `PATH`, and `PG_BIN` pointing at the PostgreSQL `bin` directory (the default is a macOS DBngin path). Set `INTERNAL_KEY` (exported, or in `.env`) as well, or uploads fail. `up.sh` serves the ASGI app under uvicorn, as `docsgpt api` does, so the [ASGI-only routes](https://docs.docsgpt.cloud/Deploying/Development-Environment#asgi-only-features) (live notifications, stream resume, device streams, artifact downloads) work in that stack. `scripts/qa/durability_e2e.py` is a separate check of the chat write-ahead log, the reconciler and task redelivery; it uses the Postgres and Redis in your `.env`.

## Workflow 📈

Here's a step-by-step guide on how to contribute to DocsGPT:

1. **Fork the Repository:**
   - Click the "Fork" button at the top-right of this repository to create your fork.

2. **Clone the Forked Repository:**
   - Clone the repository using:
      ``` shell
      git clone https://github.com/<your-github-username>/DocsGPT.git
      ```

3. **Keep your Fork in Sync:**
   - Before you make any changes, make sure that your fork is in sync to avoid merge conflicts using:
     ```shell
     git remote add upstream https://github.com/arc53/DocsGPT.git
     git pull upstream main
     ```

4. **Create and Switch to a New Branch:**
   - Create a new branch for your contribution using:
     ```shell
     git checkout -b your-branch-name
     ```

5. **Make Changes:**
   - Make the required changes in your branch.

6. **Add Changes to the Staging Area:**
   - Add your changes to the staging area using:
     ```shell
     git add .
     ```

7. **Commit Your Changes:**
   - Commit your changes with a descriptive commit message using:
     ```shell
     git commit -m "Your descriptive commit message"
     ```

8. **Push Your Changes to the Remote Repository:**
   - Push your branch with changes to your fork on GitHub using:
     ```shell
     git push origin your-branch-name
     ```

9. **Submit a Pull Request (PR):**
   - Create a Pull Request from your branch to the main repository. Make sure to include a detailed description of your changes, reference any related issues, and attach screenshots or a screen recording showing the working version.

10. **Collaborate:**
   - Be responsive to comments and feedback on your PR.
   - Make necessary updates as suggested.
   - Once your PR is approved, it will be merged into the main repository.

11. **Testing:**
   - Before submitting a Pull Request, run the checks for what you changed: `ruff check .` and `python -m pytest` for the backend (see [Running the tests](#running-the-tests)), `npm run lint`, `npm test` and `npm run build` in `frontend/`, and `npm run build` in `docs/` for documentation.

12. **Questions and Collaboration:**
    - Feel free to join our Discord. We're very friendly and welcoming to new contributors, so don't hesitate to reach out.

Thank you for considering contributing to DocsGPT! 🙏

## Questions/collaboration
Feel free to join our [Discord](https://discord.gg/vN7YFfdMpj). We're very friendly and welcoming to new contributors, so don't hesitate to reach out.
# Thank you so much for considering to contributing DocsGPT!🙏
