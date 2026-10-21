#!/bin/bash
# The docsgpt command and the images its stack runs. Nothing here is per-Droplet: secrets,
# the address and the database are made on the first boot (001_onboot).
#
# Environment: DOCSGPT_VERSION (the release), DOCSGPT_IMAGE_TAG (images to pull) and
# DOCSGPT_FROM_WHEEL (the uploaded wheel's file name when testing a branch, else empty).
set -euo pipefail

# The same pinned uv as deployment/install.sh, checked the same way.
UV_VERSION="0.12.15"
UV_INSTALLER_SHA256="716a1d6844740756c68770fcec2f79c2013fb9b03869a113f61e15f6f482a6a1"

# Where the uv tool, its Python and the stack live. /etc/environment carries these to root's
# login shells, so `docsgpt upgrade` installs into the same place later; 001_onboot and the
# login message read them from there too.
cat >>/etc/environment <<'EOF'
DOCSGPT_HOME=/opt/docsgpt
UV_TOOL_DIR=/opt/docsgpt-cli/tools
UV_TOOL_BIN_DIR=/usr/local/bin
UV_PYTHON_INSTALL_DIR=/opt/docsgpt-cli/python
EOF
set -a
# shellcheck disable=SC1091
. /etc/environment
set +a

installer="$(mktemp)"
curl -fsSL --retry 3 "https://astral.sh/uv/$UV_VERSION/install.sh" -o "$installer"
echo "$UV_INSTALLER_SHA256  $installer" | sha256sum -c -
UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh "$installer"
rm -f "$installer"

if [ -n "${DOCSGPT_FROM_WHEEL:-}" ]; then
  # A wheel keeps its file name, which uv needs to read the version from.
  package="/root/$DOCSGPT_FROM_WHEEL"
  mv /root/docsgpt-package "$package"
else
  package="docsgpt==$DOCSGPT_VERSION"
  rm -f /root/docsgpt-package
fi
uv tool install --python 3.12 "$package"
rm -f /root/*.whl
installed="$(docsgpt --version | awk '{print $2}')"
if [ "$installed" != "$DOCSGPT_VERSION" ]; then
  echo "installed docsgpt $installed, expected $DOCSGPT_VERSION" >&2
  exit 1
fi

# Pull every image the stack can run, the accounts profile included, so the first boot and
# `docsgpt up --accounts` start without a download. The Compose file is the one this
# version of the package runs.
compose="$("$(uv tool dir)/docsgpt/bin/python" -c 'from docsgpt.deploy import stack; print(stack.compose_source())')"
DOCSGPT_IMAGE_TAG="$DOCSGPT_IMAGE_TAG" DOCSGPT_DOMAIN=localhost \
  docker compose -f "$compose" --profile https --profile accounts config --images | sort -u | while read -r image; do
  docker pull -q "$image"
done

install -d -m 0700 /opt/docsgpt
install -d /var/lib/digitalocean
cat >/var/lib/digitalocean/application.info <<EOF
application_name="DocsGPT"
build_date="$(date +%Y-%m-%d)"
distro="Ubuntu 24.04"
application_version="$DOCSGPT_VERSION"
EOF
