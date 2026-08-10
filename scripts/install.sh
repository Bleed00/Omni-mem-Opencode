#!/usr/bin/env bash
# install.sh - installs and wires up Omni-mem-Opencode on this PC.
#
# Omni-mem-Opencode is a WRAPPER: it only contains code/instructions. The data
# (sessions, observations, summaries, prompts) lives in a separate DATA REPO on
# GitHub, whose local clone sits in data/ inside this wrapper.
#
# Flow:
#   1. verify prerequisites (opencode, claude-mem, running worker, gh, git...)
#   2. choose the data repo: CREATE a new one (via gh) or ATTACH an existing one
#   3. clone the data repo into $REPO_ROOT/data
#   4. (optional) periodic auto-push with a user-chosen interval
#   5. symlink omni-push / omni-pull in ~/.local/bin
set -euo pipefail

source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/lib.sh"

BIN_DIR="${HOME}/.local/bin"
GITHUB_USER="$(gh api user -q .login 2>/dev/null || true)"

say()  { echo -e "  $*"; }
info() { echo -e "\n==> $*"; }
fail() { echo -e "\nERROR: $*" >&2; exit 1; }

##############################################################################
# STEP 1 - prerequisites
##############################################################################
info "Omni-mem-Opencode - setup (repo: ${REPO_ROOT})"

info "STEP 1 - checking prerequisites"

# git
command -v git >/dev/null 2>&1 || fail "'git' not found. Install git and try again."
say "git OK"

# python3 + curl
command -v python3 >/dev/null 2>&1 || fail "'python3' not found."
say "python3 OK"
command -v curl >/dev/null 2>&1 || fail "'curl' not found."
say "curl OK"

# gh (needed to create the data repo)
command -v gh >/dev/null 2>&1 || fail "'gh' not found. Install GitHub CLI: https://cli.github.com"
gh auth status >/dev/null 2>&1 || fail "'gh' is not authenticated. Run: gh auth login"
[ -n "$GITHUB_USER" ] || fail "unable to determine your GitHub username."
say "gh OK (${GITHUB_USER})"

# opencode
if command -v opencode >/dev/null 2>&1; then
  say "opencode OK ($(opencode --version 2>/dev/null || echo 'installed'))"
elif [ -d "${HOME}/.config/opencode" ] || [ -d "${HOME}/.opencode" ]; then
  say "opencode OK (detected via config/install dir)"
else
  fail "'opencode' not found. Install opencode and try again."
fi

# claude-mem opencode plugin
if [ -f "${HOME}/.config/opencode/plugins/claude-mem.js" ]; then
  say "claude-mem opencode plugin OK"
else
  fail "claude-mem opencode plugin not found (~/.config/opencode/plugins/claude-mem.js)."
fi

# running claude-mem worker
if ! require_worker >/dev/null 2>&1; then
  fail "claude-mem worker unreachable. Start opencode or run: npx claude-mem start"
fi
say "claude-mem worker OK ($(worker_base))"

##############################################################################
# STEP 2 - data repo: new or existing
##############################################################################
info "STEP 2 - data repo (separate from the wrapper, private)"

while true; do
  read -r -p "  Create a NEW data repo or attach an EXISTING one? [new/existing] " choice
  case "${choice,,}" in
    new|n)
      while true; do
        read -r -p "  Name of the new data repo (private): " repo_name
        [ -n "$repo_name" ] && break
      done
      gh repo create "${GITHUB_USER}/${repo_name}" --private \
        --description "Memory data for Omni-mem-Opencode" >/dev/null \
        || fail "failed to create repo ${GITHUB_USER}/${repo_name}."
      repo_url="https://github.com/${GITHUB_USER}/${repo_name}.git"
      say "created: ${repo_url}"
      break
      ;;
    existing|e|use)
      while true; do
        read -r -p "  URL of the existing data repo: " repo_url
        [ -n "$repo_url" ] && break
      done
      if ! git ls-remote "$repo_url" >/dev/null 2>&1; then
        fail "repo unreachable: ${repo_url}"
      fi
      say "verified: ${repo_url}"
      break
      ;;
    *) say "answer with 'new' or 'existing'." ;;
  esac
done

##############################################################################
# STEP 3 - local clone into data/
##############################################################################
info "STEP 3 - local clone of the data repo into data/"

mkdir -p "$REPO_ROOT"
if [ -d "$DATA_DIR/.git" ]; then
  say "clone already present: ${DATA_DIR} (running git pull)"
  git -C "$DATA_DIR" pull --rebase --quiet origin main || say "pull failed, continuing with current state."
else
  git clone "$repo_url" "$DATA_DIR" || fail "failed to clone the data repo."
  say "cloned into: ${DATA_DIR}"
fi

##############################################################################
# STEP 4 - periodic auto-push (optional)
##############################################################################
info "STEP 4 - periodic auto-push (optional)"

timer_installed=0
while true; do
  read -r -p "  Enable periodic automatic push? [y/n] " yn
  case "${yn,,}" in
    y|yes)
      while true; do
        read -r -p "  Interval (e.g. 30m, 1h, 2h, 12h): " interval
        if [[ "$interval" =~ ^[0-9]+(m|h|d)$ ]]; then break; fi
        say "invalid interval. Use a format like 30m, 1h, 2h, 12h."
      done
      UNIT_DIR="${XDG_CONFIG_HOME:-${HOME}/.config}/systemd/user"
      mkdir -p "$UNIT_DIR"
      cat > "${UNIT_DIR}/omni-mem-push.service" <<EOF
[Unit]
Description=Omni-mem: export claude-mem memory to the data repo

[Service]
Type=oneshot
ExecStart=${BIN_DIR}/omni-push
EOF
      cat > "${UNIT_DIR}/omni-mem-push.timer" <<EOF
[Unit]
Description=Omni-mem: periodic memory push

[Timer]
OnBootSec=5min
OnUnitActiveSec=${interval}
Persistent=true

[Install]
WantedBy=timers.target
EOF
      systemctl --user daemon-reload
      systemctl --user enable --now omni-mem-push.timer
      say "timer enabled: omni-mem-push.timer (every ${interval})"
      timer_installed=1
      break
      ;;
    n|no)
      say "auto-push disabled."
      break
      ;;
    *) say "answer with y or n." ;;
  esac
done

##############################################################################
# STEP 5 - omni-push / omni-pull commands
##############################################################################
info "STEP 5 - wiring up commands"

mkdir -p "$BIN_DIR"
ln -sf "${REPO_ROOT}/scripts/push.sh" "${BIN_DIR}/omni-push"
ln -sf "${REPO_ROOT}/scripts/pull.sh" "${BIN_DIR}/omni-pull"
say "${BIN_DIR}/omni-push   (local export -> data repo)"
say "${BIN_DIR}/omni-pull   (data repo -> local import)"

info "Installation complete."
say "  omni-pull   imports the memory from the data repo"
say "  omni-push   exports this PC's memory to the data repo"
[ "$timer_installed" -eq 1 ] && say "  auto-push active (omni-mem-push.timer)"
