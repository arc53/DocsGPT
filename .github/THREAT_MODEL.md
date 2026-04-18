# DocsGPT Public Threat Model

**Classification:** Public  
**Last updated:** 2026-04-15  
**Applies to:** Open-source and self-hosted DocsGPT deployments

## 1) Overview

DocsGPT ingests content (files/URLs/connectors), indexes it, and answers queries via LLM-backed APIs and optional tools.

Core components:
- Backend API (`application/`)
- Workers/ingestion (`application/worker.py` and related modules)
- Datastores (MongoDB/Redis/vector stores)
- Frontend (`frontend/`)
- Optional extensions/integrations (`extensions/`)

## 2) Scope and assumptions

In scope:
- Application-level threats in this repository.
- Local and internet-exposed self-hosted deployments.

Assumptions:
- Internet-facing instances enable auth and use strong secrets.
- Datastores/internal services are not publicly exposed.

Out of scope:
- Cloud hardware/provider compromise.
- Security guarantees of external LLM vendors.
- Full security audits of third-party systems targeted by tools (external DBs/MCP servers/code-exec APIs).

## 3) Security objectives

- Protect document/conversation confidentiality.
- Preserve integrity of prompts, agents, tools, and indexed data.
- Maintain API/worker availability.
- Enforce tenant isolation in authenticated deployments.

## 4) Assets

- Documents, attachments, chunks/embeddings, summaries.
- Conversations, agents, workflows, prompt templates.
- Secrets (JWT secret, `INTERNAL_KEY`, provider/API/OAuth credentials).
- Operational capacity (worker throughput, queue depth, model quota/cost).

## 5) Trust boundaries and untrusted input

Trust boundaries:
- Internet ↔ Frontend
- Frontend ↔ Backend API
- Backend ↔ Workers/internal APIs
- Backend/workers ↔ Datastores
- Backend ↔ External LLM/connectors/remote URLs

Untrusted input includes API payloads, file uploads, remote URLs, OAuth/webhook data, retrieved content, and LLM/tool arguments.

## 6) Main attack surfaces

1. Auth/authz paths and sharing tokens.
2. File upload + parsing pipeline.
3. Remote URL fetching and connectors (SSRF risk).
4. Agent/tool execution from LLM output.
5. Template/workflow rendering.
6. Frontend rendering + token storage.
7. Internal service endpoints (`INTERNAL_KEY`).
8. High-impact integrations (SQL tool, generic API tool, remote MCP tools).

## 7) Key threats and expected mitigations

### A. Auth/authz misconfiguration
- Threat: weak/no auth or leaked tokens leads to broad data access.
- Mitigations: require auth for public deployments, short-lived tokens, rotation/revocation, least-privilege sharing.

### B. Untrusted file ingestion
- Threat: malicious files/archives trigger traversal, parser exploits, or resource exhaustion.
- Mitigations: strict path checks, archive safeguards, file limits, patched parser dependencies.

### C. SSRF/outbound abuse
- Threat: URL loaders/tools access private/internal/metadata endpoints.
- Mitigations: validate URLs + redirects, block private/link-local ranges, apply egress controls/allowlists.

### D. Prompt injection + tool abuse
- Threat: retrieved text manipulates model behavior and causes unsafe tool calls.
- Threat: never rely on the model to "choose correctly" under adversarial input.
- Mitigations: treat retrieved/model output as untrusted, enforce tool policies, only expose tools explicitly assigned by the user/admin to that agent, separate system instructions from retrieved content, audit tool calls.

### E. Dangerous tool capability chaining (SQL/API/MCP)
- Threat: write-capable SQL credentials allow destructive queries.
- Threat: API tool can trigger side effects (infra/payment/webhook/code-exec endpoints).
- Threat: remote MCP tools may expose privileged operations.
- Mitigations: read-only-by-default credentials, destination allowlists, explicit approval for write/exec actions, per-tool policy enforcement + logging.

### F. Frontend/XSS + token theft
- Threat: XSS can steal local tokens and call APIs.
- Mitigations: reduce unsafe rendering paths, strong CSP, scoped short-lived credentials.

### G. Internal endpoint exposure
- Threat: weak/unset `INTERNAL_KEY` enables internal API abuse.
- Mitigations: fail closed, require strong random keys, keep internal APIs private.

### H. DoS and cost abuse
- Threat: request floods, large ingestion jobs, expensive prompts/crawls.
- Mitigations: rate limits, quotas, timeouts, queue backpressure, usage budgets.

## 8) Example attacker stories

- Internet-exposed deployment runs with weak/no auth and receives unauthorized data access/abuse.
- Intranet deployment intentionally using weak/no auth is vulnerable to insider misuse and lateral-movement abuse.
- Crafted archive attempts path traversal during extraction.
- Malicious URL/redirect chain targets internal services.
- Poisoned document causes data exfiltration through tool calls.
- Over-privileged SQL/API/MCP tool performs destructive side effects.

## 9) Severity calibration

- **Critical:** unauthenticated public data access; prompt-injection-driven exfiltration; SSRF to sensitive internal endpoints.
- **High:** cross-tenant leakage, persistent token compromise, over-privileged destructive tools.
- **Medium:** DoS/cost amplification and non-critical information disclosure.
- **Low:** minor hardening gaps with limited impact.

## 10) Baseline controls for public deployments

1. Enforce authentication and secure defaults.
2. Set/rotate strong secrets (`JWT`, `INTERNAL_KEY`, encryption keys).
3. Restrict CORS and front API with a hardened proxy.
4. Add rate limiting/quotas for answer/upload/crawl/token endpoints.
5. Enforce URL+redirect SSRF protections and egress restrictions.
6. Apply upload/archive/parsing hardening.
7. Require least-privilege tool credentials and auditable tool execution.
8. Monitor auth failures, tool anomalies, ingestion spikes, and cost anomalies.
9. Keep dependencies/images patched and scanned.
10. Validate multi-tenant isolation with explicit tests.

## 11) Maintenance

Review this model after major auth, ingestion, connector, tool, or workflow changes.

## References

- [OWASP Top 10 for LLM Applications](https://owasp.org/www-project-top-10-for-large-language-model-applications/)
- [OWASP ASVS](https://owasp.org/www-project-application-security-verification-standard/)
- [STRIDE overview](https://learn.microsoft.com/azure/security/develop/threat-modeling-tool-threats)
- [DocsGPT SECURITY.md](../SECURITY.md)
