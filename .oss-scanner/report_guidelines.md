# How we would like reports written

## Layout and length

One finding per report, about one page, with these sections in this order:

1. **Summary**: two or three sentences saying what is wrong and what an attacker gains.
2. **Affected code**: file paths and line numbers at the commit that was scanned, and the commit hash.
3. **Preconditions**: see below.
4. **Reproduction**: numbered steps or a script that runs in the scanner image, with the output you saw.
5. **Impact**: what was read, changed or run, and whose data it was.
6. **Suggested fix**: a short description; the patch itself goes with the report.

## What every report should state

- The attacker's starting position: no account, an authenticated user, a member of the same team, the author of a
  document or web page that gets ingested, the operator of a remote MCP server or connector, or an administrator.
- The configuration it needs: `AUTH_TYPE` (unset, `simple_jwt`, `session_jwt` or `oidc`), the vector store, and any
  setting or agent tool that has to be switched on. Say plainly when the default configuration is not affected.
- The entry point that reaches the faulty code: the HTTP route and method, the Celery task, the agent tool, the
  parser and file type, or the widget property.
- Whether you ran the reproduction against a live instance, in a test, or only traced it by reading the code.
- Whether the same root cause appears elsewhere in the code; list the other places in the same report.

## Style

- Start the title with the component: `api:`, `auth:`, `parser:`, `connectors:`, `agents:`, `tools:`, `mcp:`,
  `sandbox:`, `worker:`, `frontend:` or `widget:`.
- Plain Markdown, with code and requests in fenced blocks. No tables.
- State facts and say what was not verified. No marketing language and no CVSS vector unless you derived each part.
- When a finding lives in a third-party package and not in this repository, say so in the first line and name the
  package and version from `uv.lock` or the `package-lock.json`.
