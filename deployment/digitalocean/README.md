# DocsGPT 1-Click App for DigitalOcean

The image behind the DocsGPT listing on the DigitalOcean Marketplace: Ubuntu 24.04 with
Docker, the `docsgpt` command and the stack's images already in place. Nothing in it is
configured: each Droplet sets itself up on its first boot, with secrets of its own.

What a customer gets, a minute or two after creating the Droplet:

- DocsGPT at `https://<Droplet IP>`, with a Let's Encrypt certificate for the IP address
  (six-day `shortlived` profile, renewed by Caddy), no domain needed;
- the access token, shown to root at the first login and by `docsgpt token`, so nobody who
  merely finds the address can use the instance (the login message, which every user can
  read, carries no secret);
- chat that works before any key is entered, through the DocsGPT public API;
- only ports 22, 80 and 443 open (ufw), fail2ban, and unattended security updates;
- on the first SSH login, two optional questions: move to a domain
  (`docsgpt up --domain NAME`) and turn on user accounts (`docsgpt up --accounts`, Keycloak).

Upgrades go through `docsgpt upgrade`, which backs up first; `docsgpt upgrade --rollback`
returns to the previous version and that backup. The customer guide is
[docs.docsgpt.cloud/Deploying/DigitalOcean](https://docs.docsgpt.cloud/Deploying/DigitalOcean).

## Layout

| Path | What it is |
| --- | --- |
| `docsgpt.pkr.hcl` | Packer template: build Droplet, provisioning, DigitalOcean's cleanup and image check |
| `scripts/10-system.sh` | Patches, Docker, ufw, fail2ban, unattended upgrades, the SSH "please wait" lock |
| `scripts/20-docsgpt.sh` | uv and the `docsgpt` tool under `/opt/docsgpt-cli`, image pre-pull, `application.info` |
| `files/var/lib/cloud/scripts/per-instance/001_onboot` | First boot: `docsgpt up --ip <public IP>`, then unlock SSH |
| `files/etc/update-motd.d/99-docsgpt` | Login message: address, where the token is, commands (no secrets) |
| `files/usr/local/lib/docsgpt/first-login` | Root's first login: the access token, then the optional domain and accounts questions |
| `smoke_test.py` | Boots a Droplet from a snapshot and checks it end to end |
| `listing.md` | Copy for the Marketplace listing |

The stack lives in `/opt/docsgpt` (`DOCSGPT_HOME`); `/etc/environment` points root's shells,
and with them `docsgpt upgrade`, at it and at the uv tool directory.

## Build

Needs [Packer](https://developer.hashicorp.com/packer/install) and a DigitalOcean API token
with read and write access.

```bash
packer init deployment/digitalocean
DIGITALOCEAN_TOKEN=... packer build -var docsgpt_version=1.0.0 deployment/digitalocean
```

`docsgpt_version` is a PyPI release; its Docker images (`arc53/docsgpt:<version>`) are what
the Droplet runs. To test a branch, build a wheel and pass it; its version must match:

```bash
uv build --wheel --out-dir dist
DIGITALOCEAN_TOKEN=... packer build -var docsgpt_version=1.0.0 \
  -var docsgpt_package=dist/docsgpt-1.0.0-py3-none-any.whl deployment/digitalocean
```

The build runs on an `s-2vcpu-4gb` Droplet, whose 80 GB disk becomes the image's minimum:
DigitalOcean only offers the image on plans with at least that disk, so 4 GB of memory is
the smallest. The snapshot id is in `deployment/digitalocean/packer-manifest.json`.

## Test

```bash
DIGITALOCEAN_TOKEN=... python3 deployment/digitalocean/smoke_test.py --snapshot <snapshot id>
```

It creates a Droplet and an SSH key, waits for the first boot, checks the certificate, the
closed ports, the login message, an upload answered with the token, a Keycloak sign-in after
`docsgpt up --accounts`, and a backup holding the Keycloak database, then deletes both.
`--keep` leaves the Droplet running.

## Release

`.github/workflows/digitalocean-image.yml` builds, smoke-tests and submits an image for each
release and once a month, so the listing never sits on an outdated base image. It needs the
`DIGITALOCEAN_TOKEN` secret; with `DIGITALOCEAN_MARKETPLACE_APP_ID` set as well it submits
the image through the Vendor Portal API, which puts it into DigitalOcean's review.
