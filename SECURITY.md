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
TAG=1.2.0  # the release to check
gh release download "$TAG" --repo arc53/DocsGPT --pattern install.sh --pattern docsgpt.intoto.jsonl
slsa-verifier verify-artifact install.sh \
  --provenance-path docsgpt.intoto.jsonl \
  --source-uri github.com/arc53/DocsGPT \
  --print-provenance > provenance.json
# The provenance must name the commit the release tag points at.
built=$(jq -r '.predicate.invocation.configSource.digest.sha1' provenance.json)
tagged=$(gh api "repos/arc53/DocsGPT/commits/$TAG" --jq .sha)
[ "$built" = "$tagged" ] && echo "install.sh is from $TAG" || echo "install.sh is NOT from $TAG"
```

`--source-uri` alone proves the asset was built by this repository's release workflow, not which release it belongs to; the commit check binds it to `$TAG`.

