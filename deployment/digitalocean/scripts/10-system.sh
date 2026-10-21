#!/bin/bash
# The system around DocsGPT: patches, Docker, the firewall, fail2ban and unattended upgrades.
set -euo pipefail

apt_opts=(-qqy -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold)
apt-get -qq update
apt-get "${apt_opts[@]}" full-upgrade
apt-get "${apt_opts[@]}" install ca-certificates curl gnupg jq ufw fail2ban unattended-upgrades

# Docker Engine and the Compose plugin from Docker's own repository (Ubuntu's docker.io
# lags behind and has no compose plugin).
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
# shellcheck disable=SC1091
codename="$(. /etc/os-release && echo "$VERSION_CODENAME")"
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $codename stable" \
  >/etc/apt/sources.list.d/docker.list
apt-get -qq update
apt-get "${apt_opts[@]}" install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable docker

# Only SSH and Caddy's ports are open. The backend publishes on 127.0.0.1 only, and Postgres,
# Redis and Keycloak publish nothing: Docker's published ports bypass ufw, so the Compose file
# keeps them off the public interface rather than relying on the firewall.
ufw default deny incoming
ufw default allow outgoing
ufw limit ssh
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp
ufw --force enable

# fail2ban's sshd jail is on by default on Ubuntu; make sure the service starts at boot.
systemctl enable fail2ban

# Security updates install by themselves; Docker's packages are left to `apt upgrade`.
cat >/etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF
systemctl enable unattended-upgrades

# The per-instance script sets DocsGPT up on the first boot; until it has, a root login
# would find nothing ready, so SSH says so instead (001_onboot removes this block).
cat >>/etc/ssh/sshd_config <<'EOF'
Match User root
        ForceCommand echo "Please wait while we get your droplet ready..."
EOF

chmod 0755 /var/lib/cloud/scripts/per-instance/001_onboot /etc/update-motd.d/99-docsgpt \
  /usr/local/lib/docsgpt/first-login

# The optional setup questions (a domain, user accounts) on root's first interactive login;
# first-login removes this line once they are answered.
echo '[ -x /usr/local/lib/docsgpt/first-login ] && /usr/local/lib/docsgpt/first-login  # docsgpt-first-login' \
  >>/root/.bashrc
