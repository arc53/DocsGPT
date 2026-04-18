# Human QA Checklist (~10 min)

Four compound flows. Each chains 5–10 breakable features into one tester journey — if anything regressed, it surfaces without a dedicated test. Run in order; state carries between flows.

## Prereqs
- [ ] Backend (Flask 7091 + Celery) and frontend dev server running
- [ ] LLM + embeddings keys in `.env`
- [ ] Fresh browser profile / incognito (no stale `authToken`)
- [ ] Ready: a small PDF, a public URL, an agent-tool credential (MCP endpoint or Brave/search key)

---

## Flow A — First-run journey: auth → settings → source → chat → share *(~3 min)*
Covers: session bootstrap, settings persistence + i18n, local + URL ingestion, streaming chat, abort, edit/retry, citations, feedback, attachments, markdown rendering, share link.

- [ ] Load app fresh → `localStorage.authToken` set (or JWT modal accepts pasted token); no console errors
- [ ] Settings → flip theme, change language (EN→JP→EN), bump chunk count, pick default model → reload → **all four persist**
- [ ] Sources → upload local PDF **and** ingest a URL in parallel; both finish with token counts
- [ ] New chat → ask a question the PDF answers → tokens stream → hit **Stop** mid-stream → cleanly aborts
- [ ] Edit the question, retry → new answer renders below; thumbs up it
- [ ] Open Sources popup on the answer → snippets map to the uploaded doc
- [ ] Attach a file inline in a follow-up → referenced in the response
- [ ] Ask for a reply with a code block, a table, and a mermaid diagram → all render
- [ ] Share conversation → open link in incognito → read-only view loads with full history
- [ ] Back in app, hard-refresh → conversation, thumbs, settings all rehydrate

## Flow B — Agent lifecycle: build → tool-use → publish → organize *(~3 min)*
Covers: agent create/edit/draft/publish, system prompt, model swap, source + tool attach, tool approval + denial, MCP config, pin, folders, public share, delete.

- [ ] Tools tab → add MCP server using `https://docs.mcp.cloudflare.com/mcp` → connects / saves; toggle it on
- [ ] Create **classic** agent with custom system prompt, model, the source from Flow A, and that tool → **Save draft**
- [ ] Reload → draft still there → publish it
- [ ] Chat with agent → ask *"how do I use AI workers on Cloudflare?"* → MCP tool approval prompt appears → **approve**, tool runs, answer cites docs content
- [ ] Ask again → this time **deny** approval → agent handles gracefully (no crash, no stuck spinner)
- [ ] Edit agent: swap model, add a second source, edit tool with **blank secret field** → save → existing credentials preserved, new config applied
- [ ] Pin the agent → appears in sidebar; create a folder, move it in, rename folder
- [ ] Open agent's public share URL in incognito → works unauthenticated
- [ ] Try a **Research** agent type on a broad question → research-progress steps render
- [ ] Delete the agent → gone from sidebar, folder, and pins

## Flow C — Admin, regression & cascade *(~2 min)*
Covers: analytics + filters, agent-scoped analytics, logs, delete cascades, conversation bulk delete, session rehydrate, responsive layout, chunk editing, source deletion.

- [ ] Analytics → messages / tokens / feedback charts load; toggle 1h / 7d / 30d — each returns sane data
- [ ] Agent-scoped analytics (on remaining agent) — numbers are a subset of global
- [ ] Logs tab → recent chats + tool calls listed; expand a row
- [ ] Open a source → edit one chunk, delete one chunk → persists
- [ ] Start a streaming chat, then **delete the conversation mid-stream** → no ghost spinner, sidebar updates
- [ ] Delete the original source → any chat still open degrades gracefully (no white screen)
- [ ] Settings → **Delete all conversations** → sidebar empties
- [ ] Sign out / clear token → sign back in → theme, language, pins, prompts, tools all rehydrate
- [ ] Resize to ~400px wide → sidebar collapses, chat layout doesn't break

## Flow D — API + connector spot-check *(~1 min, skip items without creds)*
Covers: agent API key, v1 streaming + non-streaming, inbound webhook, GitHub/Drive connectors, manual sync.

Set once:
```bash
export API="http://localhost:7091"
export KEY="a197be6b-969d-44c0-ba4d-af2f972a03df"
```

- [ ] **Non-streaming** — expect a JSON body with `choices[0].message.content`:
  ```bash
  curl -sS "$API/v1/chat/completions" \
    -H "Authorization: Bearer $KEY" \
    -H "Content-Type: application/json" \
    -d '{"messages":[{"role":"user","content":"how do I use AI workers"}],"stream":false}'
  ```
- [ ] **Streaming** — expect `data: {...}` SSE chunks ending in `data: [DONE]`:
  ```bash
  curl -N -sS "$API/v1/chat/completions" \
    -H "Authorization: Bearer $KEY" \
    -H "Content-Type: application/json" \
    -d '{"messages":[{"role":"user","content":"What tools do you have?"}],"stream":true}'
  ```
- [ ] **Models list** — expect the agent's model:
  ```bash
  curl -sS "$API/v1/models" -H "Authorization: Bearer $KEY"
  ```
- [ ] **Inbound webhook** — copy the webhook URL from the agent page, then fire it; confirm the run appears in Logs:
  ```bash
  curl -sS -X POST "<webhook_url>" \
    -H "Content-Type: application/json" \
    -d '{"message":"What tools do you have?"}'
  ```
- [ ] GitHub **or** Drive connector → auth → pick item → ingest → manual Sync → status updates; change sync frequency and reload

---