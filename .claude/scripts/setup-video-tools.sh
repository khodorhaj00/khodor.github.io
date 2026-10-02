#!/bin/bash
# Installs the Agent-Reach toolchain (github.com/Panniantong/Agent-Reach):
# yt-dlp + agent-reach CLI + its Claude Code skill (16 internet channels).
# Idempotent — skips anything already installed, so re-runs are cheap.
set -uo pipefail

VENV="$HOME/.agent-reach-venv"
SRC="$HOME/.agent-reach-src"
BIN="$HOME/.local/bin"

mkdir -p "$BIN"

if [ ! -x "$VENV/bin/agent-reach" ]; then
  python3 -m venv "$VENV"
  # pip cannot fetch GitHub archive zips through the egress proxy (403),
  # but anonymous git clones of public repos are served — install from a clone.
  if [ ! -d "$SRC/.git" ]; then
    GIT_LFS_SKIP_SMUDGE=1 git clone --depth 1 \
      https://github.com/Panniantong/agent-reach "$SRC"
  fi
  "$VENV/bin/pip" install -q --disable-pip-version-check "$SRC" yt-dlp
fi

ln -sf "$VENV/bin/agent-reach" "$BIN/agent-reach"
ln -sf "$VENV/bin/yt-dlp" "$BIN/yt-dlp"

# yt-dlp needs a JS runtime to solve YouTube player signatures
mkdir -p "$HOME/.config/yt-dlp"
grep -qxF -- '--js-runtimes node' "$HOME/.config/yt-dlp/config" 2>/dev/null ||
  printf '%s\n' '--js-runtimes node' >> "$HOME/.config/yt-dlp/config"

# Register the agent-reach skill into ~/.claude/skills and activate
# zero-config channels (web reader, RSS, YouTube, GitHub, Exa via mcporter).
if [ ! -f "$HOME/.claude/skills/agent-reach/SKILL.md" ]; then
  PATH="$BIN:$PATH" "$VENV/bin/agent-reach" install --env=auto --system || true
fi

echo "video tools: yt-dlp $("$BIN/yt-dlp" --version 2>/dev/null || echo MISSING), agent-reach $("$BIN/agent-reach" --version 2>/dev/null || echo ok)"
