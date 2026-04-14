# DocsGPT Incident Response Plan (IRP)

This playbook describes how maintainers respond to confirmed or suspected security incidents.

- Vulnerability reporting: [`SECURITY.md`](../SECURITY.md)
- Non-security bugs/features: [`CONTRIBUTING.md`](../CONTRIBUTING.md)

## Severity

| Severity | Definition | Typical examples |
|---|---|---|
| **Critical** | Active exploitation, supply-chain compromise, or confirmed data breach requiring immediate user action. | Compromised release artifact/image; remote execution. |
| **High** | Serious undisclosed vulnerability with no practical workaround, or CVSS >= 7.0. | key leakage; prompt injection enabling cross-tenant access. |
| **Medium** | Material impact but constrained by preconditions/scope, or a practical workaround exists. | Auth-required exploit; dependency CVE with limited reachability. |
| **Low** | Defense-in-depth or narrow availability impact with no confirmed data exposure. | Missing rate limiting; hardening gap without exploit evidence. |


## Response workflow

### 1) Triage (target: initial response within 48 hours)

1. Acknowledge report.
2. Validate on latest release and `main`.
3. Confirm in-scope security issue vs. hardening item (per `SECURITY.md`).
4. Assign severity and open a **draft GitHub Security Advisory (GHSA)** (no public issue).
5. Determine whether root cause is DocsGPT code or upstream dependency/provider.

### 2) Investigation

1. Identify affected components, versions, and deployment scope (self-hosted, cloud, or both).
2. For AI issues, explicitly evaluate prompt injection, document isolation, and output leakage.
3. Request a CVE through GHSA for **Medium+** issues.

### 3) Containment, fix, and disclosure

1. Implement and test fix in private security workflow (GHSA private fork/branch).
2. Merge fix to `main`, cut patched release, and verify published artifacts/images.
3. Patch managed cloud deployment (`app.docsgpt.cloud`) and other deployments as soon as validated.
4. Publish GHSA with CVE (if assigned), affected/fixed versions, CVSS, mitigations, and upgrade guidance.
5. **Critical/High:** coordinate disclosure timing with reporter (goal: <= 90 days) and publish a notice.
6. **Medium/Low:** include in next scheduled release unless risk requires immediate out-of-band patching.

### 4) Post-incident

1. Monitor support channels (GitHub/Discord) for regressions or exploitation reports.
2. Run a short retrospective (root cause, detection, response gaps, prevention work).
3. Track follow-up hardening actions with owners/dates.
4. Update this IRP and related runbooks as needed.

## Scenario playbooks

### Supply-chain compromise

1. Freeze releases and investigate blast radius.
2. Rotate credentials in order: Docker Hub -> GitHub tokens -> LLM provider keys -> DB credentials -> `JWT_SECRET_KEY` -> `ENCRYPTION_SECRET_KEY` -> `INTERNAL_KEY`.
3. Replace compromised artifacts/tags with clean releases and revoke/remove bad tags where possible.
4. Publish advisory with exact affected versions and required user actions.

### Data exposure

1. Determine scope (users, documents, keys, logs, time window).
2. Disable affected path or hotfix immediately for managed cloud.
3. Notify affected users with concrete remediation steps (for example, rotate keys).
4. Continue through standard fix/disclosure workflow.

### Critical regression with security impact

1. Identify introducing change (`git bisect` if needed).
2. Publish workaround within 24 hours (for example, pin to known-good version).
3. Ship patch release with regression test and close incident with public summary.

## AI-specific guidance

Treat confirmed AI-specific abuse as security incidents:

- Prompt injection causing sensitive data exfiltration (from tools that don't belong to the agent) -> **High**
- Cross-tenant retrieval/isolation failure -> **High**
- API key disclosure in output -> **High**

## Secret rotation quick reference

| Secret | Standard rotation action |
|---|---|
| Docker Hub credentials | Revoke/replace in Docker Hub; update CI/CD secrets |
| GitHub tokens/PATs | Revoke/replace in GitHub; update automation secrets |
| LLM provider API keys | Rotate in provider console; update runtime/deploy secrets |
| Database credentials | Rotate in DB platform; redeploy with new secrets |
| `JWT_SECRET_KEY` | Rotate and redeploy (invalidates all active user sessions/tokens) |
| `ENCRYPTION_SECRET_KEY` | Rotate and redeploy (re-encrypt stored data if possible; existing encrypted data may become inaccessible) |
| `INTERNAL_KEY` | Rotate and redeploy (invalidates worker-to-backend authentication) |

## Maintenance

Review this document:

- after every **Critical/High** incident, and
- at least annually.

Changes should be proposed via pull request to `main`.
