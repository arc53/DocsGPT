# DigitalOcean Marketplace listing

The copy for the DocsGPT listing in the Vendor Portal. DigitalOcean's guidelines: spell the
company "DigitalOcean" (never "DO"), and say that DigitalOcean doesn't build or support the
software.

## Name

DocsGPT

## Summary (one line)

Private AI assistant and agents over your own documents, with HTTPS from the first minute.

## Description

DocsGPT is an open-source platform for building AI assistants and agents that answer from
your own knowledge: upload documents, connect sources such as websites, GitHub, Confluence
or Google Drive, and chat with them, with citations. Build agents with tools and workflows,
and put them on your site, in Slack or Telegram, or behind an API.

This 1-Click App sets DocsGPT up on the Droplet's first boot:

- **HTTPS straight away, no domain needed.** DocsGPT answers at `https://<Droplet IP>` with a
  Let's Encrypt certificate for the IP address. Move to your own domain with one command.
- **Private by default.** An access token, shown only in the Droplet's login message, guards
  the instance; only ports 22, 80 and 443 are open.
- **Chat works immediately** through the DocsGPT public API, with no API key. Switch to
  OpenAI, Anthropic, Google, OpenRouter, Groq or any OpenAI-compatible server when you like.
- **User accounts when your team joins.** `docsgpt up --accounts` adds Keycloak sign-in, with
  an admin group and a console for adding people.
- **Safe upgrades.** `docsgpt upgrade` backs up first, and `docsgpt upgrade --rollback`
  returns to the previous version and data.

DocsGPT is built and supported by Arc53, not by DigitalOcean.

## Software included

| Software | Version | License |
| --- | --- | --- |
| DocsGPT | (release) | MIT |
| Docker CE | latest at build | Apache 2.0 |
| Caddy | 2 | Apache 2.0 |
| PostgreSQL | 16 | PostgreSQL License |
| Redis | 6 | BSD-3-Clause |
| Keycloak (optional, for user accounts) | 26 | Apache 2.0 |

## Getting started

1. Create the Droplet on a plan with at least 4 GB of memory (8 GB with user accounts and
   heavy use).
2. Wait a minute or two for the first boot, then log in as root with SSH or the Droplet
   Console. The login message shows the address and the access token.
3. Open `https://<Droplet IP>` and paste the token.
4. Optional: point a domain at the Droplet and run `docsgpt up --domain docs.example.com`;
   run `docsgpt up --accounts` to give everyone their own account.

Upgrade with `docsgpt upgrade`; `docsgpt upgrade --rollback` undoes it. The full guide is at
https://docs.docsgpt.cloud/Deploying/DigitalOcean, and support is on
https://github.com/arc53/DocsGPT/issues and Discord.

## Support details

- Website: https://www.docsgpt.cloud
- Documentation: https://docs.docsgpt.cloud/Deploying/DigitalOcean
- Support: https://github.com/arc53/DocsGPT/issues
- Source: https://github.com/arc53/DocsGPT

## README badge

Once the listing is approved, the README can link to it:

```markdown
[![Deploy on DigitalOcean](https://www.deploytodo.com/do-btn-blue.svg)](https://marketplace.digitalocean.com/apps/docsgpt?action=deploy)
```

The final `apps/<slug>` comes from the Vendor Portal; check it before adding the badge.
