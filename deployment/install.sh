#!/usr/bin/env bash
# DocsGPT installer for macOS and Linux.
#
#   curl -fsSL https://docs.ac/install | bash
#
# Installs uv when it is missing or too old, installs the `docsgpt` Python
# package with it, then runs `docsgpt up`, which sets up DocsGPT on Docker and
# starts it. Running it again upgrades the package and keeps your settings.
# Arguments go to `docsgpt up` (see `docsgpt up --help`):
#
#   curl -fsSL https://docs.ac/install | bash -s -- --domain docs.example.com --yes
#
# Environment:
#   DOCSGPT_VERSION         package version to install (default: the latest release)
#   DOCSGPT_PACKAGE         install this instead of docsgpt from PyPI (a wheel path or URL)
#   DOCSGPT_NO_MODIFY_PATH  set to 1 to leave shell profiles alone
#   DOCSGPT_INSTALL_DOCKER  set to 1 to install Docker on Linux without asking
#
# Everything runs inside main(), so a download cut short runs nothing.

UV_VERSION="0.12.15"
UV_MIN_VERSION="0.8.0"

main() {
  set -euo pipefail

  local bold="" red="" reset=""
  if [ -t 2 ]; then
    bold=$'\033[1m' red=$'\033[31m' reset=$'\033[0m'
  fi
  say() { printf '%s==>%s %s\n' "$bold" "$reset" "$*" >&2; }
  die() { printf '%serror:%s %s\n' "$red" "$reset" "$*" >&2; exit 1; }
  has() { command -v "$1" >/dev/null 2>&1; }
  have_tty() { (exec </dev/tty) 2>/dev/null; }
  ask_yes() {
    local answer
    printf '%s [y/N] ' "$1" >/dev/tty
    read -r answer </dev/tty || return 1
    case "$answer" in y | Y | yes | YES) return 0 ;; *) return 1 ;; esac
  }
  download() {
    if has curl; then
      curl -fsSL --retry 3 "$1"
    elif has wget; then
      wget -qO- "$1"
    else
      die "curl or wget is needed to download $1"
    fi
  }
  # version_ge A B: A >= B for dotted version numbers.
  version_ge() {
    local -a left right
    IFS=. read -r -a left <<<"$1"
    IFS=. read -r -a right <<<"$2"
    local i x y
    for i in 0 1 2; do
      x="${left[i]:-0}" y="${right[i]:-0}"
      x="${x%%[!0-9]*}" y="${y%%[!0-9]*}"
      if (( 10#${x:-0} > 10#${y:-0} )); then return 0; fi
      if (( 10#${x:-0} < 10#${y:-0} )); then return 1; fi
    done
    return 0
  }

  local os
  os="$(uname -s)"
  case "$os" in
    Linux | Darwin) ;;
    *) die "this installer is for macOS and Linux. On Windows, in PowerShell: irm https://docs.ac/install.ps1 | iex" ;;
  esac

  # Docker first: without it nothing below is useful.
  local docker_group_pending=0
  if ! has docker; then
    if [ "$os" = Darwin ]; then
      die "DocsGPT runs on Docker. Install Docker Desktop (https://docs.docker.com/desktop/setup/install/mac-install/) or OrbStack (https://orbstack.dev), start it, and run this again."
    fi
    if [ "${DOCSGPT_INSTALL_DOCKER:-}" = 1 ] || { have_tty && ask_yes "Docker is not installed. Install it now with Docker's script from get.docker.com?"; }; then
      local sudo=""
      if [ "$(id -u)" -ne 0 ]; then
        has sudo || die "installing Docker needs root. Install it (https://docs.docker.com/engine/install/) and run this again."
        sudo="sudo"
      fi
      say "Installing Docker"
      download https://get.docker.com | $sudo sh
      $sudo systemctl enable --now docker >/dev/null 2>&1 || true
      if [ -n "$sudo" ]; then
        $sudo usermod -aG docker "$(id -un)"
        docker_group_pending=1
      fi
    else
      die "DocsGPT runs on Docker. Install it (https://docs.docker.com/engine/install/) and run this again."
    fi
  fi

  # uv installs and upgrades the package, and brings Python 3.12 when the system has none.
  local uv="" candidate found
  for candidate in "$(command -v uv 2>/dev/null || true)" "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv"; do
    [ -n "$candidate" ] && [ -x "$candidate" ] || continue
    found="$("$candidate" --version 2>/dev/null | awk '{print $2}')" || continue
    if [ -n "$found" ] && version_ge "$found" "$UV_MIN_VERSION"; then
      uv="$candidate"
      break
    fi
  done
  if [ -z "$uv" ]; then
    local uv_dir="${XDG_BIN_HOME:-$HOME/.local/bin}"
    say "Installing uv $UV_VERSION into $uv_dir"
    download "https://astral.sh/uv/$UV_VERSION/install.sh" | env UV_INSTALL_DIR="$uv_dir" UV_NO_MODIFY_PATH=1 UV_PRINT_QUIET=1 sh
    uv="$uv_dir/uv"
    [ -x "$uv" ] || die "uv did not install into $uv_dir"
  fi

  if [ -n "${DOCSGPT_VERSION:-}" ] && [ -n "${DOCSGPT_PACKAGE:-}" ]; then
    die "set DOCSGPT_VERSION or DOCSGPT_PACKAGE, not both"
  fi
  if [ -n "${DOCSGPT_PACKAGE:-}" ]; then
    say "Installing docsgpt from $DOCSGPT_PACKAGE"
    "$uv" tool install --reinstall --python 3.12 "$DOCSGPT_PACKAGE"
  elif [ -n "${DOCSGPT_VERSION:-}" ]; then
    say "Installing docsgpt $DOCSGPT_VERSION"
    "$uv" tool install --force --python 3.12 "docsgpt==$DOCSGPT_VERSION"
  else
    say "Installing the latest docsgpt"
    "$uv" tool install --upgrade --python 3.12 docsgpt
  fi

  local bin_dir docsgpt
  bin_dir="$("$uv" tool dir --bin)"
  docsgpt="$bin_dir/docsgpt"
  [ -x "$docsgpt" ] || die "the docsgpt command is missing from $bin_dir"
  case ":$PATH:" in
    *":$bin_dir:"*) ;;
    *)
      if [ "${DOCSGPT_NO_MODIFY_PATH:-}" = 1 ]; then
        say "Add $bin_dir to PATH to run docsgpt from a new terminal"
      else
        "$uv" tool update-shell >/dev/null 2>&1 || true
        say "Added $bin_dir to PATH for new terminals"
      fi
      ;;
  esac

  if [ "$docker_group_pending" = 1 ]; then
    if has sg; then
      # The docker group applies to new logins; sg gives it to this command now.
      local command
      command="$(printf '%q ' "$docsgpt" up "$@")"
      if have_tty; then
        exec sg docker -c "$command </dev/tty"
      fi
      exec sg docker -c "$command --yes"
    fi
    say "Docker is installed and your user joined the docker group. Log out and back in, then run: docsgpt up"
    exit 0
  fi

  # Hand the terminal to docsgpt up: when this script is piped into bash, its
  # standard input is the script, not the keyboard.
  if [ -t 0 ]; then
    exec "$docsgpt" up "$@"
  fi
  if have_tty; then
    exec "$docsgpt" up "$@" </dev/tty
  fi
  exec "$docsgpt" up --yes "$@"
}

main "$@"
