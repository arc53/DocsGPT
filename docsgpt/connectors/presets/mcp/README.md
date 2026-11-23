# Curated MCP server presets

Each `<name>.yaml` here is one remote MCP server shown as a Connectors catalog
card. One file per preset, so two pull requests that each add a server never
touch the same file.

Inclusion rules: the vendor operates the server, it has a stable public URL,
and it signs in with OAuth plus dynamic client registration (or needs no
auth), so connecting takes no admin setup. Check each entry for OAuth
authorization-server metadata with a registration endpoint and for a 401
challenge on the MCP endpoint. Keep the list short; anything else is a
custom connector.

## Fields

```yaml
key: mcp:example            # required; the file is named example.yaml
name: Example               # required
description: Search and update Example records.   # required
mcp_url: https://mcp.example.com/mcp               # required
icon: example               # default: tool_mcp_tool
category: knowledge         # default: knowledge
auth_kind: mcp_oauth        # default: mcp_oauth; "mcp" for a server with no sign-in
capabilities: [read, write] # default: [read, write]
docs_url: https://example.com/docs/mcp
```

- The frontend reads `settings.connectors.descriptions.mcp_<name>` for a
  translated description.
- `sync_ingestor` also syncs the preset into Knowledge through its own MCP
  server, signed in with the same connection (Linear's issues).
- `default_actions` lists the tools that start on when the connection's tool
  is created; the rest start "Off" and can be turned on per action. Leave it
  out to turn every tool on.
- `part_of` shows the preset on another connector's card.
- `rank` places a card ahead of the others (lower first). Leave it out: cards
  without one follow the ranked ones in name order.
- `url_parameters` lists query parameters every connection must carry, for a
  server whose plain URL reaches more than one connection should (Supabase's
  project ref). The connect form asks for each one before sign-in, and the
  server refuses a URL at the preset's address without a value that matches
  its `pattern`, custom MCP servers at that address included. The values are
  kept on the connection, so a reconnect or a rebuilt tool keeps them:

  ```yaml
  url_parameters:
    - key: project_ref
      label: Project ref
      pattern: "[a-z]{20}"
      hint: In the project's settings, under General.
  ```

  The frontend translates the label from
  `settings.connectors.fields.mcp_<name>_<key>` (then `fields.<key>`) and the
  hint from `settings.connectors.fieldHints.mcp_<name>_<key>`, falling back
  to the English in the file.

The preset list in the docs is generated from these files
(`python -m docsgpt.connectors.reference --write`, run on `main` after a merge);
you don't edit it or the file it writes.
