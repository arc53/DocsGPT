# Security Policy

## Supported Versions

Security patches target the latest release and the `main` branch. We recommend always running the most recent version.

## Reporting a Vulnerability

Preferred method: use GitHub's private vulnerability reporting flow:
https://github.com/arc53/DocsGPT/security

Then click **Report a vulnerability**.


Alternatively, email us at: security@arc53.com

We aim to acknowledge reports within 48 hours.

## Incident Handling

For the public incident response process, see [`INCIDENT_RESPONSE.md`](./.github/INCIDENT_RESPONSE.md). If you believe an active exploit is occurring, include **URGENT** in your report subject line.

## Verifying Releases

Releases after 1.1.0 carry SLSA provenance for their assets (`install.sh`, `install.ps1`, `docker-compose-standalone.yaml`) in `docsgpt.intoto.jsonl`, signed with Sigstore by the release workflow. To check an asset, download it with the provenance and run [slsa-verifier](https://github.com/slsa-framework/slsa-verifier):

```bash
#!/usr/bin/env bash
# Usage: verify.sh <release tag>, e.g. verify.sh 1.2.0
set -euo pipefail
TAG="${1:?usage: verify.sh <release tag>}"
gh release download "$TAG" --repo arc53/DocsGPT --pattern install.sh --pattern docsgpt.intoto.jsonl
slsa-verifier verify-artifact install.sh \
  --provenance-path docsgpt.intoto.jsonl \
  --source-uri github.com/arc53/DocsGPT \
  --print-provenance > provenance.json
# The provenance must name the commit the release tag points at.
built=$(jq -er '.predicate.invocation.configSource.digest.sha1' provenance.json)
tagged=$(gh api "repos/arc53/DocsGPT/commits/$TAG" --jq .sha)
if [ -z "$tagged" ] || [ "$built" != "$tagged" ]; then
  echo "install.sh was built from $built, but $TAG is $tagged" >&2
  exit 1
fi
echo "install.sh is from $TAG"
```

`--source-uri` alone proves the asset was built by this repository's release workflow, not which release it belongs to; the commit check binds it to the tag.

### Releases before provenance

Releases up to 1.1.0 have no provenance. Their assets were signed later with [cosign](https://github.com/sigstore/cosign), from the files as published, by a one-off `sign-release-assets.yml` workflow (run once on 2026-11-11, then removed); each signature is attached next to its file as `<file>.sigstore.json`. The signature says these are the files the project published, not how they were built. To check one:

```bash
gh release download 1.1.0 --repo arc53/DocsGPT --pattern install.sh --pattern install.sh.sigstore.json
cosign verify-blob \
  --bundle install.sh.sigstore.json \
  --certificate-identity https://github.com/arc53/DocsGPT/.github/workflows/sign-release-assets.yml@refs/heads/main \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  install.sh
```

Like `--source-uri` above, the signature covers the file's contents, not which release it is attached to.

