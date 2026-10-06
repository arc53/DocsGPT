# DocsGPT custom CodeQL queries

These queries run in the **CodeQL Advanced** workflow
([`.github/workflows/codeql.yml`](../workflows/codeql.yml)) alongside GitHub's
`security-extended` suite. Results are uploaded to the repository's
**Security → Code scanning alerts** tab. The checks are **non-blocking**: they
annotate pull requests but do not fail the build.

## What runs

Configured by [`codeql-config.yml`](codeql-config.yml), which restricts
extraction to first-party source (`application`, `frontend/src`, `extensions`,
`scripts`) and adds the packs under [`queries/`](queries/).

### Python (`queries/python/`)

| Query | Kind | Purpose |
| --- | --- | --- |
| `InputPointInventory.ql` | inventory (note) | Marks every HTTP input point (Flask `request.*`, flask-restx fields). Each new finding on a PR is a **new untrusted-input surface** to review/allow-list. |
| `DangerousCallInventory.ql` | inventory (note) | Lists every `eval`/`exec`/`compile`/`__import__`/`os.system`/`subprocess`/`pickle`/`marshal`/`yaml.load` call — the "candidates to replace" list. |
| `DangerousExecutionTaint.ql` | taint (error) | Reports only when untrusted HTTP input actually **flows into** one of those sinks — the high-signal RCE / unsafe-deserialization finding. |

Shared sink definitions live in [`queries/python/DangerousSinks.qll`](queries/python/DangerousSinks.qll).

### JavaScript / TypeScript (`queries/javascript/`)

| Query | Kind | Purpose |
| --- | --- | --- |
| `DangerousJsSinkInventory.ql` | inventory (warning) | Lists `eval()`, `new Function()`, string-body `setTimeout`/`setInterval`, and `dangerouslySetInnerHTML`. |

## Note on the sandbox

DocsGPT intentionally executes user-supplied code through
[`application/sandbox/`](../../application/sandbox/) (`manager.exec` /
backend `.exec`). Those are **method** calls, not the Python builtin `exec`, so
the sink matchers do **not** flag them. The sandbox is the sanctioned execution
boundary; it is out of scope for these queries by design.

## Running locally

Requires the [CodeQL CLI](https://github.com/github/codeql-cli-binaries) and the
CodeQL standard libraries on the search path.

```bash
# 1. Build a database (Python shown; use javascript for the frontend).
codeql database create /tmp/docsgpt-py --language=python \
  --source-root=application --build-mode=none

# 2. Compile-check the queries.
codeql query compile .github/codeql/queries/python

# 3. Run them.
codeql database analyze /tmp/docsgpt-py .github/codeql/queries/python \
  --format=sarif-latest --output=/tmp/py-results.sarif
```

## Triaging / allow-listing a reviewed sink

An inventory finding that has been reviewed and is safe should be **dismissed in
the code-scanning UI** ("Used in tests" / "Won't fix" / "False positive") rather
than deleted from the query — that keeps the inventory complete while silencing
the specific location. For a systemic exception (e.g. a whole trusted module),
add a `paths-ignore` entry in [`codeql-config.yml`](codeql-config.yml).
